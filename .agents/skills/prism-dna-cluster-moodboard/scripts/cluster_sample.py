#!/usr/bin/env python3
"""按已落盘的多维 DNA 聚类；只产生候选板，不授予视觉或人工通过。"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from design_emotion import (DESIGN_EMOTION_VERSION, EMOTION_AXES, EMOTION_BASIS_FIELDS, SELECTED_OBJECT_VERSION,
                           emotion_binding_matches, selected_subject_groups,
                           validate_display_contract, validate_emotion)

VERSION = "prism.dna-clustering.v5.0.0"
BBOX_TOLERANCE = 1e-5

# 以下锚点是首版显式政策，不是实测审美阈值；改动必须改变输出 policy_digest。
ENUMS = {
    "ID": {
        "form": {
            "contour": ["straight", "curved", "mixed"],
            "proportion": ["slender", "balanced", "broad"],
            "volume": ["flat", "slim", "solid", "open_frame"],
            "symmetry": ["symmetric", "approximate", "asymmetric"],
        },
        "structure": {
            "component_count": ["few", "moderate", "many"],
            "connection_visibility": ["hidden", "partial", "exposed"],
            "line_density": ["sparse", "moderate", "dense"],
            "layering": ["single", "few", "many"],
        },
        "detail": {
            "edge": ["sharp", "rounded", "mixed"],
            "detail_density": ["sparse", "moderate", "dense"],
            "composition": ["unified", "segmented", "repetitive"],
        },
    },
    "CMF": {
        "color": {
            "hue": ["neutral", "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink", "brown", "mixed"],
            "chroma": ["low", "medium", "high"],
            "lightness": ["dark", "middle", "light"],
            "color_count": ["single", "few", "many"],
            "contrast": ["low", "medium", "high"],
        },
        "material": {
            # v1.0.1 对应实际首批缺口：皮革样表面与砖／混凝土／抹灰外观；不推断实材。
            "appearance": ["metal", "glass", "plastic", "textile", "wood", "stone", "paper", "ceramic", "rubber",
                           "leather", "brick", "concrete", "plaster", "mixed", "other"],
            "gloss": ["matte", "satin", "glossy", "mirror"],
            "reflection": ["diffuse", "soft_highlight", "sharp_highlight", "mirror", "directional"],
            "transparency": ["opaque", "translucent", "transparent"],
        },
        "texture": {
            "family": ["none", "grain", "linear", "grid", "organic", "figurative", "geometric", "fiber", "mixed"],
            "scale": ["fine", "medium", "large"],
            "density": ["sparse", "moderate", "dense"],
            "regularity": ["regular", "perturbed", "irregular", "nonrepeat"],
            "direction": ["none", "linear", "crossed", "radial", "curved", "mixed"],
            "edge": ["sharp", "soft", "irregular", "mixed"],
            "representation": ["none", "geometric", "organic", "figurative", "mixed"],
        },
    },
}

ORDINALS = {
    "form.proportion": ["slender", "balanced", "broad"],
    "form.symmetry": ["symmetric", "approximate", "asymmetric"],
    "structure.component_count": ["few", "moderate", "many"],
    "structure.connection_visibility": ["hidden", "partial", "exposed"],
    "structure.line_density": ["sparse", "moderate", "dense"],
    "structure.layering": ["single", "few", "many"],
    "detail.detail_density": ["sparse", "moderate", "dense"],
    "color.chroma": ["low", "medium", "high"],
    "color.lightness": ["dark", "middle", "light"],
    "color.color_count": ["single", "few", "many"],
    "color.contrast": ["low", "medium", "high"],
    "material.gloss": ["matte", "satin", "glossy", "mirror"],
    "material.transparency": ["opaque", "translucent", "transparent"],
    "texture.scale": ["fine", "medium", "large"],
    "texture.density": ["sparse", "moderate", "dense"],
}

# 主体整体语汇独立于产品类别及字面尺寸；旧分支 DNA 继续保留事实出处。
WHOLE_ENUMS = {
    "color": ENUMS["CMF"]["color"],
    "design": {
        "line_language": ["straight", "curved", "mixed"],
        "edge": ["sharp", "rounded", "mixed"],
        "detail_density": ["sparse", "moderate", "dense"],
        "composition": ["unified", "segmented", "repetitive"],
    },
    "tone": {
        "visual_weight": ["light", "balanced", "heavy"],
        "order": ["regular", "mixed", "irregular"],
        "energy": ["quiet", "balanced", "lively"],
    },
}

QUALITY_ORDER = {"distinctive": 0, "considered": 1, "ordinary": 2, "unresolved": 3}

# 分支局部事实与对象上下文分列。材料名称、功能部件数不参与跨品类代表性排序。
CONCRETE_FIELDS = {
    branch: {**{f"whole.{block}": list(fields) for block, fields in WHOLE_ENUMS.items() if block != "tone"},
             **{f"detail.{block}": [field for field in fields if (block, field) not in {
                 ("material", "appearance"), ("structure", "component_count")}]
                for block, fields in blocks.items()}}
    for branch, blocks in ENUMS.items()
}

POLICY = {
    "version": VERSION,
    "algorithm": "constrained_complete_link",
    "raw_DNA_only": False,
    "inference_kind": "subjective_visible_grounded_design_emotion",
    "article_category_brand_price_features_used": False,
    "emotion_expression_used_as_feature": False,
    "empirically_calibrated": False,
    "human_approved": False,
    "branch": {"ID": {"distance_limit": 0.25}, "CMF": {"distance_limit": 0.25}},
    "design_emotion": {
        "schema_version": DESIGN_EMOTION_VERSION,
        "axes": EMOTION_AXES,
        "visible_basis_fields": EMOTION_BASIS_FIELDS,
        "minimum_distinct_visible_basis": 3,
        "supported_status_required": True,
        "all_axes_observed_required": True,
        "distance": "mean_normalized_ordinal_axis_difference",
        "joint_distance_limit": 0.25,
        "single_axis_hard_veto": False,
        "independent_visual_review_required": True,
        "structural_checks_certify_semantic_validity": False,
    },
    "board": {"minimum": 6, "preferred": 8, "maximum": 10, "runway_percentage_max": 30},
    "unknown_policy": "unknown_emotion_axis_or_insufficient_combination_evidence_is_pending_not_similarity",
    "nondiscriminating_values": ["mixed", "other"],
    "source_policy": "article_dedup_and_evidenced_project_identity_are_separate",
    "project_binding_policy": "unit_supplement_requires_matching_SHA_and_scope_or_ROI; all_supplied_bindings_must_match; image_fallback_requires_whole_image_project",
    "prior_view_review_policy": "matching_unit_original_SHA_and_ROI_failures_sort_last_without_changing_clusters_or_ROI; changed_display_requires_current_review",
    "board_selection": "greedy_current_view_then_concrete_comparison_coverage_then_equal_block_mean_difference_then_emotion_medoid_then_design_merit_with_source_constraints",
    "concrete_relation": {"fields": CONCRETE_FIELDS, "four_axes_usage": "coarse_recall_only",
                          "ranking_only": True, "new_acceptance_threshold": None,
                          "distance_aggregation": "equal_mean_of_known_block_means;uncalibrated_candidate_heuristic",
                          "requires_concrete_relation_review": True,
                          "unknown_or_mixed_is_not_similarity": True,
                          "excluded_from_ranking": ["object_category", "material.appearance", "structure.component_count", "whole.tone"]},
    "execution": {"DNA_extraction_before_clustering": True, "terminal_image_states": ["observed", "failed"],
                  "partial_input_requires_explicit_allow_partial": True, "new_DNA_model_calls": 0,
                  "missing_evidence_action": "pending_supplement_list_only;never_implicit_model_call"},
    "global_selection_optimum_proven": False,
    "new_visual_review_performed": False,
    "feature_enums": ENUMS,
    "ordinal_anchors": ORDINALS,
    "whole_appearance_enums": WHOLE_ENUMS,
    "whole_appearance_usage": "color_and_design_concrete_candidate_representativeness;known_coverage_before_difference;no_tone_label_or_material_category_preference",
    "branch_dna_usage": "traceable_concrete_candidate_representativeness_and_independent_combination_review;no_single_field_hard_veto",
    "subject_policy": "explicit_primary_or_evidenced_peer_design_object;representative_detail_requires_current_selection_contract;legacy_primary_only_is_not_automatically_upgraded",
    "same_image_subject_binding": "current_units_bind_emotion_to_their_own_selected_object;legacy_primary_only_units_retain_image_binding;object_identity_and_bbox_must_not_conflict",
    "bbox_float_tolerance": BBOX_TOLERANCE,
    "visibility_scope_policy": "current_representative_ID_detail_or_partial_object_requires_explicit_scope_and_limitations;legacy_CMF_retains_original_crop_limitation_check;off_frame_facts_are_never_inferred",
    "quality_selection": "concrete_representativeness_before_design_merit;ordinary_remains_reviewable;unresolved_is_pending",
    "display_policy": "whole_object_or_evidenced_representative_detail;display_contains_current_fact_evidence_not_necessarily_entire_parent;original_context_and_actual_crop_require_independent_review",
    "change_note": "v5 separates frozen DNA extraction from offline clustering, demotes emotion axes to coarse recall and ranks candidates using traceable concrete block comparisons. These uncalibrated diagnostics never establish a shared design relation or grant visual approval; current independent concrete-relation review is mandatory.",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_bound_reference(reference: dict) -> Any:
    """以同一份字节核对冻结引用并读取，避免把活动文件误当已冻结输入。"""
    raw = Path(reference["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        raise ValueError(f"frozen_reference_SHA_mismatch:{reference['path']}")
    return json.loads(raw)


def validate_sample_scope(observations: dict, sample: dict) -> None:
    """终态检查覆盖冻结样本中的每张图；缺行与偷偷换图均不能称已完成。"""
    expected = {row["image_id"]: row["sha256"] for row in sample["images"]}
    actual = {row["image_id"]: row.get("sha256") for row in observations["images"]}
    if len(expected) != len(sample["images"]) or len(actual) != len(observations["images"]):
        raise ValueError("duplicate_image_id_in_frozen_scope")
    if expected != actual:
        raise ValueError("observation_images_do_not_match_frozen_sample_ID_and_SHA")


def read_prepared(path: Path) -> tuple[dict, dict, dict]:
    manifest = read_json(path)
    if manifest.get("schema_version") != "prism.design_dna_prepared.v1":
        raise ValueError("unsupported_prepared_manifest_version")
    observations = read_bound_reference(manifest["observations_ref"])
    sample = read_bound_reference(manifest["sample_ref"])
    validate_sample_scope(observations, sample)
    stage = extraction_state(observations["images"])
    counts = stage["image_status_counts"]
    expected = {"images": len(observations["images"]), "observed": counts.get("observed", 0),
                "failed": counts.get("failed", 0), "pending": 0}
    if manifest.get("terminal_counts") != expected:
        raise ValueError("prepared_terminal_counts_do_not_match_observations")
    return observations, sample, manifest


def write_new(path: Path, value: Any) -> None:
    """运行结果只新建；修订应放入新目录，避免原审阅被静默失效。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def freeze_input(path: Path, destination: Path) -> tuple[Any, dict[str, str]]:
    """增量 observations 会继续变化；当前输出绑定这一刻的原始输入字节。"""
    raw = path.read_bytes()
    value = json.loads(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(raw)
    return value, file_ref(destination)


def validate_features(unit: dict[str, Any]) -> None:
    branch = unit.get("branch")
    if branch not in ENUMS:
        raise ValueError(f"unknown_branch:{unit.get('unit_id')}")
    features = unit.get("features", {})
    if set(features) - set(ENUMS[branch]):
        raise ValueError(f"unexpected_feature_block:{unit['unit_id']}")
    for block, fields in features.items():
        if set(fields) - set(ENUMS[branch][block]):
            raise ValueError(f"unexpected_feature_field:{unit['unit_id']}:{block}")
        for field, value in fields.items():
            if value is not None and value not in ENUMS[branch][block][field]:
                raise ValueError(f"unknown_enum:{unit['unit_id']}:{block}.{field}:{value}")
    whole = unit.get("whole_appearance", {})
    for block, fields in WHOLE_ENUMS.items():
        values = whole.get(block, {})
        if set(values) - set(fields):
            raise ValueError(f"unexpected_whole_appearance_field:{unit['unit_id']}:{block}")
        for field, value in values.items():
            if value is not None and value not in fields[field]:
                raise ValueError(f"unknown_whole_appearance_enum:{unit['unit_id']}:{block}.{field}:{value}")


def field_difference(path: str, left: str, right: str, left_features: dict, right_features: dict) -> float:
    """限定枚举采用固定锚点；类别不转任意数字，序数只用于已有顺序的属性。"""
    if left == right:
        return 0.0
    if path in ORDINALS:
        order = ORDINALS[path]
        return abs(order.index(left) - order.index(right)) / (len(order) - 1)
    if path in {"form.contour", "detail.edge"} and "mixed" in {left, right}:
        return 0.40
    if path == "form.volume":
        return {frozenset(["flat", "slim"]): 0.30,
                frozenset(["slim", "solid"]): 0.55,
                frozenset(["flat", "solid"]): 0.80}.get(frozenset([left, right]), 1.0)
    if path == "color.hue":
        wheel = {"red": 0, "orange": 1, "brown": 1, "yellow": 2, "green": 4,
                 "cyan": 6, "blue": 8, "purple": 10, "pink": 11}
        if "mixed" in {left, right}:
            return 1.0
        if "neutral" in {left, right}:
            result = 0.50 if "brown" in {left, right} else 0.85
        else:
            delta = abs(wheel[left] - wheel[right])
            result = min(delta, 12 - delta) / 6
        # 低彩度时色相差异的视觉贡献减弱；该条件来自实际观察而非风格标题。
        if left_features["color"].get("chroma") == right_features["color"].get("chroma") == "low":
            result *= 0.50
        return result
    if path == "material.reflection":
        values = ["diffuse", "soft_highlight", "sharp_highlight", "mirror"]
        if left in values and right in values:
            return abs(values.index(left) - values.index(right)) / 3
    if path == "texture.regularity":
        values = ["regular", "perturbed", "irregular"]
        if left in values and right in values:
            return abs(values.index(left) - values.index(right)) / 2
    return 1.0


@dataclass(frozen=True)
class PairResult:
    status: str
    distance: float | None
    block_distances: dict[str, float]
    shared_fields: dict[str, int]
    reasons: tuple[str, ...]


def whole_block_difference(block: str, left: dict, right: dict) -> tuple[float | None, int]:
    """仅用于既成情绪簇内的次级代表性；原整体差异不再决定是否能同板。"""
    lv, rv = left.get(block, {}), right.get(block, {})
    values = []
    for field in WHOLE_ENUMS[block]:
        a, b = lv.get(field), rv.get(field)
        # 调性的 mixed 是有序中间态；其他 mixed 不证明两个混合内容相同。
        if a is None or b is None or (block != "tone" and "mixed" in {a, b}):
            continue
        if block == "tone":
            anchors = WHOLE_ENUMS[block][field]
            difference = abs(anchors.index(a) - anchors.index(b)) / (len(anchors) - 1)
        elif block == "design":
            path = "detail.detail_density" if field == "detail_density" else f"detail.{field}"
            difference = field_difference(path, a, b, left, right)
        else:
            difference = field_difference(f"color.{field}", a, b, left, right)
        values.append(difference)
    return (sum(values) / len(values) if values else None), len(values)


def concrete_values(unit: dict, block: str) -> dict:
    source, name = block.split(".", 1)
    return unit.get("whole_appearance" if source == "whole" else "features", {}).get(name, {})


def concrete_field_state(unit: dict, block: str, field: str) -> str:
    """已明确无纹理的附属属性不要求补提；未给值与混合值均不能算作相同。"""
    value = concrete_values(unit, block).get(field)
    if (block == "detail.texture" and field in {"scale", "density", "regularity", "direction", "edge"}
            and concrete_values(unit, block).get("family") == "none" and value is None):
        return "not_applicable"
    return "known" if value is not None and value not in POLICY["nondiscriminating_values"] else "unresolved"


def concrete_pair_evidence(left: dict, right: dict) -> dict:
    """给候选排序与反证检查保留具体对照，不把字段接近写成实际设计关系成立。"""
    if left["branch"] != right["branch"]:
        raise ValueError("concrete_relation_requires_same_branch")
    blocks, differences = {}, []
    total_known = total_possible = 0
    for block, fields in CONCRETE_FIELDS[left["branch"]].items():
        comparisons, unresolved, not_applicable = [], [], []
        lv, rv = concrete_values(left, block), concrete_values(right, block)
        source, name = block.split(".", 1)
        for field in fields:
            states = [concrete_field_state(unit, block, field) for unit in (left, right)]
            if "not_applicable" in states:
                not_applicable.append(field)
                continue
            if "unresolved" in states:
                unresolved.append(field)
                continue
            path = ("detail.detail_density" if field == "detail_density" else f"detail.{field}") if name == "design" else f"{name}.{field}"
            left_features = left.get("whole_appearance" if source == "whole" else "features", {})
            right_features = right.get("whole_appearance" if source == "whole" else "features", {})
            difference = field_difference(path, lv[field], rv[field], left_features, right_features)
            row = {"field": f"{block}.{field}", "left": lv[field], "right": rv[field], "difference": difference}
            comparisons.append(row)
            if difference:
                differences.append(row)
        possible = len(fields) - len(not_applicable)
        known = len(comparisons)
        total_known += known
        total_possible += possible
        blocks[block] = {"known_comparison_count": known, "possible_comparison_count": possible,
                         "coverage": known / possible if possible else 0.0,
                         "mean_known_difference": sum(row["difference"] for row in comparisons) / known if known else None,
                         "field_comparisons": comparisons, "unresolved_fields": unresolved,
                         "not_applicable_fields": not_applicable}
    means = [row["mean_known_difference"] for row in blocks.values() if row["mean_known_difference"] is not None]
    return {"unit_ids": [left["unit_id"], right["unit_id"]], "blocks": blocks,
            "known_comparison_count": total_known, "possible_comparison_count": total_possible,
            "coverage": total_known / total_possible if total_possible else 0.0,
            "equal_block_mean_difference": sum(means) / len(means) if means else None,
            "differing_fields": sorted(differences, key=lambda row: (-row["difference"], row["field"])),
            "requires_concrete_relation_review": True,
            "semantic_relation_status": "not_established_by_numeric_comparison"}


def concrete_member_profile(group: list[dict]) -> dict:
    """逐块聚合簇内已知比较，保留覆盖；不增加任何成板通过阈值。"""
    totals = {unit["unit_id"]: {block: {"known": 0, "possible": 0, "difference_sum": 0.0}
                               for block in CONCRETE_FIELDS[unit["branch"]]} for unit in group}
    for index, left in enumerate(group):
        for right in group[index + 1:]:
            pair = concrete_pair_evidence(left, right)
            for unit in (left, right):
                for block, row in pair["blocks"].items():
                    target = totals[unit["unit_id"]][block]
                    target["known"] += row["known_comparison_count"]
                    target["possible"] += row["possible_comparison_count"]
                    target["difference_sum"] += (row["mean_known_difference"] or 0) * row["known_comparison_count"]
    result = {}
    for unit_id, blocks in totals.items():
        rows = {block: {"known_comparison_count": row["known"], "possible_comparison_count": row["possible"],
                        "coverage": row["known"] / row["possible"] if row["possible"] else 0.0,
                        "mean_known_difference": row["difference_sum"] / row["known"] if row["known"] else None}
                for block, row in blocks.items()}
        known = sum(row["known"] for row in blocks.values())
        possible = sum(row["possible"] for row in blocks.values())
        means = [row["mean_known_difference"] for row in rows.values() if row["mean_known_difference"] is not None]
        result[unit_id] = {"blocks": rows, "coverage": known / possible if possible else 0.0,
                           "equal_block_mean_difference": sum(means) / len(means) if means else None,
                           "requires_concrete_relation_review": True}
    return result


def emotion_observation_reasons(unit: dict) -> list[str]:
    """组合依据、四轴观察与解释都必须存在；标签相同本身不授予相似或视觉通过。"""
    emotion = unit.get("design_emotion")
    if emotion is None:
        return ["design_emotion_observation_missing"]
    try:
        validate_emotion(emotion)
    except ValueError as exc:
        return [f"invalid_design_emotion_observation:{exc}"]
    reasons = []
    if emotion["status"] != "supported":
        reasons.append("design_emotion_interpretation_not_supported")
    for axis in EMOTION_AXES:
        if emotion["axes"].get(axis) is None:
            reasons.append(f"design_emotion:{axis}:unknown")
    basis = emotion["visible_basis"]
    known = {basis[field].strip() for field in EMOTION_BASIS_FIELDS
             if isinstance(basis.get(field), str) and basis[field].strip()}
    if len(known) < POLICY["design_emotion"]["minimum_distinct_visible_basis"]:
        reasons.append("design_emotion:insufficient_distinct_combination_evidence")
    if not emotion["coordination_reason"].strip():
        reasons.append("design_emotion:coordination_reason_missing")
    return reasons


def pair_difference(left: dict, right: dict) -> PairResult:
    """比较由五类可见组合支持的情绪关系；材质、光泽或某一轴差异不单独硬拒。"""
    if left["branch"] != right["branch"]:
        return PairResult("different_branch", None, {}, {}, ("ID_CMF_separate",))
    missing = emotion_observation_reasons(left) + emotion_observation_reasons(right)
    if missing:
        return PairResult("insufficient_overlap", None, {}, {}, tuple(dict.fromkeys(missing)))
    la, ra = left["design_emotion"]["axes"], right["design_emotion"]["axes"]
    differences = {axis: abs(values.index(la[axis]) - values.index(ra[axis])) / (len(values) - 1)
                   for axis, values in EMOTION_AXES.items()}
    distance = sum(differences.values()) / len(differences)
    # 四轴完全同值仍只是有证据的候选关系，不能替代原图和最终板图的独立组合审阅。
    return PairResult("comparable", distance, {f"design_emotion.{axis}": value for axis, value in differences.items()},
                      {"design_emotion_axes": len(differences)}, ())


def valid_bbox(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)
            and value[0] >= 0 and value[1] >= 0 and value[2] > 0 and value[3] > 0
            and value[0] + value[2] <= 1 + BBOX_TOLERANCE and value[1] + value[3] <= 1 + BBOX_TOLERANCE)


