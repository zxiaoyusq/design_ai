"""把模型给出的真实风格候选整理为稳定、可展示的最终列表。"""
from __future__ import annotations

import copy
from typing import Any

from compilation_support import _ordered_unique, _record_change, _replace_if_changed


MAX_STYLE_CANDIDATES = 5


def _style_identity(record: dict[str, Any]) -> dict[str, Any]:
    """风格名称等静态信息只信任注册表，不要求模型重复生成。"""

    return {
        "label_en": record.get("display_name_en"),
        "label_zh": record.get("display_name_zh"),
        "aliases": list(record.get("aliases") or []),
        "tag_kind": record.get("tag_kind"),
        "facet_ids": list(record.get("facet_ids") or []),
    }


def _legacy_candidates(style_result: dict[str, Any]) -> list[dict[str, Any]]:
    """只用于读取升级前的结果骨架；新模型不会再输出这些旧字段。"""

    merged: list[dict[str, Any]] = []
    confirmed = style_result.get("style_tags")
    if isinstance(confirmed, list):
        for item in confirmed:
            if not isinstance(item, dict):
                continue
            copied = copy.deepcopy(item)
            copied["main_support"] = _ordered_unique(
                [
                    *(copied.get("main_support") or []),
                    *(copied.get("core_feature_hits") or []),
                    *(copied.get("auxiliary_feature_hits") or []),
                ]
            )
            copied.setdefault("main_conflicts", [])
            merged.append(copied)

    ranked = style_result.get("candidate_ranking")
    if isinstance(ranked, list):
        merged.extend(
            copy.deepcopy(item)
            for item in ranked
            if isinstance(item, dict) and item.get("candidate_status") != "rejected"
        )
    return merged


def _normalize_styles(
    data: dict[str, Any],
    styles: dict[str, dict[str, Any]],
    fields: dict[str, dict[str, Any]],
    evidence_rules: dict[str, Any],
    tag_relations: dict[str, Any],
    element_index: dict[tuple[str, str], dict[str, Any]],
    report: dict[str, Any],
) -> None:
    """整理候选元数据和顺序；不再执行确认、降级或两两仲裁。"""

    del fields, evidence_rules, tag_relations, element_index
    style_result = data.setdefault("style_result", {})
    raw_candidates = style_result.get("style_candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = _legacy_candidates(style_result)

    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_regions = {
        str(region)
        for region in data.get("target_object", {}).get("visible_regions", [])
        if isinstance(region, str)
    }
    for source_index, item in enumerate(raw_candidates):
        if not isinstance(item, dict):
            continue
        style_id = str(item.get("style_id") or "")
        if style_id in seen_ids:
            _record_change(report, "/style_result/style_candidates/duplicate")
            continue
        seen_ids.add(style_id)

        candidate = {
            "style_id": style_id,
            "match_score": item.get("match_score"),
            "confidence": item.get("confidence"),
            "regions": _ordered_unique(
                [
                    region
                    for region in item.get("regions", [])
                    if isinstance(region, str) and region in allowed_regions
                ]
            ),
            "main_support": _ordered_unique(
                [
                    str(value).strip()
                    for value in item.get("main_support", [])
                    if str(value).strip()
                ]
            ),
            "main_conflicts": _ordered_unique(
                [
                    str(value).strip()
                    for value in item.get("main_conflicts", [])
                    if str(value).strip()
                ]
            ),
            "_source_pointer": item.get(
                "_source_pointer", f"/style_result/style_candidates/{source_index}"
            ),
        }
        registry_record = styles.get(style_id)
        if registry_record is not None:
            candidate.update(_style_identity(registry_record))
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            -float(item.get("match_score") or 0),
            str(item.get("style_id") or ""),
        )
    )
    if len(candidates) > MAX_STYLE_CANDIDATES:
        candidates = candidates[:MAX_STYLE_CANDIDATES]
        _record_change(report, "/style_result/style_candidates/maxItems")
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    _replace_if_changed(
        style_result,
        "style_candidates",
        candidates,
        "/style_result",
        report,
    )
    for legacy_key in (
        "classification_status",
        "style_tags",
        "candidate_ranking",
        "pairwise_arbitrations",
    ):
        if legacy_key in style_result:
            style_result.pop(legacy_key, None)
            _record_change(report, f"/style_result/{legacy_key}")
