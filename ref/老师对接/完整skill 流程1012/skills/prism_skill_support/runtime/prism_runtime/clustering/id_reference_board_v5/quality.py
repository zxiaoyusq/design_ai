"""Replay native selected-target v2 ID/overall_id; no legacy or CMF conversion."""
from copy import deepcopy

from .common import checked, digest, need, pins, reject_fixture


def _check_execution(ref, mode):
    if not ref:
        return
    execution = checked(ref)
    reject_fixture(execution, mode)
    for key in ("request_ref", "raw_output_ref", "receipt_ref", "grant_ref"):
        if execution.get(key):
            reject_fixture(checked(execution[key]), mode)


def consume(bundle, *, target_ref, image, brief, mode):
    if bundle is None:
        return {"eligible": False, "reason": "selected_target_quality_missing", "native": None}
    need(bundle.get("schema_version") == "prism.selected_target_quality.bundle.v2", "native_quality_bundle_v2_required")
    deps = pins()
    need(bundle.get("producer_ref") == deps["quality_protocol"] and
         bundle.get("producer_version") == "selected-target-quality-v2.0.0", "unregistered_quality_producer")
    reject_fixture(bundle, mode)
    need(bundle.get("image_id") == image["image_id"] and bundle.get("branch") == "ID"
         and bundle.get("source_kind") == image["source_kind"], "quality_bundle_image_source_branch_mismatch")
    from prism_sidecars.quality_selected_target_v2 import protocol as native
    prepared = checked(bundle["prepared_ref"])
    reject_fixture(prepared, mode)
    target = checked(target_ref)
    need(bundle.get("target_ref") == target_ref and target == prepared.get("target"), "quality_target_mismatch")
    need(target.get("branch") == "ID" and target.get("scope_kind") == "overall_id", "native_overall_ID_target_required")
    need(bundle.get("target_digest") == target.get("target_digest"), "quality_target_digest_mismatch")
    need(prepared.get("image_id") == image["image_id"] and prepared.get("image_ref") == image["image_ref"]
         and prepared.get("source_kind") == image["source_kind"] and prepared.get("source_group_id") == image["source_group_id"]
         and prepared.get("branch") == "ID", "quality_image_source_branch_mismatch")
    need(prepared.get("source_provenance_refs") == image["provenance_refs"], "quality_source_provenance_mismatch")
    for ref in prepared.get("source_provenance_refs", []):
        if ref["path"].lower().endswith(".json"):
            reject_fixture(checked(ref), mode)
    need(prepared["input_refs"]["H01_ref"] == brief["h01_ref"], "quality_H01_mismatch")
    need(prepared.get("direction_id") == brief["direction_id"], "quality_direction_mismatch")
    for name in ("negative_audit", "deferred_obligations"):
        need(prepared.get(name) == brief[name], "quality_audit_mismatch:" + name)
    # Check real-mode markers in referenced preparation/selection/receipt files,
    # not only in a caller's outer bundle. Native current() checks their hashes.
    for ref in [v for v in prepared.get("input_refs", {}).values()
                if isinstance(v, dict) and set(v) == {"path", "sha256"}]:
        reject_fixture(checked(ref), mode)
    previous = None
    if bundle.get("previous_result_ref") is not None:
        original_previous = checked(bundle["previous_result_ref"])
        reject_fixture(original_previous, mode)
        _check_execution(original_previous.get("execution_ref"), mode)
        if original_previous.get("target_review_ref"):
            reject_fixture(checked(original_previous["target_review_ref"]), mode)
        need(original_previous.get("stage") == "primary", "only_primary_can_precede_confirmation")
        previous = native.accept(prepared, original_previous.get("execution_ref"),
                                 target_review_ref=original_previous.get("target_review_ref"))
        need(previous == original_previous, "previous_quality_not_replayable")
    execution_ref = bundle.get("execution_ref")
    _check_execution(execution_ref, mode)
    if bundle.get("target_review_ref"):
        reject_fixture(checked(bundle["target_review_ref"]), mode)
    result = native.accept(prepared, execution_ref, target_review_ref=bundle.get("target_review_ref"), previous=previous)
    need(result == checked(bundle["result_ref"]), "native_quality_result_not_replayable")
    need(result.get("selected_target") == target, "quality_selected_target_changed")
    validated = result.get("validated_target")
    eligible = (result.get("status") == "complete" and result.get("decision") == "PASS"
                and result.get("admissible") is True and isinstance(validated, dict)
                and validated.get("target_scope_verified") is True)
    if validated:
        need(validated.get("image_ref") == image["image_ref"] and validated.get("target_digest") == target["target_digest"]
             and validated.get("branch") == "ID" and validated.get("scope_kind") == "overall_id"
             and validated.get("source_group_id") == image["source_group_id"],
             "validated_target_mismatch")
    return {"eligible": eligible, "reason": "selected_target_quality_pass" if eligible else "quality_" + result["status"],
            "quality_result_digest": digest(result), "native": deepcopy(result), "validated_target": deepcopy(validated),
            "bundle": deepcopy(bundle)}
