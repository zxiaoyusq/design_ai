"""Source-bound CMF comparison, independent from the frozen v3 algorithms.

The protocol validates evidence and decisions; it does not see pixels, infer
similarity, render views, or turn syntactic validity into visual approval.
"""
from collections import defaultdict
from copy import deepcopy

from .common import (VERSION, canonical, checked, digest, indexed, need, pick, pins,
                     pointer, reject_fixture, review_provenance, seal, text, verify)
from .quality import consume

PREFIX = "prism.cmf."


def _shape(value, schema):
    need(value.get("schema_version") == PREFIX + schema + ".v4", "schema_required:" + schema)


def _brief(ref):
    brief = checked(ref)
    _shape(brief, "visual_brief")
    need(text(brief.get("brief_id")), "brief_id_required")
    h01 = checked(brief["h01_ref"])
    if "digest" in h01:
        verify(h01)
    if "selection_digest" in h01:
        need(h01["selection_digest"] == digest({k: v for k, v in h01.items() if k != "selection_digest"}), "selection_digest_changed")
    need(h01.get("status") == "confirmed" or h01.get("confirmation", {}).get("status") == "confirmed", "H01_confirmation_required")
    choice = pointer(h01, brief["h01_pointer"])
    need(choice.get("direction_id") == brief.get("direction_id") and "CMF" in choice.get("branches", []), "selected_CMF_direction_required")
    direction = pick(brief["direction_evidence"]) if brief.get("direction_evidence") else choice
    need(direction.get("direction_id") == brief["direction_id"], "semantic_direction_mismatch")
    for name in ("negative_audit", "deferred_obligations"):
        ev = brief.get("audit_evidence", {}).get(name)
        original = pick(ev) if ev else direction.get(name)
        need(isinstance(original, list) and brief.get(name) == original, "complete_original_audit_required:" + name)
    need(brief.get("comparison_unit") in {"surface", "same_object_interface"}, "CMF_comparison_unit_required")
    primary = brief["primary_signature"]
    need(text(primary.get("description")) and primary.get("conditions"), "specific_joint_signature_required")
    conditions = indexed(primary["conditions"], "id")
    need(all(text(v.get("question")) for v in conditions.values()), "condition_question_required")
    secondary = indexed(brief["secondary_dimensions"], "id")
    need(not set(conditions) & set(secondary), "primary_secondary_id_collision")
    need(all(text(v.get("question")) and type(v.get("required")) is bool for v in secondary.values()), "secondary_definition_required")
    variation = indexed(brief["allowed_variation"], "id")
    need(all(text(v.get("description")) and text(v.get("boundary")) for v in variation.values()), "variation_boundary_required")
    confounders = indexed(brief["confounders"], "id")
    need(confounders and all(text(v.get("description")) for v in confounders.values()), "confounders_required")
    need(isinstance(brief.get("scope_limits"), list) and brief["scope_limits"], "scope_limits_required")
    count = brief["count_policy"]
    need(all(type(count.get(k)) is int for k in ("target", "minimum", "maximum")) and
         1 <= count["minimum"] <= count["target"] <= count["maximum"] and text(count.get("basis")), "explicit_count_policy_required")
    need(brief.get("calibration_refs"), "calibration_reference_required")
    for row in brief["calibration_refs"]:
        need(row.get("role") == "calibration_only" and row.get("pages_or_labels"), "calibration_only_required")
        checked(row["ref"], False)
    return brief, {"h01_snapshot": deepcopy(h01), "selection_snapshot": deepcopy(choice), "direction_snapshot": deepcopy(direction)}


def _pixels(ref):
    # Read metadata only. This module never crops, rewrites, or renders an image.
    from PIL import Image
    checked(ref, False)
    with Image.open(ref["path"]) as image:
        return [image.width, image.height]