def bbox_contains(outer: list[float], inner: list[float]) -> bool:
    """与观察编译共享浮点尾差尺度，不以数值容差删除可见主体。"""
    return (outer[0] <= inner[0] + BBOX_TOLERANCE and outer[1] <= inner[1] + BBOX_TOLERANCE
            and outer[0] + outer[2] + BBOX_TOLERANCE >= inner[0] + inner[2]
            and outer[1] + outer[3] + BBOX_TOLERANCE >= inner[1] + inner[3])


def has_partial_subject_limitation(unit: dict) -> bool:
    """只消费带出处的原观察限制，不能靠非空说明或面积猜测截断原因。"""
    source = unit.get("subject_visibility_limitations") or {}
    statements = [*unit.get("limitations", []), *source.get("unit", []), *source.get("image", [])]
    pattern = r"截断|裁切|裁掉|出框|超出(?:画面|镜头)|画外|未完整|不完整|局部(?:可见|呈现)|cropped|partial|cut[ -]?off|(?:不能|无法)(?:确认|观察|看清|判断)(?:其|主体的?|物品的?)?完整|(?:不能|无法)推断[^，。；]{0,12}完整(?:轮廓|形态|形状|结构|比例)"
    return any(isinstance(statement, str) and re.search(pattern, statement, re.I) for statement in statements)


