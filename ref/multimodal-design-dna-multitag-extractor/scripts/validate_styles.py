"""确认风格、候选及标签关系的只读语义校验。"""
from __future__ import annotations

from itertools import combinations
from typing import Any

from validation_rules import (
    INLINE_FIELD_REF_PATTERN,
    validate_rule_coverage,
    validate_style_feature_hits,
    validate_style_identity,
)


def _validate_confirmed_tags(
    active_styles: dict[str, dict[str, Any]],
    alias_to_field: dict[str, str],
    allowed_regions: set[str],
    assessments: list[tuple[str, dict[str, Any]]],
    color_roles: dict[str, str],
    confirmed_field_evidence_ids: dict[str, set[str]],
    confirmed_usable_field_ids: set[str],
    evidence_regions: dict[str, str],
    fields: dict[str, dict[str, Any]],
    style_tags: list[dict[str, Any]],
    usable_field_ids: set[str],
    usable_field_values: dict[str, list[Any]],
    errors: list[str],
) -> None:
    """核对确认标签的强证据、特殊门槛、颜色与区域闭环。"""
    for path, item in assessments[: len(style_tags)]:
        style_id = str(item.get("style_id") or "")
        if (
            not isinstance(item.get("confidence"), (int, float))
            or isinstance(item.get("confidence"), bool)
            or item.get("confidence") < 0.75
        ):
            errors.append(f"{path}: confirmed style confidence must be >= 0.75")
        invalid_regions = sorted(set(item.get("regions") or []) - allowed_regions)
        if invalid_regions:
            errors.append(f"{path}: regions outside target_object.visible_regions {invalid_regions}")
        if color_roles.get(style_id) == "required" and item.get("color_requirement", {}).get("status") == "not_applicable":
            errors.append(f"{path}.color_requirement: required color role cannot be not_applicable")
        errors.extend(
            validate_style_feature_hits(
                path,
                item,
                fields,
                alias_to_field,
                usable_field_ids,
                confirmed_usable_field_ids,
                confirmed_field_evidence_ids,
                active_styles.get(style_id, {}),
            )
        )
        policy = active_styles.get(style_id, {}).get("cue_family_policy")
        if isinstance(policy, dict):
            cited_core_field_ids = {
                field_id
                for hit in item.get("core_feature_hits", [])
                for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
                if field_id in confirmed_usable_field_ids
            }
            cited_field_ids = {
                field_id
                for key in ("core_feature_hits", "auxiliary_feature_hits")
                for hit in item.get(key, [])
                for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
                if field_id in confirmed_usable_field_ids
            }
            raw_families = policy.get("families")
            families = raw_families if isinstance(raw_families, dict) else {}
            family_hits = {
                family_name: cited_field_ids.intersection(family_field_ids)
                for family_name, family_field_ids in families.items()
                if isinstance(family_field_ids, list)
                and cited_field_ids.intersection(family_field_ids)
            }
            family_evidence = {
                family_name: {
                    evidence_id
                    for field_id in family_field_ids
                    for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
                    if evidence_id in set(item.get("evidence_refs") or [])
                }
                for family_name, family_field_ids in family_hits.items()
            }
            min_families = policy.get("min_distinct_families")
            independent_family_group: tuple[str, ...] = ()
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
                        independent_family_group = family_group
                        break
            if isinstance(min_families, int) and len(independent_family_group) < min_families:
                errors.append(
                    f"{path}: cue_family_policy requires at least {min_families} cue families "
                    "with mutually unshared field evidence; "
                    f"found no qualifying group among {sorted(family_evidence)}"
                )
            expressive_gate = policy.get("expressive_gate")
            gate_field_id = (
                expressive_gate.get("field_id") if isinstance(expressive_gate, dict) else None
            )
            gate_values = set(
                expressive_gate.get("allowed_values") or []
                if isinstance(expressive_gate, dict)
                else []
            )
            if (
                not isinstance(gate_field_id, str)
                or gate_field_id not in cited_core_field_ids
                or not any(value in gate_values for value in usable_field_values.get(gate_field_id, []))
            ):
                errors.append(
                    f"{path}: cue_family_policy expressive_gate requires core {gate_field_id!r} "
                    f"with one of {sorted(gate_values)}"
                )
        coverage = item.get("rule_coverage", {})
        errors.extend(validate_rule_coverage(path, item))
        if not item.get("hard_rule_passed") or item.get("missing_required_items") or item.get("exclusion_hits"):
            errors.append(f"{path}: every confirmed tag must pass hard rules without missing or exclusions")
        if coverage.get("failed_rule_count") != 0 or coverage.get("unknown_rule_count") != 0:
            errors.append(f"{path}: confirmed tag requires zero failed and unknown rules")
        if coverage.get("applicable_rule_count", 0) < 1 or coverage.get("passed_rule_count", 0) < 1:
            errors.append(
                f"{path}: confirmed tag requires applicable_rule_count>=1 and passed_rule_count>=1"
            )
        if not item.get("core_feature_hits") or not item.get("auxiliary_feature_hits"):
            errors.append(f"{path}: confirmed tag requires a decisive anchor and independent support")
        if len(item.get("evidence_refs") or []) < 2:
            errors.append(f"{path}: confirmed tag requires at least two evidence refs")
        backed_regions = {
            evidence_regions.get(str(ref), "") for ref in item.get("evidence_refs", [])
        }
        unbacked_regions = sorted(set(item.get("regions") or []) - backed_regions)
        if unbacked_regions:
            errors.append(f"{path}: regions lack matching referenced evidence {unbacked_regions}")