def _record(record, image, mode):
    verify(record)
    reject_fixture(record, mode)
    need(record.get("schema_version") == "prism.r5.cluster_record.v2", "R5_record_required")
    need(record["image_id"] == image["image_id"] and record["image_sha256"] == image["image_ref"]["sha256"]
         and record["asset"]["source_kind"] == image["source_kind"], "R5_image_source_mismatch")
    validation = record["validation"]
    need(validation.get("file_identity_verified") is True and validation.get("image_identity") == image["image_ref"], "file_bound_R5_required")
    from ..r5_dual_v2.adapter import load_record, producer
    replay = load_record(record["asset"], validation["result_identity"], validation.get("quality_identity"))
    need(replay == record, "R5_record_not_replayable")
    model = producer()
    buckets = defaultdict(list)
    for observation in record["observations"]:
        pid = observation["parameter_id"]
        if "CMF" in observation["views"] and pid.split("-")[0] in {"COL", "OPT", "TEX", "TXT", "EMI"}:
            if "引用" not in model.r3.PARAMS[pid].get("record_role", ""):
                buckets[(observation["at"], pid)].append(observation)
    clean, withheld = {}, []
    for (at, pid), rows in buckets.items():
        reason = None
        values = [r["value"] for r in rows]
        if any(v is None or any(x in model.NON_FEATURE for x in (v if isinstance(v, list) else [v])
                               if isinstance(x, str)) for v in values):
            reason = "unknown_or_non_feature"
        elif any(x["parameter_id"] == pid and x.get("at") in (None, at) for x in record["unresolved_feature_bindings"]):
            reason = "pending_or_invalid_original_fact"
        elif len({canonical(v) for v in values}) > 1:
            reason = "ambiguous_original_values"
        if reason:
            withheld.append({"reason": reason, "observations": deepcopy(rows)})
        else:
            clean.update({r["observation_id"]: r for r in rows})
    return clean, withheld


def _binding(unit, image, record, quality, mode):
    if not unit.get("target_binding_ref"):
        return None, "target_to_R5_confirmation_missing"
    binding = checked(unit["target_binding_ref"])
    _shape(binding, "target_binding")
    for key, value in {"unit_id": unit["unit_id"], "image_ref": image["image_ref"], "target_ref": unit["target_ref"],
                       "endpoints": unit["endpoints"], "record_digest": record["digest"],
                       "quality_result_digest": quality["quality_result_digest"]}.items():
        need(binding.get(key) == value, "target_binding_mismatch:" + key)
    if binding.get("original_image_seen") is not True:
        return binding, "target_original_not_reviewed"
    endpoint_reviews = indexed(binding["endpoint_reviews"], "endpoint_id")
    need(set(endpoint_reviews) == {e["endpoint_id"] for e in unit["endpoints"]}, "endpoint_review_incomplete")
    for endpoint in unit["endpoints"]:
        r = endpoint_reviews[endpoint["endpoint_id"]]
        need(r.get("original_at") == endpoint["original_at"] and r.get("observation_ids") == endpoint["observation_ids"], "endpoint_review_changed_originals")
        if r.get("selected_target_match") is not True or not text(r.get("reason")):
            return binding, "endpoint_target_correspondence_pending"
    if len(unit["endpoints"]) > 1:
        relation = binding.get("interface_review") or {}
        if (relation.get("same_object") is not True or relation.get("relation_visible") is not True
                or not text(relation.get("description"))):
            return binding, "same_object_interface_not_confirmed"
    review_provenance(binding, [image["image_ref"]], mode)
    return binding, None


def _view(unit, image, mode):
    if not unit.get("view_ref"):
        return None, "current_display_view_missing"
    view = checked(unit["view_ref"])
    _shape(view, "view")
    for key, value in {"unit_id": unit["unit_id"], "image_ref": image["image_ref"], "target_ref": unit["target_ref"],
                       "endpoints": unit["endpoints"], "pixels": image["pixels"],
                       "original_image_review_ref": unit["target_binding_ref"]}.items():
        need(view.get(key) == value, "view_binding_mismatch:" + key)
    rect = view["rectangle"]
    need(set(rect) == {"x", "y", "width", "height"} and all(type(v) in (int, float) for v in rect.values()), "normalized_rectangle_required")
    need(0 <= rect["x"] < 1 and 0 <= rect["y"] < 1 and 0 < rect["width"] <= 1 and 0 < rect["height"] <= 1
         and rect["x"] + rect["width"] <= 1.000000001 and rect["y"] + rect["height"] <= 1.000000001, "rectangle_outside_original")
    need(view.get("coordinate_frame") == "original_pixels_no_rotation" and view.get("transform") in
         {"crop_only_no_retouch", "crop_and_uniform_resize_no_retouch"}, "reversible_original_view_required")
    _pixels(view["actual_view_ref"])
    need(isinstance(view.get("limits"), list), "view_limits_required")
    if view.get("confirmed") is not True or view.get("original_and_view_match") is not True or not text(view.get("reason")):
        return view, "display_region_not_confirmed"
    review_provenance(view, [image["image_ref"], view["actual_view_ref"]], mode)
    return view, None


