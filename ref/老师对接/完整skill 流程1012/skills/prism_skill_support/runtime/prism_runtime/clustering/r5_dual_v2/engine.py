"""Versioned, overlapping evidence-pattern grouping of R5 ID and local CMF cues."""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from .adapter import load_record, producer
from .common import VERSION, canonical, digest, indexed, need, read, verify
from .quality import admission
from .scope import verify_confirmation


def _axis(pid):
    if pid.startswith("COL-"): return "color"
    if pid == "OPT-001": return "material_appearance"
    if pid == "OPT-002": return "gloss"
    if pid.startswith("TEX-"): return "texture"
    return "other_visible_CMF"


def _validate(request, records, scope):
    import jsonschema
    jsonschema.Draft202012Validator(read(Path(__file__).with_name("request.schema.json"))).validate(request)
    verify(scope)
    need(request["rule_version"] == VERSION and request["selection_digest"] == scope["selection_digest"], "Wrong rule or selection version")
    branch = request["branch"]
    need(request["schema_version"] == ("prism.h02.id_style.v2" if branch == "ID" else "prism.h02.cmf_local.v2"), "Branch/schema mismatch")
    directions = indexed(scope["directions"], "direction_id")
    need(request["direction_id"] in directions and branch in directions[request["direction_id"]]["branches"], "Unselected branch")
    direction = directions[request["direction_id"]]
    need(set(request["candidate_image_ids"]) == set(direction["candidate_image_ids"]), "Do not shrink or expand the selected direction's image pool")
    context = request["semantic_context"]
    need(context["title"] == direction["title"] and context["design_question"] == direction["design_question"],
         "The selected H01 design question/title must remain unchanged")
    if "unresolved" in direction:
        need(canonical(context["unresolved"]) == canonical(direction["unresolved"]), "H01 unresolved context was dropped")
    for side in ("trend", "research"):
        need(set(context[side + "_evidence_refs"]) == set(direction[side + "_evidence_refs"]), "Semantic direction evidence changed")
    known_semantics = set(context["trend_evidence_refs"] + context["research_evidence_refs"])
    assets = indexed(scope["asset_catalog"], "image_id")
    images = indexed(records, "image_id")
    need(set(images) <= set(request["candidate_image_ids"]), "Records outside the selected request")
    for iid, record in images.items():
        verify(record)
        need(record["schema_version"] == "prism.r5.cluster_record.v2" and record["asset"] == assets[iid]
             and record["image_sha256"] == assets[iid]["sha256"], "Source identity or role changed")
        if scope["dataset_mode"] != "synthetic_fixture":
            need(record["producer_metadata"].get("fixture_only") is not True
                 and record["producer_metadata"].get("not_a_model_output") is not True, "A fixture cannot become a real R5 result")
            need(record["validation"].get("file_identity_verified") is True, "Real inputs require source-bound load_record")
            validation = record["validation"]
            replay = load_record(record["asset"], validation["result_identity"], validation["quality_identity"])
            need(canonical(replay) == canonical(record), "Prepared R5 transport changed after source binding")
    observations = {o["observation_id"]: o for image in images.values() for o in image["observations"]}
    negative = indexed(request["negative_audit"], "negative_id")
    need(canonical(request["negative_audit"]) == canonical(scope["negative_audit"]), "Upstream negative audit was omitted or rewritten")
    indexed(request["patterns"], "pattern_id")
    model = producer()
    for pattern in request["patterns"]:
        need(set(pattern["semantic_refs"]) <= known_semantics, "Pattern invented semantic evidence")
        need(pattern["binding_scope"] == "declared_location" or branch == "ID", "CMF cannot use image-level union")
        core = indexed(pattern["core"], "parameter_id")
        support = indexed(pattern["support"], "parameter_id")
        need(not (set(core) & set(support)), "A core parameter cannot also inflate support ranking")
        need(len(core) >= 2, "At least two distinct core parameters are required")
        if branch == "ID":
            need(any(pid.startswith(("GEO-", "STR-", "REL-")) for pid in core), "ID requires form/structure/relation, not color alone")
        else:
            need(len({_axis(pid) for pid in core}) >= 2, "CMF needs two different visible axes")
        for feature in pattern["core"] + pattern["support"]:
            pid = feature["parameter_id"]
            need(pid in model.ACTIVE and branch in model.r3.views(pid)
                 and "引用" not in model.r3.PARAMS[pid].get("record_role", ""), "Wrong-view or nonvisual feature PID")
            anchors = [observations.get(ref) for ref in feature["observation_refs"]]
            need(all(a and a["parameter_id"] == pid and branch in a["views"] for a in anchors), "Feature source anchor is absent or mismatched")
            values = {canonical(v) for v in feature["allowed_values"]}
            need(values and values <= {canonical(a["value"]) for a in anchors}, "Allowed values were not preserved from source anchors")
        rules = indexed(pattern["negative_rules"], "negative_id")
        need(set(rules) == set(negative), "Every original negative must have an explicit disposition")
        for nid, rule in rules.items():
            need(set(rule["evidence_refs"]) == set(negative[nid]["evidence_refs"]), "Negative source audit changed")
            if rule["status"] == "executable":
                need(rule.get("parameter_id") in model.ACTIVE and rule.get("forbidden_values")
                     and rule.get("scope") in {"image", "declared_location"}, "Unresolved negative cannot be executable")
                need(not (pattern["binding_scope"] == "image_index" and rule["scope"] == "declared_location"), "Image-index ID has no one implicit local negative scope")
    need(all(b["image_id"] in request["candidate_image_ids"] for b in request["quality_bindings"]), "Quality binding is outside the selected pool")
    return images


