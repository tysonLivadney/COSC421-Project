"""Download UBC Okanagan Academic Calendar course-description pages."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
SUBJECT_PATH_PREFIX = "/course-descriptions/subject/"


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    final_url: str
    status: int
    headers: dict[str, str]


@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    slug: str
    url: str


class SubjectIndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.base_host = urlsplit(base_url).netloc
        self.subjects: list[Subject] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        href = dict(attributes).get("href")
        if not href:
            return
        url = urljoin(self.base_url, href)
        parts = urlsplit(url)
        if parts.netloc == self.base_host and parts.path.startswith(
            SUBJECT_PATH_PREFIX
        ):
            self._href = url
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return

        label = " ".join("".join(self._text).split())
        match = re.fullmatch(r"([A-Z]+_O)\s+-\s+(.+)", label)
        path = urlsplit(self._href).path.rstrip("/")
        slug = path.rsplit("/", 1)[-1]
        if match and slug:
            self.subjects.append(
                Subject(
                    code=match.group(1),
                    name=match.group(2),
                    slug=slug,
                    url=self._href,
                )
            )
        self._href = None
        self._text = []


class CourseCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        if tag != "article":
            return
        classes = (dict(attributes).get("class") or "").split()
        if "node--type-course" in classes:
            self.count += 1


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    collection = config.get("academic_calendar_collection")
    if not isinstance(collection, dict):
        raise ValueError("Configuration is missing 'academic_calendar_collection'")
    return collection


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def fetch(url: str, *, timeout: int, user_agent: str) -> HttpResponse:
    request = Request(
        url,
        headers={"Accept": "text/html", "User-Agent": user_agent},
    )
    with urlopen(request, timeout=timeout) as response:
        return HttpResponse(
            body=response.read(),
            final_url=response.geturl(),
            status=response.status,
            headers=dict(response.headers.items()),
        )


def fetch_with_retries(
    url: str,
    *,
    timeout: int,
    user_agent: str,
    retry_attempts: int,
    retry_delay: float,
    downloader: Callable[..., HttpResponse],
    progress: Callable[[str], None],
) -> HttpResponse:
    if retry_attempts < 1:
        raise ValueError("retry_attempts must be at least 1")

    for attempt in range(1, retry_attempts + 1):
        try:
            return downloader(url, timeout=timeout, user_agent=user_agent)
        except (OSError, http.client.HTTPException):
            if attempt == retry_attempts:
                raise
            progress(f"Request failed; retrying ({attempt + 1}/{retry_attempts})")
            time.sleep(retry_delay)
    raise RuntimeError("Unreachable retry state")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parse_subjects(body: bytes, base_url: str) -> list[Subject]:
    parser = SubjectIndexParser(base_url)
    parser.feed(body.decode("utf-8"))
    unique: dict[str, Subject] = {}
    for subject in parser.subjects:
        unique.setdefault(subject.slug, subject)
    return list(unique.values())


def count_courses(body: bytes) -> int:
    parser = CourseCounter()
    parser.feed(body.decode("utf-8"))
    return parser.count


def relative_file(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def response_record(
    request_url: str, response: HttpResponse, path: Path
) -> dict[str, Any]:
    return {
        "request_url": request_url,
        "response_url": response.final_url,
        "status": response.status,
        "response_headers": response.headers,
        "sha256": hashlib.sha256(response.body).hexdigest(),
        "file": relative_file(path),
    }


def select_subjects(
    subjects: list[Subject], selected_subjects: list[str] | None
) -> list[Subject]:
    if not selected_subjects:
        return subjects

    requested = {value.casefold() for value in selected_subjects}
    selected = [
        subject
        for subject in subjects
        if subject.slug.casefold() in requested or subject.code.casefold() in requested
    ]
    found = {
        value
        for subject in selected
        for value in (subject.slug.casefold(), subject.code.casefold())
    }
    unknown = sorted(requested.difference(found))
    if unknown:
        raise ValueError(f"Unknown subject(s): {', '.join(unknown)}")
    return selected


def collect(
    settings: dict[str, Any],
    *,
    selected_subjects: list[str] | None = None,
    collected_at: datetime | None = None,
    downloader: Callable[..., HttpResponse] = fetch,
    progress: Callable[[str], None] = print,
) -> Path:
    base_url = settings["base_url"]
    index_url = urljoin(base_url.rstrip("/") + "/", settings["subject_index_path"])
    timeout = int(settings.get("timeout_seconds", 30))
    retry_attempts = int(settings.get("retry_attempts", 3))
    retry_delay = float(settings.get("retry_delay_seconds", 2))
    request_delay = float(settings.get("request_delay_seconds", 10))
    max_subjects = int(settings.get("max_subjects", 200))
    user_agent = settings.get("user_agent", "COSC421-Project/0.1")
    if request_delay < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    retry_delay = max(retry_delay, request_delay)

    timestamp = collected_at or datetime.now(timezone.utc)
    run_name = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_directory = resolve_project_path(settings["raw_directory"]) / run_name

    progress("[academic_calendar] downloading subject index")
    index_response = fetch_with_retries(
        index_url,
        timeout=timeout,
        user_agent=user_agent,
        retry_attempts=retry_attempts,
        retry_delay=retry_delay,
        downloader=downloader,
        progress=progress,
    )
    index_path = run_directory / "subject_index.html"
    atomic_write(index_path, index_response.body)

    discovered_subjects = parse_subjects(index_response.body, base_url)
    if not discovered_subjects:
        raise ValueError("No subject links found on the Calendar index")
    if len(discovered_subjects) > max_subjects:
        raise RuntimeError(
            "Calendar index contains "
            f"{len(discovered_subjects)} subjects; limit is {max_subjects}"
        )
    subjects = select_subjects(discovered_subjects, selected_subjects)

    subject_records: list[dict[str, Any]] = []
    for position, subject in enumerate(subjects, start=1):
        if request_delay > 0:
            time.sleep(request_delay)
        progress(
            f"[{subject.code}] downloading subject {position}/{len(subjects)}"
        )
        response = fetch_with_retries(
            subject.url,
            timeout=timeout,
            user_agent=user_agent,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
            downloader=downloader,
            progress=progress,
        )
        subject_path = run_directory / "subjects" / f"{subject.slug}.html"
        atomic_write(subject_path, response.body)
        subject_records.append(
            {
                "code": subject.code,
                "name": subject.name,
                "slug": subject.slug,
                "course_count": count_courses(response.body),
                **response_record(subject.url, response, subject_path),
            }
        )

    manifest = {
        "collected_at": timestamp.astimezone(timezone.utc).isoformat(),
        "base_url": base_url,
        "discovered_subject_count": len(discovered_subjects),
        "collected_subject_count": len(subject_records),
        "subject_index": response_record(index_url, index_response, index_path),
        "subjects": subject_records,
    }
    atomic_write(
        run_directory / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        ),
    )
    return run_directory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--subject",
        action="append",
        dest="subjects",
        help="Subject slug or code; repeat to collect more than one (default: all)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = collect(
        load_config(args.config.resolve()), selected_subjects=args.subjects
    )
    print(f"Saved raw Calendar pages to {output}")


if __name__ == "__main__":
    main()