def prepare(brief_ref, manifest_ref, records, quality_bundles=()):
    """Freeze all candidate dispositions and original facts; never visual PASS."""
    records = list(records)
    dependencies = pins()
    brief, semantic = _brief(brief_ref)
    manifest = checked(manifest_ref)
    _shape(manifest, "candidate_manifest")
    mode = manifest.get("dataset_mode")
    need(mode in {"real", "synthetic_fixture"}, "explicit_dataset_mode_required")
    reject_fixture(brief, mode)
    reject_fixture(semantic, mode)
    reject_fixture(manifest, mode)
    need(manifest.get("brief_digest") == digest(brief), "manifest_brief_changed")
    images = indexed(manifest["images"], "image_id")
    units = indexed(manifest["units"], "unit_id")
    record_map = indexed(list(records), "image_id")
    need(set(record_map) <= set(images), "R5_record_outside_manifest")
    calibration_hashes = {r["ref"]["sha256"] for r in brief["calibration_refs"]}
    image_ledger, processed = {}, {}
    for iid, image in images.items():
        checked(image["image_ref"], False)
        need(image.get("pixels") == _pixels(image["image_ref"]), "original_pixel_dimensions_mismatch")
        refs = image.get("provenance_refs", [])
        need(isinstance(refs, list), "source_provenance_list_required")
        for ref in refs:
            checked(ref, False)
        need(isinstance(image.get("dedup_keys"), list) and all(text(k) for k in image["dedup_keys"]), "source_dedup_keys_required")
        why = []
        if (image.get("source_role") != "candidate" or image["image_ref"]["sha256"] in calibration_hashes
                or any(ref["sha256"] in calibration_hashes for ref in refs)):
            why.append("calibration_or_context_not_candidate")
        if image.get("source_kind") not in {"trend", "public_design_reference"}:
            why.append("source_not_visual_candidate")
        if image.get("source_status") != "established" or not text(image.get("source_group_id")) or not refs:
            why.append("source_provenance_pending")
        image_ledger[iid] = {"image_id": iid, "source_reasons": why, "unit_ids": [u["unit_id"] for u in units.values() if u["image_id"] == iid]}
        if iid in record_map:
            processed[iid] = _record(record_map[iid], image, mode)
    bundles = list(quality_bundles)
    keys = [(b.get("image_id"), b.get("target_digest")) for b in bundles]
    need(len(set(keys)) == len(keys), "duplicate_target_quality_bundle")
    need(all(iid in images for iid, _ in keys), "quality_outside_manifest")
    prepared_units, aliases, observation_aliases = [], {}, {}
    for number, unit in enumerate(units.values(), 1):
        alias = "U" + str(number).zfill(2)
        need(unit.get("image_id") in images, "unit_image_missing")
        image = images[unit["image_id"]]
        target = checked(unit["target_ref"])
        reject_fixture(target, mode)
        need(target.get("target_digest") == digest({k: v for k, v in target.items() if k != "target_digest"}), "target_digest_changed")
        need(target.get("image_id") == image["image_id"] and target.get("image_sha256") == image["image_ref"]["sha256"]
             and target.get("source_kind") == image["source_kind"] and target.get("branch") == "CMF"
             and target.get("scope_kind") == "local_cmf" and target.get("direction_id") == brief["direction_id"], "unit_target_mismatch")
        endpoints = indexed(unit["endpoints"], "endpoint_id")
        need((len(endpoints) == 1 if brief["comparison_unit"] == "surface" else len(endpoints) >= 2), "comparison_endpoint_count_mismatch")
        need(len({e["original_at"] for e in endpoints.values()}) == len(endpoints), "duplicate_original_endpoint")
        reasons = list(image_ledger[image["image_id"]]["source_reasons"])
        record = record_map.get(image["image_id"])
        clean, withheld = processed.get(image["image_id"], ({}, []))
        selected, endpoint_aliases = [], []
        if record is None:
            reasons.append("R5_missing")
        for en, endpoint in enumerate(endpoints.values(), 1):
            ea = alias + ".E" + str(en)
            need(text(endpoint.get("role")) and text(endpoint.get("original_at")), "endpoint_definition_required")
            ids = endpoint.get("observation_ids")
            need(isinstance(ids, list) and ids and len(set(ids)) == len(ids), "explicit_unique_original_observations_required")
            all_facts = {o["observation_id"]: o for o in record["observations"]} if record else {}
            obs_aliases = []
            for on, oid in enumerate(ids, 1):
                if record is None:
                    continue
                need(oid in all_facts, "unknown_original_observation_id:" + str(oid))
                original = all_facts[oid]
                need(original["at"] == endpoint["original_at"], "cross_endpoint_attribute_borrowing")
                if oid not in clean:
                    reasons.append("observation_not_clean_CMF:" + oid)
                    continue
                oa = ea + ".O" + str(on).zfill(2)
                fact = {"alias": oa, "unit_alias": alias, "endpoint_alias": ea, "image_id": image["image_id"],
                        "image_sha256": image["image_ref"]["sha256"], "record_digest": record["digest"],
                        "original_observation": deepcopy(original)}
                observation_aliases[oa] = fact
                selected.append(fact)
                obs_aliases.append(oa)
            endpoint_aliases.append({"alias": ea, "endpoint": deepcopy(endpoint), "observation_aliases": obs_aliases})
        matching = [b for b in bundles if b.get("image_id") == image["image_id"] and b.get("target_digest") == target["target_digest"]]
        if image_ledger[image["image_id"]]["source_reasons"]:
            quality = {"eligible": False, "reason": "source_not_candidate", "native": None,
                       "unconsumed_bundle": deepcopy(matching[0]) if matching else None}
        else:
            quality = consume(matching[0] if matching else None, target_ref=unit["target_ref"], image=image, brief=brief, mode=mode)
        if not quality["eligible"]:
            reasons.append(quality["reason"])
        binding = view = None
        if record and quality["eligible"] and not reasons:
            binding, pending = _binding(unit, image, record, quality, mode)
            if pending:
                reasons.append(pending)
            else:
                view, pending = _view(unit, image, mode)
                if pending:
                    reasons.append(pending)
        row = {"unit_alias": alias, "unit": deepcopy(unit), "image": deepcopy(image), "target": deepcopy(target),
               "endpoints": endpoint_aliases, "facts": selected, "quality": quality,
               "binding": binding, "view": view, "withheld_original_facts": withheld,
               "original_uncertainty": {"original_audit": deepcopy(record["original_audit"]),
                                        "unresolved_feature_bindings": deepcopy(record["unresolved_feature_bindings"])} if record else None,
               "status": "eligible" if not reasons else "pending", "reasons": list(dict.fromkeys(reasons))}
        prepared_units.append(row)
        aliases[alias] = {"unit_id": unit["unit_id"], "image_id": image["image_id"], "image_sha256": image["image_ref"]["sha256"],
                          "target_ref": unit["target_ref"], "endpoints": deepcopy(unit["endpoints"])}
    return seal({"schema_version": PREFIX + "prepared.v4", "version": VERSION, "dataset_mode": mode,
                 "brief": brief, **semantic, "units": prepared_units, "unit_aliases": aliases,
                 "observation_aliases": observation_aliases, "image_ledger": list(image_ledger.values()),
                 "negative_aliases": {"N" + str(i + 1).zfill(2): deepcopy(n) for i, n in enumerate(brief["negative_audit"])},
                 "inputs": {"brief_ref": deepcopy(brief_ref), "manifest_ref": deepcopy(manifest_ref),
                            "records": deepcopy(list(records)), "quality_bundles": deepcopy(bundles)},
                 "dependencies": dependencies, "visual_pass": False, "new_model_calls": 0})