def validate_request(request, records, *, scope):
    """Proposal-only preflight, without grouping or an invented confirmation."""
    images = _validate(request, records, scope)
    for image in images.values():
        admission(image, request["branch"], request["quality_bindings"])
    return {"passed": True, "mode": "proposal_only", "request_digest": digest(request),
            "scope_digest": scope["digest"], "records_available": len(images),
            "missing_image_ids": sorted(set(request["candidate_image_ids"]) - set(images)),
            "execution_authorized": False, "clustering_executed": False, "new_model_calls": 0}


def _pending(record, pid, location):
    return [x for x in record["unresolved_feature_bindings"] if x["parameter_id"] == pid
            and (location is None or x.get("at") in (None, location))]


def _feature(record, observations, rule, location, *, local):
    pid = rule["parameter_id"]
    found = [o for o in observations if o["parameter_id"] == pid]
    matched = [o for o in found if canonical(o["value"]) in {canonical(v) for v in rule["allowed_values"]}]
    pending = _pending(record, pid, location)
    if local and pending:
        return "pending", matched
    if matched:
        return "matched", matched
    return ("pending" if pending or not found else "mismatch"), []


def _negatives(record, pattern, location):
    audit, excluded, pending = [], False, False
    for rule in pattern["negative_rules"]:
        check = {"negative_id": rule["negative_id"], "status": rule["status"], "original_rule": deepcopy(rule)}
        if rule["status"] in {"deferred", "not_applicable"}:
            check["clearance_claimed"] = False
        elif rule["status"] == "pending":
            pending = True
            check["outcome"] = "unresolved_negative"
        else:
            pid = rule["parameter_id"]
            locations = record["locations"] if rule["scope"] == "image" else [location]
            facts = [o for o in record["observations"] if o["at"] in locations and o["parameter_id"] == pid]
            forbidden = [o for o in facts if canonical(o["value"]) in {canonical(v) for v in rule["forbidden_values"]}]
            gaps = [loc for loc in locations if _pending(record, pid, loc) or not any(o["at"] == loc for o in facts)]
            check.update(observation_refs=[o["observation_id"] for o in facts], missing_or_pending_locations=gaps,
                         forbidden_observation_refs=[o["observation_id"] for o in forbidden],
                         outcome="known_forbidden" if forbidden else "coverage_pending" if gaps else "clear_in_recorded_scope",
                         physical_absence_certified=False)
            excluded |= bool(forbidden)
            pending |= bool(gaps)
        audit.append(check)
    return audit, excluded, pending


