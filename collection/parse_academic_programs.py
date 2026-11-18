"""Parse saved UBC Okanagan undergraduate Academic Program pages."""

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

try:
    from . import collect_academic_programs as collector
except ImportError:  # Allows `python collection/parse_academic_programs.py`.
    import collect_academic_programs as collector


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
CREDIT_VALUE = re.compile(r"^\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?$|^$")
CREDITS_IN_TEXT = re.compile(r"\b(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)\s+credits?\b", re.I)
RELEVANT_TEXT = re.compile(
    r"\b(?:credit|course|elective|requirement|standing|average|grade|year|"
    r"thesis|major|minor|concentration|specialization)\b",
    re.I,
)
CHOICE_TEXT = re.compile(r"\b(?:or|one of|two of|choose|chosen|selected|from)\b", re.I)
PROGRAM_COURSE_REF = re.compile(
    r"\b(?:([A-Z]{3,4})(?:_O)?\s+)?(\d{3}[A-Z]?)\b(?![-\d%])"
)
COURSE_LIST_CONNECTOR = re.compile(
    r"^[\s,;/()]*?(?:(?:and|or|one|two|three|of)[\s,;/()]*)*$",
    re.I,
)

PROGRAM_COLUMNS = (
    "program_id",
    "name",
    "faculty",
    "level",
    "page_title",
    "calendar_collected_at",
    "source_url",
    "source_file",
)
REQUIREMENT_COLUMNS = (
    "requirement_id",
    "program_id",
    "section",
    "source_type",
    "position",
    "requirement_text",
    "credits",
    "requirement_kind",
    "course_codes",
    "raw_cells",
)
PROGRAM_COURSE_COLUMNS = (
    "program_id",
    "requirement_id",
    "course_code",
    "section",
    "source_type",
    "requirement_kind",
    "credits",
    "requirement_text",
)


