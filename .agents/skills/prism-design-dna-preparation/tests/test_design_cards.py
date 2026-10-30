"""少量离线假模型覆盖卡级隔离、冻结、来源绑定与续跑；不发送真实模型请求。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/design_cards.py"
spec = importlib.util.spec_from_file_location("design_cards", SCRIPT)
cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cards)
transport_spec = importlib.util.spec_from_file_location(
    "design_cards_test_transport", cards.REPO / "backend/app/services/visual_workflow/codex_transport.py")
transport = importlib.util.module_from_spec(transport_spec)
transport_spec.loader.exec_module(transport)


def sample_card(branch="ID"):
    return {
        "branch": branch, "subject": {"identity": "肩线清楚的外套", "role": "primary_object",
                                      "bbox": [0.1, 0.1, 0.8, 0.8], "whole_visible": True},
        "display_bbox": [0.05, 0.05, 0.9, 0.9], "evidence_bbox": [0.2, 0.2, 0.5, 0.5],
        "display_scope": "whole_object", "crop_reason": "保留完整肩线、裁片和廓形", "category": "apparel",
        "relations": {key: {"observation": "浅灰主体由直肩线与矩形裁片组织", "evidence": ["肩部平直，裁片边线清晰"],
                            "unknown": False} for key in cards.RELATIONS},
        "design_emotion": {"expression": "冷静利落", "coordination_reason": "低彩灰与清楚肩线共同表达克制",
                           "counter_signals": ["袖口有少量柔软褶皱"]},
        "design_quality": {"level": "considered", "evidence": ["肩线与裁片分区相互呼应"]},
        "style_candidates": [{"style_id": "RefinedMinimalism", "match_score": 68, "confidence": 0.6,
                              "main_support": ["简洁主体中有精确裁片细节"], "main_conflicts": ["局部褶皱较柔软"]}],
        "limitations": [], "runway": "unknown",
    }


class DesignCardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        image = self.root / "image.ppm"
        image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
        self.row = {"image_id": "image-a", "sha256": cards.digest(image), "local_path": str(image),
                    "sources": [{"article_id": "article-a", "project_id": None}], "source_kind": "trend"}
        self.sample = self.root / "sample.json"
        self.prior = self.root / "prior.json"
        cards.write_new(self.sample, {"images": [self.row]})
        cards.write_new(self.prior, {"schema_version": "prism.dna_cluster_observation.v3", "units": []})
        self.calls = 0
        self.answer = {"images": [{"image_id": "image-a", "limitations": [], "cards": [sample_card()]}]}

    def fake_executor(self, folder, *, system, payload, images, schema):
        self.calls += 1
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "system.txt").write_text(system + "\n")
        cards.write_new(folder / "payload.json", payload)
        cards.write_new(folder / "schema.json", schema)
        # 使用生产串行化边界核对真实发送文本；回答仍是合成夹具，不发网络。
        (folder / "prompt.txt").write_text(transport.build_stdin(system, payload, images))
        cards.write_new(folder / "answer.json", self.answer)
        cards.write_new(folder / "receipt.json", {
            "status": "completed", "requested_model": cards.MODEL, "requested_reasoning_effort": cards.EFFORT,
            "actual_model": None, "started_at": "2026-10-10T00:00:00+00:00", "seconds": 0.01, "images": images,
            "answer_ref": cards.reference(folder / "answer.json"), "schema_ref": cards.reference(folder / "schema.json"),
            "prompt_ref": cards.reference(folder / "prompt.txt"),
        })
        return self.answer

    def run_fixture(self, name="out", **kwargs):
        return cards.run(self.sample, self.prior, self.root / name, execute=True, executor=self.fake_executor, **kwargs)

    def test_catalog_is_38_active_visible_mechanisms(self):
        catalog, refs = cards.style_catalog()
        self.assertEqual(len(catalog), 38)
        self.assertNotIn("TribeIdentity", {item["style_id"] for item in catalog})
        self.assertTrue(all(item["visible_mechanism"] and item["counter_signals"] for item in catalog))
        self.assertEqual(len(refs), 3)

    def test_dry_run_never_creates_output_or_calls_model(self):
        result = cards.run(self.sample, self.prior, self.root / "out", executor=self.fake_executor)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.calls, 0)
        self.assertFalse((self.root / "out").exists())

    def test_current_observation_system_reaches_serialized_request(self):
        self.run_fixture()
        folder = self.root / "out/model-calls/batch-0001"
        prompt = (folder / "prompt.txt").read_text()
        sent_system = prompt.split("=== STAGE SYSTEM (verbatim) ===\n", 1)[1].split(
            "=== ORDERED ATTACHMENT IDENTITY ===", 1)[0].rstrip("\n")
        expected_system = cards.SYSTEM + "\n共享比较语义（本阶段只逐图记录，禁止开始聚类）：\n" + cards.POLICY.read_text()
        self.assertEqual(sent_system, expected_system.rstrip("\n"))
        sent_payload, _ = json.JSONDecoder().raw_decode(prompt.split("=== ACTUAL PAYLOAD ===\n", 1)[1])
        self.assertEqual(sent_payload["prompt_version"], "prism-relational-design-cards-20261010-v2")
        self.assertEqual(sent_payload, json.loads((folder / "payload.json").read_text()))
        receipt = json.loads((folder / "receipt.json").read_text())
        self.assertEqual(receipt["prompt_ref"], cards.reference(folder / "prompt.txt"))

    def test_context_and_partial_readability_use_existing_seven_relation_schema(self):
        """新观察要求使用既有承载字段，保存事实、竞争信息和未知，不增硬性输出字段。"""
        raw = self.answer["images"][0]["cards"][0]
        raw["relations"]["palette"]["observation"] = "对象为浅灰；展示窗后方的彩色招牌属于背景"
        raw["relations"]["texture"] = {"observation": "当前清晰度不能判断微纹理", "evidence": [], "unknown": True}
        raw["design_emotion"]["counter_signals"] = ["展示窗后方招牌形成独立亮点，与肩线共同争夺注意"]
        raw["limitations"] = ["廓形与大裁片可读，微纹理和窄接缝不可辨；背景招牌不属于对象配色"]
        self.run_fixture()
        loaded = cards.load_prepared(self.root / "out/prepared-manifest.json")["cards"][0]
        self.assertEqual(loaded["relations"], raw["relations"])
        self.assertEqual(loaded["design_emotion"], raw["design_emotion"])
        self.assertEqual(loaded["limitations"], raw["limitations"])
        self.assertEqual(set(cards.card_schema(["RefinedMinimalism"])["properties"]), set(raw))
        self.assertEqual(set(loaded["relations"]), set(cards.RELATIONS))

    def test_historical_v1_remains_readable_but_cannot_hit_v2_extraction_cache(self):
        """B 历史消费与 A 新提取缓存是不同契约；版本变化既不伪命中，也不自动重提。"""
        old_version = "prism-relational-design-cards-20261010-v1"
        with (patch.object(cards, "PROMPT_VERSION", old_version),
              patch.object(cards, "SYSTEM", "合成历史 v1 提取规则，仅用于缓存边界验证。")):
            self.run_fixture("legacy")
            old_path = self.root / "legacy/prepared-manifest.json"
            old_document = cards.load_prepared(old_path)
        before = cards.digest(old_path), cards.digest(self.root / "legacy/design-cards.json")
        loaded = cards.load_prepared(old_path)
        self.assertEqual(loaded, old_document)
        self.assertEqual(loaded["cards"][0]["provenance"]["prompt_version"], old_version)
        old_schema = json.loads((self.root / "legacy/model-calls/batch-0001/schema.json").read_text())
        self.assertEqual(old_schema, cards.response_schema(["image-a"], [row["style_id"] for row in loaded["style_catalog"]]))
        result = cards.run(self.sample, self.prior, self.root / "v2-planned", reuse_prepared=[old_path], executor=self.fake_executor)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertEqual(result["cross_run_reuse"]["not_reused_image_ids"], ["image-a"])
        self.assertEqual(result["planned_model_calls"], 1)
        self.assertIn("不兼容", result["cross_run_reuse"]["rejections"][0]["reason"])
        self.assertEqual(self.calls, 1)
        self.assertFalse((self.root / "v2-planned").exists())
        self.assertEqual(before, (cards.digest(old_path), cards.digest(self.root / "legacy/design-cards.json")))

    def test_freeze_and_resume_existing_success_are_lossless(self):
        result = self.run_fixture()
        self.assertEqual(result["counts"]["cards"], 1)
        document = cards.load_prepared(self.root / "out/prepared-manifest.json")
        actual = document["cards"][0]
        self.assertEqual(actual["subject"]["identity"], "肩线清楚的外套")
        self.assertEqual(actual["style_candidates"][0]["confidence"], 0.6)
        self.assertFalse(document["legacy_r5_modified"])
        self.assertFalse(document["visual_board_approved"])
        self.run_fixture(resume=True)
        self.assertEqual(self.calls, 1)

    def test_invalid_card_does_not_discard_valid_sibling(self):
        invalid = sample_card("ID")
        invalid["subject"]["whole_visible"] = False
        valid = sample_card("CMF")
        valid["subject"]["role"] = "peer_object"
        valid["display_scope"] = "representative_detail"
        valid["subject"]["whole_visible"] = False
        self.answer["images"][0]["cards"] = [invalid, valid]
        result = self.run_fixture()
        self.assertEqual(result["counts"]["observed"], 1)
        self.assertEqual(result["counts"]["cards_by_branch"], {"CMF": 1})
        document = cards.load_prepared(self.root / "out/prepared-manifest.json")
        self.assertEqual(document["images"][0]["errors"][0]["pointer"], "/images/0/cards/0")
        self.assertEqual(document["cards"][0]["subject"]["role"], "peer_object")

    def test_empty_card_is_terminal_not_false_success(self):
        self.answer["images"][0]["cards"] = []
        result = self.run_fixture()
        self.assertTrue(result["all_images_terminal"])
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["cards"], 0)

    def test_failed_model_is_not_automatically_retried(self):
        def failed(folder, **kwargs):
            self.calls += 1
            folder.mkdir(parents=True)
            cards.write_new(folder / "receipt.json", {"status": "failed", "failure": "fixture timeout"})
            raise RuntimeError("fixture timeout")
        cards.run(self.sample, self.prior, self.root / "out", execute=True, executor=failed)
        cards.run(self.sample, self.prior, self.root / "out", execute=True, resume=True, executor=failed)
        self.assertEqual(self.calls, 1)

    def test_output_cannot_be_overwritten(self):
        self.run_fixture()
        with self.assertRaises(ValueError):
            self.run_fixture()

    def test_global_auth_failure_keeps_unsent_images_resumable_without_freezing(self):
        rows = []
        for index in range(6):
            path = self.root / f"image-{index}.ppm"
            path.write_bytes(b"P6\n1 1\n255\n" + bytes((index, 0, 0)))
            rows.append({**self.row, "image_id": f"image-{index}", "local_path": str(path), "sha256": cards.digest(path)})
        self.sample.write_bytes(cards.encoded({"images": rows}))

        def auth_failed(folder, **kwargs):
            self.calls += 1
            folder.mkdir(parents=True)
            cards.write_new(folder / "receipt.json", {"status": "failed", "failure": "authentication failed"})
            raise RuntimeError("authentication failed")

        result = cards.run(self.sample, self.prior, self.root / "out", batch_size=1, workers=1,
                           execute=True, executor=auth_failed)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["pending"], 5)
        self.assertEqual(result["not_attempted_count"], 5)
        self.assertEqual(result["status"], "paused_quota_or_auth")
        self.assertFalse((self.root / "out/prepared-manifest.json").exists())
        self.assertTrue(result["execution"]["stopped_new_calls_after_fatal_failure"])
        self.assertEqual(result["execution"]["call_attempts_this_execution"], 1)
        self.assertEqual(result["execution"]["model_calls_this_execution"], 0)
        waiting = cards.run(self.sample, self.prior, self.root / "out", batch_size=1, workers=1,
                            execute=True, resume=True, executor=auth_failed)
        self.assertEqual(waiting["status"], "paused_quota_or_auth")
        self.assertEqual(self.calls, 1)

        attempted = []

        def restored(folder, **kwargs):
            image_id = kwargs["images"][0]["candidate_id"]
            attempted.append(image_id)
            self.answer = {"images": [{"image_id": image_id, "limitations": [], "cards": [sample_card()]}]}
            return self.fake_executor(folder, **kwargs)

        finished = cards.run(self.sample, self.prior, self.root / "out", batch_size=1, workers=1,
                             execute=True, resume=True, resume_after_quota_reset=True, executor=restored)
        self.assertEqual(finished["counts"]["observed"], 5)
        self.assertEqual(finished["counts"]["failed"], 1)
        self.assertEqual(finished["counts"]["pending"], 0)
        self.assertEqual(self.calls, 6)
        self.assertNotIn("image-0", attempted)
        self.assertTrue((self.root / "out/prepared-manifest.json").exists())

    def test_semantic_failure_is_not_global_auth_failure(self):
        self.assertFalse(cards.fatal_call_failure(self.root / "no-call", "whole_object 与 whole_visible 不一致"))
        self.assertFalse(cards.fatal_call_failure(self.root / "no-call", "schema validation failed"))
        self.assertTrue(cards.fatal_call_failure(self.root / "no-call", "HTTP 429 Too Many Requests"))

    def test_resume_reuses_exact_completed_call_before_freezing(self):
        plan, batches, context = cards.make_plan(self.sample, self.prior, 2, 5)
        out = self.root / "out"
        out.mkdir()
        cards.write_new(out / "plan.json", plan)
        batch = batches[0]
        self.fake_executor(out / "model-calls" / batch["batch_id"], system=context["system"], payload=batch["payload"],
                           images=batch["images"], schema=batch["schema"])
        result = self.run_fixture(resume=True, batch_size=2, workers=5)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["execution"]["model_calls_this_execution"], 0)
        self.assertEqual(result["execution"]["cached_calls"], 1)

    def test_resume_rejects_changed_successful_payload_and_does_not_retry(self):
        plan, batches, context = cards.make_plan(self.sample, self.prior, 2, 5)
        out = self.root / "out"
        out.mkdir()
        cards.write_new(out / "plan.json", plan)
        batch = batches[0]
        self.fake_executor(out / "model-calls" / batch["batch_id"], system=context["system"], payload=batch["payload"],
                           images=batch["images"], schema=batch["schema"])
        (out / "model-calls" / batch["batch_id"] / "payload.json").write_text('{"tampered":true}')
        result = self.run_fixture(resume=True, batch_size=2, workers=5)
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["counts"]["failed"], 1)

    def test_resume_rejects_modified_inputs_even_if_image_same(self):
        self.run_fixture()
        self.prior.write_text('{"units":[],"changed":true}')
        with self.assertRaises(ValueError):
            self.run_fixture(resume=True)

    def test_tampered_card_cannot_pass_by_rehashing_manifest(self):
        self.run_fixture()
        path = self.root / "out/design-cards.json"
        document = json.loads(path.read_bytes())
        document["cards"][0]["relations"]["palette"]["observation"] = "伪造亮红主色"
        path.write_bytes(cards.encoded(document))
        manifest_path = self.root / "out/prepared-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["design_cards_ref"] = cards.reference(path)
        manifest_path.write_bytes(cards.encoded(manifest))
        with self.assertRaises(ValueError):
            cards.load_prepared(manifest_path)

    def test_unknown_is_not_no_and_evidence_is_required_for_known(self):
        raw = sample_card()
        raw["relations"]["texture"] = {"observation": "分辨率不足", "evidence": [], "unknown": True}
        cards.validate_card(raw, ["RefinedMinimalism"])
        raw["relations"]["texture"]["unknown"] = False
        with self.assertRaises(ValueError):
            cards.validate_card(raw, ["RefinedMinimalism"])

    def test_geometry_is_xywh_not_xyxy(self):
        raw = sample_card()
        raw["evidence_bbox"] = [0.6, 0.6, 0.7, 0.7]
        with self.assertRaises(ValueError):
            cards.validate_card(raw, ["RefinedMinimalism"])

    def test_whole_scope_rejects_cropped_object_but_detail_allows_it(self):
        raw = sample_card()
        raw["subject"]["whole_visible"] = False
        with self.assertRaises(ValueError):
            cards.validate_card(raw, ["RefinedMinimalism"])
        raw["display_scope"] = "representative_detail"
        cards.validate_card(raw, ["RefinedMinimalism"])

    def test_deprecated_style_cannot_enter(self):
        raw = sample_card()
        raw["style_candidates"][0]["style_id"] = "TribeIdentity"
        with self.assertRaises(Exception):
            cards.validate_card(raw, ["RefinedMinimalism"])

    def test_workload_upper_bound_and_duplicate_sha(self):
        with self.assertRaises(ValueError):
            cards.run(self.sample, self.prior, self.root / "out", workers=11)
        dry_run = cards.run(self.sample, self.prior, self.root / "out")
        self.assertEqual((dry_run["batch_size"], dry_run["workers"]), (1, 10))
        duplicate = {**deepcopy(self.row), "image_id": "image-b"}
        self.sample.write_bytes(cards.encoded({"images": [self.row, duplicate]}))
        with self.assertRaises(ValueError):
            cards.run(self.sample, self.prior, self.root / "out")

    def test_durable_attempt_without_receipt_is_not_retried(self):
        plan, batches, _ = cards.make_plan(self.sample, self.prior, 1, 10)
        out = self.root / "out"
        out.mkdir()
        cards.write_new(out / "plan.json", plan)
        cards.write_new(out / "attempts/batch-0001.json", {"input_key": batches[0]["input_key"]})
        result = self.run_fixture(resume=True)
        self.assertEqual(self.calls, 0)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertTrue((out / "batch-results/batch-0001.json").exists())

    def test_unrecorded_quota_pause_is_detected_before_sending_remaining_image(self):
        second = self.root / "second.ppm"
        second.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")
        row2 = {**self.row, "image_id": "image-b", "local_path": str(second), "sha256": cards.digest(second)}
        self.sample.write_bytes(cards.encoded({"images": [self.row, row2]}))
        plan, batches, _ = cards.make_plan(self.sample, self.prior, 1, 10)
        out = self.root / "out"
        out.mkdir()
        cards.write_new(out / "plan.json", plan)
        cards.write_new(out / "model-calls/batch-0001/receipt.json", {"status": "failed", "failure": "rate_limit_exceeded"})
        result = self.run_fixture(resume=True)
        self.assertEqual(self.calls, 0)
        self.assertEqual(result["status"], "paused_quota_or_auth")
        self.assertEqual(result["not_attempted_image_ids"], ["image-b"])

    def test_single_run_lock_prevents_second_scheduler(self):
        out = self.root / "out"
        out.mkdir()
        with cards.execution_lock(out):
            with self.assertRaises(ValueError):
                with cards.execution_lock(out):
                    pass

    def test_success_coverage_threshold_is_strict_and_not_visual_accuracy(self):
        ledger = [{"status": "observed"} for _ in range(1440)]
        exactly = cards.coverage_counts(1600, ledger, [])
        self.assertFalse(exactly["strictly_over_90_percent"])
        ledger.append({"status": "observed"})
        above = cards.coverage_counts(1600, ledger, [{"image_id": "a", "branch": "ID"}, {"image_id": "a", "branch": "CMF"}])
        self.assertTrue(above["strictly_over_90_percent"])
        self.assertEqual(above["images_by_branch"], {"ID": 1, "CMF": 1})
        self.assertFalse(above["visual_accuracy_claimed"])

    def test_legacy_r5_source_path_and_corrupt_context_do_not_kill_raw_image(self):
        old = self.root / "old-r5.json"
        cards.write_new(old, {"source": self.row["local_path"], "r5_result": {
            "local_features": [{"p": "GEO-001", "v": "直线", "at": "肩线"}]}})
        row = {**self.row, "dna_primary_ref": cards.reference(old)}
        self.sample.write_bytes(cards.encoded({"images": [row]}))
        plan, batches, _ = cards.make_plan(self.sample, self.prior, 1, 10)
        self.assertEqual(plan["context_warnings"], [])
        self.assertEqual(batches[0]["payload"]["images"][0]["r5_context"]["attached_fact_count"], 1)
        old.write_text('{"source":"changed"}')
        plan, batches, _ = cards.make_plan(self.sample, self.prior, 1, 10)
        self.assertEqual(plan["invalid_inputs"], [])
        self.assertEqual(len(plan["context_warnings"]), 1)
        self.assertIn("context_warning", batches[0]["payload"]["images"][0])

    def test_quota_resume_flag_requires_explicit_execute_and_resume(self):
        with self.assertRaises(ValueError):
            cards.run(self.sample, self.prior, self.root / "out", resume_after_quota_reset=True)

    def test_strict_response_schema_is_valid_and_has_no_open_objects(self):
        schema = cards.response_schema(["image-a"], ["RefinedMinimalism"])
        cards.jsonschema.Draft202012Validator.check_schema(schema)
        cards.jsonschema.Draft202012Validator(schema).validate(self.answer)

        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)
        check(schema)

    def test_cross_run_reuse_has_zero_calls_and_keeps_original_card_provenance(self):
        self.answer["images"][0]["cards"].append(sample_card("CMF"))
        self.run_fixture()
        old_path = self.root / "out/prepared-manifest.json"
        original = cards.load_prepared(old_path)
        result = self.run_fixture("reused", reuse_prepared=[old_path])
        reused = cards.load_prepared(self.root / "reused/prepared-manifest.json")
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["execution"]["call_attempts_this_execution"], 0)
        self.assertEqual(result["execution"]["cross_run_reused_images"], 1)
        self.assertEqual(result["cross_run_reuse"]["matched_cards"], 2)
        self.assertEqual(reused["cards"], original["cards"])
        self.assertEqual(reused["images"][0]["cross_run_reuse"]["prepared_ref"], cards.reference(old_path))
        self.run_fixture("reused", reuse_prepared=[old_path], resume=True)
        self.assertEqual(self.calls, 1)
        with self.assertRaises(ValueError):
            self.run_fixture("reused", reuse_prepared=[], resume=True)

    def test_cross_run_subset_different_batch_size_and_second_generation_reuse(self):
        second = self.root / "second.ppm"
        second.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")
        row2 = {**self.row, "image_id": "image-b", "local_path": str(second), "sha256": cards.digest(second)}
        self.sample.write_bytes(cards.encoded({"images": [self.row, row2]}))
        self.answer["images"].append({"image_id": "image-b", "limitations": [], "cards": [sample_card("CMF")]})
        self.run_fixture(batch_size=2)
        subset = self.root / "subset.json"
        cards.write_new(subset, {"images": [row2]})
        result = cards.run(subset, self.prior, self.root / "subset-out", execute=True,
                           reuse_prepared=[self.root / "out/prepared-manifest.json"], executor=self.fake_executor)
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 1)
        self.assertEqual(self.calls, 1)
        second_reuse = cards.run(subset, self.prior, self.root / "second-reuse", execute=True,
                                 reuse_prepared=[self.root / "subset-out/prepared-manifest.json"], executor=self.fake_executor)
        self.assertEqual(second_reuse["cross_run_reuse"]["matched_images"], 1)
        self.assertEqual(self.calls, 1)

    def test_cross_run_changed_sample_only_calls_unseen_image(self):
        self.run_fixture()
        second = self.root / "second.ppm"
        second.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")
        row2 = {**self.row, "image_id": "image-b", "local_path": str(second), "sha256": cards.digest(second)}
        expanded = self.root / "expanded.json"
        cards.write_new(expanded, {"images": [row2, self.row]})
        observed = []

        def executor(folder, **kwargs):
            image_ids = [image["candidate_id"] for image in kwargs["images"]]
            observed.extend(image_ids)
            self.answer = {"images": [{"image_id": image_id, "limitations": [], "cards": [sample_card()]} for image_id in image_ids]}
            return self.fake_executor(folder, **kwargs)

        result = cards.run(expanded, self.prior, self.root / "expanded-out", execute=True,
                           reuse_prepared=[self.root / "out/prepared-manifest.json"], executor=executor)
        self.assertEqual(observed, ["image-b"])
        self.assertEqual(result["counts"]["observed"], 2)
        self.assertEqual(result["execution"]["cross_run_reused_images"], 1)
        self.assertEqual(result["execution"]["call_attempts_this_execution"], 1)

    def test_cross_run_mismatched_rules_model_and_prior_are_rejected_without_dry_run_calls(self):
        self.run_fixture()
        old_path = self.root / "out/prepared-manifest.json"
        for field, value in (("SYSTEM", cards.SYSTEM + "\n新的对象范围"), ("MODEL", "different-model")):
            with self.subTest(field=field), patch.object(cards, field, value):
                result = cards.run(self.sample, self.prior, self.root / "unused", reuse_prepared=[old_path])
                self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
                self.assertEqual(result["planned_model_calls"], 1)
                self.assertTrue(result["cross_run_reuse"]["rejections"])
        changed_prior = self.root / "changed-prior.json"
        cards.write_new(changed_prior, {"units": [{"image_id": self.row["image_id"], "image_sha256": self.row["sha256"],
                                                  "primary_subject": "另一个同级物品"}]})
        result = cards.run(self.sample, changed_prior, self.root / "unused", reuse_prepared=[old_path])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("上下文", result["cross_run_reuse"]["rejections"][0]["reason"])
        self.assertEqual(self.calls, 1)

    def test_cross_run_tampered_crop_and_rehashed_document_cannot_be_reused(self):
        self.run_fixture()
        document_path = self.root / "out/design-cards.json"
        document = json.loads(document_path.read_bytes())
        document["cards"][0]["display_bbox"] = [0, 0, 1, 1]
        document_path.write_bytes(cards.encoded(document))
        manifest_path = self.root / "out/prepared-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["design_cards_ref"] = cards.reference(document_path)
        manifest_path.write_bytes(cards.encoded(manifest))
        result = cards.run(self.sample, self.prior, self.root / "unused", reuse_prepared=[manifest_path])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("原答", result["cross_run_reuse"]["rejections"][0]["reason"])
        self.assertEqual(self.calls, 1)

    def test_cross_run_no_script_hash_invalidation_and_unrelated_prior_change(self):
        self.run_fixture()
        plan_path = self.root / "out/plan.json"
        plan = json.loads(plan_path.read_bytes())
        plan["script_ref"]["sha256"] = "historical-generator-sha-not-current"
        plan_path.write_bytes(cards.encoded(plan))
        document_path = self.root / "out/design-cards.json"
        document = json.loads(document_path.read_bytes())
        document["plan_ref"] = cards.reference(plan_path)
        document_path.write_bytes(cards.encoded(document))
        manifest_path = self.root / "out/prepared-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["design_cards_ref"] = cards.reference(document_path)
        manifest_path.write_bytes(cards.encoded(manifest))
        unrelated_prior = self.root / "unrelated-prior.json"
        cards.write_new(unrelated_prior, {"units": [{"image_id": "outside-sample", "image_sha256": "different"}]})
        result = cards.run(self.sample, unrelated_prior, self.root / "reused", execute=True,
                           reuse_prepared=[manifest_path], executor=self.fake_executor)
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 1)
        self.assertEqual(self.calls, 1)

    def test_cross_run_partial_card_errors_remain_visible_but_failures_are_not_hits(self):
        invalid = sample_card("CMF")
        invalid["subject"]["whole_visible"] = False
        self.answer["images"][0]["cards"].append(invalid)
        self.run_fixture()
        self.run_fixture("reused", reuse_prepared=[self.root / "out/prepared-manifest.json"])
        document = cards.load_prepared(self.root / "reused/prepared-manifest.json")
        self.assertEqual(len(document["images"][0]["errors"]), 1)
        self.assertEqual(len(document["cards"]), 1)
        self.answer["images"][0]["cards"] = []
        self.run_fixture("empty")
        result = cards.run(self.sample, self.prior, self.root / "unused",
                           reuse_prepared=[self.root / "empty/prepared-manifest.json"])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("无有效卡", result["cross_run_reuse"]["rejections"][0]["reason"])

    def test_cross_run_multiple_sources_and_unreadable_source_are_audited(self):
        self.run_fixture()
        old_path = self.root / "out/prepared-manifest.json"
        result = cards.run(self.sample, self.prior, self.root / "unused",
                           reuse_prepared=[self.root / "missing.json", old_path, old_path])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 1)
        self.assertEqual(len(result["cross_run_reuse"]["source_refs"]), 2)
        self.assertIn("source_invalid", result["cross_run_reuse"]["rejections"][0]["reason"])
        self.assertEqual(result["planned_model_calls"], 0)
        self.assertFalse((self.root / "unused").exists())

    def test_cross_run_known_actual_model_difference_is_not_a_cache_hit(self):
        self.run_fixture()
        receipt_path = self.root / "out/model-calls/batch-0001/receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["actual_model"] = "different-actual-model"
        receipt_path.write_bytes(cards.encoded(receipt))
        document_path = self.root / "out/design-cards.json"
        document = json.loads(document_path.read_bytes())
        document["cards"][0]["provenance"].update(actual_model="different-actual-model",
                                                       receipt_ref=cards.reference(receipt_path))
        document["images"][0]["receipt_ref"] = cards.reference(receipt_path)
        document_path.write_bytes(cards.encoded(document))
        manifest_path = self.root / "out/prepared-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["design_cards_ref"] = cards.reference(document_path)
        manifest_path.write_bytes(cards.encoded(manifest))
        result = cards.run(self.sample, self.prior, self.root / "unused", reuse_prepared=[manifest_path])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("实际模型", result["cross_run_reuse"]["rejections"][0]["reason"])
        self.assertEqual(self.calls, 1)

    def test_cross_run_original_request_metadata_must_match_receipt(self):
        self.run_fixture()
        folder = self.root / "out/model-calls/batch-0001"
        receipt = json.loads((folder / "receipt.json").read_bytes())
        request = {key: receipt[key] for key in ("requested_model", "requested_reasoning_effort", "started_at", "images", "prompt_ref", "schema_ref")}
        request["requested_reasoning_effort"] = "low"
        cards.write_new(folder / "request.json", request)
        result = cards.run(self.sample, self.prior, self.root / "unused",
                           reuse_prepared=[self.root / "out/prepared-manifest.json"])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("原请求记录", result["cross_run_reuse"]["rejections"][0]["reason"])

    def test_cross_run_same_image_id_with_different_pixels_cannot_hit(self):
        self.run_fixture()
        changed = self.root / "changed.ppm"
        changed.write_bytes(b"P6\n1 1\n255\n\x00\xff\x00")
        sample = self.root / "changed-sample.json"
        cards.write_new(sample, {"images": [{**self.row, "local_path": str(changed), "sha256": cards.digest(changed)}]})
        result = cards.run(sample, self.prior, self.root / "unused",
                           reuse_prepared=[self.root / "out/prepared-manifest.json"])
        self.assertEqual(result["cross_run_reuse"]["matched_images"], 0)
        self.assertIn("SHA", result["cross_run_reuse"]["rejections"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