def _member(record, pattern, branch, location, quality):
    local = location is not None
    facts = [o for o in record["observations"] if branch in o["views"] and (not local or o["at"] == location)]
    checks, evidence = [], []
    for core in pattern["core"]:
        status, matched = _feature(record, facts, core, location, local=local)
        checks.append({"parameter_id": core["parameter_id"], "status": status, "observation_refs": [o["observation_id"] for o in matched]})
        evidence.extend(matched)
    negatives, forbidden, unclear_negative = _negatives(record, pattern, location)
    if forbidden or any(c["status"] == "mismatch" for c in checks):
        return {"status": "excluded", "reason": "known_forbidden" if forbidden else "core_value_mismatch", "core_checks": checks, "negative_checks": negatives}
    if any(c["status"] == "pending" for c in checks) or unclear_negative:
        return {"status": "boundary", "reason": "core_or_negative_scope_pending", "core_checks": checks, "negative_checks": negatives}
    permitted = set(quality["allowed_locations"])
    # Keep whole-image facts for negatives. Only positive supporting locations
    # are restricted to the independently qualified, confirmed display scope.
    usable = [o for o in evidence if o["at"] in permitted]
    if not all(any(o["parameter_id"] == c["parameter_id"] for o in usable) for c in checks):
        return {"status": "boundary", "reason": "quality_scope_pending", "core_checks": checks, "negative_checks": negatives}
    support = []
    usable_facts = [o for o in facts if o["at"] in permitted]
    for auxiliary in pattern["support"]:
        status, matched = _feature(record, usable_facts, auxiliary, location, local=local)
        support.append({"parameter_id": auxiliary["parameter_id"], "status": status, "observation_refs": [o["observation_id"] for o in matched]})
    return {"status": "member", "image_id": record["image_id"], "image_sha256": record["image_sha256"],
        "source": deepcopy(record["asset"]), "location": location, "binding_scope": pattern["binding_scope"],
        "binding_basis": "exact_original_location_text" if local else "image_contains_recorded_ID_cues",
        "physical_carrier_identity_verified": False, "bounding_box": None,
        "core_checks": checks, "support_checks": support, "negative_checks": negatives,
        "core_evidence": deepcopy(usable), "known_route_evidence": deepcopy(usable_facts),
        "quality": deepcopy(quality), "original_unresolved": deepcopy(record["original_audit"]),
        "rank_basis": {"confirmed_support_parameter_count": sum(c["status"] == "matched" for c in support)},
        "visual_typicality_verified": False}


def _card(group, request):
    members = group["members"]
    by_fact = defaultdict(set)
    for member in members:
        for obs in member["known_route_evidence"]:
            by_fact[(obs["parameter_id"], canonical(obs["value"]))].add(member["image_sha256"])
    for member in members:
        shared = {o["parameter_id"] for o in member["known_route_evidence"] if len(by_fact[(o["parameter_id"], canonical(o["value"]))]) > 1}
        member["rank_basis"]["shared_recorded_parameter_count"] = len(shared)
    members.sort(key=lambda m: (-m["rank_basis"]["confirmed_support_parameter_count"], -m["rank_basis"]["shared_recorded_parameter_count"],
                               m["image_sha256"], m["image_id"], m["location"] or ""))
    main = next((m for m in members if m["quality"]["main_allowed"]), None)
    seen = {main["image_sha256"]} if main else set()
    secondary = []
    for member in members:
        if member["quality"]["support_allowed"] and member["image_sha256"] not in seen:
            secondary.append(member)
            seen.add(member["image_sha256"])
    source = lambda m: {"image_id": m["image_id"], "image_sha256": m["image_sha256"], "location": m["location"],
                        "source": deepcopy(m["source"]), "core_evidence": deepcopy(m["core_evidence"]),
                        "negative_checks": deepcopy(m["negative_checks"]),
                        "R5_unresolved": deepcopy(m["original_unresolved"]),
                        "quality_use": deepcopy(m["quality"].get("original_use")), "quality_bindings": deepcopy(m["quality"]["bindings"]),
                        "rank_basis": deepcopy(m["rank_basis"]), "quality_limits": deepcopy(m["quality"]["limitations"])}
    return {"schema_version": "prism.candidate_mood_card.v2", "status": "candidate_only",
        "branch": request["branch"], "direction_id": request["direction_id"], "pattern_id": group["pattern_id"],
        "title": group["label"], "semantic_context": deepcopy(request["semantic_context"]),
        "main_image": source(main) if main else None, "secondary_images": [source(m) for m in secondary],
        "main_selection_pending": bool(members) and main is None, "all_member_refs": [source(m) for m in members],
        "main_secondary_are_recommendations_not_usage_approval": True,
        "core_criteria": deepcopy(group["core_criteria"]), "observed_variations": deepcopy(group["observed_variations"]),
        "shared_observed_features": deepcopy(group["shared_observed_features"]),
        "negative_rule_dispositions": deepcopy(group["negative_rules"]),
        "negative_audit": deepcopy(request["negative_audit"]), "deferred_obligations": deepcopy(request["deferred_obligations"]),
        "crop_performed": False, "precise_ROI_available": False, "physical_measurement_approved": False,
        "real_material_approved": False, "product_design_approved": False, "Root_original_image_review_required": True}


