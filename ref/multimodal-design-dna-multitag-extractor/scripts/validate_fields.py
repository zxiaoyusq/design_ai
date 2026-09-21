"""主体、规范字段和新 DNA 的只读语义校验。"""
from __future__ import annotations

from typing import Any

from validation_rules import (
    ACTIVE_PROFILES,
    FIELD_ID_PATTERN,
    LEGACY_DIMENSIONS,
    bbox_contains,
    bbox_errors,
    collect_refs,
    field_key,
    is_usable_source,
    is_whole_object_region,
    iter_elements,
    norm_text,
    validate_value_domain,
    value_matches,
    view_requirement_satisfied,
)


def _validate_target_evidence(
    data: dict[str, Any],
    errors: list[str],
) -> tuple[set[str], str, dict[str, str]]:
    """核对主体框、证据区域、坐标及所有证据引用。"""
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

    return allowed_regions, target_view, evidence_regions


def _validate_modules(
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    errors: list[str],
) -> set[str]:
    """核对单图 profile、模块声明及实际字段容器的一致性。"""
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

    return active_profile_set


def _validate_elements(
    active_profile_set: set[str],
    alias_to_field: dict[str, str],
    allowed_regions: set[str],
    compatibility_derived: dict[str, dict[str, Any]],
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    target_view: str,
    value_spaces: dict[str, tuple[str, set[str]]],
    errors: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """校验规范字段状态、值域、派生依赖及字段质量统计。"""
    element_keys: set[tuple[str, str, str, str]] = set()
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
        if evidence_mode == "direct":
            if computation_status != "not_requested":
                errors.append(f"design_element[{i}]: direct field requires computation_status=not_requested")
            if observability == "observed":
                if value is None or not refs:
                    errors.append(f"design_element[{i}]: observed direct field requires value and evidence")
            else:
                errors.append(
                    f"design_element[{i}]: design_elements only accepts observed fields with usable values"
                )
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
                errors.append(
                    f"design_element[{i}]: design_elements only accepts computed fields with usable values"
                )
        value_type = element.get("value_type")
        if isinstance(value_type, str) and not value_matches(value_type, value):
            errors.append(f"design_element[{i}]: value does not match value_type={value_type!r}")
        confidence = element.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            confidences.append(float(confidence))
            if confidence < 0.75:
                low_count += 1
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

    return canonical_elements


def _validate_novel_dna(
    alias_to_field: dict[str, str],
    compatibility_derived: dict[str, dict[str, Any]],
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    value_spaces: dict[str, tuple[str, set[str]]],
    errors: list[str],
) -> None:
    """拒绝已有字段/值域重复申报，并核对新候选的类型与证据。"""
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
