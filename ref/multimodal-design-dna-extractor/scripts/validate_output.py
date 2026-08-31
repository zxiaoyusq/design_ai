#!/usr/bin/env python3
"""Validate design DNA extraction JSON against schema and semantic rules."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "design-dna-output.schema.json"
DEFAULT_KB = ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"ERROR: invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def iter_elements(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    design = data.get("design_elements", {})
    for dimension in design.get("original_md_dimensions", []):
        yield from dimension.get("elements", [])
    for module in design.get("extended_dna_modules", []):
        yield from module.get("elements", [])


def collect_refs(data: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []

    def add(path: str, values: Any) -> None:
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    refs.append((path, value))

    style = data.get("style_result", {})
    primary = style.get("primary_style")
    if isinstance(primary, dict):
        add("style_result.primary_style.evidence_refs", primary.get("evidence_refs"))
        add("style_result.primary_style.color_requirement.evidence_refs", primary.get("color_requirement", {}).get("evidence_refs"))
    for i, item in enumerate(style.get("secondary_styles", [])):
        add(f"style_result.secondary_styles[{i}].evidence_refs", item.get("evidence_refs"))
        add(f"style_result.secondary_styles[{i}].color_requirement.evidence_refs", item.get("color_requirement", {}).get("evidence_refs"))
    for i, element in enumerate(iter_elements(data)):
        add(f"design_element[{i}].evidence_refs", element.get("evidence_refs"))
    for i, item in enumerate(data.get("uncertain_fields", [])):
        for j, cand in enumerate(item.get("candidate_values", [])):
            add(f"uncertain_fields[{i}].candidate_values[{j}].supporting_evidence_refs", cand.get("supporting_evidence_refs"))
            add(f"uncertain_fields[{i}].candidate_values[{j}].contradicting_evidence_refs", cand.get("contradicting_evidence_refs"))
    for i, item in enumerate(data.get("novel_dna_elements", [])):
        add(f"novel_dna_elements[{i}].evidence_refs", item.get("evidence_refs"))
    return refs


def norm_text(value: str) -> str:
    return re.sub(r"[\s_\-—–|/（）()，,。.：:]+", "", value).lower()


def parse_style_names(kb_text: str) -> tuple[set[str], set[str]]:
    level1: set[str] = set()
    level2: set[str] = set()
    in_style = False
    for line in kb_text.splitlines():
        if line.startswith("# 工作表：设计风格"):
            in_style = True
            continue
        if line.startswith("# 工作表：设计元素"):
            in_style = False
        if not in_style:
            continue
        if line.startswith("## 一级风格："):
            level1.add(line.split("：", 1)[1].strip())
        elif line.startswith("### "):
            level2.add(line[4:].strip())
    return level1, level2


def bbox_errors(path: str, bbox: Any) -> list[str]:
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        return []  # schema handles shape/type
    x1, y1, x2, y2 = bbox
    errors = []
    if not x1 < x2:
        errors.append(f"{path}: x_min must be < x_max")
    if not y1 < y2:
        errors.append(f"{path}: y_min must be < y_max")
    return errors


def field_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("field_id") or ""),
        str(item.get("field_name") or ""),
        str(item.get("source_path") or ""),
    )


def validate_semantics(data: dict[str, Any], kb_text: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    errors += bbox_errors("target_object.bbox_norm", data.get("target_object", {}).get("bbox_norm"))
    evidence_list = data.get("evidence", [])
    evidence_ids = [e.get("evidence_id") for e in evidence_list if isinstance(e, dict)]
    duplicates = sorted({x for x in evidence_ids if evidence_ids.count(x) > 1})
    if duplicates:
        errors.append(f"duplicate evidence_id values: {duplicates}")
    evidence_set = set(evidence_ids)
    for i, ev in enumerate(evidence_list):
        errors += bbox_errors(f"evidence[{i}].bbox_norm", ev.get("bbox_norm"))

    for path, ref in collect_refs(data):
        if ref not in evidence_set:
            errors.append(f"{path}: unresolved evidence reference {ref!r}")

    uncertainty_keys = {field_key(item) for item in data.get("uncertain_fields", [])}
    element_keys: set[tuple[str, str, str, str]] = set()
    low_count = 0
    for i, element in enumerate(iter_elements(data)):
        key4 = (*field_key(element), str(element.get("region") or ""))
        if key4 in element_keys:
            warnings.append(f"design_element[{i}]: possible duplicate field/region {key4}")
        element_keys.add(key4)
        obs = element.get("observability")
        refs = element.get("evidence_refs") or []
        if obs == "observed" and not refs:
            errors.append(f"design_element[{i}]: observed field requires evidence")
        if obs == "inferred" and len(refs) < 2:
            errors.append(f"design_element[{i}]: inferred field requires at least two evidence refs")
        if obs == "not_observable" and element.get("value") is not None:
            errors.append(f"design_element[{i}]: not_observable field must have null value")
        if element.get("value") == "none" and obs != "observed":
            errors.append(f"design_element[{i}]: value 'none' requires observability 'observed'")
        confidence = element.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < 0.75:
            low_count += 1
            if field_key(element) not in uncertainty_keys:
                errors.append(
                    f"design_element[{i}]: confidence {confidence:.2f} < 0.75 but no matching uncertain_fields record"
                )

    reported_low = data.get("quality_summary", {}).get("low_confidence_field_count")
    if isinstance(reported_low, int) and reported_low != low_count:
        errors.append(
            f"quality_summary.low_confidence_field_count={reported_low}, expected {low_count} from extracted fields"
        )

    for i, item in enumerate(data.get("uncertain_fields", [])):
        candidates = item.get("candidate_values", [])
        if candidates:
            probs = [c.get("probability") for c in candidates]
            if all(isinstance(p, (int, float)) for p in probs):
                total = sum(probs)
                if not 0.97 <= total <= 1.03:
                    errors.append(f"uncertain_fields[{i}]: candidate probabilities sum to {total:.4f}, expected about 1")

    status = data.get("style_result", {}).get("classification_status")
    primary = data.get("style_result", {}).get("primary_style")
    if status == "unclassified" and primary is not None:
        errors.append("style_result: unclassified requires primary_style=null")
    if status in {"confirmed", "provisional"} and not isinstance(primary, dict):
        errors.append(f"style_result: {status} requires a primary_style object")
    if status == "confirmed" and isinstance(primary, dict):
        if not primary.get("hard_rule_passed"):
            errors.append("style_result.primary_style: confirmed style requires hard_rule_passed=true")
        if primary.get("exclusion_hits"):
            errors.append("style_result.primary_style: confirmed style cannot contain exclusion_hits")
        if primary.get("color_requirement", {}).get("status") not in {"pass", "not_applicable"}:
            errors.append("style_result.primary_style: confirmed style requires color requirement pass/not_applicable")
        if primary.get("missing_required_items"):
            errors.append("style_result.primary_style: confirmed style cannot have missing_required_items")

    level1_names, level2_names = parse_style_names(kb_text)
    assessments: list[dict[str, Any]] = []
    if isinstance(primary, dict):
        assessments.append(primary)
    assessments.extend(x for x in data.get("style_result", {}).get("secondary_styles", []) if isinstance(x, dict))
    for i, item in enumerate(assessments):
        if item.get("level_1") not in level1_names:
            warnings.append(f"style assessment[{i}]: level_1 not found verbatim in knowledge base: {item.get('level_1')!r}")
        if item.get("level_2") not in level2_names:
            warnings.append(f"style assessment[{i}]: level_2 not found verbatim in knowledge base: {item.get('level_2')!r}")

    temp_ids = [x.get("temp_id") for x in data.get("novel_dna_elements", []) if isinstance(x, dict)]
    if len(temp_ids) != len(set(temp_ids)):
        errors.append("novel_dna_elements: temp_id values must be unique")
    normalized_kb = norm_text(kb_text)
    for i, item in enumerate(data.get("novel_dna_elements", [])):
        name = str(item.get("proposed_field_name") or "")
        if name and norm_text(name) in normalized_kb:
            warnings.append(
                f"novel_dna_elements[{i}]: proposed field name appears in knowledge base; check for duplicate rather than new DNA"
            )
        if not item.get("evidence_refs"):
            errors.append(f"novel_dna_elements[{i}]: new DNA requires at least one evidence ref")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="Path to model output JSON")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--knowledge-base", type=Path, default=DEFAULT_KB)
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()

    data = load_json(args.result)
    schema = load_json(args.schema)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("ERROR: jsonschema is required. Install with: python -m pip install jsonschema>=4.21", file=sys.stderr)
        return 2

    schema_errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))
    errors = []
    for err in schema_errors:
        path = ".".join(str(x) for x in err.absolute_path) or "$"
        errors.append(f"schema {path}: {err.message}")

    kb_text = args.knowledge_base.read_text(encoding="utf-8")
    semantic_errors, warnings = validate_semantics(data, kb_text)
    errors.extend(semantic_errors)

    if errors:
        print(f"INVALID: {len(errors)} error(s)")
        for item in errors:
            print(f"  ERROR: {item}")
    else:
        print("VALID: schema and semantic checks passed")

    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        for item in warnings:
            print(f"  WARNING: {item}")

    if errors or (warnings and args.warnings_as_errors):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
