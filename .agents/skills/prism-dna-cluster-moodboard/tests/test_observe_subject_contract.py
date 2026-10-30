"""主体观察协议的少量离线边界；合成值不代表真实设计判断。"""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import observe_sample as observer
import cluster_sample as cluster


def unit(branch="CMF", *, legacy=False):
    """构造全未知事实，测试只验证范围协议，不编造视觉正确性。"""
    definitions = observer.ID_FIELDS if branch == "ID" else observer.CMF_FIELDS
    subject_box = [0.1, 0.1, 0.8, 0.8]
    evidence_box = subject_box[:] if branch == "ID" else [0.2, 0.2, 0.5, 0.5]
    record = {
        "branch": branch, "scope": "合成主物品范围", "bbox": evidence_box,
        "whole_object_visible": branch == "ID", "usable": True,
        "features": {block: {name: None for name in fields} for block, fields in definitions.items()},
        "evidence": "仅用于测试协议", "limitations": [], "reused_fact_ids": [],
    }
    if not legacy:
        record.update({
            "target_role": "primary_object" if branch == "ID" else "primary_object_surface",
            "primary_subject": {"identity": "合成主体", "bbox": subject_box,
                                "whole_visible": True, "evidence": "合成位置依据"},
            "evidence_bbox": evidence_box[:], "display_bbox": [0, 0, 1, 1],
            "design_quality": {"level": "unresolved", "evidence": "合成测试未作设计评价"},
            "whole_appearance": {
                **{block: {name: None for name in fields}
                   for block, fields in observer.WHOLE_APPEARANCE_FIELDS.items()},
                "evidence": "合成测试不补视觉值"},
        })
    return record


def selected_unit(branch="CMF", *, peer=False, detail=True):
    """新协议允许代表性局部，但不由测试夹具授予真实视觉支持。"""
    record = unit(branch)
    record.update(display_scope="representative_detail" if detail else "whole_object",
                  crop_reason="合成取景：该设计连接独立可读，并保留原图核对整体关系", design_emotion=None)
    if peer:
        record["target_role"] = "peer_object" if branch == "ID" else "peer_object_surface"
    if detail:
        record["bbox"] = record["evidence_bbox"] = [0.2, 0.2, 0.5, 0.5]
        record["display_bbox"] = [0.18, 0.18, 0.54, 0.54]
        if branch == "ID":
            record["whole_object_visible"] = False
            record["limitations"] = ["只描述当前连接局部，整物比例与完整结构未知"]
    return record


