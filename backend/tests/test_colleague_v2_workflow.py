"""v2 新合同的极小离线夹具；不调用模型、不写生产结果。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.visual_workflow import colleague_v2 as workflow


def write_ref(folder, name, value):
    path = folder / name
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode())
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def brief_fixture():
    return {"dataset_mode": "synthetic_fixture", "direction_id": "fixture-CMF", "branch": "CMF",
            "comparison_unit": "surface", "primary_relation": "fixture 可指认的表面关系",
            "semantic_to_visual_translation": "fixture 语义到可见关系的探索，不表示用户认可",
            "required_evidence": ["fixture 指定表面关系可见"], "allowed_variation": ["fixture 载体变化"],
            "confounders": ["fixture 强图案"], "scope_limits": ["fixture 不证明物理工艺"],
            "negative_audit": [], "deferred_obligations": [], "candidate_pool_policy": {"target": 100},
            "count_policy": {"target": 10, "minimum": 10, "maximum": 10},
            "frozen_before_final_selection": True}


class ColleagueWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="prism-v2-synthetic-")
        self.folder = Path(self.temp.name)
        self.support = workflow.SUPPORT_DIR

    def tearDown(self):
        self.temp.cleanup()

    def board_fixture(self, count=10):
        brief_ref = write_ref(self.folder, "brief.json", brief_fixture())
        board_ref = write_ref(self.folder, "board.bin", b"synthetic fixture rendered board, no real visual review")
        trace = write_ref(self.folder, "review-trace.txt", b"synthetic fixture, not an actual visual reading")
        tiles = []
        for n in range(count):
            image = write_ref(self.folder, f"original-{n}.bin", f"synthetic original {n}".encode())
            view = write_ref(self.folder, f"view-{n}.bin", f"synthetic actual view {n}".encode())
            evidence = write_ref(self.folder, f"project-{n}.txt", f"fixture verified project {n}".encode())
            tiles.append({"image_id": f"fixture-{n}", "original_ref": image, "view_ref": view,
                          "article_id": f"article-{n}", "source_group_id": f"group-{n}",
                          "source_project_id": f"project-{n}", "identity_basis": {
                              "reason": "synthetic identity fixture", "quote": f"fixture verified project {n}",
                              "evidence_ref": evidence}})
        board = {"dataset_mode": "synthetic_fixture", "branch": "CMF", "direction_id": "fixture-CMF",
                 "brief_ref": brief_ref, "rendered_board_ref": board_ref, "tiles": tiles}
        board_file = self.folder / "manifest.json"
        board_manifest_ref = write_ref(self.folder, "manifest.json", board)
        review = {"review_kind": "synthetic_fixture", "reviewer_actor": "synthetic fixture",
                  "review_trace_ref": trace, "board_manifest_sha256": board_manifest_ref["sha256"],
                  "rendered_board_sha256": board_ref["sha256"], "brief_sha256": brief_ref["sha256"],
                  "visual_judgment": "pass", "slots": [{"image_id": t["image_id"], "can_remain": True} for t in tiles]}
        write_ref(self.folder, "review.json", review)
        return board, review, board_file, self.folder / "review.json"

    def identity_fixture(self, board, *, shared_quote=False):
        members, sources = [], []
        if shared_quote:
            shared = write_ref(self.folder, "shared-identity.txt", b"the same design project Example A")
        for n, tile in enumerate(board["tiles"]):
            name = "Example A" if shared_quote else f"Example project {n}"
            quote = "the same design project Example A" if shared_quote else f"Designer source confirms independent {name}"
            source = shared if shared_quote else write_ref(self.folder, f"specific-project-{n}.txt", quote.encode())
            sources.extend([source, tile["identity_basis"]["evidence_ref"]])
            members.append({**deepcopy(tile), "verdict": "distinct_project_verified",
                            "reason": "synthetic source reading fixture, not a real source review",
                            "project_identity_evidence": {"evidence_ref": source, "quote": quote,
                                                          "project_name": name, "project_identity_key": f"fixture-key-{n}"}})
        context = {"review_kind": "synthetic_fixture", "reviewer_actor": "synthetic-source-reviewer", "context_id": "fixture-source-context"}
        raw_ref = write_ref(self.folder, "identity-raw.json", {**context, "members": members})
        trace_ref = write_ref(self.folder, "identity-trace.json", {**context, "sources_actually_read": True,
                              "executed_at": "2026-10-06T00:00:00+08:00", "source_refs": sources})
        review_ref = write_ref(self.folder, "identity-review.json", {**context, "members": members,
                              "raw_output_ref": raw_ref, "review_trace_ref": trace_ref})
        board["project_identity_review_ref"] = review_ref
        return board

    def test_explicit_candidate_budget_and_pause(self):
        policy = workflow.default_project_policy({"target": 177}, {"visual_requests": 100})
        self.assertEqual(policy["quantity_policy"], {"target": 10, "native_minimum": 10, "maximum": 10})
        self.assertEqual(policy["candidate_pool_policy"]["target"], 177)
        self.assertEqual(policy["execution_budget"], {"visual_requests": 100})
        self.assertTrue(policy["model_calls_paused"])
        self.assertFalse(policy["execution_authorization"]["allowed"])
        self.assertEqual(policy["model_policy"]["model"], "gpt-6-sol")
        with self.assertRaises(ValueError): workflow.default_project_policy({}, {})

    def test_family_not_generic_low_chroma_or_five_lines(self):
        brief = brief_fixture()
        self.assertTrue(workflow.validate_visual_family(brief)["valid"])
        brief["comparison_unit"] = "paired_surfaces"
        self.assertFalse(workflow.validate_visual_family(brief)["valid"])
        brief = brief_fixture(); brief["branch"] = "ID"
        self.assertFalse(workflow.validate_visual_family(brief)["valid"])
        brief["comparison_unit"] = "whole_object"
        self.assertTrue(workflow.validate_visual_family(brief)["valid"])

    def test_missing_translation_or_count_cannot_pass(self):
        for key in ("semantic_to_visual_translation", "negative_audit", "deferred_obligations"):
            brief = brief_fixture(); brief.pop(key)
            with self.subTest(key=key): self.assertFalse(workflow.validate_visual_family(brief)["valid"])
        brief = brief_fixture(); brief["count_policy"]["minimum"] = 4
        self.assertFalse(workflow.validate_visual_family(brief)["valid"])

    def test_hash_ref_detects_changed_actual_crop(self):
        ref = write_ref(self.folder, "crop.bin", b"synthetic initial crop")
        Path(ref["path"]).write_bytes(b"synthetic changed crop")
        with self.assertRaises(ValueError): workflow.checked_file_ref(ref)

    def test_four_or_five_images_never_upgraded_to_ten(self):
        for count in (4, 5):
            board, review, path, review_path = self.board_fixture(count)
            result = workflow.evaluate_board(path, review_path, budget_exhausted=True)
            with self.subTest(count=count):
                self.assertEqual(result["status"], "unfinished")
                self.assertEqual(result["dimensions"]["quantity"], "fail")
                self.assertFalse(result["eligible_to_report_visual_result"])
                self.assertFalse(result["whole_workflow_complete"])

    def test_ten_synthetic_images_neither_visual_nor_native_pass(self):
        board, review, path, review_path = self.board_fixture()
        result = workflow.evaluate_board(path, review_path)
        self.assertEqual(result["dimensions"]["quantity"], "pass")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("native_h2_gate_not_executed", result["blockers"])
        self.assertFalse(result["new_visual_review_performed"])
        self.assertEqual(result["new_model_calls"], 0)
        self.assertFalse(result["user_approved"])

    def test_independent_source_requires_evidence_not_url(self):
        board, review, path, review_path = self.board_fixture()
        board["tiles"][0]["identity_basis"] = {"reason": "different URL", "quote": "made up",
                                                   "evidence_ref": board["tiles"][0]["identity_basis"]["evidence_ref"]}
        write_ref(self.folder, "manifest.json", board)
        result = workflow.evaluate_board(path, review_path)
        self.assertIn("requires_10_evidenced_independent_projects", result["blockers"])
        self.assertEqual(result["dimensions"]["evidence"], "unknown")

    def test_distinct_ids_same_quote_observed_failure_is_unknown(self):
        board, review, path, review_path = self.board_fixture()
        common = write_ref(self.folder, "same-design-project.txt", b"the same design project Example A")
        for tile in board["tiles"]:
            tile["identity_basis"] = {"reason": "different registered IDs", "evidence_ref": common,
                                      "quote": "the same design project Example A"}
        write_ref(self.folder, "manifest.json", board)
        result = workflow.evaluate_board(path, review_path)
        self.assertEqual(result["dimensions"]["evidence"], "unknown")
        # 即便另填十个不同项目 key，重复同一条来源事实也不能成为十个项目。
        self.identity_fixture(board, shared_quote=True)
        check = workflow.verify_project_identity(board)
        self.assertIn("same_source_quote_cannot_prove_distinct_projects", check["errors"])
        self.assertFalse(check["verified_independent_projects"])

    def test_bound_ten_identity_fixture_machine_valid_without_real_pass(self):
        board, review, path, review_path = self.board_fixture()
        self.identity_fixture(board)
        check = workflow.verify_project_identity(board)
        self.assertEqual(check["machine_contract_check"], "valid", check)
        self.assertFalse(check["verified_independent_projects"])
        self.assertTrue(check["synthetic_fixture"])
        write_ref(self.folder, "manifest.json", board)
        result = workflow.evaluate_board(path, review_path)
        self.assertEqual(result["dimensions"]["evidence"], "unknown")
        self.assertFalse(result["eligible_to_report_visual_result"])
        # 新板对象或文章来源变化，旧来源核实即失效。
        board["tiles"][0]["article_id"] = "another-article"
        check = workflow.verify_project_identity(board)
        self.assertTrue(any("member_binding_changed" in x for x in check["errors"]))

    def test_source_identity_pending_or_modified_original_reply_blocks(self):
        board, review, path, review_path = self.board_fixture()
        self.identity_fixture(board)
        identity = workflow.checked_file_ref(board["project_identity_review_ref"], as_json=True)
        identity["members"][0]["verdict"] = "uncertain"
        board["project_identity_review_ref"] = write_ref(self.folder, "identity-review.json", identity)
        check = workflow.verify_project_identity(board)
        self.assertIn("identity_review_not_original_source_reply", check["errors"])
        self.assertIn("independent_project_not_verified:fixture-0", check["errors"])

    def test_duplicate_project_and_stale_review_block(self):
        board, review, path, review_path = self.board_fixture()
        board["tiles"][1]["source_project_id"] = board["tiles"][0]["source_project_id"]
        ref = write_ref(self.folder, "manifest.json", board)
        review["board_manifest_sha256"] = ref["sha256"]
        write_ref(self.folder, "review.json", review)
        result = workflow.evaluate_board(path, review_path)
        self.assertIn("duplicate_source_project_id", result["blockers"])
        review["rendered_board_sha256"] = "bad"
        write_ref(self.folder, "review.json", review)
        result = workflow.evaluate_board(path, review_path)
        self.assertTrue(any("board_contract_rejected" in x for x in result["blockers"]))

    def test_board_can_veto_member_even_if_summary_pass(self):
        board, review, path, review_path = self.board_fixture()
        review["slots"][0]["can_remain"] = False
        write_ref(self.folder, "review.json", review)
        result = workflow.evaluate_board(path, review_path)
        self.assertFalse(result["eligible_to_report_visual_result"])
        self.assertTrue(any("PASS contradicts member findings" in x for x in result["blockers"]))

    def test_native_whitelist_refuses_model_and_cached_pass(self):
        with self.assertRaises(ValueError): workflow.replay_native("r5", "execute", {})
        with self.assertRaisesRegex(ValueError, "prepared_hash_mismatch"):
            workflow.replay_native("quality", "accept", {"p": {"cached_pass": True}})
        board, review, path, review_path = self.board_fixture()
        result = workflow.evaluate_board(path, review_path, native_module="cmf",
                                         native_arguments={"passed": True})
        self.assertFalse(result["eligible_to_report_visual_result"])

    def test_target_current_crop_and_known_at_no_quality_shortcut(self):
        brief = brief_fixture()
        original = write_ref(self.folder, "original.bin", b"fixture original")
        view = write_ref(self.folder, "actual-view.bin", b"fixture current crop")
        brief_ref = write_ref(self.folder, "brief.json", brief)
        trace = {"dataset_mode": "synthetic_fixture", "original_ref": original, "actual_view_ref": view,
                 "brief_ref": brief_ref, "review_kind": "synthetic_fixture", "reviewer_actor": "fixture",
                 "original_image_seen": True, "actual_view_seen": True, "primary_relation_prominent": True,
                 "confounders_controlled": True, "same_surface_or_same_object_interface": True,
                 "evidence_derived_from_enhancement": False}
        material = {"original_ref": original, "actual_view_ref": view, "brief_ref": brief_ref,
                    "view_review_ref": write_ref(self.folder, "trace.json", trace),
                    "r5_arguments": {}, "quality_arguments": {}, "quality_target_digest": "fixture-target",
                    "observation_bindings": [{"observation_id": "fixture-obs", "value": "known", "at": "original at", "source": "fixture"}]}
        record = {"image_sha256": original["sha256"], "observations": deepcopy(material["observation_bindings"])}
        quality = {"admissible": False, "confirmation_eligible": True,
                   "validated_target": {"image_ref": original, "target_digest": "fixture-target"}}
        with patch.object(workflow, "replay_native", side_effect=[record, quality]):
            result = workflow.validate_target_material(material, brief)
        self.assertIn("native_selected_target_quality_not_admissible", result["errors"])
        self.assertFalse(result["visual_pass_awarded"])
        material["observation_bindings"][0]["at"] = "borrowed other surface"
        with patch.object(workflow, "replay_native", side_effect=[record, quality]):
            result = workflow.validate_target_material(material, brief)
        self.assertIn("binding_not_original_known_observation", result["errors"])

    def test_three_issue_rounds_not_three_request_retries(self):
        issue = {"issue_id": "fixture-outlier", "frozen_brief_ref": {"sha256": "fixture"}, "revision_attempts": []}
        attempt = {"frozen_brief_ref": issue["frozen_brief_ref"], "previous_failure_ref": {"sha256": "old"},
                   "changed_material_refs": [{"sha256": "new"}], "recheck_ref": {"sha256": "check"},
                   "reason": "fixture replace outlier under original criteria"}
        for _ in range(3): issue = workflow.record_revision(issue, attempt)
        with self.assertRaises(ValueError): workflow.record_revision(issue, attempt)
        issue["revision_attempts"] = []
        changed = deepcopy(attempt); changed["frozen_brief_ref"] = {"sha256": "loosened"}
        with self.assertRaises(ValueError): workflow.record_revision(issue, changed)
        self.assertFalse(issue["automatic_failed_request_retry"])


if __name__ == "__main__": unittest.main()
