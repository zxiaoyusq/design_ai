"""风格候选列表的只读语义校验。"""
from __future__ import annotations

from typing import Any

from validation_rules import validate_style_identity


def _validate_styles(
    alias_to_field: dict[str, str],
    allowed_regions: set[str],
    color_roles: dict[str, str],
    default_pair_relation: dict[str, Any],
    evidence_regions: dict[str, str],
    explicit_pair_relations: dict[tuple[str, str], dict[str, Any]],
    fields: dict[str, dict[str, Any]],
    active_styles: dict[str, dict[str, Any]],
    canonical_elements: dict[tuple[str, str], dict[str, Any]],
    data: dict[str, Any],
    max_confirmed_tags: int,
    tag_dependencies: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """候选只要求真实支持、合法身份与稳定排名，不再套用 confirmed 硬门槛。"""

    del (
        alias_to_field,
        color_roles,
        default_pair_relation,
        evidence_regions,
        explicit_pair_relations,
        fields,
        canonical_elements,
        max_confirmed_tags,
        tag_dependencies,
    )
    style_result = data.get("style_result", {})
    for legacy_key in (
        "classification_status",
        "style_tags",
        "candidate_ranking",
        "pairwise_arbitrations",
        "primary_style",
        "secondary_styles",
    ):
        if legacy_key in style_result:
            errors.append(
                f"style_result: legacy field {legacy_key!r} is forbidden by the candidate-only contract"
            )

    candidates = [
        item
        for item in style_result.get("style_candidates", [])
        if isinstance(item, dict)
    ]
    ranks = [item.get("rank") for item in candidates]
    if ranks != list(range(1, len(candidates) + 1)):
        errors.append(
            "style_result.style_candidates: ranks must be consecutive from 1, "
            f"got {ranks}"
        )

    candidate_ids = [str(item.get("style_id") or "") for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("style_result.style_candidates: style_id values must be unique")

    if all(
        isinstance(item.get("match_score"), (int, float))
        and not isinstance(item.get("match_score"), bool)
        for item in candidates
    ):
        expected_order = [
            str(item.get("style_id") or "")
            for item in sorted(
                candidates,
                key=lambda item: (
                    -float(item.get("match_score")),
                    str(item.get("style_id") or ""),
                ),
            )
        ]
        if candidate_ids != expected_order:
            errors.append(
                "style_result.style_candidates: must use stable order "
                "(-match_score, style_id)"
            )

    for index, candidate in enumerate(candidates):
        path = f"style_result.style_candidates[{index}]"
        errors.extend(validate_style_identity(path, candidate, active_styles))
        invalid_regions = sorted(set(candidate.get("regions") or []) - allowed_regions)
        if invalid_regions:
            errors.append(
                f"{path}: regions outside target_object.visible_regions {invalid_regions}"
            )
        if not candidate.get("main_support"):
            errors.append(f"{path}: candidate requires at least one visible support item")

    style_confidence = data.get("quality_summary", {}).get("style_confidence")
    expected_style_confidence = max(
        (
            float(item.get("confidence"))
            for item in candidates
            if isinstance(item.get("confidence"), (int, float))
            and not isinstance(item.get("confidence"), bool)
        ),
        default=0.0,
    )
    if (
        isinstance(style_confidence, (int, float))
        and style_confidence != expected_style_confidence
    ):
        errors.append(
            f"quality_summary.style_confidence={style_confidence}, "
            f"expected {expected_style_confidence}"
        )