def current(prepared):
    verify(prepared)
    _shape(prepared, "prepared")
    need(prepare(**prepared["inputs"]) == prepared, "prepared_inputs_changed")


def grouping_view(prepared):
    current(prepared)
    return {"schema_version": PREFIX + "grouping_input.v4", "prepared_digest": prepared["digest"],
            "brief": deepcopy(prepared["brief"]), "direction_snapshot": deepcopy(prepared["direction_snapshot"]),
            "negative_aliases": deepcopy(prepared["negative_aliases"]),
            "eligible_units": [{"unit_alias": u["unit_alias"], "image_ref": u["image"]["image_ref"],
                                "source_kind": u["image"]["source_kind"], "source_group_id": u["image"]["source_group_id"],
                                "selected_target": u["target"],
                                "endpoints": [{"alias": e["alias"], "role": e["endpoint"]["role"],
                                               "original_at": e["endpoint"]["original_at"], "observation_aliases": e["observation_aliases"]}
                                              for e in u["endpoints"]],
                                "known_facts": [{"alias": f["alias"], "endpoint_alias": f["endpoint_alias"],
                                                 **{k: f["original_observation"][k] for k in ("parameter_id", "value", "at", "source", "path")}}
                                                for f in u["facts"]],
                                "original_uncertainty": deepcopy(u["original_uncertainty"]),
                                "withheld_original_facts": deepcopy(u["withheld_original_facts"]),
                                "validated_quality_target": u["quality"]["validated_target"], "view": u["view"]}
                               for u in prepared["units"] if u["status"] == "eligible"],
            "rules": ["Different PIDs can support one visible relation; no value equality implies similarity.",
                      "Use exact aliases. Keep visual inference separate from original facts; original uncertainty must not be silently converted into support.",
                      "Inspect actual originals and current views. Quality is not group coherence.",
                      "Account for every eligible unit and every original negative. No category quota."]}