def unit_eligibility(unit: dict) -> tuple[bool, list[str]]:
    reasons = []
    current_selection = unit.get("feature_definition_version") == SELECTED_OBJECT_VERSION
    detail_scope = current_selection and unit.get("display_scope") == "representative_detail"
    if unit.get("usable") is not True:
        reasons.append("observation_marks_not_usable")
    if unit["branch"] == "ID" and not detail_scope and unit.get("whole_object_visible") is not True:
        reasons.append("whole_ID_object_not_visible")
    allowed_roles = {"primary_object"} if unit["branch"] == "ID" else {
        "primary_object_surface", "primary_architectural_surface"}
    if current_selection:
        allowed_roles.add("peer_object" if unit["branch"] == "ID" else "peer_object_surface")
    if unit.get("target_role") not in allowed_roles:
        reasons.append("target_is_not_an_evidenced_design_subject" if current_selection
                       else "target_is_not_an_evidenced_primary_subject")
    primary = unit.get("primary_subject", {})
    if not primary.get("identity") or not primary.get("evidence"):
        reasons.append("primary_subject_evidence_missing")
    if unit["branch"] == "ID" and not detail_scope and primary.get("whole_visible") is not True:
        reasons.append("primary_ID_subject_not_whole")
    # 历史记录以原限制文字核特写；新版用显式范围契约，避免依赖某个中文措辞。
    if (not current_selection and unit["branch"] == "CMF" and primary.get("whole_visible") is not True
            and not has_partial_subject_limitation(unit)):
        reasons.append("partial_CMF_subject_has_no_explicit_crop_limitation")
    quality = unit.get("design_quality", {})
    if quality.get("level") not in {"distinctive", "considered", "ordinary"} or not quality.get("evidence"):
        reasons.append("design_quality_not_evidenced")
    if not unit.get("whole_appearance", {}).get("evidence"):
        reasons.append("whole_appearance_evidence_missing")
    if not emotion_binding_matches(unit):
        reasons.append("design_emotion_original_subject_or_provenance_not_bound")
    if current_selection:
        try:
            validate_display_contract(unit)
        except (ValueError, TypeError, KeyError) as exc:
            reasons.append(f"invalid_current_selection_contract:{exc}")
    else:
        # 历史协议没有同级对象／代表性裁片的观察依据，不能仅凭脚本升级获得新资格。
        if unit.get("display_scope") is not None or unit.get("crop_reason") is not None:
            reasons.append("selection_scope_requires_current_observation_protocol")
        boxes = {"declared": unit.get("bbox"), "evidence": unit.get("evidence_bbox"),
                 "display": unit.get("display_bbox"), "primary_subject": primary.get("bbox")}
        for name, bbox in boxes.items():
            if not valid_bbox(bbox):
                reasons.append(f"invalid_{name}_bbox")
        if all(valid_bbox(bbox) for bbox in boxes.values()):
            if boxes["declared"] != boxes["evidence"]:
                reasons.append("declared_bbox_does_not_match_fact_evidence_bbox")
            if not bbox_contains(boxes["display"], boxes["primary_subject"]):
                reasons.append("display_crops_primary_subject_context")
            if not bbox_contains(boxes["display"], boxes["evidence"]):
                reasons.append("display_excludes_fact_evidence")
            if not bbox_contains(boxes["primary_subject"], boxes["evidence"]):
                reasons.append("fact_evidence_outside_primary_subject")
    self_pair = pair_difference(unit, unit)
    if self_pair.status != "comparable":
        reasons.extend(self_pair.reasons)
    return not reasons, reasons


