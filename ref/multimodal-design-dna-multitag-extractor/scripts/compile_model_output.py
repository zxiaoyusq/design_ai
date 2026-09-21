#!/usr/bin/env python3
"""将精简模型观察结果编译为完整 DNA 结果，并整理可确定计算的字段。"""
from __future__ import annotations


import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from dna_rules import extract_kb_value_spaces as _value_spaces
from compilation_support import _ordered_unique, _record_change, _replace_if_changed
from compile_fields import (
    FORBIDDEN_SINGLE_IMAGE_PROFILES,
    _normalize_elements,
    _normalize_modules,
)
from compile_styles import _normalize_styles


ROOT = Path(__file__).resolve().parents[1]
FIELD_REGISTRY_PATH = ROOT / "references" / "field-registry.json"
STYLE_REGISTRY_PATH = ROOT / "references" / "style-registry.json"
STYLE_EVIDENCE_RULES_PATH = ROOT / "references" / "style-evidence-rules.json"
TAG_RELATIONS_PATH = ROOT / "references" / "tag-relations.json"
KNOWLEDGE_BASE_PATH = ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"
VALUE_NORMALIZATION_PATH = ROOT / "references" / "value-normalization.json"
MODEL_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "design-dna-model-output.schema.json"
FINAL_SCHEMA_VERSION = "design_dna_multitag_extraction_v1.3"
OBSERVATION_SCHEMA_VERSION = "design_dna_multitag_observation_v3"
KNOWLEDGE_BASE_VERSION = "4.1"
MAX_NEARBY_EVIDENCE_EXPANSION = 0.05
MODULE_HEADING_PATTERN = re.compile(r"^### (DNA-M(?:0[1-9]|1[0-5]))｜(.+)$", re.M)
VALID_VIEWS = {
    "front",
    "rear",
    "left",
    "right",
    "side",
    "top",
    "bottom",
    "three_quarter",
    "detail",
    "unknown",
}
OBSERVATION_ROOT_ALIASES = (
    ("schemaVersion", "schema_version"),
    ("knowledgeBaseVersion", "knowledge_base_version"),
    ("targetObject", "target_object"),
    ("imageQuality", "image_quality"),
    ("activeProfiles", "active_profiles"),
    ("ruleAdaptations", "rule_adaptations"),
    ("styleObservations", "style_observations"),
    ("designObservations", "design_observations"),
    ("novelDnaElements", "novel_dna_elements"),
    ("qualityNotes", "quality_notes"),
)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"注册表根节点必须是对象：{path}")
    return data


def _normalize_observation_root_aliases(
    observation: dict[str, Any], report: dict[str, Any]
) -> None:
    """无损接收模型偶发生成的驼峰顶层键；冲突值仍交给 Schema 拒绝。"""

    normalizations = report.setdefault("property_alias_normalizations", [])
    for alias, canonical in OBSERVATION_ROOT_ALIASES:
        if alias not in observation:
            continue
        alias_value = observation[alias]
        if canonical in observation and observation[canonical] != alias_value:
            continue

        action = "removed_duplicate_alias"
        observation.pop(alias)
        _record_change(report, f"/{alias}")
        if canonical not in observation:
            observation[canonical] = alias_value
            _record_change(report, f"/{canonical}")
            action = "renamed_to_canonical"
        normalizations.append(
            {
                "source_pointer": f"/{alias}",
                "target_pointer": f"/{canonical}",
                "action": action,
            }
        )


def _fill_observation_descriptions(
    observation: dict[str, Any], report: dict[str, Any]
) -> None:
    """仅复制已有的 value.description，补齐缺失的观察描述。"""

    items = observation.get("design_observations")
    if not isinstance(items, list):
        return
    normalizations = report.setdefault("observation_description_normalizations", [])
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "raw_visual_description" in item:
            continue
        value = item.get("value")
        description = value.get("description") if isinstance(value, dict) else None
        if not isinstance(description, str) or not description.strip():
            continue
        item["raw_visual_description"] = description
        target_pointer = f"/design_observations/{index}/raw_visual_description"
        _record_change(report, target_pointer)
        normalizations.append(
            {
                "source_pointer": f"/design_observations/{index}/value/description",
                "target_pointer": target_pointer,
                "field_id": item.get("field_id"),
                "action": "copied_existing_description",
            }
        )


