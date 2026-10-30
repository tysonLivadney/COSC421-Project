"""Parse saved UBC Okanagan Academic Calendar course pages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
COURSE_HEADING = re.compile(
    r"(?P<subject>[A-Z]+_O)\s+"
    r"(?P<number>[0-9]{3}[A-Z]?)\s+"
    r"\((?P<credits>[^)]+)\)\s+"
    r"(?P<title>.+)"
)
REQUIREMENT_LABEL = re.compile(
    r"(?<![A-Za-z])"
    r"(?P<label>Recommended prerequisites?|Prerequisites?|Corequisites?|"
    r"Equivalency|Recommended)\s*:",
    re.IGNORECASE,
)
CSV_COLUMNS = (
    "course_code",
    "subject_code",
    "subject_name",
    "subject_slug",
    "course_number",
    "credits",
    "credits_min",
    "credits_max",
    "title",
    "academic_unit",
    "description",
    "prerequisite_text",
    "corequisite_text",
    "equivalency_text",
    "recommended_prerequisite_text",
    "recommended_text",
    "calendar_collected_at",
    "source_url",
    "source_file",
)


class SubjectPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.academic_unit_parts: list[str] = []
        self.course_parts: list[tuple[list[str], list[str]]] = []
        self._in_academic_unit = False
        self._in_course = False
        self._in_heading = False
        self._in_description = False
        self._heading_parts: list[str] = []
        self._description_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        classes = (dict(attributes).get("class") or "").split()
        if tag == "h1" and "page-title" in classes:
            self._in_academic_unit = True
        elif tag == "article" and "node--type-course" in classes:
            self._in_course = True
            self._heading_parts = []
            self._description_parts = []
        elif self._in_course and tag == "h3":
            self._in_heading = True
        elif self._in_course and tag == "p":
            self._in_description = True
        elif self._in_description and tag == "br":
            self._description_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_academic_unit = False
        elif tag == "h3":
            self._in_heading = False
        elif tag == "p":
            self._in_description = False
        elif tag == "article" and self._in_course:
            self.course_parts.append(
                (self._heading_parts, self._description_parts)
            )
            self._in_course = False

    def handle_data(self, data: str) -> None:
        if self._in_academic_unit:
            self.academic_unit_parts.append(data)
        if self._in_heading:
            self._heading_parts.append(data)
        if self._in_description:
            self._description_parts.append(data)


def normalize_text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    parsing = config.get("academic_calendar_parsing")
    if not isinstance(parsing, dict):
        raise ValueError("Configuration is missing 'academic_calendar_parsing'")
    return parsing


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest.get("subjects"), list):
        raise ValueError(f"Invalid Calendar manifest: {path}")
    return manifest


def is_complete_manifest(manifest: dict[str, Any]) -> bool:
    discovered = manifest.get("discovered_subject_count")
    collected = manifest.get("collected_subject_count")
    return isinstance(discovered, int) and discovered == collected


def find_run_directory(
    config: dict[str, Any], run_directory: Path | None = None
) -> Path:
    if run_directory is not None:
        selected = run_directory.resolve()
        load_manifest(selected / "manifest.json")
        return selected

    raw_directory = resolve_project_path(config["raw_directory"])
    direct_manifest = raw_directory / "manifest.json"
    if direct_manifest.is_file():
        manifest = load_manifest(direct_manifest)
        if not is_complete_manifest(manifest):
            raise ValueError(f"Calendar collection is incomplete: {raw_directory}")
        return raw_directory

    completed_runs: list[Path] = []
    for manifest_path in raw_directory.glob("*/manifest.json"):
        if is_complete_manifest(load_manifest(manifest_path)):
            completed_runs.append(manifest_path.parent)
    if not completed_runs:
        raise FileNotFoundError(
            f"No complete Calendar collection found in {raw_directory}"
        )
    return sorted(completed_runs)[-1]


def parse_credits(value: str) -> tuple[float, float]:
    parts = value.split("-", maxsplit=1)
    minimum = float(parts[0])
    maximum = float(parts[-1])
    return minimum, maximum


def extract_requirement_text(description: str) -> dict[str, str | None]:
    matches = list(REQUIREMENT_LABEL.finditer(description))
    values: dict[str, list[str]] = {
        "prerequisite_text": [],
        "corequisite_text": [],
        "equivalency_text": [],
        "recommended_prerequisite_text": [],
        "recommended_text": [],
    }
    label_names = {
        "prerequisite": "prerequisite_text",
        "prerequisites": "prerequisite_text",
        "corequisite": "corequisite_text",
        "corequisites": "corequisite_text",
        "equivalency": "equivalency_text",
        "recommended prerequisite": "recommended_prerequisite_text",
        "recommended prerequisites": "recommended_prerequisite_text",
        "recommended": "recommended_text",
    }

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            description
        )
        value = description[match.end() : end].strip()
        if value:
            key = label_names[match.group("label").casefold()]
            values[key].append(value)

    return {
        key: " | ".join(items) if items else None
        for key, items in values.items()
    }


def parse_subject_page(
    body: bytes,
    *,
    subject: dict[str, Any],
    collected_at: str,
) -> list[dict[str, Any]]:
    parser = SubjectPageParser()
    parser.feed(body.decode("utf-8"))
    academic_unit = normalize_text(parser.academic_unit_parts)
    courses: list[dict[str, Any]] = []

    for heading_parts, description_parts in parser.course_parts:
        heading = normalize_text(heading_parts)
        description = normalize_text(description_parts)
        match = COURSE_HEADING.fullmatch(heading)
        if match is None:
            raise ValueError(
                f"Unrecognized course heading in {subject['file']}: {heading!r}"
            )
        if match.group("subject") != subject["code"]:
            raise ValueError(
                f"Course subject does not match page {subject['code']}: {heading}"
            )

        credits_min, credits_max = parse_credits(match.group("credits"))
        course_number = match.group("number")
        course = {
            "course_code": f"{match.group('subject')} {course_number}",
            "subject_code": match.group("subject"),
            "subject_name": subject["name"],
            "subject_slug": subject["slug"],
            "course_number": course_number,
            "credits": match.group("credits"),
            "credits_min": credits_min,
            "credits_max": credits_max,
            "title": match.group("title"),
            "academic_unit": academic_unit,
            "description": description,
            **extract_requirement_text(description),
            "calendar_collected_at": collected_at,
            "source_url": subject["response_url"],
            "source_file": subject["file"],
        }
        courses.append(course)

    return courses


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parse_run(
    config: dict[str, Any], run_directory: Path | None = None
) -> dict[str, int | str]:
    selected_run = find_run_directory(config, run_directory)
    manifest = load_manifest(selected_run / "manifest.json")
    courses: list[dict[str, Any]] = []

    for subject in manifest["subjects"]:
        source_path = resolve_project_path(subject["file"])
        body = source_path.read_bytes()
        actual_hash = hashlib.sha256(body).hexdigest()
        if actual_hash != subject["sha256"]:
            raise ValueError(f"Hash mismatch for {source_path}")

        subject_courses = parse_subject_page(
            body,
            subject=subject,
            collected_at=manifest["collected_at"],
        )
        if len(subject_courses) != subject["course_count"]:
            raise ValueError(
                f"Expected {subject['course_count']} courses in {source_path}, "
                f"found {len(subject_courses)}"
            )
        courses.extend(subject_courses)

    course_codes = [course["course_code"] for course in courses]
    if len(course_codes) != len(set(course_codes)):
        raise ValueError("Duplicate course codes found in Calendar collection")

    output_directory = resolve_project_path(config["output_directory"])
    atomic_write_csv(output_directory / config["courses_csv"], courses)
    atomic_write_jsonl(output_directory / config["courses_jsonl"], courses)

    return {
        "run_directory": selected_run.as_posix(),
        "subjects": len(manifest["subjects"]),
        "courses": len(courses),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--run-directory",
        type=Path,
        help="Calendar collection to parse (default: newest complete run)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = parse_run(load_config(args.config.resolve()), args.run_directory)
    print(
        f"Parsed {counts['courses']} courses from {counts['subjects']} subjects "
        f"in {counts['run_directory']}"
    )


if __name__ == "__main__":
    main()
