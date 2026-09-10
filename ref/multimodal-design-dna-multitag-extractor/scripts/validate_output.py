#!/usr/bin/env python3
"""设计 DNA 结果校验入口：Schema 通过后按职责执行只读语义检查。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from derive_style_presets import compute_derived_style_presets
# 保留原入口公开的校验函数，已有脚本调用者无需跟随内部模块拆分迁移。
from validation_rules import (
    ACTIVE_PROFILES,
    DEFAULT_COMBINATION_PRESETS,
    DEFAULT_FIELD_REGISTRY,
    DEFAULT_KB,
    DEFAULT_SCHEMA,
    DEFAULT_STYLE_REGISTRY,
    DEFAULT_TAG_RELATIONS,
    FIELD_ID_PATTERN,
    INLINE_FIELD_REF_PATTERN,
    LEGACY_DIMENSIONS,
    MODULE_PATTERN,
    ROOT,
    STYLE_STATUSES,
    VALUE_TYPES,
    bbox_contains,
    bbox_errors,
    collect_refs,
    extract_kb_value_spaces,
    extract_kb_version,
    extract_style_color_roles,
    field_key,
    is_usable_source,
    is_whole_object_region,
    iter_elements,
    load_json,
    norm_text,
    reject_nonfinite_constant,
    validate_registries,
    validate_rule_coverage,
    validate_style_feature_hits,
    validate_style_identity,
    validate_tag_relations,
    validate_value_domain,
    value_matches,
    view_requirement_satisfied,
)
from validate_fields import (
    _validate_target_evidence,
    _validate_modules,
    _validate_elements,
    _validate_uncertainties,
    _validate_novel_dna,
)
from validate_styles import _validate_styles


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

    allowed_regions, target_view, evidence_regions = _validate_target_evidence(
        data=data,
        errors=errors,
    )

    active_profile_set = _validate_modules(
        data=data,
        fields=fields,
        errors=errors,
    )

    canonical_elements, element_by_key, uncertainty_items = _validate_elements(
        active_profile_set=active_profile_set,
        alias_to_field=alias_to_field,
        allowed_regions=allowed_regions,
        compatibility_derived=compatibility_derived,
        data=data,
        fields=fields,
        target_view=target_view,
        value_spaces=value_spaces,
        errors=errors,
    )

    _validate_uncertainties(
        alias_to_field=alias_to_field,
        compatibility_derived=compatibility_derived,
        element_by_key=element_by_key,
        fields=fields,
        uncertainty_items=uncertainty_items,
        value_spaces=value_spaces,
        errors=errors,
    )

    _validate_styles(
        alias_to_field=alias_to_field,
        allowed_regions=allowed_regions,
        color_roles=color_roles,
        default_pair_relation=default_pair_relation,
        evidence_regions=evidence_regions,
        explicit_pair_relations=explicit_pair_relations,
        fields=fields,
        active_styles=active_styles,
        canonical_elements=canonical_elements,
        data=data,
        max_confirmed_tags=max_confirmed_tags,
        tag_dependencies=tag_dependencies,
        errors=errors,
    )

    _validate_novel_dna(
        alias_to_field=alias_to_field,
        compatibility_derived=compatibility_derived,
        data=data,
        fields=fields,
        value_spaces=value_spaces,
        errors=errors,
    )

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