def grouping_template(prepared):
    """Unknown/false values deliberately cannot qualify a member."""
    current(prepared)
    brief = prepared["brief"]
    return {"schema_version": PREFIX + "grouping_proposal.v4", "prepared_digest": prepared["digest"],
            "members": [{"unit_alias": u["unit_alias"], "selection_reason": "", "original_image_seen": False, "actual_view_seen": False,
                         "conditions": [{"condition_id": c["id"], "verdict": "unknown", "observation_aliases": [],
                                         "visual_inference": "", "limits": []}
                                        for c in brief["primary_signature"]["conditions"] + brief["secondary_dimensions"]],
                         "variations": [{"id": x["id"], "verdict": "unknown", "reason": ""} for x in brief["allowed_variation"]],
                         "confounders": [{"id": x["id"], "verdict": "unresolved", "reason": ""} for x in brief["confounders"]]}
                        for u in prepared["units"] if u["status"] == "eligible"],
            "excluded_eligible": [],
            "negative_dispositions": [{"negative_alias": a, "status": "current_uncertain", "reason": "",
                                       "affected_unit_aliases": [], "scope_basis": "", "deferred_obligation_indices": []}
                                      for a in prepared["negative_aliases"]],
            "review_provenance": None}


def _source_keys(unit):
    image = unit["image"]
    return {"image:" + image["image_ref"]["sha256"], "source:" + image["source_group_id"]} | set(image["dedup_keys"])


def _assess_member(row, unit, brief):
    need(text(row.get("selection_reason")), "member_reason_required")
    blocked = []
    if row.get("original_image_seen") is not True or row.get("actual_view_seen") is not True:
        blocked.append("member_images_not_seen:" + row["unit_alias"])
    checks = indexed(row["conditions"], "condition_id")
    expected = {c["id"]: True for c in brief["primary_signature"]["conditions"]}
    expected.update({c["id"]: c["required"] for c in brief["secondary_dimensions"]})
    need(set(checks) == set(expected), "all_condition_assessments_required")
    valid = {f["alias"]: f for f in unit["facts"]}
    resolved = {}
    for cid, required in expected.items():
        c = checks[cid]
        need(c.get("verdict") in {"supported", "contradicted", "unknown"} and text(c.get("visual_inference"))
             and isinstance(c.get("limits"), list), "condition_inference_and_limits_required")
        refs = c.get("observation_aliases")
        need(isinstance(refs, list) and len(refs) == len(set(refs)) and set(refs) <= set(valid), "unknown_or_cross_unit_observation_alias")
        if c["verdict"] == "supported":
            need(refs, "supported_condition_needs_known_facts_and_visual_inference")
        if required and c["verdict"] != "supported":
            blocked.append("necessary_condition_not_supported:" + row["unit_alias"] + ":" + cid)
        resolved[cid] = [deepcopy(valid[a]) for a in refs]
    primary_ids = {c["id"] for c in brief["primary_signature"]["conditions"]}
    supported_endpoints = {f["endpoint_alias"] for cid in primary_ids if checks[cid]["verdict"] == "supported" for f in resolved[cid]}
    if supported_endpoints != {e["alias"] for e in unit["endpoints"]}:
        blocked.append("primary_endpoint_evidence_incomplete:" + row["unit_alias"])
    for field, choices, passed in (("variations", {"within", "outside", "unknown"}, "within"),
                                    ("confounders", {"controlled", "conflict", "unresolved"}, "controlled")):
        rows = indexed(row[field], "id")
        definitions = brief["allowed_variation" if field == "variations" else "confounders"]
        need(set(rows) == {c["id"] for c in definitions}, "complete_" + field + "_required")
        for key, check in rows.items():
            need(check.get("verdict") in choices and text(check.get("reason")), "invalid_" + field + "_assessment")
            if check["verdict"] != passed:
                blocked.append(field + "_not_resolved:" + row["unit_alias"] + ":" + key)
    return resolved, blocked


