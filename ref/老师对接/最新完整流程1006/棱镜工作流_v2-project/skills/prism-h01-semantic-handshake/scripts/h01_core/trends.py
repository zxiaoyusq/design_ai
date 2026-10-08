"""Read the new text-only trend clusters; never admit legacy Local-CMF T01."""
from copy import deepcopy
from .common import need, read, identity, index


def load_trends(clusters_path, catalogue_path, associations_path=None):
    paths = [clusters_path, catalogue_path] + ([associations_path] if associations_path else [])
    refs = [identity(p) for p in paths]
    result, catalogue = read(clusters_path), read(catalogue_path)
    need(result.get("schema_version") == "prism.trends.semantic_clusters.v0.1", "A new pure-text trend result is required; old Local-CMF themes are not this input")
    evidence = index(catalogue["evidence"], "evidence_id")
    articles = index(catalogue["articles"], "source_id")
    units = []
    for eid, row in evidence.items():
        need(row["source_id"] in articles and isinstance(row.get("text"), str) and row["text"].strip(), "Trend text/article binding missing")
        need(row.get("text_kind") in {"source_paraphrase", "original_text_excerpt", "original_text"}, "Explicit trend text kind required")
        need(row.get("source_group_id") and row.get("claim_origin_id"), "Trend source-group/origin identity required")
        if row["text_kind"] == "source_paraphrase":
            need(row.get("original_text_excerpt") is None, "Stored paraphrase cannot impersonate an original excerpt")
        units.append({k: deepcopy(row.get(k)) for k in ("evidence_id", "source_id", "source_group_id", "claim_origin_id", "text", "text_kind", "locator", "source_url", "original_text_excerpt")})
    clusters = []
    for row in index(result["clusters"], "cluster_id").values():
        eids = row.get("evidence_refs", [])
        need(eids and len(eids) == len(set(eids)) and set(eids) <= set(evidence), "Trend cluster evidence is missing or foreign")
        need(row.get("title") and row.get("definition") and row.get("design_question"), "Trend cluster needs a specific semantic question")
        for field, source_field in (("source_ids", "source_id"), ("source_group_ids", "source_group_id"), ("claim_origin_ids", "claim_origin_id")):
            need(set(row[field]) == {evidence[e][source_field] for e in eids}, "Trend identity should be derived from actual referenced text: " + field)
        bounds = row.get("boundaries", {})
        need(isinstance(bounds, dict) and bounds.get("shared_design_mechanism") and isinstance(bounds.get("includes"), list)
             and isinstance(bounds.get("excludes"), list), "Trend semantic boundaries required")
        clusters.append({**deepcopy(row), "label": row["title"], "semantic_truth_verified": False})
    assets, evidence_images = [], {eid: [] for eid in evidence}
    if associations_path:
        associations = read(associations_path)
        for image in index(associations["images"], "image_id").values():
            need(image.get("association_role") == "source_link_only" and image["source_id"] in articles, "Image association is not visual qualification")
            need(isinstance(image.get("sha256"), str) and len(image["sha256"]) == 64, "Image identity missing")
            eids = image.get("evidence_refs", [])
            need(set(eids) <= set(evidence) and all(evidence[e]["source_id"] == image["source_id"] for e in eids), "Image/text relation crosses original sources")
            groups = {evidence[e]["source_group_id"] for e in eids}
            need(len(groups) <= 1, "Ambiguous source group for an image")
            source_group = next(iter(groups), articles[image["source_id"]].get("publisher_group"))
            need(source_group, "Image source group missing")
            assets.append({"image_id": image["image_id"], "source_id": image["source_id"], "source_group": source_group,
                "source_kind": "trend", "sha256": image["sha256"], "path": image["path"],
                "association_role": "source_link_only", "visual_relevance_checked": False})
            for eid in eids: evidence_images[eid].append(image["image_id"])
        for eid, ids in associations.get("evidence_image_map", {}).items():
            need(eid in evidence and set(ids) == set(evidence_images[eid]), "Image association map differs from original image records")
    need(all(identity(r["path"]) == r for r in refs), "Trend files changed during preparation")
    return {"schema_version": "prism.handshake_trend_text_view.v2", "clusters": clusters, "units": units,
        "articles": list(articles.values()), "asset_catalog": assets,
        "evidence_image_map": {k: sorted(v) for k, v in evidence_images.items()},
        "source_identities": refs, "semantic_truth_verified": False,
        "unclustered_evidence_ids": sorted(set(evidence) - {e for c in clusters for e in c["evidence_refs"]}),
        "images_missing_is_not_an_H01_blocker": True}
