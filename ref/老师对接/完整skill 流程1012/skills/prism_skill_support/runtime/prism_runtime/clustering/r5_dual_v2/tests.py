"""Offline protocol/algorithm tests, never new-image model or business validation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .adapter import adapt_r5, load_record, producer
from .common import digest, identity, seal
from .engine import cluster, validate_request
from .fixtures import build_case, confirmation, fixture_data


def refresh(data):
    for name in ("prepared", "candidates", "selection"):
        data[name].pop("digest")
    data["prepared"]["asset_catalog"] = deepcopy(data["assets"])
    data["prepared"] = seal(data["prepared"])
    data["candidates"]["prepared_digest"] = data["prepared"]["digest"]
    data["candidates"] = seal(data["candidates"])
    data["selection"].update(prepared_digest=data["prepared"]["digest"], candidate_digest=data["candidates"]["digest"])
    data["selection"]["confirmation"]["candidate_digest"] = data["candidates"]["digest"]
    data["selection"] = seal(data["selection"])
    return data


class DualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture_data()

    def run_case(self, branch="CMF", data=None):
        _, scope, request, records = build_case(branch, fixture=data or self.data)
        return scope, request, records, cluster(request, records, scope=scope, confirmation=confirmation(request, scope))

    def test_two_routes_cross_product_and_separate_criteria(self):
        for branch in ("ID", "CMF"):
            _, _, _, result = self.run_case(branch)
            members = {m["image_id"] for g in result["groups"] for m in g["members"]}
            self.assertEqual(members, {"fixture:chair", "fixture:lamp"})
            self.assertEqual(result["summary"]["multi_image_groups"], 1)
            self.assertEqual(len(result["image_dispositions"]), 3)
            self.assertFalse(result["candidate_cards"][0]["crop_performed"])
            self.assertTrue(result["candidate_cards"][0]["Root_original_image_review_required"])

    def test_CMF_does_not_splice_gold_spout_and_matte_handle(self):
        _, _, records, result = self.run_case()
        kettle = next(r for r in records if r["image_id"] == "fixture:kettle")
        self.assertTrue(any(f["value"] == "金色" for f in kettle["image_index"]))
        self.assertTrue(any(f["value"] == "哑光" for f in kettle["image_index"]))
        self.assertFalse(any(m["image_id"] == "fixture:kettle" for g in result["groups"] for m in g["members"]))
        self.assertEqual({m["location"] for m in result["groups"][0]["members"]}, {"表面", "底座"})

    def test_ID_cannot_be_defined_by_color_only_and_CMF_cannot_use_image_union(self):
        _, scope, req, records = build_case("ID", fixture=self.data)
        _, _, cmf, _ = build_case("CMF", fixture=self.data)
        req["patterns"][0]["core"] = cmf["patterns"][0]["core"]
        with self.assertRaisesRegex(ValueError, "ID requires"):
            validate_request(req, records, scope=scope)
        cmf["patterns"][0]["binding_scope"] = "image_index"
        with self.assertRaisesRegex(ValueError, "CMF cannot"):
            validate_request(cmf, records, scope=scope)

    def test_shared_observed_and_variable_features_are_reported(self):
        _, _, _, result = self.run_case()
        group = result["groups"][0]
        self.assertIn({"parameter_id": "OPT-002", "value": "哑光"}, group["shared_observed_features"])
        self.assertTrue(any(f["parameter_id"] == "TEX-002" for f in group["observed_variations"]))
        self.assertTrue(result["candidate_cards"][0]["main_image"]["core_evidence"])

    def test_overlapping_patterns_and_order_independence(self):
        _, scope, req, records = build_case("CMF", fixture=self.data)
        extra = deepcopy(req["patterns"][0]);extra["pattern_id"] = "fixture:P2";extra["label"] = "另一个已确认的合成语义解释"
        req["patterns"].append(extra)
        first = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        second = cluster(req, list(reversed(records)), scope=scope, confirmation=confirmation(req, scope))
        self.assertEqual(first, second)
        self.assertEqual(next(r for r in first["image_dispositions"] if r["image_id"] == "fixture:chair")["pattern_memberships"], ["fixture:P1", "fixture:P2"])

    def test_same_photo_aliases_do_not_become_a_multi_image_group(self):
        data = deepcopy(self.data)
        chair = data["assets"][0]
        data["assets"][1]["sha256"] = chair["sha256"]
        data["results"]["fixture:lamp"] = deepcopy(data["results"]["fixture:chair"])
        data["results"]["fixture:lamp"]["image_id"] = "fixture:lamp"
        data["quality"]["fixture:lamp"]["image_sha256"] = chair["sha256"]
        _, _, _, result = self.run_case(data=refresh(data))
        self.assertEqual(result["groups"][0]["unique_image_count"], 1)
        self.assertEqual(result["groups"][0]["status"], "singleton")
        self.assertEqual(result["summary"]["multi_image_groups"], 0)

    def test_relevant_pending_blocks_local_core_unrelated_pending_is_retained(self):
        data = deepcopy(self.data)
        doc = data["results"]["fixture:lamp"]
        doc["status"] = "partial"
        doc["pending"] = [{"issue": {"fact": {"at": "字母", "p": "TXT-002", "v": "X"}}, "result": {"decision": "uncertain", "value": None}}]
        _, _, _, unrelated = self.run_case(data=data)
        self.assertEqual(unrelated["summary"]["multi_image_groups"], 1)
        doc["pending"][0]["issue"]["fact"].update(at="底座", p="OPT-002", v="哑光")
        _, _, _, related = self.run_case(data=data)
        self.assertEqual(related["groups"][0]["status"], "singleton")
        self.assertEqual(next(r for r in related["image_dispositions"] if r["image_id"] == "fixture:lamp")["status"], "boundary")

    def test_quality_is_purpose_specific_and_does_not_trust_cached_booleans(self):
        data = deepcopy(self.data)
        q = data["quality"]["fixture:lamp"]
        q["uses"]["cmf_reference"]["decision"] = "FAIL"
        q.update(id_admissible=False, cmf_admissible=True)
        self.assertEqual(self.run_case("ID", data)[3]["summary"]["multi_image_groups"], 1)
        cmf = self.run_case("CMF", data)[3]
        self.assertEqual(cmf["groups"][0]["status"], "singleton")
        self.assertTrue(any(o.get("reason") == "purpose_specific_quality_fail" and o["image_id"] == "fixture:lamp" for o in cmf["outcomes"]))

    def test_quality_region_mapping_is_explicit_and_limits_cannot_disappear(self):
        _, scope, req, records = build_case("CMF", fixture=self.data)
        req["quality_bindings"] = []
        result = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        self.assertFalse(result["groups"])
        self.assertTrue(any(o.get("reason") == "quality_scope_pending" for o in result["outcomes"]))
        _, scope, req, records = build_case("CMF", fixture=self.data)
        req["quality_bindings"][0]["acknowledged_limits"] = []
        with self.assertRaisesRegex(ValueError, "limitations"):
            validate_request(req, records, scope=scope)

    def test_research_is_not_quality_eliminated_and_not_auto_promoted_to_main(self):
        data = deepcopy(self.data)
        for asset in data["assets"]:
            asset["source_kind"] = "research"
            data["quality"][asset["image_id"]] = None
        _, _, _, result = self.run_case(data=refresh(data))
        self.assertEqual(result["summary"]["multi_image_groups"], 1)
        self.assertIsNone(result["candidate_cards"][0]["main_image"])
        self.assertTrue(result["candidate_cards"][0]["main_selection_pending"])

    def test_negative_audit_cannot_be_dropped_and_local_does_not_clear_image_scope(self):
        negative = [{"negative_id": "fixture:N1", "statement": "合成高反光排斥", "evidence_refs": ["fixture:N"], "original_condition": "fixture only"}]
        _, scope, req, records = build_case("CMF", fixture=self.data, negative_audit=negative)
        pending = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        self.assertFalse(pending["groups"])
        rule = req["patterns"][0]["negative_rules"][0]
        rule.update(status="executable", parameter_id="OPT-002", forbidden_values=["高光", "镜面外观"], scope="declared_location")
        local = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        self.assertEqual(local["summary"]["multi_image_groups"], 1)
        rule["scope"] = "image"
        whole = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        self.assertFalse(whole["groups"])
        self.assertTrue(any(o.get("reason") == "known_forbidden" and o["image_id"] == "fixture:chair" for o in whole["outcomes"]))
        req["negative_audit"] = []; req["patterns"][0]["negative_rules"] = []
        with self.assertRaisesRegex(ValueError, "negative audit"):
            validate_request(req, records, scope=scope)

    def test_declared_pending_only_locations_remain_in_negative_coverage(self):
        data = deepcopy(self.data)
        data["results"]["fixture:lamp"]["pending"] = [{"issue": {"fact": {"at": "只在未决中声明的区域", "p": "OPT-002", "v": None}}}]
        _, _, _, records = build_case("CMF", fixture=data)
        self.assertIn("只在未决中声明的区域", records[1]["locations"])

    def test_missing_images_are_accounted_and_preflight_never_authorizes_execution(self):
        _, scope, req, records = build_case("CMF", fixture=self.data)
        records = records[:2]
        pre = validate_request(req, records, scope=scope)
        self.assertTrue(pre["passed"]); self.assertFalse(pre["execution_authorized"])
        result = cluster(req, records, scope=scope, confirmation=confirmation(req, scope))
        self.assertEqual(result["summary"]["image_dispositions"]["missing_data"], 1)
        with self.assertRaises(ValueError): cluster(req, records, scope=scope, confirmation={})

    def test_stale_confirmation_unselected_images_and_invented_values_rejected(self):
        _, scope, req, records = build_case("CMF", fixture=self.data)
        conf = confirmation(req, scope)
        req["patterns"][0]["label"] += " changed"
        with self.assertRaisesRegex(ValueError, "stale"):
            cluster(req, records, scope=scope, confirmation=conf)
        req["candidate_image_ids"].append("unselected")
        with self.assertRaisesRegex(ValueError, "shrink or expand"):
            validate_request(req, records, scope=scope)
        req["candidate_image_ids"].pop()
        req["patterns"][0]["core"][0]["allowed_values"] = ["未在原观察中出现的新值"]
        with self.assertRaisesRegex(ValueError, "source anchors"):
            validate_request(req, records, scope=scope)

    def test_changed_transport_or_unknown_positive_rejected(self):
        _, scope, req, records = build_case("CMF", fixture=self.data)
        records[0]["observations"][0]["value"] = "forged"
        with self.assertRaisesRegex(ValueError, "Bound JSON changed"):
            validate_request(req, records, scope=scope)
        raw = deepcopy(self.data["results"]["fixture:chair"])
        raw["local_features"][0]["v"] = "未知"
        raw["features"], _ = producer().r3.normalize([{"feature": f, "source": f["source"]} for f in raw["local_features"]])
        with self.assertRaisesRegex(ValueError, "index disagree"):
            adapt_r5(raw, self.data["assets"][0], self.data["quality"]["fixture:chair"])

    def test_original_saved_R5_view_normalizes_without_reconstructing_geometry(self):
        project = Path(__file__).resolve().parents[3]
        p = project / "outputs/01a0dd0f-c4b6-7ae0-9a61-4bb57a2985de/prism-evaluation-loop/workflow-v2-20260929/imported-r5/HP01.json"
        original = json.loads(p.read_text(encoding="utf-8-sig"))
        asset = {"image_id": original["image_id"], "sha256": original["image_sha256"], "source_kind": "synthetic",
                 "source_id": "historical_R5_protocol_sample", "source_group": "development"}
        record = adapt_r5(original, asset)
        self.assertEqual(len(record["observations"]), len(original["local_features"]))
        self.assertEqual(record["original_audit"]["pending"], original["pending"])
        self.assertFalse(record["validation"]["physical_carrier_identity_verified"])
        self.assertFalse(record["validation"]["file_identity_verified"])
        original["CMF"]["locations"][0]["bounding_box"] = [0, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, "physical carrier or bounding box"):
            adapt_r5(original, asset)

    def test_file_bound_loader_rejects_changed_original_or_result_bytes(self):
        # Hash fixture only: these bytes are deliberately not a visual sample.
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            image = folder / "synthetic-hash-input.bin"
            image.write_bytes(b'not-an-image; identity-only-fixture')
            asset = deepcopy(self.data["assets"][0])
            asset.update(sha256=identity(image)["sha256"], image_path=str(image))
            raw = deepcopy(self.data["results"][asset["image_id"]]); raw["image_sha256"] = asset["sha256"]
            result = folder / "synthetic-result.json"
            result.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            ref = identity(result)
            record = load_record(asset, ref)
            self.assertTrue(record["validation"]["file_identity_verified"])
            self.assertTrue(record["producer_metadata"]["fixture_only"])
            result.write_text(result.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "File identity changed"):
                load_record(asset, ref)
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, "Original image file"):
                load_record(asset, identity(result))


if __name__ == "__main__":
    unittest.main()
