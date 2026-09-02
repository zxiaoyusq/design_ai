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
MODEL_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "design-dna-model-output.schema.json"
FINAL_SCHEMA_VERSION = "design_dna_multitag_extraction_v1.1"
OBSERVATION_SCHEMA_VERSION = "design_dna_multitag_observation_v1"
KNOWLEDGE_BASE_VERSION = "4.1"
FIELD_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]{2,3}")
MODULE_HEADING_PATTERN = re.compile(r"^### (DNA-M(?:0[1-9]|1[0-5]))｜(.+)$", re.M)
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

    design_observation_items = [
        copy.deepcopy(item)
        for item in observation.get("design_observations", [])
        if isinstance(item, dict)
    ]
    existing_observation_keys = {
        (str(item.get("field_id") or ""), str(item.get("region") or ""))
        for item in design_observation_items
    }
    for uncertainty in observation.get("uncertainties", []):
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
    for item in style_observations.get("confirmed_tags", []):
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
            }
        )

    other_candidates: list[dict[str, Any]] = []
    for item in style_observations.get("other_candidates", []):
        if not isinstance(item, dict):
            continue
        candidate = copy.deepcopy(item)
        candidate["dominance"] = 0
        other_candidates.append(candidate)

    expanded_uncertainties = [
        {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key != "evidence_refs"
        }
        for item in observation.get("uncertainties", [])
        if isinstance(item, dict)
    ]

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
    report: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
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

    element_index: dict[tuple[str, str], dict[str, Any]] = {}
    for module_index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        module_path = f"/design_elements/extended_dna_modules/{module_index}"
        module_id = str(module.get("module_id") or "")
        if module_id in module_names:
            _replace_if_changed(
                module, "module_name", module_names[module_id], module_path, report
            )
        elements = module.get("elements")
        if not isinstance(elements, list):
            continue
        for element_index_in_module, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            element_path = f"{module_path}/elements/{element_index_in_module}"
            field_id = str(element.get("field_id") or "")
            record = fields.get(field_id)
            if record is None:
                continue
            canonical_module_id = str(record.get("module_id") or module_id)
            for key, value in {
                "field_name": record.get("name"),
                "source_path": f"{canonical_module_id}/{field_id}",
                "schema_source": "md_extension",
                "value_type": record.get("value_type"),
                "evidence_mode": record.get("evidence_mode"),
                "applicability_status": "applicable",
            }.items():
                _replace_if_changed(element, key, value, element_path, report)

            evidence_mode = record.get("evidence_mode")
            value = element.get("value")
            if evidence_mode == "direct":
                _replace_if_changed(
                    element, "computation_status", "not_requested", element_path, report
                )
            elif evidence_mode == "reference_computed":
                _replace_if_changed(
                    element, "computation_status", "not_computable", element_path, report
                )
                _replace_if_changed(element, "value", None, element_path, report)
            elif value is None:
                _replace_if_changed(
                    element, "computation_status", "not_computable", element_path, report
                )
            else:
                _replace_if_changed(
                    element, "computation_status", "computed", element_path, report
                )
                _replace_if_changed(
                    element, "observability", "observed", element_path, report
                )
            refs = element.get("evidence_refs")
            if isinstance(refs, list):
                _replace_if_changed(
                    element,
                    "evidence_refs",
                    _ordered_unique(refs),
                    element_path,
                    report,
                )
            element_index[(field_id, str(element.get("region") or ""))] = element

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

    for index, tag in enumerate(tags):
        path = f"/style_result/style_tags/{index}"
        style_id = str(tag.get("style_id") or "")
        if style_id in styles:
            for key, value in _style_identity(styles[style_id]).items():
                _replace_if_changed(tag, key, value, path, report)
        referenced_fields = [
            field_id
            for key in ("core_feature_hits", "auxiliary_feature_hits")
            for hit in tag.get(key, [])
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
            _ordered_unique([*(tag.get("evidence_refs") or []), *inferred_refs]),
            path,
            report,
        )

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

    existing_candidates = style_result.get("candidate_ranking")
    raw_candidates = (
        [item for item in existing_candidates if isinstance(item, dict)]
        if isinstance(existing_candidates, list)
        else []
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
    items = data.get("uncertain_fields")
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
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


def compile_model_output(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """编译并整理模型结果；不会发明像素事实或改变风格硬判结论。"""

    field_registry = _load_json(FIELD_REGISTRY_PATH)
    style_registry = _load_json(STYLE_REGISTRY_PATH)
    tag_relations = _load_json(TAG_RELATIONS_PATH)
    knowledge_base = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    fields = _field_records(field_registry)
    styles = _active_style_records(style_registry)
    module_names = _module_names(knowledge_base)
    source_contract = str(data.get("schema_version") or "unknown")
    result = copy.deepcopy(data)
    if source_contract == OBSERVATION_SCHEMA_VERSION:
        from jsonschema import Draft202012Validator

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
    report: dict[str, Any] = {
        "source_contract": source_contract,
        "target_schema_version": FINAL_SCHEMA_VERSION,
        "changed_paths": [],
    }
    _replace_if_changed(result, "schema_version", FINAL_SCHEMA_VERSION, "", report)
    _replace_if_changed(
        result,
        "knowledge_base_version",
        KNOWLEDGE_BASE_VERSION,
        "",
        report,
    )
    element_index = _normalize_elements(result, fields, module_names, report)
    _normalize_modules(result, module_names, report)
    _normalize_styles(result, styles, tag_relations, element_index, report)
    _normalize_uncertainties(result, fields, element_index, report)
    _normalize_quality(result, element_index, report)
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
