#!/usr/bin/env python3
"""结果校验使用的注册表契约、字段类型与基础证据规则。"""
from __future__ import annotations


import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from dna_rules import extract_kb_value_spaces, view_requirement_satisfied


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


def is_usable_source(element: dict[str, Any]) -> bool:
    if element.get("value") is None or element.get("observability") != "observed":
        return False
    if element.get("evidence_mode") == "direct":
        return element.get("computation_status") == "not_requested"
    return element.get("computation_status") == "computed"


def is_whole_object_region(region: str) -> bool:
    return region == "whole_object" or region.startswith("whole_object_")
