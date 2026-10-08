"""Small alias boundaries plus unchanged CMF/ID native-quality consumer paths."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from ..id_reference_board_v5.common import checked, digest, identity, seal
from ..r5_dual_v2 import adapter as native
from . import load_record, consumer


def aliased_case(branch, folder):
    if branch == "CMF":
        from ..cmf_reference_board_v4 import fixtures as f
    else:
        from ..id_reference_board_v5 import fixtures as f
    args = f.build(folder)
    before = deepcopy(args)
    original = checked(args["records"][0]["validation"]["result_identity"])
    # This is a new, explicitly synthetic producer fixture with a different
    # original ID. No old raw file or real execution receipt is rewritten.
    original["image_id"] = "synthetic-producer-original-id"
    ref = f.save(folder / "original-ID-synthetic-R5.json", original)
    record = load_record(args["records"][0]["asset"], ref)
    args["records"][0] = record
    m = checked(args["manifest_ref"])
    u = m["units"][0]
    b = checked(u["target_binding_ref"])
    b["record_digest"] = record["digest"]
    u["target_binding_ref"] = f.save(folder / "alias-record-binding.synthetic.json", b)
    v = checked(u["view_ref"])
    v["original_image_review_ref"] = u["target_binding_ref"]
    u["view_ref"] = f.save(folder / "alias-record-view.synthetic.json", v)
    args["manifest_ref"] = f.save(folder / "alias-manifest.synthetic.json", m)
    return args, before, f


class ExactByteAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(tempfile.gettempdir()) / "prism-native-tests"
        root.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix="alias-", dir=root)
        cls.folder = Path(cls.tmp.name).resolve()
        assert cls.folder.is_relative_to(root.resolve())
        cls.cases = {b: aliased_case(b, cls.folder / b) for b in ("CMF", "ID")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def save(self, name, value):
        return self.cases["CMF"][2].save(self.folder / ("case-" + digest([self._testMethodName, name])[:16] + ".json"), value)

    def test_alias_preserves_all_original_facts_audit_and_result_identity(self):
        record = self.cases["CMF"][0]["records"][0]
        alias = record["task_image_id_alias"]
        original = native.load_record(alias["validation_asset"], alias["original_result_ref"])
        for key in original:
            if key not in {"digest", "asset", "image_id"}:
                self.assertEqual(record[key], original[key], key)
        self.assertEqual(original["digest"], alias["original_record_digest"])
        self.assertNotEqual(alias["original_image_id"], alias["current_image_id"])
        self.assertEqual(record["validation"]["result_identity"], alias["original_result_ref"])
        self.assertEqual(checked(alias["original_result_ref"])["image_id"], alias["original_image_id"])

    def test_same_id_keeps_native_output_without_alias(self):
        for _, before, _ in self.cases.values():
            old = before["records"][0]
            self.assertEqual(load_record(old["asset"], old["validation"]["result_identity"]), old)
            self.assertNotIn("task_image_id_alias", old)

    def test_wrong_image_or_claimed_sha_is_rejected(self):
        args = self.cases["CMF"][0]
        record = args["records"][0]
        asset = deepcopy(record["asset"])
        asset["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "exact_image_bytes_required"):
            load_record(asset, record["validation"]["result_identity"])
        other = deepcopy(args["records"][1]["asset"])
        with self.assertRaisesRegex(ValueError, "exact_image_bytes_required"):
            load_record(other, record["validation"]["result_identity"])

    def test_model_version_settings_and_unknown_schema_are_rejected(self):
        record = self.cases["CMF"][0]["records"][0]
        raw = checked(record["validation"]["result_identity"])
        for key, value in (("algorithm_version", "unknown"), ("model", "other-model"), ("reasoning_effort", "high"),
                           ("service_tier_requested", "priority"), ("fast_mode", True), ("model", None),
                           ("schema_version", "unknown-schema")):
            with self.subTest(key=key, value=value):
                changed = deepcopy(raw)
                changed[key] = value
                with self.assertRaises(ValueError):
                    load_record(record["asset"], self.save(key + str(value), changed))

    def test_tampered_bytes_or_inconsistent_original_facts_are_rejected(self):
        record = self.cases["CMF"][0]["records"][0]
        raw = checked(record["validation"]["result_identity"])
        stale = self.save("stale", raw)
        Path(stale["path"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "file_hash_changed"):
            load_record(record["asset"], stale)
        for value in (None, "a-new-inconsistent-value"):
            changed = deepcopy(raw)
            changed["local_features"][0]["v"] = value
            with self.assertRaises(ValueError):
                load_record(record["asset"], self.save("inconsistent", changed))

    def test_partial_unknowns_stay_unresolved_and_old_quality_is_not_aliased(self):
        record = self.cases["CMF"][0]["records"][0]
        raw = checked(record["validation"]["result_identity"])
        raw["status"] = "partial"
        raw["pending"] = [{"p": "OPT-002", "at": "body", "reason": "not resolved in original"}]
        ref = self.save("partial", raw)
        r = load_record(record["asset"], ref)
        self.assertEqual(r["original_audit"]["pending"], raw["pending"])
        self.assertEqual(r["producer_metadata"]["status"], "partial")
        cmf = consumer("CMF")
        clean, _ = cmf.prepare.__globals__["_record"](r, {"image_id": r["image_id"], "image_ref": r["asset"]["image_ref"], "source_kind": "trend"}, "synthetic_fixture")
        self.assertFalse(any(o["at"] == "body" and o["parameter_id"] == "OPT-002" for o in clean.values()))
        with self.assertRaisesRegex(ValueError, "alias_requires_separate_current_target_quality"):
            load_record(record["asset"], ref, self.cases["CMF"][0]["quality_bundles"][0]["result_ref"])

    def test_both_consumers_prepare_and_review_with_unchanged_quality(self):
        for branch, (args, before, f) in self.cases.items():
            with self.subTest(branch=branch):
                api = consumer(branch)
                p = api.prepare(**args)
                self.assertTrue(all(u["status"] == "eligible" for u in p["units"]))
                self.assertEqual(args["quality_bundles"], before["quality_bundles"])
                trace = f.save(self.folder / branch / "trace.json", {"fixture_only": True, "model_calls": 0})
                # Each proposal template is generated by the isolated API, since
                # the original unwrapped consumer must still reject aliases.
                template = api.grouping_template(p)
                for row in template["members"]:
                    unit = next(u for u in p["units"] if u["unit_alias"] == row["unit_alias"])
                    row.update(selection_reason="synthetic alias transport case", original_image_seen=True, actual_view_seen=True)
                    for c in row["conditions"]:
                        c.update(verdict="supported", observation_aliases=[x["alias"] for x in unit["facts"]], visual_inference="synthetic review")
                    for field, verdict in (("variations", "within"), ("confounders", "controlled")):
                        for c in row[field]:
                            c.update(verdict=verdict, reason="synthetic review")
                for row in template["negative_dispositions"]:
                    row.update(status="future_product_obligation", reason="original future obligation remains", scope_basis="synthetic scope", deferred_obligation_indices=[0])
                refs = [r for u in p["units"] for r in (u["image"]["image_ref"], u["view"]["actual_view_ref"])]
                template["review_provenance"] = f.provenance(trace, refs)
                proposal_ref = f.save(self.folder / branch / "proposal.json", template)
                g = api.accept_grouping(p, proposal_ref)
                self.assertFalse(g["visual_pass"])
                self.assertEqual(g["status"], "candidate_for_board_review")
                request = api.prepare_board_review(g, args["records"][0]["asset"]["image_ref"])
                review = api.board_review_template(g, request)
                self.assertFalse(review["board_seen"])
                review.update(board_seen=True, verdict="coherent", reason="Synthetic protocol check, not a real review")
                for row in review["members"]:
                    for key in ("original_image_seen", "actual_view_seen", "target_and_endpoints_correct", "tile_matches_current_view",
                                "apparent_scale_comparable", "whole_target_visible", "whole_shape_relations_readable"):
                        if key in row:
                            row[key] = True
                    row["reason"] = "synthetic"
                    for field, verdict in (("conditions", "supported"), ("variations", "within"), ("confounders", "controlled")):
                        for c in row[field]:
                            c.update(verdict=verdict, reason="synthetic")
                for c in review["global_checks"]:
                    c.update(verdict="supported", reason="synthetic")
                for c in review["negative_review"]:
                    c.update(verdict="scope_and_disposition_supported", reason="synthetic; original obligation retained")
                review["review_provenance"] = f.provenance(trace, [request["rendered_board_ref"]] + refs)
                accepted = api.accept_board_review(g, request, f.save(self.folder / branch / "review.json", review))
                self.assertEqual(accepted["status"], "ready_for_user_feedback")
                self.assertFalse(accepted["user_approved"])
                self.assertEqual(p["units"][0]["quality"]["native"], checked(args["quality_bundles"][0]["result_ref"]))
                template["negative_dispositions"] = []
                with self.assertRaisesRegex(ValueError, "full_negative_audit_required"):
                    api.accept_grouping(p, f.save(self.folder / branch / "omitted-negative.json", template))

    def test_original_modules_and_metadata_checks_are_not_monkeypatched(self):
        from ..cmf_reference_board_v4 import protocol as cmf
        from ..id_reference_board_v5 import protocol as idp
        old_load, old_cmf, old_id = native.load_record, cmf.prepare, idp.prepare
        for branch, (args, _, _) in self.cases.items():
            api = consumer(branch)
            self.assertNotEqual(api.prepare.__module__, cmf.prepare.__module__ if branch == "CMF" else idp.prepare.__module__)
            with self.assertRaisesRegex(ValueError, "Original image identity mismatch"):
                (cmf if branch == "CMF" else idp).prepare(**args)
            record = deepcopy(args["records"][0])
            record["task_image_id_alias"]["original_image_id"] = "invented"
            record.pop("digest")
            record = seal(record)
            changed = deepcopy(args)
            changed["records"][0] = record
            with self.assertRaisesRegex(ValueError, "R5_record_not_replayable"):
                api.prepare(**changed)
        self.assertIs(native.load_record, old_load)
        self.assertIs(cmf.prepare, old_cmf)
        self.assertIs(idp.prepare, old_id)


if __name__ == "__main__":
    unittest.main()
