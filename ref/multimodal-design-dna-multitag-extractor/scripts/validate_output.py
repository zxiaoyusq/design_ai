#!/usr/bin/env python3
"""Validate multi-tag design DNA JSON against its schema, registries, and relation rules."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from derive_style_presets import compute_derived_style_presets

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "design-dna-output.schema.json"
DEFAULT_KB = ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"
DEFAULT_STYLE_REGISTRY = ROOT / "references" / "style-registry.json"
DEFAULT_FIELD_REGISTRY = ROOT / "references" / "field-registry.json"
DEFAULT_TAG_RELATIONS = ROOT / "references" / "tag-relations.json"
DEFAULT_COMBINATION_PRESETS = ROOT / "references" / "style-combination-presets.json"

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


def reject_nonfinite_constant(value: str) -> Any:
    """标准 JSON 不允许 NaN/Infinity；Python 默认解析器需要显式拒绝。"""
    raise ValueError(f"non-finite numeric constant {value!r} is not valid JSON")


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_nonfinite_constant,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except ValueError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}") from exc


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
    for i, item in enumerate(style.get("style_tags", [])):
        add(f"style_result.style_tags[{i}].evidence_refs", item.get("evidence_refs"))
        add(
            f"style_result.style_tags[{i}].color_requirement.evidence_refs",
            item.get("color_requirement", {}).get("evidence_refs"),
        )
    for i, item in enumerate(style.get("pairwise_arbitrations", [])):
        add(f"style_result.pairwise_arbitrations[{i}].evidence_refs", item.get("evidence_refs"))
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

    if "parents" in style_registry:
        errors.append("style-registry: flat ontology forbids the legacy parents collection")

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
        if "parent_style_id" in item:
            errors.append(f"style-registry.styles[{i}]: flat ontology forbids parent_style_id")
        status = item.get("status")
        if status not in STYLE_STATUSES:
            errors.append(f"style-registry.styles[{i}]: invalid status {status!r}")
        if status == "active":
            active_styles[style_id] = item
        aliases = item.get("aliases")
        if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias for alias in aliases):
            errors.append(f"style-registry.styles[{i}]: aliases must be non-empty strings")
        similarity_weight = item.get("similarity_weight")
        if (
            not isinstance(similarity_weight, (int, float))
            or isinstance(similarity_weight, bool)
            or not 0 <= similarity_weight <= 1
        ):
            errors.append(f"style-registry.styles[{i}]: similarity_weight must be within 0..1")
        tag_kind = item.get("tag_kind")
        expected_weight = 1 if tag_kind == "atomic" else 0 if tag_kind in {"composite", "identity"} else None
        if expected_weight is not None and similarity_weight != expected_weight:
            errors.append(
                f"style-registry.styles[{i}]: tag_kind={tag_kind!r} requires "
                f"similarity_weight={expected_weight}"
            )

    if len(active_styles) != 38:
        errors.append(f"style-registry: expected 38 active styles, found {len(active_styles)}")

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

    # 弃用风格只能迁移到一个活动风格，或迁移为一组规范字段；两条路径严格互斥。
    for style_id, item in styles.items():
        replaced_by = item.get("replaced_by")
        replacement_field_ids = item.get("replacement_field_ids")
        has_style_replacement = isinstance(replaced_by, str) and bool(replaced_by)
        has_field_replacement = (
            isinstance(replacement_field_ids, list) and bool(replacement_field_ids)
        )
        if item.get("status") == "active":
            if replaced_by is not None:
                errors.append(f"style-registry: active {style_id!r} must have replaced_by=null")
            if replacement_field_ids is not None:
                errors.append(
                    f"style-registry: active {style_id!r} must not have replacement_field_ids"
                )
            continue
        if item.get("status") != "deprecated":
            continue
        if has_style_replacement == has_field_replacement:
            errors.append(
                f"style-registry: deprecated {style_id!r} requires exactly one migration path: "
                "active replaced_by or non-empty replacement_field_ids"
            )
        if has_style_replacement and replaced_by not in active_styles:
            errors.append(
                f"style-registry: deprecated {style_id!r} replaced_by must reference an active style"
            )
        if has_style_replacement and replacement_field_ids is not None:
            errors.append(
                f"style-registry: deprecated {style_id!r} style migration must not declare "
                "replacement_field_ids"
            )
        if has_field_replacement:
            if replaced_by is not None:
                errors.append(
                    f"style-registry: deprecated {style_id!r} field migration requires replaced_by=null"
                )
            if (
                not all(isinstance(field_id, str) and field_id in fields for field_id in replacement_field_ids)
                or len(replacement_field_ids) != len(set(replacement_field_ids))
            ):
                errors.append(
                    f"style-registry: deprecated {style_id!r} has invalid replacement_field_ids"
                )
        elif replacement_field_ids is not None:
            errors.append(
                f"style-registry: deprecated {style_id!r} replacement_field_ids must be "
                "a non-empty canonical field array"
            )

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

        # 可选线索族策略把“多类独立线索 + 受控表达角色”变成机器约束。
        policy = item.get("cue_family_policy")
        if policy is None:
            continue
        if not isinstance(policy, dict):
            errors.append(f"style-registry: {style_id}.cue_family_policy must be an object")
            continue
        min_families = policy.get("min_distinct_families")
        families = policy.get("families")
        expressive_gate = policy.get("expressive_gate")
        if (
            not isinstance(min_families, int)
            or isinstance(min_families, bool)
            or min_families < 2
        ):
            errors.append(
                f"style-registry: {style_id}.cue_family_policy.min_distinct_families must be an integer >= 2"
            )
        if not isinstance(families, dict) or not families:
            errors.append(f"style-registry: {style_id}.cue_family_policy.families must be a non-empty object")
            families = {}
        family_union: set[str] = set()
        for family_name, family_field_ids in families.items():
            family_path = f"style-registry: {style_id}.cue_family_policy.families.{family_name}"
            if not isinstance(family_name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", family_name):
                errors.append(f"{family_path}: family name must use lower_snake_case")
            if (
                not isinstance(family_field_ids, list)
                or not family_field_ids
                or not all(isinstance(field_id, str) for field_id in family_field_ids)
                or len(family_field_ids) != len(set(family_field_ids))
            ):
                errors.append(f"{family_path}: must be a non-empty unique field_id array")
                continue
            family_set = set(family_field_ids)
            overlap = sorted(family_union & family_set)
            if overlap:
                errors.append(f"{family_path}: fields occur in multiple cue families {overlap}")
            family_union.update(family_set)
        if isinstance(min_families, int) and not isinstance(min_families, bool) and min_families > len(families):
            errors.append(
                f"style-registry: {style_id}.cue_family_policy.min_distinct_families exceeds family count"
            )
        allowed_style_fields = set(decisive or []) | set(auxiliary or [])
        unknown_family_fields = sorted(family_union - fields.keys())
        if unknown_family_fields:
            errors.append(
                f"style-registry: {style_id}.cue_family_policy has unknown fields {unknown_family_fields}"
            )
        disallowed_family_fields = sorted(family_union - allowed_style_fields)
        if disallowed_family_fields:
            errors.append(
                f"style-registry: {style_id}.cue_family_policy has fields outside style allowlists "
                f"{disallowed_family_fields}"
            )
        if not isinstance(expressive_gate, dict):
            errors.append(
                f"style-registry: {style_id}.cue_family_policy.expressive_gate must be an object"
            )
        else:
            gate_field_id = expressive_gate.get("field_id")
            gate_values = expressive_gate.get("allowed_values")
            if set(expressive_gate) != {"field_id", "allowed_values"}:
                errors.append(
                    f"style-registry: {style_id}.cue_family_policy.expressive_gate requires only "
                    "field_id and allowed_values"
                )
            if (
                not isinstance(gate_field_id, str)
                or gate_field_id not in fields
                or gate_field_id not in set(decisive or [])
                or fields.get(gate_field_id, {}).get("decision_use") != "hard"
            ):
                errors.append(
                    f"style-registry: {style_id}.cue_family_policy.expressive_gate.field_id "
                    "must be a hard decisive field"
                )
            if (
                not isinstance(gate_values, list)
                or not gate_values
                or not all(isinstance(value, str) and value for value in gate_values)
                or len(gate_values) != len(set(gate_values))
            ):
                errors.append(
                    f"style-registry: {style_id}.cue_family_policy.expressive_gate.allowed_values "
                    "must be a non-empty unique string array"
                )
    return errors, warnings, active_styles, fields, alias_to_field, compatibility_derived


def validate_tag_relations(
    tag_relations: dict[str, Any],
    active_styles: dict[str, dict[str, Any]],
    kb_version: str | None,
) -> tuple[
    list[str],
    int,
    set[str],
    dict[str, Any],
    dict[tuple[str, str], dict[str, Any]],
    list[dict[str, Any]],
]:
    """校验多标签本体，并返回可直接用于结果仲裁的规范化索引。"""
    errors: list[str] = []
    if tag_relations.get("knowledge_base_version") != kb_version:
        errors.append(
            "tag-relations: knowledge_base_version="
            f"{tag_relations.get('knowledge_base_version')!r}, expected {kb_version!r}"
        )

    max_tags = tag_relations.get("max_confirmed_tags")
    if not isinstance(max_tags, int) or isinstance(max_tags, bool) or not 1 <= max_tags <= 3:
        errors.append("tag-relations: max_confirmed_tags must be an integer within 1..3")
        max_tags = 3

    facet_ids: list[str] = []
    facets = tag_relations.get("facets")
    if not isinstance(facets, list) or not facets:
        errors.append("tag-relations: facets must be a non-empty array")
        facets = []
    for index, facet in enumerate(facets):
        facet_id = facet.get("facet_id") if isinstance(facet, dict) else facet
        if not isinstance(facet_id, str) or not facet_id:
            errors.append(f"tag-relations.facets[{index}]: invalid facet_id")
            continue
        facet_ids.append(facet_id)
    if len(facet_ids) != len(set(facet_ids)):
        errors.append("tag-relations: duplicate facet_id values")
    facet_set = set(facet_ids)

    for style_id, style in active_styles.items():
        tag_kind = style.get("tag_kind")
        if tag_kind not in {"atomic", "composite", "identity"}:
            errors.append(f"style-registry: {style_id}.tag_kind is invalid")
        style_facets = style.get("facet_ids")
        if (
            not isinstance(style_facets, list)
            or not style_facets
            or not all(isinstance(item, str) and item for item in style_facets)
            or len(style_facets) != len(set(style_facets))
        ):
            errors.append(f"style-registry: {style_id}.facet_ids must be a non-empty unique string array")
            continue
        unknown_facets = sorted(set(style_facets) - facet_set)
        if unknown_facets:
            errors.append(f"style-registry: {style_id}.facet_ids has unknown facets {unknown_facets}")

    relation_values = {"compatible", "exclusive", "conditional"}
    scope_values = {"global", "same_region_same_mechanism", "cross_region_or_mechanism"}
    same_region_values = {"forbidden", "independent_evidence"}
    default_pair = tag_relations.get("default_pair_relation")
    if not isinstance(default_pair, dict):
        errors.append("tag-relations: default_pair_relation must be an object")
        default_pair = {}
    if default_pair.get("relation") != "conditional":
        errors.append("tag-relations: default relation must be conditional")
    if default_pair.get("scope") != "same_region_same_mechanism":
        errors.append("tag-relations: default scope must be same_region_same_mechanism")
    if default_pair.get("same_region_coexistence") not in same_region_values:
        errors.append(
            "tag-relations: default conditional relation requires "
            "same_region_coexistence=forbidden|independent_evidence"
        )
    if not isinstance(default_pair.get("coexistence_rule"), str) or not default_pair.get("coexistence_rule"):
        errors.append("tag-relations: default_pair_relation requires coexistence_rule")
    default_conflict_facets = default_pair.get("conflict_facet_ids")
    if default_conflict_facets is not None and (
        not isinstance(default_conflict_facets, list)
        or not default_conflict_facets
        or not all(isinstance(item, str) and item in facet_set for item in default_conflict_facets)
        or len(default_conflict_facets) != len(set(default_conflict_facets))
    ):
        errors.append(
            "tag-relations: default_pair_relation.conflict_facet_ids must be a non-empty "
            "unique array of known facets when present"
        )

    active_ids = set(active_styles)
    pair_map: dict[tuple[str, str], dict[str, Any]] = {}
    relation_ids: set[str] = set()
    pair_relations = tag_relations.get("pair_relations")
    if not isinstance(pair_relations, list):
        errors.append("tag-relations: pair_relations must be an array")
        pair_relations = []
    for index, relation in enumerate(pair_relations):
        path = f"tag-relations.pair_relations[{index}]"
        if not isinstance(relation, dict):
            errors.append(f"{path}: relation must be an object")
            continue
        relation_id = relation.get("relation_id")
        if not isinstance(relation_id, str) or not relation_id:
            errors.append(f"{path}: invalid relation_id")
        elif relation_id in relation_ids:
            errors.append(f"{path}: duplicate relation_id {relation_id!r}")
        else:
            relation_ids.add(relation_id)
        style_ids = relation.get("style_ids")
        if (
            not isinstance(style_ids, list)
            or len(style_ids) != 2
            or not all(isinstance(item, str) for item in style_ids)
            or len(set(style_ids)) != 2
        ):
            errors.append(f"{path}: style_ids must contain exactly two distinct style IDs")
            continue
        unknown_styles = sorted(set(style_ids) - active_ids)
        if unknown_styles:
            errors.append(f"{path}: unknown active styles {unknown_styles}")
        pair_key = tuple(sorted(style_ids))
        if pair_key in pair_map:
            errors.append(f"{path}: duplicate unordered style pair {pair_key}")
        else:
            pair_map[pair_key] = relation
        if relation.get("relation") not in relation_values:
            errors.append(f"{path}: invalid relation {relation.get('relation')!r}")
        if relation.get("scope") not in scope_values:
            errors.append(f"{path}: invalid scope {relation.get('scope')!r}")
        if not isinstance(relation.get("rule"), str) or not relation.get("rule"):
            errors.append(f"{path}: rule must be a non-empty string")
        conflict_facets = relation.get("conflict_facet_ids")
        if relation.get("relation") == "conditional":
            if relation.get("same_region_coexistence") not in same_region_values:
                errors.append(
                    f"{path}: conditional relation requires "
                    "same_region_coexistence=forbidden|independent_evidence"
                )
            if (
                not isinstance(conflict_facets, list)
                or not conflict_facets
                or not all(isinstance(item, str) and item in facet_set for item in conflict_facets)
                or len(conflict_facets) != len(set(conflict_facets))
            ):
                errors.append(
                    f"{path}: conditional relation requires non-empty unique conflict_facet_ids "
                    "from the facet registry"
                )
            elif isinstance(style_ids, list) and all(style_id in active_styles for style_id in style_ids):
                for style_id in style_ids:
                    if not set(active_styles[style_id].get("facet_ids") or []).intersection(
                        conflict_facets
                    ):
                        errors.append(
                            f"{path}: conflict_facet_ids do not apply to style {style_id!r}"
                        )
        else:
            if conflict_facets is not None:
                errors.append(f"{path}: conflict_facet_ids is only valid for conditional relations")
            if "same_region_coexistence" in relation:
                errors.append(
                    f"{path}: same_region_coexistence is only valid for conditional relations"
                )

    dependencies = tag_relations.get("tag_dependencies")
    if not isinstance(dependencies, list):
        errors.append("tag-relations: tag_dependencies must be an array")
        dependencies = []
    for index, dependency in enumerate(dependencies):
        path = f"tag-relations.tag_dependencies[{index}]"
        if not isinstance(dependency, dict):
            errors.append(f"{path}: dependency must be an object")
            continue
        relation_id = dependency.get("relation_id")
        if not isinstance(relation_id, str) or not relation_id:
            errors.append(f"{path}: invalid relation_id")
        elif relation_id in relation_ids:
            errors.append(f"{path}: duplicate relation_id {relation_id!r}")
        else:
            relation_ids.add(relation_id)
        source = dependency.get("source_style_id")
        targets = dependency.get("target_style_ids")
        if source not in active_ids:
            errors.append(f"{path}: unknown source_style_id {source!r}")
        if dependency.get("relation") not in {"requires", "implies"}:
            errors.append(f"{path}: relation must be requires or implies")
        if dependency.get("target_quantifier") not in {"any", "all"}:
            errors.append(f"{path}: target_quantifier must be any or all")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(item, str) for item in targets)
            or len(targets) != len(set(targets))
        ):
            errors.append(f"{path}: target_style_ids must be a non-empty unique string array")
        else:
            unknown_targets = sorted(set(targets) - active_ids)
            if unknown_targets:
                errors.append(f"{path}: unknown target styles {unknown_targets}")
            if source in targets:
                errors.append(f"{path}: source_style_id cannot also be a target")
        if not isinstance(dependency.get("rule"), str) or not dependency.get("rule"):
            errors.append(f"{path}: rule must be a non-empty string")

    requires_sources = {
        dependency.get("source_style_id")
        for dependency in dependencies
        if isinstance(dependency, dict) and dependency.get("relation") == "requires"
    }
    for style_id, style in active_styles.items():
        if style.get("tag_kind") == "composite" and style_id not in requires_sources:
            errors.append(
                f"tag-relations: composite style {style_id!r} requires at least one requires dependency"
            )
        if style.get("tag_kind") in {"atomic", "identity"} and style_id in requires_sources:
            errors.append(
                f"tag-relations: {style.get('tag_kind')} style {style_id!r} cannot source a requires dependency"
            )

    return errors, int(max_tags), facet_set, default_pair, pair_map, dependencies


def validate_style_identity(
    path: str,
    item: dict[str, Any],
    active_styles: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    style_id = item.get("style_id")
    record = active_styles.get(style_id)
    if record is None:
        return [f"{path}: unknown or inactive style_id {style_id!r}"]
    label_en = record.get("display_name_en")
    label_zh = record.get("display_name_zh")
    if item.get("label_en") != label_en:
        errors.append(f"{path}: label_en={item.get('label_en')!r}, expected {label_en!r}")
    if item.get("label_zh") != label_zh:
        errors.append(f"{path}: label_zh={item.get('label_zh')!r}, expected {label_zh!r}")
    if set(item.get("aliases") or []) != set(record.get("aliases") or []):
        errors.append(f"{path}: aliases must match style registry")
    if item.get("tag_kind") != record.get("tag_kind"):
        errors.append(
            f"{path}: tag_kind={item.get('tag_kind')!r}, expected {record.get('tag_kind')!r}"
        )
    if set(item.get("facet_ids") or []) != set(record.get("facet_ids") or []):
        errors.append(f"{path}: facet_ids must match style registry")
    forbidden_hierarchy = sorted(
        key for key in ("parent_style_id", "level_1", "level_2") if key in item
    )
    if forbidden_hierarchy:
        errors.append(f"{path}: flat labels forbid hierarchy fields {forbidden_hierarchy}")
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
    confirmed_usable_field_ids: set[str],
    confirmed_field_evidence_ids: dict[str, set[str]],
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
                elif field_id not in confirmed_usable_field_ids:
                    errors.append(
                        f"{path}.{key}[{index}]: {field_id} confidence must be >=0.75 "
                        "to support a confirmed style"
                    )
                elif field_id not in allowed_ids:
                    errors.append(
                        f"{path}.{key}[{index}]: {field_id} is not allowed by this style's {allowed_key}"
                    )
                elif not assessment_evidence.intersection(
                    confirmed_field_evidence_ids.get(field_id, set())
                ):
                    errors.append(
                        f"{path}.{key}[{index}]: evidence_refs do not include >=0.75-confidence "
                        f"evidence for {field_id}"
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
    tag_relations: dict[str, Any],
    combination_presets: dict[str, Any] | None = None,
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
    (
        relation_errors,
        max_confirmed_tags,
        _facet_ids,
        default_pair_relation,
        explicit_pair_relations,
        tag_dependencies,
    ) = validate_tag_relations(tag_relations, active_styles, kb_version)
    errors.extend(relation_errors)
    if combination_presets is None:
        combination_presets = json.loads(
            DEFAULT_COMBINATION_PRESETS.read_text(encoding="utf-8"),
            parse_constant=reject_nonfinite_constant,
        )
    color_roles = extract_style_color_roles(kb_text)
    value_spaces = extract_kb_value_spaces(kb_text)

    style_result = data.get("style_result", {})
    confirmed_style_ids = [
        item.get("style_id")
        for item in style_result.get("style_tags", [])
        if isinstance(item, dict) and isinstance(item.get("style_id"), str)
    ]
    expected_presets = compute_derived_style_presets(
        confirmed_style_ids,
        combination_presets,
    )
    if style_result.get("derived_style_presets") != expected_presets:
        errors.append(
            "style_result.derived_style_presets: must equal deterministic Python derivation "
            "from confirmed style_tags"
        )

    target_object = data.get("target_object", {})
    target_bbox = target_object.get("bbox_norm")
    target_view = str(target_object.get("view") or "unknown")
    visible_regions = {
        str(region) for region in target_object.get("visible_regions", []) if isinstance(region, str)
    }
    allowed_regions = visible_regions | {"whole_object"}
    errors += bbox_errors("target_object.bbox_norm", target_bbox)
    evidence_list = data.get("evidence", [])
    evidence_ids = [item.get("evidence_id") for item in evidence_list if isinstance(item, dict)]
    duplicate_evidence = sorted({item for item in evidence_ids if evidence_ids.count(item) > 1})
    if duplicate_evidence:
        errors.append(f"duplicate evidence_id values: {duplicate_evidence}")
    evidence_set = set(evidence_ids)
    evidence_regions = {
        str(item.get("evidence_id")): str(item.get("region") or "")
        for item in evidence_list
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }
    for i, evidence in enumerate(evidence_list):
        bbox = evidence.get("bbox_norm")
        errors += bbox_errors(f"evidence[{i}].bbox_norm", bbox)
        if not bbox_contains(target_bbox, bbox):
            errors.append(f"evidence[{i}].bbox_norm: evidence box must be inside target_object.bbox_norm")
        if evidence.get("region") not in allowed_regions:
            errors.append(
                f"evidence[{i}].region={evidence.get('region')!r} is outside "
                "target_object.visible_regions"
            )
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
        if element.get("region") not in allowed_regions:
            errors.append(
                f"design_element[{i}].region={element.get('region')!r} is outside "
                "target_object.visible_regions"
            )
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
    for legacy_key in ("primary_style", "secondary_styles"):
        if legacy_key in style_result:
            errors.append(f"style_result: legacy field {legacy_key!r} is forbidden by the flat multi-tag contract")
    status = style_result.get("classification_status")
    if status == "provisional":
        errors.append("style_result: provisional is not supported; use confirmed or unclassified")
    style_tags = [item for item in style_result.get("style_tags", []) if isinstance(item, dict)]
    candidates = [item for item in style_result.get("candidate_ranking", []) if isinstance(item, dict)]
    arbitrations = [
        item for item in style_result.get("pairwise_arbitrations", []) if isinstance(item, dict)
    ]
    if status == "confirmed" and not style_tags:
        errors.append("style_result: confirmed requires at least one style tag")
    if status == "unclassified" and style_tags:
        errors.append("style_result: unclassified requires style_tags=[]")
    if len(style_tags) > max_confirmed_tags:
        errors.append(
            f"style_result.style_tags: found {len(style_tags)}, tag-relations allows {max_confirmed_tags}"
        )

    assessments: list[tuple[str, dict[str, Any]]] = [
        (f"style_result.style_tags[{i}]", item) for i, item in enumerate(style_tags)
    ]
    assessments.extend((f"style_result.candidate_ranking[{i}]", item) for i, item in enumerate(candidates))
    for path, item in assessments:
        errors.extend(validate_style_identity(path, item, active_styles))

    tag_ids = [str(item.get("style_id") or "") for item in style_tags]
    if len(tag_ids) != len(set(tag_ids)):
        errors.append("style_result.style_tags: style_id values must be unique")
    dominances = [item.get("dominance") for item in style_tags]
    numeric_dominances = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in dominances
    )
    if numeric_dominances:
        if len(dominances) == 1 and float(dominances[0]) != 1:
            errors.append("style_result.style_tags: a single confirmed tag requires dominance=1")
        if len(dominances) > 1 and not 0.99 <= sum(float(value) for value in dominances) <= 1.01:
            errors.append("style_result.style_tags: non-empty dominance values must sum to about 1")
        if all(
            isinstance(item.get("match_score"), (int, float))
            and not isinstance(item.get("match_score"), bool)
            for item in style_tags
        ):
            expected_tag_order = [
                str(item.get("style_id") or "")
                for item in sorted(
                    style_tags,
                    key=lambda item: (
                        -float(item.get("dominance")),
                        -float(item.get("match_score")),
                        str(item.get("style_id") or ""),
                    ),
                )
            ]
            if tag_ids != expected_tag_order:
                errors.append(
                    "style_result.style_tags: must use stable order "
                    "(-dominance, -match_score, style_id)"
                )
    def is_usable_confirmed_value(element: dict[str, Any]) -> bool:
        return element.get("value") is not None and (
            (element.get("evidence_mode") == "direct" and element.get("observability") == "observed")
            or (element.get("evidence_mode") != "direct" and element.get("computation_status") == "computed")
        )

    usable_field_ids = {
        str(element.get("field_id"))
        for element in canonical_elements.values()
        if is_usable_confirmed_value(element)
    }
    confirmed_usable_field_ids = {
        str(element.get("field_id"))
        for element in canonical_elements.values()
        if is_usable_confirmed_value(element)
        and isinstance(element.get("confidence"), (int, float))
        and not isinstance(element.get("confidence"), bool)
        and element.get("confidence") >= 0.75
    }
    usable_field_values: dict[str, list[Any]] = {}
    confirmed_field_evidence_ids: dict[str, set[str]] = {}
    for element in canonical_elements.values():
        field_id = str(element.get("field_id") or "")
        if (
            is_usable_confirmed_value(element)
            and isinstance(element.get("confidence"), (int, float))
            and not isinstance(element.get("confidence"), bool)
            and element.get("confidence") >= 0.75
        ):
            usable_field_values.setdefault(field_id, []).append(element.get("value"))
            confirmed_field_evidence_ids.setdefault(field_id, set()).update(
                element.get("evidence_refs") or []
            )
    for path, item in assessments[: len(style_tags)]:
        style_id = str(item.get("style_id") or "")
        if (
            not isinstance(item.get("confidence"), (int, float))
            or isinstance(item.get("confidence"), bool)
            or item.get("confidence") < 0.75
        ):
            errors.append(f"{path}: confirmed style confidence must be >= 0.75")
        invalid_regions = sorted(set(item.get("regions") or []) - allowed_regions)
        if invalid_regions:
            errors.append(f"{path}: regions outside target_object.visible_regions {invalid_regions}")
        if color_roles.get(style_id) == "required" and item.get("color_requirement", {}).get("status") == "not_applicable":
            errors.append(f"{path}.color_requirement: required color role cannot be not_applicable")
        errors.extend(
            validate_style_feature_hits(
                path,
                item,
                fields,
                alias_to_field,
                usable_field_ids,
                confirmed_usable_field_ids,
                confirmed_field_evidence_ids,
                active_styles.get(style_id, {}),
            )
        )
        policy = active_styles.get(style_id, {}).get("cue_family_policy")
        if isinstance(policy, dict):
            cited_core_field_ids = {
                field_id
                for hit in item.get("core_feature_hits", [])
                for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
                if field_id in confirmed_usable_field_ids
            }
            cited_field_ids = {
                field_id
                for key in ("core_feature_hits", "auxiliary_feature_hits")
                for hit in item.get(key, [])
                for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
                if field_id in confirmed_usable_field_ids
            }
            raw_families = policy.get("families")
            families = raw_families if isinstance(raw_families, dict) else {}
            family_hits = {
                family_name: cited_field_ids.intersection(family_field_ids)
                for family_name, family_field_ids in families.items()
                if isinstance(family_field_ids, list)
                and cited_field_ids.intersection(family_field_ids)
            }
            family_evidence = {
                family_name: {
                    evidence_id
                    for field_id in family_field_ids
                    for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
                    if evidence_id in set(item.get("evidence_refs") or [])
                }
                for family_name, family_field_ids in family_hits.items()
            }
            min_families = policy.get("min_distinct_families")
            independent_family_group: tuple[str, ...] = ()
            if (
                isinstance(min_families, int)
                and not isinstance(min_families, bool)
                and min_families >= 1
            ):
                for family_group in combinations(sorted(family_evidence), min_families):
                    if all(
                        family_evidence[family_name]
                        - {
                            evidence_id
                            for other_name in family_group
                            if other_name != family_name
                            for evidence_id in family_evidence[other_name]
                        }
                        for family_name in family_group
                    ):
                        independent_family_group = family_group
                        break
            if isinstance(min_families, int) and len(independent_family_group) < min_families:
                errors.append(
                    f"{path}: cue_family_policy requires at least {min_families} cue families "
                    "with mutually unshared field evidence; "
                    f"found no qualifying group among {sorted(family_evidence)}"
                )
            expressive_gate = policy.get("expressive_gate")
            gate_field_id = (
                expressive_gate.get("field_id") if isinstance(expressive_gate, dict) else None
            )
            gate_values = set(
                expressive_gate.get("allowed_values") or []
                if isinstance(expressive_gate, dict)
                else []
            )
            if (
                not isinstance(gate_field_id, str)
                or gate_field_id not in cited_core_field_ids
                or not any(value in gate_values for value in usable_field_values.get(gate_field_id, []))
            ):
                errors.append(
                    f"{path}: cue_family_policy expressive_gate requires core {gate_field_id!r} "
                    f"with one of {sorted(gate_values)}"
                )
        coverage = item.get("rule_coverage", {})
        errors.extend(validate_rule_coverage(path, item))
        if not item.get("hard_rule_passed") or item.get("missing_required_items") or item.get("exclusion_hits"):
            errors.append(f"{path}: every confirmed tag must pass hard rules without missing or exclusions")
        if coverage.get("failed_rule_count") != 0 or coverage.get("unknown_rule_count") != 0:
            errors.append(f"{path}: confirmed tag requires zero failed and unknown rules")
        if coverage.get("applicable_rule_count", 0) < 1 or coverage.get("passed_rule_count", 0) < 1:
            errors.append(
                f"{path}: confirmed tag requires applicable_rule_count>=1 and passed_rule_count>=1"
            )
        if not item.get("core_feature_hits") or not item.get("auxiliary_feature_hits"):
            errors.append(f"{path}: confirmed tag requires a decisive anchor and independent support")
        if len(item.get("evidence_refs") or []) < 2:
            errors.append(f"{path}: confirmed tag requires at least two evidence refs")
        backed_regions = {
            evidence_regions.get(str(ref), "") for ref in item.get("evidence_refs", [])
        }
        unbacked_regions = sorted(set(item.get("regions") or []) - backed_regions)
        if unbacked_regions:
            errors.append(f"{path}: regions lack matching referenced evidence {unbacked_regions}")

    ranks = [item.get("rank") for item in candidates]
    if ranks != list(range(1, len(candidates) + 1)):
        errors.append(f"style_result.candidate_ranking: ranks must be consecutive from 1, got {ranks}")
    candidate_ids = [item.get("style_id") for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("style_result.candidate_ranking: style_id values must be unique")
    if all(
        isinstance(item.get("match_score"), (int, float)) and not isinstance(item.get("match_score"), bool)
        for item in candidates
    ):
        expected_candidate_order = [
            item.get("style_id")
            for item in sorted(
                candidates,
                key=lambda item: (-float(item.get("match_score")), str(item.get("style_id") or "")),
            )
        ]
        if candidate_ids != expected_candidate_order:
            errors.append(
                "style_result.candidate_ranking: must use stable order (-match_score, style_id)"
            )
    confirmed_candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        path = f"style_result.candidate_ranking[{index}]"
        candidate_status = candidate.get("candidate_status")
        dominance = candidate.get("dominance")
        if candidate_status == "confirmed":
            confirmed_candidate_ids.add(str(candidate.get("style_id") or ""))
            if not candidate.get("hard_rule_passed"):
                errors.append(f"{path}: confirmed candidate requires hard_rule_passed=true")
            if not isinstance(dominance, (int, float)) or isinstance(dominance, bool) or dominance <= 0:
                errors.append(f"{path}: confirmed candidate requires dominance > 0")
            if (
                not isinstance(candidate.get("confidence"), (int, float))
                or isinstance(candidate.get("confidence"), bool)
                or candidate.get("confidence") < 0.75
            ):
                errors.append(f"{path}: confirmed candidate confidence must be >= 0.75")
        elif candidate_status in {"provisional", "rejected"}:
            if dominance != 0:
                errors.append(f"{path}: non-confirmed candidate requires dominance=0")
            if candidate.get("hard_rule_passed") is True and not candidate.get("main_conflicts"):
                errors.append(
                    f"{path}: non-confirmed hard_rule_passed=true requires non-empty main_conflicts"
                )
        invalid_regions = sorted(set(candidate.get("regions") or []) - allowed_regions)
        if invalid_regions:
            errors.append(f"{path}: regions outside target_object.visible_regions {invalid_regions}")

    candidate_by_id = {str(item.get("style_id") or ""): item for item in candidates}
    if confirmed_candidate_ids != set(tag_ids):
        errors.append(
            "style_result: candidate_status=confirmed IDs must exactly equal style_tags IDs"
        )
    if status == "unclassified" and confirmed_candidate_ids:
        errors.append("style_result: unclassified cannot contain confirmed candidates")
    for index, tag in enumerate(style_tags):
        path = f"style_result.style_tags[{index}]"
        style_id = str(tag.get("style_id") or "")
        candidate = candidate_by_id.get(style_id)
        if candidate is None:
            errors.append(f"{path}: confirmed style must appear in candidate_ranking")
            continue
        if candidate.get("candidate_status") != "confirmed":
            errors.append(f"{path}: matching candidate_status must be confirmed")
        for key in (
            "label_en",
            "label_zh",
            "aliases",
            "tag_kind",
            "match_score",
            "confidence",
            "dominance",
            "regions",
            "hard_rule_passed",
        ):
            if key in {"aliases", "regions"}:
                matches = set(candidate.get(key) or []) == set(tag.get(key) or [])
            else:
                matches = candidate.get(key) == tag.get(key)
            if not matches:
                errors.append(f"{path}: candidate_ranking value differs for {key}")
        if set(candidate.get("facet_ids") or []) != set(tag.get("facet_ids") or []):
            errors.append(f"{path}: candidate_ranking value differs for facet_ids")

    def regions_overlap(left: set[str], right: set[str]) -> bool:
        return bool(left & right) or "whole_object" in left or "whole_object" in right

    expected_pair_keys = {
        tuple(sorted((tag_ids[left], tag_ids[right])))
        for left in range(len(tag_ids))
        for right in range(left + 1, len(tag_ids))
    }
    actual_pair_keys: list[tuple[str, str]] = []
    tags_by_id = {str(item.get("style_id") or ""): item for item in style_tags}
    for index, arbitration in enumerate(arbitrations):
        path = f"style_result.pairwise_arbitrations[{index}]"
        style_a = str(arbitration.get("style_id_a") or "")
        style_b = str(arbitration.get("style_id_b") or "")
        if style_a >= style_b:
            errors.append(f"{path}: style_id_a/style_id_b must use canonical lexical order")
        pair_key = tuple(sorted((style_a, style_b)))
        actual_pair_keys.append(pair_key)
        if style_a == style_b or style_a not in tags_by_id or style_b not in tags_by_id:
            errors.append(f"{path}: pair must reference two distinct confirmed style tags")
            continue
        expected_relation = explicit_pair_relations.get(pair_key, default_pair_relation)
        relation = arbitration.get("relation")
        scope = arbitration.get("scope")
        if relation != expected_relation.get("relation"):
            errors.append(f"{path}: relation must match tag-relations for pair {pair_key}")
        if scope != expected_relation.get("scope"):
            errors.append(f"{path}: scope must match tag-relations for pair {pair_key}")
        if arbitration.get("decision") != "coexist":
            errors.append(f"{path}: confirmed tag pairs require decision='coexist'")

        tag_a, tag_b = tags_by_id[style_a], tags_by_id[style_b]
        shared_evidence = bool(
            set(tag_a.get("evidence_refs") or []) & set(tag_b.get("evidence_refs") or [])
        )
        region_overlap = shared_evidence or regions_overlap(
            set(tag_a.get("regions") or []), set(tag_b.get("regions") or [])
        )
        core_ids_a = {
            field_id
            for hit in tag_a.get("core_feature_hits", [])
            for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
        }
        core_ids_b = {
            field_id
            for hit in tag_b.get("core_feature_hits", [])
            for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
        }
        independent_mechanisms = bool(core_ids_a - core_ids_b) and bool(core_ids_b - core_ids_a)
        conflict_facets = set(expected_relation.get("conflict_facet_ids") or [])
        if not conflict_facets and pair_key not in explicit_pair_relations:
            conflict_facets = set(tag_a.get("facet_ids") or []) & set(tag_b.get("facet_ids") or [])
        uses_default_relation = pair_key not in explicit_pair_relations
        has_conflict_facet = bool(conflict_facets & set(tag_a.get("facet_ids") or [])) and bool(
            conflict_facets & set(tag_b.get("facet_ids") or [])
        )
        core_evidence_a = {
            evidence_id
            for field_id in core_ids_a
            for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
            if evidence_id in set(tag_a.get("evidence_refs") or [])
        }
        core_evidence_b = {
            evidence_id
            for field_id in core_ids_b
            for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
            if evidence_id in set(tag_b.get("evidence_refs") or [])
        }
        exclusive_core_evidence_a = core_evidence_a - core_evidence_b
        exclusive_core_evidence_b = core_evidence_b - core_evidence_a
        pair_refs = set(arbitration.get("evidence_refs") or [])
        if (
            relation == "conditional"
            and region_overlap
            and (uses_default_relation or has_conflict_facet)
        ):
            same_region_mode = expected_relation.get("same_region_coexistence")
            if same_region_mode == "forbidden":
                errors.append(
                    f"{path}: conditional conflict facets {sorted(conflict_facets)} use "
                    "same_region_coexistence=forbidden and cannot coexist on overlapping regions"
                )
            elif same_region_mode == "independent_evidence" and not (
                independent_mechanisms
                and exclusive_core_evidence_a
                and exclusive_core_evidence_b
                and pair_refs.intersection(exclusive_core_evidence_a)
                and pair_refs.intersection(exclusive_core_evidence_b)
            ):
                errors.append(
                    f"{path}: same-region conditional coexistence requires different core fields, "
                    "mutually exclusive core field evidence, and arbitration refs for both sides"
                )
        if relation == "exclusive" and scope == "global":
            errors.append(f"{path}: globally exclusive tags cannot both be confirmed")
        if (
            relation in {"exclusive", "conditional"}
            and scope in {"same_region_same_mechanism", "cross_region_or_mechanism"}
            and region_overlap
            and not independent_mechanisms
        ):
            errors.append(
                f"{path}: coexistence requires region separation or independent core mechanisms under scope={scope}"
            )
        if (
            relation == "compatible"
            and scope == "cross_region_or_mechanism"
            and region_overlap
            and not independent_mechanisms
        ):
            errors.append(
                f"{path}: compatible cross-region/mechanism coexistence requires region separation "
                "or independent core mechanisms"
            )
        if not pair_refs.intersection(tag_a.get("evidence_refs") or []):
            errors.append(f"{path}: evidence_refs must include evidence for {style_a}")
        if not pair_refs.intersection(tag_b.get("evidence_refs") or []):
            errors.append(f"{path}: evidence_refs must include evidence for {style_b}")

    if len(actual_pair_keys) != len(expected_pair_keys):
        errors.append(
            "style_result.pairwise_arbitrations: count must equal C(n,2) for confirmed tags"
        )
    if len(actual_pair_keys) != len(set(actual_pair_keys)):
        errors.append("style_result.pairwise_arbitrations: unordered style pairs must be unique")
    if set(actual_pair_keys) != expected_pair_keys:
        errors.append(
            "style_result.pairwise_arbitrations: pairs must exactly cover all confirmed tag combinations"
        )

    confirmed_id_set = set(tag_ids)
    candidate_id_set = set(candidate_by_id)
    for dependency in tag_dependencies:
        source = dependency.get("source_style_id")
        targets = set(dependency.get("target_style_ids") or [])
        if source not in confirmed_id_set:
            continue
        quantifier = dependency.get("target_quantifier")
        available = confirmed_id_set if dependency.get("relation") == "requires" else candidate_id_set
        satisfied = targets.issubset(available) if quantifier == "all" else bool(targets & available)
        if not satisfied:
            errors.append(
                "style_result.style_tags: "
                f"{source} {dependency.get('relation')} target_quantifier={quantifier} "
                f"for {sorted(targets)}"
            )

    style_confidence = data.get("quality_summary", {}).get("style_confidence")
    expected_style_confidence = max(
        (float(item.get("confidence")) for item in style_tags if isinstance(item.get("confidence"), (int, float))),
        default=0.0,
    )
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
    parser.add_argument("--tag-relations", type=Path, default=DEFAULT_TAG_RELATIONS)
    parser.add_argument("--combination-presets", type=Path, default=DEFAULT_COMBINATION_PRESETS)
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()

    data = load_json(args.result)
    schema = load_json(args.schema)
    style_registry = load_json(args.style_registry)
    field_registry = load_json(args.field_registry)
    tag_relations = load_json(args.tag_relations)
    combination_presets = load_json(args.combination_presets)
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

    warnings: list[str] = []
    # 结构无效时不进入假定对象形状的语义层，确保畸形输入也只返回可读错误。
    if not schema_errors:
        kb_text = args.knowledge_base.read_text(encoding="utf-8")
        semantic_errors, warnings = validate_semantics(
            data,
            kb_text,
            style_registry,
            field_registry,
            tag_relations,
            combination_presets,
        )
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
