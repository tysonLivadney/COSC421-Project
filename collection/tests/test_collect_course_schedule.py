import http.client
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collection import collect_course_schedule as collector


class CourseScheduleCollectorTests(unittest.TestCase):
    def test_build_url_encodes_json_api_filters(self) -> None:
        url = collector.build_url(
            "https://example.test/jsonapi",
            "node/section",
            {"filter[field_is_visible]": "1", "page[limit]": "50"},
        )
        self.assertEqual(
            url,
            "https://example.test/jsonapi/node/section?"
            "filter%5Bfield_is_visible%5D=1&page%5Blimit%5D=50",
        )

    def test_collect_follows_pagination_and_preserves_response_bytes(self) -> None:
        first_body = json.dumps(
            {
                "data": [{"type": "node--section", "id": "one"}],
                "links": {"next": "https://example.test/page/2"},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        second_body = b'{"data":[{"type":"node--section","id":"two"}]}'
        responses = {
            "https://example.test/jsonapi/node/section?page%5Blimit%5D=1": first_body,
            "https://example.test/page/2": second_body,
        }
        attempts: dict[str, int] = {}

        def fake_download(url: str, **_: object) -> collector.HttpResponse:
            attempts[url] = attempts.get(url, 0) + 1
            if url == "https://example.test/page/2" and attempts[url] == 1:
                raise http.client.IncompleteRead(b"partial", 10)
            return collector.HttpResponse(
                body=responses[url],
                final_url=url,
                status=200,
                headers={"Content-Type": "application/vnd.api+json"},
            )

        with tempfile.TemporaryDirectory(
            dir=Path(__file__).parent
        ) as temporary_directory:
            original_root = collector.PROJECT_ROOT
            collector.PROJECT_ROOT = Path(temporary_directory)
            try:
                settings = {
                    "base_url": "https://example.test/jsonapi",
                    "raw_directory": "raw",
                    "retry_attempts": 2,
                    "retry_delay_seconds": 0,
                    "datasets": {
                        "sections": {
                            "path": "node/section",
                            "query": {"page[limit]": "1"},
                        }
                    },
                }
                run_directory = collector.collect(
                    settings,
                    collected_at=datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
                    downloader=fake_download,
                    progress=lambda _: None,
                )
            finally:
                collector.PROJECT_ROOT = original_root

            first_file = run_directory / "sections" / "page_0001.json"
            second_file = run_directory / "sections" / "page_0002.json"
            self.assertEqual(first_file.read_bytes(), first_body)
            self.assertEqual(second_file.read_bytes(), second_body)

            manifest = json.loads(
                (run_directory / "manifest.json").read_text(encoding="utf-8")
            )
            pages = manifest["datasets"][0]["pages"]
            self.assertEqual(len(pages), 2)
            self.assertEqual(pages[1]["primary_resource_count"], 1)
            self.assertEqual(attempts["https://example.test/page/2"], 2)


if __name__ == "__main__":
    unittest.main()
