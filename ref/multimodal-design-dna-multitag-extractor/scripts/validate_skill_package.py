#!/usr/bin/env python3
"""Validate package structure, synchronized versions, assets, and examples."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# 包校验必须只读；导入本地校验模块时也不生成 __pycache__。
sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILL_VERSION = "1.3.0"
EXPECTED_SCHEMA_VERSION = "design_dna_multitag_extraction_v1.1"
EXPECTED_MODEL_SCHEMA_VERSION = "design_dna_multitag_observation_v1"
EXPECTED_KNOWLEDGE_BASE_VERSION = "4.1"
REQUIRED = [
    "SKILL.md",
    "manifest.json",
    "references/extraction-protocol.zh-CN.md",
    "references/output-contract.zh-CN.md",
    "references/design-dna-knowledge-base.zh-CN.md",
    "references/knowledge-index.zh-CN.md",
    "references/category-adaptation.zh-CN.md",
    "references/novel-dna-governance.zh-CN.md",
    "references/style-registry.json",
    "references/model-reference-bundle.json",
    "references/style-combination-presets.json",
    "references/field-registry.json",
    "references/tag-relations.json",
    "schemas/design-dna-output.schema.json",
    "schemas/design-dna-model-output.schema.json",
    "scripts/derive_style_presets.py",
    "scripts/compile_model_output.py",
    "scripts/build_observation_schema.py",
    "scripts/build_model_reference_bundle.py",
    "scripts/build_model_output_schema.py",
    "scripts/validate_output.py",
    "scripts/save_result.py",
    "scripts/build_prompt_bundle.py",
    "scripts/build_knowledge_index.py",
    "evals/cases.jsonl",
    "evals/preset-derivation-cases.json",
    "evals/rubric.zh-CN.md",
    "examples/smartphone-rear.example.json",
    "examples/apparel.example.json",
    "examples/smartphone-red-multitag.example.json",
    "checksums.sha256",
]


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for key in ("name", "description", "version", "schema-version", "knowledge-base-version"):
        found = re.search(rf"^\s*{re.escape(key)}:\s*(.+)$", match.group(1), re.M)
        if found:
            result[key] = found.group(1).strip().strip("\"'")
    return result


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


def _controlled_value_spaces(knowledge_base: str) -> dict[str, tuple[str, set[str]]]:
    """读取知识库中 enum 与 multi_label 的显式值域。"""
    section = knowledge_base.split("## 四、规范字段定义", 1)[-1].split(
        "## 五、别名、合并与派生", 1
    )[0]
    spaces: dict[str, tuple[str, set[str]]] = {}
    for match in re.finditer(
        r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| (.*?) \| .*? \| .*? \| .*? \|$",
        section,
        re.M,
    ):
        field_id, description = match.groups()
        type_match = re.search(r"；(enum|multi_label)(?:\s*/\s*(.*))?$", description)
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


def _check_versions(errors: list[str]) -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    metadata = _frontmatter(skill)
    if not metadata:
        errors.append("SKILL.md missing YAML frontmatter")
        return
    name = metadata.get("name", "")
    if name != ROOT.name:
        errors.append(f"frontmatter name {name!r} must match directory {ROOT.name!r}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("frontmatter name violates Agent Skills naming constraints")
    if not metadata.get("description"):
        errors.append("frontmatter missing non-empty description")
    expected_frontmatter = {
        "version": EXPECTED_SKILL_VERSION,
        "schema-version": EXPECTED_SCHEMA_VERSION,
        "knowledge-base-version": EXPECTED_KNOWLEDGE_BASE_VERSION,
    }
    for key, expected_value in expected_frontmatter.items():
        if metadata.get(key) != expected_value:
            errors.append(f"SKILL {key}={metadata.get(key)!r}, expected {expected_value!r}")

    manifest = _load_json("manifest.json", errors)
    schema = _load_json("schemas/design-dna-output.schema.json", errors)
    model_schema = _load_json("schemas/design-dna-model-output.schema.json", errors)
    if not all(isinstance(item, dict) for item in (manifest, schema, model_schema)):
        return
    expected = {
        "name": name,
        "version": metadata.get("version"),
        "schema_version": metadata.get("schema-version"),
        "knowledge_base_version": metadata.get("knowledge-base-version"),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest {key}={manifest.get(key)!r} != SKILL {value!r}")
    if manifest.get("version") != EXPECTED_SKILL_VERSION:
        errors.append(f"manifest version must be {EXPECTED_SKILL_VERSION}")
    if manifest.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        errors.append(f"manifest schema_version must be {EXPECTED_SCHEMA_VERSION}")
    if manifest.get("knowledge_base_version") != EXPECTED_KNOWLEDGE_BASE_VERSION:
        errors.append(f"manifest knowledge_base_version must be {EXPECTED_KNOWLEDGE_BASE_VERSION}")
    if manifest.get("model_output_schema") != "schemas/design-dna-model-output.schema.json":
        errors.append("manifest model_output_schema must reference the model-only schema")

    schema_const = schema.get("properties", {}).get("schema_version", {}).get("const")
    if schema_const != manifest.get("schema_version"):
        errors.append(f"schema const {schema_const!r} != manifest schema_version")
    kb_schema_const = schema.get("properties", {}).get("knowledge_base_version", {}).get("const")
    if kb_schema_const != manifest.get("knowledge_base_version"):
        errors.append(f"schema knowledge_base_version const {kb_schema_const!r} != manifest")
    if manifest.get("model_output_schema_version") != EXPECTED_MODEL_SCHEMA_VERSION:
        errors.append("manifest model_output_schema_version is not the lean observation contract")
    if (
        model_schema.get("properties", {}).get("schema_version", {}).get("const")
        != EXPECTED_MODEL_SCHEMA_VERSION
        or model_schema.get("properties", {}).get("knowledge_base_version", {}).get("const")
        != manifest.get("knowledge_base_version")
    ):
        errors.append("model output schema must use observation v1 and the manifest KB version")
    kb = (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    version_match = re.search(r"知识库版本\*\*：\s*([^\s]+)", kb)
    kb_version = version_match.group(1) if version_match else None
    if kb_version != manifest.get("knowledge_base_version"):
        errors.append(f"knowledge base version {kb_version!r} != manifest")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value in (manifest.get("version"), manifest.get("schema_version"), manifest.get("knowledge_base_version")):
        if value and str(value) not in readme:
            errors.append(f"README missing current version {value!r}")


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
        "classification_status",
        "style_tags",
        "derived_style_presets",
        "candidate_ranking",
        "pairwise_arbitrations",
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
    confirmed_observation = model_definitions.get("confirmedStyleObservation", {})
    forbidden_model_fields = {
        "label_en",
        "label_zh",
        "aliases",
        "tag_kind",
        "facet_ids",
        "evidence_refs",
        "rule_coverage",
    }
    if forbidden_model_fields.intersection(confirmed_observation.get("properties", {})):
        errors.append("confirmed style observations contain host-compiled metadata")
    if set(result_properties.get("classification_status", {}).get("enum", [])) != {
        "confirmed",
        "unclassified",
    }:
        errors.append("schema classification_status must only allow confirmed/unclassified")
    if result_properties.get("style_tags", {}).get("maxItems") != 3:
        errors.append("schema style_tags must cap confirmed labels at 3")
    if result_properties.get("candidate_ranking", {}).get("minItems") != 1:
        errors.append("schema candidate_ranking must contain at least one ranked candidate")
    if result_properties.get("pairwise_arbitrations", {}).get("maxItems") != 3:
        errors.append("schema pairwise_arbitrations must cap C(3,2) at 3")
    if result_properties.get("derived_style_presets", {}).get("maxItems") != 12:
        errors.append("schema derived_style_presets must cap registered presets at 12")
    single_tag_rule = next(
        (
            rule
            for rule in style_result.get("allOf", [])
            if rule.get("if", {})
            .get("properties", {})
            .get("style_tags", {})
            == {"minItems": 1, "maxItems": 1}
        ),
        {},
    )
    if (
        single_tag_rule.get("then", {})
        .get("properties", {})
        .get("style_tags", {})
        .get("items", {})
        .get("properties", {})
        .get("dominance", {})
        .get("const")
        != 1
    ):
        errors.append("schema single style tag must require dominance=1")

    identity_fields = {"style_id", "label_en", "label_zh", "aliases", "tag_kind", "facet_ids"}
    forbidden_hierarchy = {"parent_style_id", "level_1", "level_2"}
    style_tag = definitions.get("styleTag", {})
    style_tag_properties = set(style_tag.get("properties", {}))
    if not identity_fields.issubset(style_tag_properties):
        errors.append("schema styleTag is missing flat identity/facet fields")
    if style_tag_properties.intersection(forbidden_hierarchy):
        errors.append("schema styleTag must not expose parent/level hierarchy fields")
    required_tag_fields = {
        *identity_fields,
        "match_score",
        "confidence",
        "dominance",
        "regions",
        "hard_rule_passed",
        "rule_coverage",
        "color_requirement",
        "core_feature_hits",
        "auxiliary_feature_hits",
        "missing_required_items",
        "exclusion_hits",
        "evidence_refs",
    }
    if set(style_tag.get("required", [])) != required_tag_fields:
        errors.append("schema styleTag required fields are incomplete or contain legacy fields")
    if style_tag.get("properties", {}).get("confidence", {}).get("minimum") != 0.75:
        errors.append("schema confirmed styleTag confidence must have minimum 0.75")
    coverage_rules = (
        style_tag.get("properties", {}).get("rule_coverage", {}).get("allOf", [])
    )
    confirmed_coverage = (
        coverage_rules[1].get("properties", {})
        if isinstance(coverage_rules, list)
        and len(coverage_rules) > 1
        and isinstance(coverage_rules[1], dict)
        else {}
    )
    if (
        confirmed_coverage.get("applicable_rule_count", {}).get("minimum") != 1
        or confirmed_coverage.get("passed_rule_count", {}).get("minimum") != 1
    ):
        errors.append(
            "schema confirmed styleTag must require applicable_rule_count>=1 and passed_rule_count>=1"
        )

    candidate = definitions.get("styleCandidate", {})
    candidate_properties = set(candidate.get("properties", {}))
    if not identity_fields.issubset(candidate_properties) or candidate_properties.intersection(forbidden_hierarchy):
        errors.append("schema styleCandidate identity must be flat and facet-aware")
    if "candidate_status" not in candidate.get("required", []):
        errors.append("schema styleCandidate must require candidate_status")
    candidate_rules = candidate.get("allOf", [])
    confirmed_rule = next(
        (
            rule
            for rule in candidate_rules
            if rule.get("if", {}).get("properties", {}).get("candidate_status", {}).get("const")
            == "confirmed"
        ),
        {},
    )
    confirmed_properties = confirmed_rule.get("then", {}).get("properties", {})
    if (
        confirmed_properties.get("confidence", {}).get("minimum") != 0.75
        or confirmed_properties.get("hard_rule_passed", {}).get("const") is not True
    ):
        errors.append("schema confirmed candidate must require confidence>=0.75 and hard_rule_passed=true")
    nonconfirmed_rule = next(
        (
            rule
            for rule in candidate_rules
            if set(
                rule.get("if", {})
                .get("properties", {})
                .get("candidate_status", {})
                .get("enum", [])
            )
            == {"provisional", "rejected"}
            and "hard_rule_passed"
            not in rule.get("if", {}).get("properties", {})
        ),
        {},
    )
    nonconfirmed_properties = nonconfirmed_rule.get("then", {}).get("properties", {})
    if nonconfirmed_properties.get("dominance", {}).get("const") != 0:
        errors.append("schema provisional/rejected candidate must require dominance=0")
    if "hard_rule_passed" in nonconfirmed_properties:
        errors.append("schema provisional/rejected candidate must allow either hard-rule boolean")
    hard_conflict_rule = next(
        (
            rule
            for rule in candidate_rules
            if rule.get("if", {}).get("properties", {}).get("hard_rule_passed", {}).get("const")
            is True
            and set(
                rule.get("if", {})
                .get("properties", {})
                .get("candidate_status", {})
                .get("enum", [])
            )
            == {"provisional", "rejected"}
        ),
        {},
    )
    if (
        hard_conflict_rule.get("then", {})
        .get("properties", {})
        .get("main_conflicts", {})
        .get("minItems")
        != 1
    ):
        errors.append("schema non-confirmed hard-pass candidate must require main_conflicts")
    pairwise = definitions.get("pairwiseArbitration", {})
    expected_pair_fields = {
        "style_id_a",
        "style_id_b",
        "relation",
        "scope",
        "decision",
        "reason",
        "evidence_refs",
    }
    if set(pairwise.get("required", [])) != expected_pair_fields:
        errors.append("schema pairwiseArbitration fields are incomplete")


def _check_examples_and_evals(errors: list[str]) -> None:
    example_payloads: list[dict[str, Any]] = []
    for example in sorted((ROOT / "examples").glob("*.json")):
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_output.py"), str(example)],
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            errors.append(f"example failed validation: {example.name}\n{process.stdout}{process.stderr}")
        payload = _load_json(str(example.relative_to(ROOT)), errors)
        if isinstance(payload, dict):
            example_payloads.append(payload)

    if not any(
        len(item.get("style_result", {}).get("style_tags", [])) >= 2
        for item in example_payloads
    ):
        errors.append("examples must include at least one valid multi-tag pairwise arbitration")
    for item in example_payloads:
        style_result = item.get("style_result", {})
        tag_count = len(style_result.get("style_tags", []))
        pair_count = len(style_result.get("pairwise_arbitrations", []))
        if pair_count != tag_count * (tag_count - 1) // 2:
            errors.append("example pairwise_arbitrations must contain exactly C(n,2) records")

    model_schema = _load_json("schemas/design-dna-model-output.schema.json", errors)
    if isinstance(model_schema, dict):
        from jsonschema import Draft202012Validator

        for payload in example_payloads:
            if not list(Draft202012Validator(model_schema).iter_errors(payload)):
                errors.append("lean model schema must reject a complete final-result example")

    style_registry = _load_json("references/style-registry.json", errors)
    active_style_ids = {
        item.get("style_id")
        for item in (style_registry or {}).get("styles", [])
        if isinstance(item, dict) and item.get("status") == "active"
    }
    combination_presets = _load_json("references/style-combination-presets.json", errors)
    preset_cases = _load_json("evals/preset-derivation-cases.json", errors)
    if isinstance(combination_presets, dict):
        from derive_style_presets import compute_derived_style_presets, write_derived_style_presets

        registered_preset_ids = {
            item.get("preset_id")
            for item in combination_presets.get("presets", [])
            if isinstance(item, dict)
        }
        for payload in example_payloads:
            style_result = payload.get("style_result", {})
            style_ids = [
                item.get("style_id")
                for item in style_result.get("style_tags", [])
                if isinstance(item, dict)
            ]
            expected_derived = compute_derived_style_presets(style_ids, combination_presets)
            if style_result.get("derived_style_presets") != expected_derived:
                errors.append("example derived_style_presets differs from deterministic derivation")
        if not isinstance(preset_cases, list) or not preset_cases:
            errors.append("preset derivation evals must be a non-empty array")
        else:
            case_ids = [item.get("id") for item in preset_cases if isinstance(item, dict)]
            if len(case_ids) != len(preset_cases) or len(case_ids) != len(set(case_ids)):
                errors.append("preset derivation eval IDs must be unique")
            for case in preset_cases:
                if not isinstance(case, dict):
                    errors.append("preset derivation eval entries must be objects")
                    continue
                style_ids = case.get("style_ids")
                expected_ids = case.get("expected_preset_ids")
                if (
                    not isinstance(style_ids, list)
                    or not all(item in active_style_ids for item in style_ids)
                    or not isinstance(expected_ids, list)
                    or not all(item in registered_preset_ids for item in expected_ids)
                ):
                    errors.append(f"preset derivation eval {case.get('id')} has invalid IDs")
                    continue
                actual_ids = [
                    item["preset_id"]
                    for item in compute_derived_style_presets(style_ids, combination_presets)
                ]
                if actual_ids != expected_ids:
                    errors.append(
                        f"preset derivation eval {case.get('id')} expected {expected_ids}, got {actual_ids}"
                    )

            forged = copy.deepcopy(example_payloads[0]) if example_payloads else None
            if isinstance(forged, dict):
                forged["style_result"]["derived_style_presets"] = [
                    {
                        "preset_id": "CyberAesthetic",
                        "label_en": "forged",
                        "label_zh": "伪造",
                        "matched_style_ids": ["CyberNeon"],
                    }
                ]
                write_derived_style_presets(forged, combination_presets)
                if forged["style_result"]["derived_style_presets"] != compute_derived_style_presets(
                    [
                        item.get("style_id")
                        for item in forged["style_result"].get("style_tags", [])
                        if isinstance(item, dict)
                    ],
                    combination_presets,
                ):
                    errors.append("preset derivation must overwrite forged model values")
    cases_path = ROOT / "evals/cases.jsonl"
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(cases_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=_reject_nonfinite_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
            errors.append(f"evals/cases.jsonl:{line_number}: {message}")
            continue
        if not isinstance(value, dict) or not value.get("id"):
            errors.append(f"evals/cases.jsonl:{line_number}: case must be object with id")
            continue
        cases.append(value)
        referenced_styles = list(value.get("styles_under_test", []))
        raw_expected = value.get("expected")
        if raw_expected is not None and not isinstance(raw_expected, dict):
            errors.append(f"evals/cases.jsonl:{line_number}: expected must be an object when present")
            expected: dict[str, Any] | None = None
        else:
            expected = raw_expected
        if expected is not None:
            forbidden_expected = sorted(
                key for key in ("primary_style_id", "secondary_style_ids") if key in expected
            )
            if forbidden_expected:
                errors.append(
                    f"evals/cases.jsonl:{line_number}: legacy expected fields {forbidden_expected} are forbidden"
                )
            classification = expected.get("classification_status")
            if classification not in {"confirmed", "unclassified"}:
                errors.append(
                    f"evals/cases.jsonl:{line_number}: classification_status must be confirmed/unclassified"
                )
            style_tag_ids = expected.get("style_tag_ids")
            reject_style_ids = expected.get("reject_style_ids")
            provisional_ids = expected.get("provisional_candidate_ids", [])
            for key, values in (
                ("style_tag_ids", style_tag_ids),
                ("reject_style_ids", reject_style_ids),
                ("provisional_candidate_ids", provisional_ids),
            ):
                if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                    errors.append(f"evals/cases.jsonl:{line_number}: {key} must be a string array")
            if isinstance(style_tag_ids, list):
                if classification == "confirmed" and not 1 <= len(style_tag_ids) <= 3:
                    errors.append(
                        f"evals/cases.jsonl:{line_number}: confirmed expects 1..3 style_tag_ids"
                    )
                if classification == "unclassified" and style_tag_ids:
                    errors.append(
                        f"evals/cases.jsonl:{line_number}: unclassified requires style_tag_ids=[]"
                    )
                referenced_styles.extend(style_tag_ids)
            if isinstance(reject_style_ids, list):
                referenced_styles.extend(reject_style_ids)
            if isinstance(provisional_ids, list):
                referenced_styles.extend(provisional_ids)
        unknown_styles = sorted({item for item in referenced_styles if item not in active_style_ids})
        if unknown_styles:
            errors.append(f"evals/cases.jsonl:{line_number}: unknown active styles {unknown_styles}")

    case_ids = [str(item.get("id")) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("evals/cases.jsonl contains duplicate case IDs")
    triggered_case_ids = {str(item.get("id")) for item in cases if item.get("should_trigger") is True}
    expected_triggered_case_ids = {
        "MT-01-compatible-kinetic-color",
        "MT-02-compatible-natural-biomorphic",
        "MT-03-conditional-same-color",
        "MT-04-exclusive-minimalism",
        "MT-05-conditional-independent-ornament",
    }
    if len(cases) != 80 or triggered_case_ids != expected_triggered_case_ids:
        errors.append(
            "eval corpus must contain 80 cases with only MT-01..MT-05 marked should_trigger=true"
        )
    expected_coverage = {
        (f"CG-{number:02d}", kind)
        for number in range(1, 9)
        for kind in ("positive", "boundary", "negative")
    }
    actual_coverage = {
        (str(item.get("confusion_group_id")), str(item.get("case_type")))
        for item in cases
        if item.get("suite") == "confusion"
    }
    missing_coverage = sorted(expected_coverage - actual_coverage)
    if missing_coverage:
        errors.append(f"evals missing confusion coverage: {missing_coverage}")
    red_car = next((item for item in cases if item.get("id") == "CG-05-boundary-red-mini-car"), None)
    red_expected = red_car.get("expected", {}) if isinstance(red_car, dict) else {}
    red_rejects = set(red_expected.get("reject_style_ids", []))
    if red_expected.get("style_tag_ids") != ["SaturatedBold"] or not {
        "KineticEnergy",
        "NeoRetro",
        "BiomorphicForm",
    }.issubset(red_rejects):
        errors.append(
            "red mini-car regression must confirm only SaturatedBold and reject KineticEnergy/NeoRetro/BiomorphicForm"
        )

    # 两个定向变异防止值域和派生依赖校验在后续维护中静默失效。
    from validate_output import validate_semantics

    knowledge_base = (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    field_registry = _load_json("references/field-registry.json", errors)
    tag_relations = _load_json("references/tag-relations.json", errors)
    if not all(isinstance(item, dict) for item in (style_registry, field_registry, tag_relations)):
        return

    phone = _load_json("examples/smartphone-rear.example.json", errors)
    if isinstance(phone, dict):
        forged_presets = copy.deepcopy(phone)
        forged_presets["style_result"]["derived_style_presets"] = [
            {
                "preset_id": "CyberAesthetic",
                "label_en": "Cyber Aesthetic",
                "label_zh": "赛博风格",
                "matched_style_ids": ["CyberNeon"],
            }
        ]
        mutation_errors, _ = validate_semantics(
            forged_presets,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
            combination_presets if isinstance(combination_presets, dict) else None,
        )
        if not any("must equal deterministic Python derivation" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: forged derived style preset was accepted")

        invalid_label = copy.deepcopy(phone)
        for module in invalid_label.get("design_elements", {}).get("extended_dna_modules", []):
            for element in module.get("elements", []):
                if element.get("field_id") == "DEV-05":
                    element["value"] = ["__INVALID__"]
        mutation_errors, _ = validate_semantics(
            invalid_label, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("outside the controlled domain" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: invalid multi_label value was accepted")

        # 通用表面字段不得绕过 NeoRetro 的线索族和表达角色门槛。
        generic_retro = copy.deepcopy(phone)
        neoretro = next(
            item for item in style_registry["styles"] if item.get("style_id") == "NeoRetro"
        )
        tag = generic_retro["style_result"]["style_tags"][0]
        candidate = generic_retro["style_result"]["candidate_ranking"][0]
        for item in (tag, candidate):
            item.update(
                style_id="NeoRetro",
                label_en=neoretro["display_name_en"],
                label_zh=neoretro["display_name_zh"],
                aliases=neoretro["aliases"],
                tag_kind=neoretro["tag_kind"],
                facet_ids=neoretro["facet_ids"],
            )
        tag["core_feature_hits"] = ["CMF-01：普通视觉材质候选。"]
        tag["auxiliary_feature_hits"] = ["CMF-04：普通材质对比。"]
        mutation_errors, _ = validate_semantics(
            generic_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("cue_family_policy expressive_gate requires core" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: generic NeoRetro cues were accepted")

        # 两个 cue family 不能用同一证据换字段；DET-17 必须是受控的“历史造型化”。
        same_evidence_retro = copy.deepcopy(generic_retro)
        same_evidence_retro["module_applicability"]["applicable_modules"].append(
            {
                "module_id": "DNA-M09",
                "module_name": "细节语法",
                "reason": "定向变异门禁。",
            }
        )
        same_evidence_retro["design_elements"]["extended_dna_modules"].append(
            {
                "module_id": "DNA-M09",
                "module_name": "细节语法",
                "elements": [
                    {
                        "field_id": "DET-08",
                        "field_name": "装饰线几何",
                        "source_path": "DNA-M09/DET-08",
                        "schema_source": "md_extension",
                        "value": {"role": "trim"},
                        "raw_visual_description": "可见包边轮廓。",
                        "value_type": "object",
                        "evidence_mode": "direct",
                        "region": "back_cover",
                        "applicability_status": "applicable",
                        "observability": "observed",
                        "computation_status": "not_requested",
                        "confidence": 0.9,
                        "evidence_refs": ["EV-003"],
                    },
                    {
                        "field_id": "DET-17",
                        "field_name": "细节语法角色",
                        "source_path": "DNA-M09/DET-17",
                        "schema_source": "md_extension",
                        "value": "历史造型化",
                        "raw_visual_description": "只按可见细节组合归入历史造型化语法，不推断年代。",
                        "value_type": "enum",
                        "evidence_mode": "inferred",
                        "region": "back_cover",
                        "applicability_status": "applicable",
                        "observability": "observed",
                        "computation_status": "computed",
                        "confidence": 0.9,
                        "evidence_refs": ["EV-003", "EV-004"],
                    },
                ],
            }
        )
        for module in same_evidence_retro["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "CMF-01":
                    element["confidence"] = 0.8
        same_evidence_retro["uncertain_fields"] = []
        same_evidence_retro["quality_summary"]["low_confidence_field_count"] = 0
        same_tag = same_evidence_retro["style_result"]["style_tags"][0]
        same_tag["core_feature_hits"] = [
            "CMF-01：异质视觉表面。",
            "DET-17：细节语法角色为历史造型化。",
        ]
        same_tag["auxiliary_feature_hits"] = ["DET-08：可见包边。"]
        same_tag["evidence_refs"] = ["EV-001", "EV-002", "EV-003", "EV-004"]
        mutation_errors, _ = validate_semantics(
            same_evidence_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("mutually unshared field evidence" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: NeoRetro cue families reused one evidence")

        valid_retro = copy.deepcopy(same_evidence_retro)
        valid_retro["quality_summary"]["mean_confidence"] = 0.856
        for module in valid_retro["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "DET-08":
                    element["evidence_refs"] = ["EV-002"]
        valid_errors, _ = validate_semantics(
            valid_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if valid_errors:
            errors.append(
                "validator mutation gate failed: NeoRetro with independent surface/hardware evidence "
                f"and DET-17=历史造型化 was rejected: {valid_errors}"
            )

        wrong_expressive_role = copy.deepcopy(valid_retro)
        for module in wrong_expressive_role["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "DET-17":
                    element["value"] = "当代技术化"
        mutation_errors, _ = validate_semantics(
            wrong_expressive_role, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("cue_family_policy expressive_gate requires core" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: NeoRetro accepted a non-historical DET-17 role")

    apparel = _load_json("examples/apparel.example.json", errors)
    if isinstance(apparel, dict):
        missing_dependency = copy.deepcopy(apparel)
        modules = missing_dependency.get("design_elements", {}).get("extended_dna_modules", [])
        color_module = next((item for item in modules if item.get("module_id") == "DNA-M06"), None)
        if isinstance(color_module, dict):
            color_module.setdefault("elements", []).append(
                {
                    "field_id": "CLR-20",
                    "field_name": "调色板结构",
                    "source_path": "DNA-M06/CLR-20",
                    "schema_source": "md_extension",
                    "value": "单主色",
                    "raw_visual_description": "仅由已有主色记录直接推导。",
                    "value_type": "enum",
                    "evidence_mode": "derived",
                    "region": "whole_object",
                    "applicability_status": "applicable",
                    "observability": "observed",
                    "computation_status": "computed",
                    "confidence": 0.9,
                    "evidence_refs": ["EV-003"],
                }
            )
            mutation_errors, _ = validate_semantics(
                missing_dependency, knowledge_base, style_registry, field_registry, tag_relations
            )
            if not any("missing usable derived sources" in item for item in mutation_errors):
                errors.append("validator mutation gate failed: derived field without sources was accepted")

    multitag = _load_json("examples/smartphone-red-multitag.example.json", errors)
    if isinstance(multitag, dict):
        def require_semantic_rejection(
            gate_name: str,
            payload: dict[str, Any],
            expected_fragment: str,
            *,
            styles: dict[str, Any] = style_registry,
            relations: dict[str, Any] = tag_relations,
        ) -> None:
            mutation_errors, _ = validate_semantics(
                payload,
                knowledge_base,
                styles,
                field_registry,
                relations,
            )
            if not any(expected_fragment in item for item in mutation_errors):
                errors.append(f"validator mutation gate failed: {gate_name} was accepted")

        outside_evidence = copy.deepcopy(multitag)
        outside_evidence["evidence"][0]["region"] = "__OUTSIDE_VISIBLE_REGIONS__"
        require_semantic_rejection(
            "evidence region outside visible_regions",
            outside_evidence,
            "outside target_object.visible_regions",
        )

        outside_element = copy.deepcopy(multitag)
        outside_element["design_elements"]["extended_dna_modules"][0]["elements"][0][
            "region"
        ] = "__OUTSIDE_VISIBLE_REGIONS__"
        require_semantic_rejection(
            "design-element region outside visible_regions",
            outside_element,
            "outside target_object.visible_regions",
        )

        low_style_confidence = copy.deepcopy(multitag)
        low_style_confidence["style_result"]["style_tags"][0]["confidence"] = 0.74
        low_style_confidence["style_result"]["candidate_ranking"][0]["confidence"] = 0.74
        require_semantic_rejection(
            "confirmed confidence below 0.75",
            low_style_confidence,
            "confidence must be >= 0.75",
        )

        low_core_confidence = copy.deepcopy(multitag)
        for module in low_core_confidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "CLR-01":
                    element["confidence"] = 0.74
        require_semantic_rejection(
            "confirmed style citing a low-confidence core DNA field",
            low_core_confidence,
            "CLR-01 confidence must be >=0.75 to support a confirmed style",
        )

        hard_pass_without_conflict = copy.deepcopy(multitag)
        rejected = hard_pass_without_conflict["style_result"]["candidate_ranking"][2]
        rejected["hard_rule_passed"] = True
        rejected["main_conflicts"] = []
        require_semantic_rejection(
            "non-confirmed hard pass without pair conflict",
            hard_pass_without_conflict,
            "requires non-empty main_conflicts",
        )

        unstable_tags = copy.deepcopy(multitag)
        unstable_tags["style_result"]["style_tags"].reverse()
        require_semantic_rejection(
            "unstable style-tag ordering",
            unstable_tags,
            "must use stable order (-dominance, -match_score, style_id)",
        )

        unstable_candidates = copy.deepcopy(multitag)
        unstable_candidates["style_result"]["candidate_ranking"][2]["match_score"] = 50
        unstable_candidates["style_result"]["candidate_ranking"][3]["match_score"] = 50
        require_semantic_rejection(
            "unstable candidate tie ordering",
            unstable_candidates,
            "must use stable order (-match_score, style_id)",
        )

        # 构造同区域、同冲突 facet、但 core 字段不同的条件关系，防止字段 ID 绕过互斥。
        conflict_case = copy.deepcopy(multitag)
        conflict_styles = copy.deepcopy(style_registry)
        refined_record = next(
            item
            for item in conflict_styles["styles"]
            if item.get("style_id") == "RefinedMinimalism"
        )
        refined_record["facet_ids"].append("color_optics")
        conflict_case["style_result"]["style_tags"][1]["facet_ids"].append("color_optics")
        conflict_case["style_result"]["candidate_ranking"][1]["facet_ids"].append(
            "color_optics"
        )
        conflict_relations = copy.deepcopy(tag_relations)
        conflict_relation = next(
            item
            for item in conflict_relations["pair_relations"]
            if set(item.get("style_ids", [])) == {"RefinedMinimalism", "SaturatedBold"}
        )
        conflict_relation.update(
            relation="conditional",
            scope="same_region_same_mechanism",
            conflict_facet_ids=["color_optics"],
            same_region_coexistence="forbidden",
        )
        conflict_case["style_result"]["pairwise_arbitrations"][0].update(
            relation="conditional",
            scope="same_region_same_mechanism",
        )
        require_semantic_rejection(
            "overlapping conditional conflict facet",
            conflict_case,
            "same_region_coexistence=forbidden",
            styles=conflict_styles,
            relations=conflict_relations,
        )

        independent_case = copy.deepcopy(conflict_case)
        independent_relations = copy.deepcopy(conflict_relations)
        independent_relation = next(
            item
            for item in independent_relations["pair_relations"]
            if set(item.get("style_ids", [])) == {"RefinedMinimalism", "SaturatedBold"}
        )
        independent_relation["same_region_coexistence"] = "independent_evidence"
        independent_errors, _ = validate_semantics(
            independent_case,
            knowledge_base,
            conflict_styles,
            field_registry,
            independent_relations,
        )
        if independent_errors:
            errors.append(
                "validator mutation gate failed: same-region conditional pair with independent "
                "core evidence was rejected"
            )

        reused_core_evidence = copy.deepcopy(independent_case)
        for module in reused_core_evidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") in {"DEV-03", "DEV-05"}:
                    element["evidence_refs"] = ["EV-003"]
        require_semantic_rejection(
            "same-region conditional pair reusing core evidence",
            reused_core_evidence,
            "mutually exclusive core field evidence",
            styles=conflict_styles,
            relations=independent_relations,
        )

        # 未显式登记且 facet 无交集的同区组合仍须执行默认独立证据门，不能换字段复用证据。
        default_reused_evidence = copy.deepcopy(multitag)
        default_relations = copy.deepcopy(tag_relations)
        default_relations["pair_relations"] = [
            relation
            for relation in default_relations["pair_relations"]
            if set(relation.get("style_ids", [])) != {"RefinedMinimalism", "SaturatedBold"}
        ]
        default_reused_evidence["style_result"]["pairwise_arbitrations"][0].update(
            relation="conditional",
            scope="same_region_same_mechanism",
        )
        for module in default_reused_evidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") in {"DEV-03", "DEV-05"}:
                    element["evidence_refs"] = ["EV-003"]
        require_semantic_rejection(
            "default same-region pair reusing core evidence across different fields",
            default_reused_evidence,
            "mutually exclusive core field evidence",
            relations=default_relations,
        )

        allowed_hard_pass = copy.deepcopy(multitag)
        allowed_candidate = allowed_hard_pass["style_result"]["candidate_ranking"][2]
        allowed_candidate["hard_rule_passed"] = True
        allowed_candidate["main_conflicts"] = ["与已确认标签存在成对冲突"]
        allowed_errors, _ = validate_semantics(
            allowed_hard_pass,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
        )
        if allowed_errors:
            errors.append(
                "validator mutation gate failed: non-confirmed hard pass with conflict was rejected"
            )

        zero_rule_tag = copy.deepcopy(multitag)
        zero_rule_tag["style_result"]["style_tags"][0]["rule_coverage"].update(
            applicable_rule_count=0,
            passed_rule_count=0,
        )
        require_semantic_rejection(
            "confirmed tag with zero applicable rules",
            zero_rule_tag,
            "applicable_rule_count>=1 and passed_rule_count>=1",
        )

    if isinstance(phone, dict):
        invalid_single_dominance = copy.deepcopy(phone)
        invalid_single_dominance["style_result"]["style_tags"][0]["dominance"] = 0.9
        invalid_single_dominance["style_result"]["candidate_ranking"][0]["dominance"] = 0.9
        mutation_errors, _ = validate_semantics(
            invalid_single_dominance,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
        )
        if not any("single confirmed tag requires dominance=1" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: single-tag dominance below 1 was accepted")


def _check_registries(errors: list[str]) -> None:
    style_registry = _load_json("references/style-registry.json", errors)
    field_registry = _load_json("references/field-registry.json", errors)
    tag_relations = _load_json("references/tag-relations.json", errors)
    combination_presets = _load_json("references/style-combination-presets.json", errors)
    manifest = _load_json("manifest.json", errors)
    if not all(
        isinstance(item, dict)
        for item in (style_registry, field_registry, tag_relations, combination_presets, manifest)
    ):
        return
    expected_version = manifest.get("knowledge_base_version")
    for name, registry in (
        ("style", style_registry),
        ("field", field_registry),
        ("tag-relations", tag_relations),
        ("combination-presets", combination_presets),
    ):
        if registry.get("knowledge_base_version") != expected_version:
            errors.append(f"{name} registry knowledge_base_version mismatch")

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
        if style_result_schema.get("style_tags", {}).get("maxItems") != max_tags:
            errors.append("schema style_tags maxItems differs from tag-relations max_confirmed_tags")
        expected_pair_cap = max_tags * (max_tags - 1) // 2
        if style_result_schema.get("pairwise_arbitrations", {}).get("maxItems") != expected_pair_cap:
            errors.append("schema pairwise_arbitrations maxItems differs from C(max_confirmed_tags,2)")
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


def _check_scripts(errors: list[str]) -> None:
    for script in sorted((ROOT / "scripts").glob("*.py")):
        try:
            source = script.read_text(encoding="utf-8")
            compile(source, str(script), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"python compile failed: {script.name}: {exc}")
    validator_source = (ROOT / "scripts/validate_output.py").read_text(encoding="utf-8")
    saver_source = (ROOT / "scripts/save_result.py").read_text(encoding="utf-8")
    package_source = (ROOT / "scripts/validate_skill_package.py").read_text(encoding="utf-8")
    if "parse_constant=" not in validator_source or "parse_constant=" not in package_source:
        errors.append("JSON validators must reject NaN/Infinity through parse_constant")
    if "parse_constant=" not in saver_source or "allow_nan=False" not in saver_source:
        errors.append("save_result must strictly read and write finite JSON numbers")
    if "write_derived_style_presets(data, preset_registry)" not in saver_source:
        errors.append("save_result must derive and overwrite combination presets before validation")

    from validate_output import reject_nonfinite_constant
    from save_result import _strict_json_loads

    for name, parser in (
        (
            "validate_output",
            lambda raw: json.loads(raw, parse_constant=reject_nonfinite_constant),
        ),
        ("save_result", _strict_json_loads),
    ):
        for raw in ('{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}'):
            try:
                parser(raw)
            except ValueError:
                continue
            errors.append(f"{name} accepted non-finite JSON: {raw}")


def _check_index(errors: list[str]) -> None:
    index = (ROOT / "references/knowledge-index.zh-CN.md").read_text(encoding="utf-8")
    if "约第 " in index or "未解析到字段" in index:
        errors.append("knowledge index contains unstable line numbers or unresolved fields")
    for required_id in ("PureMinimalism", "BiomorphicForm", "DNA-M01", "DNA-M15"):
        if required_id not in index:
            errors.append(f"knowledge index missing {required_id}")
    if "CyberAesthetic" in index or "查询组合预设" in index:
        errors.append("model-facing knowledge index must not expose host-only combination presets")
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_knowledge_index.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        errors.append(f"knowledge index is not generated from registries\n{process.stdout}{process.stderr}")
    model_schema_process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_model_output_schema.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if model_schema_process.returncode != 0:
        errors.append(
            "model output schema is not generated from the final schema\n"
            f"{model_schema_process.stdout}{model_schema_process.stderr}"
        )
    model_reference_process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_model_reference_bundle.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if model_reference_process.returncode != 0:
        errors.append(
            "model reference bundle is not generated from registries\n"
            f"{model_reference_process.stdout}{model_reference_process.stderr}"
        )


def _check_checksums(errors: list[str]) -> None:
    checksum_path = ROOT / "checksums.sha256"
    listed: set[str] = set()
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\s+\./(.+)", line)
        if not match:
            errors.append(f"checksums.sha256:{line_number}: malformed entry")
            continue
        expected, relative = match.groups()
        if relative in listed:
            errors.append(f"checksums.sha256:{line_number}: duplicate target {relative}")
            continue
        listed.add(relative)
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"checksum target missing: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"checksum mismatch: {relative}")

    expected_files = {
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file()
        and path != checksum_path
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }
    missing = sorted(expected_files - listed)
    unexpected = sorted(listed - expected_files)
    if missing:
        errors.append(f"checksums.sha256 missing package files: {missing}")
    if unexpected:
        errors.append(f"checksums.sha256 contains unexpected files: {unexpected}")


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")
    # 缺少单个资产不能让其余只读检查静默跳过；每项独立聚合故障，便于一次修完。
    for check in (
        _check_versions,
        _check_schema,
        _check_registries,
        _check_examples_and_evals,
        _check_scripts,
        _check_index,
        _check_checksums,
    ):
        try:
            check(errors)
        except Exception as exc:  # 缺失或损坏的前置资产也应转成包级错误，而非中止校验器。
            errors.append(f"{check.__name__} failed: {exc}")

    if errors:
        print(f"INVALID PACKAGE: {len(errors)} error(s)")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1
    print("VALID PACKAGE: structure, versions, schema, examples, evals, index, scripts, and checksums passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
