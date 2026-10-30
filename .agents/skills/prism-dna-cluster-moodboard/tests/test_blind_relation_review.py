"""0.5 纯视觉盲审的结构与状态门；假模型不证明真实图片的审美准确率。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import jsonschema

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from finalize_boards import (RELATION_REVIEW_POLICY_VERSION, concrete_relation_review_supported,
                             finalize, reviewed_view_snapshot)
from render_delivery import board_validation
from review_boards import blind_member_inputs, compile_source_pending, review_one, schema
from model_runtime import ref
from test_selected_view_delivery import board_fixture


def relation_fixture():
    board, reviews = board_fixture()
    board["requires_concrete_relation_review"] = True
    review = reviews["reviews"][0]
    reviews["review_policy_version"] = RELATION_REVIEW_POLICY_VERSION
    review["provenance"].update(review_policy_version=RELATION_REVIEW_POLICY_VERSION,
                                 blind_visual_review=True, upstream_explanations_sent=False)
    review["shared_design_relation"] = {
        "statement": "合成测试：连续浅色面与小面积深色接合线对照，不是真实图像结论",
        "visible_anchors": [{"dimension": "color", "visible_relation": "大面积浅色面和少量深色边缘"},
                            {"dimension": "detail_language", "visible_relation": "少量连续接缝组织界面"}]}
    difference = {"strongest_difference": "合成测试：一个表面更粗糙", "difference_assessment": "coordinated",
                  "coordination_reason": "合成测试：粗糙处理仍由同一连续面和边缘组织约束"}
    for member in review["members"]:
        member["relation_evidence"] = {"visible_support": ["合成测试：浅色主面与细深边缘"], **difference}
    review["least_consistent_unit_id"] = board["members"][0]["unit_id"]
    review["pair_checks"] = [{"unit_id_a": board["members"][0]["unit_id"],
                              "unit_id_b": board["members"][1]["unit_id"],
                              "shared_visible_support": ["合成测试：主面与细边缘的比例关系"], **difference}]
    return board, reviews


class BlindRelationReviewTests(unittest.TestCase):
    def test_negative_review_schema_allows_honestly_empty_positive_evidence(self):
        board, reviews = relation_fixture()
        raw = deepcopy(reviews["reviews"][0])
        provenance = raw.pop("provenance")
        sources = raw.pop("source_identity_checks")
        raw["visual_runway_checks"] = [
            {key: source[key] for key in ("unit_id", "image_id", "runway_state", "runway_reason")}
            for source in sources]
        raw.update(visual_verdict="needs_revision", reason="合成失败例：没有可支持的共同设计关系")
        raw["shared_design_relation"] = {"statement": "当前共同关系不成立", "visible_anchors": []}
        for member in raw["members"]:
            member["relation_evidence"].update(visible_support=[], difference_assessment="conflicting")
        raw["pair_checks"][0].update(shared_visible_support=[], difference_assessment="conflicting")
        # 验真 JSON Schema，而非仅断言 minItems 的数字；负向结果不用假造任何正向观察。
        jsonschema.Draft202012Validator(schema()).validate(raw)
        compiled = {**raw, "provenance": provenance, "source_identity_checks": sources}
        reviews["reviews"] = [compiled]
        self.assertFalse(finalize({"boards": [board]}, reviews)["boards"][0]["validation"]["visual"])

    def test_coherent_cannot_pass_with_empty_board_member_or_pair_support(self):
        for scope in ("board", "member", "pair"):
            board, reviews = relation_fixture()
            review = reviews["reviews"][0]
            if scope == "board":
                review["shared_design_relation"]["visible_anchors"] = []
            elif scope == "member":
                review["members"][0]["relation_evidence"]["visible_support"] = []
            else:
                review["pair_checks"][0]["shared_visible_support"] = []
            self.assertEqual(review["visual_verdict"], "coherent")
            self.assertFalse(finalize({"boards": [board]}, reviews)["boards"][0]["validation"]["visual"])

    def test_blind_payload_excludes_upstream_interpretations_but_audit_keeps_them(self):
        board, _ = relation_fixture()
        marker = "不应出现在盲审输入中的上游结论"
        board.update(title=marker, profile={"summary": marker}, mechanical_checks={"explanation": marker})
        sample, units = {}, {}
        for member in board["members"]:
            member.update(crop_reason=marker, design_quality={"grade": "distinctive", "evidence": marker},
                          design_emotion={"axes": {"energy": "lively"}, "expression": marker})
            member["primary_subject"].update(identity=marker, evidence=marker)
            sample[member["image_id"]] = {"sha256": member["sha256"], "sources": [
                {"article_id": "1", "title": marker, "article_url": "https://example.invalid/1"}]}
            units[member["unit_id"]] = {"features": {"color": marker}, "evidence": marker}
        payload, audit = blind_member_inputs(board, sample, units,
                                             {"1": {"text_evidence": [marker]}}, {})
        self.assertNotIn(marker, json.dumps(payload, ensure_ascii=False))
        self.assertIn(marker, json.dumps(audit, ensure_ascii=False))
        self.assertTrue(audit["not_sent_to_visual_model"])
        self.assertFalse(audit["source_identity_review_performed"])
        self.assertEqual(payload[0]["selected_object_bbox"], board["members"][0]["primary_subject"]["bbox"])
        self.assertNotIn("source_identity_checks", schema()["required"])
        self.assertIn("visual_runway_checks", schema()["required"])

    def test_new_candidate_cannot_inherit_old_v4_pass(self):
        board, reviews = board_fixture()
        board["requires_concrete_relation_review"] = True
        result = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertFalse(result["validation"]["visual"])
        self.assertEqual(board_validation(result, None)[1][0]["state"], "revision")

    def test_v5_requires_complete_positive_relation_and_strongest_difference(self):
        board, reviews = relation_fixture()
        result = finalize({"boards": [board]}, reviews)["boards"][0]
        self.assertTrue(result["validation"]["visual"])
        self.assertEqual(board_validation(result, None)[1][0]["state"], "passed")
        for path in ("shared_design_relation", "pair_checks", "least_consistent_unit_id"):
            changed = deepcopy(reviews)
            changed["reviews"][0].pop(path)
            self.assertFalse(finalize({"boards": [board]}, changed)["boards"][0]["validation"]["visual"])
        for field in ("visible_support", "strongest_difference", "coordination_reason"):
            changed = deepcopy(reviews)
            changed["reviews"][0]["members"][0]["relation_evidence"][field] = [] if field == "visible_support" else "  "
            self.assertFalse(finalize({"boards": [board]}, changed)["boards"][0]["validation"]["visual"])

    def test_any_counterevidence_overrules_top_level_coherent(self):
        board, reviews = relation_fixture()
        for state in ("conflicting", "unresolved"):
            for kind in ("member", "pair"):
                changed = deepcopy(reviews)
                review = changed["reviews"][0]
                row = review["members"][0]["relation_evidence"] if kind == "member" else review["pair_checks"][0]
                row["difference_assessment"] = state
                finalized = finalize({"boards": [board]}, changed)["boards"][0]
                self.assertFalse(finalized["validation"]["visual"])
                self.assertEqual(board_validation(finalized, review)[1][0]["state"], "revision")

    def test_pairs_bind_real_distinct_ids_and_include_weakest_member(self):
        board, reviews = relation_fixture()
        original = reviews["reviews"][0]
        for left, right in (("synthetic:0", "invented"), ("synthetic:0", "synthetic:0"),
                            ("synthetic:1", "synthetic:2")):
            review = deepcopy(original)
            review["pair_checks"][0].update(unit_id_a=left, unit_id_b=right)
            self.assertFalse(concrete_relation_review_supported(board, review))
        review = deepcopy(original)
        review["pair_checks"].append(deepcopy(review["pair_checks"][0]))
        self.assertFalse(concrete_relation_review_supported(board, review))

    def test_v5_policy_on_review_alone_still_enforces_new_gate_and_snapshot(self):
        board, reviews = relation_fixture()
        del board["requires_concrete_relation_review"]
        reviews["reviews"][0]["members"][0].pop("relation_evidence")
        self.assertFalse(finalize({"boards": [board]}, reviews)["boards"][0]["validation"]["visual"])
        board, reviews = relation_fixture()
        reviews["reviews"][0]["provenance"]["upstream_explanations_sent"] = True
        self.assertFalse(finalize({"boards": [board]}, reviews)["boards"][0]["validation"]["visual"])
        board, reviews = relation_fixture()
        board["members"].reverse()
        self.assertFalse(finalize({"boards": [board]}, reviews)["boards"][0]["validation"]["visual"])

    def test_one_fake_visual_call_does_not_grant_unseen_source_identity(self):
        board, reviews = relation_fixture()
        fake_answer = deepcopy(reviews["reviews"][0])
        fake_answer.pop("provenance")
        fake_answer["visual_runway_checks"] = [
            {key: row[key] for key in ("unit_id", "image_id", "runway_state", "runway_reason")}
            for row in fake_answer.pop("source_identity_checks")]
        with tempfile.TemporaryDirectory(prefix="prism-blind-review-test-") as directory:
            root = Path(directory)
            sample = {}
            for index, member in enumerate(board["members"]):
                path = root / f"synthetic-{index}.png"
                path.write_bytes(f"synthetic fixture {index}, not an actual image".encode())
                member["sha256"] = ref(path)["sha256"]
                sample[member["image_id"]] = {"sha256": member["sha256"], "local_path": str(path), "sources": []}
            capture = root / f"{board['board_id']}.png"
            capture.write_bytes(b"synthetic capture fixture")
            Path(str(capture) + ".json").write_text(json.dumps({
                **reviewed_view_snapshot(board), "screenshot_ref": ref(capture)}))
            contract = root / "contract.json"
            contract.write_text("{}")

            def fake_execute(folder, **kwargs):
                folder.mkdir(parents=True)
                (folder / "answer.json").write_text(json.dumps(fake_answer))
                (folder / "receipt.json").write_text('{"synthetic_test_only":true}')
                self.assertNotIn("profile", kwargs["payload"])
                return deepcopy(fake_answer)

            with patch("review_boards.execute_structured", side_effect=fake_execute) as call:
                review = review_one(board, sample, {}, {}, root, root / "review", contract)
            self.assertEqual(call.call_count, 1)
            self.assertTrue(all(row["project_state"] == "unknown" for row in review["source_identity_checks"]))
            self.assertFalse(review["provenance"]["source_identity_review_performed"])
            result = finalize({"boards": [board]}, {"review_policy_version": RELATION_REVIEW_POLICY_VERSION,
                                                    "reviews": [review]})["boards"][0]
            self.assertTrue(result["validation"]["visual"])
            self.assertFalse(result["validation"]["source"])
            self.assertEqual(result["status"], "visual_ready_source_pending")
            self.assertEqual(board_validation(result, None)[1][0]["state"], "passed")

    def test_visual_runway_checks_cannot_switch_object(self):
        with self.assertRaisesRegex(ValueError, "目标单元"):
            compile_source_pending({"visual_runway_checks": [{"unit_id": "another", "image_id": "i"}]}, {"u": "i"})

    def test_changed_original_or_sample_identity_blocks_new_and_reused_review(self):
        for mismatch in ("original_bytes", "sample_sha"):
            for existing_answer in (False, True):
                with self.subTest(mismatch=mismatch, existing_answer=existing_answer):
                    with tempfile.TemporaryDirectory(prefix="prism-blind-sha-test-") as directory:
                        root = Path(directory)
                        board, _ = relation_fixture()
                        sample = {}
                        for index, member in enumerate(board["members"]):
                            path = root / f"synthetic-{index}.png"
                            path.write_bytes(f"frozen synthetic original {index}".encode())
                            member["sha256"] = ref(path)["sha256"]
                            sample[member["image_id"]] = {
                                "sha256": member["sha256"], "local_path": str(path), "sources": []}
                        capture = root / f"{board['board_id']}.png"
                        capture.write_bytes(b"frozen synthetic board screenshot")
                        record = Path(str(capture) + ".json")
                        record.write_text(json.dumps({**reviewed_view_snapshot(board), "screenshot_ref": ref(capture)}))
                        before_capture = capture.read_bytes(), record.read_bytes()
                        output = root / "review"
                        saved_answer = output / "calls" / board["board_id"] / "answer.json"
                        if existing_answer:
                            saved_answer.parent.mkdir(parents=True)
                            saved_answer.write_bytes(b'{"synthetic_history":"must remain unchanged"}')
                        image = sample[board["members"][0]["image_id"]]
                        if mismatch == "original_bytes":
                            Path(image["local_path"]).write_bytes(b"different bytes now present at the same path")
                        else:
                            image["sha256"] = "a" * 64
                        with patch("review_boards.execute_structured") as call:
                            with self.assertRaisesRegex(ValueError, "冻结.*SHA.*不一致"):
                                review_one(board, sample, {}, {}, root, output, root / "unused-contract.json")
                        call.assert_not_called()
                        self.assertEqual((capture.read_bytes(), record.read_bytes()), before_capture)
                        self.assertFalse((output / "audit-context").exists())
                        if existing_answer:
                            self.assertEqual(saved_answer.read_bytes(), b'{"synthetic_history":"must remain unchanged"}')


if __name__ == "__main__":
    unittest.main()
