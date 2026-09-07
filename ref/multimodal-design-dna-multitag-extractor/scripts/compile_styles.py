"""风格证据挂接、独立硬门槛复核和候选关系整理。"""
from __future__ import annotations

import copy
import re
from itertools import combinations
from typing import Any
from compilation_support import _ordered_unique, _record_change, _replace_if_changed

FIELD_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*-[0-9]{2,3}")

def _style_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "label_en": record.get("display_name_en"),
        "label_zh": record.get("display_name_zh"),
        "aliases": list(record.get("aliases") or []),
        "tag_kind": record.get("tag_kind"),
        "facet_ids": list(record.get("facet_ids") or []),
    }


def _pair_relation_map(tag_relations: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for item in tag_relations.get("pair_relations", []):
        if not isinstance(item, dict):
            continue
        style_ids = item.get("style_ids")
        if isinstance(style_ids, list) and len(style_ids) == 2:
            pairs[tuple(sorted(str(style_id) for style_id in style_ids))] = item
    return pairs


def _field_evidence_index(
    element_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for (field_id, _region), element in element_index.items():
        confidence = element.get("confidence")
        available = (
            element.get("observability") == "observed"
            if element.get("evidence_mode") == "direct"
            else element.get("computation_status") == "computed"
        )
        if (
            not available
            or element.get("value") is None
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or float(confidence) < 0.75
        ):
            continue
        result.setdefault(field_id, []).extend(element.get("evidence_refs") or [])
    return {field_id: _ordered_unique(refs) for field_id, refs in result.items()}


def _confirmed_element(element: dict[str, Any]) -> bool:
    """判断字段是否足以进入 confirmed 风格证据链。"""

    confidence = element.get("confidence")
    available = (
        element.get("observability") == "observed"
        if element.get("evidence_mode") == "direct"
        else element.get("computation_status") == "computed"
    )
    return bool(
        available
        and element.get("value") is not None
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and float(confidence) >= 0.75
        and element.get("evidence_refs")
    )


def _value_at_path(value: Any, path: Any) -> Any:
    """读取机器证据规则中的短路径；路径缺失时返回 None。"""

    if path in (None, "", []):
        return value
    parts = path if isinstance(path, list) else str(path).split(".")
    current = value
    for part in parts:
        if isinstance(current, dict) and str(part) in current:
            current = current[str(part)]
        elif isinstance(current, list) and str(part).isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _matches_value_rule(value: Any, matcher: dict[str, Any]) -> bool:
    """执行少量可审计的值级比较，不使用自由文本相似度猜测。"""

    actual = _value_at_path(value, matcher.get("path"))
    operator = matcher.get("operator")
    expected = matcher.get("value")
    expected_values = matcher.get("values")
    if operator == "equals":
        return actual == expected
    if operator == "in":
        return isinstance(expected_values, list) and actual in expected_values
    if operator == "not_in":
        return isinstance(expected_values, list) and actual not in expected_values
    if operator in {"gte", "lte"}:
        if (
            not isinstance(actual, (int, float))
            or isinstance(actual, bool)
            or not isinstance(expected, (int, float))
            or isinstance(expected, bool)
        ):
            return False
        return actual >= expected if operator == "gte" else actual <= expected
    if operator in {"contains_any", "contains_all"}:
        if not isinstance(expected_values, list) or not expected_values:
            return False
        if isinstance(actual, list):
            present = set(actual)
            checks = [item in present for item in expected_values]
        elif isinstance(actual, str):
            checks = [str(item) in actual for item in expected_values]
        elif isinstance(actual, dict):
            present = set(actual)
            checks = [item in present for item in expected_values]
        else:
            return False
        return any(checks) if operator == "contains_any" else all(checks)
    return False


def _matching_rule_elements(
    clause: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    field_id = str(clause.get("field_id") or "")
    matcher = clause.get("match")
    if not field_id or not isinstance(matcher, dict):
        return []
    return [
        element
        for (candidate_id, _region), element in element_index.items()
        if candidate_id == field_id
        and _confirmed_element(element)
        and _matches_value_rule(element.get("value"), matcher)
    ]


def _style_hit_text(field_ids: list[str], elements: list[dict[str, Any]]) -> str:
    descriptions = _ordered_unique(
        [
            str(element.get("raw_visual_description") or "").strip()
            for element in elements
            if str(element.get("raw_visual_description") or "").strip()
        ]
    )
    detail = "；".join(descriptions[:2]) or "字段值通过宿主值级证据规则"
    return f"{'、'.join(field_ids)}：{detail}"


def _auto_link_style_hits(
    *,
    style_id: str,
    role: str,
    existing_hits: list[str],
    allowed_field_ids: set[str],
    evidence_rules: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    source_pointer: Any,
    report: dict[str, Any],
) -> list[str]:
    """只用显式值级规则补足缺失证据，不从字段名直接推断风格。"""

    style_rules = evidence_rules.get("styles")
    if not isinstance(style_rules, dict):
        return existing_hits
    style_config = style_rules.get(style_id)
    if not isinstance(style_config, dict):
        return existing_hits
    result = list(existing_hits)
    for rule in style_config.get("rules", []):
        if not isinstance(rule, dict) or rule.get("role") != role:
            continue
        if existing_hits and not rule.get("always_link"):
            continue
        clauses = [
            {
                "field_id": rule.get("field_id"),
                "match": rule.get("match"),
            },
            *[
                clause
                for clause in rule.get("requires", [])
                if isinstance(clause, dict)
            ],
        ]
        field_ids = [str(clause.get("field_id") or "") for clause in clauses]
        if not field_ids or any(field_id not in allowed_field_ids for field_id in field_ids):
            continue
        already_cited = {
            field_id
            for hit in result
            for field_id in FIELD_ID_PATTERN.findall(str(hit))
        }
        if set(field_ids).issubset(already_cited):
            continue
        matched_groups = [
            _matching_rule_elements(clause, element_index) for clause in clauses
        ]
        if any(not group for group in matched_groups):
            continue
        elements = [group[0] for group in matched_groups]
        hit = _style_hit_text(field_ids, elements)
        result.append(hit)
        report.setdefault("auto_linked_style_hits", []).append(
            {
                "style_id": style_id,
                "source_pointer": source_pointer,
                "role": role,
                "rule_id": rule.get("rule_id"),
                "field_ids": field_ids,
                "evidence_refs": _ordered_unique(
                    [
                        evidence_id
                        for element in elements
                        for evidence_id in element.get("evidence_refs", [])
                    ]
                ),
            }
        )
    return _ordered_unique(result)


def _semantic_review_candidates(
    *,
    allowed_field_ids: set[str],
    cited_field_ids: set[str],
    fields: dict[str, dict[str, Any]],
    element_index: dict[tuple[str, str], dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """为小范围复核选择强字段；完整注册表不会进入模型上下文。"""

    candidates = [
        {
            "field_id": field_id,
            "field_name": element.get("field_name"),
            "decision_use": fields.get(field_id, {}).get("decision_use"),
            "value": copy.deepcopy(element.get("value")),
            "raw_visual_description": element.get("raw_visual_description"),
            "region": region,
            "confidence": element.get("confidence"),
            "evidence_refs": copy.deepcopy(element.get("evidence_refs", [])),
        }
        for (field_id, region), element in element_index.items()
        if field_id in allowed_field_ids
        and field_id not in cited_field_ids
        and _confirmed_element(element)
    ]
    candidates.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0),
            -len(item.get("evidence_refs") or []),
            str(item.get("field_id") or ""),
            str(item.get("region") or ""),
        )
    )
    return candidates[:limit]


def _record_pruned_style_hit(
    report: dict[str, Any],
    *,
    style_id: str,
    source_pointer: Any,
    role: str,
    hit: str,
    reason: str,
    field_ids: list[str],
) -> None:
    """记录被剔除的弱引用；剔除本身不等于整个风格失败。"""

    report.setdefault("pruned_style_hits", []).append(
        {
            "style_id": style_id,
            "source_pointer": source_pointer,
            "role": role,
            "hit": hit,
            "field_ids": field_ids,
            "reason": reason,
        }
    )


def _style_policy_downgrade_reasons(
    style_record: dict[str, Any],
    core_field_ids: set[str],
    auxiliary_field_ids: set[str],
    field_evidence: dict[str, list[str]],
    element_index: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    """复核注册表中的不可裁剪硬门槛，目前包括 NeoRetro 线索族策略。"""

    policy = style_record.get("cue_family_policy")
    if not isinstance(policy, dict):
        return []
    cited_field_ids = core_field_ids | auxiliary_field_ids
    raw_families = policy.get("families")
    families = raw_families if isinstance(raw_families, dict) else {}
    family_hits = {
        str(family_name): cited_field_ids.intersection(
            str(field_id) for field_id in family_field_ids
        )
        for family_name, family_field_ids in families.items()
        if isinstance(family_field_ids, list)
        and cited_field_ids.intersection(str(field_id) for field_id in family_field_ids)
    }
    family_evidence = {
        family_name: {
            evidence_id
            for field_id in family_field_ids
            for evidence_id in field_evidence.get(field_id, [])
        }
        for family_name, family_field_ids in family_hits.items()
    }
    min_families = policy.get("min_distinct_families")
    qualifying_group: tuple[str, ...] = ()
    if (
        isinstance(min_families, int)
        and not isinstance(min_families, bool)
        and min_families >= 1
    ):
        for family_group in combinations(sorted(family_evidence), min_families):
            if all(
                family_evidence[family_name]
                - {
                    evidence_id
                    for other_name in family_group
                    if other_name != family_name
                    for evidence_id in family_evidence[other_name]
                }
                for family_name in family_group
            ):
                qualifying_group = family_group
                break
    reasons: list[str] = []
    if isinstance(min_families, int) and len(qualifying_group) < min_families:
        reasons.append(f"特殊硬门槛需要至少 {min_families} 组具有独立证据的线索族")

    expressive_gate = policy.get("expressive_gate")
    gate_field_id = (
        expressive_gate.get("field_id")
        if isinstance(expressive_gate, dict)
        else None
    )
    allowed_values = set(
        expressive_gate.get("allowed_values") or []
        if isinstance(expressive_gate, dict)
        else []
    )
    gate_values = {
        element.get("value")
        for (field_id, _region), element in element_index.items()
        if field_id == gate_field_id
        and isinstance(element.get("value"), str)
        and field_id in field_evidence
    }
    if (
        not isinstance(gate_field_id, str)
        or gate_field_id not in core_field_ids
        or not gate_values.intersection(allowed_values)
    ):
        reasons.append(
            f"特殊硬门槛缺少决定字段 {gate_field_id} 的允许值 {sorted(allowed_values)}"
        )
    return reasons



def _rebuild_style_hits(
    tag: dict[str, Any], style_id: str, path: str,
    decisive_ids: set[str], auxiliary_ids: set[str],
    field_evidence: dict[str, list[str]], report: dict[str, Any],
) -> dict[str, list[str]]:
    """整理已有命中的角色与可用性，后续再执行自动挂接和硬门槛复核。"""
    rebuilt_hits: dict[str, list[str]] = {
        "core_feature_hits": [],
        "auxiliary_feature_hits": [],
    }
    for original_role in ("core_feature_hits", "auxiliary_feature_hits"):
        for hit in tag.get(original_role, []):
            hit_text = str(hit)
            referenced = FIELD_ID_PATTERN.findall(hit_text)
            if not referenced:
                _record_pruned_style_hit(
                    report,
                    style_id=style_id,
                    source_pointer=tag.get("_source_pointer"),
                    role=original_role,
                    hit=hit_text,
                    field_ids=[],
                    reason="证据命中未引用规范字段",
                )
                continue
            unavailable = [
                field_id for field_id in referenced if field_id not in field_evidence
            ]
            if unavailable:
                _record_pruned_style_hit(
                    report,
                    style_id=style_id,
                    source_pointer=tag.get("_source_pointer"),
                    role=original_role,
                    hit=hit_text,
                    field_ids=unavailable,
                    reason="字段没有置信度不低于 0.75 的可用值与证据",
                )
                continue
            can_core = all(field_id in decisive_ids for field_id in referenced)
            can_auxiliary = all(
                field_id in auxiliary_ids for field_id in referenced
            )
            target_role: str | None = None
            if original_role == "core_feature_hits" and can_core:
                target_role = original_role
            elif original_role == "auxiliary_feature_hits" and can_auxiliary:
                target_role = original_role
            elif can_core and not can_auxiliary:
                target_role = "core_feature_hits"
            elif can_auxiliary and not can_core:
                target_role = "auxiliary_feature_hits"
            elif can_core and can_auxiliary:
                target_role = original_role
            if target_role is None:
                _record_pruned_style_hit(
                    report,
                    style_id=style_id,
                    source_pointer=tag.get("_source_pointer"),
                    role=original_role,
                    hit=hit_text,
                    field_ids=referenced,
                    reason="字段不在该风格允许的决定或辅助集合",
                )
                continue
            rebuilt_hits[target_role].append(hit_text)
            if target_role != original_role:
                _record_change(report, f"{path}/{original_role}/reclassified")

    return rebuilt_hits


def _normalize_style_tag(
    index: int, tag: dict[str, Any], styles: dict[str, dict[str, Any]],
    fields: dict[str, dict[str, Any]], evidence_rules: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    field_evidence: dict[str, list[str]], evidence_regions: dict[str, str],
    review_candidate_limit: int, report: dict[str, Any],
) -> dict[str, Any] | None:
    """复核单个标签；闭环不足时返回降级候选，并记录原因和语义复核请求。"""
    path = f"/style_result/style_tags/{index}"
    style_id = str(tag.get("style_id") or "")
    style_record = styles.get(style_id)
    downgrade_reasons: list[str] = []
    if style_record is None:
        downgrade_reasons.append("风格 ID 未在活动注册表中")
        decisive_ids: set[str] = set()
        auxiliary_ids: set[str] = set()
    else:
        for key, value in _style_identity(style_record).items():
            _replace_if_changed(tag, key, value, path, report)
        decisive_ids = set(style_record.get("decisive_field_ids") or [])
        auxiliary_ids = set(style_record.get("auxiliary_field_ids") or [])

    rebuilt_hits = _rebuild_style_hits(
        tag, style_id, path, decisive_ids, auxiliary_ids, field_evidence, report
    )
    rebuilt_hits["core_feature_hits"] = _auto_link_style_hits(
        style_id=style_id,
        role="core",
        existing_hits=rebuilt_hits["core_feature_hits"],
        allowed_field_ids=decisive_ids,
        evidence_rules=evidence_rules,
        element_index=element_index,
        source_pointer=tag.get("_source_pointer"),
        report=report,
    )
    rebuilt_hits["auxiliary_feature_hits"] = _auto_link_style_hits(
        style_id=style_id,
        role="auxiliary",
        existing_hits=rebuilt_hits["auxiliary_feature_hits"],
        allowed_field_ids=auxiliary_ids,
        evidence_rules=evidence_rules,
        element_index=element_index,
        source_pointer=tag.get("_source_pointer"),
        report=report,
    )
    for role, hits in rebuilt_hits.items():
        _replace_if_changed(tag, role, _ordered_unique(hits), path, report)
    core_field_ids = {
        field_id
        for hit in rebuilt_hits["core_feature_hits"]
        for field_id in FIELD_ID_PATTERN.findall(hit)
    }
    auxiliary_field_ids = {
        field_id
        for hit in rebuilt_hits["auxiliary_feature_hits"]
        for field_id in FIELD_ID_PATTERN.findall(hit)
    }
    review_roles: dict[str, list[dict[str, Any]]] = {}
    cited_field_ids = core_field_ids | auxiliary_field_ids
    if not rebuilt_hits["core_feature_hits"]:
        downgrade_reasons.append("缺少注册表允许的决定字段")
        review_candidates = _semantic_review_candidates(
            allowed_field_ids=decisive_ids,
            cited_field_ids=cited_field_ids,
            fields=fields,
            element_index=element_index,
            limit=review_candidate_limit,
        )
        if review_candidates:
            review_roles["core"] = review_candidates
    elif not any(
        fields.get(field_id, {}).get("decision_use") == "hard"
        for field_id in core_field_ids
    ):
        downgrade_reasons.append("决定证据缺少 decision_use=hard 的规范字段")
        review_candidates = _semantic_review_candidates(
            allowed_field_ids={
                field_id
                for field_id in decisive_ids
                if fields.get(field_id, {}).get("decision_use") == "hard"
            },
            cited_field_ids=cited_field_ids,
            fields=fields,
            element_index=element_index,
            limit=review_candidate_limit,
        )
        if review_candidates:
            review_roles["core"] = review_candidates
    if not rebuilt_hits["auxiliary_feature_hits"]:
        downgrade_reasons.append("缺少注册表允许且可用的辅助字段")
        review_candidates = _semantic_review_candidates(
            allowed_field_ids=auxiliary_ids,
            cited_field_ids=cited_field_ids,
            fields=fields,
            element_index=element_index,
            limit=review_candidate_limit,
        )
        if review_candidates:
            review_roles["auxiliary"] = review_candidates
    if auxiliary_field_ids and not auxiliary_field_ids.difference(core_field_ids):
        downgrade_reasons.append("辅助字段没有形成独立于决定字段的支持")
    policy_reasons: list[str] = []
    if style_record is not None:
        policy_reasons = _style_policy_downgrade_reasons(
            style_record,
            core_field_ids,
            auxiliary_field_ids,
            field_evidence,
            element_index,
        )
        downgrade_reasons.extend(policy_reasons)
        policy = style_record.get("cue_family_policy")
        if (
            isinstance(policy, dict)
            and any("线索族" in reason for reason in policy_reasons)
            and not any("缺少决定字段" in reason for reason in policy_reasons)
        ):
            raw_families = policy.get("families")
            families = raw_families if isinstance(raw_families, dict) else {}
            family_fields = {
                str(field_id)
                for field_ids in families.values()
                if isinstance(field_ids, list)
                for field_id in field_ids
            }
            for role, allowed_ids in (
                ("core", decisive_ids),
                ("auxiliary", auxiliary_ids),
            ):
                candidates = _semantic_review_candidates(
                    allowed_field_ids=allowed_ids.intersection(family_fields),
                    cited_field_ids=cited_field_ids,
                    fields=fields,
                    element_index=element_index,
                    limit=review_candidate_limit,
                )
                if candidates:
                    review_roles[role] = _ordered_unique(
                        [*(review_roles.get(role) or []), *candidates]
                    )[:review_candidate_limit]
    referenced_fields = [
        field_id
        for key in ("core_feature_hits", "auxiliary_feature_hits")
        for hit in rebuilt_hits[key]
        for field_id in FIELD_ID_PATTERN.findall(str(hit))
    ]
    inferred_refs = [
        evidence_id
        for field_id in referenced_fields
        for evidence_id in field_evidence.get(field_id, [])
    ]
    color = tag.get("color_requirement")
    if isinstance(color, dict):
        color_refs = color.get("evidence_refs")
        if not isinstance(color_refs, list):
            color_refs = []
        if color.get("status") == "pass":
            color_refs = _ordered_unique(
                [
                    *color_refs,
                    *(
                        evidence_id
                        for field_id in referenced_fields
                        if field_id.startswith("CLR-")
                        for evidence_id in field_evidence.get(field_id, [])
                    ),
                ]
            )
            if not color_refs:
                downgrade_reasons.append("颜色门槛通过但没有可用颜色证据")
        inferred_refs.extend(color_refs)
        _replace_if_changed(
            color,
            "evidence_refs",
            _ordered_unique(color_refs),
            f"{path}/color_requirement",
            report,
        )
    _replace_if_changed(
        tag,
        "evidence_refs",
        _ordered_unique(inferred_refs),
        path,
        report,
    )
    backed_regions = {
        evidence_regions.get(evidence_id, "")
        for evidence_id in tag.get("evidence_refs", [])
        if evidence_regions.get(evidence_id)
    }
    normalized_regions = [
        region
        for region in tag.get("regions", [])
        if isinstance(region, str) and region in backed_regions
    ]
    _replace_if_changed(
        tag,
        "regions",
        _ordered_unique(normalized_regions),
        path,
        report,
    )
    if len(tag.get("evidence_refs") or []) < 2:
        downgrade_reasons.append("可用风格证据少于两条")
    if not normalized_regions:
        downgrade_reasons.append("声明区域没有对应的引用证据")
    coverage = tag.get("rule_coverage")
    if not isinstance(coverage, dict):
        downgrade_reasons.append("规则覆盖结构缺失")
    elif (
        coverage.get("applicable_rule_count", 0) < 1
        or coverage.get("passed_rule_count", 0) < 1
        or coverage.get("failed_rule_count", 0) != 0
        or coverage.get("unknown_rule_count", 0) != 0
    ):
        downgrade_reasons.append("规则覆盖没有达到 confirmed 门槛")
    if (
        not tag.get("hard_rule_passed")
        or tag.get("missing_required_items")
        or tag.get("exclusion_hits")
    ):
        downgrade_reasons.append("硬规则、缺失项或排除项未闭合")

    coverage_ready = isinstance(coverage, dict) and (
        coverage.get("applicable_rule_count", 0) >= 1
        and coverage.get("passed_rule_count", 0) >= 1
        and coverage.get("failed_rule_count", 0) == 0
        and coverage.get("unknown_rule_count", 0) == 0
    )
    hard_rule_ready = bool(
        tag.get("hard_rule_passed")
        and not tag.get("missing_required_items")
        and not tag.get("exclusion_hits")
    )
    expressive_gate_failed = any(
        "特殊硬门槛缺少决定字段" in reason for reason in downgrade_reasons
    )
    if (
        review_roles
        and style_record is not None
        and coverage_ready
        and hard_rule_ready
        and not expressive_gate_failed
    ):
        report.setdefault("semantic_review_requests", []).append(
            {
                "style_id": style_id,
                "source_pointer": tag.get("_source_pointer"),
                "missing_roles": sorted(review_roles),
                "current_core_field_ids": sorted(core_field_ids),
                "current_auxiliary_field_ids": sorted(auxiliary_field_ids),
                "roles": review_roles,
                "downgrade_reasons": _ordered_unique(downgrade_reasons),
            }
        )

    if downgrade_reasons:
        demoted_candidate = {
                "style_id": style_id,
                "match_score": tag.get("match_score", 0),
                "confidence": tag.get("confidence", 0),
                "dominance": 0,
                "regions": copy.deepcopy(tag.get("regions", [])),
                "candidate_status": "provisional",
                "hard_rule_passed": False,
                "main_support": _ordered_unique(
                    [
                        *rebuilt_hits["core_feature_hits"],
                        *rebuilt_hits["auxiliary_feature_hits"],
                    ]
                ),
                "main_conflicts": _ordered_unique(downgrade_reasons),
                "_source_pointer": tag.get("_source_pointer"),
            }
        report.setdefault("style_downgrades", []).append(
            {
                "style_id": style_id,
                "source_pointer": tag.get("_source_pointer"),
                "reasons": _ordered_unique(downgrade_reasons),
            }
        )
        _record_change(report, f"{path}/demoted")
        return demoted_candidate
    return None



def _normalize_candidates(
    style_result: dict[str, Any], tags: list[dict[str, Any]],
    demoted_candidates: list[dict[str, Any]], styles: dict[str, dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """生成 confirmed 镜像，保留降级原因，并稳定排序候选。"""
    existing_candidates = style_result.get("candidate_ranking")
    raw_candidates = (
        [*demoted_candidates, *[item for item in existing_candidates if isinstance(item, dict)]]
        if isinstance(existing_candidates, list)
        else demoted_candidates
    )
    candidates: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for candidate in raw_candidates:
        style_id = str(candidate.get("style_id") or "")
        if style_id in seen_candidate_ids:
            _record_change(report, "/style_result/candidate_ranking/duplicate")
            continue
        seen_candidate_ids.add(style_id)
        candidates.append(candidate)
    candidate_by_id = {
        str(item.get("style_id") or ""): item
        for item in candidates
        if isinstance(item.get("style_id"), str)
    }
    tag_by_id = {str(tag.get("style_id") or ""): tag for tag in tags}
    for style_id, tag in tag_by_id.items():
        candidate = candidate_by_id.get(style_id)
        if candidate is None:
            candidate = {"style_id": style_id, "main_support": [], "main_conflicts": []}
            candidates.append(candidate)
            candidate_by_id[style_id] = candidate
        for key in (
            "label_en",
            "label_zh",
            "aliases",
            "tag_kind",
            "facet_ids",
            "match_score",
            "confidence",
            "dominance",
            "regions",
            "hard_rule_passed",
        ):
            candidate[key] = copy.deepcopy(tag.get(key))
        candidate["candidate_status"] = "confirmed"
        if not candidate.get("main_support"):
            candidate["main_support"] = _ordered_unique(
                [
                    *(tag.get("core_feature_hits") or []),
                    *(tag.get("auxiliary_feature_hits") or []),
                ]
            )
        candidate["main_conflicts"] = []

    for candidate in candidates:
        style_id = str(candidate.get("style_id") or "")
        if style_id in styles:
            candidate.update(_style_identity(styles[style_id]))
        if style_id not in tag_by_id:
            candidate["dominance"] = 0
            if candidate.get("candidate_status") == "confirmed":
                candidate["candidate_status"] = "provisional"

    candidates.sort(
        key=lambda item: (
            -float(item.get("match_score") or 0),
            str(item.get("style_id") or ""),
        )
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    _replace_if_changed(
        style_result, "candidate_ranking", candidates, "/style_result", report
    )



def _normalize_pairs(
    style_result: dict[str, Any], tags: list[dict[str, Any]],
    tag_relations: dict[str, Any], report: dict[str, Any],
) -> None:
    """仅重建已有仲裁的静态字段和引用，不补造缺失的语义理由。"""
    tag_by_id = {str(tag.get("style_id") or ""): tag for tag in tags}
    pair_relations = _pair_relation_map(tag_relations)
    default_relation = tag_relations.get("default_pair_relation")
    if not isinstance(default_relation, dict):
        default_relation = {}
    existing_pairs = style_result.get("pairwise_arbitrations")
    pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(existing_pairs, list):
        for item in existing_pairs:
            if not isinstance(item, dict):
                continue
            key = tuple(
                sorted(
                    (
                        str(item.get("style_id_a") or ""),
                        str(item.get("style_id_b") or ""),
                    )
                )
            )
            pair_by_key[key] = item
    rebuilt_pairs: list[dict[str, Any]] = []
    for style_id_a, style_id_b in combinations(sorted(tag_by_id), 2):
        key = (style_id_a, style_id_b)
        previous = pair_by_key.get(key)
        if previous is None:
            # 关系理由属于模型语义判断；缺失时不伪造，交由最终校验触发语义修复。
            continue
        relation = pair_relations.get(key, default_relation)
        rebuilt_pairs.append(
            {
                "style_id_a": style_id_a,
                "style_id_b": style_id_b,
                "relation": relation.get("relation"),
                "scope": relation.get("scope"),
                "decision": "coexist",
                "reason": previous.get("reason", ""),
                "evidence_refs": _ordered_unique(
                    [
                        *(previous.get("evidence_refs") or []),
                        *(tag_by_id[style_id_a].get("evidence_refs") or []),
                        *(tag_by_id[style_id_b].get("evidence_refs") or []),
                    ]
                ),
            }
        )
    _replace_if_changed(
        style_result,
        "pairwise_arbitrations",
        rebuilt_pairs,
        "/style_result",
        report,
    )


def _normalize_styles(
    data: dict[str, Any],
    styles: dict[str, dict[str, Any]],
    fields: dict[str, dict[str, Any]],
    evidence_rules: dict[str, Any],
    tag_relations: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    style_result = data.setdefault("style_result", {})
    raw_tags = style_result.get("style_tags")
    candidate_tags = (
        [item for item in raw_tags if isinstance(item, dict)]
        if isinstance(raw_tags, list)
        else []
    )
    tags: list[dict[str, Any]] = []
    seen_tag_ids: set[str] = set()
    for tag in candidate_tags:
        style_id = str(tag.get("style_id") or "")
        if style_id in seen_tag_ids:
            _record_change(report, "/style_result/style_tags/duplicate")
            continue
        seen_tag_ids.add(style_id)
        tags.append(tag)
    field_evidence = _field_evidence_index(element_index)
    evidence_regions = {
        str(item.get("evidence_id") or ""): str(item.get("region") or "")
        for item in data.get("evidence", [])
        if isinstance(item, dict)
    }
    demoted_candidates: list[dict[str, Any]] = []
    retained_tags: list[dict[str, Any]] = []
    review_policy = evidence_rules.get("review_policy")
    if not isinstance(review_policy, dict):
        review_policy = {}
    review_candidate_limit = review_policy.get("max_fields_per_role", 6)
    if not isinstance(review_candidate_limit, int) or review_candidate_limit < 1:
        review_candidate_limit = 6

    for index, tag in enumerate(tags):
        demoted = _normalize_style_tag(
            index, tag, styles, fields, evidence_rules, element_index,
            field_evidence, evidence_regions, review_candidate_limit, report,
        )
        if demoted is None:
            retained_tags.append(tag)
        else:
            demoted_candidates.append(demoted)

    tags = retained_tags

    if len(tags) == 1:
        _replace_if_changed(tags[0], "dominance", 1, "/style_result/style_tags/0", report)
    elif len(tags) > 1:
        values = [tag.get("dominance") for tag in tags]
        if all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) > 0
            for value in values
        ):
            total = sum(float(value) for value in values)
            normalized: list[float] = []
            for value in values[:-1]:
                normalized.append(round(float(value) / total, 6))
            normalized.append(round(1 - sum(normalized), 6))
            for index, value in enumerate(normalized):
                _replace_if_changed(
                    tags[index],
                    "dominance",
                    value,
                    f"/style_result/style_tags/{index}",
                    report,
                )

    tags.sort(
        key=lambda item: (
            -float(item.get("dominance") or 0),
            -float(item.get("match_score") or 0),
            str(item.get("style_id") or ""),
        )
    )
    _replace_if_changed(style_result, "style_tags", tags, "/style_result", report)
    _replace_if_changed(
        style_result,
        "classification_status",
        "confirmed" if tags else "unclassified",
        "/style_result",
        report,
    )
    if not tags and demoted_candidates:
        _replace_if_changed(
            style_result,
            "composition_summary",
            "候选风格的决定字段、辅助字段或区域证据未形成完整闭环，已降级为未分类。",
            "/style_result",
            report,
        )

    _normalize_candidates(style_result, tags, demoted_candidates, styles, report)
    _normalize_pairs(style_result, tags, tag_relations, report)
