"""Convert saved JSON:API responses into tabular and lossless outputs.

Raw responses are never modified. Every resource is written to JSON Lines in
its original form, and commonly useful attributes and relationship identifiers
are flattened into CSV files for inspection and downstream processing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
METADATA_COLUMNS = ("resource_role", "resource_type", "resource_id", "source_file")


def load_config(path: Path) -> dict[str, Any]:
    """Load and minimally validate a conversion configuration file."""
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    for section in ("input", "output", "conversion"):
        if section not in config or not isinstance(config[section], dict):
            raise ValueError(f"Configuration is missing the '{section}' object")

    return config


def resolve_project_path(value: str) -> Path:
    """Resolve configured paths relative to the repository root."""
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def json_cell(value: Any) -> Any:
    """Keep scalar values readable and encode structured values as JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def relationship_values(relationship: dict[str, Any]) -> dict[str, Any]:
    """Extract identifiers from either to-one or to-many JSON:API data."""
    data = relationship.get("data")
    if data is None:
        resources: list[dict[str, Any]] = []
    elif isinstance(data, list):
        resources = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        resources = [data]
    else:
        resources = []

    return {
        "ids": [item.get("id") for item in resources],
        "types": [item.get("type") for item in resources],
        "target_ids": [
            item.get("meta", {}).get("drupal_internal__target_id")
            for item in resources
        ],
    }


def flatten_resource(
    resource: dict[str, Any],
    *,
    role: str,
    source_file: str,
    separator: str,
    include_source_file: bool,
) -> dict[str, Any]:
    """Flatten one JSON:API resource without interpreting domain semantics."""
    row: dict[str, Any] = {
        "resource_role": role,
        "resource_type": resource.get("type"),
        "resource_id": resource.get("id"),
    }
    if include_source_file:
        row["source_file"] = source_file

    attributes = resource.get("attributes") or {}
    if isinstance(attributes, dict):
        for name, value in attributes.items():
            row[f"attribute{separator}{name}"] = json_cell(value)

    relationships = resource.get("relationships") or {}
    if isinstance(relationships, dict):
        for name, relationship in relationships.items():
            if not isinstance(relationship, dict):
                continue
            values = relationship_values(relationship)
            for value_name, value in values.items():
                row[f"relationship{separator}{name}{separator}{value_name}"] = json_cell(value)

    # These fields are less useful as individual columns but remain valuable.
    # Preserve them in compact form in addition to the lossless JSONL output.
    for name in ("links", "meta"):
        if name in resource:
            row[name] = json_cell(resource[name])

    return row


def iter_resources(payload: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield primary and included resources from one JSON:API document."""
    primary = payload.get("data", [])
    if isinstance(primary, dict):
        primary = [primary]
    if not isinstance(primary, list):
        raise ValueError("The JSON:API 'data' member must be an object or array")

    included = payload.get("included", [])
    if not isinstance(included, list):
        raise ValueError("The JSON:API 'included' member must be an array")

    for resource in primary:
        if isinstance(resource, dict):
            yield "primary", resource
    for resource in included:
        if isinstance(resource, dict):
            yield "included", resource


def discover_input_files(
    config: dict[str, Any], run_directory: Path | None = None
) -> list[Path]:
    input_config = config["input"]
    raw_directory = (
        run_directory.resolve()
        if run_directory is not None
        else resolve_project_path(input_config["raw_directory"])
    )
    pattern = input_config.get("file_pattern", "*.json")
    recursive = input_config.get("recursive", True)

    # A direct directory remains useful for fixtures and explicitly selected
    # runs. Otherwise, use only the newest completed collection so interrupted
    # runs and duplicate pages are never combined.
    direct_files = sorted(
        path for path in raw_directory.glob(pattern) if path.is_file()
    )
    is_collection = (raw_directory / "manifest.json").is_file()
    if run_directory is None and not direct_files and not is_collection:
        completed_runs = sorted(
            manifest.parent for manifest in raw_directory.glob("*/manifest.json")
        )
        if not completed_runs:
            raise FileNotFoundError(
                f"No completed collection found in {raw_directory}"
            )
        raw_directory = completed_runs[-1]

    iterator = raw_directory.rglob(pattern) if recursive else raw_directory.glob(pattern)
    return sorted(path for path in iterator if path.is_file())


def ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    present = {column for row in rows for column in row}
    leading = [column for column in METADATA_COLUMNS if column in present]
    return leading + sorted(present.difference(leading))


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a CSV atomically so interrupted runs do not leave partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ordered_columns(rows)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            if columns:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
                writer.writeheader()
                writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_jsonl(path: Path, resources: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for resource in resources:
                handle.write(json.dumps(resource, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def convert(
    config: dict[str, Any], run_directory: Path | None = None
) -> dict[str, int]:
    """Convert every configured raw JSON file and return record counts."""
    conversion_config = config["conversion"]
    separator = conversion_config.get("column_separator", ".")
    include_source = conversion_config.get("include_source_file", True)
    deduplicate = conversion_config.get("deduplicate_resources", False)

    primary_rows: list[dict[str, Any]] = []
    included_rows: list[dict[str, Any]] = []
    lossless_resources: list[dict[str, Any]] = []
    seen: set[tuple[str, Any, Any]] = set()
    input_files = discover_input_files(config, run_directory)

    for input_path in input_files:
        with input_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object in {input_path}")

        try:
            source_file = input_path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            source_file = input_path.resolve().as_posix()
        for role, resource in iter_resources(payload):
            key = (role, resource.get("type"), resource.get("id"))
            if deduplicate and key in seen:
                continue
            seen.add(key)

            row = flatten_resource(
                resource,
                role=role,
                source_file=source_file,
                separator=separator,
                include_source_file=include_source,
            )
            (primary_rows if role == "primary" else included_rows).append(row)
            lossless_resources.append(
                {
                    "source_file": source_file,
                    "resource_role": role,
                    "resource": resource,
                }
            )

    output_config = config["output"]
    output_directory = resolve_project_path(output_config["directory"])
    atomic_write_csv(output_directory / output_config["primary_csv"], primary_rows)
    atomic_write_csv(output_directory / output_config["included_csv"], included_rows)
    atomic_write_jsonl(output_directory / output_config["lossless_jsonl"], lossless_resources)

    return {
        "input_files": len(input_files),
        "primary_resources": len(primary_rows),
        "included_resources": len(included_rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert saved JSON:API responses to CSV and JSON Lines."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Configuration file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        help="Completed collection directory to convert (default: newest completed run)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = convert(load_config(args.config.resolve()), args.run_directory)
    print(
        "Converted "
        f"{counts['input_files']} file(s): "
        f"{counts['primary_resources']} primary and "
        f"{counts['included_resources']} included resource(s)."
    )


if __name__ == "__main__":
    main()
