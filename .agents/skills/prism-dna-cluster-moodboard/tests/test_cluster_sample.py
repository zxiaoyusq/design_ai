"""少量离线边界：不调用模型，不把合成数据当视觉验收。"""

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cluster_sample.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("prism_cluster_sample", SCRIPT)
cluster = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cluster
SPEC.loader.exec_module(cluster)


def primary_contract(branch):
    """合成主体观察只用于行为边界，不代表真实图片已完成视觉核验。"""
    return {"feature_definition_version": "v2",
            "target_role": "primary_object" if branch == "ID" else "primary_object_surface",
            "primary_subject": {"identity": "合成主物品", "bbox": [0, 0, 1, 1],
                                "whole_visible": True, "evidence": "合成的主体与取景依据"},
            "evidence_bbox": [0, 0, 1, 1], "display_bbox": [0, 0, 1, 1],
            "design_quality": {"level": "considered", "evidence": "合成的比例与细节组织依据"},
            "whole_appearance": {
                "color": {"hue": "neutral", "chroma": "low", "lightness": "dark", "color_count": "single", "contrast": "low"},
                "design": {"line_language": "straight", "edge": "sharp", "detail_density": "sparse", "composition": "unified"},
                "tone": {"visual_weight": "balanced", "order": "regular", "energy": "quiet"},
                "evidence": "整体颜色、线条组织与调性来自同一合成主物品"}}


def emotion_contract(index):
    """带合成出处的组合解释，不是真实模型观察或实际视觉通过。"""
    return {"image_sha256": f"{index:064x}",
            "design_emotion": {
                "status": "supported",
                "axes": {"affinity": "welcoming", "discipline": "relaxed", "energy": "calm", "weight": "balanced"},
                "visible_basis": {"form": "合成：连续轮廓舒缓转折", "proportion": "合成：宽缓舒展的主体比例",
                                  "color": "合成：整体低对比浅暖配色", "material_texture": "合成：柔和的表面光线过渡",
                                  "detail_language": "合成：收口细节沿整体方向连贯"},
                "coordination_reason": "合成夹具：舒展形体、柔和配色与连续细节共同支持安静亲和的整体解释",
                "expression": "合成的亲和安静组合", "limitations": ["合成数据不能替代真实板审"]},
            "design_emotion_provenance": {
                "schema_version": cluster.DESIGN_EMOTION_VERSION, "image_id": f"i{index:02}",
                "image_sha256": f"{index:064x}", "primary_subject_identity": "合成主物品",
                "primary_subject_bbox": [0, 0, 1, 1], "inference_kind": "subjective_visual_interpretation",
                "observation_ref": {"path": "/synthetic/answer.json", "sha256": "a" * 64},
                "receipt_ref": {"path": "/synthetic/receipt.json", "sha256": "b" * 64},
                "observation_pointer": "/images/0/design_emotion", "prompt_version": "synthetic-combination-v1"}}


def rebind_synthetic_subject(unit):
    unit["design_emotion_provenance"]["primary_subject_identity"] = unit["primary_subject"]["identity"].strip()
    unit["design_emotion_provenance"]["primary_subject_bbox"] = list(unit["primary_subject"]["bbox"])


def selected_contract(unit, *, detail=False, peer=False):
    """显式新协议夹具；不能把历史单主体观察在运行时自动升为同级／局部资格。"""
    unit = copy.deepcopy(unit)
    unit.update(feature_definition_version=cluster.SELECTED_OBJECT_VERSION,
                display_scope="representative_detail" if detail else "whole_object",
                crop_reason="合成：所选对象的连续转折、配色与收口在此范围仍有完整设计表达")
    if peer:
        unit["target_role"] = "peer_object" if unit["branch"] == "ID" else "peer_object_surface"
        unit["primary_subject"]["evidence"] = "合成：与主角并列呈现、独立可辨的同级设计对象，不是背景"
    if detail:
        unit["bbox"] = unit["evidence_bbox"] = [0.2, 0.2, 0.5, 0.5]
        unit["display_bbox"] = [0.15, 0.15, 0.6, 0.6]
        unit["whole_object_visible"] = False
        unit["limitations"] = ["局部ID事实只描述展示的连接与造型，不概括整件对象形态"]
    return unit


def cmf(index=0):
    return {**primary_contract("CMF"), **emotion_contract(index), "unit_id": f"u{index:02}", "image_id": f"i{index:02}", "branch": "CMF",
            "scope": "合成测试表面", "bbox": [0, 0, 1, 1], "usable": True,
            "whole_object_visible": False, "evidence": "合成夹具；不是真实视觉判断",
            "features": {
                "color": {"hue": "neutral", "chroma": "low", "lightness": "dark", "color_count": "single", "contrast": "low"},
                "material": {"appearance": "plastic", "gloss": "matte", "reflection": "diffuse", "transparency": "opaque"},
                "texture": {"family": "none", "scale": None, "density": None, "regularity": None,
                            "direction": None, "edge": None, "representation": "none"}}}


