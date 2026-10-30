import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collection import collect_academic_calendar as collector


class AcademicCalendarCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        self.index_body = (fixtures / "calendar_subject_index.html").read_bytes()
        self.subject_body = (fixtures / "calendar_subject.html").read_bytes()

    def test_parse_subjects_reads_calendar_links(self) -> None:
        subjects = collector.parse_subjects(
            self.index_body, "https://okanagan.calendar.ubc.ca"
        )

        self.assertEqual(
            [(subject.code, subject.name, subject.slug) for subject in subjects],
            [
                ("COSC_O", "Computer Science", "cosco"),
                ("DATA_O", "Data Science", "datao"),
            ],
        )

    def test_collect_preserves_html_and_records_metadata(self) -> None:
        responses = {
            "https://example.test/course-descriptions/courses-subject": (
                self.index_body
            ),
            "https://example.test/course-descriptions/subject/cosco": (
                self.subject_body
            ),
        }

        def fake_download(url: str, **_: object) -> collector.HttpResponse:
            return collector.HttpResponse(
                body=responses[url],
                final_url=url,
                status=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

        with tempfile.TemporaryDirectory(
            dir=Path(__file__).parent
        ) as temporary_directory:
            settings = {
                "base_url": "https://example.test",
                "subject_index_path": "course-descriptions/courses-subject",
                "raw_directory": temporary_directory,
                "request_delay_seconds": 0,
                "datasets": {},
            }
            run_directory = collector.collect(
                settings,
                selected_subjects=["COSC_O"],
                collected_at=datetime(2026, 10, 28, 12, tzinfo=timezone.utc),
                downloader=fake_download,
                progress=lambda _: None,
            )

            self.assertEqual(
                (run_directory / "subject_index.html").read_bytes(), self.index_body
            )
            self.assertEqual(
                (run_directory / "subjects" / "cosco.html").read_bytes(),
                self.subject_body,
            )
            manifest = json.loads(
                (run_directory / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["discovered_subject_count"], 1)
            self.assertEqual(manifest["collected_subject_count"], 1)
            self.assertEqual(manifest["subjects"][0]["code"], "COSC_O")
            self.assertEqual(manifest["subjects"][0]["course_count"], 2)


if __name__ == "__main__":
    unittest.main()
