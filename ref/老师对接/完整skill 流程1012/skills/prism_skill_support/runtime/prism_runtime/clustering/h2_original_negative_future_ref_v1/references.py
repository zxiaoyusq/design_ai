"""Lossless links to original negatives, never new negatives or judgments."""
from copy import deepcopy

from ..id_reference_board_v5.common import checked, digest, indexed, need, text, verify

VERSION = "h2-original-negative-future-ref-v1.0.0"
SCHEMA = "prism.h2.original_negative_future_references.v1"


def _sources(prepared, proposal_ref):
    verify(prepared)
    branches = {"prism.cmf.prepared.v4": "CMF", "prism.id.prepared.v5": "ID"}
    need(prepared.get("schema_version") in branches, "registered_prepared_schema_required")
    proposal = checked(proposal_ref)
    need(proposal.get("prepared_digest") == prepared["digest"], "proposal_prepared_mismatch")
    expected_aliases = {"N" + str(i + 1).zfill(2): n for i, n in enumerate(prepared["brief"]["negative_audit"])}
    need(prepared["negative_aliases"] == expected_aliases, "original_negative_aliases_not_complete")
    rows = indexed(proposal["negative_dispositions"], "negative_alias")
    need(set(rows) == set(expected_aliases), "full_negative_dispositions_required")
    return branches[prepared["schema_version"]], proposal, rows


def derive_future_references(prepared, proposal_ref):
    """Pure construction from existing future rows with explicit empty indices.

    The original proposal is never edited. Rows using existing indices and all
    current conflict/uncertainty dispositions are left on their original path.
    """
    branch, proposal, rows = _sources(prepared, proposal_ref)
    references = []
    for alias, row in rows.items():
        if row.get("status") != "future_product_obligation" or row.get("deferred_obligation_indices") != []:
            continue
        original = prepared["negative_aliases"][alias]
        need(text(original.get("negative_id")) and text(row.get("reason")) and text(row.get("scope_basis")), "complete_future_negative_identity_reason_scope_required")
        references.append({
            "negative_alias": alias, "negative_id": original["negative_id"],
            "original_negative_digest": digest(original), "original_negative": deepcopy(original),
            "original_disposition_digest": digest(row), "original_disposition": deepcopy(row),
            "follow_up_kind": "future_target_product_check_of_original_negative",
            "status": "unresolved", "resolved": False,
            "reason": row["reason"], "scope_basis": row["scope_basis"],
            "adds_research_evidence": False, "adds_visual_constraint": False,
        })
    return {"schema_version": SCHEMA, "adapter_version": VERSION, "branch": branch,
            "prepared_digest": prepared["digest"], "proposal_ref": deepcopy(proposal_ref), "proposal_digest": digest(proposal),
            "negative_audit_digest": digest(prepared["brief"]["negative_audit"]),
            "deferred_obligations_digest": digest(prepared["brief"]["deferred_obligations"]),
            "references": references}


def validate_future_references(prepared, proposal_ref, reference_ref):
    actual = checked(reference_ref)
    expected = derive_future_references(prepared, proposal_ref)
    need(actual.get("schema_version") == SCHEMA, "original_negative_future_reference_schema_required")
    rows = indexed(actual.get("references"), "negative_alias")
    need(all(r.get("status") == "unresolved" and r.get("resolved") is False for r in rows.values()), "future_reference_must_remain_unresolved")
    # Exact typed canonical equality checks every field, including nested people,
    # original wording, unknown scope/entity, source evidence, and H01 impact.
    need(digest(actual) == digest(expected), "supplemental_original_negative_reference_mismatch")
    return deepcopy(actual)


def future_gate(prepared, proposal_ref, row, reference_ref):
    document = validate_future_references(prepared, proposal_ref, reference_ref)
    need(row.get("status") == "future_product_obligation", "direct_reference_only_for_existing_future_row")
    refs = row.get("deferred_obligation_indices")
    if isinstance(refs, list) and refs and all(type(i) is int and 0 <= i < len(prepared["brief"]["deferred_obligations"]) for i in refs):
        return  # The frozen original index condition, unchanged.
    need(refs == [], "future_negative_must_retain_original_obligation")
    matching = [r for r in document["references"] if r["negative_alias"] == row["negative_alias"]]
    need(len(matching) == 1 and matching[0]["original_disposition"] == row, "exact_original_negative_future_reference_required")