def conflicting_image_subjects(units: list[dict]) -> dict[str, list[str]]:
    """新版按所选对象绑定；旧版仍核单主体，不能把历史背景悄悄重标为同级物品。"""
    subjects = defaultdict(list)
    selected_units = defaultdict(list)
    for unit in units:
        if unit.get("feature_definition_version") == SELECTED_OBJECT_VERSION:
            selected_units[unit["image_id"]].append(unit)
            continue
        subject = unit.get("primary_subject", {})
        if (unit.get("usable") is True and unit.get("target_role") in {
                "primary_object", "primary_object_surface", "primary_architectural_surface"}
                and isinstance(subject.get("identity"), str) and subject["identity"].strip()
                and valid_bbox(subject.get("bbox"))):
            subjects[unit["image_id"]].append(subject)
    conflicts = {}
    for image_id, rows in subjects.items():
        baseline = rows[0]
        reasons = []
        if any(row["identity"].strip() != baseline["identity"].strip() for row in rows[1:]):
            reasons.append("same_image_primary_subject_identity_conflict")
        if any(any(abs(a - b) > BBOX_TOLERANCE for a, b in zip(row["bbox"], baseline["bbox"], strict=True))
               for row in rows[1:]):
            reasons.append("same_image_primary_subject_bbox_conflict")
        if reasons:
            conflicts[image_id] = reasons
    for image_id, rows in selected_units.items():
        try:
            selected_subject_groups(rows)
        except (ValueError, TypeError, KeyError) as exc:
            conflicts.setdefault(image_id, []).append(f"selected_object_binding_conflict:{exc}")
    return conflicts


def cluster_units(units: list[dict], image_sha_by_id: dict[str, str] | None = None) -> tuple[list[list[dict]], dict, list[dict]]:
    """只合并全部跨簇对均可比较且在冻结阈值内的簇；输入顺序不改变结果。"""
    unit_rows = sorted(units, key=lambda item: item["unit_id"])
    if len({item["unit_id"] for item in unit_rows}) != len(unit_rows):
        raise ValueError("duplicate_unit_id")
    eligible, dispositions = [], []
    subject_conflicts = conflicting_image_subjects(unit_rows)
    for unit in unit_rows:
        validate_features(unit)
        supported, reasons = unit_eligibility(unit)
        if unit["image_id"] in subject_conflicts:
            supported = False
            reasons.extend(subject_conflicts[unit["image_id"]])
        if image_sha_by_id is not None and unit.get("image_sha256") != image_sha_by_id.get(unit["image_id"]):
            supported = False
            reasons.append("design_emotion_unit_SHA_does_not_match_original_image")
        if supported:
            eligible.append(unit)
        else:
            dispositions.append({"unit_id": unit["unit_id"], "image_id": unit["image_id"], "branch": unit["branch"],
                                 "status": "evidence_insufficient", "reasons": reasons})
    final_groups, merge_trace = [], []
    stats = Counter()
    reason_counts = Counter()
    for branch in ("ID", "CMF"):
        items = [u for u in eligible if u["branch"] == branch]
        groups = {i: [u] for i, u in enumerate(items)}
        active = set(groups)
        distances, heap = {}, []
        limit = POLICY["branch"][branch]["distance_limit"]
        for i, left in enumerate(items):
            for j in range(i + 1, len(items)):
                pair = pair_difference(left, items[j])
                stats[f"{branch}:{pair.status}"] += 1
                reason_counts.update(pair.reasons)
                if pair.status == "comparable" and pair.distance is not None and pair.distance <= limit + 1e-12:
                    distances[i, j] = pair.distance
                    heapq.heappush(heap, (pair.distance, i, j))
        next_id = len(items)
        while heap:
            distance, a, b = heapq.heappop(heap)
            if a not in active or b not in active:
                continue
            merged = sorted(groups[a] + groups[b], key=lambda u: u["unit_id"])
            active.remove(a)
            active.remove(b)
            for c in sorted(active):
                da = distances.get(tuple(sorted([a, c])))
                db = distances.get(tuple(sorted([b, c])))
                # 任一跨簇关系缺失即不合并；缺失原因留在 pair statistics 和单元证据中。
                if da is not None and db is not None:
                    d = max(da, db)
                    distances[c, next_id] = d
                    heapq.heappush(heap, (d, c, next_id))
            groups[next_id] = merged
            active.add(next_id)
            merge_trace.append({"branch": branch, "members": [u["unit_id"] for u in merged], "maximum_distance": distance})
            next_id += 1
        final_groups.extend(groups[i] for i in sorted(active))
    final_groups.sort(key=lambda group: (group[0]["branch"], -len(group), [u["unit_id"] for u in group]))
    return final_groups, {"pair_status_counts": dict(stats), "pair_reason_counts": dict(reason_counts), "merges": merge_trace}, dispositions


