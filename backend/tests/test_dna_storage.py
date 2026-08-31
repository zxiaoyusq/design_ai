"""图片文件存储与结果配对测试。"""

import asyncio
import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.services.dna import storage


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(105, 91, 210)).save(buffer, format="PNG")
    return buffer.getvalue()


class DnaStorageTestCase(unittest.TestCase):
    def test_uploaded_image_survives_directory_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            uploads_dir = Path(temporary_dir) / "uploads"
            upload = UploadFile(
                file=BytesIO(png_bytes()),
                filename="folder/产品 图.png",
                headers=Headers({"content-type": "image/png"}),
            )
            with patch.object(storage, "UPLOADS_DIR", uploads_dir):
                saved = asyncio.run(
                    storage.save_uploaded_image(upload, "folder/产品 图.png")
                )
                scanned = storage.list_uploaded_images()
                metadata, image_path = storage.get_uploaded_image(saved.id)

            self.assertEqual(scanned[0].id, saved.id)
            self.assertEqual(metadata.relative_path, "folder/产品 图.png")
            self.assertEqual(image_path.name, "产品_图.png")
            self.assertTrue(image_path.is_file())

    def test_non_image_upload_is_rejected(self) -> None:
        upload = UploadFile(file=BytesIO(b"not-an-image"), filename="fake.png")
        with self.assertRaisesRegex(storage.ImageStorageError, "可读取的图片"):
            asyncio.run(storage.save_uploaded_image(upload))

    def test_result_list_requires_business_view_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            results_dir = Path(temporary_dir)
            result_id = "20260831_120000_product_design_dna"
            (results_dir / f"{result_id}.json").write_text("{}", encoding="utf-8")
            business = {
                "object": {"category": "智能手机"},
                "style": {"primary": {"level_2": "现代简致"}},
                "design_summary": "简洁、克制的现代产品。",
            }
            (results_dir / f"{result_id}_business_view.json").write_text(
                json.dumps(business, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(storage, "RESULTS_DIR", results_dir):
                storage.save_result_trace(
                    result_id,
                    {"model_id": "gpt-5.6-terra-20260820"},
                )
                summaries = storage.list_results()
                detail = storage.load_result(result_id, "business")

            self.assertEqual(summaries[0]["image_name"], "product")
            self.assertEqual(summaries[0]["primary_style"], "现代简致")
            self.assertEqual(detail["design_summary"], business["design_summary"])
            self.assertEqual(detail["model_id"], "gpt-5.6-terra-20260820")
            self.assertEqual(
                detail["schema_version"],
                storage.BUSINESS_VIEW_SCHEMA_VERSION,
            )

    def test_result_trace_is_saved_outside_skill_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            results_dir = Path(temporary_dir)
            result_id = "20260831_120000_product_design_dna"
            with patch.object(storage, "RESULTS_DIR", results_dir):
                path = storage.save_result_trace(
                    result_id,
                    {"model_id": "gpt-5.6-terra-20260820"},
                )

            self.assertEqual(path.parent.name, ".metadata")
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["model_id"],
                "gpt-5.6-terra-20260820",
            )

    def test_deleting_upload_preserves_result_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            uploads_dir = root / "uploads"
            results_dir = root / "result"
            upload = UploadFile(file=BytesIO(png_bytes()), filename="sample.png")
            result_id = "20260831_120000_sample_design_dna"
            with (
                patch.object(storage, "UPLOADS_DIR", uploads_dir),
                patch.object(storage, "RESULTS_DIR", results_dir),
            ):
                saved = asyncio.run(storage.save_uploaded_image(upload))
                _, source_path = storage.get_uploaded_image(saved.id)
                (results_dir / f"{result_id}.json").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (results_dir / f"{result_id}.json").write_text("{}", encoding="utf-8")
                (results_dir / f"{result_id}_business_view.json").write_text(
                    "{}", encoding="utf-8"
                )
                storage.save_result_trace(
                    result_id,
                    {
                        "input_image": {
                            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest()
                        }
                    },
                )

                storage.delete_uploaded_image(saved.id)
                thumbnail_path, content_type = storage.get_result_image(result_id)

            self.assertFalse(uploads_dir.joinpath(saved.id).exists())
            self.assertTrue(thumbnail_path.is_file())
            self.assertEqual(content_type, "image/webp")

    def test_delete_result_removes_all_owned_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            results_dir = Path(temporary_dir)
            result_id = "20260831_120000_sample_design_dna"
            full_path = results_dir / f"{result_id}.json"
            business_path = results_dir / f"{result_id}_business_view.json"
            full_path.write_text("{}", encoding="utf-8")
            business_path.write_text("{}", encoding="utf-8")
            with patch.object(storage, "RESULTS_DIR", results_dir):
                trace_path = storage.save_result_trace(result_id, {})
                image_path = results_dir / "source.png"
                image_path.write_bytes(png_bytes())
                thumbnail_path = storage.save_result_image(result_id, image_path)
                storage.delete_result(result_id)

            self.assertFalse(full_path.exists())
            self.assertFalse(business_path.exists())
            self.assertFalse(trace_path.exists())
            self.assertFalse(thumbnail_path.exists())


if __name__ == "__main__":
    unittest.main()