def accept_grouping(prepared, proposal_ref):
    current(prepared)
    proposal = checked(proposal_ref)
    _shape(proposal, "grouping_proposal")
    reject_fixture(proposal, prepared["dataset_mode"])
    need(proposal.get("prepared_digest") == prepared["digest"], "proposal_prepared_mismatch")
    eligible = {u["unit_alias"]: u for u in prepared["units"] if u["status"] == "eligible"}
    members = indexed(proposal["members"], "unit_alias")
    excluded = indexed(proposal["excluded_eligible"], "unit_alias")
    need(not set(members) & set(excluded) and set(members) | set(excluded) == set(eligible), "eligible_partition_incomplete_or_unknown_alias")
    need(all(text(r.get("reason")) for r in excluded.values()), "exclusion_reason_required")
    if eligible:
        refs = [ref for u in eligible.values() for ref in (u["image"]["image_ref"], u["view"]["actual_view_ref"])]
        review_provenance(proposal, refs, prepared["dataset_mode"])
    count = prepared["brief"]["count_policy"]
    blockers = []
    if not count["minimum"] <= len(members) <= count["maximum"]:
        blockers.append("independent_source_count_outside_policy")
    seen, resolved_members = set(), []
    for alias, member in members.items():
        unit = eligible[alias]
        keys = _source_keys(unit)
        if keys & seen:
            blockers.append("same_source_max1:" + alias)
        seen |= keys
        support, blocked = _assess_member(member, unit, prepared["brief"])
        blockers += blocked
        resolved_members.append({"unit_alias": alias, "exact_unit": deepcopy(unit), "assessment": deepcopy(member),
                                 "condition_evidence": support})
    negatives = indexed(proposal["negative_dispositions"], "negative_alias")
    need(set(negatives) == set(prepared["negative_aliases"]), "full_negative_audit_required")
    for alias, row in negatives.items():
        need(row.get("status") in {"current_compatible", "current_conflict", "current_uncertain", "future_product_obligation", "not_applicable_to_reference"}
             and text(row.get("reason")) and text(row.get("scope_basis")), "negative_scope_reason_required")
        need(isinstance(row.get("affected_unit_aliases"), list) and set(row["affected_unit_aliases"]) <= set(members), "negative_member_scope_mismatch")
        if row["status"] in {"current_conflict", "current_uncertain"}:
            blockers.append("unresolved_current_negative:" + alias)
        if row["status"] == "future_product_obligation":
            refs = row.get("deferred_obligation_indices")
            need(isinstance(refs, list) and refs and all(type(i) is int and 0 <= i < len(prepared["brief"]["deferred_obligations"]) for i in refs),
                 "future_negative_must_retain_original_obligation")
    ledger = [{"unit_alias": u["unit_alias"], "unit_id": u["unit"]["unit_id"],
               "disposition": "member" if u["unit_alias"] in members else "visual_excluded" if u["unit_alias"] in excluded else "preparation_pending",
               "reason": excluded[u["unit_alias"]]["reason"] if u["unit_alias"] in excluded else list(u["reasons"])} for u in prepared["units"]]
    return seal({"schema_version": PREFIX + "grouping.v4", "version": VERSION, "prepared_snapshot": deepcopy(prepared),
                 "proposal_ref": deepcopy(proposal_ref), "members": resolved_members, "dispositions": ledger,
                 "negative_dispositions": deepcopy(proposal["negative_dispositions"]),
                 "negative_audit": deepcopy(prepared["brief"]["negative_audit"]),
                 "deferred_obligations": deepcopy(prepared["brief"]["deferred_obligations"]),
                 "count": {"actual": len(members), "target": count["target"], "below_target": len(members) < count["target"]},
                 "blockers": list(dict.fromkeys(blockers)), "status": "blocked" if blockers else "candidate_for_board_review",
                 "visual_pass": False, "expansion_allowed": False})