def cluster_profile(group: list[dict]) -> dict:
    branch = group[0]["branch"]
    blocks = {}
    for block, fields in ENUMS[branch].items():
        blocks[block] = {}
        for field in fields:
            values = Counter(u["features"].get(block, {}).get(field) for u in group)
            unknown = values.pop(None, 0)
            known = sum(values.values())
            ordered = sorted(values.items(), key=lambda row: (-row[1], row[0]))
            blocks[block][field] = {"values": dict(ordered), "known_count": known, "unknown_count": unknown,
                                    "mode": ordered[0][0] if ordered else None,
                                    "mode_support": ordered[0][1] if ordered else 0}
    whole_blocks = {}
    for block, fields in WHOLE_ENUMS.items():
        whole_blocks[block] = {}
        for field in fields:
            values = Counter(u.get("whole_appearance", {}).get(block, {}).get(field) for u in group)
            unknown = values.pop(None, 0)
            ordered = sorted(values.items(), key=lambda row: (-row[1], row[0]))
            whole_blocks[block][field] = {"values": dict(ordered), "known_count": sum(values.values()),
                                          "unknown_count": unknown, "mode": ordered[0][0] if ordered else None,
                                          "mode_support": ordered[0][1] if ordered else 0}
    emotion_axes = {}
    for axis in EMOTION_AXES:
        values = Counter(u["design_emotion"]["axes"][axis] for u in group)
        ordered = sorted(values.items(), key=lambda row: (-row[1], row[0]))
        emotion_axes[axis] = {"values": dict(ordered), "known_count": sum(values.values()),
                              "mode": ordered[0][0], "mode_support": ordered[0][1]}
    averages, context_representativeness = {}, {}
    diameter = 0.0
    worst_pair = []
    for i, left in enumerate(group):
        values = []
        context_sum, context_known = 0.0, 0
        for right in group:
            if left is right:
                continue
            pair = pair_difference(left, right)
            if pair.distance is None:
                raise ValueError("cluster_contains_noncomparable_pair")
            values.append(pair.distance)
            for block in WHOLE_ENUMS:
                context_difference, count = whole_block_difference(
                    block, left.get("whole_appearance", {}), right.get("whole_appearance", {}))
                if context_difference is not None:
                    context_sum += context_difference * count
                    context_known += count
            if pair.distance > diameter:
                diameter = pair.distance
                worst_pair = [left["unit_id"], right["unit_id"]]
        averages[left["unit_id"]] = sum(values) / len(values) if values else 0.0
        possible = max(0, len(group) - 1) * sum(map(len, WHOLE_ENUMS.values()))
        context_representativeness[left["unit_id"]] = {
            "known_comparison_count": context_known, "possible_comparison_count": possible,
            "coverage": context_known / possible if possible else 0.0,
            "mean_known_difference": context_sum / context_known if context_known else None}
    medoid = min(averages, key=lambda key: (averages[key], key))
    review_items = []
    if branch == "CMF":
        appearances = blocks["material"]["appearance"]["values"]
        if len(appearances) > 1:
            review_items.append({"kind": "material_appearance_transition", "observed_categories": appearances,
                                 "required_review": "结合形态、比例、配色、材料质感与细节核对跨材质是否协调；材料不同本身不作否定。",
                                 "reason": "情绪四轴近似只生成候选，真实不同材质的组合关系仍须看原图与整板。"})
    for block, fields in blocks.items():
        for field, item in fields.items():
            if any(value in item["values"] for value in POLICY["nondiscriminating_values"]):
                review_items.append({"kind": "nondiscriminating_observation", "field": f"{block}.{field}",
                                     "required_review": "mixed/other 已保留但不作为相似证据；核对实际混合内容是否形成第二强信号。"})
    return {"blocks": blocks, "whole_appearance": whole_blocks,
            "design_emotion": {"axes": emotion_axes, "schema_version": DESIGN_EMOTION_VERSION,
                               "inference_kind": "subjective_visible_grounded_interpretation"},
            "design_quality_counts": dict(Counter(u.get("design_quality", {}).get("level", "unresolved") for u in group)),
            "medoid_unit_id": medoid, "maximum_pair_distance": diameter,
            "most_different_pair": worst_pair, "average_member_distance": averages,
            "within_cluster_context_representativeness": context_representativeness,
            "concrete_relation_representativeness": concrete_member_profile(group),
            "requires_concrete_relation_review": True,
            "critical_review_items": review_items,
            "basis": "subjective_design_emotion_supported_by_visible_multidimensional_combination",
            "visual_review_performed": False}


def article_keys(image: dict) -> set[str]:
    keys = set()
    for source in image.get("sources", []):
        if isinstance(source, dict) and source.get("article_id"):
            keys.add(str(source["article_id"]))
    if image.get("article_id"):
        keys.add(str(image["article_id"]))
    return keys


def source_group_keys(image: dict) -> set[str]:
    """已有同源组用于去重，仍不据此声称已经核实真实项目身份。"""
    return {str(source[key]) for source in image.get("sources", []) if isinstance(source, dict)
            for key in ("source_group_id", "claim_origin_id") if source.get(key)}


def project_identity(image: dict, supplement: dict | None = None) -> dict:
    """文章身份不等于项目身份；没有明确证据的字符串不得计为核实项目。"""
    source = supplement if supplement is not None else (image.get("project_identity") or image)
    key = source.get("project_key") or source.get("key")
    state = source.get("project_state") or source.get("state") or "unknown"
    evidence = source.get("evidence") or source.get("source_refs") or []
    supported = state in {"source_supported", "verified"} and bool(key) and bool(evidence)
    return {"project_key": key, "project_state": state if supported else "unknown", "evidence": evidence,
            "supported": supported}


def unit_project_identity(unit: dict, image: dict, identities: dict) -> dict:
    """局部对象的身份结论优先；不能借同图另一表面的产品系列证明当前表面。"""
    if unit["unit_id"] in identities:
        supplement = identities[unit["unit_id"]]
        result = project_identity(image, supplement)
        reasons = []
        if supplement.get("unit_id") != unit["unit_id"]:
            reasons.append("unit_id_missing_or_mismatch")
        if supplement.get("image_id") != image["image_id"]:
            reasons.append("image_id_missing_or_mismatch")
        if not supplement.get("sha256") or supplement["sha256"] != image.get("sha256"):
            reasons.append("original_SHA_missing_or_mismatch")
        has_scope = isinstance(supplement.get("scope"), str) and bool(supplement["scope"].strip())
        has_roi = supplement.get("roi") is not None
        if not has_scope and not has_roi:
            reasons.append("scope_and_ROI_binding_missing")
        # 同时提供文字范围与矩形时，两者都须匹配；不能用旧通用文字放行已经换目标的裁片。
        if has_scope and supplement["scope"] != unit.get("scope"):
            reasons.append("target_scope_mismatch")
        if has_roi and supplement["roi"] != unit.get("bbox"):
            reasons.append("target_ROI_mismatch")
        validation = {"status": "unverified" if reasons else "matched", "reasons": reasons,
                      "claimed_project_key": result["project_key"]}
        if reasons:
            # 未获支持的旧键不能参与选板排重；原主张及依据仍留在诊断和 evidence 中。
            result = {**result, "project_key": None, "project_state": "unknown", "supported": False}
        return {**result, "binding_scope": "unit", "binding_id": unit["unit_id"],
                "binding_validation": validation}
    supplement = identities.get(unit["image_id"]) or image.get("project_identity") or image
    result = project_identity(image, supplement)
    if supplement.get("identity_scope") != "whole_image_project":
        return {**result, "project_state": "unknown", "supported": False,
                "binding_scope": "image_scope_unconfirmed", "binding_id": unit["image_id"]}
    return {**result, "binding_scope": "whole_image_project", "binding_id": unit["image_id"]}


