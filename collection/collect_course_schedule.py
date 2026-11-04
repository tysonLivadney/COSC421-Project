"""Download configured datasets from the UBC Course Schedule JSON:API."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    final_url: str
    status: int
    headers: dict[str, str]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    collection = config.get("course_schedule_collection")
    if not isinstance(collection, dict):
        raise ValueError("Configuration is missing 'course_schedule_collection'")
    if not isinstance(collection.get("datasets"), dict):
        raise ValueError("Course Schedule configuration is missing 'datasets'")
    return collection


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def build_url(base_url: str, path: str, query: dict[str, Any]) -> str:
    """Build a URL while preserving any query parameters already in the path."""
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    parts = urlsplit(url)
    parameters = parse_qsl(parts.query, keep_blank_values=True)
    parameters.extend((key, str(value)) for key, value in query.items())
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(parameters), parts.fragment)
    )


def fetch(url: str, *, timeout: int, user_agent: str) -> HttpResponse:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.api+json",
            "User-Agent": user_agent,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return HttpResponse(
            body=response.read(),
            final_url=response.geturl(),
            status=response.status,
            headers=dict(response.headers.items()),
        )


def parse_payload(body: bytes, source_url: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON response from {source_url}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object from {source_url}")
    return payload


def next_page_url(payload: dict[str, Any]) -> str | None:
    links = payload.get("links") or {}
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    if isinstance(next_link, str):
        return next_link
    if isinstance(next_link, dict):
        href = next_link.get("href")
        return href if isinstance(href, str) else None
    return None


def resource_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 1 if isinstance(value, dict) else 0


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


def collect_dataset(
    *,
    name: str,
    dataset: dict[str, Any],
    settings: dict[str, Any],
    run_directory: Path,
    downloader: Callable[..., HttpResponse] = fetch,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    url = build_url(settings["base_url"], dataset["path"], dataset.get("query", {}))
    timeout = int(settings.get("timeout_seconds", 30))
    user_agent = settings.get("user_agent", "COSC421-Project/0.1")
    max_pages = int(settings.get("max_pages_per_dataset", 500))
    retry_attempts = int(settings.get("retry_attempts", 3))
    retry_delay = float(settings.get("retry_delay_seconds", 2))
    dataset_directory = run_directory / name
    pages: list[dict[str, Any]] = []

    page_number = 1
    while url:
        if page_number > max_pages:
            raise RuntimeError(f"Dataset '{name}' exceeded the {max_pages}-page limit")

        progress(f"[{name}] downloading page {page_number}")
        for attempt in range(1, retry_attempts + 1):
            try:
                response = downloader(url, timeout=timeout, user_agent=user_agent)
                break
            except (OSError, http.client.HTTPException) as error:
                if attempt == retry_attempts:
                    raise
                progress(
                    f"[{name}] page {page_number} failed; "
                    f"retrying ({attempt + 1}/{retry_attempts})"
                )
                time.sleep(retry_delay)
        payload = parse_payload(response.body, response.final_url)
        page_path = dataset_directory / f"page_{page_number:04d}.json"
        atomic_write(page_path, response.body)
        try:
            manifest_path = page_path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            manifest_path = page_path.resolve().as_posix()
        pages.append(
            {
                "page": page_number,
                "request_url": url,
                "response_url": response.final_url,
                "status": response.status,
                "response_headers": response.headers,
                "sha256": hashlib.sha256(response.body).hexdigest(),
                "file": manifest_path,
                "primary_resource_count": resource_count(payload.get("data")),
                "included_resource_count": resource_count(payload.get("included")),
            }
        )
        url = next_page_url(payload)
        page_number += 1

    return {"dataset": name, "pages": pages}


def collect(
    settings: dict[str, Any],
    *,
    selected_datasets: list[str] | None = None,
    collected_at: datetime | None = None,
    downloader: Callable[..., HttpResponse] = fetch,
    progress: Callable[[str], None] = print,
) -> Path:
    datasets = settings["datasets"]
    names = selected_datasets or list(datasets)
    unknown = sorted(set(names).difference(datasets))
    if unknown:
        raise ValueError(f"Unknown dataset(s): {', '.join(unknown)}")

    timestamp = collected_at or datetime.now(timezone.utc)
    run_name = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_directory = resolve_project_path(settings["raw_directory"]) / run_name
    manifests = [
        collect_dataset(
            name=name,
            dataset=datasets[name],
            settings=settings,
            run_directory=run_directory,
            downloader=downloader,
            progress=progress,
        )
        for name in names
    ]

    manifest = {
        "collected_at": timestamp.astimezone(timezone.utc).isoformat(),
        "base_url": settings["base_url"],
        "datasets": manifests,
    }
    atomic_write(
        run_directory / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    )
    return run_directory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        help="Dataset name from config.json; repeat to collect more than one.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = collect(
        load_config(args.config.resolve()), selected_datasets=args.datasets
    )
    print(f"Saved raw responses to {output}")


if __name__ == "__main__":
    main()