def _current_grouping(grouping):
    verify(grouping)
    _shape(grouping, "grouping")
    need(accept_grouping(grouping["prepared_snapshot"], grouping["proposal_ref"]) == grouping, "grouping_inputs_changed")


def prepare_board_review(grouping, rendered_board_ref):
    _current_grouping(grouping)
    need(grouping["status"] == "candidate_for_board_review", "grouping_blocked")
    pixels = _pixels(rendered_board_ref)
    return seal({"schema_version": PREFIX + "board_review_request.v4", "grouping_digest": grouping["digest"],
                 "rendered_board_ref": deepcopy(rendered_board_ref), "rendered_board_pixels": pixels,
                 "brief": deepcopy(grouping["prepared_snapshot"]["brief"]),
                 "tiles": [{"tile_index": i + 1, "unit_alias": m["unit_alias"],
                            "image_ref": m["exact_unit"]["image"]["image_ref"], "view_ref": m["exact_unit"]["unit"]["view_ref"],
                            "actual_view_ref": m["exact_unit"]["view"]["actual_view_ref"],
                            "target_ref": m["exact_unit"]["unit"]["target_ref"], "endpoints": m["exact_unit"]["endpoints"]}
                           for i, m in enumerate(grouping["members"])],
                 "negative_aliases": deepcopy(grouping["prepared_snapshot"]["negative_aliases"]),
                 "negative_dispositions": deepcopy(grouping["negative_dispositions"]),
                 "required_global_checks": ["shared_specific_signature", "differences_within_brief", "comparable_apparent_scale",
                                            "targets_and_views_readable", "not_caption_or_PID_only", "calibration_separation"],
                 "visual_pass": False})


def board_review_template(grouping, request):
    need(prepare_board_review(grouping, request["rendered_board_ref"]) == request, "stale_board_review_request")
    brief = request["brief"]
    required = [c["id"] for c in brief["primary_signature"]["conditions"]] + [c["id"] for c in brief["secondary_dimensions"] if c["required"]]
    return {"schema_version": PREFIX + "board_review.v4", "request_digest": request["digest"],
            "rendered_board_ref": deepcopy(request["rendered_board_ref"]), "board_seen": False, "verdict": "unresolved", "reason": "",
            "members": [{**deepcopy(t), "original_image_seen": False, "actual_view_seen": False, "target_and_endpoints_correct": False,
                         "tile_matches_current_view": False, "apparent_scale_comparable": False,
                         "conditions": [{"condition_id": cid, "verdict": "unknown", "reason": ""} for cid in required],
                         "variations": [{"id": c["id"], "verdict": "unknown", "reason": ""} for c in brief["allowed_variation"]],
                         "confounders": [{"id": c["id"], "verdict": "unresolved", "reason": ""} for c in brief["confounders"]],
                         "reason": ""} for t in request["tiles"]],
            "global_checks": [{"id": k, "verdict": "unresolved", "reason": ""} for k in request["required_global_checks"]],
            "negative_review": [{"negative_alias": a, "verdict": "unresolved", "reason": ""} for a in request["negative_aliases"]],
            "acknowledged_scope_limits": deepcopy(brief["scope_limits"]),
            "acknowledged_deferred_obligations": deepcopy(brief["deferred_obligations"]), "review_provenance": None}