class SubjectContractTests(unittest.TestCase):
    def test_legacy_decode_preserves_old_version_without_subject_guesses(self):
        old = unit(legacy=True)
        self.assertEqual(observer.decode_unit(old), old)
        self.assertEqual(observer.observed_version(old), observer.LEGACY_VERSION)
        self.assertFalse(observer.SUBJECT_FIELDS.intersection(old))

    def test_new_request_cannot_accept_legacy_or_partial_subject_payload(self):
        with self.assertRaises(jsonschema.ValidationError):
            observer.decode_unit(unit(legacy=True), version=observer.VERSION)
        partial = unit()
        del partial["whole_appearance"]
        with self.assertRaises(jsonschema.ValidationError):
            observer.decode_unit(partial)

    def test_cmf_evidence_can_be_local_while_display_preserves_whole_subject(self):
        current = unit()
        self.assertEqual(observer.decode_unit(current), current)
        cropped = deepcopy(current)
        cropped["display_bbox"] = cropped["evidence_bbox"]
        with self.assertRaisesRegex(ValueError, "完整包含"):
            observer.decode_unit(cropped)

    def test_primary_surface_cannot_borrow_background(self):
        current = unit()
        current["bbox"] = current["evidence_bbox"] = [0, 0, 0.05, 0.05]
        with self.assertRaisesRegex(ValueError, "不能借用背景"):
            observer.decode_unit(current)
        current["target_role"] = "background"
        current["usable"] = False
        self.assertEqual(observer.decode_unit(current)["target_role"], "background")
        current["usable"] = True
        with self.assertRaisesRegex(ValueError, "完整可辨主物品"):
            observer.decode_unit(current)

    def test_id_cannot_crop_to_surface_or_claim_cutoff_as_usable(self):
        current = unit("ID")
        current["bbox"] = current["evidence_bbox"] = [0.2, 0.2, 0.5, 0.5]
        with self.assertRaisesRegex(ValueError, "保留整件"):
            observer.decode_unit(current)
        current = unit("ID")
        current["primary_subject"]["whole_visible"] = False
        with self.assertRaisesRegex(ValueError, "完整可辨主物品"):
            observer.decode_unit(current)

    def test_v2_wire_features_decode_without_losing_new_observations(self):
        current = unit()
        wire = deepcopy(current)
        wire["features"] = {f"f{i}": None for i, _ in enumerate(observer.FEATURE_ORDERS["CMF"])}
        self.assertEqual(observer.decode_unit(wire), current)
        self.assertEqual(observer.observed_version(current), observer.SUBJECT_VERSION)
        self.assertIsNone(current["whole_appearance"]["tone"]["energy"])

    def test_primary_cmf_closeup_requires_explicit_image_or_unit_limit(self):
        current = unit()
        current["primary_subject"]["whole_visible"] = False
        with self.assertRaisesRegex(ValueError, "特写须明确记录"):
            observer.decode_unit(current)
        self.assertEqual(observer.decode_unit(current, image_limitations=["主物品顶端超出画面，不能判断完整长度"]), current)
        current["limitations"] = ["物品顶端被裁切，只描述可见部分"]
        self.assertEqual(observer.decode_unit(current), current)

    def test_same_image_subject_binding_rejects_chair_wall_substitution(self):
        chair, wall = unit("ID"), unit()
        chair["primary_subject"]["identity"] = "中央椅子"
        wall["primary_subject"]["identity"] = "右侧背景墙"
        with self.assertRaisesRegex(ValueError, "主体框冲突"):
            observer.validate_primary_binding([chair, wall])
        wall["usable"] = False
        observer.validate_primary_binding([chair, wall])

    def test_same_subject_allows_coordinate_tail_error_not_repositioning(self):
        first, second = unit("ID"), unit()
        second["primary_subject"]["bbox"][0] += 0.000005
        observer.validate_primary_binding([first, second])
        second["primary_subject"]["bbox"][0] += 0.02
        with self.assertRaisesRegex(ValueError, "主体框冲突"):
            observer.validate_primary_binding([first, second])

    def test_explicit_occlusion_or_folded_whole_shape_limits_match_both_compilers(self):
        for statement in (
            "沙发右前部被银色座椅遮挡，不能确认完整座面、支撑及端部构造。",
            "腰部被上衣遮挡，坐姿折叠改变裤形，不能推断展开后的完整轮廓。",
        ):
            current = unit()
            current["primary_subject"]["whole_visible"] = False
            current["limitations"] = [statement]
            self.assertTrue(observer.has_partial_subject_limitation(current))
            self.assertTrue(cluster.has_partial_subject_limitation(current))
            self.assertEqual(observer.decode_unit(current), current)

    def test_background_occlusion_or_unknown_material_is_not_subject_limit(self):
        for statement in ("背景被遮挡，但主体完整可见。", "不能推断实际材料成分，图中可见完整轮廓。",
                          "不能判断面料真实触感；不能推断用户情绪。"):
            current = unit()
            current["limitations"] = [statement]
            self.assertFalse(observer.has_partial_subject_limitation(current))
            self.assertFalse(cluster.has_partial_subject_limitation(current))

    def test_v3_peer_and_primary_id_cmf_support_representative_crop(self):
        for branch in ("ID", "CMF"):
            for peer in (True, False):
                current = selected_unit(branch, peer=peer)
                self.assertEqual(observer.decode_unit(current, version=observer.VERSION), current)
                self.assertFalse(observer.contains_bbox(current["display_bbox"], current["primary_subject"]["bbox"]))
                self.assertEqual(observer.observed_version(current), observer.VERSION)

    def test_new_crop_needs_expression_reason_and_must_contain_real_evidence(self):
        current = selected_unit()
        current["crop_reason"] = "  "
        with self.assertRaisesRegex(ValueError, "crop_reason"):
            observer.decode_unit(current)
        current = selected_unit()
        current["display_bbox"] = [0.2, 0.2, 0.1, 0.1]
        with self.assertRaisesRegex(ValueError, "包含本单元事实"):
            observer.decode_unit(current)

    def test_v3_background_still_cannot_be_used_and_whole_id_stays_complete(self):
        current = selected_unit()
        current["target_role"] = "background"
        with self.assertRaisesRegex(ValueError, "主物品或有明确依据"):
            observer.decode_unit(current)
        current = selected_unit("ID", detail=False)
        current["whole_object_visible"] = False
        with self.assertRaisesRegex(ValueError, "整物ID"):
            observer.decode_unit(current)

    def test_v3_local_id_requires_explicit_limitation(self):
        current = selected_unit("ID")
        current["limitations"] = []
        with self.assertRaisesRegex(ValueError, "观察范围限制"):
            observer.decode_unit(current)

    def test_summary_scope_is_bound_to_actual_unit_protocols(self):
        old = {**unit(), "feature_definition_version": observer.SUBJECT_VERSION}
        new = {**selected_unit(), "feature_definition_version": observer.VERSION}
        original = deepcopy([old, new])
        legacy_scope = observer.observation_scope_summary([old])
        current_scope = observer.observation_scope_summary([new])
        mixed_scope = observer.observation_scope_summary([old, new])
        self.assertEqual(legacy_scope["protocol_scopes"][0]["feature_definition_version"], observer.SUBJECT_VERSION)
        self.assertNotIn("代表性局部", legacy_scope["purpose"])
        self.assertIn("代表性局部", current_scope["purpose"])
        self.assertEqual(len(mixed_scope["protocol_scopes"]), 2)
        self.assertEqual([entry["units"] for entry in mixed_scope["protocol_scopes"]], [1, 1])
        self.assertEqual([old, new], original)
        self.assertEqual(observer.observation_scope_summary([])["protocol_scopes"], [])


if __name__ == "__main__":
    unittest.main()
