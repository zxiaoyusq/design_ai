#!/usr/bin/env python3
"""将精简模型观察结果编译为完整 DNA 结果，并整理可确定计算的字段。"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
FIELD_REGISTRY_PATH = ROOT / "references" / "field-registry.json"
STYLE_REGISTRY_PATH = ROOT / "references" / "style-registry.json"
TAG_RELATIONS_PATH = ROOT / "references" / "tag-relations.json"
KNOWLEDGE_BASE_PATH = ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"
VALUE_NORMALIZATION_PATH = ROOT / "references" / "value-normalization.json"
MODEL_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "design-dna-model-output.schema.json"
FINAL_SCHEMA_VERSION = "design_dna_multitag_extraction_v1.1"
OBSERVATION_SCHEMA_VERSION = "design_dna_multitag_observation_v1"
KNOWLEDGE_BASE_VERSION = "4.1"
FIELD_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]{2,3}")
MODULE_HEADING_PATTERN = re.compile(r"^### (DNA-M(?:0[1-9]|1[0-5]))｜(.+)$", re.M)
VALUE_SPACE_ROW_PATTERN = re.compile(
    r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| (.*?) \| .*? \| .*? \| .*? \|$",
    re.M,
)
FORBIDDEN_SINGLE_IMAGE_PROFILES = {
    "profile:multi_face_device",
    "profile:reference_analysis",
    "profile:trend_analysis",
}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"注册表根节点必须是对象：{path}")
    return data


def _ordered_unique(values: Sequence[Any]) -> list[Any]:
    """在不改变首次出现顺序的前提下去重 JSON 标量。"""

    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _record_change(report: dict[str, Any], path: str) -> None:
    changes = report.setdefault("changed_paths", [])
    if path not in changes:
        changes.append(path)


def _normalize_observation_contract(
    observation: dict[str, Any], report: dict[str, Any]
) -> None:
    """在严格模型 Schema 前修复不需要视觉判断的置信度归类矛盾。"""

    uncertainties = observation.get("uncertainties")
    design_observations = observation.get("design_observations")
    if not isinstance(uncertainties, list) or not isinstance(design_observations, list):
        return
    existing_keys = {
        (item.get("field_id"), item.get("region"))
        for item in design_observations
        if isinstance(item, dict)
    }
    retained: list[Any] = []
    normalizations = report.setdefault("observation_contract_normalizations", [])
    for index, item in enumerate(uncertainties):
        if not isinstance(item, dict):
            retained.append(item)
            continue
        confidence = item.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence >= 0.75
            and item.get("best_estimate") is not None
            and item.get("observability") == "observed"
        ):
            key = (item.get("field_id"), item.get("region"))
            if key not in existing_keys:
                design_observations.append(
                    {
                        "field_id": item.get("field_id"),
                        "value": copy.deepcopy(item.get("best_estimate")),
                        "raw_visual_description": item.get("reason", ""),
                        "region": item.get("region"),
                        "observability": "observed",
                        "confidence": confidence,
                        "evidence_refs": copy.deepcopy(item.get("evidence_refs", [])),
                    }
                )
                existing_keys.add(key)
                _record_change(report, "/design_observations/-")
            _record_change(report, f"/uncertainties/{index}")
            normalizations.append(
                {
                    "source_pointer": f"/uncertainties/{index}",
                    "field_id": item.get("field_id"),
                    "action": "promoted_to_design_observation",
                    "reason": "confidence >= 0.75 且存在已观察的最佳估计",
                }
            )
            continue
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence > 0.749999
        ):
            item["confidence"] = 0.749999
            _record_change(report, f"/uncertainties/{index}/confidence")
            normalizations.append(
                {
                    "source_pointer": f"/uncertainties/{index}",
                    "field_id": item.get("field_id"),
                    "action": "clamped_uncertainty_confidence",
                    "reason": "不确定项没有可提升为已确认观察的最佳估计",
                }
            )
        retained.append(item)
    observation["uncertainties"] = retained


def _replace_if_changed(
    target: dict[str, Any],
    key: str,
    value: Any,
    path: str,
    report: dict[str, Any],
) -> None:
    if target.get(key) != value:
        target[key] = value
        _record_change(report, f"{path}/{key}")


def _module_names(knowledge_base: str) -> dict[str, str]:
    return {
        module_id: name.strip()
        for module_id, name in MODULE_HEADING_PATTERN.findall(knowledge_base)
    }


def _value_spaces(knowledge_base: str) -> dict[str, tuple[str, set[str]]]:
    """从知识库字段表提取 enum 与受控列表值域。"""

    section = knowledge_base.split("## 四、规范字段定义", 1)[-1].split(
        "## 五、别名、合并与派生", 1
    )[0]
    spaces: dict[str, tuple[str, set[str]]] = {}
    for field_id, description in VALUE_SPACE_ROW_PATTERN.findall(section):
        type_match = re.search(
            r"；(enum|list|multi_label)(?:\s*/\s*(.*))?$", description
        )
        if not type_match:
            continue
        before_type = description[: type_match.start()]
        slash_values = (type_match.group(2) or "").strip()
        if "：" in before_type:
            raw_values = before_type.split("：", 1)[1]
        elif "、" in slash_values:
            raw_values = slash_values
        else:
            continue
        values = {
            value.strip()
            for value in re.split(r"[、,，]", raw_values)
            if value.strip()
        }
        if values:
            spaces[field_id] = (type_match.group(1), values)
    return spaces


def _view_requirement_satisfied(required_views: list[str], target_view: str) -> bool:
    if "any" in required_views:
        return True
    normalized_view = "side" if target_view in {"left", "right"} else target_view
    return normalized_view in required_views


def _nearest_bucket(value: int | float, buckets: list[int]) -> int:
    """按距离就近离散化；等距时向更高档位归一。"""

    return min(buckets, key=lambda bucket: (abs(float(value) - bucket), -bucket))


def _normalized_controlled_value(
    field_id: str,
    record: dict[str, Any],
    value: Any,
    spaces: dict[str, tuple[str, set[str]]],
    normalization: dict[str, Any],
) -> tuple[Any, list[str]]:
    """只执行有机器规则支持的无歧义值归一，返回调整说明。"""

    notes: list[str] = []
    aliases = normalization.get("field_value_aliases", {}).get(field_id, {})
    controlled = spaces.get(field_id)
    if controlled:
        controlled_type, allowed = controlled
        if controlled_type == "enum" and isinstance(value, str):
            normalized = aliases.get(value, value)
            if normalized != value:
                notes.append(f"值别名 {value!r} → {normalized!r}")
            if normalized not in allowed:
                return None, [*notes, f"值 {normalized!r} 不在受控值域"]
            value = normalized
        elif controlled_type in {"list", "multi_label"} and isinstance(value, list):
            normalized_items: list[Any] = []
            invalid_items: list[str] = []
            relation_field = field_id in set(
                normalization.get("relation_token_fields", [])
            )
            for item in value:
                if not isinstance(item, str):
                    normalized_items.append(item)
                    continue
                normalized = aliases.get(item, item)
                if normalized not in allowed and relation_field:
                    matched = [token for token in allowed if token in normalized]
                    if len(matched) == 1:
                        normalized = matched[0]
                if normalized in allowed:
                    normalized_items.append(normalized)
                    if normalized != item:
                        notes.append(f"受控词 {item!r} → {normalized!r}")
                else:
                    invalid_items.append(item)
            if invalid_items and not normalized_items:
                return None, [*notes, f"无法归一受控值 {invalid_items!r}"]
            if invalid_items:
                notes.append(f"移除无法归一的受控值 {invalid_items!r}")
            value = _ordered_unique(normalized_items)

    unit = record.get("unit")
    buckets = [
        int(item)
        for item in normalization.get("ordinal_buckets", [0, 25, 50, 75, 100])
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    if (
        unit == "ordinal_0_25_50_75_100"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and buckets
    ):
        normalized_number = _nearest_bucket(value, buckets)
        if normalized_number != value:
            notes.append(f"序数 {value!r} → {normalized_number!r}")
        value = normalized_number
    if unit == "label+ordinal_strength" and isinstance(value, list) and buckets:
        for item in value:
            if not isinstance(item, dict):
                continue
            strength = item.get("strength")
            if isinstance(strength, (int, float)) and not isinstance(strength, bool):
                normalized_strength = _nearest_bucket(strength, buckets)
                if normalized_strength != strength:
                    notes.append(
                        f"强度 {strength!r} → {normalized_strength!r}"
                    )
                    item["strength"] = normalized_strength
    return value, notes


def _active_style_records(style_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["style_id"]): item
        for item in style_registry.get("styles", [])
        if isinstance(item, dict)
        and isinstance(item.get("style_id"), str)
        and item.get("status") == "active"
    }


def _field_records(field_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["field_id"]): item
        for item in field_registry.get("fields", [])
        if isinstance(item, dict) and isinstance(item.get("field_id"), str)
    }


def _style_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "label_en": record.get("display_name_en"),
        "label_zh": record.get("display_name_zh"),
        "aliases": list(record.get("aliases") or []),
        "tag_kind": record.get("tag_kind"),
        "facet_ids": list(record.get("facet_ids") or []),
    }


def _pair_relation_map(tag_relations: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in tag_relations.get("pair_relations", []):
        if not isinstance(item, dict):
            continue
        style_ids = item.get("style_ids")
        if isinstance(style_ids, list) and len(style_ids) == 2:
            pairs[tuple(sorted(str(style_id) for style_id in style_ids))] = item
    return pairs


def _expand_observation(
    observation: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    module_names: dict[str, str],
) -> dict[str, Any]:
    """把模型只需负责的视觉观察结构展开为最终结果骨架。"""

    active_profiles = [
        profile
        for profile in observation.get("active_profiles", [])
        if isinstance(profile, str) and profile not in FORBIDDEN_SINGLE_IMAGE_PROFILES
    ]
    if "core" not in active_profiles:
        active_profiles.insert(0, "core")
    active_profiles = _ordered_unique(active_profiles)

    design_observation_items = []
    for index, item in enumerate(observation.get("design_observations", [])):
        if not isinstance(item, dict):
            continue
        copied = copy.deepcopy(item)
        copied["_source_pointer"] = f"/design_observations/{index}"
        design_observation_items.append(copied)
    existing_observation_keys = {
        (str(item.get("field_id") or ""), str(item.get("region") or ""))
        for item in design_observation_items
    }
    for uncertainty_index, uncertainty in enumerate(observation.get("uncertainties", [])):
        if not isinstance(uncertainty, dict):
            continue
        key = (
            str(uncertainty.get("field_id") or ""),
            str(uncertainty.get("region") or ""),
        )
        if key in existing_observation_keys:
            continue
        design_observation_items.append(
            {
                "field_id": uncertainty.get("field_id"),
                "value": uncertainty.get("best_estimate"),
                "raw_visual_description": uncertainty.get("reason", ""),
                "region": uncertainty.get("region"),
                "observability": uncertainty.get("observability"),
                "confidence": uncertainty.get("confidence"),
                "evidence_refs": copy.deepcopy(
                    uncertainty.get("evidence_refs", [])
                ),
                "_source_pointer": f"/uncertainties/{uncertainty_index}",
            }
        )
        existing_observation_keys.add(key)

    modules: dict[str, list[dict[str, Any]]] = {}
    for item in design_observation_items:
        if not isinstance(item, dict):
            continue
        record = fields.get(str(item.get("field_id") or ""))
        module_id = str(record.get("module_id") or "") if record else ""
        if not module_id:
            # 未知字段保留在占位模块中，使最终校验器给出明确的 canonical field 错误。
            module_id = "DNA-M14"
        modules.setdefault(module_id, []).append(copy.deepcopy(item))

    applicable_modules = [
        {
            "module_id": module_id,
            "module_name": module_names.get(module_id, module_id),
            "reason": "本次模型观察包含该模块的适用品类字段。",
        }
        for module_id in sorted(modules)
        if module_id != "DNA-M15"
    ]
    style_observations = observation.get("style_observations")
    if not isinstance(style_observations, dict):
        style_observations = {}
    quality_notes = observation.get("quality_notes")
    if not isinstance(quality_notes, dict):
        quality_notes = {}

    confirmed_tags: list[dict[str, Any]] = []
    for source_index, item in enumerate(style_observations.get("confirmed_tags", [])):
        if not isinstance(item, dict):
            continue
        applicable_count = item.get("applicable_rule_count", 0)
        confirmed_tags.append(
            {
                "style_id": item.get("style_id"),
                "match_score": item.get("match_score"),
                "confidence": item.get("confidence"),
                "dominance": item.get("dominance"),
                "regions": copy.deepcopy(item.get("regions", [])),
                "hard_rule_passed": True,
                "rule_coverage": {
                    "applicable_rule_count": applicable_count,
                    "passed_rule_count": applicable_count,
                    "failed_rule_count": 0,
                    "unknown_rule_count": 0,
                    "not_applicable_rule_count": item.get(
                        "not_applicable_rule_count", 0
                    ),
                },
                "color_requirement": {
                    "status": item.get("color_requirement_status"),
                    "evidence_refs": [],
                },
                "core_feature_hits": copy.deepcopy(
                    item.get("core_feature_hits", [])
                ),
                "auxiliary_feature_hits": copy.deepcopy(
                    item.get("auxiliary_feature_hits", [])
                ),
                "missing_required_items": [],
                "exclusion_hits": [],
                "evidence_refs": [],
                "_source_pointer": (
                    f"/style_observations/confirmed_tags/{source_index}"
                ),
            }
        )

    other_candidates: list[dict[str, Any]] = []
    for item in style_observations.get("other_candidates", []):
        if not isinstance(item, dict):
            continue
        candidate = copy.deepcopy(item)
        candidate["dominance"] = 0
        other_candidates.append(candidate)

    expanded_uncertainties = []
    for source_index, item in enumerate(observation.get("uncertainties", [])):
        if not isinstance(item, dict):
            continue
        expanded = {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key != "evidence_refs"
        }
        expanded["_source_pointer"] = f"/uncertainties/{source_index}"
        expanded_uncertainties.append(expanded)

    return {
        "schema_version": FINAL_SCHEMA_VERSION,
        "knowledge_base_version": observation.get(
            "knowledge_base_version", KNOWLEDGE_BASE_VERSION
        ),
        "target_object": copy.deepcopy(observation.get("target_object", {})),
        "image_quality": copy.deepcopy(observation.get("image_quality", {})),
        "module_applicability": {
            "active_profiles": active_profiles,
            "applicable_modules": applicable_modules,
            "excluded_modules": [
                {
                    "module_id": "DNA-M15",
                    "module_name": module_names.get("DNA-M15", "DNA-M15"),
                    "reason": "profile_not_applicable",
                    "explanation": "当前为单图提取，未激活参考集或趋势分析 profile。",
                }
            ],
            "rule_adaptations": copy.deepcopy(observation.get("rule_adaptations", [])),
        },
        "style_result": {
            "classification_status": style_observations.get("classification_status"),
            "style_tags": confirmed_tags,
            "candidate_ranking": other_candidates,
            "pairwise_arbitrations": copy.deepcopy(
                style_observations.get("pairwise_reasoning", [])
            ),
            "composition_summary": style_observations.get("composition_summary", ""),
        },
        "design_elements": {
            "original_md_dimensions": [],
            "extended_dna_modules": [
                {
                    "module_id": module_id,
                    "module_name": module_names.get(module_id, module_id),
                    "elements": elements,
                }
                for module_id, elements in sorted(modules.items())
            ],
        },
        "uncertain_fields": expanded_uncertainties,
        "novel_dna_elements": copy.deepcopy(
            observation.get("novel_dna_elements", [])
        ),
        "evidence": copy.deepcopy(observation.get("evidence", [])),
        "quality_summary": {
            "visible_coverage": observation.get("image_quality", {}).get(
                "object_visible_ratio", 0
            ),
            "mean_confidence": 0,
            "style_confidence": 0,
            "low_confidence_field_count": 0,
            "missing_critical_fields": copy.deepcopy(
                quality_notes.get("missing_critical_fields", [])
            ),
            "warnings": copy.deepcopy(quality_notes.get("warnings", [])),
            "concise_summary": quality_notes.get("concise_summary", ""),
        },
    }


def _iter_elements(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    elements: list[tuple[str, dict[str, Any]]] = []
    design_elements = data.get("design_elements")
    if not isinstance(design_elements, dict):
        return elements
    for module in design_elements.get("extended_dna_modules", []):
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("module_id") or "")
        for element in module.get("elements", []):
            if isinstance(element, dict):
                elements.append((module_id, element))
    return elements


def _normalize_elements(
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    module_names: dict[str, str],
    value_spaces: dict[str, tuple[str, set[str]]],
    normalization: dict[str, Any],
    report: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """过滤不适用字段并完成不涉及视觉推断的值与元数据整理。"""

    design_elements = data.setdefault(
        "design_elements", {"original_md_dimensions": [], "extended_dna_modules": []}
    )
    _replace_if_changed(
        design_elements,
        "original_md_dimensions",
        [],
        "/design_elements",
        report,
    )
    modules = design_elements.get("extended_dna_modules")
    if not isinstance(modules, list):
        return {}

    applicability = data.get("module_applicability")
    if not isinstance(applicability, dict):
        applicability = {}
    active_profiles = {
        profile
        for profile in applicability.get("active_profiles", [])
        if isinstance(profile, str) and profile not in FORBIDDEN_SINGLE_IMAGE_PROFILES
    }
    active_profiles.add("core")
    target = data.get("target_object")
    target_view = str(target.get("view") or "unknown") if isinstance(target, dict) else "unknown"

    canonical_elements: dict[str, list[dict[str, Any]]] = {}
    element_index: dict[tuple[str, str], dict[str, Any]] = {}
    filtered = report.setdefault("filtered_fields", [])
    normalized_values = report.setdefault("value_normalizations", [])
    for module_index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        elements = module.get("elements")
        if not isinstance(elements, list):
            continue
        for element_index_in_module, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            source_path = (
                f"/design_elements/extended_dna_modules/{module_index}"
                f"/elements/{element_index_in_module}"
            )
            field_id = str(element.get("field_id") or "")
            record = fields.get(field_id)
            if record is None:
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "unknown_canonical_field",
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue

            required_profiles = {
                profile
                for profile in record.get("applicability", [])
                if isinstance(profile, str)
            }
            if required_profiles and not required_profiles.intersection(active_profiles):
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "profile_not_applicable",
                        "required_profiles": sorted(required_profiles),
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue
            required_views = [
                view for view in record.get("required_views", []) if isinstance(view, str)
            ]
            if required_views and not _view_requirement_satisfied(required_views, target_view):
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "view_not_applicable",
                        "required_views": required_views,
                        "actual_view": target_view,
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue

            canonical_module_id = str(record.get("module_id") or "")
            normalized_value, notes = _normalized_controlled_value(
                field_id,
                record,
                copy.deepcopy(element.get("value")),
                value_spaces,
                normalization,
            )
            if notes:
                normalized_values.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "notes": notes,
                    }
                )
            original_value = element.get("value")
            if normalized_value != original_value:
                _replace_if_changed(
                    element, "value", normalized_value, source_path, report
                )
            invalid_value = original_value is not None and normalized_value is None
            if invalid_value:
                element["_compiler_uncertainty_reason"] = notes[-1]
                confidence = element.get("confidence")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    _replace_if_changed(
                        element,
                        "confidence",
                        min(float(confidence), 0.74),
                        source_path,
                        report,
                    )
            confidence = element.get("confidence")
            if (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and float(confidence) < 0.30
                and element.get("value") is not None
            ):
                element["_compiler_uncertainty_reason"] = (
                    "置信度低于 0.30，不能保留确定值"
                )
                _replace_if_changed(element, "value", None, source_path, report)

            for key, metadata_value in {
                "field_name": record.get("name"),
                "source_path": f"{canonical_module_id}/{field_id}",
                "schema_source": "md_extension",
                "value_type": record.get("value_type"),
                "evidence_mode": record.get("evidence_mode"),
                "applicability_status": "applicable",
            }.items():
                _replace_if_changed(element, key, metadata_value, source_path, report)

            evidence_mode = record.get("evidence_mode")
            value = element.get("value")
            if evidence_mode == "direct":
                _replace_if_changed(
                    element, "computation_status", "not_requested", source_path, report
                )
                if value is None:
                    _replace_if_changed(
                        element, "observability", "unknown", source_path, report
                    )
            elif evidence_mode == "reference_computed":
                _replace_if_changed(
                    element, "computation_status", "not_computable", source_path, report
                )
                _replace_if_changed(element, "value", None, source_path, report)
            elif value is None:
                _replace_if_changed(
                    element, "computation_status", "not_computable", source_path, report
                )
                if element.get("observability") == "observed":
                    _replace_if_changed(
                        element, "observability", "unknown", source_path, report
                    )
            else:
                _replace_if_changed(
                    element, "computation_status", "computed", source_path, report
                )
                _replace_if_changed(
                    element, "observability", "observed", source_path, report
                )
            refs = element.get("evidence_refs")
            if not isinstance(refs, list):
                refs = []
            _replace_if_changed(
                element,
                "evidence_refs",
                _ordered_unique(refs),
                source_path,
                report,
            )

            region = str(element.get("region") or "")
            key = (field_id, region)
            previous = element_index.get(key)
            if previous is not None:
                previous_confidence = previous.get("confidence")
                current_confidence = element.get("confidence")
                previous_score = float(previous_confidence or 0)
                current_score = float(current_confidence or 0)
                if previous.get("value") is not None:
                    previous_score += 1
                if element.get("value") is not None:
                    current_score += 1
                if current_score <= previous_score:
                    filtered.append(
                        {
                            "field_id": field_id,
                            "source_pointer": element.get("_source_pointer"),
                            "reason": "duplicate_field_region",
                        }
                    )
                    continue
                canonical_elements[canonical_module_id].remove(previous)
            element_index[key] = element
            canonical_elements.setdefault(canonical_module_id, []).append(element)

    rebuilt_modules = [
        {
            "module_id": module_id,
            "module_name": module_names.get(module_id, module_id),
            "elements": elements,
        }
        for module_id, elements in sorted(canonical_elements.items())
        if elements
    ]
    _replace_if_changed(
        design_elements,
        "extended_dna_modules",
        rebuilt_modules,
        "/design_elements",
        report,
    )

    # 派生字段的证据闭环完全由注册依赖和已存在的源字段证据计算，不创造视觉事实。
    for (field_id, region), element in element_index.items():
        record = fields.get(field_id, {})
        if (
            record.get("evidence_mode") != "derived"
            or element.get("computation_status") != "computed"
        ):
            continue
        source_refs: list[str] = []
        for dependency in record.get("derived_from", []):
            candidates = [
                source
                for (source_id, source_region), source in element_index.items()
                if source_id == dependency
                and source.get("value") is not None
                and source.get("observability") == "observed"
                and (
                    source_region == region
                    or source_region.startswith("whole_object")
                    or region.startswith("whole_object")
                )
            ]
            if candidates:
                source_refs.extend(candidates[0].get("evidence_refs") or [])
        merged_refs = _ordered_unique(
            [*(element.get("evidence_refs") or []), *source_refs]
        )
        _replace_if_changed(
            element,
            "evidence_refs",
            merged_refs,
            f"/design_elements/{field_id}@{region}",
            report,
        )
    return element_index


def _normalize_modules(
    data: dict[str, Any],
    module_names: dict[str, str],
    report: dict[str, Any],
) -> None:
    applicability = data.setdefault("module_applicability", {})
    active_profiles = applicability.get("active_profiles")
    if not isinstance(active_profiles, list):
        active_profiles = []
    active_profiles = [
        item
        for item in active_profiles
        if isinstance(item, str) and item not in FORBIDDEN_SINGLE_IMAGE_PROFILES
    ]
    if "core" not in active_profiles:
        active_profiles.insert(0, "core")
    _replace_if_changed(
        applicability,
        "active_profiles",
        _ordered_unique(active_profiles),
        "/module_applicability",
        report,
    )

    present_modules = {
        module_id for module_id, _element in _iter_elements(data) if module_id != "DNA-M15"
    }
    existing_applicable = {
        str(item.get("module_id") or ""): item
        for item in applicability.get("applicable_modules", [])
        if isinstance(item, dict)
    }
    rebuilt_applicable = []
    for module_id in sorted(present_modules):
        previous = existing_applicable.get(module_id, {})
        rebuilt_applicable.append(
            {
                "module_id": module_id,
                "module_name": module_names.get(module_id, module_id),
                "reason": previous.get("reason")
                or "本次模型观察包含该模块的适用品类字段。",
            }
        )
    _replace_if_changed(
        applicability,
        "applicable_modules",
        rebuilt_applicable,
        "/module_applicability",
        report,
    )

    excluded = [
        copy.deepcopy(item)
        for item in applicability.get("excluded_modules", [])
        if isinstance(item, dict) and item.get("module_id") != "DNA-M15"
    ]
    excluded.append(
        {
            "module_id": "DNA-M15",
            "module_name": module_names.get("DNA-M15", "DNA-M15"),
            "reason": "profile_not_applicable",
            "explanation": "当前为单图提取，未激活参考集或趋势分析 profile。",
        }
    )
    _replace_if_changed(
        applicability,
        "excluded_modules",
        excluded,
        "/module_applicability",
        report,
    )
    if not isinstance(applicability.get("rule_adaptations"), list):
        _replace_if_changed(
            applicability,
            "rule_adaptations",
            [],
            "/module_applicability",
            report,
        )


def _field_evidence_index(
    element_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for (field_id, _region), element in element_index.items():
        confidence = element.get("confidence")
        available = (
            element.get("observability") == "observed"
            if element.get("evidence_mode") == "direct"
            else element.get("computation_status") == "computed"
        )
        if (
            not available
            or element.get("value") is None
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or float(confidence) < 0.75
        ):
            continue
        result.setdefault(field_id, []).extend(element.get("evidence_refs") or [])
    return {field_id: _ordered_unique(refs) for field_id, refs in result.items()}


def _normalize_styles(
    data: dict[str, Any],
    styles: dict[str, dict[str, Any]],
    tag_relations: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    style_result = data.setdefault("style_result", {})
    raw_tags = style_result.get("style_tags")
    candidate_tags = (
        [item for item in raw_tags if isinstance(item, dict)]
        if isinstance(raw_tags, list)
        else []
    )
    tags: list[dict[str, Any]] = []
    seen_tag_ids: set[str] = set()
    for tag in candidate_tags:
        style_id = str(tag.get("style_id") or "")
        if style_id in seen_tag_ids:
            _record_change(report, "/style_result/style_tags/duplicate")
            continue
        seen_tag_ids.add(style_id)
        tags.append(tag)
    field_evidence = _field_evidence_index(element_index)
    evidence_regions = {
        str(item.get("evidence_id") or ""): str(item.get("region") or "")
        for item in data.get("evidence", [])
        if isinstance(item, dict)
    }
    demoted_candidates: list[dict[str, Any]] = []
    retained_tags: list[dict[str, Any]] = []

    for index, tag in enumerate(tags):
        path = f"/style_result/style_tags/{index}"
        style_id = str(tag.get("style_id") or "")
        style_record = styles.get(style_id)
        downgrade_reasons: list[str] = []
        if style_record is None:
            downgrade_reasons.append("风格 ID 未在活动注册表中")
            decisive_ids: set[str] = set()
            auxiliary_ids: set[str] = set()
        else:
            for key, value in _style_identity(style_record).items():
                _replace_if_changed(tag, key, value, path, report)
            decisive_ids = set(style_record.get("decisive_field_ids") or [])
            auxiliary_ids = set(style_record.get("auxiliary_field_ids") or [])

        rebuilt_hits: dict[str, list[str]] = {
            "core_feature_hits": [],
            "auxiliary_feature_hits": [],
        }
        for original_role in ("core_feature_hits", "auxiliary_feature_hits"):
            for hit in tag.get(original_role, []):
                hit_text = str(hit)
                referenced = FIELD_ID_PATTERN.findall(hit_text)
                if not referenced:
                    downgrade_reasons.append(f"证据命中未引用规范字段：{hit_text}")
                    continue
                unavailable = [
                    field_id for field_id in referenced if field_id not in field_evidence
                ]
                if unavailable:
                    downgrade_reasons.append(
                        f"字段没有可用于确认风格的值或证据：{', '.join(unavailable)}"
                    )
                    continue
                can_core = all(field_id in decisive_ids for field_id in referenced)
                can_auxiliary = all(
                    field_id in auxiliary_ids for field_id in referenced
                )
                target_role: str | None = None
                if original_role == "core_feature_hits" and can_core:
                    target_role = original_role
                elif original_role == "auxiliary_feature_hits" and can_auxiliary:
                    target_role = original_role
                elif can_core and not can_auxiliary:
                    target_role = "core_feature_hits"
                elif can_auxiliary and not can_core:
                    target_role = "auxiliary_feature_hits"
                elif can_core and can_auxiliary:
                    target_role = original_role
                if target_role is None:
                    downgrade_reasons.append(
                        f"字段不在该风格允许的决定或辅助集合：{', '.join(referenced)}"
                    )
                    continue
                rebuilt_hits[target_role].append(hit_text)
                if target_role != original_role:
                    _record_change(report, f"{path}/{original_role}/reclassified")

        for role, hits in rebuilt_hits.items():
            _replace_if_changed(tag, role, _ordered_unique(hits), path, report)
        core_field_ids = {
            field_id
            for hit in rebuilt_hits["core_feature_hits"]
            for field_id in FIELD_ID_PATTERN.findall(hit)
        }
        auxiliary_field_ids = {
            field_id
            for hit in rebuilt_hits["auxiliary_feature_hits"]
            for field_id in FIELD_ID_PATTERN.findall(hit)
        }
        if not rebuilt_hits["core_feature_hits"]:
            downgrade_reasons.append("缺少注册表允许的决定字段")
        if not rebuilt_hits["auxiliary_feature_hits"]:
            downgrade_reasons.append("缺少注册表允许且可用的辅助字段")
        if auxiliary_field_ids and not auxiliary_field_ids.difference(core_field_ids):
            downgrade_reasons.append("辅助字段没有形成独立于决定字段的支持")
        referenced_fields = [
            field_id
            for key in ("core_feature_hits", "auxiliary_feature_hits")
            for hit in rebuilt_hits[key]
            for field_id in FIELD_ID_PATTERN.findall(str(hit))
        ]
        inferred_refs = [
            evidence_id
            for field_id in referenced_fields
            for evidence_id in field_evidence.get(field_id, [])
        ]
        color = tag.get("color_requirement")
        if isinstance(color, dict):
            color_refs = color.get("evidence_refs")
            if not isinstance(color_refs, list):
                color_refs = []
            if color.get("status") == "pass":
                color_refs = _ordered_unique(
                    [
                        *color_refs,
                        *(
                            evidence_id
                            for field_id in referenced_fields
                            if field_id.startswith("CLR-")
                            for evidence_id in field_evidence.get(field_id, [])
                        ),
                    ]
                )
                if not color_refs:
                    downgrade_reasons.append("颜色门槛通过但没有可用颜色证据")
            inferred_refs.extend(color_refs)
            _replace_if_changed(
                color,
                "evidence_refs",
                _ordered_unique(color_refs),
                f"{path}/color_requirement",
                report,
            )
        _replace_if_changed(
            tag,
            "evidence_refs",
            _ordered_unique(inferred_refs),
            path,
            report,
        )
        backed_regions = {
            evidence_regions.get(evidence_id, "")
            for evidence_id in tag.get("evidence_refs", [])
            if evidence_regions.get(evidence_id)
        }
        normalized_regions = [
            region
            for region in tag.get("regions", [])
            if isinstance(region, str) and region in backed_regions
        ]
        _replace_if_changed(
            tag,
            "regions",
            _ordered_unique(normalized_regions),
            path,
            report,
        )
        if len(tag.get("evidence_refs") or []) < 2:
            downgrade_reasons.append("可用风格证据少于两条")
        if not normalized_regions:
            downgrade_reasons.append("声明区域没有对应的引用证据")
        coverage = tag.get("rule_coverage")
        if not isinstance(coverage, dict):
            downgrade_reasons.append("规则覆盖结构缺失")
        elif (
            coverage.get("applicable_rule_count", 0) < 1
            or coverage.get("passed_rule_count", 0) < 1
            or coverage.get("failed_rule_count", 0) != 0
            or coverage.get("unknown_rule_count", 0) != 0
        ):
            downgrade_reasons.append("规则覆盖没有达到 confirmed 门槛")
        if (
            not tag.get("hard_rule_passed")
            or tag.get("missing_required_items")
            or tag.get("exclusion_hits")
        ):
            downgrade_reasons.append("硬规则、缺失项或排除项未闭合")

        if downgrade_reasons:
            demoted_candidates.append(
                {
                    "style_id": style_id,
                    "match_score": tag.get("match_score", 0),
                    "confidence": tag.get("confidence", 0),
                    "dominance": 0,
                    "regions": copy.deepcopy(tag.get("regions", [])),
                    "candidate_status": "provisional",
                    "hard_rule_passed": False,
                    "main_support": _ordered_unique(
                        [
                            *rebuilt_hits["core_feature_hits"],
                            *rebuilt_hits["auxiliary_feature_hits"],
                        ]
                    ),
                    "main_conflicts": _ordered_unique(downgrade_reasons),
                    "_source_pointer": tag.get("_source_pointer"),
                }
            )
            report.setdefault("style_downgrades", []).append(
                {
                    "style_id": style_id,
                    "source_pointer": tag.get("_source_pointer"),
                    "reasons": _ordered_unique(downgrade_reasons),
                }
            )
            _record_change(report, f"{path}/demoted")
            continue
        retained_tags.append(tag)

    tags = retained_tags

    if len(tags) == 1:
        _replace_if_changed(tags[0], "dominance", 1, "/style_result/style_tags/0", report)
    elif len(tags) > 1:
        values = [tag.get("dominance") for tag in tags]
        if all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) > 0
            for value in values
        ):
            total = sum(float(value) for value in values)
            normalized: list[float] = []
            for value in values[:-1]:
                normalized.append(round(float(value) / total, 6))
            normalized.append(round(1 - sum(normalized), 6))
            for index, value in enumerate(normalized):
                _replace_if_changed(
                    tags[index],
                    "dominance",
                    value,
                    f"/style_result/style_tags/{index}",
                    report,
                )

    tags.sort(
        key=lambda item: (
            -float(item.get("dominance") or 0),
            -float(item.get("match_score") or 0),
            str(item.get("style_id") or ""),
        )
    )
    _replace_if_changed(style_result, "style_tags", tags, "/style_result", report)
    _replace_if_changed(
        style_result,
        "classification_status",
        "confirmed" if tags else "unclassified",
        "/style_result",
        report,
    )
    if not tags and demoted_candidates:
        _replace_if_changed(
            style_result,
            "composition_summary",
            "候选风格的决定字段、辅助字段或区域证据未形成完整闭环，已降级为未分类。",
            "/style_result",
            report,
        )

    existing_candidates = style_result.get("candidate_ranking")
    raw_candidates = (
        [*demoted_candidates, *[item for item in existing_candidates if isinstance(item, dict)]]
        if isinstance(existing_candidates, list)
        else demoted_candidates
    )
    candidates: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for candidate in raw_candidates:
        style_id = str(candidate.get("style_id") or "")
        if style_id in seen_candidate_ids:
            _record_change(report, "/style_result/candidate_ranking/duplicate")
            continue
        seen_candidate_ids.add(style_id)
        candidates.append(candidate)
    candidate_by_id = {
        str(item.get("style_id") or ""): item
        for item in candidates
        if isinstance(item.get("style_id"), str)
    }
    tag_by_id = {str(tag.get("style_id") or ""): tag for tag in tags}
    for style_id, tag in tag_by_id.items():
        candidate = candidate_by_id.get(style_id)
        if candidate is None:
            candidate = {"style_id": style_id, "main_support": [], "main_conflicts": []}
            candidates.append(candidate)
            candidate_by_id[style_id] = candidate
        for key in (
            "label_en",
            "label_zh",
            "aliases",
            "tag_kind",
            "facet_ids",
            "match_score",
            "confidence",
            "dominance",
            "regions",
            "hard_rule_passed",
        ):
            candidate[key] = copy.deepcopy(tag.get(key))
        candidate["candidate_status"] = "confirmed"
        if not candidate.get("main_support"):
            candidate["main_support"] = _ordered_unique(
                [
                    *(tag.get("core_feature_hits") or []),
                    *(tag.get("auxiliary_feature_hits") or []),
                ]
            )
        candidate["main_conflicts"] = []

    for candidate in candidates:
        style_id = str(candidate.get("style_id") or "")
        if style_id in styles:
            candidate.update(_style_identity(styles[style_id]))
        if style_id not in tag_by_id:
            candidate["dominance"] = 0
            if candidate.get("candidate_status") == "confirmed":
                candidate["candidate_status"] = "provisional"

    candidates.sort(
        key=lambda item: (
            -float(item.get("match_score") or 0),
            str(item.get("style_id") or ""),
        )
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    _replace_if_changed(
        style_result, "candidate_ranking", candidates, "/style_result", report
    )

    pair_relations = _pair_relation_map(tag_relations)
    default_relation = tag_relations.get("default_pair_relation")
    if not isinstance(default_relation, dict):
        default_relation = {}
    existing_pairs = style_result.get("pairwise_arbitrations")
    pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(existing_pairs, list):
        for item in existing_pairs:
            if not isinstance(item, dict):
                continue
            key = tuple(
                sorted(
                    (
                        str(item.get("style_id_a") or ""),
                        str(item.get("style_id_b") or ""),
                    )
                )
            )
            pair_by_key[key] = item
    rebuilt_pairs: list[dict[str, Any]] = []
    for style_id_a, style_id_b in combinations(sorted(tag_by_id), 2):
        key = (style_id_a, style_id_b)
        previous = pair_by_key.get(key)
        if previous is None:
            # 关系理由属于模型语义判断；缺失时不伪造，交由最终校验触发语义修复。
            continue
        relation = pair_relations.get(key, default_relation)
        rebuilt_pairs.append(
            {
                "style_id_a": style_id_a,
                "style_id_b": style_id_b,
                "relation": relation.get("relation"),
                "scope": relation.get("scope"),
                "decision": "coexist",
                "reason": previous.get("reason", ""),
                "evidence_refs": _ordered_unique(
                    [
                        *(previous.get("evidence_refs") or []),
                        *(tag_by_id[style_id_a].get("evidence_refs") or []),
                        *(tag_by_id[style_id_b].get("evidence_refs") or []),
                    ]
                ),
            }
        )
    _replace_if_changed(
        style_result,
        "pairwise_arbitrations",
        rebuilt_pairs,
        "/style_result",
        report,
    )


def _normalize_uncertainties(
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """从最终字段状态单向重建不确定项镜像，避免模型维护重复结构。"""

    raw_items = data.get("uncertain_fields")
    if not isinstance(raw_items, list):
        raw_items = []
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        field_id = str(item.get("field_id") or "")
        region = str(item.get("region") or "")
        key = (field_id, region)
        if key not in element_index:
            same_field = [
                element_region
                for candidate_field_id, element_region in element_index
                if candidate_field_id == field_id
            ]
            if len(same_field) == 1:
                region = same_field[0]
                key = (field_id, region)
                item["region"] = region
        existing.setdefault(key, item)

    rebuilt: list[dict[str, Any]] = []
    for (field_id, region), element in element_index.items():
        evidence_mode = str(element.get("evidence_mode") or "")
        observability = str(element.get("observability") or "unknown")
        computation_status = str(element.get("computation_status") or "")
        confidence = element.get("confidence")
        low_confidence = (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) < 0.75
        )
        unavailable = (
            evidence_mode == "direct" and observability != "observed"
        ) or (
            evidence_mode != "direct" and computation_status != "computed"
        )
        compiler_reason = element.get("_compiler_uncertainty_reason")
        if not (low_confidence or unavailable or compiler_reason):
            continue

        item = copy.deepcopy(existing.get((field_id, region), {}))
        item.setdefault("field_id", field_id)
        item.setdefault("region", region)
        if compiler_reason and not unavailable:
            reason_type = "definition_gap"
            reason = str(compiler_reason)
        elif evidence_mode == "reference_computed":
            reason_type = "missing_reference"
            reason = "当前单图任务缺少该字段所需的批准参考集。"
        elif unavailable and evidence_mode != "direct":
            reason_type = "not_computable"
            reason = "当前可用观察不足以完成该非直接字段计算。"
        elif unavailable:
            reason_type = "not_observable"
            reason = "当前图片没有提供该字段所需的清晰可见信息。"
        else:
            reason_type = "low_confidence"
            reason = "字段置信度低于确认阈值 0.75。"
        item["reason_type"] = reason_type
        item["reason"] = item.get("reason") or reason
        item["best_estimate"] = None if unavailable else element.get("value")
        item.setdefault("candidate_values", [])
        item.setdefault(
            "recommended_additional_view_or_info",
            "补充更清晰或覆盖相应区域与视角的图片。",
        )
        item.setdefault("_source_pointer", element.get("_source_pointer"))
        rebuilt.append(item)

    _replace_if_changed(
        data,
        "uncertain_fields",
        rebuilt,
        "",
        report,
    )

    for index, item in enumerate(rebuilt):
        if not isinstance(item, dict):
            continue
        path = f"/uncertain_fields/{index}"
        field_id = str(item.get("field_id") or "")
        region = str(item.get("region") or "")
        element = element_index.get((field_id, region))
        if element is None:
            same_field = [
                (element_region, candidate)
                for (candidate_field_id, element_region), candidate in element_index.items()
                if candidate_field_id == field_id
            ]
            if len(same_field) == 1:
                region, element = same_field[0]
                _replace_if_changed(item, "region", region, path, report)
        record = fields.get(field_id)
        if record is not None:
            _replace_if_changed(item, "field_name", record.get("name"), path, report)
            _replace_if_changed(
                item,
                "source_path",
                f"{record.get('module_id')}/{field_id}",
                path,
                report,
            )
        if element is not None:
            for key in (
                "evidence_mode",
                "applicability_status",
                "observability",
                "computation_status",
                "confidence",
            ):
                _replace_if_changed(item, key, element.get(key), path, report)
        if (
            element is not None
            and item.get("best_estimate") is None
            and element.get("value") is not None
            and (
                element.get("observability") == "observed"
                if element.get("evidence_mode") == "direct"
                else element.get("computation_status") == "computed"
            )
        ):
            _replace_if_changed(
                item, "best_estimate", element.get("value"), path, report
            )
        candidates = item.get("candidate_values")
        if isinstance(candidates, list) and candidates:
            probabilities = [
                candidate.get("probability") if isinstance(candidate, dict) else None
                for candidate in candidates
            ]
            if all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and float(value) >= 0
                for value in probabilities
            ):
                total = sum(float(value) for value in probabilities)
                if total > 0:
                    normalized = [round(float(value) / total, 6) for value in probabilities[:-1]]
                    normalized.append(round(1 - sum(normalized), 6))
                    if any(
                        candidate.get("probability") != probability
                        for candidate, probability in zip(candidates, normalized, strict=True)
                    ):
                        for candidate, probability in zip(candidates, normalized, strict=True):
                            candidate["probability"] = probability
                        _record_change(report, f"{path}/candidate_values/*/probability")


def _normalize_quality(
    data: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    quality = data.setdefault("quality_summary", {})
    confidences = [
        float(element["confidence"])
        for element in element_index.values()
        if isinstance(element.get("confidence"), (int, float))
        and not isinstance(element.get("confidence"), bool)
    ]
    tags = data.get("style_result", {}).get("style_tags", [])
    style_confidences = [
        float(item["confidence"])
        for item in tags
        if isinstance(item, dict)
        and isinstance(item.get("confidence"), (int, float))
        and not isinstance(item.get("confidence"), bool)
    ]
    calculated = {
        "mean_confidence": round(sum(confidences) / len(confidences), 6)
        if confidences
        else 0,
        "low_confidence_field_count": sum(value < 0.75 for value in confidences),
        "style_confidence": max(style_confidences, default=0),
    }
    for key, value in calculated.items():
        _replace_if_changed(quality, key, value, "/quality_summary", report)
    if not isinstance(quality.get("visible_coverage"), (int, float)):
        image_quality = data.get("image_quality")
        visible = (
            image_quality.get("object_visible_ratio", 0)
            if isinstance(image_quality, dict)
            else 0
        )
        _replace_if_changed(
            quality, "visible_coverage", visible, "/quality_summary", report
        )
    warnings = [
        item for item in quality.get("warnings", []) if isinstance(item, str)
    ]
    filtered_count = len(report.get("filtered_fields", []))
    normalized_count = len(report.get("value_normalizations", []))
    downgraded_count = len(report.get("style_downgrades", []))
    compiler_warnings = []
    if filtered_count:
        compiler_warnings.append(f"宿主按视角、Profile 或规范字段过滤了 {filtered_count} 项观察。")
    if normalized_count:
        compiler_warnings.append(f"宿主按受控值域确定性归一了 {normalized_count} 项字段。")
    if downgraded_count:
        compiler_warnings.append(f"宿主因证据闭环不足降级了 {downgraded_count} 个风格标签。")
    _replace_if_changed(
        quality,
        "warnings",
        _ordered_unique([*warnings, *compiler_warnings]),
        "/quality_summary",
        report,
    )


def _finalize_source_map(data: dict[str, Any], report: dict[str, Any]) -> None:
    """建立最终校验路径到模型观察路径的旁路映射，并移除内部标记。"""

    source_map: dict[str, dict[str, Any]] = {}
    flat_index = 0
    modules = data.get("design_elements", {}).get("extended_dna_modules", [])
    for module in modules if isinstance(modules, list) else []:
        if not isinstance(module, dict):
            continue
        for element in module.get("elements", []):
            if not isinstance(element, dict):
                continue
            pointer = element.get("_source_pointer")
            if isinstance(pointer, str):
                source_map[f"design_element[{flat_index}]"] = {
                    "source_pointer": pointer,
                    "field_id": element.get("field_id"),
                    "region": element.get("region"),
                }
            flat_index += 1

    style_result = data.get("style_result")
    if isinstance(style_result, dict):
        for collection_name in ("style_tags", "candidate_ranking"):
            items = style_result.get(collection_name)
            for index, item in enumerate(items if isinstance(items, list) else []):
                if not isinstance(item, dict):
                    continue
                pointer = item.get("_source_pointer")
                if isinstance(pointer, str):
                    source_map[f"style_result.{collection_name}[{index}]"] = {
                        "source_pointer": pointer,
                        "style_id": item.get("style_id"),
                    }
    uncertainties = data.get("uncertain_fields")
    for index, item in enumerate(uncertainties if isinstance(uncertainties, list) else []):
        if not isinstance(item, dict):
            continue
        pointer = item.get("_source_pointer")
        if isinstance(pointer, str):
            source_map[f"uncertain_fields[{index}]"] = {
                "source_pointer": pointer,
                "field_id": item.get("field_id"),
                "region": item.get("region"),
            }
    report["source_map"] = source_map

    def strip_private(value: Any) -> None:
        if isinstance(value, dict):
            for key in [key for key in value if key.startswith("_")]:
                value.pop(key, None)
            for child in value.values():
                strip_private(child)
        elif isinstance(value, list):
            for child in value:
                strip_private(child)

    strip_private(data)


def compile_model_output(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """编译并整理模型结果；不会发明像素事实，证据不足时只做保守降级。"""

    field_registry = _load_json(FIELD_REGISTRY_PATH)
    style_registry = _load_json(STYLE_REGISTRY_PATH)
    tag_relations = _load_json(TAG_RELATIONS_PATH)
    normalization = _load_json(VALUE_NORMALIZATION_PATH)
    knowledge_base = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    fields = _field_records(field_registry)
    styles = _active_style_records(style_registry)
    module_names = _module_names(knowledge_base)
    value_spaces = _value_spaces(knowledge_base)
    source_contract = str(data.get("schema_version") or "unknown")
    result = copy.deepcopy(data)
    report: dict[str, Any] = {
        "source_contract": source_contract,
        "target_schema_version": FINAL_SCHEMA_VERSION,
        "changed_paths": [],
    }
    if source_contract == OBSERVATION_SCHEMA_VERSION:
        from jsonschema import Draft202012Validator

        _normalize_observation_contract(result, report)
        observation_schema = _load_json(MODEL_OUTPUT_SCHEMA_PATH)
        schema_errors = sorted(
            Draft202012Validator(observation_schema).iter_errors(result),
            key=lambda error: list(error.absolute_path),
        )
        if schema_errors:
            details = []
            for error in schema_errors:
                path = "/" + "/".join(str(part) for part in error.absolute_path)
                details.append(f"model_schema {path or '/'}: {error.message}")
            raise ValueError("模型观察结果未通过 Schema：\n- " + "\n- ".join(details))
        result = _expand_observation(result, fields, module_names)
    _replace_if_changed(result, "schema_version", FINAL_SCHEMA_VERSION, "", report)
    _replace_if_changed(
        result,
        "knowledge_base_version",
        KNOWLEDGE_BASE_VERSION,
        "",
        report,
    )
    element_index = _normalize_elements(
        result,
        fields,
        module_names,
        value_spaces,
        normalization,
        report,
    )
    _normalize_modules(result, module_names, report)
    _normalize_styles(result, styles, tag_relations, element_index, report)
    _normalize_uncertainties(result, fields, element_index, report)
    _normalize_quality(result, element_index, report)
    _finalize_source_map(result, report)
    report["deterministic_correction_count"] = len(report["changed_paths"])
    return result, report


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="模型 JSON；默认从 stdin 读取")
    parser.add_argument(
        "--envelope",
        action="store_true",
        help="输出包含 result 与 report 的对象，供应用层采集整理统计",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("模型 JSON 根节点必须是对象")
        result, report = compile_model_output(data)
        payload = {"result": result, "report": report} if args.envelope else result
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
        print()
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
