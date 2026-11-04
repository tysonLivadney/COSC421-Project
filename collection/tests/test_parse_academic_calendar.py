import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from collection.parse_academic_calendar import (
    extract_requirement_text,
    parse_run,
    parse_subject_page,
)


class AcademicCalendarParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = (
            Path(__file__).parent / "fixtures" / "calendar_subject.html"
        )
        self.subject = {
            "code": "COSC_O",
            "name": "Computer Science",
            "slug": "cosco",
            "course_count": 2,
            "response_url": (
                "https://okanagan.calendar.ubc.ca/"
                "course-descriptions/subject/cosco"
            ),
            "file": "calendar_subject.html",
        }

    def test_parse_subject_page_extracts_course_fields(self) -> None:
        courses = parse_subject_page(
            self.fixture.read_bytes(),
            subject=self.subject,
            collected_at="2026-10-28T12:00:00+00:00",
        )

        self.assertEqual(len(courses), 2)
        self.assertEqual(courses[0]["course_code"], "COSC_O 111")
        self.assertEqual(courses[0]["title"], "Computer Programming I")
        self.assertEqual(courses[0]["credits_min"], 3.0)
        self.assertEqual(courses[0]["credits_max"], 3.0)
        self.assertIn("H2O", courses[0]["description"])
        self.assertEqual(courses[0]["prerequisite_text"], "MATH_O 100.")
        self.assertEqual(
            courses[0]["academic_unit"], "Computer Science, Faculty of Science"
        )

    def test_extract_requirement_text_handles_all_labels(self) -> None:
        values = extract_requirement_text(
            "Description. Recommended prerequisite: MATH_O 100. "
            "Prerequisites: COSC_O 111 and MATH_O 101. "
            "Corequisite: DATA_O 101. Equivalency: TEST_O 100. "
            "Recommended: Third-year standing."
        )

        self.assertEqual(values["recommended_prerequisite_text"], "MATH_O 100.")
        self.assertEqual(
            values["prerequisite_text"], "COSC_O 111 and MATH_O 101."
        )
        self.assertEqual(values["corequisite_text"], "DATA_O 101.")
        self.assertEqual(values["equivalency_text"], "TEST_O 100.")
        self.assertEqual(values["recommended_text"], "Third-year standing.")

    def test_parse_run_writes_csv_and_jsonl(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).parent
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            run_directory = temporary_path / "raw" / "2026-10-28T120000Z"
            subject_path = run_directory / "subjects" / "cosco.html"
            subject_path.parent.mkdir(parents=True)
            shutil.copy2(self.fixture, subject_path)

            subject = {
                **self.subject,
                "file": subject_path.resolve().as_posix(),
                "sha256": hashlib.sha256(subject_path.read_bytes()).hexdigest(),
            }
            manifest = {
                "collected_at": "2026-10-28T12:00:00+00:00",
                "discovered_subject_count": 1,
                "collected_subject_count": 1,
                "subjects": [subject],
            }
            (run_directory / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            output_directory = temporary_path / "processed"
            config = {
                "raw_directory": str(temporary_path / "raw"),
                "output_directory": str(output_directory),
                "courses_csv": "courses.csv",
                "courses_jsonl": "courses.jsonl",
            }
            counts = parse_run(config)

            self.assertEqual(counts["subjects"], 1)
            self.assertEqual(counts["courses"], 2)
            with (output_directory / "courses.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[1]["course_code"], "COSC_O 121")
            jsonl_rows = [
                json.loads(line)
                for line in (output_directory / "courses.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(jsonl_rows), 2)


if __name__ == "__main__":
    unittest.main()
