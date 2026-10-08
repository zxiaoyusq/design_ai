"""Bind the existing semantic-first selection; never choose directions or images."""
from copy import deepcopy

from .common import digest, indexed, need, seal, verify

FLOW_SCHEMA = "prism.semantic-first-dual-h02.v2"


def prepare_scope(prepared, candidates, selection, *, negative_audit=None):
    for document, stage in ((prepared, "H01_semantic"), (candidates, "H01_candidates"), (selection, "designer_selection")):
        verify(document)
        need(document.get("schema_version") == FLOW_SCHEMA and document.get("stage") == stage, "Wrong semantic-first artifact stage")
    need(candidates["prepared_digest"] == selection["prepared_digest"] == prepared["digest"]
         and selection["candidate_digest"] == candidates["digest"], "Selection snapshot changed")
    confirm = selection["confirmation"]
    need(confirm.get("status") == "confirmed" and confirm.get("actor_id") and confirm.get("source_ref")
         and confirm.get("selection_digest") == digest(selection["selection"])
         and confirm.get("candidate_digest") == candidates["digest"], "Selection is not explicitly bound")
    mode = prepared["dataset_mode"]
    _actor(confirm, mode)
    need(negative_audit is not None or mode == "synthetic_fixture", "Bind the explicit upstream negative audit; pass [] only when the source audit is empty")
    negatives = deepcopy(negative_audit or [])
    indexed(negatives, "negative_id")
    all_refs = {r["evidence_id"] for rows in prepared.get("lanes", {}).values() for r in rows}
    for negative in negatives:
        need(negative.get("statement") and negative.get("evidence_refs")
             and set(negative["evidence_refs"]) <= all_refs, "Negative audit needs original semantic evidence references")
    assets = indexed(prepared["asset_catalog"], "image_id")
    available = indexed(candidates["directions"], "direction_id")
    choices = indexed(selection["selection"], "direction_id")
    need(choices and set(choices) <= set(available), "Only explicitly selected directions are permitted")
    directions = []
    for did, choice in choices.items():
        branches = choice["branches"]
        need(branches and len(branches) == len(set(branches)) and set(branches) <= {"ID", "CMF"}, "Select valid distinct branches")
        direction = available[did]
        ids = direction["candidate_image_ids"]
        need(len(ids) == len(set(ids)) and set(ids) <= set(assets), "Unknown/duplicate selected-direction images")
        need(direction.get("trend_evidence_refs") and direction.get("research_evidence_refs"), "Two-lane semantic references required")
        directions.append({**deepcopy(direction), "branches": deepcopy(branches)})
    return seal({"schema_version": "prism.r5.cluster_scope.v2", "dataset_mode": mode,
        "selection_digest": selection["digest"], "prepared_digest": prepared["digest"],
        "candidate_digest": candidates["digest"], "confirmation": deepcopy(confirm),
        "directions": directions, "asset_catalog": deepcopy(prepared["asset_catalog"]),
        "negative_audit": negatives,
        "identity_authentication": "trusted_Root_caller_responsibility", "selection_created_here": False})


def _actor(confirmation, mode):
    actor = confirmation.get("actor_kind")
    need(actor in {"human_designer", "user_delegated_ai", "synthetic_fixture"}, "Unknown confirmation actor")
    if actor == "synthetic_fixture":
        need(mode == "synthetic_fixture", "A test confirmation cannot authorize real inputs")
    if actor == "user_delegated_ai":
        need(confirmation.get("current_scope_delegation_ref"), "Current-scope delegation is required")


def verify_confirmation(request, scope, confirmation):
    verify(scope)
    need(confirmation.get("status") == "confirmed" and confirmation.get("actor_id") and confirmation.get("source_ref"),
         "An attributable H02 branch confirmation is required")
    _actor(confirmation, scope["dataset_mode"])
    need(confirmation.get("request_digest") == digest(request)
         and confirmation.get("selection_digest") == scope["selection_digest"], "H02 confirmation is stale or for another request")
