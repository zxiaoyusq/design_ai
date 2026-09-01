#!/usr/bin/env python3
"""Validate design DNA JSON against Schema v4, registries, and semantic rules."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "design-dna-output.schema.json"
DEFAULT_KB = ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"
DEFAULT_STYLE_REGISTRY = ROOT / "references" / "style-registry.json"
DEFAULT_FIELD_REGISTRY = ROOT / "references" / "field-registry.json"

VALUE_TYPES = {"enum", "float", "integer", "boolean", "list", "object", "text", "multi_label"}
STYLE_STATUSES = {"active", "deprecated"}
MODULE_PATTERN = re.compile(r"^DNA-M(?:0[1-9]|1[0-5])$")
FIELD_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-[0-9]{2,3}$")
INLINE_FIELD_REF_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]*-[0-9]{2,3}\b")
LEGACY_DIMENSIONS = {"ID形态", "相机架构", "颜色", "材质工艺", "纹理图案", "设计细节"}
ACTIVE_PROFILES = {
    "core",
    "profile:device_controls",
    "profile:imaging_device",
    "profile:screen_device",
    "profile:handled_object",
    "profile:portable_object",
    "profile:contact_surface",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def iter_elements(data: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    design = data.get("design_elements", {})
    for dimension in design.get("original_md_dimensions", []):
        dimension_name = str(dimension.get("dimension") or "")
        for element in dimension.get("elements", []):
            yield "md_original", dimension_name, element
    for module in design.get("extended_dna_modules", []):
        module_id = str(module.get("module_id") or "")
        for element in module.get("elements", []):
            yield "md_extension", module_id, element


def collect_refs(data: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []

    def add(path: str, values: Any) -> None:
        if isinstance(values, list):
            refs.extend((path, value) for value in values if isinstance(value, str))

    style = data.get("style_result", {})
    primary = style.get("primary_style")
    if isinstance(primary, dict):
        add("style_result.primary_style.evidence_refs", primary.get("evidence_refs"))
        add(
            "style_result.primary_style.color_requirement.evidence_refs",
            primary.get("color_requirement", {}).get("evidence_refs"),
        )
    for i, item in enumerate(style.get("secondary_styles", [])):
        add(f"style_result.secondary_styles[{i}].evidence_refs", item.get("evidence_refs"))
        add(
            f"style_result.secondary_styles[{i}].color_requirement.evidence_refs",
            item.get("color_requirement", {}).get("evidence_refs"),
        )
    for i, (_, _, element) in enumerate(iter_elements(data)):
        add(f"design_element[{i}].evidence_refs", element.get("evidence_refs"))
    for i, item in enumerate(data.get("uncertain_fields", [])):
        for j, candidate in enumerate(item.get("candidate_values", [])):
            add(
                f"uncertain_fields[{i}].candidate_values[{j}].supporting_evidence_refs",
                candidate.get("supporting_evidence_refs"),
            )
            add(
                f"uncertain_fields[{i}].candidate_values[{j}].contradicting_evidence_refs",
                candidate.get("contradicting_evidence_refs"),
            )
    for i, item in enumerate(data.get("novel_dna_elements", [])):
        add(f"novel_dna_elements[{i}].evidence_refs", item.get("evidence_refs"))
    return refs


def norm_text(value: str) -> str:
    value = re.sub(r"^\s*[0-9]+[.、]\s*", "", value)
    return re.sub(r"[\s_\-—–|/（）()，,。.：:]+", "", value).lower()


def extract_kb_version(kb_text: str) -> str | None:
    match = re.search(r"知识库版本[^0-9]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", kb_text)
    return match.group(1) if match else None


def extract_style_color_roles(kb_text: str) -> dict[str, str]:
    """读取风格规则中的颜色角色，供语义校验约束 required 风格。"""
    rules = kb_text.split("## 活动风格规则", 1)[-1].split("# 设计元素与 DNA 规范字段", 1)[0]
    headings = list(re.finditer(r"^### ([A-Za-z0-9]+) — .+$", rules, re.M))
    roles: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(rules)
        section = rules[heading.end():end]
        match = re.search(r"^\| 颜色角色 \| (.*?) \|$", section, re.M)
        if match:
            roles[heading.group(1)] = re.split(r"[:：]", match.group(1), maxsplit=1)[0].strip()
    return roles


def extract_kb_value_spaces(kb_text: str) -> dict[str, tuple[str, set[str]]]:
    """从规范字段表读取 enum 与受控标签集合的机器值域。"""
    section = kb_text.split("## 四、规范字段定义", 1)[-1].split("## 五、别名、合并与派生", 1)[0]
    spaces: dict[str, tuple[str, set[str]]] = {}
    for match in re.finditer(
        r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| (.*?) \| .*? \| .*? \| .*? \|$",
        section,
        re.M,
    ):
        field_id, description = match.groups()
        type_match = re.search(r"；(enum|list|multi_label)(?:\s*/\s*(.*))?$", description)
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
        values = {item.strip() for item in raw_values.split("、") if item.strip()}
        if values:
            spaces[field_id] = (type_match.group(1), values)
    return spaces


def bbox_errors(path: str, bbox: Any) -> list[str]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return []  # JSON Schema reports shape/type.
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in bbox):
        return []
    x1, y1, x2, y2 = bbox
    errors: list[str] = []
    if not x1 < x2:
        errors.append(f"{path}: x_min must be < x_max")
    if not y1 < y2:
        errors.append(f"{path}: y_min must be < y_max")
    return errors


def bbox_contains(outer: Any, inner: Any, tolerance: float = 1e-6) -> bool:
    if not (
        isinstance(outer, list)
        and isinstance(inner, list)
        and len(outer) == 4
        and len(inner) == 4
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in outer + inner)
    ):
        return True  # JSON Schema or bbox_errors reports malformed boxes.
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def field_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("field_id") or ""),
        str(item.get("field_name") or ""),
        str(item.get("source_path") or ""),
        str(item.get("region") or ""),
    )


def value_matches(value_type: str, value: Any) -> bool:
    if value is None:
        return True
    if value_type in {"enum", "text"}:
        return isinstance(value, str)
    if value_type in {"float", "continuous"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "list":
        return isinstance(value, list)
    if value_type == "multi_label":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if value_type == "object":
        return isinstance(value, dict)
    return False


def validate_value_domain(
    path: str,
    record: dict[str, Any],
    value: Any,
    value_spaces: dict[str, tuple[str, set[str]]],
) -> list[str]:
    """执行知识库枚举、受控列表及常用数值单位的值域约束。"""
    if value is None:
        return []
    errors: list[str] = []
    field_id = str(record.get("field_id") or "")
    controlled = value_spaces.get(field_id)
    if controlled:
        controlled_type, allowed = controlled
        if controlled_type == "enum" and isinstance(value, str) and value not in allowed:
            errors.append(f"{path}: value {value!r} is outside the enum domain {sorted(allowed)}")
        if controlled_type in {"list", "multi_label"} and isinstance(value, list):
            invalid = sorted({item for item in value if isinstance(item, str) and item not in allowed})
            if invalid:
                errors.append(f"{path}: list values {invalid} are outside the controlled domain {sorted(allowed)}")

    unit = record.get("unit")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if unit == "normalized_ratio" and not 0 <= number <= 1:
            errors.append(f"{path}: normalized_ratio must be within 0..1")
        elif unit == "aspect_ratio" and number <= 0:
            errors.append(f"{path}: aspect_ratio must be > 0")
        elif unit == "count" and number < 0:
            errors.append(f"{path}: count must be >= 0")
        elif unit == "ordinal_0_25_50_75_100" and value not in {0, 25, 50, 75, 100}:
            errors.append(f"{path}: ordinal value must be one of 0, 25, 50, 75, 100")

    if unit == "OKLCH+hex+区域" and isinstance(value, dict):
        oklch = value.get("oklch")
        if isinstance(oklch, dict):
            l_value, c_value, h_value = oklch.get("l"), oklch.get("c"), oklch.get("h")
            if isinstance(l_value, (int, float)) and not isinstance(l_value, bool) and not 0 <= l_value <= 1:
                errors.append(f"{path}.oklch.l: must be within 0..1")
            if isinstance(c_value, (int, float)) and not isinstance(c_value, bool) and c_value < 0:
                errors.append(f"{path}.oklch.c: must be >= 0")
            if isinstance(h_value, (int, float)) and not isinstance(h_value, bool) and not 0 <= h_value < 360:
                errors.append(f"{path}.oklch.h: must be within 0..<360")
        hex_value = value.get("hex_approx")
        if isinstance(hex_value, str) and not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_value):
            errors.append(f"{path}.hex_approx: must be a six-digit hex color")
    if unit == "label+ordinal_strength" and isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item.get("label"):
                errors.append(f"{path}[{index}]: requires a non-empty label")
                continue
            if item.get("strength") not in {0, 25, 50, 75, 100}:
                errors.append(f"{path}[{index}].strength: must be one of 0, 25, 50, 75, 100")
    return errors


def view_requirement_satisfied(required_views: list[str], target_view: str) -> bool:
    """判断当前单图视角能否满足字段的候选视角集合。"""
    if "any" in required_views:
        return True
    normalized_view = "side" if target_view in {"left", "right"} else target_view
    return normalized_view in required_views


def validate_registries(
    style_registry: dict[str, Any],
    field_registry: dict[str, Any],
    kb_version: str | None,
) -> tuple[
    list[str],
    list[str],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, dict[str, Any]],
]:
    errors: list[str] = []
    warnings: list[str] = []
    for name, registry in (("style-registry", style_registry), ("field-registry", field_registry)):
        version = registry.get("knowledge_base_version")
        if version != kb_version:
            errors.append(f"{name}: knowledge_base_version={version!r}, expected {kb_version!r}")

    parent_items = style_registry.get("parents", [])
    parents: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(parent_items):
        parent_id = item.get("parent_style_id")
        if not isinstance(parent_id, str) or not parent_id:
            errors.append(f"style-registry.parents[{i}]: invalid parent_style_id")
            continue
        if parent_id in parents:
            errors.append(f"style-registry: duplicate parent_style_id {parent_id!r}")
        parents[parent_id] = item

    styles: dict[str, dict[str, Any]] = {}
    active_styles: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(style_registry.get("styles", [])):
        style_id = item.get("style_id")
        if not isinstance(style_id, str) or not style_id:
            errors.append(f"style-registry.styles[{i}]: invalid style_id")
            continue
        if style_id in styles:
            errors.append(f"style-registry: duplicate style_id {style_id!r}")
        styles[style_id] = item
        if item.get("parent_style_id") not in parents:
            errors.append(f"style-registry.styles[{i}]: unknown parent_style_id {item.get('parent_style_id')!r}")
        status = item.get("status")
        if status not in STYLE_STATUSES:
            errors.append(f"style-registry.styles[{i}]: invalid status {status!r}")
        if status == "active":
            active_styles[style_id] = item
        aliases = item.get("aliases")
        if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias for alias in aliases):
            errors.append(f"style-registry.styles[{i}]: aliases must be non-empty strings")

    for style_id, item in styles.items():
        replaced_by = item.get("replaced_by")
        if item.get("status") == "deprecated" and replaced_by not in active_styles:
            errors.append(f"style-registry: deprecated {style_id!r} must point to an active replaced_by")
        if item.get("status") == "active" and replaced_by is not None:
            errors.append(f"style-registry: active {style_id!r} must have replaced_by=null")
    if len(active_styles) != 31:
        errors.append(f"style-registry: expected 31 active styles, found {len(active_styles)}")

    fields: dict[str, dict[str, Any]] = {}
    alias_to_field: dict[str, str] = {}
    for i, item in enumerate(field_registry.get("fields", [])):
        field_id = item.get("field_id")
        if not isinstance(field_id, str) or not FIELD_ID_PATTERN.fullmatch(field_id):
            errors.append(f"field-registry.fields[{i}]: invalid field_id {field_id!r}")
            continue
        if field_id in fields:
            errors.append(f"field-registry: duplicate field_id {field_id!r}")
        fields[field_id] = item
        module_id = item.get("module_id")
        if not isinstance(module_id, str) or not MODULE_PATTERN.fullmatch(module_id):
            errors.append(f"field-registry.fields[{i}]: invalid module_id {module_id!r}")
        if item.get("value_type") not in VALUE_TYPES:
            errors.append(f"field-registry.fields[{i}]: invalid value_type {item.get('value_type')!r}")
        aliases = item.get("aliases")
        if not isinstance(aliases, list):
            errors.append(f"field-registry.fields[{i}]: aliases must be an array")
            aliases = []
        for alias in aliases:
            if isinstance(alias, str) and FIELD_ID_PATTERN.fullmatch(alias):
                if alias in alias_to_field and alias_to_field[alias] != field_id:
                    errors.append(f"field-registry: field ID alias {alias!r} maps to multiple fields")
                alias_to_field[alias] = field_id
    count = field_registry.get("canonical_field_count")
    if count != len(fields):
        errors.append(f"field-registry: canonical_field_count={count}, actual={len(fields)}")
    compatibility_policy = field_registry.get("compatibility_derived_policy")
    if compatibility_policy != {"decision_use": "none", "weight": 0}:
        errors.append("field-registry: compatibility_derived_policy must fix decision_use=none and weight=0")
    compatibility_derived = field_registry.get("compatibility_derived")
    if not isinstance(compatibility_derived, dict):
        errors.append("field-registry: compatibility_derived must be an object")
        compatibility_derived = {}
    for legacy_id, mapping in compatibility_derived.items():
        if not isinstance(legacy_id, str) or not FIELD_ID_PATTERN.fullmatch(legacy_id):
            errors.append(f"field-registry: invalid compatibility-derived ID {legacy_id!r}")
        if legacy_id in fields or legacy_id in alias_to_field:
            errors.append(f"field-registry: compatibility-derived ID {legacy_id!r} collides with canonical/alias")
        sources = mapping.get("source_field_ids") if isinstance(mapping, dict) else None
        if not isinstance(sources, list) or not sources or not all(source in fields for source in sources):
            errors.append(f"field-registry: compatibility-derived {legacy_id!r} has invalid canonical sources")
        if not isinstance(mapping, dict) or not isinstance(mapping.get("transform"), str) or not mapping.get("transform"):
            errors.append(f"field-registry: compatibility-derived {legacy_id!r} lacks transform")

    for style_id, item in active_styles.items():
        decisive = item.get("decisive_field_ids")
        auxiliary = item.get("auxiliary_field_ids")
        for key, values in (("decisive_field_ids", decisive), ("auxiliary_field_ids", auxiliary)):
            if not isinstance(values, list) or not values or len(values) != len(set(values)):
                errors.append(f"style-registry: {style_id}.{key} must be a non-empty unique array")
                continue
            unknown = sorted(set(values) - fields.keys())
            if unknown:
                errors.append(f"style-registry: {style_id}.{key} has unknown fields {unknown}")
            invalid_use = sorted(
                field_id
                for field_id in values
                if fields.get(field_id, {}).get("decision_use") not in {"hard", "support"}
            )
            if invalid_use:
                errors.append(f"style-registry: {style_id}.{key} has non-decision fields {invalid_use}")
        if isinstance(decisive, list) and not any(
            fields.get(field_id, {}).get("decision_use") == "hard" for field_id in decisive
        ):
            errors.append(f"style-registry: {style_id}.decisive_field_ids needs a hard field")
        if isinstance(decisive, list) and isinstance(auxiliary, list) and set(decisive) & set(auxiliary):
            errors.append(f"style-registry: {style_id} decisive/auxiliary field sets must be disjoint")
    return errors, warnings, active_styles, fields, alias_to_field, compatibility_derived


def validate_style_identity(
    path: str,
    item: dict[str, Any],
    active_styles: dict[str, dict[str, Any]],
    parents: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    style_id = item.get("style_id")
    record = active_styles.get(style_id)
    if record is None:
        return [f"{path}: unknown or inactive style_id {style_id!r}"]
    parent_id = item.get("parent_style_id")
    if parent_id != record.get("parent_style_id"):
        errors.append(
            f"{path}: parent_style_id={parent_id!r}, expected {record.get('parent_style_id')!r} for {style_id}"
        )
    label_en = record.get("display_name_en")
    label_zh = record.get("display_name_zh")
    if item.get("label_en") != label_en:
        errors.append(f"{path}: label_en={item.get('label_en')!r}, expected {label_en!r}")
    if item.get("label_zh") != label_zh:
        errors.append(f"{path}: label_zh={item.get('label_zh')!r}, expected {label_zh!r}")
    if set(item.get("aliases") or []) != set(record.get("aliases") or []):
        errors.append(f"{path}: aliases must match style registry")
    parent = parents.get(record.get("parent_style_id"), {})
    parent_display = str(parent.get("display_name") or "")
    if parent_display and norm_text(str(item.get("level_1") or "")) != norm_text(parent_display):
        errors.append(f"{path}: level_1 does not match parent display name {parent_display!r}")
    level2_norm = norm_text(str(item.get("level_2") or ""))
    canonical_labels = {
        norm_text(str(label)) for label in (label_en, label_zh) if isinstance(label, str) and label
    }
    if canonical_labels and not any(label in level2_norm for label in canonical_labels):
        errors.append(f"{path}: level_2 must contain a canonical display label")
    return errors


def validate_rule_coverage(path: str, assessment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    coverage = assessment.get("rule_coverage", {})
    applicable = coverage.get("applicable_rule_count")
    passed = coverage.get("passed_rule_count")
    failed = coverage.get("failed_rule_count")
    unknown = coverage.get("unknown_rule_count")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (applicable, passed, failed, unknown)):
        if applicable != passed + failed + unknown:
            errors.append(
                f"{path}.rule_coverage: applicable={applicable}, expected passed+failed+unknown={passed + failed + unknown}"
            )
    if assessment.get("hard_rule_passed"):
        if failed:
            errors.append(f"{path}: hard_rule_passed=true requires failed_rule_count=0")
        if assessment.get("missing_required_items"):
            errors.append(f"{path}: hard_rule_passed=true cannot contain missing_required_items")
        if assessment.get("exclusion_hits"):
            errors.append(f"{path}: hard_rule_passed=true cannot contain exclusion_hits")
        if assessment.get("color_requirement", {}).get("status") not in {"pass", "not_applicable"}:
            errors.append(f"{path}: hard_rule_passed=true requires color requirement pass/not_applicable")
    color = assessment.get("color_requirement", {})
    if color.get("status") == "pass" and not color.get("evidence_refs"):
        errors.append(f"{path}.color_requirement: pass requires evidence")
    return errors


def validate_style_feature_hits(
    path: str,
    assessment: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    alias_to_field: dict[str, str],
    usable_field_ids: set[str],
    field_evidence_ids: dict[str, set[str]],
    style_record: dict[str, Any],
) -> list[str]:
    """确保风格命中能追溯到本次已确认的规范 DNA，而不是自由文本断言。"""
    errors: list[str] = []
    assessment_evidence = set(assessment.get("evidence_refs") or [])
    hit_ids: dict[str, set[str]] = {"core_feature_hits": set(), "auxiliary_feature_hits": set()}
    for key in hit_ids:
        allowed_key = "decisive_field_ids" if key == "core_feature_hits" else "auxiliary_field_ids"
        allowed_ids = set(style_record.get(allowed_key) or [])
        for index, hit in enumerate(assessment.get(key, [])):
            refs = set(INLINE_FIELD_REF_PATTERN.findall(str(hit)))
            if not refs:
                errors.append(f"{path}.{key}[{index}]: must cite at least one canonical field_id")
                continue
            for field_id in refs:
                if field_id in alias_to_field:
                    errors.append(
                        f"{path}.{key}[{index}]: {field_id} is an alias; use {alias_to_field[field_id]}"
                    )
                elif field_id not in fields:
                    errors.append(f"{path}.{key}[{index}]: unknown field_id {field_id}")
                elif field_id not in usable_field_ids:
                    errors.append(f"{path}.{key}[{index}]: {field_id} has no observed/computed value in this result")
                elif field_id not in allowed_ids:
                    errors.append(
                        f"{path}.{key}[{index}]: {field_id} is not allowed by this style's {allowed_key}"
                    )
                elif not assessment_evidence.intersection(field_evidence_ids.get(field_id, set())):
                    errors.append(
                        f"{path}.{key}[{index}]: evidence_refs do not include evidence for {field_id}"
                    )
            hit_ids[key].update(refs)
    core_ids = hit_ids["core_feature_hits"]
    auxiliary_ids = hit_ids["auxiliary_feature_hits"]
    if assessment.get("hard_rule_passed") and core_ids and not any(
        fields.get(field_id, {}).get("decision_use") == "hard" for field_id in core_ids
    ):
        errors.append(f"{path}.core_feature_hits: passed hard rule requires a hard-decision field")
    if core_ids and auxiliary_ids and not auxiliary_ids.difference(core_ids):
        errors.append(f"{path}.auxiliary_feature_hits: requires at least one field independent from core hits")
    return errors


def validate_semantics(
    data: dict[str, Any],
    kb_text: str,
    style_registry: dict[str, Any],
    field_registry: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    kb_version = extract_kb_version(kb_text)
    if kb_version is None:
        errors.append("knowledge base: cannot parse version")
    if data.get("knowledge_base_version") != kb_version:
        errors.append(
            f"knowledge_base_version={data.get('knowledge_base_version')!r}, expected {kb_version!r} from knowledge base"
        )
    registry_errors, registry_warnings, active_styles, fields, alias_to_field, compatibility_derived = validate_registries(
        style_registry, field_registry, kb_version
    )
    errors.extend(registry_errors)
    warnings.extend(registry_warnings)
    parents = {
        item.get("parent_style_id"): item
        for item in style_registry.get("parents", [])
        if isinstance(item, dict) and isinstance(item.get("parent_style_id"), str)
    }
    color_roles = extract_style_color_roles(kb_text)
    value_spaces = extract_kb_value_spaces(kb_text)

    target_bbox = data.get("target_object", {}).get("bbox_norm")
    target_view = str(data.get("target_object", {}).get("view") or "unknown")
    errors += bbox_errors("target_object.bbox_norm", target_bbox)
    evidence_list = data.get("evidence", [])
    evidence_ids = [item.get("evidence_id") for item in evidence_list if isinstance(item, dict)]
    duplicate_evidence = sorted({item for item in evidence_ids if evidence_ids.count(item) > 1})
    if duplicate_evidence:
        errors.append(f"duplicate evidence_id values: {duplicate_evidence}")
    evidence_set = set(evidence_ids)
    for i, evidence in enumerate(evidence_list):
        bbox = evidence.get("bbox_norm")
        errors += bbox_errors(f"evidence[{i}].bbox_norm", bbox)
        if not bbox_contains(target_bbox, bbox):
            errors.append(f"evidence[{i}].bbox_norm: evidence box must be inside target_object.bbox_norm")
    for path, ref in collect_refs(data):
        if ref not in evidence_set:
            errors.append(f"{path}: unresolved evidence reference {ref!r}")

    module_info = data.get("module_applicability", {})
    active_profiles = module_info.get("active_profiles", [])
    active_profile_set = {item for item in active_profiles if isinstance(item, str)}
    if active_profile_set - ACTIVE_PROFILES:
        errors.append(
            f"module_applicability.active_profiles: unsupported profiles {sorted(active_profile_set - ACTIVE_PROFILES)}"
        )
    if "core" not in active_profile_set:
        errors.append("module_applicability.active_profiles: core is required")
    applicable_ids = [item.get("module_id") for item in module_info.get("applicable_modules", [])]
    excluded_ids = [item.get("module_id") for item in module_info.get("excluded_modules", [])]
    for label, values in (("applicable_modules", applicable_ids), ("excluded_modules", excluded_ids)):
        duplicates = sorted({item for item in values if values.count(item) > 1})
        if duplicates:
            errors.append(f"module_applicability.{label}: duplicate module IDs {duplicates}")
    overlap = sorted(set(applicable_ids) & set(excluded_ids))
    if overlap:
        errors.append(f"module_applicability: modules cannot be both applicable and excluded: {overlap}")
    canonical_module_ids = {str(item.get("module_id")) for item in fields.values()}
    valid_module_ids = canonical_module_ids | LEGACY_DIMENSIONS
    for label, values in (("applicable_modules", applicable_ids), ("excluded_modules", excluded_ids)):
        unknown_modules = sorted({item for item in values if item not in valid_module_ids})
        if unknown_modules:
            errors.append(f"module_applicability.{label}: unknown module IDs {unknown_modules}")
    if "DNA-M15" in applicable_ids:
        errors.append(
            "module_applicability: DNA-M15 is reserved for reference/trend extensions and is not applicable in this single-image Skill"
        )
    m15_records = [
        item for item in module_info.get("excluded_modules", []) if item.get("module_id") == "DNA-M15"
    ]
    if not m15_records or m15_records[0].get("reason") != "profile_not_applicable":
        errors.append("module_applicability: DNA-M15 must be excluded with reason=profile_not_applicable")
    module_profiles: dict[str, set[str]] = {}
    for record in fields.values():
        module_profiles.setdefault(str(record.get("module_id") or ""), set()).update(
            profile for profile in record.get("applicability", []) if isinstance(profile, str)
        )
    for module_id in applicable_ids:
        profiles = module_profiles.get(str(module_id), set())
        if profiles and "core" not in profiles and not profiles.intersection(active_profile_set):
            errors.append(
                f"module_applicability: {module_id} requires one of active profiles {sorted(profiles)}"
            )

    extended_modules = data.get("design_elements", {}).get("extended_dna_modules", [])
    used_module_ids = [item.get("module_id") for item in extended_modules]
    duplicates = sorted({item for item in used_module_ids if used_module_ids.count(item) > 1})
    if duplicates:
        errors.append(f"design_elements.extended_dna_modules: duplicate module IDs {duplicates}")
    for module_id in used_module_ids:
        if module_id not in applicable_ids:
            errors.append(f"design_elements: used module {module_id!r} is not listed as applicable")
        if module_id in excluded_ids:
            errors.append(f"design_elements: used module {module_id!r} is also excluded")
    dimensions = data.get("design_elements", {}).get("original_md_dimensions", [])
    if dimensions:
        errors.append("design_elements.original_md_dimensions: current extractor must output []")
    dimension_names = [item.get("dimension") for item in dimensions]
    duplicate_dimensions = sorted({item for item in dimension_names if dimension_names.count(item) > 1})
    if duplicate_dimensions:
        errors.append(f"design_elements.original_md_dimensions: duplicate dimensions {duplicate_dimensions}")
    for dimension in dimension_names:
        if dimension not in applicable_ids:
            errors.append(f"design_elements: used dimension {dimension!r} is not listed as applicable")

    uncertainty_items = data.get("uncertain_fields", [])
    uncertainty_key_list = [field_key(item) for item in uncertainty_items]
    duplicate_uncertainty = sorted({key for key in uncertainty_key_list if uncertainty_key_list.count(key) > 1})
    if duplicate_uncertainty:
        errors.append(f"uncertain_fields: duplicate field/region records {duplicate_uncertainty}")
    uncertainty_keys = set(uncertainty_key_list)
    element_keys: set[tuple[str, str, str, str]] = set()
    element_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    confidences: list[float] = []
    low_count = 0
    canonical_elements: dict[tuple[str, str], dict[str, Any]] = {}
    for i, (schema_source, container_id, element) in enumerate(iter_elements(data)):
        if element.get("schema_source") != schema_source:
            errors.append(
                f"design_element[{i}]: schema_source={element.get('schema_source')!r}, expected {schema_source!r}"
            )
        key4 = field_key(element)
        if key4 in element_keys:
            errors.append(f"design_element[{i}]: duplicate field/region {key4}")
        element_keys.add(key4)
        element_by_key[key4] = element
        observability = element.get("observability")
        computation_status = element.get("computation_status")
        evidence_mode = element.get("evidence_mode")
        refs = element.get("evidence_refs") or []
        value = element.get("value")
        if element.get("applicability_status") != "applicable":
            errors.append(f"design_element[{i}]: design_elements only accepts applicable fields")
        unavailable = False
        if evidence_mode == "direct":
            if computation_status != "not_requested":
                errors.append(f"design_element[{i}]: direct field requires computation_status=not_requested")
            if observability == "observed":
                if value is None or not refs:
                    errors.append(f"design_element[{i}]: observed direct field requires value and evidence")
            else:
                unavailable = True
                if value is not None:
                    errors.append(f"design_element[{i}]: unavailable direct field must have null value")
        elif evidence_mode in {"derived", "inferred", "reference_computed"}:
            if computation_status not in {"computed", "not_computable"}:
                errors.append(
                    f"design_element[{i}]: {evidence_mode} field requires computed/not_computable"
                )
            if computation_status == "computed":
                if observability != "observed":
                    errors.append(
                        f"design_element[{i}]: computed {evidence_mode} field requires observability=observed"
                    )
                minimum_refs = 2 if evidence_mode == "inferred" else 1
                if value is None or len(refs) < minimum_refs:
                    errors.append(
                        f"design_element[{i}]: computed {evidence_mode} field requires value and {minimum_refs}+ evidence refs"
                    )
            else:
                unavailable = True
                if value is not None:
                    errors.append(f"design_element[{i}]: uncomputed field must have null value")
        value_type = element.get("value_type")
        if isinstance(value_type, str) and not value_matches(value_type, value):
            errors.append(f"design_element[{i}]: value does not match value_type={value_type!r}")
        confidence = element.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            confidences.append(float(confidence))
            if confidence < 0.75:
                low_count += 1
                if field_key(element) not in uncertainty_keys:
                    errors.append(
                        f"design_element[{i}]: confidence {confidence:.2f} < 0.75 but no matching uncertain_fields record"
                    )
            if confidence < 0.30:
                has_definite_value = (
                    evidence_mode == "direct" and observability == "observed"
                ) or (
                    evidence_mode != "direct" and computation_status == "computed"
                )
                if has_definite_value:
                    errors.append(
                        f"design_element[{i}]: confidence below 0.30 cannot carry a definite value"
                    )
        if unavailable and field_key(element) not in uncertainty_keys:
            errors.append(f"design_element[{i}]: unavailable field requires uncertain_fields record")

        if schema_source == "md_extension":
            field_id = element.get("field_id")
            if field_id in alias_to_field:
                errors.append(
                    f"design_element[{i}]: field_id {field_id!r} is an alias; use canonical {alias_to_field[field_id]!r}"
                )
            if field_id in compatibility_derived:
                sources = compatibility_derived[field_id].get("source_field_ids", [])
                errors.append(
                    f"design_element[{i}]: field_id {field_id!r} is compatibility-derived; use canonical sources {sources}"
                )
            record = fields.get(field_id)
            if record is None:
                errors.append(f"design_element[{i}]: unknown canonical field_id {field_id!r}")
            else:
                expected_source_path = f"{container_id}/{field_id}"
                if element.get("source_path") != expected_source_path:
                    errors.append(
                        f"design_element[{i}]: source_path={element.get('source_path')!r}, "
                        f"expected {expected_source_path!r}"
                    )
                if record.get("module_id") != container_id:
                    errors.append(
                        f"design_element[{i}]: field {field_id} belongs to {record.get('module_id')}, not {container_id}"
                    )
                if record.get("value_type") != value_type:
                    errors.append(
                        f"design_element[{i}]: value_type={value_type!r}, registry expects {record.get('value_type')!r}"
                    )
                required_profiles = set(record.get("applicability") or [])
                if not required_profiles.intersection(active_profile_set):
                    errors.append(
                        f"design_element[{i}]: {field_id} requires active profile in {sorted(required_profiles)}"
                    )
                definite_value = (
                    evidence_mode == "direct" and observability == "observed"
                ) or (
                    evidence_mode != "direct" and computation_status == "computed"
                )
                required_views = record.get("required_views") or []
                if definite_value and not view_requirement_satisfied(required_views, target_view):
                    errors.append(
                        f"design_element[{i}]: {field_id} requires view in {required_views}, got {target_view!r}"
                    )
                errors.extend(validate_value_domain(f"design_element[{i}].value", record, value, value_spaces))
                valid_names = {norm_text(str(record.get("name") or ""))}
                valid_names.update(norm_text(str(alias)) for alias in record.get("aliases", []) if isinstance(alias, str))
                if norm_text(str(element.get("field_name") or "")) not in valid_names:
                    errors.append(f"design_element[{i}]: field_name does not match field registry for {field_id}")
                registry_mode = record.get("evidence_mode")
                if evidence_mode != registry_mode:
                    errors.append(
                        f"design_element[{i}]: evidence_mode={evidence_mode!r}, registry expects {registry_mode!r}"
                    )
                if registry_mode == "reference_computed" and computation_status != "not_computable":
                    errors.append(
                        f"design_element[{i}]: {field_id} needs a reference set and must be not_computable in this single-image run"
                    )
                canonical_key = (str(field_id), str(element.get("region") or ""))
                if canonical_key in canonical_elements:
                    errors.append(f"design_element[{i}]: duplicate canonical field/region {canonical_key}")
                canonical_elements[canonical_key] = element
        else:
            if evidence_mode != "derived":
                errors.append(f"design_element[{i}]: legacy aliases must use evidence_mode='derived'")
            if not str(element.get("source_path") or "").startswith("legacy_alias/"):
                errors.append(f"design_element[{i}]: legacy alias source_path must start with 'legacy_alias/'")

    def is_usable_source(element: dict[str, Any]) -> bool:
        if element.get("value") is None or element.get("observability") != "observed":
            return False
        if element.get("evidence_mode") == "direct":
            return element.get("computation_status") == "not_requested"
        return element.get("computation_status") == "computed"

    def is_whole_object_region(region: str) -> bool:
        return region == "whole_object" or region.startswith("whole_object_")

    # 派生值必须能回溯到注册表声明的全部规范源字段及其原始证据。
    for (field_id, region), element in canonical_elements.items():
        record = fields.get(field_id, {})
        if record.get("evidence_mode") != "derived" or element.get("computation_status") != "computed":
            continue
        dependencies = [item for item in record.get("derived_from", []) if item in fields]
        if not dependencies:
            continue
        source_evidence: set[str] = set()
        missing_sources: list[str] = []
        for dependency in dependencies:
            candidates = [
                (source_region, source)
                for (source_id, source_region), source in canonical_elements.items()
                if source_id == dependency
                and is_usable_source(source)
                and (
                    source_region == region
                    or is_whole_object_region(source_region)
                    or is_whole_object_region(region)
                )
            ]
            if not candidates:
                missing_sources.append(dependency)
                continue
            candidates.sort(
                key=lambda item: (
                    item[0] != region,
                    not is_whole_object_region(item[0]),
                )
            )
            source_evidence.update(candidates[0][1].get("evidence_refs") or [])
        if missing_sources:
            errors.append(
                f"design_element[{field_id}@{region}]: missing usable derived sources {missing_sources}"
            )
        missing_evidence = sorted(source_evidence - set(element.get("evidence_refs") or []))
        if missing_evidence:
            errors.append(
                f"design_element[{field_id}@{region}]: derived evidence_refs must include source evidence {missing_evidence}"
            )

    reported_low = data.get("quality_summary", {}).get("low_confidence_field_count")
    if isinstance(reported_low, int) and reported_low != low_count:
        errors.append(
            f"quality_summary.low_confidence_field_count={reported_low}, expected {low_count} from extracted fields"
        )
    reported_mean = data.get("quality_summary", {}).get("mean_confidence")
    expected_mean = sum(confidences) / len(confidences) if confidences else 0.0
    if isinstance(reported_mean, (int, float)) and abs(float(reported_mean) - expected_mean) > 0.011:
        errors.append(
            f"quality_summary.mean_confidence={reported_mean}, expected about {expected_mean:.3f} from extracted fields"
        )

    for i, item in enumerate(uncertainty_items):
        key4 = field_key(item)
        matching_element = element_by_key.get(key4)
        if matching_element is None:
            errors.append(f"uncertain_fields[{i}]: must match a design_elements field and region")
        else:
            for key in (
                "evidence_mode",
                "applicability_status",
                "observability",
                "computation_status",
                "confidence",
            ):
                if item.get(key) != matching_element.get(key):
                    errors.append(f"uncertain_fields[{i}].{key}: must match design_elements")
        field_id = item.get("field_id")
        if field_id in alias_to_field:
            errors.append(
                f"uncertain_fields[{i}]: field_id {field_id!r} is an alias; use {alias_to_field[field_id]!r}"
            )
        if field_id in compatibility_derived:
            errors.append(f"uncertain_fields[{i}]: field_id {field_id!r} is compatibility-derived, not canonical")
        record = fields.get(field_id)
        if record is None:
            errors.append(f"uncertain_fields[{i}]: unknown canonical field_id {field_id!r}")
        elif item.get("evidence_mode") != record.get("evidence_mode"):
            errors.append(f"uncertain_fields[{i}]: evidence_mode differs from field registry")
        if record is not None:
            errors.extend(
                validate_value_domain(
                    f"uncertain_fields[{i}].best_estimate",
                    record,
                    item.get("best_estimate"),
                    value_spaces,
                )
            )
            controlled = value_spaces.get(str(field_id))
            if controlled and controlled[0] == "enum":
                allowed = controlled[1]
                for candidate_index, candidate in enumerate(item.get("candidate_values", [])):
                    candidate_value = candidate.get("value")
                    if isinstance(candidate_value, str) and candidate_value not in allowed:
                        errors.append(
                            f"uncertain_fields[{i}].candidate_values[{candidate_index}]: "
                            f"value {candidate_value!r} is outside the enum domain"
                        )
        if item.get("evidence_mode") == "direct" and item.get("computation_status") != "not_requested":
            errors.append(f"uncertain_fields[{i}]: direct field requires computation_status=not_requested")
        if item.get("evidence_mode") != "direct" and item.get("computation_status") not in {
            "computed",
            "not_computable",
        }:
            errors.append(f"uncertain_fields[{i}]: non-direct field requires computed/not_computable")
        if (
            item.get("evidence_mode") != "direct"
            and item.get("computation_status") == "computed"
            and item.get("observability") != "observed"
        ):
            errors.append(f"uncertain_fields[{i}]: computed non-direct field requires observability=observed")
        candidates = item.get("candidate_values", [])
        if candidates:
            probabilities = [candidate.get("probability") for candidate in candidates]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in probabilities):
                total = sum(probabilities)
                if not 0.97 <= total <= 1.03:
                    errors.append(
                        f"uncertain_fields[{i}]: candidate probabilities sum to {total:.4f}, expected about 1"
                    )
        if item.get("computation_status") == "not_computable" and item.get("reason_type") not in {
            "missing_reference",
            "not_computable",
        }:
            errors.append(
                f"uncertain_fields[{i}]: not_computable requires reason_type missing_reference/not_computable"
            )
        unavailable = (
            item.get("evidence_mode") == "direct" and item.get("observability") != "observed"
        ) or (
            item.get("evidence_mode") != "direct" and item.get("computation_status") != "computed"
        )
        if unavailable and item.get("best_estimate") is not None:
            errors.append(f"uncertain_fields[{i}]: unavailable field requires best_estimate=null")

    style_result = data.get("style_result", {})
    status = style_result.get("classification_status")
    primary = style_result.get("primary_style")
    secondaries = [item for item in style_result.get("secondary_styles", []) if isinstance(item, dict)]
    candidates = [item for item in style_result.get("candidate_ranking", []) if isinstance(item, dict)]
    if status == "unclassified":
        if primary is not None:
            errors.append("style_result: unclassified requires primary_style=null")
        if secondaries:
            errors.append("style_result: unclassified requires secondary_styles=[]")
    if status in {"confirmed", "provisional"} and not isinstance(primary, dict):
        errors.append(f"style_result: {status} requires a primary_style object")

    assessments: list[tuple[str, dict[str, Any]]] = []
    if isinstance(primary, dict):
        assessments.append(("style_result.primary_style", primary))
    assessments.extend((f"style_result.secondary_styles[{i}]", item) for i, item in enumerate(secondaries))
    assessments.extend((f"style_result.candidate_ranking[{i}]", item) for i, item in enumerate(candidates))
    for path, item in assessments:
        errors.extend(validate_style_identity(path, item, active_styles, parents))
    usable_field_ids = {
        str(element.get("field_id"))
        for element in canonical_elements.values()
        if element.get("value") is not None
        and (
            (element.get("evidence_mode") == "direct" and element.get("observability") == "observed")
            or (element.get("evidence_mode") != "direct" and element.get("computation_status") == "computed")
        )
    }
    field_evidence_ids: dict[str, set[str]] = {}
    for element in canonical_elements.values():
        field_id = str(element.get("field_id") or "")
        field_evidence_ids.setdefault(field_id, set()).update(element.get("evidence_refs") or [])
    style_assessments: list[tuple[str, dict[str, Any]]] = []
    if isinstance(primary, dict):
        style_assessments.append(("style_result.primary_style", primary))
    style_assessments.extend((f"style_result.secondary_styles[{i}]", item) for i, item in enumerate(secondaries))
    for path, item in style_assessments:
        style_id = str(item.get("style_id") or "")
        if color_roles.get(style_id) == "required" and item.get("color_requirement", {}).get("status") == "not_applicable":
            errors.append(f"{path}.color_requirement: required color role cannot be not_applicable")
        errors.extend(
            validate_style_feature_hits(
                path,
                item,
                fields,
                alias_to_field,
                usable_field_ids,
                field_evidence_ids,
                active_styles.get(style_id, {}),
            )
        )
    if isinstance(primary, dict):
        errors.extend(validate_rule_coverage("style_result.primary_style", primary))
        if status == "confirmed":
            coverage = primary.get("rule_coverage", {})
            if coverage.get("failed_rule_count") != 0 or coverage.get("unknown_rule_count") != 0:
                errors.append("style_result.primary_style: confirmed requires zero failed and unknown rules")
            if not primary.get("core_feature_hits") or not primary.get("auxiliary_feature_hits"):
                errors.append("style_result.primary_style: confirmed requires a decisive anchor and independent support")
            if len(primary.get("evidence_refs") or []) < 2:
                errors.append("style_result.primary_style: confirmed requires at least two evidence refs")
            if not str(primary.get("conflict_arbitration") or "").strip():
                errors.append("style_result.primary_style: confirmed requires conflict_arbitration")
            else:
                record = active_styles.get(primary.get("style_id"), {})
                groups = record.get("confusion_groups") or []
                arbitration = str(primary.get("conflict_arbitration"))
                if groups and not any(group in arbitration for group in groups):
                    errors.append(
                        "style_result.primary_style: conflict_arbitration must cite an applicable CG group"
                    )
    primary_refs = set(primary.get("evidence_refs") or []) if isinstance(primary, dict) else set()
    seen_secondary: set[str] = set()
    for i, item in enumerate(secondaries):
        path = f"style_result.secondary_styles[{i}]"
        errors.extend(validate_rule_coverage(path, item))
        style_id = str(item.get("style_id") or "")
        if style_id in seen_secondary or (isinstance(primary, dict) and style_id == primary.get("style_id")):
            errors.append(f"{path}: duplicate primary/secondary style_id {style_id!r}")
        seen_secondary.add(style_id)
        if not item.get("hard_rule_passed") or item.get("missing_required_items") or item.get("exclusion_hits"):
            errors.append(f"{path}: secondary style must pass hard rules without missing or exclusion hits")
        if not item.get("core_feature_hits") or not item.get("auxiliary_feature_hits"):
            errors.append(f"{path}: secondary style requires a decisive anchor and independent support")
        arbitration = str(item.get("conflict_arbitration") or "")
        groups = active_styles.get(style_id, {}).get("confusion_groups") or []
        if not arbitration or (groups and not any(group in arbitration for group in groups)):
            errors.append(f"{path}: secondary style requires arbitration citing an applicable CG group")
        refs = set(item.get("evidence_refs") or [])
        if not refs or not refs.difference(primary_refs):
            errors.append(f"{path}: secondary style requires evidence independent from primary style")

    ranks = [item.get("rank") for item in candidates]
    if ranks != list(range(1, len(candidates) + 1)):
        errors.append(f"style_result.candidate_ranking: ranks must be consecutive from 1, got {ranks}")
    candidate_ids = [item.get("style_id") for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("style_result.candidate_ranking: style_id values must be unique")
    scores = [item.get("match_score") for item in candidates]
    if all(isinstance(value, (int, float)) for value in scores):
        if any(scores[i] < scores[i + 1] for i in range(len(scores) - 1)):
            errors.append("style_result.candidate_ranking: match_score must be non-increasing")
    if isinstance(primary, dict):
        if not candidates:
            errors.append("style_result: classified result requires candidate_ranking")
        elif candidates[0].get("style_id") != primary.get("style_id"):
            errors.append("style_result.candidate_ranking[0] must match primary_style")
        else:
            for key in ("match_score", "confidence", "hard_rule_passed"):
                if candidates[0].get(key) != primary.get(key):
                    errors.append(f"style_result.candidate_ranking[0].{key} must equal primary_style.{key}")

    style_confidence = data.get("quality_summary", {}).get("style_confidence")
    expected_style_confidence = primary.get("confidence") if isinstance(primary, dict) else 0
    if isinstance(style_confidence, (int, float)) and style_confidence != expected_style_confidence:
        errors.append(
            f"quality_summary.style_confidence={style_confidence}, expected {expected_style_confidence}"
        )

    temp_ids = [item.get("temp_id") for item in data.get("novel_dna_elements", []) if isinstance(item, dict)]
    if len(temp_ids) != len(set(temp_ids)):
        errors.append("novel_dna_elements: temp_id values must be unique")
    known_names = {norm_text(str(item.get("name") or "")) for item in fields.values()}
    known_names.update(
        norm_text(str(alias))
        for item in fields.values()
        for alias in item.get("aliases", [])
        if isinstance(alias, str) and not FIELD_ID_PATTERN.fullmatch(alias)
    )
    known_modules = {str(item.get("module_id")) for item in fields.values()}
    for i, item in enumerate(data.get("novel_dna_elements", [])):
        path = f"novel_dna_elements[{i}]"
        novelty_type = item.get("novelty_type")
        module_id = item.get("proposed_module_id")
        existing_field_id = item.get("existing_field_id")
        proposed_name = norm_text(str(item.get("proposed_field_name") or ""))
        if novelty_type == "new_module":
            if module_id is not None:
                errors.append(f"{path}: new_module requires proposed_module_id=null")
        else:
            if module_id not in known_modules:
                errors.append(f"{path}: {novelty_type} requires an existing proposed_module_id")
        if novelty_type == "new_field" and proposed_name in known_names:
            errors.append(f"{path}: proposed field already exists; use existing canonical field")
        if novelty_type == "new_enum_value":
            if existing_field_id in alias_to_field:
                errors.append(
                    f"{path}: existing_field_id is an alias; use {alias_to_field[existing_field_id]!r}"
                )
            if existing_field_id in compatibility_derived:
                errors.append(f"{path}: existing_field_id must not be compatibility-derived")
            record = fields.get(existing_field_id)
            if record is None:
                errors.append(f"{path}: new_enum_value requires a canonical existing_field_id")
            else:
                if record.get("module_id") != module_id:
                    errors.append(
                        f"{path}: proposed_module_id must match existing field module {record.get('module_id')!r}"
                    )
                if record.get("value_type") != "enum" or item.get("recommended_value_type") != "enum":
                    errors.append(f"{path}: new_enum_value requires an existing enum field and enum value type")
                current_space = value_spaces.get(str(existing_field_id), ("", set()))[1]
                if item.get("observed_value") in current_space:
                    errors.append(f"{path}: observed_value already exists in the canonical enum domain")
        elif existing_field_id is not None:
            errors.append(f"{path}: existing_field_id is only valid for new_enum_value")
        if not value_matches(str(item.get("recommended_value_type") or ""), item.get("observed_value")):
            errors.append(f"{path}: observed_value does not match recommended_value_type")
        if not item.get("evidence_refs"):
            errors.append(f"{path}: new DNA requires at least one evidence ref")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="Path to model output JSON")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--knowledge-base", type=Path, default=DEFAULT_KB)
    parser.add_argument("--style-registry", type=Path, default=DEFAULT_STYLE_REGISTRY)
    parser.add_argument("--field-registry", type=Path, default=DEFAULT_FIELD_REGISTRY)
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()

    data = load_json(args.result)
    schema = load_json(args.schema)
    style_registry = load_json(args.style_registry)
    field_registry = load_json(args.field_registry)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("ERROR: jsonschema is required. Install with: python -m pip install jsonschema>=4.21", file=sys.stderr)
        return 2

    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.absolute_path)
    )
    errors: list[str] = []
    for error in schema_errors:
        path = ".".join(str(item) for item in error.absolute_path) or "$"
        errors.append(f"schema {path}: {error.message}")

    kb_text = args.knowledge_base.read_text(encoding="utf-8")
    semantic_errors, warnings = validate_semantics(data, kb_text, style_registry, field_registry)
    errors.extend(semantic_errors)

    if errors:
        print(f"INVALID: {len(errors)} error(s)")
        for item in errors:
            print(f"  ERROR: {item}")
    else:
        print("VALID: schema, registries, and semantic checks passed")
    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        for item in warnings:
            print(f"  WARNING: {item}")
    if errors or (warnings and args.warnings_as_errors):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
