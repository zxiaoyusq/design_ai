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

from package_checks import _check_schema, _check_registries, _load_json, _reject_nonfinite_constant


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILL_VERSION = "3.0.2"
EXPECTED_SCHEMA_VERSION = "design_dna_multitag_extraction_v1.3"
EXPECTED_MODEL_SCHEMA_VERSION = "design_dna_multitag_observation_v3"
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
    "references/style-evidence-rules.json",
    "references/model-reference-bundle.json",
    "references/style-combination-presets.json",
    "references/field-registry.json",
    "references/value-normalization.json",
    "references/tag-relations.json",
    "schemas/design-dna-output.schema.json",
    "schemas/design-dna-model-output.schema.json",
    "scripts/derive_style_presets.py",
    "scripts/compile_model_output.py",
    "scripts/compilation_support.py",
    "scripts/compile_fields.py",
    "scripts/compile_styles.py",
    "scripts/dna_rules.py",
    "scripts/build_observation_schema.py",
    "scripts/build_model_reference_bundle.py",
    "scripts/build_model_output_schema.py",
    "scripts/validate_output.py",
    "scripts/validation_rules.py",
    "scripts/validate_fields.py",
    "scripts/validate_styles.py",
    "scripts/package_checks.py",
    "scripts/save_result.py",
    "scripts/build_prompt_bundle.py",
    "scripts/build_knowledge_index.py",
    "evals/cases.jsonl",
    "evals/preset-derivation-cases.json",
    "evals/rubric.zh-CN.md",
    "examples/smartphone-rear.example.json",
    "examples/apparel.example.json",
    "examples/smartphone-red-multitag.example.json",
    "tests/test_output_regressions.py",
    "tests/test_script_contracts.py",
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
        errors.append("model output schema must use the current observation contract and manifest KB version")
    kb = (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    version_match = re.search(r"知识库版本\*\*：\s*([^\s]+)", kb)
    kb_version = version_match.group(1) if version_match else None
    if kb_version != manifest.get("knowledge_base_version"):
        errors.append(f"knowledge base version {kb_version!r} != manifest")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for value in (manifest.get("version"), manifest.get("schema_version"), manifest.get("knowledge_base_version")):
        if value and str(value) not in readme:
            errors.append(f"README missing current version {value!r}")


def _check_examples_and_evals(errors: list[str]) -> None:
    example_payloads: list[dict[str, Any]] = []
    for example in sorted((ROOT / "examples").glob("*.json")):
        process = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/validate_output.py"), str(example)],
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            errors.append(f"example failed validation: {example.name}\n{process.stdout}{process.stderr}")
        payload = _load_json(str(example.relative_to(ROOT)), errors)
        if isinstance(payload, dict):
            example_payloads.append(payload)

    if not any(
        len(item.get("style_result", {}).get("style_candidates", [])) >= 2
        for item in example_payloads
    ):
        errors.append("examples must include at least one valid multi-candidate result")

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
                for item in style_result.get("style_candidates", [])
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
                        for item in forged["style_result"].get("style_candidates", [])
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
            style_candidate_ids = expected.get("style_candidate_ids")
            if (
                not isinstance(style_candidate_ids, list)
                or len(style_candidate_ids) > 5
                or not all(isinstance(item, str) for item in style_candidate_ids)
            ):
                errors.append(
                    f"evals/cases.jsonl:{line_number}: style_candidate_ids must contain 0..5 strings"
                )
            else:
                referenced_styles.extend(style_candidate_ids)
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
    if red_expected.get("style_candidate_ids") != ["SaturatedBold"]:
        errors.append(
            "red mini-car regression must output only the visually supported SaturatedBold candidate"
        )

    # 两个定向变异防止值域和派生依赖校验在后续维护中静默失效。
    process = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover",
         "-s", str(ROOT / "tests"), "-p", "test_*.py"],
        text=True, capture_output=True,
    )
    if process.returncode != 0:
        errors.append(f"package regression tests failed:\n{process.stdout}{process.stderr}")


def _check_scripts(errors: list[str]) -> None:
    for script in sorted([*(ROOT / "scripts").glob("*.py"), *(ROOT / "tests").glob("*.py")]):
        try:
            source = script.read_text(encoding="utf-8")
            compile(source, str(script), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"python compile failed: {script.name}: {exc}")
    # JSON 严格性和预设覆盖由 tests/test_script_contracts.py 验证真实入口行为。


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
        [sys.executable, "-B", str(ROOT / "scripts/build_knowledge_index.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        errors.append(f"knowledge index is not generated from registries\n{process.stdout}{process.stderr}")
    model_schema_process = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/build_model_output_schema.py"), "--check"],
        text=True,
        capture_output=True,
    )
    if model_schema_process.returncode != 0:
        errors.append(
            "model output schema is not generated from the final schema\n"
            f"{model_schema_process.stdout}{model_schema_process.stderr}"
        )
    model_reference_process = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/build_model_reference_bundle.py"), "--check"],
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
