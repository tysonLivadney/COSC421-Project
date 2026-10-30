import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from collection.json_to_csv import (
    convert,
    discover_input_files,
    flatten_resource,
    iter_resources,
    relationship_values,
)


class JsonToCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "jsonapi_page.json"
        self.payload = json.loads(fixture.read_text(encoding="utf-8"))

    def test_iter_resources_preserves_roles(self) -> None:
        resources = list(iter_resources(self.payload))
        self.assertEqual([role for role, _ in resources], ["primary", "included"])

    def test_relationship_values_handles_to_one_relationship(self) -> None:
        relationship = self.payload["data"][0]["relationships"]["field_course"]
        self.assertEqual(
            relationship_values(relationship),
            {
                "ids": ["course-1"],
                "types": ["node--course"],
                "target_ids": [1234],
            },
        )

    def test_flatten_resource_keeps_nested_values(self) -> None:
        row = flatten_resource(
            self.payload["included"][0],
            role="included",
            source_file="data/raw/example.json",
            separator=".",
            include_source_file=True,
        )
        self.assertEqual(row["attribute.field_course_code"], "COSC_O 111")
        self.assertEqual(
            json.loads(row["attribute.body"]),
            {"processed": "Example description"},
        )

    def test_convert_writes_csv_and_lossless_jsonl(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "jsonapi_page.json"
        # Keep the test workspace inside the repository so restricted execution
        # environments can exercise the same file-writing path as the project.
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).parent
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            raw_directory = temporary_path / "raw"
            output_directory = temporary_path / "processed"
            raw_directory.mkdir()
            shutil.copy2(fixture, raw_directory / "page_0001.json")

            config = {
                "input": {
                    "raw_directory": str(raw_directory),
                    "file_pattern": "*.json",
                    "recursive": True,
                },
                "output": {
                    "directory": str(output_directory),
                    "primary_csv": "primary.csv",
                    "included_csv": "included.csv",
                    "lossless_jsonl": "resources.jsonl",
                },
                "conversion": {
                    "column_separator": ".",
                    "include_source_file": True,
                    "deduplicate_resources": False,
                },
            }

            counts = convert(config)

            self.assertEqual(
                counts,
                {
                    "input_files": 1,
                    "primary_resources": 1,
                    "included_resources": 1,
                },
            )
            with (output_directory / "primary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                primary_rows = list(csv.DictReader(handle))
            self.assertEqual(primary_rows[0]["resource_id"], "section-1")
            self.assertEqual(
                len((output_directory / "resources.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()),
                2,
            )

    def test_discover_input_files_uses_newest_completed_run(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_directory:
            raw_directory = Path(temporary_directory)
            incomplete = raw_directory / "2026-01-03T000000Z"
            older = raw_directory / "2026-01-01T000000Z"
            newer = raw_directory / "2026-01-02T000000Z"
            for directory in (incomplete, older, newer):
                directory.mkdir()
                (directory / "page_0001.json").write_text("{}", encoding="utf-8")
            (older / "manifest.json").write_text("{}", encoding="utf-8")
            (newer / "manifest.json").write_text("{}", encoding="utf-8")

            files = discover_input_files(
                {
                    "input": {
                        "raw_directory": str(raw_directory),
                        "file_pattern": "page_*.json",
                        "recursive": True,
                    }
                }
            )

            self.assertEqual(files, [newer / "page_0001.json"])


if __name__ == "__main__":
    unittest.main()
