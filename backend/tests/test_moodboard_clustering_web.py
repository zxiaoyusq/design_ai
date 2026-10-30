"""网页聚类适配的离线契约测试：临时图片、冻结卡替身，不调用真实模型。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from pydantic import ValidationError

from app.schemas.moodboards import MoodboardClusteringRequest, MoodboardScopeRequest
from app.services.moodboards.clustering import MoodboardClusteringManager, read, write
from app.services.dna.preparation import PreparationExecutionError


class FakePrepared:
    """只按传入真实指纹返回设计卡，记录补缺而不运行提取模型。"""

    def __init__(self, images):
        self.images = images
        self.available = {row["sha256"] for row in images}
        self.extractions = []
        self.cards = {row["sha256"]: {
            "card_id": f"card-{index}", "image_id": f"original-{index}", "image_sha256": row["sha256"],
            "local_path": row["path"], "category": "灯具" if index % 2 else "家具",
            "sources": [{"article_id": f"old-article-{index}"}], "display_bbox": [.25, .25, .5, .5],
            "subject": {"identity": f"完整物品 {index}"},
        } for index, row in enumerate(images)}

    def list_prepared_results(self):
        return [{"id": f"prepared-{sha}", "image_sha256": sha, "schema_valid": True,
                 "card_count": 1, "created_at": "2026-10-21", "category": self.cards[sha]["category"]}
                for sha in sorted(self.available)]

    def load_prepared_result(self, result_id):
        sha = result_id.removeprefix("prepared-")
        return {"source": {"image_sha256": sha}, "validation": {"native_evidence_verified": True},
                "cards": [deepcopy(self.cards[sha])]}

    def run_preparation_extraction(self, *, image_path, **kwargs):
        sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        self.extractions.append(sha)
        self.available.add(sha)
        return SimpleNamespace(result_id=f"prepared-{sha}")


class FakeGrouping:
    """模拟 Skill 输出及预算计数；只验证网页传入范围，不替代真实视觉质量验收。"""

    def __init__(self):
        self.inputs = []
        self.call_settings = []

    def ModelCalls(self, out, prompt, **kwargs):
        self.call_settings.append(kwargs)
        return SimpleNamespace(attempted=1)

    def run_pipeline(self, document, calls, **kwargs):
        self.inputs.append({"document": deepcopy(document), "settings": kwargs})
        cards = document["cards"]
        boards = [{"board_id": "board-1", "name": "统一设计情绪候选", "description": "离线模拟候选",
                   "members": [{"unit_id": card["card_id"]} for card in cards[:6]],
                   "constraint_check": {"category_max_ratio": .5}}] if len(cards) >= 6 else []
        return {"boards": {"boards": boards}, "clusters": {"clusters": [], "residual_cards": [],
                "summary": {"status": "completed", "model_calls": 1}}}


class MoodboardClusteringWebTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        images = []
        for index in range(8):
            path = self.root / f"data/trend_data/images/{index}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), (index * 20, 30, 70)).save(path)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            images.append({"image_id": sha, "sha256": sha, "path": str(path), "absolute_path": str(path),
                "aliases": [f"reference-{index}", f"duplicate-{index}"],
                "source_record_ids": [f"article-{index}"], "direction_ids": ["D1", "D2"],
                "origins": [{"article_id": f"article-{index}", "project_id": None, "source_kind": "trend"}],
                "preview_url": f"/source/{index}"})
        self.scope = {"images": images, "missing": [{"reason": "原图缺失"}], "excluded": [{"reason": "人工拒绝"}],
                      "result": {"id": "source-1", "title": "高潜来源", "kind": "web", "status": "completed"},
                      "direction_ids": ["D1", "D2"], "warnings": [], "source_refs": [],
                      "input_digest": "source-digest-v1"}
        self.sources = SimpleNamespace(scope=lambda *args, **kwargs: deepcopy(self.scope),
                                       catalog=lambda: {"results": [self.scope["result"]], "warnings": []})
        self.prepared = FakePrepared(images)
        self.manager = MoodboardClusteringManager(self.root, sources=self.sources, prepared=self.prepared)
        self.grouping = FakeGrouping()
        self.model = Mock(side_effect=AssertionError("真实模型调用不允许"))
        for target, value in (
            ("app.services.moodboards.clustering.get_model", Mock()),
            ("app.services.moodboards.clustering.execution_config", Mock(return_value={"model": "fake-offline"})),
            ("app.services.moodboards.clustering.grouping", Mock(return_value=self.grouping)),
            ("app.services.moodboards.clustering.execute_structured", self.model),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(MoodboardClusteringManager, "_skill_identity", return_value={"fixture": "v1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def preview(self):
        return self.manager.preview(MoodboardScopeRequest(source_result_id="source-1", direction_ids=["D1", "D2"]))

    def request(self, preview, **changes):
        return MoodboardClusteringRequest(preview_id=preview["preview_id"], model_id="fake-offline", confirmed=True,
                                         **changes)

    def start(self, **changes):
        task = self.manager.create(self.request(self.preview(), **changes))
        self.manager.run(task["id"])
        return self.manager.get(task["id"])

    def test_preview_does_not_extract_or_cluster_and_keeps_source_dedup_and_aliases(self):
        result = self.preview()
        self.assertEqual(result["counts"]["total_images"], 8)
        self.assertEqual(result["counts"]["ready_images"], 8)
        self.assertEqual(result["counts"]["unavailable_images"], 1)
        self.assertEqual(result["counts"]["excluded_images"], 1)
        saved = read(self.manager.output / "previews" / f"{result['preview_id']}.json")
        self.assertEqual(saved["scope"]["images"][0]["aliases"], ["reference-0", "duplicate-0"])
        self.assertEqual(self.prepared.extractions, [])
        self.assertEqual(self.grouping.inputs, [])
        self.model.assert_not_called()

    def test_human_confirmation_and_registered_preview_are_required(self):
        values = {"preview_id": "mbp_" + "a" * 32, "model_id": "fake-offline"}
        with self.assertRaises(ValidationError):
            MoodboardClusteringRequest(**values)
        with self.assertRaises(ValidationError):
            MoodboardClusteringRequest(**values, confirmed=False)
        with self.assertRaises(ValidationError):
            MoodboardClusteringRequest(**{**values, "preview_id": "../../private"}, confirmed=True)
        with self.assertRaises(FileNotFoundError):
            self.manager.create(MoodboardClusteringRequest(**values, confirmed=True))

    def test_changed_source_or_feedback_digest_requires_new_confirmation(self):
        preview = self.preview()
        self.scope["input_digest"] = "changed-feedback"
        with self.assertRaisesRegex(ValueError, "重新预览"):
            self.manager.create(self.request(preview))
        self.assertEqual(self.manager.list(), [])

    def test_duplicate_submission_and_parallel_task_are_blocked(self):
        first = self.preview()
        task = self.manager.create(self.request(first))
        with self.assertRaises(RuntimeError):
            self.manager.create(self.request(first))
        with self.assertRaises(RuntimeError):
            self.manager.create(self.request(self.preview()))
        self.manager.run(task["id"])
        with self.assertRaisesRegex(ValueError, "已经提交"):
            self.manager.create(self.request(first))
        self.manager.run(task["id"])
        self.assertEqual(len(self.grouping.inputs), 1)

    def test_cross_manager_parallel_create_starts_only_one_task(self):
        request = self.request(self.preview())
        other = MoodboardClusteringManager(self.root, sources=self.sources, prepared=self.prepared)

        def submit(manager):
            try:
                return manager.create(request)["id"]
            except (ValueError, RuntimeError):
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [self.manager, other]))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.manager.list()), 1)

    def test_existing_dna_is_reused_and_all_selected_directions_share_one_pool(self):
        before = deepcopy(self.prepared.cards)
        task = self.start()
        self.assertEqual(task["status"], "completed", task.get("error"))
        self.assertEqual(self.prepared.extractions, [])
        self.assertEqual(self.prepared.cards, before)
        submitted = self.grouping.inputs[0]
        self.assertEqual(len(submitted["document"]["cards"]), 8)
        self.assertEqual(submitted["settings"]["mode"], "full_catalogue")
        self.assertEqual(self.grouping.call_settings[0]["comparison_mode"], "unified")
        self.assertTrue(task["result"]["summary"]["source_selection_is_not_cluster_boundary"])
        self.assertFalse(task["result"]["summary"]["human_approved"])
        self.model.assert_not_called()

    def test_missing_dna_without_authorization_stays_partial_and_is_not_extracted(self):
        self.prepared.available = {row["sha256"] for row in self.scope["images"][:6]}
        task = self.start(prepare_missing=False)
        self.assertEqual(task["status"], "partial", task.get("error"))
        self.assertEqual(self.prepared.extractions, [])
        ledger = task["result"]["summary"]["preparation"]
        self.assertEqual(sum(row["status"] == "missing_dna_not_authorized" for row in ledger), 2)
        self.assertEqual(len(self.grouping.inputs[0]["document"]["cards"]), 6)

    def test_missing_dna_budget_is_shared_and_never_exceeded(self):
        self.prepared.available = set()
        task = self.start(prepare_missing=True, max_calls=2, workers=4)
        self.assertEqual(task["status"], "partial", task.get("error"))
        self.assertEqual(len(self.prepared.extractions), 2)
        self.assertEqual(task["result"]["summary"]["dna_calls"], 2)
        self.assertEqual(self.grouping.inputs, [])
        self.assertLessEqual(task["progress"]["calls_started"], 2)

    def test_frozen_roi_image_original_and_result_download(self):
        task = self.start()
        member = task["result"]["boards"][0]["members"][0]
        self.assertEqual(member["display_bbox"], [.25, .25, .5, .5])
        self.assertTrue(member["original_url"].endswith("?original=true"))
        cropped = self.manager.image(task["id"], member["id"])
        with Image.open(cropped) as image:
            self.assertEqual(image.size, (4, 4))
        original = self.manager.image(task["id"], member["id"], original=True)
        with Image.open(original) as image:
            self.assertEqual(image.size, (8, 8))
        result = read(self.manager.download(task["id"]))
        self.assertEqual(result["boards"][0]["members"][0]["id"], member["id"])

    def test_provider_stop_survives_generic_preparation_error_and_prevents_grouping(self):
        self.prepared.available = {self.scope["images"][0]["sha256"]}
        failure = PreparationExecutionError("本图未产生有效设计卡", result_id="prep-failed", stop_new_calls=True)
        with patch.object(self.prepared, "run_preparation_extraction", side_effect=failure) as extract:
            task = self.start(prepare_missing=True, max_calls=100, workers=1)
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(task["status"], "partial")
        self.assertEqual(self.grouping.inputs, [])
        self.assertEqual(read(self.manager.download(task["id"])), task["result"])
        ledger = task["result"]["summary"]["preparation"]
        self.assertEqual(sum(row["status"] == "not_sent_budget_or_provider" for row in ledger), 6)

    def test_unreadable_dna_index_does_not_become_automatic_full_extraction(self):
        with patch.object(self.prepared, "list_prepared_results", side_effect=ValueError("损坏索引")):
            preview = self.preview()
        self.assertTrue(preview["warnings"])
        with self.assertRaisesRegex(ValueError, "不能将索引故障"):
            self.manager.create(self.request(preview, prepare_missing=True))
        self.assertEqual(self.prepared.extractions, [])

    def test_http_contract_keeps_confirmation_and_new_history_separate(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch("app.api.moodboards.moodboard_clustering_manager", self.manager), TestClient(app) as client:
            prefix = "/api/v1/moodboards/clustering"
            self.assertEqual(client.get(prefix + "/catalog").status_code, 200)
            preview = client.post(prefix + "/preview", json={"source_result_id": "source-1", "direction_ids": ["D1"]}).json()
            body = {"preview_id": preview["preview_id"], "model_id": "fake-offline"}
            self.assertEqual(client.post(prefix + "/tasks", json=body).status_code, 422)
            response = client.post(prefix + "/tasks", json={**body, "confirmed": True})
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["id"]
            self.assertEqual(client.get(prefix + "/tasks/" + task_id).json()["status"], "completed")
            self.assertEqual(client.get(prefix + "/tasks/" + task_id + "/download").status_code, 200)
            self.assertEqual(len(client.get(prefix + "/tasks").json()), 1)

    def test_image_paths_tokens_and_changed_bytes_are_rejected(self):
        task = self.start()
        member = task["result"]["boards"][0]["members"][0]
        with self.assertRaises(FileNotFoundError):
            self.manager.image(task["id"], "../private")
        with self.assertRaises(FileNotFoundError):
            self.manager.download("../../private")
        original = self.manager.image(task["id"], member["id"], original=True)
        original.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.manager.image(task["id"], member["id"], original=True)
        document_path = self.manager.output / task["id"] / "verified-cards.json"
        document = read(document_path)
        outside = self.root / "private.png"
        Image.new("RGB", (8, 8)).save(outside)
        card = next(row for row in document["cards"] if row["card_id"] == member["card_id"])
        card.update(local_path=str(outside), image_sha256=hashlib.sha256(outside.read_bytes()).hexdigest())
        write(document_path, document)
        with self.assertRaises(ValueError):
            self.manager.image(task["id"], member["id"], original=True)


if __name__ == "__main__":
    unittest.main()
