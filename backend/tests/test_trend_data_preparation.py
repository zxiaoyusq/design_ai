"""趋势来源表的字段保真、图片归属与可重复下载验证。"""

import hashlib
import io
import json
import struct
import tempfile
import threading
import unittest
import zlib
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from openpyxl import Workbook

from scripts.prepare_trend_data import DESCRIPTION_FIELDS, _download_url, download_image, main, read_trends


EXPECTED_DESCRIPTION_FIELDS = (
    "title_zh",
    "summary_zh",
    "image_url",
    "image_width",
    "image_height",
    "primary_category",
    "subcategory",
    "tags",
    "confidence",
    "language_original",
    "release_time",
    "clust_status",
    "local_vl_info",
)


def make_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    """生成完整 PNG，以便校验真实解码而非仅检查扩展名或文件头。"""

    def chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload))
        )

    pixels = (b"\x00" + bytes(color) * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class TrendWorkbookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.source = Path(self.temp_directory.name) / "文章信息表.xlsx"
        self.headers = ["id", *EXPECTED_DESCRIPTION_FIELDS]
        self.row = {
            "id": "0012",
            "title_zh": "可持续材料趋势",
            "summary_zh": "保留中文与换行。\n第二段总结。",
            "image_url": "https://example.test/a.png || || https://example.test/b.png||https://example.test/a.png",
            "image_width": "640||800||640",
            "image_height": "480||600||480",
            "primary_category": "产品设计",
            "subcategory": "家具，灯具,配饰",
            "tags": "自然,再生材料，柔和",
            "confidence": 0.91,
            "language_original": "en",
            "release_time": datetime(2026, 9, 1, 10, 20, 30),
            "clust_status": 1,
            "local_vl_info": '{"主色":"绿色","置信度":0.9}',
        }

    def write_workbook(self, rows: list[dict], headers: list[str] | None = None) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "趋势信息"
        selected_headers = self.headers if headers is None else headers
        worksheet.append(selected_headers)
        for row in rows:
            worksheet.append([row.get(field) for field in selected_headers])
        workbook.save(self.source)
        workbook.close()

    def test_preserves_descriptions_and_each_image_occurrence(self) -> None:
        self.write_workbook([self.row, {}, {**self.row, "id": "0013"}])

        records, sheet_name = read_trends(self.source)

        self.assertEqual(tuple(DESCRIPTION_FIELDS), EXPECTED_DESCRIPTION_FIELDS)
        self.assertEqual(sheet_name, "趋势信息")
        self.assertEqual([record["source_row"] for record in records], [2, 4])
        record = records[0]
        self.assertEqual(record["id"], "0012")
        for field in ("title_zh", "summary_zh", "image_url", "image_width", "image_height"):
            self.assertEqual(record[field], self.row[field])
        self.assertTrue(all(field in record for field in EXPECTED_DESCRIPTION_FIELDS))
        self.assertEqual(record["subcategory"], ["家具", "灯具", "配饰"])
        self.assertEqual(record["tags"], ["自然", "再生材料", "柔和"])
        self.assertEqual(record["confidence"], 0.91)
        self.assertIsInstance(record["confidence"], (int, float))
        self.assertEqual(record["clust_status"], 1)
        self.assertIsInstance(record["clust_status"], int)
        self.assertEqual(record["release_time"], "2026-09-01T10:20:30")
        self.assertEqual(record["local_vl_info"], {"主色": "绿色", "置信度": 0.9})
        expected_urls = [
            "https://example.test/a.png",
            "https://example.test/b.png",
            "https://example.test/a.png",
        ]
        self.assertEqual([entry["url"] for entry in record["images"]], expected_urls)
        for index, entry in enumerate(record["images"], start=1):
            self.assertEqual(entry["image_id"], f"0012_{index:03d}")
            self.assertEqual(entry["trend_id"], "0012")
            self.assertEqual(entry["index"], index)
            self.assertIsNone(entry["local_path"])
            self.assertEqual(entry["status"], "pending")
        # 整个记录需可直接送入 JSON 序列化，不残留日期等工作簿对象。
        json.dumps(records, ensure_ascii=False, allow_nan=False)

    def test_invalid_local_vl_info_keeps_source_and_warns(self) -> None:
        self.write_workbook([{**self.row, "local_vl_info": "原始非 JSON 描述", "image_url": None}])

        records, _ = read_trends(self.source, sheet_name="趋势信息", limit=1)

        self.assertEqual(records[0]["local_vl_info"], "原始非 JSON 描述")
        self.assertTrue(records[0]["warnings"])
        self.assertEqual(records[0]["images"], [])

    def test_missing_description_header_is_rejected(self) -> None:
        self.write_workbook([self.row], [field for field in self.headers if field != "summary_zh"])
        with self.assertRaises(ValueError):
            read_trends(self.source)

    def test_duplicate_header_is_rejected(self) -> None:
        self.write_workbook([self.row], [*self.headers, "title_zh"])
        with self.assertRaises(ValueError):
            read_trends(self.source)

    def test_missing_or_duplicate_id_is_rejected(self) -> None:
        scenarios = (
            ([{**self.row, "id": None}], self.headers),
            ([self.row], [field for field in self.headers if field != "id"]),
            ([self.row, self.row], self.headers),
        )
        for rows, headers in scenarios:
            with self.subTest(rows=len(rows), has_id="id" in headers):
                self.write_workbook(rows, headers)
                with self.assertRaises(ValueError):
                    read_trends(self.source)

    def test_limit_keeps_source_order_and_still_validates_all_ids(self) -> None:
        self.write_workbook([self.row, {**self.row, "id": "0013"}])
        records, _ = read_trends(self.source, limit=1)
        self.assertEqual([record["id"] for record in records], ["0012"])

        self.write_workbook([self.row, self.row])
        with self.assertRaises(ValueError):
            read_trends(self.source, limit=1)


class TrendImageDownloadTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.png = make_png(2, 3, (10, 180, 40))
        cls.other_png = make_png(4, 1, (180, 10, 40))
        cls.requests = Counter()

        class ImageHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                cls.requests[self.path] += 1
                status = 200
                content_type = "image/png"
                if self.path == "/missing.png":
                    status, body = 404, b"not found"
                elif self.path == "/retry.png" and cls.requests[self.path] == 1:
                    status, body = 503, b"try again"
                elif self.path == "/html.png":
                    content_type, body = "text/html", b"<html>not an image</html>"
                elif self.path == "/broken.png":
                    body = b"\x89PNG\r\n\x1a\ntruncated"
                elif self.path == "/other.png":
                    body = cls.other_png
                else:
                    body = cls.png
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        cls.server.daemon_threads = True
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=3)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.output_dir = Path(self.temp_directory.name)

    def entry(self, endpoint: str, index: int = 1) -> dict:
        return {
            "image_id": f"0012_{index:03d}",
            "trend_id": "0012",
            "url": self.base_url + endpoint,
            "index": index,
            "local_path": None,
            "status": "pending",
        }

    def test_download_metadata_and_cache_reuse_then_corruption_recovery(self) -> None:
        entry = self.entry("/cache.png")
        result = download_image(entry, self.output_dir, timeout=3, retries=0)

        self.assertEqual(result["status"], "downloaded", result)
        for field in ("image_id", "trend_id", "url", "index"):
            self.assertEqual(result[field], entry[field])
        self.assertEqual((result["width"], result["height"]), (2, 3))
        self.assertEqual(result["size_bytes"], len(self.png))
        self.assertEqual(result["sha256"], hashlib.sha256(self.png).hexdigest())
        relative_path = Path(result["local_path"])
        self.assertFalse(relative_path.is_absolute())
        local_path = self.output_dir / relative_path
        self.assertEqual(local_path.read_bytes(), self.png)

        requests_before = self.requests["/cache.png"]
        cached = download_image(entry, self.output_dir, timeout=3, retries=0)
        self.assertEqual(cached["status"], "downloaded", cached)
        self.assertEqual(cached["local_path"], result["local_path"])
        self.assertEqual(self.requests["/cache.png"], requests_before)

        local_path.write_bytes(b"corrupted cache")
        restored = download_image(entry, self.output_dir, timeout=3, retries=0)
        self.assertEqual(restored["status"], "downloaded", restored)
        self.assertEqual(local_path.read_bytes(), self.png)
        self.assertGreater(self.requests["/cache.png"], requests_before)

    def test_url_change_and_repeated_image_do_not_mix_associations(self) -> None:
        first = download_image(self.entry("/original.png"), self.output_dir, timeout=3, retries=0)
        changed = download_image(self.entry("/other.png"), self.output_dir, timeout=3, retries=0)
        repeated = download_image(self.entry("/original.png", index=2), self.output_dir, timeout=3, retries=0)

        for result in (first, changed, repeated):
            self.assertEqual(result["status"], "downloaded", result)
        self.assertNotEqual(first["local_path"], changed["local_path"])
        self.assertEqual((changed["width"], changed["height"]), (4, 1))
        self.assertEqual((self.output_dir / first["local_path"]).read_bytes(), self.png)
        self.assertEqual((self.output_dir / changed["local_path"]).read_bytes(), self.other_png)
        self.assertEqual(repeated["image_id"], "0012_002")
        self.assertEqual(repeated["index"], 2)
        self.assertEqual((self.output_dir / repeated["local_path"]).read_bytes(), self.png)

    def test_non_images_http_failures_and_oversized_responses_stay_failed(self) -> None:
        for endpoint, maximum in (
            ("/html.png", 1024),
            ("/broken.png", 1024),
            ("/missing.png", 1024),
            ("/large.png", 10),
        ):
            with self.subTest(endpoint=endpoint):
                entry = self.entry(endpoint)
                result = download_image(entry, self.output_dir, timeout=3, retries=0, max_bytes=maximum)
                self.assertEqual(result["status"], "failed", result)
                self.assertIsNone(result["local_path"])
                self.assertTrue(result["error"])
                self.assertEqual(result["image_id"], entry["image_id"])
                self.assertEqual(result["url"], entry["url"])

    def test_transient_http_failure_is_retried(self) -> None:
        result = download_image(self.entry("/retry.png"), self.output_dir, timeout=3, retries=1)

        self.assertEqual(result["status"], "downloaded", result)
        self.assertGreaterEqual(self.requests["/retry.png"], 2)

    def write_source_workbook(self) -> Path:
        source = self.output_dir / "原始文章.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "趋势信息"
        fields = ["id", *EXPECTED_DESCRIPTION_FIELDS]
        row = {
            "id": "0012",
            "title_zh": "材料趋势",
            "summary_zh": "一条趋势包含一张有效图片和一张失效图片。",
            "image_url": f"{self.base_url}/main.png||{self.base_url}/missing.png",
        }
        worksheet.append(fields)
        worksheet.append([row.get(field) for field in fields])
        workbook.save(source)
        workbook.close()
        return source

    def test_main_writes_consistent_indexes_report_source_and_image_links(self) -> None:
        source = self.write_source_workbook()
        destination = self.output_dir / "prepared"
        with redirect_stdout(io.StringIO()):
            exit_code = main([
                "--input", str(source), "--output", str(destination),
                "--workers", "2", "--retries", "0", "--timeout", "3",
            ])

        self.assertEqual(exit_code, 2)
        document = json.loads((destination / "trends.json").read_text(encoding="utf-8"))
        lines = [
            json.loads(line)
            for line in (destination / "trends.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        report = json.loads((destination / "download_report.json").read_text(encoding="utf-8"))
        self.assertEqual(document["trends"], lines)
        self.assertEqual(document["counts"], report["counts"])
        expected_counts = {"trends": 1, "image_references": 2, "downloaded": 1, "failed": 1, "pending": 0}
        for field, value in expected_counts.items():
            self.assertEqual(document["counts"][field], value)

        source_info = document["source"]
        self.assertEqual(source_info, report["source"])
        source_copy = destination / source_info["file"]
        self.assertEqual(source_copy.parent.name, "source")
        self.assertEqual(source_copy.read_bytes(), source.read_bytes())
        self.assertEqual(source_info["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(source_info["description_fields"], list(EXPECTED_DESCRIPTION_FIELDS))

        trend = lines[0]
        self.assertTrue(all(field in trend for field in EXPECTED_DESCRIPTION_FIELDS))
        self.assertEqual(trend["id"], "0012")
        self.assertEqual(trend["source_row"], 2)
        images = trend["images"]
        self.assertEqual([image["image_id"] for image in images], ["0012_001", "0012_002"])
        self.assertEqual([image["trend_id"] for image in images], [trend["id"], trend["id"]])
        self.assertEqual([image["url"] for image in images], trend["image_url"].split("||"))
        self.assertEqual([image["status"] for image in images], ["downloaded", "failed"])
        self.assertEqual((destination / images[0]["local_path"]).read_bytes(), self.png)
        self.assertIsNone(images[1]["local_path"])
        self.assertEqual(report["failures"], [images[1]])

    def test_main_dry_run_does_not_create_output_or_download(self) -> None:
        source = self.write_source_workbook()
        destination = self.output_dir / "dry-run"
        with patch("scripts.prepare_trend_data.download_image") as downloader, redirect_stdout(io.StringIO()):
            exit_code = main(["--input", str(source), "--output", str(destination), "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(destination.exists())
        downloader.assert_not_called()

    def test_materialdistrict_download_requests_original_and_keeps_source_url(self) -> None:
        original = "https://media.materialdistrict.com/uploads/material.png?version=2"
        wrapped = "https://materialdistrict.com/_next/image?" + urlencode({"url": original, "w": 640, "q": 75})
        response = io.BytesIO(self.png)
        response.url = original
        entry = {**self.entry("/placeholder"), "url": wrapped}

        self.assertEqual(_download_url(wrapped), original)
        with patch("scripts.prepare_trend_data.urlopen", return_value=response) as opener:
            result = download_image(entry, self.output_dir, timeout=3, retries=0)

        self.assertEqual(result["status"], "downloaded", result)
        self.assertEqual(opener.call_args.args[0].full_url, original)
        self.assertEqual(result["url"], wrapped)
        self.assertEqual(result["download_url"], original)
        self.assertEqual(result["resolved_url"], original)
        self.assertEqual((self.output_dir / result["local_path"]).read_bytes(), self.png)

    def test_image_url_unwrapping_is_limited_to_known_wrapper_and_media_host(self) -> None:
        for host, original in (
            ("other.example", "https://media.materialdistrict.com/image.png"),
            ("materialdistrict.com", "https://other.example/image.png"),
            ("materialdistrict.com", "http://media.materialdistrict.com/image.png"),
        ):
            with self.subTest(host=host, original=original):
                wrapped = f"https://{host}/_next/image?" + urlencode({"url": original})
                self.assertEqual(_download_url(wrapped), wrapped)

    def test_unwrapped_unicode_path_is_encoded_without_double_escaping(self) -> None:
        original = "https://media.materialdistrict.com/uploads/© 图%20片.jpg?v=2&width=640"
        wrapped = "https://materialdistrict.com/_next/image/?" + urlencode({"url": original})
        encoded = "https://media.materialdistrict.com/uploads/%C2%A9%20%E5%9B%BE%20%E7%89%87.jpg?v=2&width=640"
        self.assertEqual(_download_url(wrapped), encoded)
        self.assertEqual(_download_url(encoded), encoded)


if __name__ == "__main__":
    unittest.main()
