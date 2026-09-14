"""Skill 包内 Schema、机器注册表和知识库之间的静态一致性检查。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dna_rules import extract_kb_value_spaces as _controlled_value_spaces

ROOT = Path(__file__).resolve().parents[1]


def _load_json(relative_path: str, errors: list[str]) -> Any:
    try:
        return json.loads(
            (ROOT / relative_path).read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_constant,
        )
    except Exception as exc:  # 包级报告需要聚合全部错误。
        errors.append(f"invalid JSON in {relative_path}: {exc}")
        return None


def _reject_nonfinite_constant(value: str) -> Any:
    """包资产和 eval 必须使用标准 JSON 数值。"""
    raise ValueError(f"non-finite numeric constant {value!r} is not valid JSON")


def _normalized_label(value: str) -> str:
    """按宿主风格兼容逻辑折叠标点，提前发现别名冲突。"""
    return re.sub(r"[\s_\-—–|/（）()，,。.：:]+", "", value).lower()


def _check_schema(errors: list[str]) -> None:
    schema = _load_json("schemas/design-dna-output.schema.json", errors)
    model_schema = _load_json("schemas/design-dna-model-output.schema.json", errors)
    if not isinstance(schema, dict) or not isinstance(model_schema, dict):
        return
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(model_schema)
    except Exception as exc:
        errors.append(f"invalid Draft 2020-12 schema: {exc}")
    legacy_slot = (
        schema.get("$defs", {})
        .get("designElements", {})
        .get("properties", {})
        .get("original_md_dimensions", {})
    )
    if legacy_slot.get("maxItems") != 0:
        errors.append("schema must keep original_md_dimensions empty for model output")
    module_applicability = schema.get("$defs", {}).get("moduleApplicability", {})
    if "active_profiles" not in module_applicability.get("required", []):
        errors.append("schema module_applicability must require active_profiles")
    active_profile_items = (
        module_applicability.get("properties", {}).get("active_profiles", {}).get("items", {}).get("enum", [])
    )
    if "core" not in active_profile_items or set(active_profile_items).intersection(
        {"profile:multi_face_device", "profile:reference_analysis", "profile:trend_analysis"}
    ):
        errors.append("single-image schema profiles must include core and exclude multi-face/reference/trend profiles")

    definitions = schema.get("$defs", {})
    forbidden_defs = {"parentStyleId", "styleAssessment", "secondaryStyleAssessment"}
    present_forbidden = sorted(forbidden_defs.intersection(definitions))
    if present_forbidden:
        errors.append(f"schema retains legacy hierarchy definitions {present_forbidden}")
    style_result = definitions.get("styleResult", {})
    expected_result_fields = {
        "style_candidates",
        "derived_style_presets",
        "composition_summary",
    }
    if set(style_result.get("required", [])) != expected_result_fields:
        errors.append("schema styleResult required fields do not match the flat multi-tag contract")
    result_properties = style_result.get("properties", {})
    if set(result_properties) != expected_result_fields:
        errors.append("schema styleResult properties must reject legacy primary/secondary fields")
    model_properties = model_schema.get("properties", {})
    if set(model_properties) != {
        "schema_version",
        "knowledge_base_version",
        "target_object",
        "image_quality",
        "active_profiles",
        "rule_adaptations",
        "style_observations",
        "design_observations",
        "uncertainties",
        "novel_dna_elements",
        "evidence",
        "quality_notes",
    }:
        errors.append("model output schema must expose only the lean observation fields")
    model_definitions = model_schema.get("$defs", {})
    if "styleResult" in model_definitions or "qualitySummary" in model_definitions:
        errors.append("model output schema must not retain host-compiled final result definitions")
    candidate_observation = model_definitions.get("styleCandidateObservation", {})
    forbidden_model_fields = {
        "label_en",
        "label_zh",
        "aliases",
        "tag_kind",
        "facet_ids",
        "evidence_refs",
        "rule_coverage",
    }
    if forbidden_model_fields.intersection(candidate_observation.get("properties", {})):
        errors.append("style candidate observations contain host-compiled metadata")
    if set(candidate_observation.get("required", [])) != {
        "style_id",
        "match_score",
        "confidence",
        "regions",
        "main_support",
        "main_conflicts",
    }:
        errors.append("model style candidate observation fields are incomplete")
    model_style_observations = model_definitions.get("styleObservations", {})
    if set(model_style_observations.get("required", [])) != {
        "candidate_tags",
        "composition_summary",
    }:
        errors.append("model style observations must use the candidate-only contract")
    candidate_tags_schema = model_style_observations.get("properties", {}).get(
        "candidate_tags", {}
    )
    if candidate_tags_schema.get("maxItems") != 5:
        errors.append("model candidate_tags must contain at most 5 items")
    style_candidates_schema = result_properties.get("style_candidates", {})
    if style_candidates_schema.get("maxItems") != 5:
        errors.append("schema style_candidates must contain at most 5 ranked candidates")
    if result_properties.get("derived_style_presets", {}).get("maxItems") != 12:
        errors.append("schema derived_style_presets must cap registered presets at 12")

    identity_fields = {"style_id", "label_en", "label_zh", "aliases", "tag_kind", "facet_ids"}
    forbidden_hierarchy = {"parent_style_id", "level_1", "level_2"}
    candidate = definitions.get("styleCandidate", {})
    candidate_properties = set(candidate.get("properties", {}))
    if not identity_fields.issubset(candidate_properties) or candidate_properties.intersection(forbidden_hierarchy):
        errors.append("schema styleCandidate identity must be flat and facet-aware")
    expected_candidate_fields = {
        *identity_fields,
        "rank",
        "match_score",
        "confidence",
        "regions",
        "main_support",
        "main_conflicts",
    }
    if set(candidate.get("required", [])) != expected_candidate_fields:
        errors.append("schema styleCandidate required fields are incomplete")
    if candidate.get("properties", {}).get("main_support", {}).get("minItems") != 1:
        errors.append("schema styleCandidate main_support must be non-empty")


def _check_style_evidence_rules(
    active: list[dict[str, Any]],
    errors: list[str],
    style_evidence_rules: dict[str, Any],
) -> None:
    """核对值级证据规则中的风格、操作符及字段引用。"""
    active_by_id = {
        str(item.get("style_id") or ""): item
        for item in active
        if item.get("style_id")
    }
    rules_by_style = style_evidence_rules.get("styles")
    if not isinstance(rules_by_style, dict):
        errors.append("style-evidence rules styles must be an object")
        rules_by_style = {}
    unknown_rule_styles = sorted(set(rules_by_style) - set(active_by_id))
    if unknown_rule_styles:
        errors.append(
            f"style-evidence rules reference inactive styles {unknown_rule_styles}"
        )
    seen_rule_ids: set[str] = set()
    supported_operators = {
        "equals",
        "in",
        "not_in",
        "gte",
        "lte",
        "contains_any",
        "contains_all",
    }
    for style_id, config in rules_by_style.items():
        if not isinstance(config, dict):
            errors.append(f"style-evidence {style_id} config must be an object")
            continue
        style = active_by_id.get(style_id, {})
        for rule in config.get("rules", []):
            if not isinstance(rule, dict):
                errors.append(f"style-evidence {style_id} contains non-object rule")
                continue
            rule_id = str(rule.get("rule_id") or "")
            if not rule_id or rule_id in seen_rule_ids:
                errors.append(f"style-evidence has missing/duplicate rule_id {rule_id!r}")
            seen_rule_ids.add(rule_id)
            role = rule.get("role")
            allowed_key = (
                "decisive_field_ids" if role == "core" else "auxiliary_field_ids"
            )
            if role not in {"core", "auxiliary"}:
                errors.append(f"style-evidence {rule_id} has invalid role {role!r}")
                continue
            clauses = [
                {"field_id": rule.get("field_id"), "match": rule.get("match")},
                *(
                    rule.get("requires", [])
                    if isinstance(rule.get("requires"), list)
                    else []
                ),
            ]
            allowed_ids = set(style.get(allowed_key) or [])
            for clause in clauses:
                if not isinstance(clause, dict):
                    errors.append(f"style-evidence {rule_id} has invalid clause")
                    continue
                field_id = clause.get("field_id")
                matcher = clause.get("match")
                if field_id not in allowed_ids:
                    errors.append(
                        f"style-evidence {rule_id} field {field_id!r} is outside {allowed_key}"
                    )
                if (
                    not isinstance(matcher, dict)
                    or matcher.get("operator") not in supported_operators
                ):
                    errors.append(f"style-evidence {rule_id} has invalid matcher")


def _check_presets(
    active: list[dict[str, Any]],
    combination_presets: dict[str, Any],
    errors: list[str],
    schema: dict[str, Any],
) -> None:
    """核对组合预设的原子标签、匹配条款与 Schema 枚举。"""
    active_id_set = {item.get("style_id") for item in active}
    atomic_id_set = {
        item.get("style_id") for item in active if item.get("tag_kind") == "atomic"
    }
    presets = combination_presets.get("presets")
    if combination_presets.get("purpose") != "deterministic_postprocess_and_query":
        errors.append("combination presets purpose must be deterministic postprocess and query")
    if combination_presets.get("output_policy") != "emit_only_in_derived_style_presets":
        errors.append("combination presets must only emit in derived_style_presets")
    if combination_presets.get("match_policy") != "all_clauses_and_min_distinct_styles":
        errors.append("combination presets must use the deterministic all-clause match policy")
    if not isinstance(presets, list) or not presets:
        errors.append("combination presets must contain a non-empty presets array")
        presets = []
    preset_ids = [item.get("preset_id") for item in presets if isinstance(item, dict)]
    if len(preset_ids) != len(presets) or len(preset_ids) != len(set(preset_ids)):
        errors.append("combination presets must have unique preset_id values")
    collisions = sorted(set(preset_ids).intersection(active_id_set))
    if collisions:
        errors.append(f"combination preset IDs collide with active styles: {collisions}")
    schema_preset_ids = (
        schema.get("$defs", {})
        .get("derivedStylePreset", {})
        .get("properties", {})
        .get("preset_id", {})
        .get("enum", [])
    ) if isinstance(schema, dict) else []
    if len(preset_ids) != 12 or preset_ids != schema_preset_ids:
        errors.append("final schema preset enum must match the 12 registry presets in order")
    for preset in presets:
        if not isinstance(preset, dict):
            errors.append("combination preset entries must be objects")
            continue
        clauses = preset.get("clauses")
        minimum_distinct = preset.get("min_distinct_style_ids")
        if not isinstance(clauses, list) or not clauses:
            errors.append(f"combination preset {preset.get('preset_id')} has invalid clauses")
            continue
        clause_union = {
            style_id
            for clause in clauses
            if isinstance(clause, dict)
            for style_id in clause.get("style_ids", [])
            if isinstance(style_id, str)
        }
        if (
            not isinstance(minimum_distinct, int)
            or isinstance(minimum_distinct, bool)
            or not 1 <= minimum_distinct <= min(3, len(clause_union))
        ):
            errors.append(
                f"combination preset {preset.get('preset_id')} has invalid min_distinct_style_ids"
            )
        for clause in clauses:
            style_members = clause.get("style_ids") if isinstance(clause, dict) else None
            min_match = clause.get("min_match") if isinstance(clause, dict) else None
            if (
                not isinstance(style_members, list)
                or not style_members
                or len(style_members) != len(set(style_members))
                or not all(item in atomic_id_set for item in style_members)
                or not isinstance(min_match, int)
                or isinstance(min_match, bool)
                or not 1 <= min_match <= len(style_members)
            ):
                errors.append(
                    f"combination preset {preset.get('preset_id')} has an invalid atomic clause"
                )


def _check_style_documents(
    active: list[dict[str, Any]],
    errors: list[str],
    field_ids: set[str],
    styles: list[dict[str, Any]],
) -> str:
    """核对风格身份、别名、知识库硬规则及混淆组。"""
    active_id_set = {item.get("style_id") for item in active}
    for style in styles:
        replaced_by = style.get("replaced_by")
        replacement_field_ids = style.get("replacement_field_ids")
        has_style_replacement = isinstance(replaced_by, str) and bool(replaced_by)
        has_field_replacement = (
            isinstance(replacement_field_ids, list) and bool(replacement_field_ids)
        )
        if style.get("status") == "active":
            if replaced_by is not None or replacement_field_ids is not None:
                errors.append(f"active style {style.get('style_id')} must not declare a migration")
            continue
        if style.get("status") != "deprecated":
            errors.append(f"style {style.get('style_id')} has invalid status {style.get('status')!r}")
            continue
        if has_style_replacement == has_field_replacement:
            errors.append(
                f"deprecated style {style.get('style_id')} requires exactly one migration path"
            )
        if has_style_replacement and replaced_by not in active_id_set:
            errors.append(
                f"deprecated style {style.get('style_id')} replaced_by must reference an active style"
            )
        if has_style_replacement and replacement_field_ids is not None:
            errors.append(
                f"deprecated style {style.get('style_id')} style migration must not declare "
                "replacement_field_ids"
            )
        if has_field_replacement:
            if replaced_by is not None:
                errors.append(
                    f"deprecated style {style.get('style_id')} field migration requires replaced_by=null"
                )
            if (
                not all(isinstance(field_id, str) and field_id in field_ids for field_id in replacement_field_ids)
                or len(replacement_field_ids) != len(set(replacement_field_ids))
            ):
                errors.append(
                    f"deprecated style {style.get('style_id')} has invalid replacement_field_ids"
                )
        elif replacement_field_ids is not None:
            errors.append(
                f"deprecated style {style.get('style_id')} replacement_field_ids must be a "
                "non-empty canonical field array"
            )
    normalized_labels: dict[str, str] = {}
    for style in styles:
        target = str(style.get("replaced_by") or style.get("style_id") or "")
        for value in (
            style.get("style_id"),
            style.get("display_name_en"),
            style.get("display_name_zh"),
            *(style.get("aliases") or []),
        ):
            if not isinstance(value, str) or not value:
                continue
            normalized = _normalized_label(value)
            previous = normalized_labels.get(normalized)
            if previous is not None and previous != target:
                errors.append(f"style label alias {value!r} collides between {previous} and {target}")
            normalized_labels[normalized] = target
    knowledge_base = (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    rule_ids = set(re.findall(r"^### ([A-Za-z0-9]+) — ", knowledge_base, re.M))
    active_ids = {item.get("style_id") for item in active}
    if rule_ids != active_ids:
        errors.append(
            f"knowledge style rules differ from registry: missing={sorted(active_ids - rule_ids)}, "
            f"extra={sorted(rule_ids - active_ids)}"
        )
    rule_text = knowledge_base.split("## 活动风格规则", 1)[-1].split(
        "# 设计元素与 DNA 规范字段", 1
    )[0]
    rule_matches = list(re.finditer(r"^### ([A-Za-z0-9]+) — .+$", rule_text, re.M))
    required_rule_rows = {
        "核心机制", "颜色角色", "硬门槛", "决定锚点", "辅助证据",
        "硬排除", "混淆组", "异混淆特征", "典型视觉Token",
    }
    rule_rows: dict[str, dict[str, str]] = {}
    for index, match in enumerate(rule_matches):
        end = rule_matches[index + 1].start() if index + 1 < len(rule_matches) else len(rule_text)
        rows = {
            row.group(1).strip(): row.group(2).strip()
            for row in re.finditer(r"^\| ([^|]+?) \| (.*?) \|$", rule_text[match.end():end], re.M)
        }
        rule_rows[match.group(1)] = rows
        missing_rows = required_rule_rows - rows.keys()
        if missing_rows:
            errors.append(f"style {match.group(1)} missing rule rows {sorted(missing_rows)}")
        color_role = re.split(r"[:：]", rows.get("颜色角色", ""), maxsplit=1)[0].strip()
        if color_role not in {"required", "supporting", "unrestricted"}:
            errors.append(f"style {match.group(1)} has invalid color role {color_role!r}")
    for style in active:
        rows = rule_rows.get(str(style.get("style_id")), {})
        documented_groups = set(re.findall(r"CG-\d+", rows.get("混淆组", "")))
        if documented_groups != set(style.get("confusion_groups", [])):
            errors.append(f"style {style.get('style_id')} confusion groups differ from its rule block")

    confusion_ids = set(re.findall(r"^\| (CG-\d+) \|", knowledge_base, re.M))
    if len(confusion_ids) != 8:
        errors.append(f"knowledge base must define 8 confusion groups, got {len(confusion_ids)}")
    confusion_members = {
        match.group(1): {item.strip() for item in match.group(2).split("、") if item.strip()}
        for match in re.finditer(r"^\| (CG-\d+) \| ([^|]+?) \|", knowledge_base, re.M)
    }
    for style in active:
        unknown_groups = sorted(set(style.get("confusion_groups", [])) - confusion_ids)
        if unknown_groups:
            errors.append(f"style {style.get('style_id')} has unknown confusion groups {unknown_groups}")
        for group in style.get("confusion_groups", []):
            if style.get("style_id") not in confusion_members.get(group, set()):
                errors.append(f"style {style.get('style_id')} is absent from knowledge group {group}")
    for group, members in confusion_members.items():
        for style_id in members:
            record = next((item for item in active if item.get("style_id") == style_id), None)
            if record is None:
                errors.append(f"knowledge group {group} references unknown active style {style_id}")
            elif group not in record.get("confusion_groups", []):
                errors.append(f"knowledge group {group} is absent from style registry for {style_id}")

    return knowledge_base


def _check_field_documents(
    active: list[dict[str, Any]],
    errors: list[str],
    field_registry: dict[str, Any],
    knowledge_base: str,
) -> None:
    """核对规范字段、兼容映射、知识库值域与声明。"""
    fields = [item for item in field_registry.get("fields", []) if isinstance(item, dict)]
    field_ids = [item.get("field_id") for item in fields]
    if len(field_ids) != len(set(field_ids)):
        errors.append("field registry contains duplicate field_id")
    if len(fields) != 192:
        errors.append(f"canonical field count must be exactly 192, got {len(fields)}")
    if field_registry.get("canonical_field_count") != len(fields):
        errors.append("field registry canonical_field_count does not match fields")
    required_keys = {
        "field_id", "module_id", "name", "value_type", "evidence_mode",
        "required_views", "applicability", "decision_use", "aliases",
    }
    for field in fields:
        missing = required_keys - field.keys()
        if missing:
            errors.append(f"field {field.get('field_id')} missing registry keys {sorted(missing)}")
        if field.get("value_type") not in {
            "enum", "float", "integer", "boolean", "list", "multi_label", "object", "text",
        }:
            errors.append(f"field {field.get('field_id')} has invalid value_type")
        if field.get("evidence_mode") not in {"direct", "derived", "inferred", "reference_computed"}:
            errors.append(f"field {field.get('field_id')} has invalid evidence_mode")
        if field.get("decision_use") not in {"hard", "support", "semantic_only", "none"}:
            errors.append(f"field {field.get('field_id')} has invalid decision_use")
        for array_key in ("required_views", "applicability", "aliases"):
            value = field.get(array_key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"field {field.get('field_id')} has invalid {array_key}")
        if field.get("evidence_mode") == "derived" and not field.get("derived_from"):
            errors.append(f"derived field {field.get('field_id')} is missing derived_from")
        if field.get("evidence_mode") == "reference_computed" and not set(
            field.get("required_views", [])
        ).intersection({"reference_set", "time_series"}):
            errors.append(f"reference field {field.get('field_id')} lacks reference required_views")
        if field.get("decision_use") == "hard" and field.get("evidence_mode") != "direct":
            if not (
                field.get("field_id") == "DET-17"
                and field.get("evidence_mode") == "inferred"
            ):
                errors.append(
                    f"hard field {field.get('field_id')} must use direct evidence unless it is DET-17"
                )
        for dependency in field.get("derived_from", []):
            if dependency not in field_ids and not str(dependency).startswith(
                ("input_quality.", "input_geometry.", "style_result.", "request_context.", "evidence_")
            ):
                errors.append(f"field {field.get('field_id')} has unknown dependency {dependency}")
    aliases = [alias for field in fields for alias in field.get("aliases", [])]
    if len(aliases) != len(set(aliases)):
        errors.append("field registry contains duplicate aliases")
    collisions = sorted(set(field_ids) & set(aliases))
    if collisions:
        errors.append(f"field aliases collide with canonical IDs: {collisions}")
    canonical_ids = set(field_ids)
    expected_structured_lists = {"PRT-01", "DEV-09", "CLR-03", "IDG-08", "IMG-03", "IMG-05"}
    actual_structured_lists = {
        str(field.get("field_id")) for field in fields if field.get("value_type") == "list"
    }
    if actual_structured_lists != expected_structured_lists:
        errors.append(
            "structured list registry drift: "
            f"missing={sorted(expected_structured_lists - actual_structured_lists)}, "
            f"extra={sorted(actual_structured_lists - expected_structured_lists)}"
        )
    expected_multi_labels = {
        "CMP-13", "PRT-03", "PRT-05", "PRT-11", "PRT-13", "DEV-05", "CLR-12",
        "CMF-04", "CMF-05", "TEX-11", "DET-16", "IMG-04", "IMG-06", "IMG-07",
        "IMG-08", "IMG-10",
    }
    actual_multi_labels = {
        str(field.get("field_id")) for field in fields if field.get("value_type") == "multi_label"
    }
    if actual_multi_labels != expected_multi_labels:
        errors.append(
            "multi_label registry drift: "
            f"missing={sorted(expected_multi_labels - actual_multi_labels)}, "
            f"extra={sorted(actual_multi_labels - expected_multi_labels)}"
        )
    compatibility_policy = field_registry.get("compatibility_derived_policy")
    if compatibility_policy != {"decision_use": "none", "weight": 0}:
        errors.append("compatibility_derived_policy must be decision_use=none and weight=0")
    compatibility_derived = field_registry.get("compatibility_derived")
    if not isinstance(compatibility_derived, dict):
        errors.append("field registry compatibility_derived must be an object")
        compatibility_derived = {}
    id_aliases = {alias for alias in aliases if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d{2,3}", alias)}
    derived_ids = set(compatibility_derived)
    if len(id_aliases) != 25 or len(derived_ids) != 31:
        errors.append(f"compatibility mapping count drift: aliases={len(id_aliases)}, derived={len(derived_ids)}")
    if id_aliases & derived_ids or canonical_ids & derived_ids:
        errors.append("compatibility-derived IDs must be disjoint from aliases and canonical IDs")
    for legacy_id, mapping in compatibility_derived.items():
        sources = mapping.get("source_field_ids") if isinstance(mapping, dict) else None
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d{2,3}", str(legacy_id)):
            errors.append(f"invalid compatibility-derived ID {legacy_id!r}")
        if not isinstance(sources, list) or not sources or not set(sources).issubset(canonical_ids):
            errors.append(f"compatibility-derived {legacy_id} has invalid sources")
        if not isinstance(mapping, dict) or not mapping.get("transform"):
            errors.append(f"compatibility-derived {legacy_id} lacks transform")
    definition_section = knowledge_base.split("## 四、规范字段定义", 1)[-1].split(
        "## 五、别名、合并与派生", 1
    )[0]
    documented_ids = set(re.findall(r"^\| ([A-Z]{3,4}-\d+) \|", definition_section, re.M))
    if documented_ids != canonical_ids:
        errors.append(
            f"knowledge DNA fields differ from registry: missing={sorted(canonical_ids - documented_ids)}, "
            f"extra={sorted(documented_ids - canonical_ids)}"
        )
    registry_by_id = {str(item.get("field_id")): item for item in fields}
    expected_det17 = {
        "field_id": "DET-17",
        "module_id": "DNA-M09",
        "name": "细节语法角色",
        "value_type": "enum",
        "evidence_mode": "inferred",
        "required_views": ["any"],
        "applicability": ["core"],
        "decision_use": "hard",
        "aliases": [],
    }
    if registry_by_id.get("DET-17") != expected_det17:
        errors.append("DET-17 registry contract must remain inferred/core/hard with no aliases")
    definition_rows = {
        match.group(1): tuple(part.strip() for part in match.groups()[1:])
        for match in re.finditer(
            r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$",
            definition_section,
            re.M,
        )
    }
    for field_id, (description, applicability, evidence_view, decision_use) in definition_rows.items():
        field = registry_by_id.get(field_id, {})
        documented_name = description.split("；", 1)[0].split("：", 1)[0].strip()
        if field.get("name") != documented_name:
            errors.append(f"field {field_id} name differs between knowledge base and registry")
        if str(field.get("value_type")) not in description:
            errors.append(f"field {field_id} value_type is absent from its knowledge definition")
        if applicability not in field.get("applicability", []):
            errors.append(f"field {field_id} applicability differs from its knowledge definition")
        if evidence_view.split("/", 1)[0].strip() != field.get("evidence_mode"):
            errors.append(f"field {field_id} evidence_mode differs from its knowledge definition")
        documented_views = {
            item.strip()
            for item in re.split(r"或", evidence_view.split("/", 1)[1].strip())
            if item.strip()
        }
        if documented_views != set(field.get("required_views", [])):
            errors.append(f"field {field_id} required_views differs from its knowledge definition")
        if decision_use != field.get("decision_use"):
            errors.append(f"field {field_id} decision_use differs from its knowledge definition")
        unit = field.get("unit")
        if unit and str(unit) not in description:
            errors.append(f"field {field_id} unit is absent from its knowledge definition")
    semantic_rows = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"^\| (SEM-\d+) \| (.*?) \| .*? \| .*? \|$", definition_section, re.M)
    }
    for field_id, name in semantic_rows.items():
        field = registry_by_id.get(field_id, {})
        expected_semantic = {
            "name": name,
            "value_type": "integer",
            "evidence_mode": "inferred",
            "required_views": ["any"],
            "applicability": ["core"],
            "decision_use": "semantic_only",
            "unit": "ordinal_0_25_50_75_100",
        }
        if any(field.get(key) != value for key, value in expected_semantic.items()):
            errors.append(f"semantic field {field_id} differs between knowledge base and registry")

    for style in active:
        decisive = style.get("decisive_field_ids")
        auxiliary = style.get("auxiliary_field_ids")
        if not isinstance(decisive, list) or not decisive or len(decisive) != len(set(decisive)):
            errors.append(f"style {style.get('style_id')} decisive_field_ids invalid")
            continue
        if not isinstance(auxiliary, list) or not auxiliary or len(auxiliary) != len(set(auxiliary)):
            errors.append(f"style {style.get('style_id')} auxiliary_field_ids invalid")
            continue
        if set(decisive) & set(auxiliary):
            errors.append(f"style {style.get('style_id')} decisive/auxiliary sets overlap")
        for field_id in decisive + auxiliary:
            if field_id not in registry_by_id:
                errors.append(f"style {style.get('style_id')} references unknown field {field_id}")
            elif registry_by_id[field_id].get("decision_use") not in {"hard", "support"}:
                errors.append(f"style {style.get('style_id')} references non-decision field {field_id}")
        if not any(registry_by_id.get(field_id, {}).get("decision_use") == "hard" for field_id in decisive):
            errors.append(f"style {style.get('style_id')} decisive set lacks a hard field")

    enum_rows = {
        field_id: {item.strip() for item in raw_values.split("、") if item.strip()}
        for field_id, raw_values in re.findall(
            r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| [^|]*?：(.*?)；enum(?:\s*/[^|]+)? \|",
            definition_section,
            re.M,
        )
    }
    enum_fields = {field_id for field_id, field in registry_by_id.items() if field.get("value_type") == "enum"}
    if set(enum_rows) != enum_fields:
        errors.append(
            f"enum value-space coverage differs: missing={sorted(enum_fields - set(enum_rows))}, "
            f"extra={sorted(set(enum_rows) - enum_fields)}"
        )
    for field_id, values in enum_rows.items():
        if not values or len(values) != len([item for item in values]):
            errors.append(f"field {field_id} has invalid enum value space")
    if enum_rows.get("DET-17") != {
        "必要功能结构", "通用装饰", "历史造型化", "当代技术化", "未知",
    }:
        errors.append("DET-17 must keep its five-value visible-syntax enum")
    controlled_spaces = _controlled_value_spaces(knowledge_base)
    documented_multi_labels = {
        field_id for field_id, (value_type, values) in controlled_spaces.items()
        if value_type == "multi_label" and values
    }
    if documented_multi_labels != expected_multi_labels:
        errors.append(
            "multi_label value-space coverage differs: "
            f"missing={sorted(expected_multi_labels - documented_multi_labels)}, "
            f"extra={sorted(documented_multi_labels - expected_multi_labels)}"
        )


def _check_registries(errors: list[str]) -> None:
    style_registry = _load_json("references/style-registry.json", errors)
    style_evidence_rules = _load_json("references/style-evidence-rules.json", errors)
    field_registry = _load_json("references/field-registry.json", errors)
    tag_relations = _load_json("references/tag-relations.json", errors)
    combination_presets = _load_json("references/style-combination-presets.json", errors)
    value_normalization = _load_json("references/value-normalization.json", errors)
    manifest = _load_json("manifest.json", errors)
    if not all(
        isinstance(item, dict)
        for item in (
            style_registry,
            style_evidence_rules,
            field_registry,
            tag_relations,
            combination_presets,
            value_normalization,
            manifest,
        )
    ):
        return
    expected_version = manifest.get("knowledge_base_version")
    for name, registry in (
        ("style", style_registry),
        ("style-evidence", style_evidence_rules),
        ("field", field_registry),
        ("tag-relations", tag_relations),
        ("combination-presets", combination_presets),
        ("value-normalization", value_normalization),
    ):
        if registry.get("knowledge_base_version") != expected_version:
            errors.append(f"{name} registry knowledge_base_version mismatch")

    field_ids = {
        str(item.get("field_id"))
        for item in field_registry.get("fields", [])
        if isinstance(item, dict) and item.get("field_id")
    }
    aliases = value_normalization.get("field_value_aliases")
    relation_fields = value_normalization.get("relation_token_fields")
    ordinal_buckets = value_normalization.get("ordinal_buckets")
    if not isinstance(aliases, dict) or any(
        field_id not in field_ids or not isinstance(mapping, dict)
        for field_id, mapping in aliases.items()
    ):
        errors.append("value-normalization field aliases must reference registry fields")
    if (
        not isinstance(relation_fields, list)
        or len(relation_fields) != len(set(relation_fields))
        or any(field_id not in field_ids for field_id in relation_fields)
    ):
        errors.append("value-normalization relation fields are invalid")
    if ordinal_buckets != [0, 25, 50, 75, 100]:
        errors.append("value-normalization ordinal buckets must be 0/25/50/75/100")

    if "parents" in style_registry:
        errors.append("flat style registry must not contain parents")
    styles = [item for item in style_registry.get("styles", []) if isinstance(item, dict)]
    style_ids = [item.get("style_id") for item in styles]
    if len(style_ids) != len(set(style_ids)):
        errors.append("style registry contains duplicate style_id")
    active = [item for item in styles if item.get("status") == "active"]
    if len(active) != 38:
        errors.append(f"style registry must contain 38 active styles, got {len(active)}")
    for style in active:
        if "parent_style_id" in style:
            errors.append(f"style {style.get('style_id')} must not contain parent_style_id")
        if not style.get("confusion_groups"):
            errors.append(f"active style {style.get('style_id')} has no confusion group")

        if style.get("tag_kind") not in {"atomic", "composite", "identity"}:
            errors.append(f"style {style.get('style_id')} has invalid tag_kind")
        facet_ids = style.get("facet_ids")
        if (
            not isinstance(facet_ids, list)
            or not facet_ids
            or not all(isinstance(item, str) and item for item in facet_ids)
            or len(facet_ids) != len(set(facet_ids))
        ):
            errors.append(f"style {style.get('style_id')} has invalid facet_ids")
        weight = style.get("similarity_weight")
        if (
            not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not 0 <= weight <= 1
        ):
            errors.append(f"style {style.get('style_id')} has invalid similarity_weight")
        expected_weight = 1 if style.get("tag_kind") == "atomic" else 0
        if weight != expected_weight:
            errors.append(
                f"style {style.get('style_id')} tag_kind={style.get('tag_kind')!r} "
                f"requires similarity_weight={expected_weight}"
            )

    _check_style_evidence_rules(
        active=active,
        errors=errors,
        style_evidence_rules=style_evidence_rules,
    )

    from validate_output import validate_registries, validate_tag_relations

    active_by_id = {str(item.get("style_id")): item for item in active}
    registry_errors, _, _, _, _, _ = validate_registries(
        style_registry,
        field_registry,
        str(expected_version) if expected_version is not None else None,
    )
    errors.extend(f"registry contract: {item}" for item in registry_errors)
    neoretro_policy = active_by_id.get("NeoRetro", {}).get("cue_family_policy")
    if not isinstance(neoretro_policy, dict):
        errors.append("NeoRetro must declare cue_family_policy")
    else:
        if (
            neoretro_policy.get("min_distinct_families") != 2
            or neoretro_policy.get("expressive_gate")
            != {"field_id": "DET-17", "allowed_values": ["历史造型化"]}
            or "required_expressive_field_ids" in neoretro_policy
        ):
            errors.append(
                "NeoRetro cue policy must require two families and DET-17=历史造型化"
            )
    relation_errors, max_tags, facet_ids, default_pair, pair_relations, dependencies = validate_tag_relations(
        tag_relations,
        active_by_id,
        str(expected_version) if expected_version is not None else None,
    )
    errors.extend(f"tag relation contract: {item}" for item in relation_errors)
    if max_tags != 3:
        errors.append("tag-relations max_confirmed_tags must be exactly 3")
    if not facet_ids:
        errors.append("tag-relations must define searchable facets")
    schema = _load_json("schemas/design-dna-output.schema.json", errors)
    if isinstance(schema, dict):
        schema_style_ids = schema.get("$defs", {}).get("styleId", {}).get("enum", [])
        active_style_ids = [item.get("style_id") for item in active]
        if (
            not isinstance(schema_style_ids, list)
            or len(schema_style_ids) != 38
            or len(schema_style_ids) != len(set(schema_style_ids))
            or set(schema_style_ids) != set(active_style_ids)
        ):
            errors.append("schema styleId enum must contain exactly the 38 active registry styles")
        style_result_schema = schema.get("$defs", {}).get("styleResult", {}).get("properties", {})
        if style_result_schema.get("style_candidates", {}).get("maxItems") != 5:
            errors.append("schema style_candidates maxItems must be exactly 5")
    if not pair_relations:
        errors.append("tag-relations must define at least one explicit pair relation")
    if default_pair.get("same_region_coexistence") != "independent_evidence":
        errors.append(
            "default conditional relation must use same_region_coexistence=independent_evidence"
        )
    forbidden_relation_ids = {f"PR-{number:03d}" for number in range(15, 21)}
    independent_relation_ids = {f"PR-{number:03d}" for number in range(21, 24)}
    for relation in pair_relations.values():
        conflict_facets = relation.get("conflict_facet_ids")
        if relation.get("relation") == "conditional" and (
            not isinstance(conflict_facets, list) or not conflict_facets
        ):
            errors.append(
                f"conditional relation {relation.get('relation_id')} lacks conflict_facet_ids"
            )
        relation_id = relation.get("relation_id")
        expected_mode = (
            "forbidden"
            if relation_id in forbidden_relation_ids
            else "independent_evidence"
            if relation_id in independent_relation_ids
            else None
        )
        if expected_mode is not None and relation.get("same_region_coexistence") != expected_mode:
            errors.append(
                f"conditional relation {relation_id} must use same_region_coexistence={expected_mode}"
            )
    for dependency in dependencies:
        if dependency.get("target_quantifier") not in {"any", "all"}:
            errors.append(
                f"tag dependency {dependency.get('relation_id')} lacks target_quantifier any/all"
            )
    field_ids = {
        item.get("field_id")
        for item in field_registry.get("fields", [])
        if isinstance(item, dict) and isinstance(item.get("field_id"), str)
    }
    _check_presets(
        active=active,
        combination_presets=combination_presets,
        errors=errors,
        schema=schema,
    )

    knowledge_base = _check_style_documents(
        active=active,
        errors=errors,
        field_ids=field_ids,
        styles=styles,
    )

    _check_field_documents(
        active=active,
        errors=errors,
        field_registry=field_registry,
        knowledge_base=knowledge_base,
    )
