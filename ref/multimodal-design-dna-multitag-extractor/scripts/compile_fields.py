"""规范字段适用性、受控值与模块整理。"""
from __future__ import annotations

import copy
from typing import Any

from compilation_support import _ordered_unique, _record_change, _replace_if_changed
from dna_rules import view_requirement_satisfied as _view_requirement_satisfied

FORBIDDEN_SINGLE_IMAGE_PROFILES = {"profile:multi_face_device", "profile:reference_analysis", "profile:trend_analysis"}

def _nearest_bucket(value: int | float, buckets: list[int]) -> int:
    """按距离就近离散化；等距时向更高档位归一。"""

    return min(buckets, key=lambda bucket: (abs(float(value) - bucket), -bucket))


def _value_shape_matches(value_type: str, value: Any) -> bool:
    """只判断注册表基础类型，不尝试解释结构化值内部的视觉语义。"""

    if value_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type in {"string", "text", "enum"}:
        return isinstance(value, str)
    if value_type in {"list", "multi_label"}:
        return isinstance(value, list)
    if value_type == "object":
        return isinstance(value, dict)
    return False


def _normalized_controlled_value(
    field_id: str,
    record: dict[str, Any],
    value: Any,
    spaces: dict[str, tuple[str, set[str]]],
    normalization: dict[str, Any],
) -> tuple[Any, list[str]]:
    """只执行有机器规则支持的无歧义值归一，返回调整说明。"""

    notes: list[str] = []
    aliases = normalization.get("field_value_aliases", {}).get(field_id, {})
    controlled = spaces.get(field_id)
    if controlled:
        controlled_type, allowed = controlled
        if controlled_type == "enum":
            # 仅展开没有附加语义的单键包装；多键对象继续交给严格校验，避免丢失信息。
            if (
                isinstance(value, dict)
                and set(value) == {"label"}
                and isinstance(value.get("label"), str)
            ):
                wrapped = value
                value = wrapped["label"]
                notes.append(f"枚举单键包装 {wrapped!r} → {value!r}")
            if isinstance(value, str):
                normalized = aliases.get(value, value)
                if normalized != value:
                    notes.append(f"值别名 {value!r} → {normalized!r}")
                if normalized not in allowed:
                    return None, [*notes, f"值 {normalized!r} 不在受控值域"]
                value = normalized
        elif controlled_type in {"list", "multi_label"} and isinstance(value, list):
            normalized_items: list[Any] = []
            invalid_items: list[str] = []
            relation_field = field_id in set(
                normalization.get("relation_token_fields", [])
            )
            for item in value:
                if not isinstance(item, str):
                    normalized_items.append(item)
                    continue
                normalized = aliases.get(item, item)
                if normalized not in allowed and relation_field:
                    matched = [token for token in allowed if token in normalized]
                    if len(matched) == 1:
                        normalized = matched[0]
                if normalized in allowed:
                    normalized_items.append(normalized)
                    if normalized != item:
                        notes.append(f"受控词 {item!r} → {normalized!r}")
                else:
                    invalid_items.append(item)
            if invalid_items and not normalized_items:
                return None, [*notes, f"无法归一受控值 {invalid_items!r}"]
            if invalid_items:
                notes.append(f"移除无法归一的受控值 {invalid_items!r}")
            value = _ordered_unique(normalized_items)

    unit = record.get("unit")
    buckets = [
        int(item)
        for item in normalization.get("ordinal_buckets", [0, 25, 50, 75, 100])
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    strength_aliases = normalization.get("ordinal_strength_aliases", {})
    if (
        unit == "ordinal_0_25_50_75_100"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and buckets
    ):
        normalized_number = _nearest_bucket(value, buckets)
        if normalized_number != value:
            notes.append(f"序数 {value!r} → {normalized_number!r}")
        value = normalized_number
    if unit == "label+ordinal_strength" and isinstance(value, list) and buckets:
        for item in value:
            if not isinstance(item, dict):
                continue
            if (
                "strength" not in item
                and "ordinal_strength" in item
            ):
                original_strength = item.pop("ordinal_strength")
                item["strength"] = original_strength
                notes.append("键名 ordinal_strength → strength")
            strength = item.get("strength")
            if isinstance(strength, str):
                normalized_alias = strength_aliases.get(strength.strip().casefold())
                if normalized_alias in buckets:
                    notes.append(f"强度别名 {strength!r} → {normalized_alias!r}")
                    item["strength"] = normalized_alias
                    strength = normalized_alias
            if isinstance(strength, (int, float)) and not isinstance(strength, bool):
                normalized_strength = _nearest_bucket(strength, buckets)
                if normalized_strength != strength:
                    notes.append(
                        f"强度 {strength!r} → {normalized_strength!r}"
                    )
                    item["strength"] = normalized_strength
    return value, notes


def _iter_elements(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    elements: list[tuple[str, dict[str, Any]]] = []
    design_elements = data.get("design_elements")
    if not isinstance(design_elements, dict):
        return elements
    for module in design_elements.get("extended_dna_modules", []):
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("module_id") or "")
        for element in module.get("elements", []):
            if isinstance(element, dict):
                elements.append((module_id, element))
    return elements


def _normalize_elements(
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    module_names: dict[str, str],
    value_spaces: dict[str, tuple[str, set[str]]],
    normalization: dict[str, Any],
    report: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """过滤不适用字段并完成不涉及视觉推断的值与元数据整理。"""

    design_elements = data.setdefault(
        "design_elements", {"original_md_dimensions": [], "extended_dna_modules": []}
    )
    _replace_if_changed(
        design_elements,
        "original_md_dimensions",
        [],
        "/design_elements",
        report,
    )
    modules = design_elements.get("extended_dna_modules")
    if not isinstance(modules, list):
        return {}

    applicability = data.get("module_applicability")
    if not isinstance(applicability, dict):
        applicability = {}
    active_profiles = {
        profile
        for profile in applicability.get("active_profiles", [])
        if isinstance(profile, str) and profile not in FORBIDDEN_SINGLE_IMAGE_PROFILES
    }
    active_profiles.add("core")
    target = data.get("target_object")
    target_view = str(target.get("view") or "unknown") if isinstance(target, dict) else "unknown"

    canonical_elements: dict[str, list[dict[str, Any]]] = {}
    element_index: dict[tuple[str, str], dict[str, Any]] = {}
    filtered = report.setdefault("filtered_fields", [])
    normalized_values = report.setdefault("value_normalizations", [])
    for module_index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        elements = module.get("elements")
        if not isinstance(elements, list):
            continue
        for element_index_in_module, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            source_path = (
                f"/design_elements/extended_dna_modules/{module_index}"
                f"/elements/{element_index_in_module}"
            )
            field_id = str(element.get("field_id") or "")
            record = fields.get(field_id)
            if record is None:
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "unknown_canonical_field",
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue

            required_profiles = {
                profile
                for profile in record.get("applicability", [])
                if isinstance(profile, str)
            }
            if required_profiles and not required_profiles.intersection(active_profiles):
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "profile_not_applicable",
                        "required_profiles": sorted(required_profiles),
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue
            required_views = [
                view for view in record.get("required_views", []) if isinstance(view, str)
            ]
            if required_views and not _view_requirement_satisfied(required_views, target_view):
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": "view_not_applicable",
                        "required_views": required_views,
                        "actual_view": target_view,
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue

            canonical_module_id = str(record.get("module_id") or "")
            normalized_value, notes = _normalized_controlled_value(
                field_id,
                record,
                copy.deepcopy(element.get("value")),
                value_spaces,
                normalization,
            )
            if normalized_value is not None and not _value_shape_matches(
                str(record.get("value_type") or ""), normalized_value
            ):
                notes.append(
                    f"值类型与 {record.get('value_type')!r} 不匹配，已保守置空"
                )
                normalized_value = None
            if notes:
                normalized_values.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "notes": notes,
                    }
                )
            original_value = element.get("value")
            if normalized_value != original_value:
                _replace_if_changed(
                    element, "value", normalized_value, source_path, report
                )
            invalid_value = original_value is not None and normalized_value is None
            if invalid_value:
                confidence = element.get("confidence")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    _replace_if_changed(
                        element,
                        "confidence",
                        min(float(confidence), 0.74),
                        source_path,
                        report,
                    )
            for key, metadata_value in {
                "field_name": record.get("name"),
                "source_path": f"{canonical_module_id}/{field_id}",
                "schema_source": "md_extension",
                "value_type": record.get("value_type"),
                "evidence_mode": record.get("evidence_mode"),
                "applicability_status": "applicable",
            }.items():
                _replace_if_changed(element, key, metadata_value, source_path, report)

            evidence_mode = record.get("evidence_mode")
            value = element.get("value")
            if evidence_mode == "direct":
                if element.get("observability") != "observed" and value is not None:
                    _replace_if_changed(
                        element, "value", None, source_path, report
                    )
                    value = None
                _replace_if_changed(
                    element, "computation_status", "not_requested", source_path, report
                )
                if value is None:
                    _replace_if_changed(
                        element, "observability", "unknown", source_path, report
                    )
            elif evidence_mode == "reference_computed":
                _replace_if_changed(
                    element, "computation_status", "not_computable", source_path, report
                )
                _replace_if_changed(element, "value", None, source_path, report)
            elif value is None:
                _replace_if_changed(
                    element, "computation_status", "not_computable", source_path, report
                )
                if element.get("observability") == "observed":
                    _replace_if_changed(
                        element, "observability", "unknown", source_path, report
                    )
            else:
                _replace_if_changed(
                    element, "computation_status", "computed", source_path, report
                )
                _replace_if_changed(
                    element, "observability", "observed", source_path, report
                )
            refs = element.get("evidence_refs")
            if not isinstance(refs, list):
                refs = []
            normalized_refs = _ordered_unique(refs)
            _replace_if_changed(
                element,
                "evidence_refs",
                normalized_refs,
                source_path,
                report,
            )
            insufficient_inferred_evidence = (
                evidence_mode == "inferred" and len(normalized_refs) < 2
            )
            if insufficient_inferred_evidence:
                # 不能由代码判断哪条额外证据支持推断字段；证据不足时只省略该字段。
                _replace_if_changed(
                    element,
                    "computation_status",
                    "not_computable",
                    source_path,
                    report,
                )

            # 最终结果只保留具有可用值的字段；无值、不可见和不可计算状态仅进入编译报告。
            unavailable = (
                element.get("value") is None
                or element.get("observability") != "observed"
                or (
                    evidence_mode != "direct"
                    and element.get("computation_status") != "computed"
                )
            )
            if unavailable:
                filtered_reason = "no_usable_value"
                filtered_details = (
                    notes[-1] if notes else "字段不可见、无有效值或不可计算"
                )
                if insufficient_inferred_evidence:
                    filtered_reason = "insufficient_inferred_evidence"
                    filtered_details = (
                        "推断字段至少需要两条独立证据，宿主不能补造证据引用"
                    )
                filtered.append(
                    {
                        "field_id": field_id,
                        "source_pointer": element.get("_source_pointer"),
                        "reason": filtered_reason,
                        "details": filtered_details,
                    }
                )
                _record_change(report, f"{source_path}/filtered")
                continue

            region = str(element.get("region") or "")
            key = (field_id, region)
            previous = element_index.get(key)
            if previous is not None:
                previous_confidence = previous.get("confidence")
                current_confidence = element.get("confidence")
                previous_score = float(previous_confidence or 0)
                current_score = float(current_confidence or 0)
                if previous.get("value") is not None:
                    previous_score += 1
                if element.get("value") is not None:
                    current_score += 1
                if current_score <= previous_score:
                    filtered.append(
                        {
                            "field_id": field_id,
                            "source_pointer": element.get("_source_pointer"),
                            "reason": "duplicate_field_region",
                        }
                    )
                    continue
                canonical_elements[canonical_module_id].remove(previous)
            element_index[key] = element
            canonical_elements.setdefault(canonical_module_id, []).append(element)

    def usable_source(element: dict[str, Any]) -> bool:
        if element.get("value") is None or element.get("observability") != "observed":
            return False
        if element.get("evidence_mode") == "direct":
            return element.get("computation_status") == "not_requested"
        return element.get("computation_status") == "computed"

    def dependency_candidates(
        dependency: str, region: str
    ) -> list[dict[str, Any]]:
        return [
            source
            for (source_id, source_region), source in element_index.items()
            if source_id == dependency
            and usable_source(source)
            and (
                source_region == region
                or source_region.startswith("whole_object")
                or region.startswith("whole_object")
            )
        ]

    # 缺少任一规范源字段时逐层降级，避免下游派生字段继续引用不可用的中间值。
    while True:
        degraded = False
        for (field_id, region), element in list(element_index.items()):
            record = fields.get(field_id, {})
            if (
                record.get("evidence_mode") != "derived"
                or element.get("computation_status") != "computed"
            ):
                continue
            dependencies = [
                dependency
                for dependency in record.get("derived_from", [])
                if dependency in fields
            ]
            missing = [
                dependency
                for dependency in dependencies
                if not dependency_candidates(dependency, region)
            ]
            if not missing:
                continue
            canonical_module_id = str(record.get("module_id") or "")
            canonical_elements.get(canonical_module_id, []).remove(element)
            element_index.pop((field_id, region), None)
            filtered.append(
                {
                    "field_id": field_id,
                    "source_pointer": element.get("_source_pointer"),
                    "reason": "missing_derived_dependencies",
                    "missing_dependencies": missing,
                }
            )
            _record_change(report, f"/design_elements/{field_id}@{region}/filtered")
            report.setdefault("derived_field_degradations", []).append(
                {
                    "field_id": field_id,
                    "region": region,
                    "missing_dependencies": missing,
                    "action": "omitted_from_result",
                }
            )
            degraded = True
        if not degraded:
            break

    # 仍可计算的派生字段只合并已存在源字段的证据，不创造视觉事实。
    for (field_id, region), element in element_index.items():
        record = fields.get(field_id, {})
        if (
            record.get("evidence_mode") != "derived"
            or element.get("computation_status") != "computed"
        ):
            continue
        source_refs: list[str] = []
        for dependency in record.get("derived_from", []):
            candidates = dependency_candidates(dependency, region)
            if candidates:
                source_refs.extend(candidates[0].get("evidence_refs") or [])
        merged_refs = _ordered_unique(
            [*(element.get("evidence_refs") or []), *source_refs]
        )
        _replace_if_changed(
            element,
            "evidence_refs",
            merged_refs,
            f"/design_elements/{field_id}@{region}",
            report,
        )

    rebuilt_modules = [
        {
            "module_id": module_id,
            "module_name": module_names.get(module_id, module_id),
            "elements": elements,
        }
        for module_id, elements in sorted(canonical_elements.items())
        if elements
    ]
    _replace_if_changed(
        design_elements,
        "extended_dna_modules",
        rebuilt_modules,
        "/design_elements",
        report,
    )
    return element_index


