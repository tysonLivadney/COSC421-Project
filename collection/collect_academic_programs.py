"""Download UBC Okanagan undergraduate program pages from the Academic Calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

try:
    from . import collect_academic_calendar as common
except ImportError:  # Allows `python collection/collect_academic_programs.py`.
    import collect_academic_calendar as common


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")


@dataclass(frozen=True)
class Program:
    program_id: str
    name: str
    faculty: str
    level: str
    url: str


@dataclass(frozen=True)
class RelatedPage:
    title: str
    slug: str
    url: str


class ProgramIndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.base_host = urlsplit(base_url).netloc
        self.programs: list[Program] = []
        self._in_row = False
        self._cell_depth = 0
        self._cells: list[list[str]] = []
        self._href: str | None = None

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._href = None
        elif self._in_row and tag == "td":
            self._cell_depth += 1
            self._cells.append([])
        elif self._in_row and self._cell_depth and tag == "a" and self._href is None:
            href = dict(attributes).get("href")
            if href:
                url = urljoin(self.base_url, href)
                if urlsplit(url).netloc == self.base_host:
                    self._href = url

    def handle_data(self, data: str) -> None:
        if self._in_row and self._cell_depth and self._cells:
            self._cells[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell_depth:
            self._cell_depth -= 1
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False

    def _finish_row(self) -> None:
        cells = [" ".join("".join(cell).split()) for cell in self._cells]
        if len(cells) < 3 or not self._href:
            return
        name, faculty, level = cells[:3]
        path = urlsplit(self._href).path.rstrip("/")
        program_id = path.rsplit("/", 1)[-1]
        if name and faculty and level and program_id:
            self.programs.append(
                Program(program_id, name, faculty, level, self._href)
            )


class RelatedPageParser(HTMLParser):
    def __init__(self, page_url: str, title_patterns: list[str]) -> None:
        super().__init__()
        self.page_url = page_url
        parts = urlsplit(page_url)
        self.host = parts.netloc
        self.path_prefix = parts.path.rstrip("/") + "/"
        self.title_patterns = [pattern.casefold() for pattern in title_patterns]
        self.pages: list[RelatedPage] = []
        self._url: str | None = None
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        href = dict(attributes).get("href")
        if not href:
            return
        url = urljoin(self.page_url, href)
        parts = urlsplit(url)
        if parts.netloc == self.host and parts.path.startswith(self.path_prefix):
            self._url = parts._replace(query="", fragment="").geturl()
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._url is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._url is None:
            return
        title = " ".join("".join(self._parts).split())
        if title and any(pattern in title.casefold() for pattern in self.title_patterns):
            slug = urlsplit(self._url).path.rstrip("/").rsplit("/", 1)[-1]
            if slug:
                self.pages.append(RelatedPage(title, slug, self._url))
        self._url = None
        self._parts = []


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    collection = config.get("academic_program_collection")
    if not isinstance(collection, dict):
        raise ValueError("Configuration is missing 'academic_program_collection'")
    return collection


def parse_programs(body: bytes, base_url: str) -> list[Program]:
    parser = ProgramIndexParser(base_url)
    parser.feed(body.decode("utf-8"))
    unique: dict[str, Program] = {}
    for program in parser.programs:
        unique.setdefault(program.program_id, program)
    return list(unique.values())


def parse_related_pages(
    body: bytes, page_url: str, title_patterns: list[str]
) -> list[RelatedPage]:
    parser = RelatedPageParser(page_url, title_patterns)
    parser.feed(body.decode("utf-8"))
    unique: dict[str, RelatedPage] = {}
    for page in parser.pages:
        unique.setdefault(page.url, page)
    return list(unique.values())


def select_programs(
    programs: list[Program], level: str, selected_programs: list[str] | None
) -> list[Program]:
    matching_level = [p for p in programs if p.level.casefold() == level.casefold()]
    if not selected_programs:
        return matching_level

    requested = {value.casefold() for value in selected_programs}
    selected = [
        p
        for p in matching_level
        if p.program_id.casefold() in requested or p.name.casefold() in requested
    ]
    found = {
        value
        for program in selected
        for value in (program.program_id.casefold(), program.name.casefold())
    }
    unknown = sorted(requested.difference(found))
    if unknown:
        raise ValueError(f"Unknown program(s): {', '.join(unknown)}")
    return selected


def safe_file_name(program_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", program_id).strip("-")
    if not value:
        raise ValueError(f"Invalid program id: {program_id!r}")
    return f"{value}.html"


def response_record(
    request_url: str, response: common.HttpResponse, path: Path
) -> dict[str, Any]:
    return {
        "request_url": request_url,
        "response_url": response.final_url,
        "status": response.status,
        "response_headers": response.headers,
        "sha256": hashlib.sha256(response.body).hexdigest(),
        "file": common.relative_file(path),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest.get("programs"), list):
        raise ValueError(f"Invalid Academic Programs manifest: {path}")
    return manifest


def eligible_count(manifest: dict[str, Any]) -> int:
    recorded = manifest.get("eligible_program_count")
    if isinstance(recorded, int):
        return recorded
    index_path = common.resolve_project_path(manifest["program_index"]["file"])
    discovered = parse_programs(index_path.read_bytes(), manifest["base_url"])
    return len(select_programs(discovered, manifest.get("level", "Undergraduate"), None))


def find_complete_run(
    settings: dict[str, Any], run_directory: Path | None = None
) -> Path:
    if run_directory is not None:
        selected = run_directory.resolve()
        manifest = load_manifest(selected / "manifest.json")
        if manifest.get("collected_program_count") != eligible_count(manifest):
            raise ValueError(f"Academic Programs collection is incomplete: {selected}")
        return selected

    raw_directory = common.resolve_project_path(settings["raw_directory"])
    complete: list[Path] = []
    for manifest_path in raw_directory.glob("*/manifest.json"):
        manifest = load_manifest(manifest_path)
        if manifest.get("collected_program_count") == eligible_count(manifest):
            complete.append(manifest_path.parent)
    if not complete:
        raise FileNotFoundError(
            f"No complete Academic Programs collection found in {raw_directory}"
        )
    return sorted(complete)[-1]


def select_program_records(
    programs: list[dict[str, Any]], selected_programs: list[str] | None
) -> list[dict[str, Any]]:
    if not selected_programs:
        return programs
    requested = {value.casefold() for value in selected_programs}
    selected = [
        program
        for program in programs
        if str(program["program_id"]).casefold() in requested
        or program["name"].casefold() in requested
    ]
    found = {
        value
        for program in selected
        for value in (
            str(program["program_id"]).casefold(),
            program["name"].casefold(),
        )
    }
    unknown = sorted(requested.difference(found))
    if unknown:
        raise ValueError(f"Unknown program(s): {', '.join(unknown)}")
    return selected


def related_settings(settings: dict[str, Any]) -> tuple[int, list[str]]:
    maximum = int(settings.get("max_related_pages_per_program", 20))
    patterns = settings.get(
        "related_page_title_patterns",
        ["degree requirements", "diploma requirements", "program requirements"],
    )
    if not isinstance(patterns, list) or not all(
        isinstance(value, str) for value in patterns
    ):
        raise ValueError("related_page_title_patterns must be a list of strings")
    return maximum, patterns


def collect_related_only(
    settings: dict[str, Any],
    *,
    run_directory: Path | None = None,
    selected_programs: list[str] | None = None,
    downloader: Callable[..., common.HttpResponse] = common.fetch,
    progress: Callable[[str], None] = print,
) -> tuple[Path, int]:
    selected_run = find_complete_run(settings, run_directory)
    manifest_path = selected_run / "manifest.json"
    manifest = load_manifest(manifest_path)
    programs = select_program_records(manifest["programs"], selected_programs)
    timeout = int(settings.get("timeout_seconds", 30))
    retry_attempts = int(settings.get("retry_attempts", 3))
    request_delay = float(settings.get("request_delay_seconds", 10))
    retry_delay = max(float(settings.get("retry_delay_seconds", 10)), request_delay)
    user_agent = settings.get("user_agent", "COSC421-Project/0.1")
    max_related, patterns = related_settings(settings)
    downloaded = 0

    for program in programs:
        body = common.resolve_project_path(program["file"]).read_bytes()
        pages = parse_related_pages(body, program["response_url"], patterns)
        if len(pages) > max_related:
            raise RuntimeError(
                f"{program['name']} has {len(pages)} related requirement pages; "
                f"limit is {max_related}"
            )
        records = program.setdefault("related_pages", [])
        existing = {record["request_url"] for record in records}
        missing = [page for page in pages if page.url not in existing]
        for position, page in enumerate(missing, start=1):
            if request_delay > 0:
                time.sleep(request_delay)
            progress(
                f"[{program['name']}] downloading missing related page "
                f"{position}/{len(missing)}: {page.title}"
            )
            response = common.fetch_with_retries(
                page.url,
                timeout=timeout,
                user_agent=user_agent,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
                downloader=downloader,
                progress=progress,
            )
            path = (
                selected_run
                / "related"
                / Path(safe_file_name(str(program["program_id"]))).stem
                / safe_file_name(page.slug)
            )
            common.atomic_write(path, response.body)
            records.append(
                {
                    "title": page.title,
                    "slug": page.slug,
                    **response_record(page.url, response, path),
                }
            )
            downloaded += 1

    manifest["collected_related_page_count"] = sum(
        len(program.get("related_pages", [])) for program in manifest["programs"]
    )
    common.atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        ),
    )
    return selected_run, downloaded


def collect(
    settings: dict[str, Any],
    *,
    selected_programs: list[str] | None = None,
    collected_at: datetime | None = None,
    downloader: Callable[..., common.HttpResponse] = common.fetch,
    progress: Callable[[str], None] = print,
) -> Path:
    base_url = settings["base_url"]
    index_url = urljoin(base_url.rstrip("/") + "/", settings["program_index_path"])
    level = settings.get("level", "Undergraduate")
    timeout = int(settings.get("timeout_seconds", 30))
    retry_attempts = int(settings.get("retry_attempts", 3))
    retry_delay = float(settings.get("retry_delay_seconds", 10))
    request_delay = float(settings.get("request_delay_seconds", 10))
    max_programs = int(settings.get("max_programs", 200))
    max_related, related_patterns = related_settings(settings)
    user_agent = settings.get("user_agent", "COSC421-Project/0.1")
    if request_delay < 0:
        raise ValueError("request_delay_seconds cannot be negative")
    retry_delay = max(retry_delay, request_delay)

    timestamp = collected_at or datetime.now(timezone.utc)
    run_name = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    raw_directory = common.resolve_project_path(settings["raw_directory"])
    run_directory = raw_directory / run_name

    progress("[academic_programs] downloading program index")
    index_response = common.fetch_with_retries(
        index_url,
        timeout=timeout,
        user_agent=user_agent,
        retry_attempts=retry_attempts,
        retry_delay=retry_delay,
        downloader=downloader,
        progress=progress,
    )
    index_path = run_directory / "program_index.html"
    common.atomic_write(index_path, index_response.body)

    discovered = parse_programs(index_response.body, base_url)
    if not discovered:
        raise ValueError("No program links found on the Academic Programs index")
    programs = select_programs(discovered, level, selected_programs)
    eligible_program_count = len(select_programs(discovered, level, None))
    if len(programs) > max_programs:
        raise RuntimeError(
            f"Academic Programs index contains {len(programs)} {level} programs; "
            f"limit is {max_programs}"
        )

    records: list[dict[str, Any]] = []
    for position, program in enumerate(programs, start=1):
        if request_delay > 0:
            time.sleep(request_delay)
        progress(
            f"[{program.name}] downloading program {position}/{len(programs)}"
        )
        response = common.fetch_with_retries(
            program.url,
            timeout=timeout,
            user_agent=user_agent,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
            downloader=downloader,
            progress=progress,
        )
        path = run_directory / "programs" / safe_file_name(program.program_id)
        common.atomic_write(path, response.body)
        related_pages = parse_related_pages(
            response.body, response.final_url, related_patterns
        )
        if len(related_pages) > max_related:
            raise RuntimeError(
                f"{program.name} has {len(related_pages)} related requirement pages; "
                f"limit is {max_related}"
            )
        related_records: list[dict[str, Any]] = []
        for related_position, related in enumerate(related_pages, start=1):
            if request_delay > 0:
                time.sleep(request_delay)
            progress(
                f"[{program.name}] downloading related page "
                f"{related_position}/{len(related_pages)}: {related.title}"
            )
            related_response = common.fetch_with_retries(
                related.url,
                timeout=timeout,
                user_agent=user_agent,
                retry_attempts=retry_attempts,
                retry_delay=retry_delay,
                downloader=downloader,
                progress=progress,
            )
            related_path = (
                run_directory
                / "related"
                / Path(safe_file_name(program.program_id)).stem
                / safe_file_name(related.slug)
            )
            common.atomic_write(related_path, related_response.body)
            related_records.append(
                {
                    "title": related.title,
                    "slug": related.slug,
                    **response_record(related.url, related_response, related_path),
                }
            )
        records.append(
            {
                "program_id": program.program_id,
                "name": program.name,
                "faculty": program.faculty,
                "level": program.level,
                "related_pages": related_records,
                **response_record(program.url, response, path),
            }
        )

    manifest = {
        "collected_at": timestamp.astimezone(timezone.utc).isoformat(),
        "base_url": base_url,
        "level": level,
        "discovered_program_count": len(discovered),
        "eligible_program_count": eligible_program_count,
        "collected_program_count": len(records),
        "collected_related_page_count": sum(
            len(program["related_pages"]) for program in records
        ),
        "program_index": response_record(index_url, index_response, index_path),
        "programs": records,
    }
    common.atomic_write(
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
        "--program",
        action="append",
        dest="programs",
        help="Program name or Calendar node id; repeat for more than one (default: all)",
    )
    parser.add_argument(
        "--related-only",
        action="store_true",
        help="Add missing requirement child pages to an existing complete run",
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        help="Run to update with --related-only (default: newest complete run)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_config(args.config.resolve())
    if args.related_only:
        output, downloaded = collect_related_only(
            settings,
            run_directory=args.run_directory,
            selected_programs=args.programs,
        )
        print(f"Added {downloaded} related pages to {output}")
    else:
        if args.run_directory is not None:
            raise ValueError("--run-directory requires --related-only")
        output = collect(settings, selected_programs=args.programs)
        print(f"Saved raw Academic Program pages to {output}")


if __name__ == "__main__":
    main()