def accept_board_review(grouping, request, review_ref):
    need(prepare_board_review(grouping, request["rendered_board_ref"]) == request, "stale_board_review_request")
    review = checked(review_ref)
    _shape(review, "board_review")
    mode = grouping["prepared_snapshot"]["dataset_mode"]
    reject_fixture(review, mode)
    need(review.get("request_digest") == request["digest"] and review.get("rendered_board_ref") == request["rendered_board_ref"], "review_not_current_board")
    need(review.get("verdict") in {"coherent", "incoherent", "unresolved"} and text(review.get("reason")), "board_verdict_and_reason_required")
    required_refs = [request["rendered_board_ref"]] + [ref for t in request["tiles"] for ref in (t["image_ref"], t["actual_view_ref"])]
    review_provenance(review, required_refs, mode)
    blockers = []
    if review.get("board_seen") is not True or review["verdict"] != "coherent":
        blockers.append("whole_board_not_visually_accepted")
    rows = indexed(review["members"], "unit_alias")
    need(set(rows) == {t["unit_alias"] for t in request["tiles"]}, "all_current_tiles_required")
    template = board_review_template(grouping, request)
    for expected in template["members"]:
        row = rows[expected["unit_alias"]]
        tile = next(t for t in request["tiles"] if t["unit_alias"] == row["unit_alias"])
        need(all(row.get(k) == v for k, v in tile.items()), "review_tile_binding_mismatch")
        need(text(row.get("reason")), "member_visual_reason_required")
        for key in ("original_image_seen", "actual_view_seen", "target_and_endpoints_correct", "tile_matches_current_view", "apparent_scale_comparable"):
            if row.get(key) is not True:
                blockers.append(key + ":" + row["unit_alias"])
        for field, key, passing, choices in (("conditions", "condition_id", "supported", {"supported", "contradicted", "unknown"}),
                                            ("variations", "id", "within", {"within", "outside", "unknown"}),
                                            ("confounders", "id", "controlled", {"controlled", "conflict", "unresolved"})):
            actual = indexed(row[field], key)
            need(set(actual) == {r[key] for r in expected[field]}, "member_visual_checks_incomplete:" + field)
            for cid, check in actual.items():
                need(check.get("verdict") in choices and text(check.get("reason")), "visual_check_reason_required")
                if check["verdict"] != passing:
                    blockers.append(field + ":" + row["unit_alias"] + ":" + cid)
    for field, key, expected, passing, choices in (
            ("global_checks", "id", set(request["required_global_checks"]), "supported", {"supported", "conflict", "unresolved"}),
            ("negative_review", "negative_alias", set(request["negative_aliases"]), "scope_and_disposition_supported", {"scope_and_disposition_supported", "conflict", "unresolved"})):
        actual = indexed(review[field], key)
        need(set(actual) == expected, "board_audit_incomplete:" + field)
        for cid, row in actual.items():
            need(row.get("verdict") in choices and text(row.get("reason")), "board_audit_reason_required")
            if row["verdict"] != passing:
                blockers.append(field + ":" + cid)
    for name, original in (("acknowledged_scope_limits", request["brief"]["scope_limits"]),
                           ("acknowledged_deferred_obligations", grouping["deferred_obligations"])):
        need(review.get(name) == original, "board_audit_erased:" + name)
    return seal({"schema_version": PREFIX + "board_acceptance.v4", "version": VERSION, "dataset_mode": mode,
                 "grouping_snapshot": deepcopy(grouping), "request": deepcopy(request), "review_ref": deepcopy(review_ref),
                 "blockers": blockers, "status": "blocked" if blockers else "ready_for_user_feedback",
                 "visual_review_accepted": not blockers, "physical_properties_verified": False,
                 "user_approved": False, "expansion_allowed": False,
                 "negative_audit": deepcopy(grouping["negative_audit"]), "deferred_obligations": deepcopy(grouping["deferred_obligations"])})


def check_expansion_gate(acceptance, user_decision_ref=None):
    verify(acceptance)
    need(accept_board_review(acceptance["grouping_snapshot"], acceptance["request"], acceptance["review_ref"]) == acceptance, "stale_board_acceptance")
    result = {"schema_version": PREFIX + "expansion_gate.v4", "acceptance_digest": acceptance["digest"],
              "expansion_allowed": False, "reason": "explicit_current_human_approval_required"}
    if acceptance["status"] != "ready_for_user_feedback":
        return {**result, "reason": "current_board_not_ready"}
    if acceptance["dataset_mode"] != "real":
        return {**result, "reason": "synthetic_cannot_authorize_expansion"}
    if user_decision_ref is None:
        return result
    decision = checked(user_decision_ref)
    _shape(decision, "user_decision")
    reject_fixture(decision, "real")
    need(decision.get("acceptance_digest") == acceptance["digest"] and decision.get("rendered_board_ref") == acceptance["request"]["rendered_board_ref"], "user_decision_not_current_board")
    if decision.get("actor_kind") != "human" or decision.get("decision") != "approve_expansion":
        return result
    message = pick(decision["original_user_message"])
    need(message.get("role") == "user" and message.get("origin_kind") == "human" and message.get("delegated") is False
         and text(message.get("message_id")) and text(message.get("thread_id"))
         and text(decision.get("exact_quote")) and decision["exact_quote"] in message.get("content", ""), "original_human_approval_evidence_required")
    return {**result, "expansion_allowed": True, "reason": "explicit_current_human_approval",
            "user_decision_ref": deepcopy(user_decision_ref), "approval_evidence": deepcopy(decision["original_user_message"])}