def _valid_normalized_bbox(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and len(value) == 4
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and 0 <= item <= 1
            for item in value
        )
        and value[0] < value[2]
        and value[1] < value[3]
    )


def _complete_evidence_record(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    evidence_id = evidence.get("evidence_id")
    description = evidence.get("description")
    visual_cues = evidence.get("visual_cues")
    return bool(
        isinstance(evidence_id, str)
        and re.fullmatch(r"EV-[A-Za-z0-9_-]+", evidence_id)
        and isinstance(description, str)
        and description.strip()
        and evidence.get("view") in VALID_VIEWS
        and isinstance(visual_cues, list)
        and visual_cues
        and all(isinstance(cue, str) and cue for cue in visual_cues)
        and len(visual_cues) == len(set(visual_cues))
        and _valid_normalized_bbox(evidence.get("bbox_norm"))
    )


def _synchronize_target_bbox(data: dict[str, Any], report: dict[str, Any]) -> None:
    """吸收证据框与主体框之间不超过 0.05 的坐标取整偏差。"""

    target = data.get("target_object")
    evidence_items = data.get("evidence")
    if not isinstance(target, dict) or not isinstance(evidence_items, list):
        return
    target_bbox = target.get("bbox_norm")
    if not _valid_normalized_bbox(target_bbox):
        return
    valid_evidence = [
        evidence for evidence in evidence_items if _complete_evidence_record(evidence)
    ]
    if not valid_evidence:
        return
    evidence_boxes = [evidence["bbox_norm"] for evidence in valid_evidence]
    expanded = [
        min(target_bbox[0], *(bbox[0] for bbox in evidence_boxes)),
        min(target_bbox[1], *(bbox[1] for bbox in evidence_boxes)),
        max(target_bbox[2], *(bbox[2] for bbox in evidence_boxes)),
        max(target_bbox[3], *(bbox[3] for bbox in evidence_boxes)),
    ]
    expansion = [
        target_bbox[0] - expanded[0],
        target_bbox[1] - expanded[1],
        expanded[2] - target_bbox[2],
        expanded[3] - target_bbox[3],
    ]
    if expanded == target_bbox or any(
        delta > MAX_NEARBY_EVIDENCE_EXPANSION + 1e-9
        for delta in expansion
    ):
        return
    original = copy.deepcopy(target_bbox)
    target["bbox_norm"] = expanded
    _record_change(report, "/target_object/bbox_norm")
    report.setdefault("target_bbox_normalizations", []).append(
        {
            "action": "expanded_to_nearby_evidence_bounds",
            "original_bbox_norm": original,
            "normalized_bbox_norm": copy.deepcopy(expanded),
            "max_edge_expansion": max(expansion),
        }
    )


def _synchronize_evidence_regions(data: dict[str, Any], report: dict[str, Any]) -> None:
    """把有效证据已经明确命名、但主体清单漏登记的区域补入可见区域。"""

    target = data.get("target_object")
    evidence_items = data.get("evidence")
    if not isinstance(target, dict) or not isinstance(evidence_items, list):
        return
    visible_regions = target.get("visible_regions")
    target_bbox = target.get("bbox_norm")
    if not isinstance(visible_regions, list) or not _valid_normalized_bbox(target_bbox):
        return

    declared_regions = {
        region for region in visible_regions if isinstance(region, str) and region
    }
    normalizations = report.setdefault("visible_region_normalizations", [])
    for index, evidence in enumerate(evidence_items):
        if not isinstance(evidence, dict):
            continue
        region = evidence.get("region")
        bbox = evidence.get("bbox_norm")
        evidence_id = evidence.get("evidence_id")
        has_valid_bbox = (
            _valid_normalized_bbox(bbox)
            and bbox[0] >= target_bbox[0] - 1e-6
            and bbox[1] >= target_bbox[1] - 1e-6
            and bbox[2] <= target_bbox[2] + 1e-6
            and bbox[3] <= target_bbox[3] + 1e-6
        )
        # 只同步模型已经用完整证据记录明确表达的空间事实，不根据字段名猜测区域。
        if not (
            isinstance(region, str)
            and region
            and region != "whole_object"
            and region not in declared_regions
            and _complete_evidence_record(evidence)
            and has_valid_bbox
        ):
            continue
        visible_regions.append(region)
        declared_regions.add(region)
        _record_change(report, "/target_object/visible_regions")
        normalizations.append(
            {
                "source_pointer": f"/evidence/{index}/region",
                "evidence_id": evidence_id,
                "region": region,
                "action": "declared_from_valid_evidence",
            }
        )


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

    style_candidates: list[dict[str, Any]] = []
    for source_index, item in enumerate(style_observations.get("candidate_tags", [])):
        if not isinstance(item, dict):
            continue
        candidate = copy.deepcopy(item)
        candidate["_source_pointer"] = (
            f"/style_observations/candidate_tags/{source_index}"
        )
        style_candidates.append(candidate)

    expanded_evidence = []
    for source_index, item in enumerate(observation.get("evidence", [])):
        if not isinstance(item, dict):
            continue
        expanded = copy.deepcopy(item)
        expanded["_source_pointer"] = f"/evidence/{source_index}"
        expanded_evidence.append(expanded)

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
            "style_candidates": style_candidates,
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
        "novel_dna_elements": copy.deepcopy(
            observation.get("novel_dna_elements", [])
        ),
        "evidence": expanded_evidence,
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
    tags = data.get("style_result", {}).get("style_candidates", [])
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
    compiler_warnings = []
    if filtered_count:
        compiler_warnings.append(f"宿主按视角、Profile 或规范字段过滤了 {filtered_count} 项观察。")
    if normalized_count:
        compiler_warnings.append(f"宿主按受控值域确定性归一了 {normalized_count} 项字段。")
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
    for module_index, module in enumerate(
        modules if isinstance(modules, list) else []
    ):
        if not isinstance(module, dict):
            continue
        for element_index, element in enumerate(module.get("elements", [])):
            if not isinstance(element, dict):
                continue
            pointer = element.get("_source_pointer")
            if isinstance(pointer, str):
                mapping = {
                    "source_pointer": pointer,
                    "field_id": element.get("field_id"),
                    "region": element.get("region"),
                }
                source_map[f"design_element[{flat_index}]"] = mapping
                source_map[
                    "design_elements.extended_dna_modules."
                    f"{module_index}.elements.{element_index}"
                ] = copy.deepcopy(mapping)
            flat_index += 1

    style_result = data.get("style_result")
    if isinstance(style_result, dict):
        for collection_name in ("style_candidates",):
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
    evidence_items = data.get("evidence")
    for index, item in enumerate(
        evidence_items if isinstance(evidence_items, list) else []
    ):
        if not isinstance(item, dict):
            continue
        pointer = item.get("_source_pointer")
        if isinstance(pointer, str):
            source_map[f"evidence[{index}]"] = {
                "source_pointer": pointer,
                "evidence_id": item.get("evidence_id"),
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
    style_evidence_rules = _load_json(STYLE_EVIDENCE_RULES_PATH)
    tag_relations = _load_json(TAG_RELATIONS_PATH)
    normalization = _load_json(VALUE_NORMALIZATION_PATH)
    knowledge_base = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    fields = _field_records(field_registry)
    styles = _active_style_records(style_registry)
    module_names = _module_names(knowledge_base)
    value_spaces = _value_spaces(knowledge_base)
    source_contract = str(
        data.get("schema_version") or data.get("schemaVersion") or "unknown"
    )
    result = copy.deepcopy(data)
    report: dict[str, Any] = {
        "source_contract": source_contract,
        "target_schema_version": FINAL_SCHEMA_VERSION,
        "changed_paths": [],
    }
    if source_contract == OBSERVATION_SCHEMA_VERSION:
        from jsonschema import Draft202012Validator

        _normalize_observation_root_aliases(result, report)
        _fill_observation_descriptions(result, report)
        _synchronize_target_bbox(result, report)
        _synchronize_evidence_regions(result, report)
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
    else:
        _synchronize_target_bbox(result, report)
        _synchronize_evidence_regions(result, report)
    if "uncertain_fields" in result:
        # 兼容读取旧结果时可以接收 v1.1/v1.2，但重新编译后不再传播旧字段。
        result.pop("uncertain_fields", None)
        _record_change(report, "/uncertain_fields")
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
    _normalize_styles(
        result,
        styles,
        fields,
        style_evidence_rules,
        tag_relations,
        element_index,
        report,
    )
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