def id_unit(index, count):
    return {**primary_contract("ID"), **emotion_contract(index), "unit_id": f"id{index}", "image_id": f"i{index:02}", "branch": "ID",
            "scope": "合成整体", "bbox": [0, 0, 1, 1], "usable": True, "whole_object_visible": True,
            "features": {"form": {"contour": "straight", "proportion": "balanced", "volume": "slim", "symmetry": "symmetric"},
                         "structure": {"component_count": count, "connection_visibility": "partial", "line_density": "moderate", "layering": "few"},
                         "detail": {"edge": "sharp", "detail_density": "sparse", "composition": "unified"}}}


def observations(number=8):
    return {"schema_version": "synthetic_fixture", "images": [
        {"image_id": f"i{i:02}", "sha256": f"{i:064x}", "local_path": f"/synthetic/{i}.png", "status": "observed",
         "sources": [{"article_id": f"article-{i}", "title": "不参与聚类的标题"}],
         "runway": {"classification": "no", "evidence": "合成场景"}}
        for i in range(number)], "units": [cmf(i) for i in range(number)]}


class ClusterBoundaryTests(unittest.TestCase):
    def test_current_peer_representative_detail_can_be_smaller_than_parent(self):
        unit = selected_contract(cmf(), peer=True, detail=True)
        self.assertTrue(cluster.unit_eligibility(unit)[0])
        member = cluster.member_record(unit, observations(1)["images"][0],
                                       {"average_member_distance": {unit["unit_id"]: 0}}, {})
        self.assertEqual(member["roi"], unit["display_bbox"])
        self.assertEqual(member["display_scope"], "representative_detail")
        self.assertEqual(member["primary_subject"]["bbox"], [0, 0, 1, 1])
        self.assertFalse(cluster.bbox_contains(member["roi"], member["primary_subject"]["bbox"]))

    def test_current_ID_representative_detail_keeps_local_fact_limits(self):
        unit = selected_contract(id_unit(0, "few"), detail=True)
        self.assertTrue(cluster.unit_eligibility(unit)[0])
        unit["limitations"] = []
        self.assertFalse(cluster.unit_eligibility(unit)[0])
        unit["display_scope"] = "whole_object"
        unit["display_bbox"] = [0, 0, 1, 1]
        self.assertFalse(cluster.unit_eligibility(unit)[0])

    def test_current_scope_cannot_borrow_background_or_hide_facts(self):
        for mutation in ("background", "outside_parent", "exclude_fact", "missing_reason"):
            unit = selected_contract(cmf(), detail=True)
            if mutation == "background":
                unit["target_role"] = "background"
            elif mutation == "outside_parent":
                unit["primary_subject"]["bbox"] = [0, 0, 0.1, 0.1]
                rebind_synthetic_subject(unit)
            elif mutation == "exclude_fact":
                unit["display_bbox"] = [0.2, 0.2, 0.1, 0.1]
            else:
                unit["crop_reason"] = " "
            with self.subTest(mutation=mutation):
                self.assertFalse(cluster.unit_eligibility(unit)[0])

    def test_old_observation_cannot_gain_peer_or_detail_eligibility_by_added_label(self):
        unit = selected_contract(cmf(), detail=True, peer=True)
        unit["feature_definition_version"] = "prism.dna_cluster_observation.v2"
        before = copy.deepcopy(unit)
        eligible, reasons = cluster.unit_eligibility(unit)
        self.assertFalse(eligible)
        self.assertIn("selection_scope_requires_current_observation_protocol", reasons)
        self.assertEqual(unit, before)

    def test_current_same_image_peer_objects_have_their_own_emotion_binding(self):
        chair, lamp = selected_contract(cmf()), selected_contract(cmf(), peer=True)
        chair["primary_subject"].update(identity="左侧椅子", bbox=[0, 0, 0.45, 1])
        chair["bbox"] = chair["evidence_bbox"] = chair["display_bbox"] = [0, 0, 0.45, 1]
        lamp["unit_id"] = "peer-lamp"
        lamp["primary_subject"].update(identity="右侧台灯", bbox=[0.55, 0, 0.45, 1])
        lamp["bbox"] = lamp["evidence_bbox"] = lamp["display_bbox"] = [0.55, 0, 0.45, 1]
        for unit in (chair, lamp):
            rebind_synthetic_subject(unit)
        groups, _, dispositions = cluster.cluster_units([chair, lamp])
        self.assertFalse(dispositions)
        self.assertEqual(sum(map(len, groups)), 2)
        lamp["design_emotion_provenance"] = copy.deepcopy(chair["design_emotion_provenance"])
        self.assertFalse(cluster.unit_eligibility(lamp)[0])

    def test_current_same_object_identity_cannot_point_at_two_locations(self):
        first, second = selected_contract(cmf()), selected_contract(cmf(), peer=True)
        second["unit_id"] = "inconsistent-peer"
        second["primary_subject"]["bbox"] = [0.5, 0, 0.5, 1]
        second["bbox"] = second["evidence_bbox"] = [0.5, 0, 0.5, 1]
        rebind_synthetic_subject(second)
        groups, _, dispositions = cluster.cluster_units([first, second])
        self.assertFalse(groups)
        self.assertEqual(len(dispositions), 2)
        self.assertTrue(all(any(reason.startswith("selected_object_binding_conflict:") for reason in row["reasons"])
                            for row in dispositions))

    def test_current_per_object_emotion_progress_does_not_reuse_stale_image_emotion(self):
        data = observations(1)
        data["images"][0]["design_emotion"] = copy.deepcopy(data["units"][0]["design_emotion"])
        data["units"][0] = selected_contract(data["units"][0])
        data["units"][0].pop("design_emotion")
        counts, states = cluster.emotion_progress(data["images"], data["units"], [])
        self.assertEqual(states["i00"], "missing")
        self.assertEqual(counts["missing_emotion_images"], 1)

    def test_only_common_color_without_combination_evidence_is_insufficient(self):
        left, right = cmf(), cmf(1)
        left["features"]["material"] = right["features"]["material"] = {}
        left["features"]["texture"] = right["features"]["texture"] = {}
        for unit in (left, right):
            unit["design_emotion"]["visible_basis"] = dict.fromkeys(cluster.EMOTION_BASIS_FIELDS)
            unit["design_emotion"]["visible_basis"]["color"] = "只有共同配色"
        result = cluster.pair_difference(left, right)
        self.assertEqual(result.status, "insufficient_overlap")
        self.assertIsNone(result.distance)

    def test_original_texture_absence_and_unknown_are_preserved_not_hard_emotion_gates(self):
        left, right = cmf(), cmf(1)
        self.assertEqual(cluster.pair_difference(left, right).status, "comparable")
        right["features"]["texture"] = {}
        self.assertEqual(cluster.pair_difference(left, right).status, "comparable")
        self.assertEqual(left["features"]["texture"]["family"], "none")
        self.assertEqual(right["features"]["texture"], {})

    def test_single_raw_color_gloss_or_material_difference_is_not_a_hard_veto(self):
        left, right = cmf(), cmf(1)
        right["features"]["color"]["chroma"] = "high"
        right["whole_appearance"]["color"]["chroma"] = "high"
        result = cluster.pair_difference(left, right)
        self.assertEqual(result.status, "comparable")
        right["features"]["material"].update({"gloss": "mirror", "reflection": "mirror"})
        self.assertEqual(cluster.pair_difference(left, right).status, "comparable")
        # 仅外观类别不同并非一条普适禁令，其余可见关系仍需联合比较。
        right = cmf(1)
        right["features"]["material"]["appearance"] = "stone"
        self.assertEqual(cluster.pair_difference(left, right).status, "comparable")

    def test_mixed_material_is_not_similarity_evidence_or_automatic_rejection(self):
        left, right = cmf(), cmf(1)
        left["features"]["material"]["appearance"] = "mixed"
        right["features"]["material"]["appearance"] = "mixed"
        result = cluster.pair_difference(left, right)
        self.assertEqual(result.status, "comparable")
        self.assertEqual(result.shared_fields, {"design_emotion_axes": 4})

    def test_multiple_material_appearances_remain_an_explicit_review_issue(self):
        left, right = cmf(), cmf(1)
        right["features"]["material"]["appearance"] = "stone"
        profile = cluster.cluster_profile([left, right])
        self.assertEqual(profile["critical_review_items"][0]["kind"], "material_appearance_transition")
        self.assertFalse(profile["visual_review_performed"])

    def test_observation_v3_appearance_values_are_known_without_rewriting_old_other(self):
        for value in ("leather", "brick", "concrete", "plaster"):
            unit = cmf()
            unit["features"]["material"]["appearance"] = value
            cluster.validate_features(unit)
            self.assertEqual(cluster.pair_difference(unit, unit).status, "comparable")
        legacy = cmf()
        legacy["features"]["material"]["appearance"] = "other"
        self.assertEqual(cluster.pair_difference(legacy, legacy).status, "comparable")
        self.assertEqual(legacy["features"]["material"]["appearance"], "other")

    def test_complete_link_prevents_transitive_chain_and_is_order_stable(self):
        units = [id_unit(0, "few"), id_unit(1, "moderate"), id_unit(2, "many")]
        for unit, weight, affinity in zip(units, ("light", "balanced", "grounded"), ("welcoming", "balanced", "reserved")):
            unit["design_emotion"]["axes"].update({"weight": weight, "affinity": affinity})
        groups, _, _ = cluster.cluster_units(units)
        reverse, _, _ = cluster.cluster_units(list(reversed(units)))
        memberships = lambda rows: sorted(sorted(u["unit_id"] for u in group) for group in rows)
        self.assertEqual(sorted(map(len, groups)), [1, 2])
        self.assertEqual(memberships(groups), memberships(reverse))

    def test_titles_and_directions_do_not_change_memberships(self):
        original = observations()
        changed = copy.deepcopy(original)
        for image in changed["images"]:
            image["sources"][0].update({"title": "完全相反的新名字", "direction_id": "fake-new-theme", "category": "different"})
        first, first_boards = cluster.build_outputs(original)
        second, _ = cluster.build_outputs(changed)
        self.assertEqual([c["unit_ids"] for c in first["clusters"]], [c["unit_ids"] for c in second["clusters"]])
        self.assertEqual(first["summary"]["disposition_count"], 8)
        self.assertEqual(first_boards["boards"][0]["status"], "draft_source_pending")
        self.assertEqual(first_boards["boards"][0]["mechanical_checks"]["independent_project_count"], 0)

    def test_project_identity_is_not_inferred_from_article(self):
        image = observations(1)["images"][0]
        self.assertFalse(cluster.project_identity(image)["supported"])
        self.assertFalse(cluster.project_identity(image, {"project_key": "project-x", "project_state": "source_supported"})["supported"])
        self.assertTrue(cluster.project_identity(image, {"project_key": "project-x", "project_state": "source_supported", "evidence": ["source-quote"]})["supported"])

    def test_surface_identity_unknown_overrides_other_part_image_identity(self):
        image, unit = observations(1)["images"][0], cmf()
        identities = {image["image_id"]: {"project_key": "stone-series", "project_state": "source_supported", "evidence": "article describes stone"},
                      unit["unit_id"]: {"project_state": "unknown", "evidence": "wood cabinet not bound to named stone series"}}
        result = cluster.unit_project_identity(unit, image, identities)
        self.assertFalse(result["supported"])
        self.assertEqual(result["binding_scope"], "unit")
        identities[unit["unit_id"]] = {}
        self.assertFalse(cluster.unit_project_identity(unit, image, identities)["supported"])

    def test_image_identity_requires_explicit_whole_project_scope(self):
        image, unit = observations(1)["images"][0], cmf()
        proof = {"project_key": "house-project", "project_state": "source_supported", "evidence": "source identifies complete house"}
        self.assertFalse(cluster.unit_project_identity(unit, image, {image["image_id"]: proof})["supported"])
        proof["identity_scope"] = "whole_image_project"
        self.assertTrue(cluster.unit_project_identity(unit, image, {image["image_id"]: proof})["supported"])

    def test_unit_source_identity_requires_SHA_and_current_target_binding(self):
        image, unit = observations(1)["images"][0], cmf()
        proof = {"unit_id": unit["unit_id"], "image_id": image["image_id"], "sha256": image["sha256"],
                 "scope": unit["scope"], "roi": unit["bbox"], "project_key": "reviewed-project",
                 "project_state": "source_supported", "evidence": [{"reason": "合成的目标级实审依据"}]}
        result = cluster.unit_project_identity(unit, image, {unit["unit_id"]: proof})
        self.assertTrue(result["supported"])
        self.assertEqual(result["binding_validation"]["status"], "matched")
        # 允许只提供 scope 或 ROI；同时提供时不能让一个匹配掩盖另一个已经变化。
        for omit in ("scope", "roi"):
            one_binding = {key: value for key, value in proof.items() if key != omit}
            self.assertTrue(cluster.unit_project_identity(unit, image, {unit["unit_id"]: one_binding})["supported"])
        invalid = [
            ({**proof, "sha256": "f" * 64}, "original_SHA_missing_or_mismatch"),
            ({key: value for key, value in proof.items() if key != "sha256"}, "original_SHA_missing_or_mismatch"),
            ({**proof, "scope": "同图另一表面"}, "target_scope_mismatch"),
            ({**proof, "roi": [0, 0, 0.5, 0.5]}, "target_ROI_mismatch"),
            ({key: value for key, value in proof.items() if key not in {"scope", "roi"}}, "scope_and_ROI_binding_missing"),
        ]
        for changed, reason in invalid:
            with self.subTest(reason=reason):
                result = cluster.unit_project_identity(unit, image, {unit["unit_id"]: changed})
                self.assertFalse(result["supported"])
                self.assertEqual(result["project_state"], "unknown")
                self.assertIsNone(result["project_key"])
                self.assertIn(reason, result["binding_validation"]["reasons"])
                self.assertEqual(result["binding_validation"]["claimed_project_key"], "reviewed-project")
                member = cluster.member_record(unit, image, {"average_member_distance": {unit["unit_id"]: 0}},
                                               {unit["unit_id"]: changed})
                self.assertIn(reason, member["project_identity_validation"]["reasons"])

    def test_runway_unknown_uses_upper_bound_at_six_eight_ten(self):
        for count, allowed in [(6, 1), (8, 2), (10, 3)]:
            data = observations(count)
            for index in range(allowed):
                data["images"][index]["runway"]["classification"] = "yes"
            _, output = cluster.build_outputs(data, preferred=count)
            board = output["boards"][0]
            self.assertEqual(board["mechanical_checks"]["quantity"], count)
            self.assertTrue(board["mechanical_checks"]["runway_conservative_pass"])
            members = copy.deepcopy(board["members"])
            next(m for m in members if m["runway_state"] == "no")["runway_state"] = "unknown"
            self.assertFalse(cluster.mechanical_checks(members)["runway_conservative_pass"])

    def test_same_project_or_article_never_fills_multiple_board_slots(self):
        data = observations(10)
        identities = {f"i{i:02}": {"project_key": "shared" if i < 4 else f"p{i}", "project_state": "source_supported", "evidence": "synthetic proof", "identity_scope": "whole_image_project"}
                      for i in range(10)}
        data["images"][8]["sources"] = copy.deepcopy(data["images"][9]["sources"])
        _, output = cluster.build_outputs(data, identities)
        board = output["boards"][0]
        self.assertEqual(len(board["members"]), 6)
        self.assertTrue(board["mechanical_checks"]["known_projects_unique"])
        self.assertTrue(board["mechanical_checks"]["source_articles_unique"])

    def test_incomplete_id_and_missing_units_stay_in_ledger(self):
        data = observations(2)
        unit = id_unit(0, "few")
        unit["whole_object_visible"] = False
        data["units"] = [unit]
        output, boards = cluster.build_outputs(data)
        self.assertEqual(output["unit_dispositions"][0]["status"], "evidence_insufficient")
        self.assertEqual(output["image_dispositions"][1]["status"], "no_comparable_unit")
        self.assertFalse(boards["boards"])

    def test_known_view_failure_changes_selection_priority_not_cluster_membership(self):
        data = observations(9)
        failure = {"unit_id": "u00", "sha256": data["images"][0]["sha256"], "roi": [0, 0, 1, 1],
                   "status": "unresolved", "reason": "synthetic current-view readability failure",
                   "reviewed_window_px": [300, 200], "review_ref": {"path": "/synthetic/review.json", "sha256": "a" * 64}}
        original, _ = cluster.build_outputs(data)
        result, boards = cluster.build_outputs(data, view_reviews=[failure])
        self.assertEqual(original["clusters"][0]["unit_ids"], result["clusters"][0]["unit_ids"])
        self.assertNotIn("u00", [row["unit_id"] for row in boards["boards"][0]["members"]])
        alternative = next(row for row in boards["boards"][0]["alternates"] if row["unit_id"] == "u00")
        self.assertEqual(alternative["view_review_status"], "needs_current_view_review")
        self.assertEqual(alternative["roi"], [0, 0, 1, 1])

    def test_view_failure_does_not_transfer_to_other_ROI_or_SHA_and_can_remain_pending(self):
        data = observations(6)
        failure = {"unit_id": "u00", "sha256": data["images"][0]["sha256"], "roi": [0, 0, 1, 1],
                   "status": "unresolved", "reason": "synthetic scope failure", "review_ref": {"path": "/synthetic/review.json", "sha256": "a" * 64}}
        _, boards = cluster.build_outputs(data, view_reviews=[failure])
        self.assertEqual(boards["boards"][0]["view_review_status"], "needs_current_view_review")
        self.assertEqual(len(boards["boards"][0]["members"]), 6)
        for key, value in [("roi", [0, 0, 0.5, 0.5]), ("sha256", "f" * 64)]:
            changed = {**failure, key: value}
            self.assertFalse(cluster.matching_view_failures(data["units"][0], data["images"][0], [changed]))

    def test_minor_background_and_legacy_units_do_not_gain_primary_eligibility(self):
        for role in ("secondary_object", "background", "incidental_detail", "unknown"):
            unit = cmf()
            unit["target_role"] = role
            eligible, reasons = cluster.unit_eligibility(unit)
            self.assertFalse(eligible)
            self.assertIn("target_is_not_an_evidenced_primary_subject", reasons)
        legacy = cmf()
        for field in primary_contract("CMF"):
            legacy.pop(field)
        eligible, reasons = cluster.unit_eligibility(legacy)
        self.assertFalse(eligible)
        self.assertIn("primary_subject_evidence_missing", reasons)
        self.assertNotIn("primary_subject", legacy)

    def test_cmf_displays_whole_subject_but_keeps_fact_scope_and_rejects_micro_display(self):
        unit = cmf()
        unit["bbox"] = unit["evidence_bbox"] = [0.4, 0.4, 0.1, 0.1]
        image = observations(1)["images"][0]
        self.assertTrue(cluster.unit_eligibility(unit)[0])
        member = cluster.member_record(unit, image, {"average_member_distance": {unit["unit_id"]: 0}}, {})
        self.assertEqual(member["roi"], [0, 0, 1, 1])
        self.assertEqual(member["evidence_bbox"], [0.4, 0.4, 0.1, 0.1])
        unit["display_bbox"] = unit["bbox"]
        eligible, reasons = cluster.unit_eligibility(unit)
        self.assertFalse(eligible)
        self.assertIn("display_crops_primary_subject_context", reasons)

    def test_cross_category_ID_uses_design_vocabulary_not_literal_parts_or_shape(self):
        phone, chair = id_unit(0, "few"), id_unit(1, "many")
        phone["category"], chair["category"] = "phone", "chair"
        phone["primary_subject"]["identity"], chair["primary_subject"]["identity"] = "手机", "椅子"
        rebind_synthetic_subject(phone)
        rebind_synthetic_subject(chair)
        chair["features"]["form"].update({"contour": "curved", "proportion": "broad", "volume": "open_frame"})
        chair["features"]["structure"].update({"line_density": "dense", "layering": "many"})
        groups, _, dispositions = cluster.cluster_units([phone, chair])
        self.assertEqual([len(group) for group in groups], [2])
        self.assertFalse(dispositions)
        self.assertEqual(cluster.pair_difference(phone, chair).distance, 0)

    def test_local_color_cannot_hide_observed_combination_emotion_difference(self):
        left, right = cmf(), cmf(1)
        right["whole_appearance"]["color"].update({"hue": "red", "chroma": "high", "lightness": "light"})
        right["design_emotion"]["axes"].update({"affinity": "reserved", "discipline": "precise", "energy": "lively"})
        self.assertEqual(left["features"]["color"], right["features"]["color"])
        result = cluster.pair_difference(left, right)
        self.assertGreater(result.distance, 0.25)
        groups, _, _ = cluster.cluster_units([left, right])
        self.assertEqual(len(groups), 2)

    def test_ID_combination_can_survive_palette_and_individual_axis_difference(self):
        left, right = id_unit(0, "few"), id_unit(1, "many")
        right["whole_appearance"]["color"].update({"hue": "blue", "chroma": "high", "lightness": "light"})
        self.assertEqual(cluster.pair_difference(left, right).status, "comparable")
        right["design_emotion"]["axes"]["energy"] = "lively"
        self.assertEqual(cluster.pair_difference(left, right).distance, 0.25)
        self.assertEqual(len(cluster.cluster_units([left, right])[0]), 1)

    def test_unknown_or_mixed_raw_color_cannot_reduce_joint_emotion_distance(self):
        left, right = id_unit(0, "few"), id_unit(1, "many")
        right["design_emotion"]["axes"]["affinity"] = "balanced"
        expected_design_distance = 0.125
        for unavailable in (None, "mixed"):
            with self.subTest(unavailable=unavailable):
                left["whole_appearance"]["color"]["hue"] = unavailable
                right["whole_appearance"]["color"]["hue"] = unavailable
                result = cluster.pair_difference(left, right)
                self.assertEqual(result.status, "comparable")
                self.assertEqual(result.distance, expected_design_distance)
        right["design_emotion"]["axes"]["affinity"] = None
        self.assertEqual(cluster.pair_difference(left, right).status, "insufficient_overlap")

    def test_old_mixed_design_without_new_emotion_is_insufficient(self):
        left, right = id_unit(0, "few"), id_unit(1, "many")
        for unit in (left, right):
            unit["whole_appearance"]["design"].update({"line_language": "mixed", "edge": "mixed"})
            unit.pop("design_emotion")
        result = cluster.pair_difference(left, right)
        self.assertEqual(result.status, "insufficient_overlap")
        self.assertIsNone(result.distance)
        self.assertIn("design_emotion_observation_missing", result.reasons)

    def test_same_image_different_primary_objects_remain_pending(self):
        chair, wall = id_unit(0, "few"), cmf()
        chair["primary_subject"]["identity"] = "中央椅子"
        wall["primary_subject"]["identity"] = "右側墙面"
        wall["bbox"] = wall["evidence_bbox"] = wall["primary_subject"]["bbox"] = [0.7, 0.1, 0.3, 0.8]
        groups, _, dispositions = cluster.cluster_units([chair, wall])
        self.assertFalse(groups)
        self.assertEqual(len(dispositions), 2)
        for row in dispositions:
            self.assertEqual(row["status"], "evidence_insufficient")
            self.assertIn("same_image_primary_subject_identity_conflict", row["reasons"])
            self.assertIn("same_image_primary_subject_bbox_conflict", row["reasons"])

    def test_same_image_same_identity_cannot_hide_changed_subject_bbox(self):
        whole, surface = id_unit(0, "few"), cmf()
        surface["bbox"] = surface["evidence_bbox"] = surface["primary_subject"]["bbox"] = [0.7, 0.1, 0.3, 0.8]
        groups, _, dispositions = cluster.cluster_units([whole, surface])
        self.assertFalse(groups)
        self.assertIn("same_image_primary_subject_bbox_conflict", dispositions[0]["reasons"])

    def test_same_subject_different_fact_frames_and_unusable_diagnostics_remain_valid(self):
        whole, surface, diagnostic = id_unit(0, "few"), cmf(), cmf(1)
        surface["bbox"] = surface["evidence_bbox"] = [0.4, 0.4, 0.2, 0.2]
        surface["primary_subject"]["identity"] = "  合成主物品  "
        diagnostic["image_id"] = whole["image_id"]
        diagnostic["usable"] = False
        diagnostic["primary_subject"]["identity"] = "不可用背景诊断"
        groups, _, dispositions = cluster.cluster_units([whole, surface, diagnostic])
        self.assertEqual(sum(map(len, groups)), 2)
        self.assertEqual(len(dispositions), 1)
        self.assertNotIn("same_image_primary_subject_identity_conflict", dispositions[0]["reasons"])

    def test_CMF_primary_closeup_can_be_partial_without_claiming_whole_ID(self):
        unit = cmf()
        unit["primary_subject"]["whole_visible"] = False
        unit["limitations"] = ["原图为木柜主要表面特写，主体边缘延伸到画外，不推断完整造型"]
        self.assertTrue(cluster.unit_eligibility(unit)[0])
        id_row = id_unit(0, "few")
        id_row["primary_subject"]["whole_visible"] = False
        self.assertFalse(cluster.unit_eligibility(id_row)[0])

    def test_partial_CMF_needs_explicit_original_unit_or_image_limitation(self):
        unit = cmf()
        unit["primary_subject"]["whole_visible"] = False
        for statements in ([], ["材质实际成分不可确认"]):
            unit["limitations"] = statements
            eligible, reasons = cluster.unit_eligibility(unit)
            self.assertFalse(eligible)
            self.assertIn("partial_CMF_subject_has_no_explicit_crop_limitation", reasons)
        for scope in ("unit", "image"):
            unit["subject_visibility_limitations"] = {scope: ["主物品右端超出画面，仅对可见部分记录"]}
            self.assertTrue(cluster.unit_eligibility(unit)[0])

    def test_subject_geometry_float_tolerance_matches_observer_without_hiding_real_crop(self):
        whole, surface = id_unit(0, "few"), cmf()
        surface["primary_subject"]["bbox"] = [0, 0, 0.999995, 1]
        self.assertFalse(cluster.conflicting_image_subjects([whole, surface]))
        self.assertTrue(cluster.unit_eligibility(surface)[0])
        surface["primary_subject"]["bbox"] = [0, 0, 0.9999, 1]
        self.assertIn(surface["image_id"], cluster.conflicting_image_subjects([whole, surface]))
        self.assertFalse(cluster.unit_eligibility(surface)[0])

    def test_arbitrary_category_identity_and_price_do_not_change_membership_or_selection(self):
        original = observations(9)
        changed = copy.deepcopy(original)
        for index, unit in enumerate(changed["units"]):
            unit.update({"category": ["汽车", "手机", "服装"][index % 3], "price": 10 ** index})
            unit["primary_subject"]["identity"] = f"无关品类与品牌文字-{index}"
            rebind_synthetic_subject(unit)
            changed["images"][index].update({"category": "测试品类", "price": 1 / (index + 1)})
        first, first_boards = cluster.build_outputs(original)
        second, second_boards = cluster.build_outputs(changed)
        self.assertEqual([row["unit_ids"] for row in first["clusters"]], [row["unit_ids"] for row in second["clusters"]])
        self.assertEqual([row["unit_id"] for row in first_boards["boards"][0]["members"]],
                         [row["unit_id"] for row in second_boards["boards"][0]["members"]])

    def test_cross_material_combination_can_share_emotion_without_matching_gloss_or_texture(self):
        textile, metal = cmf(), cmf(1)
        textile["features"]["material"].update({"appearance": "textile", "gloss": "matte", "reflection": "diffuse"})
        textile["features"]["texture"].update({"family": "fiber", "scale": "fine", "density": "dense"})
        metal["features"]["material"].update({"appearance": "metal", "gloss": "glossy", "reflection": "sharp_highlight"})
        metal["features"]["texture"]["family"] = "none"
        textile["design_emotion"]["visible_basis"]["material_texture"] = "浅暖织物表面与宽圆轮廓连贯，织纹不压过主体"
        metal["design_emotion"]["visible_basis"]["material_texture"] = "亮面金属只形成连续柔缓的反光带，暖色主体与圆钝收口共同缓和硬质感"
        metal["design_emotion"]["coordination_reason"] = "暖色宽圆比例、连续高光带和圆钝接缝共同构成亲和松弛的解释，不以金属类别定调"
        groups, _, _ = cluster.cluster_units([textile, metal])
        self.assertEqual([len(group) for group in groups], [2])
        self.assertEqual(cluster.pair_difference(textile, metal).distance, 0)
        self.assertFalse(cluster.cluster_profile(groups[0])["visual_review_performed"])

    def test_same_round_shape_can_have_different_joint_emotion(self):
        soft, precise = cmf(), cmf(1)
        for unit in (soft, precise):
            unit["whole_appearance"]["design"]["line_language"] = "curved"
        soft["features"]["material"]["appearance"] = "textile"
        precise["features"]["material"].update({"appearance": "metal", "gloss": "mirror", "reflection": "mirror"})
        precise["whole_appearance"]["design"]["edge"] = "sharp"
        precise["design_emotion"]["axes"].update({"affinity": "reserved", "discipline": "precise", "weight": "grounded"})
        precise["design_emotion"]["visible_basis"].update({
            "material_texture": "镜面金属形成清晰高反差的映照", "detail_language": "圆主体的锐利接缝与严密收口形成精确感"})
        precise["design_emotion"]["coordination_reason"] = "即使主轮廓圆润，镜面反射、锐缝和厚实体量组合仍显克制而精确"
        # 故意保持同一自然语言标签，证明标题或风格词不影响组合距离。
        self.assertEqual(soft["design_emotion"]["expression"], precise["design_emotion"]["expression"])
        self.assertGreater(cluster.pair_difference(soft, precise).distance, 0.25)
        self.assertEqual(len(cluster.cluster_units([soft, precise])[0]), 2)

    def test_missing_limited_or_label_only_emotion_never_becomes_similarity(self):
        for mutation in ("missing", "limited", "axis_unknown", "label_only", "repeated_label"):
            unit = cmf()
            if mutation == "missing":
                unit.pop("design_emotion")
            elif mutation == "limited":
                unit["design_emotion"]["status"] = "limited"
            elif mutation == "axis_unknown":
                unit["design_emotion"]["axes"]["affinity"] = None
            elif mutation == "label_only":
                unit["design_emotion"]["visible_basis"] = dict.fromkeys(cluster.EMOTION_BASIS_FIELDS)
            else:
                unit["design_emotion"]["visible_basis"] = dict.fromkeys(cluster.EMOTION_BASIS_FIELDS, "亲和")
            with self.subTest(mutation=mutation):
                self.assertFalse(cluster.unit_eligibility(unit)[0])
                self.assertEqual(cluster.pair_difference(unit, unit).status, "insufficient_overlap")

    def test_emotion_binding_requires_current_subject_original_SHA_and_receipt(self):
        for key, value in (("image_sha256", "f" * 64), ("primary_subject_identity", "另一物品"), ("receipt_ref", {})):
            unit = cmf()
            unit["design_emotion_provenance"][key] = value
            with self.subTest(key=key):
                self.assertFalse(cluster.unit_eligibility(unit)[0])
        data = observations(8)
        data["units"][0]["image_sha256"] = "f" * 64
        data["units"][0]["design_emotion_provenance"]["image_sha256"] = "f" * 64
        self.assertTrue(cluster.unit_eligibility(data["units"][0])[0])
        clusters, _ = cluster.build_outputs(data)
        rejected = next(row for row in clusters["unit_dispositions"] if row["unit_id"] == "u00")
        self.assertIn("design_emotion_unit_SHA_does_not_match_original_image", rejected["reasons"])

    def test_emotion_ties_use_whole_context_not_material_category_for_representativeness(self):
        data = observations(9)
        data["units"][0]["whole_appearance"]["color"].update({"hue": "red", "chroma": "high", "contrast": "high"})
        data["units"][8]["features"]["material"]["appearance"] = "metal"
        clusters, output = cluster.build_outputs(data)
        self.assertEqual(clusters["clusters"][0]["unit_count"], 9)
        selected = {unit["unit_id"] for unit in output["boards"][0]["members"]}
        self.assertNotIn("u00", selected)
        self.assertIn("u08", selected)
        profile = output["boards"][0]["profile"]
        self.assertGreater(profile["within_cluster_context_representativeness"]["u00"]["mean_known_difference"],
                           profile["within_cluster_context_representativeness"]["u08"]["mean_known_difference"])
        self.assertFalse(output["boards"][0]["designer_approved"])

    def test_emotion_summary_separates_missing_no_subject_and_declared_states(self):
        data = observations(7)
        data["units"][1]["design_emotion"]["status"] = "limited"
        data["units"][2]["design_emotion"]["status"] = "unresolved"
        data["units"][3].pop("design_emotion")
        data["units"][4]["usable"] = False
        data["units"] = data["units"][:5]
        data["images"][6]["status"] = "failed"
        clusters, boards = cluster.build_outputs(data)
        summary = clusters["summary"]
        self.assertEqual(summary["emotion_unit_status_counts"],
                         {"supported": 1, "limited": 1, "unresolved": 1, "missing": 1, "no_usable_subject": 1})
        self.assertEqual(summary["emotion_image_status_counts"],
                         {"supported": 1, "limited": 1, "unresolved": 1, "missing": 2, "no_usable_subject": 2})
        self.assertEqual(summary["eligible_units"], 1)
        self.assertEqual(summary["missing_emotion_units"], 1)
        self.assertEqual(boards["design_emotion_summary"]["missing_emotion_images"], 2)
        self.assertFalse(summary["all_sample_images_observed"])

    def test_all_technical_observations_can_be_complete_while_all_emotions_are_missing(self):
        data = observations(6)
        for unit in data["units"]:
            unit.pop("design_emotion")
        clusters, boards = cluster.build_outputs(data)
        self.assertTrue(clusters["summary"]["all_sample_images_observed"])
        self.assertEqual(clusters["summary"]["missing_emotion_images"], 6)
        self.assertEqual(clusters["summary"]["missing_emotion_units"], 6)
        self.assertEqual(clusters["summary"]["eligible_units"], 0)
        self.assertFalse(boards["boards"])

    def test_design_merit_prioritizes_evidence_not_category_or_price(self):
        data = observations(9)
        data["units"][0]["design_quality"] = {"level": "ordinary", "evidence": "合成：可读但缺少鲜明设计组织"}
        data["units"][0]["price"] = 999999
        data["units"][8]["design_quality"] = {"level": "distinctive", "evidence": "合成：整体比例与连接形成明确设计关系"}
        _, boards = cluster.build_outputs(data)
        chosen = boards["boards"][0]["members"]
        self.assertEqual(chosen[0]["unit_id"], "u08")
        self.assertNotIn("u00", [member["unit_id"] for member in chosen])
        self.assertEqual(boards["boards"][0]["alternates"][0]["unit_id"], "u00")
        unit = cmf()
        unit["design_quality"]["level"] = "unresolved"
        self.assertFalse(cluster.unit_eligibility(unit)[0])
        unit["design_quality"] = {"level": "distinctive", "evidence": ""}
        self.assertFalse(cluster.unit_eligibility(unit)[0])


if __name__ == "__main__":
    unittest.main()
