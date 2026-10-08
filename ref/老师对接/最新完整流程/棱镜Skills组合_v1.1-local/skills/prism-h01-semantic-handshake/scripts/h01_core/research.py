"""Lossless text/provenance projection of the current research semantic result."""
from copy import deepcopy
from pathlib import Path

from .common import need, read, identity, index, research_compiler

CLUSTER_KINDS = {"shared_theme", "exploratory_signal", "design_issue", "background_theme"}


def load_research(dataset_path, run_path):
    dataset, run = Path(dataset_path).resolve(), Path(run_path).resolve()
    paths = [run / name for name in ("clusters.json", "handshake-input.json", "analyst-proposal.json", "handoff.json")]
    refs = [identity(p) for p in paths]
    result, summary, proposal, handoff = (read(p) for p in paths)
    need(result.get("schema_version") == "prism.research_semantic_clustering.v1"
        and summary.get("schema_version") == "prism.research_cluster_handoff.v1", "Current research clustering/handoff required")
    # Imported datasets are data; never execute a supplied _methods directory.
    compiler, code_refs = research_compiler()
    replay = compiler["validate_and_compile"](dataset, proposal)
    expected = {k: v for k, v in replay.items() if k != "membership_rows"}
    need(result == expected, "Research clusters no longer match original units and analyst proposal")
    need(summary["input_binding"] == result["input_binding"] == handoff["input_binding"], "Research source bindings differ")
    for name, sha in result["input_binding"]["files"].items():
        ref = identity(dataset / name)
        need(ref["sha256"] == sha, "Research source changed: " + name)
        refs.append(ref)
    summary_clusters = index(summary["clusters"], "cluster_id")
    clusters = index(result["clusters"], "cluster_id")
    need(set(summary_clusters) == set(clusters), "Summary cannot omit or introduce a semantic cluster")
    coverage = index(result["coverage"], "unit_id")
    negative_ids = sorted(u for u, row in coverage.items() if row["source_attitude"] == "dislike")
    need(set(negative_ids) == set(handoff["negative_unit_ids"]), "Complete original negative ledger required")
    units, memberships = {}, []
    for uid, row in coverage.items():
        units[uid] = {"unit_id": uid, "person_id": row["person_id"], "text": row["whole_source_unit"],
            "source_kind": row["source_kind"], "source_attitude": row["source_attitude"],
            "source_entity": row["source_entity"], "source_page": row["source_page"],
            "source_slide_id": row["source_slide_id"], "source_unit_digest": row["source_unit_digest"],
            "evidence_quotes": deepcopy(row["evidence_quotes"]),
            "coverage_disposition": row["disposition"], "coverage_reason": row["reason"],
            "residual_note": row.get("residual_note"), "cluster_ids": deepcopy(row["cluster_ids"]),
            "source_scope": None, "source_channel": None, "source_id": None,
            "image_associations": deepcopy(row["image_links"])}
    normalized = []
    for cid, cluster in clusters.items():
        head = summary_clusters[cid]
        need(cluster["kind"] in CLUSTER_KINDS and head["kind"] == cluster["kind"], "Research cluster kind changed")
        need(head["title"] == cluster["title"] and head["definition"] == cluster["definition"]
             and head["boundaries"] == cluster["boundaries"], "Summary label or boundary differs from full research")
        need(set(head["member_units"]) == {m["unit_id"] for m in cluster["members"]}, "Summary membership changed")
        members = []
        for member in cluster["members"]:
            unit = units[member["unit_id"]]
            need(member["whole_source_unit"] == unit["text"] and member["source_unit_digest"] == unit["source_unit_digest"], "Membership source changed")
            unit.update(source_id=member["source_id"], source_scope=deepcopy(member["source_scope"]), source_channel=member["source_channel"])
            row = {k: deepcopy(member[k]) for k in ("membership_id", "unit_id", "person_id", "relation", "facet", "quote", "rationale", "limits", "source_channel", "source_attitude", "source_scope", "source_entity", "contrast_or_limit_markers", "direct_support_vote")}
            members.append(row)
            memberships.append({"cluster_id": cid, **deepcopy(row)})
        normalized.append({"cluster_id": cid, "label": cluster["title"], "kind": cluster["kind"],
            "definition": cluster["definition"], "common_meaning": cluster["common_meaning"],
            "design_question": cluster["handshake_question"], "boundaries": deepcopy(cluster["boundaries"]),
            "evidence_refs": sorted({m["unit_id"] for m in members}), "members": members,
            "people_by_role": deepcopy(head["people_by_role"]),
            "summary_status": cluster["summary_status"], "semantic_truth_verified": False})
    # Unclustered units retain their actual source role too, rather than losing
    # entity/brand/context distinctions merely because no membership was made.
    raw_units = {u["semantic_unit_id"]: u for u in compiler["lines"](dataset / "semantic-units.jsonl")}
    for uid, unit in units.items():
        raw = raw_units[uid]
        unit.update(source_id=raw["source_id"], source_scope=deepcopy(raw.get("scope")),
                    source_channel=compiler["source_channel"](raw),
                    contrast_or_limit_markers=deepcopy(raw["contrast_or_limit_markers"]),
                    input_interpretation_status=raw["independent_review_status"])
    refs += code_refs
    need(all(identity(r["path"]) == r for r in refs), "Research changed while preparing its text view")
    return {"schema_version": "prism.handshake_research_text_view.v2", "clusters": normalized,
        "units": list(units.values()), "negative_unit_ids": negative_ids,
        "unclustered_unit_ids": [u for u, row in coverage.items() if not row["cluster_ids"]],
        "people": deepcopy(result["people"]), "source_identities": refs,
        "input_binding": deepcopy(result["input_binding"]),
        "independent_semantic_review_performed": handoff["summary"]["independent_semantic_review_performed"],
        "semantic_truth_verified": False, "new_product_population_filtered": False,
        "image_links_are_layout_candidates_not_preference_or_visual_approval": True}