def cluster(request, records, *, scope, confirmation):
    verify_confirmation(request, scope, confirmation)
    images = _validate(request, records, scope)
    result = {"schema_version": "prism.r5.dual_clusters.v2", "algorithm_version": VERSION,
        "rule_digest": digest(read(Path(__file__).with_name("rules.json"))), "request_digest": digest(request),
        "scope_digest": scope["digest"], "selection_digest": scope["selection_digest"],
        "scope_snapshot": deepcopy(scope), "input_records": [deepcopy(images[iid]) for iid in request["candidate_image_ids"] if iid in images],
        "request": deepcopy(request), "confirmation": deepcopy(confirmation), "branch": request["branch"],
        "groups": [], "outcomes": [], "candidate_cards": [], "image_dispositions": [],
        "new_model_calls": 0, "new_API_calls": 0, "product_design_approved": False,
        "real_material_approved": False, "physical_measurement_approved": False, "visual_effectiveness_established": False}
    for pattern in request["patterns"]:
        group = {"pattern_id": pattern["pattern_id"], "label": pattern["label"], "rationale": pattern["rationale"],
                 "core_criteria": deepcopy(pattern["core"]), "negative_rules": deepcopy(pattern["negative_rules"]), "members": []}
        for iid in request["candidate_image_ids"]:
            record = images.get(iid)
            base = {"image_id": iid, "pattern_id": pattern["pattern_id"]}
            if record is None:
                result["outcomes"].append({**base, "status": "missing_data", "reason": "R5_result_missing"})
                continue
            quality = admission(record, request["branch"], request["quality_bindings"])
            if quality["status"] in {"FAIL", "pending"}:
                result["outcomes"].append({**base, "status": "excluded" if quality["status"] == "FAIL" else "boundary",
                                           "reason": quality["reason"], "quality": quality})
                continue
            locations = record["locations_by_view"][request["branch"]] if pattern["binding_scope"] == "declared_location" else [None]
            if not locations:
                result["outcomes"].append({**base, "status": "boundary", "reason": "no_declared_locations"})
            for location in locations:
                member = _member(record, pattern, request["branch"], location, quality)
                result["outcomes"].append({**base, "location": location, **deepcopy(member)})
                if member["status"] == "member": group["members"].append(member)
        if not group["members"]:
            continue
        group["unique_image_count"] = len({m["image_sha256"] for m in group["members"]})
        group["status"] = "multi_image_group" if group["unique_image_count"] >= 2 else "singleton"
        variation = defaultdict(dict)
        for member in group["members"]:
            for obs in member["known_route_evidence"]:
                item = variation[obs["parameter_id"]].setdefault(canonical(obs["value"]), {"value": deepcopy(obs["value"]), "image_ids": set()})
                item["image_ids"].add(member["image_id"])
        group["observed_variations"] = [{"parameter_id": pid, "values": [{"value": v["value"], "image_ids": sorted(v["image_ids"])} for v in variants.values()]}
            for pid, variants in sorted(variation.items()) if len(variants) > 1]
        common = set.intersection(*[{(o["parameter_id"], canonical(o["value"])) for o in m["known_route_evidence"]} for m in group["members"]])
        group["shared_observed_features"] = [{"parameter_id": pid, "value": deepcopy(variation[pid][value]["value"])} for pid, value in sorted(common)]
        group["common_basis"] = "Every member satisfies the confirmed core predicates; allowed variants are not claimed identical."
        result["candidate_cards"].append(_card(group, request))
        result["groups"].append(group)
    for iid in request["candidate_image_ids"]:
        groups = [g for g in result["groups"] if any(m["image_id"] == iid for m in g["members"])]
        outcomes = [o for o in result["outcomes"] if o["image_id"] == iid]
        state = ("member" if any(g["status"] == "multi_image_group" for g in groups) else "singleton" if groups else
                 "missing_data" if iid not in images else "boundary" if any(o["status"] == "boundary" for o in outcomes) else
                 "excluded" if outcomes and all(o["status"] == "excluded" for o in outcomes) else "ungrouped")
        result["image_dispositions"].append({"image_id": iid, "status": state,
            "pattern_memberships": [g["pattern_id"] for g in groups],
            "has_boundary_scopes": any(o["status"] == "boundary" for o in outcomes), "all_outcomes_retained": True})
    result["summary"] = {"candidate_images": len(request["candidate_image_ids"]),
        "multi_image_groups": sum(g["status"] == "multi_image_group" for g in result["groups"]),
        "singleton_groups": sum(g["status"] == "singleton" for g in result["groups"]),
        "image_dispositions": dict(Counter(r["status"] for r in result["image_dispositions"])),
        "each_candidate_accounted_once": len(result["image_dispositions"]) == len(request["candidate_image_ids"])}
    result["ungrouped_patterns"] = [{"pattern_id": p["pattern_id"], "label": p["label"],
        "reason_counts": dict(Counter(o.get("reason", "unspecified") for o in result["outcomes"] if o["pattern_id"] == p["pattern_id"]))}
        for p in request["patterns"] if p["pattern_id"] not in {g["pattern_id"] for g in result["groups"]}]
    return result