def clean(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def extract_course_codes(text: str) -> list[str]:
    """Extract explicit course codes and tightly connected bare-number lists."""
    found: list[str] = []
    subject: str | None = None
    previous_end = 0
    for match in PROGRAM_COURSE_REF.finditer(text):
        explicit_subject = match.group(1)
        if explicit_subject:
            subject = explicit_subject
        elif subject is None or not COURSE_LIST_CONNECTOR.fullmatch(
            text[previous_end : match.start()]
        ):
            subject = None
            previous_end = match.end()
            continue
        found.append(f"{subject}_O {match.group(2)}")
        previous_end = match.end()
    return unique(found)


class ProgramPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.page_title_parts: list[str] = []
        self.blocks: list[dict[str, Any]] = []
        self._in_page_title = False
        self._body_depth = 0
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._headings: list[tuple[int, str]] = []
        self._paragraph_parts: list[str] | None = None
        self._list_parts: list[list[str]] = []
        self._table_number = 0
        self._table_title = ""
        self._row_cells: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._position = 0
        self._superscript_depth = 0

    @property
    def in_body(self) -> bool:
        return self._body_depth > 0

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        classes = (dict(attributes).get("class") or "").split()
        if tag == "h1" and "page-title" in classes:
            self._in_page_title = True

        if tag == "div" and "field--name-body" in classes and not self.in_body:
            self._body_depth = 1
            return
        if self.in_body and tag == "div":
            self._body_depth += 1
        if not self.in_body:
            return

        if tag == "sup":
            self._superscript_depth += 1
            return
        if self._superscript_depth:
            return

        if tag in {"h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._heading_parts = []
        elif tag == "p":
            self._paragraph_parts = []
        elif tag == "li":
            self._list_parts.append([])
        elif tag == "table":
            self._table_number += 1
            self._table_title = ""
        elif tag == "tr":
            self._row_cells = []
        elif tag in {"td", "th"} and self._row_cells is not None:
            self._cell_parts = []
        elif tag == "br":
            self._append_text(" ")

    def handle_data(self, data: str) -> None:
        if self._in_page_title:
            self.page_title_parts.append(data)
        if not self.in_body:
            return
        if self._superscript_depth:
            return
        self._append_text(data)

    def _append_text(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_parts.append(data)
        if self._paragraph_parts is not None:
            self._paragraph_parts.append(data)
        for parts in self._list_parts:
            parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_page_title = False
        if not self.in_body:
            return

        if tag == "sup" and self._superscript_depth:
            self._superscript_depth -= 1
            return
        if self._superscript_depth:
            return

        if self._heading_level is not None and tag == f"h{self._heading_level}":
            text = clean(self._heading_parts)
            level = self._heading_level
            self._headings = [(n, h) for n, h in self._headings if n < level]
            if text:
                self._headings.append((level, text))
            self._heading_level = None
            self._heading_parts = []
        elif tag == "p" and self._paragraph_parts is not None:
            self._add_text_block("paragraph", clean(self._paragraph_parts))
            self._paragraph_parts = None
        elif tag == "li" and self._list_parts:
            parts = self._list_parts.pop()
            self._add_text_block("list", clean(parts))
        elif tag in {"td", "th"} and self._cell_parts is not None:
            if self._row_cells is not None:
                self._row_cells.append(clean(self._cell_parts))
            self._cell_parts = None
        elif tag == "tr" and self._row_cells is not None:
            self._add_table_row(self._row_cells)
            self._row_cells = None
        elif tag == "div":
            self._body_depth -= 1

    def _section(self, table_title: str = "") -> str:
        parts = [heading for _, heading in self._headings]
        if table_title and (not parts or parts[-1] != table_title):
            parts.append(table_title)
        return " > ".join(parts)

    def _add_text_block(self, source_type: str, text: str) -> None:
        codes = extract_course_codes(text)
        if not text or (not codes and not RELEVANT_TEXT.search(text)):
            return
        credit_match = CREDITS_IN_TEXT.search(text)
        self._position += 1
        self.blocks.append(
            {
                "section": self._section(),
                "source_type": source_type,
                "position": self._position,
                "requirement_text": text,
                "credits": credit_match.group(1) if credit_match else "",
                "course_codes": codes,
                "raw_cells": [],
            }
        )

    def _add_table_row(self, cells: list[str]) -> None:
        cells = [cell for cell in cells if cell]
        if not cells:
            return
        if (
            len(cells) > 1
            and cells[-1].casefold() == "credits"
            and not extract_course_codes(cells[0])
        ):
            self._table_title = cells[0]
            return

        credits = ""
        text_cells = cells
        if len(cells) > 1 and CREDIT_VALUE.fullmatch(cells[-1]):
            credits = cells[-1]
            text_cells = cells[:-1]
        text = " | ".join(text_cells)
        self._position += 1
        self.blocks.append(
            {
                "section": self._section(self._table_title),
                "source_type": "table",
                "position": self._position,
                "requirement_text": text,
                "credits": credits,
                "course_codes": extract_course_codes(text),
                "raw_cells": cells,
            }
        )


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def requirement_kind(text: str, codes: list[str]) -> str:
    lowered = text.casefold()
    if "total" in lowered or "minimum credits for degree" in lowered:
        return "total"
    if "elective" in lowered:
        return "elective"
    if codes and (len(codes) > 1 and CHOICE_TEXT.search(text)):
        return "course_choice"
    if codes:
        return "course"
    return "other"


def parse_program_page(
    body: bytes, *, program: dict[str, Any], collected_at: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    parser = ProgramPageParser()
    parser.feed(body.decode("utf-8"))

    program_row = {
        "program_id": program["program_id"],
        "name": program["name"],
        "faculty": program["faculty"],
        "level": program["level"],
        "page_title": clean(parser.page_title_parts),
        "calendar_collected_at": collected_at,
        "source_url": program["response_url"],
        "source_file": program["file"],
    }
    requirements: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    for number, block in enumerate(parser.blocks, start=1):
        requirement_id = f"{program['program_id']}:{number}"
        codes = block.pop("course_codes")
        row = {
            "requirement_id": requirement_id,
            "program_id": program["program_id"],
            **block,
            "requirement_kind": requirement_kind(block["requirement_text"], codes),
            "course_codes": "|".join(codes),
            "raw_cells": json.dumps(block["raw_cells"], ensure_ascii=False),
        }
        requirements.append(row)
        mentions.extend(
            {
                "program_id": program["program_id"],
                "requirement_id": requirement_id,
                "course_code": code,
                "section": row["section"],
                "source_type": row["source_type"],
                "requirement_kind": row["requirement_kind"],
                "credits": row["credits"],
                "requirement_text": row["requirement_text"],
            }
            for code in codes
        )
    return program_row, requirements, mentions


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    parsing = config.get("academic_program_parsing")
    if not isinstance(parsing, dict):
        raise ValueError("Configuration is missing 'academic_program_parsing'")
    return parsing


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest.get("programs"), list):
        raise ValueError(f"Invalid Academic Programs manifest: {path}")
    return manifest


def eligible_program_count(run_directory: Path, manifest: dict[str, Any]) -> int:
    recorded = manifest.get("eligible_program_count")
    if isinstance(recorded, int):
        return recorded
    index_file = resolve_project_path(manifest["program_index"]["file"])
    discovered = collector.parse_programs(index_file.read_bytes(), manifest["base_url"])
    level = manifest.get("level", "Undergraduate")
    return len(collector.select_programs(discovered, level, None))


def is_complete_manifest(run_directory: Path, manifest: dict[str, Any]) -> bool:
    return manifest.get("collected_program_count") == eligible_program_count(
        run_directory, manifest
    )


def find_run_directory(config: dict[str, Any], run_directory: Path | None = None) -> Path:
    if run_directory is not None:
        selected = run_directory.resolve()
        load_manifest(selected / "manifest.json")
        return selected

    raw_directory = resolve_project_path(config["raw_directory"])
    complete: list[Path] = []
    for manifest_path in raw_directory.glob("*/manifest.json"):
        manifest = load_manifest(manifest_path)
        if is_complete_manifest(manifest_path.parent, manifest):
            complete.append(manifest_path.parent)
    if not complete:
        raise FileNotFoundError(
            f"No complete Academic Programs collection found in {raw_directory}"
        )
    return sorted(complete)[-1]


def atomic_write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def parse_run(
    config: dict[str, Any], run_directory: Path | None = None
) -> dict[str, int | str]:
    selected_run = find_run_directory(config, run_directory)
    manifest = load_manifest(selected_run / "manifest.json")
    programs: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []

    for program in manifest["programs"]:
        source_path = resolve_project_path(program["file"])
        body = source_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != program["sha256"]:
            raise ValueError(f"Hash mismatch for {source_path}")
        program_row, program_requirements, program_mentions = parse_program_page(
            body, program=program, collected_at=manifest["collected_at"]
        )
        programs.append(program_row)
        requirements.extend(program_requirements)
        mentions.extend(program_mentions)

    output = resolve_project_path(config["output_directory"])
    atomic_write_csv(output / config["programs_csv"], PROGRAM_COLUMNS, programs)
    atomic_write_csv(
        output / config["requirements_csv"], REQUIREMENT_COLUMNS, requirements
    )
    atomic_write_csv(
        output / config["program_courses_csv"], PROGRAM_COURSE_COLUMNS, mentions
    )
    return {
        "run_directory": selected_run.as_posix(),
        "programs": len(programs),
        "requirements": len(requirements),
        "course_mentions": len(mentions),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-directory", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = parse_run(load_config(args.config.resolve()), args.run_directory)
    print(
        f"Parsed {counts['programs']} programs, {counts['requirements']} requirements, "
        f"and {counts['course_mentions']} course mentions from {counts['run_directory']}"
    )


if __name__ == "__main__":
    main()