def runway_state(image: dict) -> str:
    runway = image.get("runway", {})
    value = runway.get("classification") if isinstance(runway, dict) else runway
    return value if value in {"yes", "no"} else "unknown"


def mechanical_checks(members: list[dict], minimum: int = 6, maximum: int = 10) -> dict:
    number = len(members)
    runway = Counter(m["runway_state"] for m in members)
    projects = [m["project_key"] for m in members if m["project_state"] in {"source_supported", "verified"}]
    articles = [key for member in members for key in member.get("source_article_keys", [])]
    groups = [key for member in members for key in member.get("source_group_keys", [])]
    return {"quantity": number, "quantity_pass": minimum <= number <= maximum,
            "runway_known_count": runway["yes"], "runway_unknown_count": runway["unknown"],
            "runway_maximum": number * 30 // 100,
            "runway_known_ratio": runway["yes"] / number if number else None,
            "runway_upper_bound_ratio": (runway["yes"] + runway["unknown"]) / number if number else None,
            "runway_conservative_pass": runway["yes"] + runway["unknown"] <= number * 30 // 100,
            "source_articles_unique": len(articles) == len(set(articles)),
            "known_source_groups_unique": len(groups) == len(set(groups)),
            "source_article_identity_complete": all(m.get("source_article_keys") for m in members),
            "known_projects_unique": len(projects) == len(set(projects)),
            "independent_project_count": len(set(projects)),
            "project_identity_complete": len(projects) == number,
            "unique_original_count": len({m["sha256"] for m in members}),
            "visual_review_performed": False}


def matching_view_failures(unit: dict, image: dict, view_reviews: list[dict]) -> list[dict]:
    """已知失败只绑定这一原图、单元与视窗；不从 keep=false 推出永久不可用。"""
    return [row for row in view_reviews if row.get("unit_id") == unit["unit_id"]
            and row.get("sha256") == image["sha256"]
            and row.get("roi") == unit.get("display_bbox", unit.get("bbox", [0, 0, 1, 1]))
            and row.get("status") == "unresolved" and row.get("review_ref") and row.get("reason")]


def member_record(unit: dict, image: dict, profile: dict, identities: dict, view_reviews: list[dict] | None = None) -> dict:
    project = unit_project_identity(unit, image, identities)
    prior_failures = matching_view_failures(unit, image, view_reviews or [])
    return {"unit_id": unit["unit_id"], "image_id": unit["image_id"], "sha256": image.get("sha256"),
            "branch": unit["branch"], "whole_object_visible": unit.get("whole_object_visible"),
            "local_path": image.get("local_path"), "roi": unit.get("display_bbox", unit.get("bbox", [0, 0, 1, 1])),
            "display_bbox": unit.get("display_bbox"), "evidence_bbox": unit.get("evidence_bbox", unit.get("bbox")),
            "target_role": unit.get("target_role"), "primary_subject": unit.get("primary_subject"),
            "display_scope": unit.get("display_scope"), "crop_reason": unit.get("crop_reason"),
            "subject_visibility_limitations": unit.get("subject_visibility_limitations"),
            "design_quality": unit.get("design_quality"), "whole_appearance": unit.get("whole_appearance"),
            "design_emotion": unit.get("design_emotion"),
            "design_emotion_provenance": unit.get("design_emotion_provenance"),
            "feature_definition_version": unit.get("feature_definition_version"),
            "scope": unit.get("scope"), "reason": unit.get("evidence", ""),
            "limitations": unit.get("limitations", []),
            "design_emotion_average_distance": profile["average_member_distance"][unit["unit_id"]],
            "context_representativeness": profile.get("within_cluster_context_representativeness", {}).get(
                unit["unit_id"], {"coverage": 0.0, "mean_known_difference": None}),
            "concrete_representativeness": profile.get("concrete_relation_representativeness", {}).get(
                unit["unit_id"], {"coverage": 0.0, "equal_block_mean_difference": None}),
            "requires_concrete_relation_review": True,
            "features": unit["features"], "field_states": unit.get("field_states", {}), "coverage": unit.get("coverage", {}),
            "project_key": project["project_key"], "project_state": project["project_state"],
            "project_identity_scope": project["binding_scope"], "project_identity_binding": project["binding_id"],
            "project_identity_validation": project.get("binding_validation"),
            "project_evidence": project["evidence"], "runway_state": runway_state(image),
            "runway_evidence": image.get("runway", {}), "source_refs": image.get("sources", []),
            "source_article_keys": sorted(article_keys(image)), "observation_ref": unit.get("observation_ref"),
            "observation_pointer": unit.get("observation_pointer"),
            "source_group_keys": sorted(source_group_keys(image)),
            "reused_fact_ids": unit.get("reused_fact_ids", []), "reused_fact_refs": unit.get("reused_fact_refs", []),
            "prior_view_failures": prior_failures,
            "view_review_status": "needs_current_view_review" if prior_failures else "not_performed",
            "target_quality_status": "requires_current_target_review"}


