"""ID-specific boundary tests using genuine native normalization/replay, synthetic data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from .common import checked, digest, identity
from .fixtures import build, save, proposal, board_review, PNG
from .protocol import prepare, grouping_view, accept_grouping, prepare_board_review, accept_board_review


class WholeIDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(tempfile.gettempdir()) / "prism-native-tests"
        root.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix="id-v5-", dir=root)
        cls.folder = Path(cls.tmp.name).resolve()
        assert cls.folder.is_relative_to(root.resolve())
        cls.args = build(cls.folder / "base")
        cls.p = prepare(**cls.args)
        cls.trace = save(cls.folder / "trace.json", {"fixture_only": True, "model_calls": 0, "note": "not a real visual review"})
        cls.proposal = proposal(cls.p, cls.trace)
        cls.g = accept_grouping(cls.p, save(cls.folder / "proposal.json", cls.proposal))
        board = cls.folder / "board.png"
        board.write_bytes(PNG + b"STATIC SYNTHETIC FIXTURE; NOT A RENDER")
        cls.request = prepare_board_review(cls.g, identity(board))
        cls.review = board_review(cls.g, cls.request, cls.trace)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def local(self, name, value):
        return save(self.folder / ("case-" + digest([self._testMethodName, name])[:16] + ".json"), value)

    def manifest(self, change):
        args = deepcopy(self.args)
        m = checked(args["manifest_ref"])
        change(m)
        args["manifest_ref"] = self.local("manifest", m)
        return args

    def grouping(self, change):
        p = deepcopy(self.proposal)
        change(p)
        return accept_grouping(self.p, self.local("proposal", p))

    def test_native_ID_fresh_multi_at_and_cross_PID_support(self):
        self.assertTrue(all(u["status"] == "eligible" for u in self.p["units"]))
        for u in self.p["units"]:
            result = u["quality"]["native"]
            self.assertEqual((result["branch"], result["scope_kind"], result["decision"]), ("ID", "overall_id", "PASS"))
            self.assertIsNone(result["original_receipt_ref"])
            self.assertEqual(result["prerequisite_global_quality_calls"], 0)
        self.assertTrue(all(r["quality"] is None for r in self.args["records"]))
        self.assertEqual({f["original_observation"]["at"] for f in self.p["units"][1]["facts"]}, {"body", "trim"})
        self.assertEqual(self.p["units"][0]["unit"]["target_declaration"]["kind"], "explicit_ensemble")
        sets = [{f["original_observation"]["parameter_id"] for f in u["facts"]} for u in self.p["units"]]
        self.assertFalse(set.intersection(*sets))
        self.assertEqual(self.g["status"], "candidate_for_board_review")
        self.assertFalse(self.g["visual_pass"])

    def test_wrong_image_and_wrong_branch_fail(self):
        args = deepcopy(self.args)
        args["records"][0]["image_sha256"] = args["records"][1]["image_sha256"]
        args["records"][0].pop("digest")
        args["records"][0]["digest"] = digest(args["records"][0])
        with self.assertRaisesRegex(ValueError, "R5_image_source_mismatch"):
            prepare(**args)
        args = deepcopy(self.args)
        args["quality_bundles"][0]["branch"] = "CMF"
        with self.assertRaisesRegex(ValueError, "quality_bundle_image_source_branch_mismatch"):
            prepare(**args)

    def test_same_image_wrong_target_and_forged_native_result_fail(self):
        args = deepcopy(self.args)
        bundle = args["quality_bundles"][0]
        target = checked(bundle["target_ref"])
        target["selected_scope"] = "neighbor object only"
        target["target_digest"] = digest({k: v for k, v in target.items() if k != "target_digest"})
        target_ref = self.local("wrong-target", target)
        m = checked(args["manifest_ref"])
        m["units"][0]["target_ref"] = target_ref
        m["units"][0]["target_declaration"]["selected_scope"] = target["selected_scope"]
        args["manifest_ref"] = self.local("wrong-target-manifest", m)
        bundle.update(target_ref=target_ref, target_digest=target["target_digest"])
        with self.assertRaisesRegex(ValueError, "quality_target_mismatch"):
            prepare(**args)
        args = deepcopy(self.args)
        result = checked(args["quality_bundles"][0]["result_ref"])
        result["validated_target"]["selected_scope"] = "neighbor"
        args["quality_bundles"][0]["result_ref"] = self.local("forged-result", result)
        with self.assertRaisesRegex(ValueError, "native_quality_result_not_replayable"):
            prepare(**args)

    def test_overall_id_label_cannot_qualify_local_original_or_view(self):
        def original(m):
            unit = m["units"][0]
            b = checked(unit["target_binding_ref"])
            b["overall_target_review"]["visibility"] = "local_only"
            unit["target_binding_ref"] = self.local("local-original", b)
        p = prepare(**self.manifest(original))
        self.assertEqual(p["units"][0]["quality"]["native"]["decision"], "PASS")
        self.assertIn("original_whole_target_not_confirmed", p["units"][0]["reasons"])
        def display(m):
            unit = m["units"][0]
            v = checked(unit["view_ref"])
            v["overall_view_review"]["visibility"] = "local_only"
            unit["view_ref"] = self.local("local-display", v)
        p = prepare(**self.manifest(display))
        self.assertIn("display_is_not_confirmed_whole_ID_view", p["units"][0]["reasons"])

    def test_cross_object_and_cross_original_at_cannot_be_borrowed(self):
        args = self.manifest(lambda m: m["units"][0]["endpoints"][0].update(target_object_ids=["neighbor"]))
        with self.assertRaisesRegex(ValueError, "endpoint_outside_declared_target"):
            prepare(**args)
        oid = self.args["records"][0]["observations"][2]["observation_id"]
        args = self.manifest(lambda m: m["units"][0]["endpoints"][0].update(observation_ids=[oid]))
        with self.assertRaisesRegex(ValueError, "cross_endpoint_attribute_borrowing"):
            prepare(**args)
        def unconfirmed(m):
            u = m["units"][0]
            b = checked(u["target_binding_ref"])
            b["endpoint_reviews"][0]["same_declared_target"] = False
            u["target_binding_ref"] = self.local("other-object-review", b)
        p = prepare(**self.manifest(unconfirmed))
        self.assertIn("endpoint_target_correspondence_pending", p["units"][0]["reasons"])

    def test_explicit_ensemble_requires_actual_overall_relation(self):
        def change(m):
            u = m["units"][0]
            b = checked(u["target_binding_ref"])
            b["overall_target_review"]["ensemble_relation_visible"] = False
            u["target_binding_ref"] = self.local("no-ensemble", b)
        p = prepare(**self.manifest(change))
        self.assertIn("declared_ensemble_relation_not_confirmed", p["units"][0]["reasons"])

    def test_CMF_color_cannot_substitute_for_ID_fact(self):
        color = self.args["records"][0]["observations"][3]
        self.assertEqual(color["views"], ["CMF"])
        args = self.manifest(lambda m: m["units"][0]["endpoints"][0].update(observation_ids=[color["observation_id"]]))
        p = prepare(**args)
        self.assertEqual(p["units"][0]["status"], "pending")
        self.assertNotIn("U01.E1.O01", p["observation_aliases"])

    def test_unknown_anchor_cannot_support_and_original_uncertainty_remains(self):
        from ..r5_dual_v2.adapter import load_record
        args = deepcopy(self.args)
        r = args["records"][0]
        raw = checked(r["validation"]["result_identity"])
        raw["pending"] = [{"p": "GEO-001", "at": "body", "reason": "whole contour uncertain"}]
        args["records"][0] = load_record(r["asset"], self.local("uncertain-R5", raw))
        p = prepare(**args)
        self.assertEqual(p["units"][0]["status"], "pending")
        self.assertNotIn("U01.E1.O01", p["observation_aliases"])
        self.assertEqual(p["units"][0]["original_uncertainty"]["original_audit"]["pending"], raw["pending"])

    def test_unknown_or_cross_unit_alias_is_not_repaired(self):
        for alias in ("U01.E1.O99", "U02.E1.O01"):
            with self.assertRaisesRegex(ValueError, "unknown_or_cross_unit_observation_alias"):
                self.grouping(lambda p: p["members"][0]["conditions"][0].update(observation_aliases=[alias]))

    def test_stale_display_binding_and_changed_view_bytes_fail(self):
        def change(m):
            v = checked(m["units"][0]["view_ref"])
            v["target_ref"] = m["units"][1]["target_ref"]
            m["units"][0]["view_ref"] = self.local("stale-view", v)
        with self.assertRaisesRegex(ValueError, "view_binding_mismatch:target_ref"):
            prepare(**self.manifest(change))
        target = self.folder / "changing-board.png"
        target.write_bytes(PNG + b"before")
        request = prepare_board_review(self.g, identity(target))
        review_ref = self.local("current-review", board_review(self.g, request, self.trace))
        target.write_bytes(PNG + b"after")
        with self.assertRaisesRegex(ValueError, "file_hash_changed"):
            accept_board_review(self.g, request, review_ref)

    def test_same_source_and_nine_members_are_blocked(self):
        def same(m):
            m["images"][0]["dedup_keys"].append("series:shared")
            m["images"][1]["dedup_keys"].append("series:shared")
        p = prepare(**self.manifest(same))
        g = accept_grouping(p, self.local("same-source-proposal", proposal(p, self.trace)))
        self.assertIn("same_source_max1:U02", g["blockers"])
        def nine(p):
            row = p["members"].pop()
            p["excluded_eligible"].append({"unit_alias": row["unit_alias"], "reason": "not visually related"})
        g = self.grouping(nine)
        self.assertIn("independent_source_count_outside_policy", g["blockers"])

    def test_full_negative_audit_current_conflict_and_unresolved_future(self):
        with self.assertRaisesRegex(ValueError, "full_negative_audit_required"):
            self.grouping(lambda p: p.update(negative_dispositions=[]))
        g = self.grouping(lambda p: p["negative_dispositions"][0].update(status="current_conflict", affected_unit_aliases=["U01"]))
        self.assertIn("unresolved_current_negative:N01", g["blockers"])
        self.assertEqual(g["negative_audit"], self.p["brief"]["negative_audit"])
        self.assertEqual(self.g["deferred_obligations"][0]["status"], "unresolved")

    def test_missing_quality_and_calibration_are_accounted_as_pending(self):
        args = deepcopy(self.args)
        args["quality_bundles"] = args["quality_bundles"][1:]
        p = prepare(**args)
        g = accept_grouping(p, self.local("missing-quality", proposal(p, self.trace)))
        self.assertEqual(len(g["dispositions"]), 10)
        self.assertEqual(g["dispositions"][0]["disposition"], "preparation_pending")
        calibration = self.p["brief"]["calibration_refs"][0]["ref"]
        args = self.manifest(lambda m: m["images"][0]["provenance_refs"].append(calibration))
        p = prepare(**args)
        self.assertIn("calibration_or_context_not_candidate", p["units"][0]["reasons"])
        self.assertEqual(len(grouping_view(p)["eligible_units"]), 9)

    def test_real_mode_rejects_synthetic_and_count_policy_cannot_lower_to_nine(self):
        with self.assertRaisesRegex(ValueError, "synthetic_evidence_in_real_mode"):
            prepare(**self.manifest(lambda m: m.update(dataset_mode="real")))
        args = deepcopy(self.args)
        b = checked(args["brief_ref"])
        b["count_policy"]["minimum"] = 9
        args["brief_ref"] = self.local("lower-count", b)
        with self.assertRaisesRegex(ValueError, "ID_minimum_10_source_policy_required"):
            prepare(**args)

    def test_whole_board_review_is_required_and_not_execution_authority(self):
        valid = accept_board_review(self.g, self.request, self.local("whole-review", self.review))
        self.assertEqual(valid["status"], "ready_for_user_feedback")
        self.assertFalse(valid["user_approved"])
        self.assertFalse(valid["execution_authorization_decided_here"])
        r = deepcopy(self.review)
        r["members"][0]["whole_target_visible"] = False
        blocked = accept_board_review(self.g, self.request, self.local("local-tile", r))
        self.assertEqual(blocked["status"], "blocked")
        r = deepcopy(self.review)
        r["global_checks"][0].update(verdict="conflict", reason="same wording but different overall design")
        self.assertEqual(accept_board_review(self.g, self.request, self.local("incoherent", r))["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
