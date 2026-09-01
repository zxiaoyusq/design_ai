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
    "references/field-registry.json",
    "schemas/design-dna-output.schema.json",
    "scripts/validate_output.py",
    "scripts/build_prompt_bundle.py",
    "scripts/build_knowledge_index.py",
    "evals/cases.jsonl",
    "evals/rubric.zh-CN.md",
    "examples/smartphone-rear.example.json",
    "examples/apparel.example.json",
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
        return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
    except Exception as exc:  # 包级报告需要聚合全部错误。
        errors.append(f"invalid JSON in {relative_path}: {exc}")
        return None


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

    manifest = _load_json("manifest.json", errors)
    schema = _load_json("schemas/design-dna-output.schema.json", errors)
    if not isinstance(manifest, dict) or not isinstance(schema, dict):
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

    schema_const = schema.get("properties", {}).get("schema_version", {}).get("const")
    if schema_const != manifest.get("schema_version"):
        errors.append(f"schema const {schema_const!r} != manifest schema_version")
    kb_schema_const = schema.get("properties", {}).get("knowledge_base_version", {}).get("const")
    if kb_schema_const != manifest.get("knowledge_base_version"):
        errors.append(f"schema knowledge_base_version const {kb_schema_const!r} != manifest")
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
    if not isinstance(schema, dict):
        return
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
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