def choose_board(group: list[dict], images: dict, profile: dict, identities: dict,
                 minimum: int = 6, preferred: int = 8, maximum: int = 10,
                 view_reviews: list[dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    """先按具体可见关系代表性，再按设计感择优；所有结果仍待实际独立板审。"""
    candidates = [member_record(u, images[u["image_id"]], profile, identities, view_reviews) for u in group]
    # 改变展示尺寸不自动解决旧失败。优先其他同簇图，必要时仍保留待复核候选。
    candidates.sort(key=lambda m: (bool(m["prior_view_failures"]),
                                   -m["concrete_representativeness"]["coverage"],
                                   (m["concrete_representativeness"]["equal_block_mean_difference"]
                                    if m["concrete_representativeness"]["equal_block_mean_difference"] is not None else 1.0),
                                   m["design_emotion_average_distance"],
                                   QUALITY_ORDER.get((m.get("design_quality") or {}).get("level"), 3),
                                   m["unit_id"]))

    def select(size: int, enforce_runway: bool) -> list[dict]:
        selected, used_sha, used_articles, used_groups, used_projects = [], set(), set(), set(), set()
        risky = 0
        for member in candidates:
            articles = set(member["source_article_keys"])
            groups = set(member["source_group_keys"])
            project = member["project_key"]
            if member["sha256"] in used_sha or articles & used_articles or groups & used_groups or (project and project in used_projects):
                continue
            is_risky = member["runway_state"] != "no"
            if enforce_runway and is_risky and risky + 1 > size * 30 // 100:
                continue
            selected.append(member)
            used_sha.add(member["sha256"])
            used_articles.update(articles)
            used_groups.update(groups)
            if project:
                used_projects.add(project)
            risky += is_risky
            if len(selected) == size:
                break
        return selected

    # 默认八张，供给不足可用七／六张；九／十张需实际审阅后另作有理由的版本。
    for size in range(min(preferred, maximum), minimum - 1, -1):
        chosen = select(size, True)
        if len(chosen) == size:
            checks = mechanical_checks(chosen, minimum, maximum)
            selected_ids = {m["unit_id"] for m in chosen}
            return chosen, [m for m in candidates if m["unit_id"] not in selected_ids], checks
    # unknown 来源可能暂时无法证明配额；仍交付草案供核验，不伪称配额已通过。
    draft = select(min(preferred, maximum), False)
    selected_ids = {m["unit_id"] for m in draft}
    return draft, [m for m in candidates if m["unit_id"] not in selected_ids], mechanical_checks(draft, minimum, maximum)


def post_cluster_title(branch: str, profile: dict) -> str:
    """名称只读取既成簇的情绪共同解释，不用某种材料名掩盖组合关系。"""
    terms = {
        "welcoming": "亲和", "reserved": "疏离克制", "relaxed": "松弛", "precise": "精确秩序",
        "calm": "安静", "lively": "活跃", "light": "轻盈", "grounded": "稳重",
    }
    result = []
    for axis in EMOTION_AXES:
        item = profile["design_emotion"]["axes"][axis]
        if item["mode"] in terms and item["mode_support"] >= item["known_count"] * 0.60:
            result.append(terms[item["mode"]])
    return " · ".join(result) if result else f"{branch} 协调设计情绪候选"


def emotion_record_status(value: Any) -> str:
    """统计原记录状态，不把 supported 声明等同于出处有效或已通过整板审阅。"""
    if value is None:
        return "missing"
    try:
        validate_emotion(value)
    except ValueError:
        return "unresolved"
    return value["status"]


def emotion_progress(images: list[dict], units: list[dict], groups: list[list[dict]]) -> tuple[dict, dict[str, str]]:
    """技术观察、无可用主体、情绪观察及候选资格分开计数，失败／待处理不能冒充无主体。"""
    names = ("supported", "limited", "unresolved", "missing", "no_usable_subject")
    unit_counts, image_counts = Counter(dict.fromkeys(names, 0)), Counter(dict.fromkeys(names, 0))
    by_image = defaultdict(list)
    selected_scope_images = {unit["image_id"] for unit in units
                             if unit.get("feature_definition_version") == SELECTED_OBJECT_VERSION}
    for unit in units:
        role = unit.get("target_role")
        if unit.get("usable") is False or role in {"secondary_object", "background", "incidental_detail", "unknown"}:
            state = "no_usable_subject"
        else:
            state = emotion_record_status(unit.get("design_emotion"))
        unit_counts[state] += 1
        by_image[unit["image_id"]].append(state)
    image_states = {}
    for image in images:
        active_states = set(by_image[image["image_id"]]) - {"no_usable_subject"}
        if not active_states and image.get("status") == "observed":
            state = "no_usable_subject"
        elif image.get("design_emotion") is not None and image["image_id"] not in selected_scope_images:
            state = emotion_record_status(image["design_emotion"])
        elif len(active_states) == 1:
            # 兼容显式 units 顶层输入；只汇总已有同图声明，不为原图创建任何新情绪值。
            state = next(iter(active_states))
        elif active_states:
            state = "unresolved"
        else:
            state = "missing"
        image_counts[state] += 1
        image_states[image["image_id"]] = state
    return ({"emotion_image_status_counts": dict(image_counts), "emotion_unit_status_counts": dict(unit_counts),
             "eligible_units": sum(map(len, groups)), "missing_emotion_units": unit_counts["missing"],
             "missing_emotion_images": image_counts["missing"],
             "emotion_counts_meaning": "declared_observation_state;eligible_units_adds_subject_provenance_and_policy_checks;none_implies_visual_or_designer_approval"},
            image_states)


def extraction_state(images: list[dict], *, allow_partial: bool = False) -> dict:
    """提取阶段先收口；失败是终态，未处理／在途不能伪装成已完成的图片池。"""
    counts = Counter(image.get("status", "unknown") for image in images)
    outstanding = [{"image_id": image["image_id"], "status": image.get("status", "unknown")}
                   for image in images if image.get("status") not in {"observed", "failed"}]
    if outstanding and not allow_partial:
        states = ",".join(sorted({row["status"] for row in outstanding}))
        raise ValueError(f"DNA_extraction_not_terminal:{len(outstanding)}:{states};use_allow_partial_only_for_explicit_pilot")
    return {"image_status_counts": dict(counts), "all_sample_images_terminal": not outstanding,
            "all_sample_images_observed": counts.get("observed", 0) == len(images),
            "allow_partial": allow_partial, "outstanding_images": outstanding,
            "phase": "partial_pilot" if outstanding else "frozen_extraction_then_offline_clustering",
            "new_DNA_model_calls": 0}


def pending_evidence(units: list[dict], dispositions: list[dict]) -> list[dict]:
    """缺项只输出定点待补清单，不能在聚类中调用模型；不适用不误报为缺失。"""
    rejected = {row["unit_id"]: row.get("reasons", []) for row in dispositions if row["status"] == "evidence_insufficient"}
    rows = []
    for unit in units:
        unresolved = [f"{block}.{field}" for block, fields in CONCRETE_FIELDS[unit["branch"]].items()
                      for field in fields if concrete_field_state(unit, block, field) == "unresolved"]
        if unresolved or unit["unit_id"] in rejected:
            rows.append({"unit_id": unit["unit_id"], "image_id": unit["image_id"],
                         "unresolved_concrete_fields": unresolved, "eligibility_issues": rejected.get(unit["unit_id"], []),
                         "action": "return_to_DNA_preparation_if_needed;no_model_call_in_clustering",
                         "note": "未观察或混合值需要明确实际内容；不推断字段缺项原因，也不默认所有缺项必须重提。"})
    return rows


def build_outputs(observations: dict, identities: dict | None = None, *, minimum: int = 6,
                  preferred: int = 8, maximum: int = 10, view_reviews: list[dict] | None = None,
                  allow_partial: bool = False) -> tuple[dict, dict]:
    if not 6 <= minimum <= preferred <= maximum <= 10:
        raise ValueError("board_count_must_be_within_authorized_6_to_10")
    identities = identities or {}
    view_reviews = view_reviews or []
    image_list = observations.get("images", [])
    stage = extraction_state(image_list, allow_partial=allow_partial)
    images = {row["image_id"]: row for row in image_list}
    if len(images) != len(image_list):
        raise ValueError("duplicate_image_id")
    units = observations.get("units")
    if units is None:
        units = [u for image in image_list for u in image.get("units", [])]
    for unit in units:
        if unit["image_id"] not in images:
            raise ValueError(f"unit_image_missing:{unit['unit_id']}")
        image = images[unit["image_id"]]
        if not image.get("sha256") or not image.get("local_path"):
            raise ValueError(f"original_identity_missing:{unit['unit_id']}")
    # 显式 pilot 也只能消费已完成观察；在途或失败行即使残留旧单元也不加入候选。
    observed_units = [unit for unit in units if images[unit["image_id"]].get("status") == "observed"]
    groups, trace, dispositions = cluster_units(observed_units, {key: image.get("sha256") for key, image in images.items()})
    dispositions.extend({"unit_id": unit["unit_id"], "image_id": unit["image_id"], "branch": unit["branch"],
                         "status": "evidence_insufficient", "reasons": ["source_image_observation_not_observed"]}
                        for unit in units if images[unit["image_id"]].get("status") != "observed")
    clusters, boards = [], []
    for group in groups:
        branch = group[0]["branch"]
        ids = [u["unit_id"] for u in group]
        cluster_id = f"{branch}-{digest(ids)[:12]}"
        profile = cluster_profile(group)
        chosen, alternates, checks = choose_board(group, images, profile, identities, minimum, preferred, maximum, view_reviews)
        supported_projects = {unit_project_identity(u, images[u["image_id"]], identities)["project_key"] for u in group
                              if unit_project_identity(u, images[u["image_id"]], identities)["supported"]}
        source_article_ids = set().union(*(article_keys(images[u["image_id"]]) for u in group))
        status = "candidate_cluster" if checks["quantity_pass"] else ("singleton" if len(group) == 1 else "small_cluster")
        title = post_cluster_title(branch, profile)
        clusters.append({"cluster_id": cluster_id, "branch": branch, "title": title, "status": status,
                         "requires_concrete_relation_review": True,
                         "unit_ids": ids, "unit_count": len(ids), "unique_original_count": len({images[u['image_id']]['sha256'] for u in group}),
                         "independent_project_count": len(supported_projects), "source_article_count": len(source_article_ids),
                         "project_identity_complete": all(unit_project_identity(u, images[u["image_id"]], identities)["supported"] for u in group),
                         "profile": profile, "board_candidate_count": len(chosen), "source_and_quantity_checks": checks})
        for unit in group:
            dispositions.append({"unit_id": unit["unit_id"], "image_id": unit["image_id"], "branch": branch,
                                 "status": status, "cluster_id": cluster_id})
        if checks["quantity_pass"]:
            board_status = "candidate_for_review"
            if not checks["runway_conservative_pass"]:
                board_status = "draft_runway_conflict" if checks["runway_known_count"] > checks["runway_maximum"] else "draft_runway_pending"
            elif not checks["project_identity_complete"] or not checks["source_article_identity_complete"]:
                board_status = "draft_source_pending"
            boards.append({"board_id": f"BOARD-{cluster_id}", "cluster_id": cluster_id, "branch": branch,
                           "requires_concrete_relation_review": True,
                           "concrete_relation_status": "requires_concrete_relation_review",
                           "concrete_pair_diagnostics": [concrete_pair_evidence(left, right)
                                                         for i, left in enumerate(chosen) for right in chosen[i + 1:]],
                           "title": title, "profile": profile, "members": chosen, "alternates": alternates,
                           "status": board_status, "mechanical_checks": checks,
                           "view_review_status": "needs_current_view_review" if any(m["prior_view_failures"] for m in chosen) else "not_performed",
                           "prior_view_failure_count": sum(bool(m["prior_view_failures"]) for m in chosen),
                           "visual_review_status": "not_performed", "designer_approved": False})
    processed_images = {u["image_id"] for u in units}
    image_statuses = Counter(image.get("status", "unknown") for image in image_list)
    emotion_summary, emotion_image_states = emotion_progress(image_list, units, groups)
    image_dispositions = [{"image_id": image["image_id"], "sha256": image.get("sha256"),
                           "observation_status": image.get("status", "unknown"),
                           "design_emotion_status": emotion_image_states[image["image_id"]],
                           "unit_count": sum(u["image_id"] == image["image_id"] for u in units),
                           "status": "units_recorded" if image["image_id"] in processed_images else "no_comparable_unit"}
                          for image in image_list]
    policy = json.loads(json.dumps(POLICY))
    policy["board"].update({"minimum": minimum, "preferred": preferred, "maximum": maximum})
    metadata = {"schema_version": VERSION, "policy": policy, "policy_digest": digest(policy),
                "observation_digest": digest(observations), "source_identity_digest": digest(identities),
                "view_reviews_digest": digest(view_reviews),
                "design_emotion_summary": emotion_summary, "extraction_state": stage,
                "pending_evidence": pending_evidence(units, dispositions),
                "generated_at": datetime.now(timezone.utc).isoformat(), "new_model_calls": 0,
                "new_visual_review_performed": False}
    return ({**metadata, "clusters": clusters, "unit_dispositions": sorted(dispositions, key=lambda item: item["unit_id"]),
             "image_dispositions": image_dispositions, "trace": trace,
             "summary": {"image_count": len(image_list), "unit_count": len(units), "cluster_count": len(clusters),
                         **emotion_summary,
                         "candidate_board_count": len(boards), "disposition_count": len(dispositions),
                         "image_status_counts": dict(image_statuses),
                         "all_sample_images_terminal": stage["all_sample_images_terminal"],
                         "all_sample_images_observed": image_statuses.get("observed", 0) == len(image_list)}},
            {**metadata, "boards": boards, "candidate_count": len(boards),
             "image_status_counts": dict(image_statuses),
             "all_sample_images_terminal": stage["all_sample_images_terminal"],
             "all_sample_images_observed": image_statuses.get("observed", 0) == len(image_list)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--observations", type=Path, help="兼容已有观察；默认要求冻结清单全部图片结束")
    inputs.add_argument("--prepared", type=Path, help="独立 DNA 提取 Skill 导出的不可变 prepared-manifest.json")
    parser.add_argument("--source-identities", type=Path)
    parser.add_argument("--view-reviews", type=Path, help="有原review引用的当前视窗失败，降低选板优先级但不改DNA簇")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--minimum", type=int, default=6)
    parser.add_argument("--preferred", type=int, default=8)
    parser.add_argument("--maximum", type=int, default=10)
    parser.add_argument("--run-label", default="candidate_clustering", help="例如 pilot100_intermediate，标明中途快照用途")
    parser.add_argument("--allow-partial", action="store_true", help="仅显式试跑允许未结束的提取快照；默认要求所有图片 observed/failed")
    args = parser.parse_args()
    prepared, sample = None, None
    if args.prepared:
        observations, sample, prepared = read_prepared(args.prepared)
        observation_path = Path(prepared["observations_ref"]["path"])
    else:
        observation_path = args.observations
        observations = read_json(observation_path)
        if observations.get("sample_ref"):
            sample = read_bound_reference(observations["sample_ref"])
            validate_sample_scope(observations, sample)
    extraction_state(observations["images"], allow_partial=args.allow_partial)
    for filename in ("clusters.json", "boards.json"):
        if (args.out_dir / filename).exists():
            raise FileExistsError(f"fresh_output_directory_required:{args.out_dir / filename}")
    observations, observation_ref = freeze_input(observation_path, args.out_dir / "inputs" / "observations.json")
    if prepared and observation_ref["sha256"] != prepared["observations_ref"]["sha256"]:
        raise ValueError("prepared_observations_changed_while_freezing")
    if sample is not None:
        validate_sample_scope(observations, sample)
    identities = {}
    view_reviews = []
    algorithm_path = args.out_dir / "inputs" / "cluster_sample.py"
    with algorithm_path.open("xb") as handle:
        handle.write(Path(__file__).read_bytes())
    refs = {"observations": observation_ref, "algorithm": file_ref(algorithm_path)}
    if prepared:
        _, refs["prepared_manifest"] = freeze_input(args.prepared, args.out_dir / "inputs" / "prepared-manifest.json")
        _, refs["sample"] = freeze_input(Path(prepared["sample_ref"]["path"]), args.out_dir / "inputs" / "sample.json")
    elif sample is not None:
        _, refs["sample"] = freeze_input(Path(observations["sample_ref"]["path"]), args.out_dir / "inputs" / "sample.json")
    # 共享的轻量情绪契约也是算法依赖，必须与脚本一起冻结，避免以后重放依赖活动源码。
    emotion_contract_path = args.out_dir / "inputs" / "design_emotion.py"
    with emotion_contract_path.open("xb") as handle:
        handle.write(Path(__file__).with_name("design_emotion.py").read_bytes())
    refs["design_emotion_contract"] = file_ref(emotion_contract_path)
    if args.source_identities:
        source_rows, source_ref = freeze_input(args.source_identities, args.out_dir / "inputs" / "source-identities.json")
        if isinstance(source_rows, dict) and ("images" in source_rows or "units" in source_rows):
            rows = source_rows.get("images", []) + source_rows.get("units", [])
        else:
            rows = source_rows
        identities = {row.get("unit_id") or row["image_id"]: row for row in rows} if isinstance(rows, list) else rows
        refs["source_identities"] = source_ref
    if args.view_reviews:
        review_data, review_ref = freeze_input(args.view_reviews, args.out_dir / "inputs" / "view-reviews.json")
        view_reviews = review_data.get("failures", []) if isinstance(review_data, dict) else review_data
        for row in view_reviews:
            ref = row["review_ref"]
            if file_ref(Path(ref["path"]))["sha256"] != ref["sha256"]:
                raise ValueError("prior_view_review_ref_changed")
        refs["view_reviews"] = review_ref
    clusters, boards = build_outputs(observations, identities, minimum=args.minimum, preferred=args.preferred,
                                    maximum=args.maximum, view_reviews=view_reviews, allow_partial=args.allow_partial)
    clusters["input_refs"] = boards["input_refs"] = refs
    clusters["input_scope"] = boards["input_scope"] = "frozen_sample_manifest" if sample is not None else "explicit_observations_manifest_only"
    clusters["run_label"] = boards["run_label"] = args.run_label
    write_new(args.out_dir / "clusters.json", clusters)
    write_new(args.out_dir / "boards.json", boards)
    print(json.dumps(clusters["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
