"""微型离线夹具：只发布 LIKE / ENJOY 图片，不读取图片内容。"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from lean_images import linked_image_refs, selected_user_images
from lean_output import publish


class LeanImagesTests(unittest.TestCase):
    def test_only_positive_user_images_are_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "linked.jpg").write_bytes(b"not actual pixels")
            (root / "liked.jpg").write_bytes(b"not actual pixels")
            (root / "disliked.jpg").write_bytes(b"not actual pixels")
            (root / "untagged.jpg").write_bytes(b"not actual pixels")
            qa = {"id": "a", "ai_analysis": "柔和表面让人放松。", "ref_pic_links": [
                {"code": "PPT-ONE", "image_ids": ["one"], "local_paths": ["linked.jpg"],
                 "emotion_tag": "LIKE"},
                {"code": "PPT-TWO", "image_ids": ["two"], "local_paths": ["disliked.jpg"],
                 "emotion_tag": "DISLIKE"},
                {"code": "PPT-THREE", "image_ids": ["three"], "local_paths": ["untagged.jpg"]}]}
            users = [{"id": "u1", "aesthetic_research": [qa], "image_preferences": [
                {"image_id": "one", "local_path": "./linked.jpg", "emotion_tag": "LIKE"},
                {"image_id": "liked", "local_path": "liked.jpg", "emotion_tag": "ENJOY"},
                {"image_id": "two", "local_path": "disliked.jpg", "emotion_tag": "DISLIKE"}],
                "ppt_images": [{"image_id": "three", "local_path": "untagged.jpg"}]}]
            inventory = selected_user_images(users, root)
            self.assertEqual(len(inventory), 2)
            self.assertEqual(len(inventory[0]["source_locations"]), 2)
            self.assertEqual(inventory[0]["image_ids"], ["one"])
            self.assertEqual(inventory[0]["emotion_tags"], ["LIKE"])
            source = {"id": "user:u1:user_qa:a", "kind": "user_qa", "user_id": "u1",
                      "fields": {"ai_analysis": qa["ai_analysis"]},
                      "image_refs": linked_image_refs(qa, root, "user:u1:user_qa:a")}
            sources = {"T00001": {"id": "trend:t", "kind": "trend", "fields": {},
                                   "clustering_label": "亲和触感", "image_refs": []}, "U000001": source}
            manifest = {"project_root": str(root), "counts": {"users_with_text": 1},
                        "user_image_inventory": inventory,
                        "trend_categories": [{"label": "亲和触感", "article_count": 1},
                                             {"label": "透明表达", "article_count": 1}]}
            run = root / "run"
            publish(run, manifest, sources, "## 柔和的安心感\n方向正文。[T00001 U000001]")
            result = json.loads((run / "high_potential_trends.json").read_text())
            card = result["trends"][0]
            self.assertEqual(card["clustering_labels"], ["亲和触感"])
            self.assertEqual(result["trend_categories"][1]["trend_ids"], [])
            self.assertEqual(len(card["image_refs"]), 1)
            self.assertEqual(card["image_refs"][0]["association_level"], "explicit_record_link")
            self.assertEqual(card["image_refs"][0]["absolute_path"], str(root / "linked.jpg"))
            self.assertEqual(result["user_image_filter"], "like_or_enjoy")
            self.assertEqual(len(result["user_images"]), 2)
            self.assertTrue(result["user_images"][0]["linked_to_result"])
            self.assertFalse(result["user_images"][1]["linked_to_result"])
            images = (run / "image_paths.md").read_text()
            other = images.split("## 其他用户喜欢的图片")[1]
            self.assertIn("liked.jpg", other)
            self.assertNotIn("linked.jpg", other)
            self.assertNotIn("disliked.jpg", images)
            self.assertNotIn("untagged.jpg", images)
            self.assertIn("# 大趋势分类：亲和触感", (run / "report.md").read_text())

    def test_paths_cannot_escape_the_user_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                selected_user_images([{"id": "u1", "local_paths": ["../outside.jpg"],
                                       "emotion_tag": "ENJOY"}], Path(folder))


if __name__ == "__main__":
    unittest.main()
