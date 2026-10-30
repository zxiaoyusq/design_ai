"""只用少量本地真实字节和假模型回执验证冻结边界，不调用模型。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/freeze_prepared.py"
spec = importlib.util.spec_from_file_location("freeze_prepared", SCRIPT)
freeze_prepared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze_prepared)


class FreezePreparedTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "image.ppm"
        self.image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
        self.sample = {"images": [{"image_id": "image-a", "sha256": freeze_prepared.sha(self.image.read_bytes()),
                                   "local_path": str(self.image)}]}
        self.raw = {"branch": "ID", "features": {"form": {"contour": "curved", "proportion": None}},
                    "primary_subject": {"identity": "单椅", "bbox": [0.1, 0.1, 0.8, 0.8]},
                    "bbox": [0.1, 0.1, 0.8, 0.8], "evidence_bbox": [0.1, 0.1, 0.8, 0.8],
                    "display_bbox": [0.05, 0.05, 0.9, 0.9], "display_scope": "whole_object",
                    "crop_reason": "保留椅子完整轮廓", "target_role": "peer_object", "usable": True}
        self.prompt_version = "prism-dna-cluster-observation-20261010-v9"
        self.answer = {"images": [{"image_id": "image-a", "units": [self.raw]}]}
        self.observations_path, self.sample_path = self.root / "observations.json", self.root / "sample.json"
        self.build()

    def write_json(self, path, data):
        path.write_bytes(freeze_prepared.encoded(data))

    def build(self, version="v3"):
        prompt = self.root / "prompt.txt"
        prompt.write_text("fixture\n=== ACTUAL PAYLOAD ===\n" + json.dumps({"prompt_version": self.prompt_version}))
        self.write_json(self.root / "answer.json", self.answer)
        image = self.sample["images"][0]
        self.receipt = {"status": "completed", "requested_model": "fixture-model", "actual_model": None,
                        "requested_reasoning_effort": "high", "started_at": "2026-10-10T00:00:00+00:00",
                        "answer_ref": freeze_prepared.reference(self.root / "answer.json"),
                        "prompt_ref": freeze_prepared.reference(prompt),
                        "images": [{"candidate_id": image["image_id"], "sha256": image["sha256"]}]}
        self.write_json(self.root / "receipt.json", self.receipt)
        self.unit = {**deepcopy(self.raw), "unit_id": "image-a:ID:1", "image_id": image["image_id"],
                     "image_sha256": image["sha256"], "observation_ref": self.receipt["answer_ref"],
                     "receipt_ref": freeze_prepared.reference(self.root / "receipt.json"),
                     "observation_pointer": "/images/0/units/0", "model_requested": "fixture-model",
                     "feature_definition_version": f"prism.dna_cluster_observation.{version}"}
        self.row = {**image, "status": "observed", "units": [self.unit],
                    "observation_ref": self.unit["observation_ref"], "receipt_ref": self.unit["receipt_ref"],
                    "observation_prompt_version": self.prompt_version}
        self.observations = {"images": [self.row], "units": [self.unit]}
        self.save()

    def save(self):
        self.write_json(self.sample_path, self.sample)
        self.write_json(self.observations_path, self.observations)

    def run_freeze(self, name="prepared", cache=None):
        self.save()
        return freeze_prepared.freeze(self.observations_path, self.sample_path, self.root / name, cache)

    def test_freeze_preserves_bytes_unknowns_and_no_visual_pass(self):
        manifest = self.run_freeze()
        self.assertEqual((self.root / "prepared/observations.snapshot.json").read_bytes(), self.observations_path.read_bytes())
        self.assertEqual(manifest["terminal_counts"], {"images": 1, "observed": 1, "failed": 0, "pending": 0})
        self.assertFalse(manifest["visual_approval_granted"])
        self.assertFalse(manifest["automatic_cross_run_model_skipping_implemented"])
        self.assertEqual(manifest["model_calls"], 0)
        asset = json.loads(Path(manifest["asset_index"][0]["asset_ref"]["path"]).read_bytes())
        self.assertIsNone(asset["observation"]["units"][0]["features"]["form"]["proportion"])

    def test_failure_is_terminal_but_not_cached(self):
        self.row.update(status="failed", units=[], observation_error="fixture timeout")
        self.observations["units"] = []
        manifest = self.run_freeze()
        self.assertEqual(manifest["terminal_counts"]["failed"], 1)
        self.assertIsNone(manifest["asset_index"][0]["asset_ref"])

    def test_pending_rejected_before_writing(self):
        self.row["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "未终态"):
            self.run_freeze()
        self.assertFalse((self.root / "prepared").exists())

    def test_exact_sample_set_and_duplicate_identity_required(self):
        self.sample["images"].append(deepcopy(self.sample["images"][0]))
        with self.assertRaisesRegex(ValueError, "重复"):
            self.run_freeze()
        self.sample["images"][-1]["image_id"] = "extra"
        with self.assertRaisesRegex(ValueError, "集合"):
            self.run_freeze()

    def test_original_image_tampering_rejected(self):
        self.image.write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.run_freeze()

    def test_top_level_units_must_match_per_image(self):
        self.observations["units"] = []
        with self.assertRaisesRegex(ValueError, "顶层 units"):
            self.run_freeze()

    def test_cannot_silently_drop_units_from_both_indexes(self):
        self.observations["units"] = []
        self.row["units"] = []
        with self.assertRaisesRegex(ValueError, "遗漏或增添"):
            self.run_freeze()

    def test_answer_and_receipt_tampering_rejected(self):
        (self.root / "answer.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.run_freeze()

    def test_modified_features_or_scope_without_new_observation_rejected(self):
        self.unit["features"]["form"]["contour"] = "straight"
        with self.assertRaisesRegex(ValueError, "DNA 与原回答"):
            self.run_freeze()
        self.unit["features"]["form"]["contour"] = "curved"
        self.unit["display_bbox"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, "display_bbox"):
            self.run_freeze()

    def test_same_batch_pointer_cannot_borrow_other_image(self):
        self.answer["images"][0]["image_id"] = "other-image"
        self.answer["images"].append({"image_id": "image-a", "units": [deepcopy(self.raw)]})
        self.build()
        with self.assertRaisesRegex(ValueError, "其他图片"):
            self.run_freeze()

    def test_prompt_or_model_label_cannot_be_upgraded(self):
        self.row["observation_prompt_version"] = "future-prompt"
        with self.assertRaisesRegex(ValueError, "Prompt 版本"):
            self.run_freeze()
        self.row["observation_prompt_version"] = self.prompt_version
        self.unit["model_requested"] = "fake-new-model"
        with self.assertRaisesRegex(ValueError, "请求模型"):
            self.run_freeze()

    def test_legacy_scope_is_preserved_not_upgraded(self):
        self.raw.pop("display_scope")
        self.raw.pop("crop_reason")
        self.prompt_version = "prism-dna-cluster-observation-20261009-v7"
        self.build("v2")
        manifest = self.run_freeze()
        self.assertEqual(manifest["asset_index"][0]["scope_status"], "legacy_scope_preserved")
        self.unit["feature_definition_version"] = "prism.dna_cluster_observation.v3"
        with self.assertRaisesRegex(ValueError, "协议标签"):
            self.run_freeze("fake-upgrade")

    def test_cache_is_content_addressed_reused_and_conflict_protected(self):
        cache = self.root / "cache"
        first = self.run_freeze("one", cache)
        second = self.run_freeze("two", cache)
        self.assertEqual(first["asset_index"], second["asset_index"])
        self.assertEqual(len(list(cache.glob("*.json"))), 1)
        path = Path(first["asset_index"][0]["asset_ref"]["path"])
        path.write_bytes(b"corrupt cache")
        with self.assertRaisesRegex(ValueError, "缓存冲突"):
            self.run_freeze("three", cache)
        self.assertFalse((self.root / "three").exists())

    def test_new_actual_observation_changes_cache_key(self):
        cache = self.root / "cache"
        first = self.run_freeze("one", cache)
        self.raw["display_bbox"] = [0, 0, 1, 1]
        self.build()
        second = self.run_freeze("two", cache)
        self.assertNotEqual(first["asset_index"][0]["cache_key"], second["asset_index"][0]["cache_key"])

    def test_existing_output_never_overwritten(self):
        self.run_freeze()
        with self.assertRaises(FileExistsError):
            self.run_freeze()

    def test_actual_targeted_revision_can_replace_initial_unit_observation(self):
        revision = deepcopy(self.raw)
        revision["display_bbox"] = [0, 0, 1, 1]
        self.write_json(self.root / "revision-answer.json", {
            "revisions": [{"image_id": "image-a", "unit_id": self.unit["unit_id"], "observation": revision}]})
        prompt = self.root / "revision-prompt.txt"
        prompt.write_text('fixture\n=== ACTUAL PAYLOAD ===\n{"prompt_version":"prism-dna-targeted-revision-v3"}')
        receipt = {**self.receipt, "answer_ref": freeze_prepared.reference(self.root / "revision-answer.json"),
                   "prompt_ref": freeze_prepared.reference(prompt)}
        self.write_json(self.root / "revision-receipt.json", receipt)
        self.unit.update(revision, observation_ref=receipt["answer_ref"],
                         receipt_ref=freeze_prepared.reference(self.root / "revision-receipt.json"),
                         observation_pointer="/revisions/0/observation")
        manifest = self.run_freeze()
        self.assertIn("prism-dna-targeted-revision-v3", manifest["asset_index"][0]["prompt_versions"])

    def test_emotion_requires_bound_original_and_preserves_actual_model(self):
        self.raw["design_emotion"] = {"status": "limited", "expression": "温和", "limitations": ["比例不可知"]}
        self.build()
        with self.assertRaisesRegex(ValueError, "缺少独立出处"):
            self.run_freeze()
        self.unit["design_emotion_provenance"] = {
            "observation_ref": self.unit["observation_ref"], "receipt_ref": self.unit["receipt_ref"],
            "observation_pointer": "/images/0/units/0/design_emotion", "image_id": "image-a",
            "image_sha256": self.row["sha256"], "primary_subject_identity": "单椅",
            "primary_subject_bbox": self.raw["primary_subject"]["bbox"], "prompt_version": self.prompt_version,
            "model_requested": "fixture-model", "assessed_at": self.receipt["started_at"]}
        self.run_freeze()
        self.unit["design_emotion_provenance"]["primary_subject_identity"] = "茶几"
        with self.assertRaisesRegex(ValueError, "其他对象"):
            self.run_freeze("wrong-subject")

    def test_declared_source_sample_must_match_supplied_bytes(self):
        self.write_json(self.root / "other-sample.json", {"images": []})
        self.observations["sample_ref"] = freeze_prepared.reference(self.root / "other-sample.json")
        with self.assertRaisesRegex(ValueError, "原样本"):
            self.run_freeze()


if __name__ == "__main__":
    unittest.main()
