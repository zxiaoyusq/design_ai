"""Read purpose-specific decisions and confirmed textual bindings, never score quality."""
from copy import deepcopy

from .common import digest, need


def admission(record, branch, bindings):
    asset, raw = record["asset"], record.get("quality")
    result = {"branch": branch, "status": "pending", "reason": "quality_result_missing",
              "allowed_locations": [], "main_allowed": False, "support_allowed": False,
              "original_result": deepcopy(raw), "limitations": [], "bindings": [],
              "physical_region_identity_verified": False, "bounding_box": None}
    if asset["source_kind"] != "trend":
        if asset["source_kind"] == "unknown":
            result["reason"] = "source_role_unknown"
            return result
        result.update(status="not_applicable", reason="non_trend_source_not_quality_eliminated",
                      allowed_locations=record["locations"], support_allowed=True)
        return result
    if raw is None:
        return result
    need(raw.get("schema_version") == "prism.quality_selected.decision.v2", "Unsupported quality decision schema")
    need(raw.get("image_id") == record["image_id"] and raw.get("image_sha256") == record["image_sha256"]
         and raw.get("source_kind") == asset["source_kind"], "Quality result belongs to a different source image")
    need(raw.get("global_decision") is None, "A global quality decision cannot replace purpose decisions")
    use = raw["uses"]["id_reference" if branch == "ID" else "cmf_reference"]
    result.update(original_use=deepcopy(use), limitations=deepcopy(use.get("limits", [])))
    if use.get("status") != "complete":
        result.update(reason="quality_" + str(use.get("status", "missing_status")))
        return result
    need(use.get("decision") in {"PASS", "FAIL"}, "A complete quality use must have PASS/FAIL")
    if use["decision"] == "FAIL":
        result.update(status="FAIL", reason="purpose_specific_quality_fail")
        return result
    accepted = set()
    for binding in bindings:
        if binding["image_id"] != record["image_id"]:
            continue
        need(binding["quality_digest"] == digest(raw), "Quality scope uses a stale result")
        evidence = use.get("evidence", [])
        idx = binding["evidence_index"]
        need(type(idx) is int and 0 <= idx < len(evidence), "Quality evidence index is invalid for this purpose")
        need(binding["acknowledged_limits"] == use.get("limits", []), "Quality limitations were dropped or changed")
        need(binding["locations"] and set(binding["locations"]) <= set(record["locations"]), "Quality binding invents an R5 location")
        accepted.update(binding["locations"])
        result["bindings"].append({**deepcopy(binding), "original_quality_evidence": deepcopy(evidence[idx]),
                                   "binding_basis": "explicit_H02_branch_confirmation_not_geometric_verification"})
    result.update(status="PASS", reason="purpose_pass_with_scope_binding" if accepted else "quality_scope_pending",
                  allowed_locations=sorted(accepted), main_allowed=bool(accepted), support_allowed=bool(accepted))
    return result