def _validate_candidates(
    allowed_regions: set[str],
    candidates: list[dict[str, Any]],
    status: str,
    style_tags: list[dict[str, Any]],
    tag_ids: list[str],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    """核对候选排序及其与 confirmed 标签的镜像一致性。"""
    ranks = [item.get("rank") for item in candidates]
    if ranks != list(range(1, len(candidates) + 1)):
        errors.append(f"style_result.candidate_ranking: ranks must be consecutive from 1, got {ranks}")
    candidate_ids = [item.get("style_id") for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("style_result.candidate_ranking: style_id values must be unique")
    if all(
        isinstance(item.get("match_score"), (int, float)) and not isinstance(item.get("match_score"), bool)
        for item in candidates
    ):
        expected_candidate_order = [
            item.get("style_id")
            for item in sorted(
                candidates,
                key=lambda item: (-float(item.get("match_score")), str(item.get("style_id") or "")),
            )
        ]
        if candidate_ids != expected_candidate_order:
            errors.append(
                "style_result.candidate_ranking: must use stable order (-match_score, style_id)"
            )
    confirmed_candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        path = f"style_result.candidate_ranking[{index}]"
        candidate_status = candidate.get("candidate_status")
        dominance = candidate.get("dominance")
        if candidate_status == "confirmed":
            confirmed_candidate_ids.add(str(candidate.get("style_id") or ""))
            if not candidate.get("hard_rule_passed"):
                errors.append(f"{path}: confirmed candidate requires hard_rule_passed=true")
            if not isinstance(dominance, (int, float)) or isinstance(dominance, bool) or dominance <= 0:
                errors.append(f"{path}: confirmed candidate requires dominance > 0")
            if (
                not isinstance(candidate.get("confidence"), (int, float))
                or isinstance(candidate.get("confidence"), bool)
                or candidate.get("confidence") < 0.75
            ):
                errors.append(f"{path}: confirmed candidate confidence must be >= 0.75")
        elif candidate_status in {"provisional", "rejected"}:
            if dominance != 0:
                errors.append(f"{path}: non-confirmed candidate requires dominance=0")
            if candidate.get("hard_rule_passed") is True and not candidate.get("main_conflicts"):
                errors.append(
                    f"{path}: non-confirmed hard_rule_passed=true requires non-empty main_conflicts"
                )
        invalid_regions = sorted(set(candidate.get("regions") or []) - allowed_regions)
        if invalid_regions:
            errors.append(f"{path}: regions outside target_object.visible_regions {invalid_regions}")

    candidate_by_id = {str(item.get("style_id") or ""): item for item in candidates}
    if confirmed_candidate_ids != set(tag_ids):
        errors.append(
            "style_result: candidate_status=confirmed IDs must exactly equal style_tags IDs"
        )
    if status == "unclassified" and confirmed_candidate_ids:
        errors.append("style_result: unclassified cannot contain confirmed candidates")
    for index, tag in enumerate(style_tags):
        path = f"style_result.style_tags[{index}]"
        style_id = str(tag.get("style_id") or "")
        candidate = candidate_by_id.get(style_id)
        if candidate is None:
            errors.append(f"{path}: confirmed style must appear in candidate_ranking")
            continue
        if candidate.get("candidate_status") != "confirmed":
            errors.append(f"{path}: matching candidate_status must be confirmed")
        for key in (
            "label_en",
            "label_zh",
            "aliases",
            "tag_kind",
            "match_score",
            "confidence",
            "dominance",
            "regions",
            "hard_rule_passed",
        ):
            if key in {"aliases", "regions"}:
                matches = set(candidate.get(key) or []) == set(tag.get(key) or [])
            else:
                matches = candidate.get(key) == tag.get(key)
            if not matches:
                errors.append(f"{path}: candidate_ranking value differs for {key}")
        if set(candidate.get("facet_ids") or []) != set(tag.get("facet_ids") or []):
            errors.append(f"{path}: candidate_ranking value differs for facet_ids")

    return candidate_by_id


def _validate_pairs(
    arbitrations: list[dict[str, Any]],
    confirmed_field_evidence_ids: dict[str, set[str]],
    default_pair_relation: dict[str, Any],
    explicit_pair_relations: dict[tuple[str, str], dict[str, Any]],
    style_tags: list[dict[str, Any]],
    tag_ids: list[str],
    errors: list[str],
) -> None:
    """逐对校验作用域、独占证据和仲裁数量，不修改模型结论。"""
    def regions_overlap(left: set[str], right: set[str]) -> bool:
        return bool(left & right) or "whole_object" in left or "whole_object" in right

    expected_pair_keys = {
        tuple(sorted((tag_ids[left], tag_ids[right])))
        for left in range(len(tag_ids))
        for right in range(left + 1, len(tag_ids))
    }
    actual_pair_keys: list[tuple[str, str]] = []
    tags_by_id = {str(item.get("style_id") or ""): item for item in style_tags}
    for index, arbitration in enumerate(arbitrations):
        path = f"style_result.pairwise_arbitrations[{index}]"
        style_a = str(arbitration.get("style_id_a") or "")
        style_b = str(arbitration.get("style_id_b") or "")
        if style_a >= style_b:
            errors.append(f"{path}: style_id_a/style_id_b must use canonical lexical order")
        pair_key = tuple(sorted((style_a, style_b)))
        actual_pair_keys.append(pair_key)
        if style_a == style_b or style_a not in tags_by_id or style_b not in tags_by_id:
            errors.append(f"{path}: pair must reference two distinct confirmed style tags")
            continue
        expected_relation = explicit_pair_relations.get(pair_key, default_pair_relation)
        relation = arbitration.get("relation")
        scope = arbitration.get("scope")
        if relation != expected_relation.get("relation"):
            errors.append(f"{path}: relation must match tag-relations for pair {pair_key}")
        if scope != expected_relation.get("scope"):
            errors.append(f"{path}: scope must match tag-relations for pair {pair_key}")
        if arbitration.get("decision") != "coexist":
            errors.append(f"{path}: confirmed tag pairs require decision='coexist'")

        tag_a, tag_b = tags_by_id[style_a], tags_by_id[style_b]
        shared_evidence = bool(
            set(tag_a.get("evidence_refs") or []) & set(tag_b.get("evidence_refs") or [])
        )
        region_overlap = shared_evidence or regions_overlap(
            set(tag_a.get("regions") or []), set(tag_b.get("regions") or [])
        )
        core_ids_a = {
            field_id
            for hit in tag_a.get("core_feature_hits", [])
            for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
        }
        core_ids_b = {
            field_id
            for hit in tag_b.get("core_feature_hits", [])
            for field_id in INLINE_FIELD_REF_PATTERN.findall(str(hit))
        }
        independent_mechanisms = bool(core_ids_a - core_ids_b) and bool(core_ids_b - core_ids_a)
        conflict_facets = set(expected_relation.get("conflict_facet_ids") or [])
        if not conflict_facets and pair_key not in explicit_pair_relations:
            conflict_facets = set(tag_a.get("facet_ids") or []) & set(tag_b.get("facet_ids") or [])
        uses_default_relation = pair_key not in explicit_pair_relations
        has_conflict_facet = bool(conflict_facets & set(tag_a.get("facet_ids") or [])) and bool(
            conflict_facets & set(tag_b.get("facet_ids") or [])
        )
        core_evidence_a = {
            evidence_id
            for field_id in core_ids_a
            for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
            if evidence_id in set(tag_a.get("evidence_refs") or [])
        }
        core_evidence_b = {
            evidence_id
            for field_id in core_ids_b
            for evidence_id in confirmed_field_evidence_ids.get(field_id, set())
            if evidence_id in set(tag_b.get("evidence_refs") or [])
        }
        exclusive_core_evidence_a = core_evidence_a - core_evidence_b
        exclusive_core_evidence_b = core_evidence_b - core_evidence_a
        pair_refs = set(arbitration.get("evidence_refs") or [])
        if (
            relation == "conditional"
            and region_overlap
            and (uses_default_relation or has_conflict_facet)
        ):
            same_region_mode = expected_relation.get("same_region_coexistence")
            if same_region_mode == "forbidden":
                errors.append(
                    f"{path}: conditional conflict facets {sorted(conflict_facets)} use "
                    "same_region_coexistence=forbidden and cannot coexist on overlapping regions"
                )
            elif same_region_mode == "independent_evidence" and not (
                independent_mechanisms
                and exclusive_core_evidence_a
                and exclusive_core_evidence_b
                and pair_refs.intersection(exclusive_core_evidence_a)
                and pair_refs.intersection(exclusive_core_evidence_b)
            ):
                errors.append(
                    f"{path}: same-region conditional coexistence requires different core fields, "
                    "mutually exclusive core field evidence, and arbitration refs for both sides"
                )
        if relation == "exclusive" and scope == "global":
            errors.append(f"{path}: globally exclusive tags cannot both be confirmed")
        if (
            relation in {"exclusive", "conditional"}
            and scope in {"same_region_same_mechanism", "cross_region_or_mechanism"}
            and region_overlap
            and not independent_mechanisms
        ):
            errors.append(
                f"{path}: coexistence requires region separation or independent core mechanisms under scope={scope}"
            )
        if (
            relation == "compatible"
            and scope == "cross_region_or_mechanism"
            and region_overlap
            and not independent_mechanisms
        ):
            errors.append(
                f"{path}: compatible cross-region/mechanism coexistence requires region separation "
                "or independent core mechanisms"
            )
        if not pair_refs.intersection(tag_a.get("evidence_refs") or []):
            errors.append(f"{path}: evidence_refs must include evidence for {style_a}")
        if not pair_refs.intersection(tag_b.get("evidence_refs") or []):
            errors.append(f"{path}: evidence_refs must include evidence for {style_b}")

    if len(actual_pair_keys) != len(expected_pair_keys):
        errors.append(
            "style_result.pairwise_arbitrations: count must equal C(n,2) for confirmed tags"
        )
    if len(actual_pair_keys) != len(set(actual_pair_keys)):
        errors.append("style_result.pairwise_arbitrations: unordered style pairs must be unique")
    if set(actual_pair_keys) != expected_pair_keys:
        errors.append(
            "style_result.pairwise_arbitrations: pairs must exactly cover all confirmed tag combinations"
        )


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
    """核对确认标签、候选镜像、标签关系和风格统计。"""
    style_result = data.get("style_result", {})
    for legacy_key in ("primary_style", "secondary_styles"):
        if legacy_key in style_result:
            errors.append(f"style_result: legacy field {legacy_key!r} is forbidden by the flat multi-tag contract")
    status = style_result.get("classification_status")
    if status == "provisional":
        errors.append("style_result: provisional is not supported; use confirmed or unclassified")
    style_tags = [item for item in style_result.get("style_tags", []) if isinstance(item, dict)]
    candidates = [item for item in style_result.get("candidate_ranking", []) if isinstance(item, dict)]
    arbitrations = [
        item for item in style_result.get("pairwise_arbitrations", []) if isinstance(item, dict)
    ]
    if status == "confirmed" and not style_tags:
        errors.append("style_result: confirmed requires at least one style tag")
    if status == "unclassified" and style_tags:
        errors.append("style_result: unclassified requires style_tags=[]")
    if len(style_tags) > max_confirmed_tags:
        errors.append(
            f"style_result.style_tags: found {len(style_tags)}, tag-relations allows {max_confirmed_tags}"
        )

    assessments: list[tuple[str, dict[str, Any]]] = [
        (f"style_result.style_tags[{i}]", item) for i, item in enumerate(style_tags)
    ]
    assessments.extend((f"style_result.candidate_ranking[{i}]", item) for i, item in enumerate(candidates))
    for path, item in assessments:
        errors.extend(validate_style_identity(path, item, active_styles))

    tag_ids = [str(item.get("style_id") or "") for item in style_tags]
    if len(tag_ids) != len(set(tag_ids)):
        errors.append("style_result.style_tags: style_id values must be unique")
    dominances = [item.get("dominance") for item in style_tags]
    numeric_dominances = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in dominances
    )
    if numeric_dominances:
        if len(dominances) == 1 and float(dominances[0]) != 1:
            errors.append("style_result.style_tags: a single confirmed tag requires dominance=1")
        if len(dominances) > 1 and not 0.99 <= sum(float(value) for value in dominances) <= 1.01:
            errors.append("style_result.style_tags: non-empty dominance values must sum to about 1")
        if all(
            isinstance(item.get("match_score"), (int, float))
            and not isinstance(item.get("match_score"), bool)
            for item in style_tags
        ):
            expected_tag_order = [
                str(item.get("style_id") or "")
                for item in sorted(
                    style_tags,
                    key=lambda item: (
                        -float(item.get("dominance")),
                        -float(item.get("match_score")),
                        str(item.get("style_id") or ""),
                    ),
                )
            ]
            if tag_ids != expected_tag_order:
                errors.append(
                    "style_result.style_tags: must use stable order "
                    "(-dominance, -match_score, style_id)"
                )
    def is_usable_confirmed_value(element: dict[str, Any]) -> bool:
        return element.get("value") is not None and (
            (element.get("evidence_mode") == "direct" and element.get("observability") == "observed")
            or (element.get("evidence_mode") != "direct" and element.get("computation_status") == "computed")
        )

    usable_field_ids = {
        str(element.get("field_id"))
        for element in canonical_elements.values()
        if is_usable_confirmed_value(element)
    }
    confirmed_usable_field_ids = {
        str(element.get("field_id"))
        for element in canonical_elements.values()
        if is_usable_confirmed_value(element)
        and isinstance(element.get("confidence"), (int, float))
        and not isinstance(element.get("confidence"), bool)
        and element.get("confidence") >= 0.75
    }
    usable_field_values: dict[str, list[Any]] = {}
    confirmed_field_evidence_ids: dict[str, set[str]] = {}
    for element in canonical_elements.values():
        field_id = str(element.get("field_id") or "")
        if (
            is_usable_confirmed_value(element)
            and isinstance(element.get("confidence"), (int, float))
            and not isinstance(element.get("confidence"), bool)
            and element.get("confidence") >= 0.75
        ):
            usable_field_values.setdefault(field_id, []).append(element.get("value"))
            confirmed_field_evidence_ids.setdefault(field_id, set()).update(
                element.get("evidence_refs") or []
            )
    _validate_confirmed_tags(
        active_styles=active_styles,
        alias_to_field=alias_to_field,
        allowed_regions=allowed_regions,
        assessments=assessments,
        color_roles=color_roles,
        confirmed_field_evidence_ids=confirmed_field_evidence_ids,
        confirmed_usable_field_ids=confirmed_usable_field_ids,
        evidence_regions=evidence_regions,
        fields=fields,
        style_tags=style_tags,
        usable_field_ids=usable_field_ids,
        usable_field_values=usable_field_values,
        errors=errors,
    )

    candidate_by_id = _validate_candidates(
        allowed_regions=allowed_regions,
        candidates=candidates,
        status=status,
        style_tags=style_tags,
        tag_ids=tag_ids,
        errors=errors,
    )

    _validate_pairs(
        arbitrations=arbitrations,
        confirmed_field_evidence_ids=confirmed_field_evidence_ids,
        default_pair_relation=default_pair_relation,
        explicit_pair_relations=explicit_pair_relations,
        style_tags=style_tags,
        tag_ids=tag_ids,
        errors=errors,
    )

    confirmed_id_set = set(tag_ids)
    candidate_id_set = set(candidate_by_id)
    for dependency in tag_dependencies:
        source = dependency.get("source_style_id")
        targets = set(dependency.get("target_style_ids") or [])
        if source not in confirmed_id_set:
            continue
        quantifier = dependency.get("target_quantifier")
        available = confirmed_id_set if dependency.get("relation") == "requires" else candidate_id_set
        satisfied = targets.issubset(available) if quantifier == "all" else bool(targets & available)
        if not satisfied:
            errors.append(
                "style_result.style_tags: "
                f"{source} {dependency.get('relation')} target_quantifier={quantifier} "
                f"for {sorted(targets)}"
            )

    style_confidence = data.get("quality_summary", {}).get("style_confidence")
    expected_style_confidence = max(
        (float(item.get("confidence")) for item in style_tags if isinstance(item.get("confidence"), (int, float))),
        default=0.0,
    )
    if isinstance(style_confidence, (int, float)) and style_confidence != expected_style_confidence:
        errors.append(
            f"quality_summary.style_confidence={style_confidence}, expected {expected_style_confidence}"
        )
