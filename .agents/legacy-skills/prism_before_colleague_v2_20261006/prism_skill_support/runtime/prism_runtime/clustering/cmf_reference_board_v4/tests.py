"""Boundary regressions, with native R5 and fresh-quality replay. No inference."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from .common import checked, digest, identity
from .fixtures import build, save, proposal, board_review, PNG
from .protocol import (prepare, grouping_view, accept_grouping, prepare_board_review,
                       accept_board_review, check_expansion_gate)


class CMFReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(tempfile.gettempdir()) / "prism-native-tests"
        # All temporary evidence is confined to this owner's delivery directory.
        root.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix="cmf-v4-", dir=root)
        cls.folder = Path(cls.tmp.name).resolve()
        assert cls.folder.is_relative_to(root.resolve())
        cls.args = build(cls.folder / "base")
        cls.prepared = prepare(**cls.args)
        cls.trace = save(cls.folder / "trace.json", {"fixture_only": True, "actual_model_calls": 0, "note": "Synthetic evidence only"})
        cls.proposal = proposal(cls.prepared, cls.trace)
        cls.proposal_ref = save(cls.folder / "proposal.json", cls.proposal)
        cls.grouping = accept_grouping(cls.prepared, cls.proposal_ref)
        p = cls.folder / "synthetic-board.png"
        p.write_bytes(PNG + b"SYNTHETIC BOARD, NOT REAL DESIGN")
        cls.request = prepare_board_review(cls.grouping, identity(p))
        cls.review = board_review(cls.grouping, cls.request, cls.trace)
        cls.review_ref = save(cls.folder / "board-review.json", cls.review)
        cls.acceptance = accept_board_review(cls.grouping, cls.request, cls.review_ref)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def changed_manifest(self, change):
        args = deepcopy(self.args)
        value = checked(args["manifest_ref"])
        change(value)
        args["manifest_ref"] = save(self.folder / (self._testMethodName + "-manifest.json"), value)
        return args

    def changed_proposal(self, change, prepared=None):
        p = prepared or self.prepared
        value = proposal(p, self.trace)
        change(value)
        return accept_grouping(p, save(self.folder / (self._testMethodName + "-proposal.json"), value))

    def test_fresh_native_quality_and_cross_PID_support_do_not_invent_DNA(self):
        self.assertTrue(all(u["status"] == "eligible" for u in self.prepared["units"]))
        self.assertTrue(all(r["quality"] is None for r in self.args["records"]))
        pid_sets = [{f["original_observation"]["parameter_id"] for f in u["facts"]} for u in self.prepared["units"]]
        self.assertEqual(set.intersection(*pid_sets), set())
        self.assertEqual(self.grouping["status"], "candidate_for_board_review")
        self.assertFalse(self.grouping["visual_pass"])
        for bundle in self.args["quality_bundles"]:
            result = checked(bundle["result_ref"])
            self.assertIsNone(result["original_receipt_ref"])
            self.assertEqual(result["prerequisite_global_quality_calls"], 0)
        view = grouping_view(self.prepared)
        self.assertNotIn("r5obs:", str(view["eligible_units"][0]["known_facts"]))
        self.assertEqual(self.grouping["members"][0]["condition_evidence"]["P1"][0]["original_observation"], self.prepared["units"][0]["facts"][0]["original_observation"])

    def test_unrelated_matching_words_cannot_skip_necessary_condition(self):
        g = self.changed_proposal(lambda v: v["members"][0]["conditions"][0].update(verdict="unknown", visual_inference="Same color, but joint relation not visible"))
        self.assertEqual(g["status"], "blocked")
        with self.assertRaisesRegex(ValueError, "grouping_blocked"):
            prepare_board_review(g, self.request["rendered_board_ref"])

    def test_unknown_and_cross_unit_aliases_are_not_repaired(self):
        for alias in ("U999.E1.O01", "U02.E1.O01"):
            with self.assertRaisesRegex(ValueError, "unknown_or_cross_unit"):
                self.changed_proposal(lambda v: v["members"][0]["conditions"][0].update(observation_aliases=[alias]))

    def test_cross_endpoint_attribute_borrowing_is_rejected(self):
        paper = self.args["records"][0]["observations"][2]["observation_id"]
        args = self.changed_manifest(lambda m: m["units"][0]["endpoints"][0].update(observation_ids=[paper]))
        with self.assertRaisesRegex(ValueError, "cross_endpoint_attribute_borrowing"):
            prepare(**args)

    def test_interface_primary_cannot_cite_only_one_endpoint(self):
        g = self.changed_proposal(lambda v: v["members"][0]["conditions"][0].update(observation_aliases=["U01.E1.O01"]))
        self.assertIn("primary_endpoint_evidence_incomplete:U01", g["blockers"])

    def test_interface_requires_actual_same_object_confirmation(self):
        def change(m):
            b = checked(m["units"][0]["target_binding_ref"])
            b["interface_review"]["same_object"] = False
            m["units"][0]["target_binding_ref"] = save(self.folder / "not-same-object.json", b)
        p = prepare(**self.changed_manifest(change))
        self.assertEqual(p["units"][0]["status"], "pending")
        self.assertIn("same_object_interface_not_confirmed", p["units"][0]["reasons"])
        self.assertEqual(len(grouping_view(p)["eligible_units"]), 9)

    def test_pending_original_fact_is_not_a_similarity_anchor(self):
        from ..r5_dual_v2.adapter import load_record
        args = deepcopy(self.args)
        r = args["records"][0]
        raw = checked(r["validation"]["result_identity"])
        raw["pending"] = [{"p": "OPT-002", "at": "body", "reason": "synthetic uncertain reflection"}]
        result_ref = save(self.folder / "pending-R5.json", raw)
        args["records"][0] = load_record(r["asset"], result_ref)
        p = prepare(**args)
        self.assertEqual(p["units"][0]["status"], "pending")
        self.assertNotIn("U01.E1.O01", p["observation_aliases"])
        self.assertTrue(p["units"][0]["withheld_original_facts"])

    def test_missing_quality_stays_pending_with_complete_partition(self):
        args = deepcopy(self.args)
        args["quality_bundles"] = args["quality_bundles"][1:]
        p = prepare(**args)
        g = accept_grouping(p, save(self.folder / "pending-proposal.json", proposal(p, self.trace)))
        self.assertEqual(len(g["dispositions"]), 10)
        self.assertEqual(g["dispositions"][0]["disposition"], "preparation_pending")
        self.assertIn("independent_source_count_outside_policy", g["blockers"])

    def test_unselected_unknowns_remain_visible_to_grouping_model(self):
        from ..r5_dual_v2.adapter import load_record
        args = deepcopy(self.args)
        record = args["records"][0]
        raw = checked(record["validation"]["result_identity"])
        raw["pending"] = [{"p": "OPT-001", "at": "body", "reason": "Material appearance remains unknown"}]
        args["records"][0] = load_record(record["asset"], save(self.folder / "unselected-unknown-R5.json", raw))
        m = checked(args["manifest_ref"])
        unit = m["units"][0]
        binding = checked(unit["target_binding_ref"])
        binding["record_digest"] = args["records"][0]["digest"]
        unit["target_binding_ref"] = save(self.folder / "unselected-unknown-binding.json", binding)
        view = checked(unit["view_ref"])
        view["original_image_review_ref"] = unit["target_binding_ref"]
        unit["view_ref"] = save(self.folder / "unselected-unknown-view.json", view)
        args["manifest_ref"] = save(self.folder / "unselected-unknown-manifest.json", m)
        prepared = prepare(**args)
        self.assertEqual(prepared["units"][0]["status"], "eligible")
        model = grouping_view(prepared)["eligible_units"][0]
        self.assertEqual(model["original_uncertainty"]["original_audit"]["pending"], raw["pending"])
        self.assertNotIn("OPT-001", {f["parameter_id"] for f in model["known_facts"]})

    def test_native_result_tampering_does_not_qualify(self):
        args = deepcopy(self.args)
        result = checked(args["quality_bundles"][0]["result_ref"])
        result["validated_target"]["selected_scope"] = "separate paper"
        args["quality_bundles"][0]["result_ref"] = save(self.folder / "forged-result.json", result)
        with self.assertRaisesRegex(ValueError, "native_quality_result_not_replayable"):
            prepare(**args)

    def test_same_image_wrong_target_cannot_borrow_quality(self):
        args = deepcopy(self.args)
        b = args["quality_bundles"][0]
        target = checked(b["target_ref"])
        target["selected_scope"] = "separate paper"
        target["target_digest"] = digest({k: v for k, v in target.items() if k != "target_digest"})
        target_ref = save(self.folder / "other-target.json", target)
        m = checked(args["manifest_ref"])
        m["units"][0]["target_ref"] = target_ref
        args["manifest_ref"] = save(self.folder / "other-target-manifest.json", m)
        b.update(target_ref=target_ref, target_digest=target["target_digest"])
        with self.assertRaisesRegex(ValueError, "quality_target_mismatch"):
            prepare(**args)

    def test_calibration_derivatives_and_context_are_never_members(self):
        calibration = self.prepared["brief"]["calibration_refs"][0]["ref"]
        args = self.changed_manifest(lambda m: m["images"][0]["provenance_refs"].append(calibration))
        p = prepare(**args)
        self.assertIn("calibration_or_context_not_candidate", p["units"][0]["reasons"])
        self.assertEqual(len(grouping_view(p)["eligible_units"]), 9)

    def test_same_series_cap_applies_across_different_article_ids(self):
        def change(m):
            m["images"][0]["dedup_keys"].append("series:shared")
            m["images"][1]["dedup_keys"].append("series:shared")
        p = prepare(**self.changed_manifest(change))
        g = accept_grouping(p, save(self.folder / "source-proposal.json", proposal(p, self.trace)))
        self.assertIn("same_source_max1:U02", g["blockers"])

    def test_full_negative_audit_and_current_conflict(self):
        with self.assertRaisesRegex(ValueError, "full_negative_audit_required"):
            self.changed_proposal(lambda v: v.update(negative_dispositions=[]))
        g = self.changed_proposal(lambda v: v["negative_dispositions"][0].update(status="current_conflict", affected_unit_aliases=["U01"]))
        self.assertEqual(g["status"], "blocked")
        self.assertEqual(g["negative_audit"], self.prepared["brief"]["negative_audit"])
        self.assertEqual(self.grouping["status"], "candidate_for_board_review")
        self.assertEqual(self.grouping["deferred_obligations"][0]["status"], "unresolved")

    def test_count_nine_does_not_silently_lower_minimum(self):
        def change(v):
            removed = v["members"].pop()
            v["excluded_eligible"].append({"unit_alias": removed["unit_alias"], "reason": "Relation does not fit"})
        g = self.changed_proposal(change)
        self.assertTrue(g["count"]["below_target"])
        self.assertIn("independent_source_count_outside_policy", g["blockers"])

    def test_current_view_target_is_bound(self):
        def change(m):
            view = checked(m["units"][0]["view_ref"])
            view["target_ref"] = m["units"][1]["target_ref"]
            m["units"][0]["view_ref"] = save(self.folder / "wrong-view.json", view)
        with self.assertRaisesRegex(ValueError, "view_binding_mismatch:target_ref"):
            prepare(**self.changed_manifest(change))

    def test_changed_board_bytes_invalidate_old_review(self):
        p = self.folder / "changing-board.png"
        p.write_bytes(PNG + b"first")
        request = prepare_board_review(self.grouping, identity(p))
        review_ref = save(self.folder / "changing-review.json", board_review(self.grouping, request, self.trace))
        p.write_bytes(PNG + b"second")
        with self.assertRaisesRegex(ValueError, "file_hash_changed"):
            accept_board_review(self.grouping, request, review_ref)

    def test_whole_board_must_inspect_all_originals_and_current_views(self):
        review = deepcopy(self.review)
        review["members"][0]["actual_view_seen"] = False
        out = accept_board_review(self.grouping, self.request, save(self.folder / "unseen-view.json", review))
        self.assertEqual(out["status"], "blocked")
        review = deepcopy(self.review)
        review["global_checks"][0].update(verdict="conflict", reason="Only shared captions, unrelated visual families")
        out = accept_board_review(self.grouping, self.request, save(self.folder / "incoherent.json", review))
        self.assertEqual(out["status"], "blocked")

    def test_real_mode_rejects_synthetic_quality_and_source(self):
        args = self.changed_manifest(lambda m: m.update(dataset_mode="real"))
        with self.assertRaisesRegex(ValueError, "synthetic_evidence_in_real_mode"):
            prepare(**args)

    def test_machine_review_cannot_authorize_expansion(self):
        self.assertEqual(self.acceptance["status"], "ready_for_user_feedback")
        self.assertFalse(self.acceptance["expansion_allowed"])
        out = check_expansion_gate(self.acceptance)
        self.assertFalse(out["expansion_allowed"])
        self.assertEqual(out["reason"], "synthetic_cannot_authorize_expansion")


if __name__ == "__main__":
    unittest.main()
