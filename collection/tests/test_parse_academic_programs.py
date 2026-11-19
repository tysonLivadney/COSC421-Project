import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collection import parse_academic_programs as parser


class AcademicProgramParserTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "calendar_program.html"
        self.body = fixture.read_bytes()
        self.program = {
            "program_id": "17037",
            "name": "Computer Science (B.Sc.)",
            "faculty": "Science",
            "level": "Undergraduate",
            "response_url": "https://example.test/programs/computer-science",
            "file": "programs/17037.html",
        }

    def test_parse_program_page_preserves_groups_and_course_mentions(self) -> None:
        program, requirements, mentions = parser.parse_program_page(
            self.body, program=self.program, collected_at="2026-11-18T12:00:00+00:00"
        )

        self.assertEqual(program["page_title"], "Computer Science (B.Sc.)")
        choice = next(r for r in requirements if r["requirement_text"] == "COSC_O 111 or 123")
        self.assertEqual(choice["section"], "B.Sc. Major in Computer Science > First Year")
        self.assertEqual(choice["requirement_kind"], "course_choice")
        self.assertEqual(choice["course_codes"], "COSC_O 111|COSC_O 123")
        self.assertEqual(choice["credits"], "3")
        self.assertIn("COSC_O 451", {row["course_code"] for row in mentions})
        mentioned = {row["course_code"] for row in mentions}
        self.assertIn("ENGL_O 112", mentioned)
        self.assertNotIn("APSC_O 112", mentioned)
        self.assertNotIn("Unrelated footer", {r["section"] for r in requirements})

    def test_course_extraction_rejects_credit_counts_and_level_rules(self) -> None:
        text = (
            "EESC_O 449 or EESC_O 450 and 451, representing 6 of the 120 credits; "
            "EESC_O courses numbered 200, 300 and 400."
        )

        self.assertEqual(
            parser.extract_course_codes(text),
            ["EESC_O 449", "EESC_O 450", "EESC_O 451"],
        )

    def test_parse_run_writes_normalized_csv_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            run = root / "raw" / "2026-11-18T120000Z"
            source = run / "programs" / "17037.html"
            source.parent.mkdir(parents=True)
            source.write_bytes(self.body)
            related_body = (
                b'<h1 class="page-title">Shared Degree Requirements</h1>'
                b'<div class="field--name-body"><table>'
                b'<tr><td>STAT_O 230</td><td>3</td></tr>'
                b'</table></div>'
            )
            related_source = run / "related" / "17037" / "degree-requirements.html"
            related_source.parent.mkdir(parents=True)
            related_source.write_bytes(related_body)
            index = run / "program_index.html"
            index.write_text(
                '<table><tr><td><a href="/node/17037">Computer Science (B.Sc.)</a></td>'
                '<td>Science</td><td>Undergraduate</td></tr></table>',
                encoding="utf-8",
            )
            manifest = {
                "base_url": "https://example.test",
                "collected_at": datetime(2026, 11, 18, 12, tzinfo=timezone.utc).isoformat(),
                "level": "Undergraduate",
                "eligible_program_count": 1,
                "collected_program_count": 1,
                "program_index": {"file": index.as_posix()},
                "programs": [
                    {
                        **self.program,
                        "file": source.as_posix(),
                        "sha256": hashlib.sha256(self.body).hexdigest(),
                        "related_pages": [
                            {
                                "title": "Degree Requirements",
                                "slug": "degree-requirements",
                                "response_url": "https://example.test/programs/computer-science/degree-requirements",
                                "file": related_source.as_posix(),
                                "sha256": hashlib.sha256(related_body).hexdigest(),
                            }
                        ],
                    }
                ],
            }
            (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "processed"
            config = {
                "raw_directory": str(root / "raw"),
                "output_directory": str(output),
                "programs_csv": "programs.csv",
                "requirements_csv": "requirements.csv",
                "program_courses_csv": "program_courses.csv",
            }

            counts = parser.parse_run(config)

            self.assertEqual(counts["programs"], 1)
            self.assertTrue((output / "requirements.csv").is_file())
            with (output / "program_courses.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertIn("COSC_O 123", {row["course_code"] for row in rows})
            related = next(row for row in rows if row["course_code"] == "STAT_O 230")
            self.assertEqual(related["source_page_title"], "Shared Degree Requirements")
            self.assertIn(":degree-requirements:", related["requirement_id"])


if __name__ == "__main__":
    unittest.main()
