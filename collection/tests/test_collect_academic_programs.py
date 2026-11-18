import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collection import collect_academic_programs as collector


class AcademicProgramCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "calendar_program_index.html"
        self.index_body = fixture.read_bytes()
        self.program_body = (
            b'<html><main><h1>Computer Science</h1>'
            b'<a href="/node/17037/degree-requirements">Degree Requirements</a>'
            b'<a href="/node/17037/admission-requirements">Admission Requirements</a>'
            b'</main></html>'
        )
        self.related_body = b"<html><main><h1>Degree Requirements</h1></main></html>"

    def test_parse_programs_reads_table_rows(self) -> None:
        programs = collector.parse_programs(self.index_body, "https://example.test")

        self.assertEqual(
            [(p.program_id, p.name, p.faculty, p.level) for p in programs],
            [
                ("17037", "Computer Science (B.Sc.)", "Science", "Undergraduate"),
                ("16688", "Computer Science (B.A.)", "Arts and Social Sciences", "Undergraduate"),
                ("16848", "Computer Science", "College of Graduate Studies", "Graduate"),
            ],
        )

    def test_collect_preserves_selected_undergraduate_page(self) -> None:
        responses = {
            "https://example.test/academic-programs": self.index_body,
            "https://example.test/node/17037": self.program_body,
            "https://example.test/node/17037/degree-requirements": self.related_body,
        }

        def fake_download(url: str, **_: object) -> collector.common.HttpResponse:
            return collector.common.HttpResponse(
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
                "program_index_path": "academic-programs",
                "raw_directory": temporary_directory,
                "level": "Undergraduate",
                "request_delay_seconds": 0,
            }
            run_directory = collector.collect(
                settings,
                selected_programs=["17037"],
                collected_at=datetime(2026, 11, 18, 12, tzinfo=timezone.utc),
                downloader=fake_download,
                progress=lambda _: None,
            )

            self.assertEqual(
                (run_directory / "programs" / "17037.html").read_bytes(),
                self.program_body,
            )
            self.assertEqual(
                (
                    run_directory
                    / "related"
                    / "17037"
                    / "degree-requirements.html"
                ).read_bytes(),
                self.related_body,
            )
            manifest = json.loads(
                (run_directory / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["discovered_program_count"], 3)
            self.assertEqual(manifest["eligible_program_count"], 2)
            self.assertEqual(manifest["collected_program_count"], 1)
            self.assertEqual(manifest["collected_related_page_count"], 1)
            self.assertEqual(manifest["programs"][0]["faculty"], "Science")
            self.assertEqual(
                manifest["programs"][0]["related_pages"][0]["title"],
                "Degree Requirements",
            )

    def test_related_only_adds_missing_page_without_redownloading_main(self) -> None:
        calls: list[str] = []

        def fake_download(url: str, **_: object) -> collector.common.HttpResponse:
            calls.append(url)
            return collector.common.HttpResponse(
                body=self.related_body,
                final_url=url,
                status=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            run = Path(temporary) / "2026-11-18T120000Z"
            source = run / "programs" / "17037.html"
            source.parent.mkdir(parents=True)
            source.write_bytes(self.program_body)
            manifest = {
                "base_url": "https://example.test",
                "level": "Undergraduate",
                "eligible_program_count": 1,
                "collected_program_count": 1,
                "programs": [
                    {
                        "program_id": "17037",
                        "name": "Computer Science (B.Sc.)",
                        "response_url": "https://example.test/node/17037",
                        "file": source.as_posix(),
                    }
                ],
            }
            (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            settings = {
                "raw_directory": temporary,
                "request_delay_seconds": 0,
            }

            _, first = collector.collect_related_only(
                settings, run_directory=run, downloader=fake_download, progress=lambda _: None
            )
            _, second = collector.collect_related_only(
                settings, run_directory=run, downloader=fake_download, progress=lambda _: None
            )

            self.assertEqual((first, second), (1, 0))
            self.assertEqual(calls, ["https://example.test/node/17037/degree-requirements"])


if __name__ == "__main__":
    unittest.main()
