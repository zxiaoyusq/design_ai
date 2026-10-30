"""已交付情绪板的最小离线投影测试，不调用模型或改写来源产物。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app.services.moodboards.saved_results import SavedMoodboardResults, RUNS, DEFAULT_RESULT_ID


class SavedMoodboardResultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / "data/result/saved-fixture"
        self.folder.mkdir(parents=True)
        self.image = self.root / "data/original.png"
        Image.new("RGB", (20, 16), (40, 70, 100)).save(self.image)
        self.image_sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        unit = {"unit_id": "card-1", "image_id": "image-1", "image_sha256": self.image_sha,
                "local_path": str(self.image), "display_bbox": [.2, .25, .5, .5],
                "category": "灯具", "subject": {"identity": "主灯具"}, "sources": [{"article_id": "A1"}]}
        observations = self.write("observations.json", {"units": [unit]})
        answer = self.write("call/answer.json", {"groups": [{"member_ids": ["card-1"]}]})
        self.write("call/receipt.json", {"status": "completed", "requested_model": "fake-recorded-model",
                  "answer_ref": self.ref(answer)})
        self.board = {"board_id": "B1", "title": "已保存测试板", "dominant_relation": "块面、边界与柔散反光",
                      "provenance": {"path": str(answer.parent), "status": "completed", "answer_ref": self.ref(answer)},
                      "common_relations": {"palette": "主辅色角色"}, "member_evidence": [{"card_id": "card-1", "support": "真实成员依据"}],
                      "members": [{"unit_id": "card-1", "image_id": "image-1", "sha256": self.image_sha,
                                   "display_bbox": unit["display_bbox"]}],
                      "constraints": {"quantity_policy": {"minimum": 5, "maximum": 10}}}
        self.boards_path = self.write("boards.json", {"boards": [self.board], "summary": {"cards": 1},
                                                       "input_refs": {"observations": self.ref(observations)}})
        assessment = self.write("assessment.json", {"boards": [{"board_id": "B1", "result": "supported_in_current_context",
                                                       "observation": "保留原有判断"}]})
        self.manifest_path = self.write("manifest.json", {"created_at": "2026-10-12T01:30:00+08:00",
                                     "inputs": {"boards.json": self.ref(self.boards_path)}, "assessment_ref": self.ref(assessment)})
        spec = {"folder": Path("data/result/saved-fixture"), "manifest": "manifest.json", "boards": "boards.json",
                "title": "已交付测试运行", "kind": "bounded", "status_label": "原板面对照支持", "notes": []}
        registry = patch.dict(RUNS, {DEFAULT_RESULT_ID: spec}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.feedback_path = self.root / "ref/问题反馈/情绪版选图.json"
        self.feedback_path.parent.mkdir(parents=True)
        self.feedback = {"schema_version": "prism.image_rejection_feedback.v1", "collection_identity": "collection-1", "records": [{
            "board_id": "bounded-1", "unit_id": "card-1", "image_sha256": self.image_sha,
            "roi": unit["display_bbox"], "status": "rejected", "reason": "当前组合不协调", "updated_at": "2026-10-13"}]}
        self.feedback_path.write_text(json.dumps(self.feedback), encoding="utf-8")
        collection = self.root / "frontend/public/visual-workflow/moodboard-image-review-20261012/deployment-manifest.json"
        collection.parent.mkdir(parents=True)
        collection.write_text(json.dumps({"identity": "collection-1"}), encoding="utf-8")
        self.service = SavedMoodboardResults(self.root)

    def write(self, name, document):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def ref(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_structured_result_keeps_raw_members_and_applies_exact_human_feedback(self):
        before = self.boards_path.read_bytes()
        catalog = self.service.list()
        self.assertEqual(catalog["default_result_id"], DEFAULT_RESULT_ID)
        self.assertEqual(catalog["results"][0]["image_count"], 1)
        result = self.service.get(DEFAULT_RESULT_ID)
        board = result["boards"][0]
        self.assertEqual(board["status_label"], "有人工排除 · 待修改")
        self.assertEqual(board["feedback_summary"], {"rejected": 1, "unmarked": 0})
        self.assertEqual(board["members"][0]["reason"], "真实成员依据")
        self.assertEqual(board["members"][0]["source_label"], "文章 A1")
        self.assertIn("原有审阅：当前板面对照支持", board["review_notes"][0])
        self.assertEqual(result["model_id"], "fake-recorded-model")
        self.assertEqual(len(result["trace"]["feedback_refs"]), 2)
        self.assertEqual(self.service.download(DEFAULT_RESULT_ID).read_bytes(), before)

    def test_image_replays_frozen_roi_and_original_bytes(self):
        member = self.service.get(DEFAULT_RESULT_ID)["boards"][0]["members"][0]
        cropped = self.service.image(DEFAULT_RESULT_ID, member["id"])
        with Image.open(cropped) as image:
            self.assertEqual(image.size, (10, 8))
        self.assertEqual(self.service.image(DEFAULT_RESULT_ID, member["id"], original=True).read_bytes(), self.image.read_bytes())
        Image.new("RGB", (10, 8), "red").save(cropped)
        with self.assertRaisesRegex(ValueError, "缓存的取景像素"):
            self.service.image(DEFAULT_RESULT_ID, member["id"])

    def test_registration_and_image_tokens_do_not_accept_arbitrary_paths(self):
        with self.assertRaises(FileNotFoundError):
            self.service.get("../../private")
        with self.assertRaises(FileNotFoundError):
            self.service.image(DEFAULT_RESULT_ID, "../../private")

    def test_feedback_cannot_move_to_another_roi_or_collection(self):
        changed = deepcopy(self.feedback)
        changed["records"][0]["roi"] = [0, 0, 1, 1]
        self.feedback_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "未精确对应"):
            self.service.get(DEFAULT_RESULT_ID)
        changed["collection_identity"] = "other-collection"
        self.feedback_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "集合的身份不匹配"):
            self.service.get(DEFAULT_RESULT_ID)

    def test_tampered_manifest_bound_boards_and_source_pixels_are_rejected(self):
        member = self.service.get(DEFAULT_RESULT_ID)["boards"][0]["members"][0]
        self.image.write_bytes(b"changed pixels")
        with self.assertRaisesRegex(ValueError, "字节与冻结记录不一致"):
            self.service.image(DEFAULT_RESULT_ID, member["id"])
        self.boards_path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "来源 SHA 不匹配"):
            self.service.get(DEFAULT_RESULT_ID)


if __name__ == "__main__":
    unittest.main()
