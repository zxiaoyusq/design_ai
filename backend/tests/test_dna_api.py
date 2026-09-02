"""DNA 上传与任务 API 测试。"""

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.dna import storage


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color=(220, 180, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


class DnaApiTestCase(unittest.TestCase):
    def test_upload_list_preview_and_create_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            uploads_dir = Path(temporary_dir) / "uploads"
            with (
                patch.object(storage, "UPLOADS_DIR", uploads_dir),
                patch("app.services.dna.tasks.extraction_task_manager.run"),
            ):
                client = TestClient(app)
                response = client.post(
                    "/api/v1/dna/images",
                    files={"files": ("sample.png", png_bytes(), "image/png")},
                    data={"paths": "folder/sample.png"},
                )
                self.assertEqual(response.status_code, 201)
                image = response.json()[0]

                listed = client.get("/api/v1/dna/images")
                preview = client.get(image["preview_url"])
                task = client.post(
                    "/api/v1/dna/extractions",
                    json={
                        "image_ids": [image["id"]],
                        "model_id": "claude-opus-5-20260820",
                        "prompt": "关注色彩",
                    },
                )

            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()), 1)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(task.status_code, 202)
            self.assertEqual(task.json()["items"][0]["status"], "pending")
            self.assertEqual(task.json()["items"][0]["stage"], "queued")
            self.assertEqual(
                task.json()["items"][0]["events"][0]["message"],
                "已加入提取队列",
            )

    def test_uploaded_image_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            uploads_dir = Path(temporary_dir) / "uploads"
            results_dir = Path(temporary_dir) / "results"
            with (
                patch.object(storage, "UPLOADS_DIR", uploads_dir),
                patch.object(storage, "RESULTS_DIR", results_dir),
            ):
                client = TestClient(app)
                uploaded = client.post(
                    "/api/v1/dna/images",
                    files={"files": ("delete-me.png", png_bytes(), "image/png")},
                ).json()[0]
                deleted = client.delete(f"/api/v1/dna/images/{uploaded['id']}")
                listed = client.get("/api/v1/dna/images")
                preview = client.get(uploaded["preview_url"])

            self.assertEqual(deleted.status_code, 204)
            self.assertEqual(listed.json(), [])
            self.assertEqual(preview.status_code, 404)

    def test_result_thumbnail_and_delete_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            results_dir = Path(temporary_dir) / "results"
            results_dir.mkdir(parents=True)
            result_id = "20260831_120000_sample_design_dna"
            (results_dir / f"{result_id}.json").write_text("{}", encoding="utf-8")
            (results_dir / f"{result_id}_business_view.json").write_text(
                '{"object":{"category":"产品"}}', encoding="utf-8"
            )
            source = Path(temporary_dir) / "sample.png"
            source.write_bytes(png_bytes())
            with patch.object(storage, "RESULTS_DIR", results_dir):
                storage.save_result_image(result_id, source)
                client = TestClient(app)
                listed = client.get("/api/v1/dna/results")
                preview_url = listed.json()[0]["preview_url"]
                preview = client.get(preview_url)
                deleted = client.delete(f"/api/v1/dna/results/{result_id}")
                missing = client.get(f"/api/v1/dna/results/{result_id}")

            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.headers["content-type"], "image/webp")
            self.assertEqual(deleted.status_code, 204)
            self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