def _normalize_modules(
    data: dict[str, Any],
    module_names: dict[str, str],
    report: dict[str, Any],
) -> None:
    applicability = data.setdefault("module_applicability", {})
    active_profiles = applicability.get("active_profiles")
    if not isinstance(active_profiles, list):
        active_profiles = []
    active_profiles = [
        item
        for item in active_profiles
        if isinstance(item, str) and item not in FORBIDDEN_SINGLE_IMAGE_PROFILES
    ]
    if "core" not in active_profiles:
        active_profiles.insert(0, "core")
    _replace_if_changed(
        applicability,
        "active_profiles",
        _ordered_unique(active_profiles),
        "/module_applicability",
        report,
    )

    present_modules = {
        module_id for module_id, _element in _iter_elements(data) if module_id != "DNA-M15"
    }
    existing_applicable = {
        str(item.get("module_id") or ""): item
        for item in applicability.get("applicable_modules", [])
        if isinstance(item, dict)
    }
    rebuilt_applicable = []
    for module_id in sorted(present_modules):
        previous = existing_applicable.get(module_id, {})
        rebuilt_applicable.append(
            {
                "module_id": module_id,
                "module_name": module_names.get(module_id, module_id),
                "reason": previous.get("reason")
                or "本次模型观察包含该模块的适用品类字段。",
            }
        )
    _replace_if_changed(
        applicability,
        "applicable_modules",
        rebuilt_applicable,
        "/module_applicability",
        report,
    )

    excluded = [
        copy.deepcopy(item)
        for item in applicability.get("excluded_modules", [])
        if isinstance(item, dict) and item.get("module_id") != "DNA-M15"
    ]
    excluded.append(
        {
            "module_id": "DNA-M15",
            "module_name": module_names.get("DNA-M15", "DNA-M15"),
            "reason": "profile_not_applicable",
            "explanation": "当前为单图提取，未激活参考集或趋势分析 profile。",
        }
    )
    _replace_if_changed(
        applicability,
        "excluded_modules",
        excluded,
        "/module_applicability",
        report,
    )
    if not isinstance(applicability.get("rule_adaptations"), list):
        _replace_if_changed(
            applicability,
            "rule_adaptations",
            [],
            "/module_applicability",
            report,
        )
