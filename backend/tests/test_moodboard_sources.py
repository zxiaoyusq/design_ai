"""用微型原图和注册源验证选材范围；不启动模型或全量读取图库。"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app.services.moodboards.sources import MoodboardSources


class MoodboardSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result_id = "web_" + "a" * 32
        self.folder = self.root / "data/result/high_trend" / self.result_id
        self.folder.mkdir(parents=True)
        self.image = self.root / "data/trend_data/images/a.png"
        self.image.parent.mkdir(parents=True)
        Image.new("RGB", (3, 2), "red").save(self.image)
        self.copy = self.image.with_name("copy.png")
        self.copy.write_bytes(self.image.read_bytes())
        self.sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.write("web_task.json", {"id": self.result_id, "status": "completed", "created_at": "2026-10-21"})
        self.write("sources.json", {"T1": {"id": "article-1", "kind": "trend"}})
        self.result = {"trends": [
            {"id": "D1", "title": "趋势A", "image_refs": [self.ref("a", self.image)]},
            {"id": "D2", "title": "趋势B", "associated_image_refs": [self.ref("alias", self.copy)],
             "visual_extension_image_refs": [self.ref("missing", self.image.with_name("missing.png"))]},
        ], "user_images": [{"path": "/not-related.png"}]}
        self.write("high_potential_trends.json", self.result)
        self.service = MoodboardSources(self.root, native_results={})

    def write(self, name, value):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def ref(image_id, path):
        return {"image_id": image_id, "absolute_path": str(path), "source_record_id": "article-1",
                "evidence_ids": ["T1"], "role": "trend_reference"}

    def test_catalog_no_image_hash_and_scope_merges_all_selected_directions(self):
        with patch("app.services.moodboards.sources._sha", side_effect=AssertionError("catalog must not hash")):
            catalog = self.service.catalog()
        self.assertEqual(len(catalog["results"]), 1)
        self.assertEqual(catalog["results"][0]["directions"][1]["image_reference_count"], 2)
        scope = self.service.scope(self.result_id, ["D1", "D2"])
        self.assertEqual(len(scope["images"]), 1)
        item = scope["images"][0]
        self.assertEqual(item["sha256"], self.sha)
        self.assertEqual(item["aliases"], ["a", "alias"])
        self.assertEqual(item["direction_ids"], ["D1", "D2"])
        self.assertEqual(len(item["origins"]), 2)
        self.assertEqual(len(scope["missing"]), 1)
        self.assertEqual(scope["counts"]["reference_count"], 3)
        self.assertEqual(len(scope["source_refs"]), 3)
        selected = self.service.scope(self.result_id, ["D2"])
        self.assertTrue(selected["images"][0]["preview_url"].endswith("/images/1"))

    def test_human_rejection_keeps_sha_excluded_even_if_result_revision_changed(self):
        self.write("image_review/review.json", {"task_id": self.result_id, "revision": 2,
            "source_result_sha256": "old", "images": [{"sha256": self.sha, "retained": False}]})
        scope = self.service.scope(self.result_id, ["D1", "D2"])
        self.assertEqual(scope["images"], [])
        self.assertEqual(scope["excluded"][0]["aliases"], ["a", "alias"])
        self.assertEqual(scope["review_binding"]["revision"], 2)
        self.assertTrue(any("旧版结果" in warning for warning in scope["warnings"]))

    def test_keep_associated_user_and_unknown_but_exclude_explicit_dislike(self):
        user = {**self.ref("user", self.image), "role": "user_reference", "source_record_id": "user-1",
                "evidence_ids": []}
        self.result["trends"][0]["image_refs"] = [user]
        self.write("high_potential_trends.json", self.result)
        scope = self.service.scope(self.result_id, ["D1"])
        self.assertEqual(len(scope["images"]), 1)
        self.assertEqual(scope["images"][0]["origins"][0]["source_kind"], "user")
        user["emotion_tag"] = "ENJOY DISLIKE"
        self.write("high_potential_trends.json", self.result)
        self.assertEqual(len(self.service.scope(self.result_id, ["D1"])["excluded"]), 1)

    def test_path_escape_invalid_direction_and_explicit_fail_are_not_admitted(self):
        outside = self.root / "private.png"
        outside.write_bytes(self.image.read_bytes())
        link = self.image.with_name("escape.png")
        link.symlink_to(outside)
        self.result["trends"][0]["image_refs"] = [self.ref("escape", link)]
        self.write("high_potential_trends.json", self.result)
        self.assertEqual(len(self.service.scope(self.result_id, ["D1"])["missing"]), 1)
        with self.assertRaises(ValueError):
            self.service.scope(self.result_id, ["other"])
        with self.assertRaises(FileNotFoundError):
            self.service.scope("../../private", ["D1"])
        self.result["trends"][0]["image_refs"] = [{**self.ref("failed", self.image), "human_review": {"status": "FAIL"}}]
        self.write("high_potential_trends.json", self.result)
        self.assertEqual(self.service.scope(self.result_id, ["D1"])["images"], [])

    def test_input_digest_changes_when_human_selection_changes(self):
        before = self.service.scope(self.result_id, ["D1"])["input_digest"]
        self.write("image_review/review.json", {"task_id": self.result_id, "revision": 1,
                                             "images": [{"sha256": self.sha, "retained": True}]})
        after = self.service.scope(self.result_id, ["D1"])["input_digest"]
        self.assertNotEqual(before, after)

    def test_concurrent_review_mutation_requires_new_preview(self):
        original = self.service._references

        def changing(*args):
            yield from original(*args)
            self.write("image_review/review.json", {"task_id": self.result_id, "revision": 1,
                         "images": [{"sha256": self.sha, "retained": False}]})

        with patch.object(self.service, "_references", changing):
            with self.assertRaisesRegex(ValueError, "读取期间发生变化"):
                self.service.scope(self.result_id, ["D1"])

    def test_native_uses_all_pages_not_preview_subset(self):
        root = self.root
        image = self.image

        class NativeFixture:
            calls = []

            def get(self):
                return {"id": "native-test", "status": "completed", "result": {"trends": [
                    {"id": "N1", "title": "原生方向", "image_refs": [], "native_detail": {"total_image_count": 101}}]}}

            def images(self, direction_id, page, page_size, scope):
                self.calls.append(page)
                start = (page - 1) * page_size
                return {"total": 101, "items": [{"native_image_key": str(index), "image_id": f"native-{index}",
                    "source_record_id": f"source-{index}", "url": f"/native/{index}"}
                    for index in range(start, min(start + page_size, 101))]}

            def image(self, key):
                return image

        native = NativeFixture()
        service = MoodboardSources(root, native_results={"native-test": native})
        scope = service.scope("native-test", ["N1"])
        self.assertEqual(native.calls, [1, 2])
        self.assertEqual(scope["counts"]["reference_count"], 101)
        self.assertEqual(len(scope["images"][0]["aliases"]), 101)


if __name__ == "__main__":
    unittest.main()