def _check_examples_and_evals(errors: list[str]) -> None:
    for example in sorted((ROOT / "examples").glob("*.json")):
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_output.py"), str(example)],
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            errors.append(f"example failed validation: {example.name}\n{process.stdout}{process.stderr}")

    style_registry = _load_json("references/style-registry.json", errors)
    active_style_ids = {
        item.get("style_id")
        for item in (style_registry or {}).get("styles", [])
        if isinstance(item, dict) and item.get("status") == "active"
    }
    cases_path = ROOT / "evals/cases.jsonl"
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(cases_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"evals/cases.jsonl:{line_number}: {exc.msg}")
            continue
        if not isinstance(value, dict) or not value.get("id"):
            errors.append(f"evals/cases.jsonl:{line_number}: case must be object with id")
            continue
        cases.append(value)
        referenced_styles = list(value.get("styles_under_test", []))
        expected = value.get("expected", {}) if isinstance(value.get("expected"), dict) else {}
        if expected.get("primary_style_id") is not None:
            referenced_styles.append(expected.get("primary_style_id"))
        referenced_styles.extend(expected.get("reject_style_ids", []))
        unknown_styles = sorted({item for item in referenced_styles if item not in active_style_ids})
        if unknown_styles:
            errors.append(f"evals/cases.jsonl:{line_number}: unknown active styles {unknown_styles}")

    case_ids = [str(item.get("id")) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("evals/cases.jsonl contains duplicate case IDs")
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
    if red_expected.get("primary_style_id") != "SaturatedBold" or not {
        "KineticEnergy",
        "NeoRetro",
        "BiomorphicForm",
    }.issubset(red_rejects):
        errors.append(
            "red mini-car regression must select SaturatedBold and reject KineticEnergy/NeoRetro/BiomorphicForm"
        )

    # 两个定向变异防止值域和派生依赖校验在后续维护中静默失效。
    from validate_output import validate_semantics

    knowledge_base = (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    field_registry = _load_json("references/field-registry.json", errors)
    if not isinstance(style_registry, dict) or not isinstance(field_registry, dict):
        return

    phone = _load_json("examples/smartphone-rear.example.json", errors)
    if isinstance(phone, dict):
        invalid_label = copy.deepcopy(phone)
        for module in invalid_label.get("design_elements", {}).get("extended_dna_modules", []):
            for element in module.get("elements", []):
                if element.get("field_id") == "DEV-05":
                    element["value"] = ["__INVALID__"]
        mutation_errors, _ = validate_semantics(
            invalid_label, knowledge_base, style_registry, field_registry
        )
        if not any("outside the controlled domain" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: invalid multi_label value was accepted")

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
                missing_dependency, knowledge_base, style_registry, field_registry
            )
            if not any("missing usable derived sources" in item for item in mutation_errors):
                errors.append("validator mutation gate failed: derived field without sources was accepted")


def _check_registries(errors: list[str]) -> None:
    style_registry = _load_json("references/style-registry.json", errors)
    field_registry = _load_json("references/field-registry.json", errors)
    manifest = _load_json("manifest.json", errors)
    if not all(isinstance(item, dict) for item in (style_registry, field_registry, manifest)):
        return
    expected_version = manifest.get("knowledge_base_version")
    for name, registry in (("style", style_registry), ("field", field_registry)):
        if registry.get("knowledge_base_version") != expected_version:
            errors.append(f"{name} registry knowledge_base_version mismatch")

    parents = style_registry.get("parents", [])
    parent_ids = [item.get("parent_style_id") for item in parents if isinstance(item, dict)]
    if len(parent_ids) != 6 or len(set(parent_ids)) != 6:
        errors.append("style registry must contain 6 unique parents")
    styles = [item for item in style_registry.get("styles", []) if isinstance(item, dict)]
    style_ids = [item.get("style_id") for item in styles]
    if len(style_ids) != len(set(style_ids)):
        errors.append("style registry contains duplicate style_id")
    active = [item for item in styles if item.get("status") == "active"]
    if len(active) != 31:
        errors.append(f"style registry must contain 31 active styles, got {len(active)}")
    for style in active:
        if style.get("parent_style_id") not in parent_ids:
            errors.append(f"style {style.get('style_id')} has unknown parent")
        if not style.get("confusion_groups"):
            errors.append(f"active style {style.get('style_id')} has no confusion group")
    deprecated = {item.get("style_id"): item for item in styles if item.get("status") == "deprecated"}
    if deprecated.get("QuietElegantLuxury", {}).get("replaced_by") != "RefinedMinimalism":
        errors.append("QuietElegantLuxury migration is missing")
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

    parent_by_display = {
        item.get("display_name"): item.get("parent_style_id")
        for item in parents
        if isinstance(item, dict)
    }
    documented_parents: dict[str, str | None] = {}
    current_parent: str | None = None
    for line in rule_text.splitlines():
        parent_match = re.match(r"^## 一级风格：\d+\.(.+)$", line)
        if parent_match:
            current_parent = parent_by_display.get(parent_match.group(1))
            continue
        style_match = re.match(r"^### ([A-Za-z0-9]+) — ", line)
        if style_match:
            documented_parents[style_match.group(1)] = current_parent
    for style in active:
        if documented_parents.get(str(style.get("style_id"))) != style.get("parent_style_id"):
            errors.append(f"style {style.get('style_id')} is under the wrong parent section")
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
    if len(fields) != 183:
        errors.append(f"canonical field count must be exactly 183, got {len(fields)}")
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
            errors.append(f"hard field {field.get('field_id')} must use direct evidence")
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


def _check_index(errors: list[str]) -> None:
    index = (ROOT / "references/knowledge-index.zh-CN.md").read_text(encoding="utf-8")
    if "约第 " in index or "未解析到字段" in index:
        errors.append("knowledge index contains unstable line numbers or unresolved fields")
    for required_id in ("PureMinimalism", "BiomorphicForm", "DNA-M01", "DNA-M15"):
        if required_id not in index:
            errors.append(f"knowledge index missing {required_id}")
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_knowledge_index.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        errors.append(f"knowledge index is not generated from registries\n{process.stdout}{process.stderr}")


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
    if not errors:
        _check_versions(errors)
        _check_schema(errors)
        _check_registries(errors)
        _check_examples_and_evals(errors)
        _check_scripts(errors)
        _check_index(errors)
        _check_checksums(errors)

    if errors:
        print(f"INVALID PACKAGE: {len(errors)} error(s)")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1
    print("VALID PACKAGE: structure, versions, schema, examples, evals, index, scripts, and checksums passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
