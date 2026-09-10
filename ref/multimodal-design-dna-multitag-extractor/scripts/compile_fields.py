"""规范字段适用性、受控值、模块与不确定项整理。"""
from __future__ import annotations

import copy
from typing import Any

from compilation_support import _ordered_unique, _record_change, _replace_if_changed
from dna_rules import view_requirement_satisfied as _view_requirement_satisfied

FORBIDDEN_SINGLE_IMAGE_PROFILES = {"profile:multi_face_device", "profile:reference_analysis", "profile:trend_analysis"}

def _nearest_bucket(value: int | float, buckets: list[int]) -> int:
    """按距离就近离散化；等距时向更高档位归一。"""

    return min(buckets, key=lambda bucket: (abs(float(value) - bucket), -bucket))


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
            strength = item.get("strength")
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
                element["_compiler_uncertainty_reason"] = notes[-1]
                confidence = element.get("confidence")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    _replace_if_changed(
                        element,
                        "confidence",
                        min(float(confidence), 0.74),
                        source_path,
                        report,
                    )
            confidence = element.get("confidence")
            if (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and float(confidence) < 0.30
                and element.get("value") is not None
            ):
                element["_compiler_uncertainty_reason"] = (
                    "置信度低于 0.30，不能保留确定值"
                )
                _replace_if_changed(element, "value", None, source_path, report)

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
            _replace_if_changed(
                element,
                "evidence_refs",
                _ordered_unique(refs),
                source_path,
                report,
            )

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

    # 派生字段的证据闭环完全由注册依赖和已存在的源字段证据计算，不创造视觉事实。
    for (field_id, region), element in element_index.items():
        record = fields.get(field_id, {})
        if (
            record.get("evidence_mode") != "derived"
            or element.get("computation_status") != "computed"
        ):
            continue
        source_refs: list[str] = []
        for dependency in record.get("derived_from", []):
            candidates = [
                source
                for (source_id, source_region), source in element_index.items()
                if source_id == dependency
                and source.get("value") is not None
                and source.get("observability") == "observed"
                and (
                    source_region == region
                    or source_region.startswith("whole_object")
                    or region.startswith("whole_object")
                )
            ]
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


def _normalize_uncertainties(
    data: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """从最终字段状态单向重建不确定项镜像，避免模型维护重复结构。"""

    raw_items = data.get("uncertain_fields")
    if not isinstance(raw_items, list):
        raw_items = []
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        field_id = str(item.get("field_id") or "")
        region = str(item.get("region") or "")
        key = (field_id, region)
        if key not in element_index:
            same_field = [
                element_region
                for candidate_field_id, element_region in element_index
                if candidate_field_id == field_id
            ]
            if len(same_field) == 1:
                region = same_field[0]
                key = (field_id, region)
                item["region"] = region
        existing.setdefault(key, item)

    rebuilt: list[dict[str, Any]] = []
    for (field_id, region), element in element_index.items():
        evidence_mode = str(element.get("evidence_mode") or "")
        observability = str(element.get("observability") or "unknown")
        computation_status = str(element.get("computation_status") or "")
        confidence = element.get("confidence")
        low_confidence = (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) < 0.75
        )
        unavailable = (
            evidence_mode == "direct" and observability != "observed"
        ) or (
            evidence_mode != "direct" and computation_status != "computed"
        )
        compiler_reason = element.get("_compiler_uncertainty_reason")
        if not (low_confidence or unavailable or compiler_reason):
            continue

        item = copy.deepcopy(existing.get((field_id, region), {}))
        item.setdefault("field_id", field_id)
        item.setdefault("region", region)
        if compiler_reason and not unavailable:
            reason_type = "definition_gap"
            reason = str(compiler_reason)
        elif evidence_mode == "reference_computed":
            reason_type = "missing_reference"
            reason = "当前单图任务缺少该字段所需的批准参考集。"
        elif unavailable and evidence_mode != "direct":
            reason_type = "not_computable"
            reason = "当前可用观察不足以完成该非直接字段计算。"
        elif unavailable:
            reason_type = "not_observable"
            reason = "当前图片没有提供该字段所需的清晰可见信息。"
        else:
            reason_type = "low_confidence"
            reason = "字段置信度低于确认阈值 0.75。"
        item["reason_type"] = reason_type
        item["reason"] = item.get("reason") or reason
        item["best_estimate"] = None if unavailable else element.get("value")
        item.setdefault("candidate_values", [])
        item.setdefault(
            "recommended_additional_view_or_info",
            "补充更清晰或覆盖相应区域与视角的图片。",
        )
        item.setdefault("_source_pointer", element.get("_source_pointer"))
        rebuilt.append(item)

    _replace_if_changed(
        data,
        "uncertain_fields",
        rebuilt,
        "",
        report,
    )

    for index, item in enumerate(rebuilt):
        if not isinstance(item, dict):
            continue
        path = f"/uncertain_fields/{index}"
        field_id = str(item.get("field_id") or "")
        region = str(item.get("region") or "")
        element = element_index.get((field_id, region))
        if element is None:
            same_field = [
                (element_region, candidate)
                for (candidate_field_id, element_region), candidate in element_index.items()
                if candidate_field_id == field_id
            ]
            if len(same_field) == 1:
                region, element = same_field[0]
                _replace_if_changed(item, "region", region, path, report)
        record = fields.get(field_id)
        if record is not None:
            _replace_if_changed(item, "field_name", record.get("name"), path, report)
            _replace_if_changed(
                item,
                "source_path",
                f"{record.get('module_id')}/{field_id}",
                path,
                report,
            )
        if element is not None:
            for key in (
                "evidence_mode",
                "applicability_status",
                "observability",
                "computation_status",
                "confidence",
            ):
                _replace_if_changed(item, key, element.get(key), path, report)
        if (
            element is not None
            and item.get("best_estimate") is None
            and element.get("value") is not None
            and (
                element.get("observability") == "observed"
                if element.get("evidence_mode") == "direct"
                else element.get("computation_status") == "computed"
            )
        ):
            _replace_if_changed(
                item, "best_estimate", element.get("value"), path, report
            )
        candidates = item.get("candidate_values")
        if isinstance(candidates, list) and candidates:
            probabilities = [
                candidate.get("probability") if isinstance(candidate, dict) else None
                for candidate in candidates
            ]
            if all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and float(value) >= 0
                for value in probabilities
            ):
                total = sum(float(value) for value in probabilities)
                if total > 0:
                    normalized = [round(float(value) / total, 6) for value in probabilities[:-1]]
                    normalized.append(round(1 - sum(normalized), 6))
                    if any(
                        candidate.get("probability") != probability
                        for candidate, probability in zip(candidates, normalized, strict=True)
                    ):
                        for candidate, probability in zip(candidates, normalized, strict=True):
                            candidate["probability"] = probability
                        _record_change(report, f"{path}/candidate_values/*/probability")
