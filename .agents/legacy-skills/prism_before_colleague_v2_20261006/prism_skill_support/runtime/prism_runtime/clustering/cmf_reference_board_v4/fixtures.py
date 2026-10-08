"""Offline invented fixtures. No real images, preferences, or visual approval."""
from copy import deepcopy
from pathlib import Path
import base64
import json

from .common import digest, identity, pins, read, seal

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRZkAAAAASUVORK5CYII=")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return identity(path.resolve())


def provenance(trace, refs):
    return {"actor_kind": "synthetic_fixture", "actor_id": "TEST", "source_ref": trace,
            "inspected_refs": deepcopy(refs), "basis": "Synthetic contract assertion; no real visual review."}


def build(folder, count=10):
    from ..r5_dual_v2.adapter import producer, load_record
    from ..r5_dual_v2.common import BASELINE
    from prism_sidecars.quality_selected_target_v2 import protocol as q
    from prism_sidecars.quality_selected_target_v2.test_protocol import execution
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    negative = [{"negative_id": "N-original", "person": "fixture-person", "object": "future phone",
                 "original_quote": "too glossy", "context": "one specific phone; not all materials", "scope": "unresolved"}]
    deferred = [{"id": "future-phone", "status": "unresolved", "requirement": "Actual product validation remains necessary"}]
    choice = {"direction_id": "CMF01", "branches": ["CMF"], "negative_audit": negative, "deferred_obligations": deferred}
    h01 = seal({"selection": [choice], "confirmation": {"status": "confirmed", "actor_kind": "synthetic_fixture"}})
    h01_ref = save(folder / "h01.json", h01)
    calibration_ref = save(folder / "calibration.json", {"fixture_only": True, "role": "calibration_only"})
    brief = {"schema_version": "prism.cmf.visual_brief.v4", "brief_id": "SYNTHETIC", "direction_id": "CMF01",
             "h01_ref": h01_ref, "h01_pointer": "/selection/0", "comparison_unit": "same_object_interface",
             "primary_signature": {"description": "Invented subdued body plus a precise adjoining detail; no real visual claim",
                                   "conditions": [{"id": "P1", "question": "Is the subdued body joined to the contained detail?"}]},
             "secondary_dimensions": [{"id": "S1", "question": "Fine surface appearance?", "required": False}],
             "allowed_variation": [{"id": "V1", "description": "Different product categories", "boundary": "Relation stays readable"}],
             "confounders": [{"id": "C1", "description": "Separate objects or background may simulate a join"}],
             "calibration_refs": [{"ref": calibration_ref, "pages_or_labels": ["TEST"], "role": "calibration_only"}],
             "count_policy": {"target": 10, "minimum": 10, "maximum": 12, "basis": "Explicit ten-source protocol fixture"},
             "negative_audit": negative, "deferred_obligations": deferred,
             "scope_limits": ["Synthetic protocol only; no real visual acceptance or physical properties."]}
    brief_ref = save(folder / "brief.json", brief)
    images, units, records, bundles = [], [], [], []
    model = producer()
    for i in range(count):
        dest = folder / ("image-" + str(i + 1).zfill(2))
        dest.mkdir(exist_ok=True)
        # Different file identities on deliberately tiny invented test assets.
        path = dest / "synthetic.png"
        path.write_bytes(PNG + ("SYNTHETIC:" + str(i)).encode())
        image_ref = identity(path)
        iid = "fixture-" + str(i + 1)
        trace = save(dest / "external-review-trace.json", {"fixture_only": True, "new_model_calls": 0,
                                                          "note": "Invented review, not pixel evidence"})
        source = save(dest / "source.json", {"fixture_only": True, "article_id": "article-" + str(i),
                                           "category_original": "appliance" if i % 2 else "furniture"})
        asset = {"image_id": iid, "image_ref": image_ref, "source_kind": "trend", "source_status": "established",
                 "source_group_id": "article-" + str(i), "provenance_refs": [source]}
        projection_ref = save(dest / "asset.json", {"asset": asset})
        scope_ref = save(dest / "visual-scope.json", {"direction_id": "CMF01", "branch": "CMF", "hint_only": True})
        view_choice = {"article_id": "article-" + str(i), "choice": "candidate_for_DNA_and_quality", "original_seen": True,
                       "attached_image_index": 1, "visible_surface_scope": "body and adjoining trim", "reason": "synthetic",
                       "limits": ["only front appearance; no physical proof"]}
        view_answer = save(dest / "original-selection.json", {"direction_id": "CMF01", "articles": [view_choice], "fixture_only": True})
        view_request = save(dest / "original-selection-request.json", {"call_id": "TEST-view", "images": [image_ref]})
        view_receipt = save(dest / "original-selection-receipt.json", {"call_id": "TEST-view", "exit_code": 0, "timed_out": False,
                                                                      "schema_valid": True, "tool_event_count": 0, "fixture_only": True})
        qm = save(dest / "quality-manifest.json", {"direction_id": "CMF01", "branch": "CMF", "H01_selection_ref": h01_ref,
                  "visual_scope_ref": scope_ref, "images": [{"image_ref": image_ref, "original_view_choice": view_choice, "view_review_ref": view_answer}]})
        selection = {"status": "confirmed", "directions": [{**choice, "candidate_image_ids": [iid]}]}
        selection["selection_digest"] = digest(selection)
        qs = save(dest / "quality-selection.json", selection)
        qp = q.prepare(run_id="TEST-fresh", manifest_ref=qm, image_pointer="/images/0", asset_evidence={"ref": projection_ref, "pointer": "/asset"},
                       selection_ref=qs, view_request_ref=view_request, view_receipt_ref=view_receipt)
        ep, tr = execution(dest, qp)
        result = q.accept(qp, ep, target_review_ref=tr)
        target_ref = save(dest / "target.json", qp["target"])
        bundle = {"schema_version": "prism.selected_target_quality.bundle.v2", "dataset_mode": "synthetic_fixture", "fixture_only": True,
                  "image_id": iid, "branch": "CMF", "source_kind": "trend", "target_ref": target_ref, "target_digest": qp["target"]["target_digest"],
                  "prepared_ref": save(dest / "quality-prepared.json", qp), "execution_ref": ep, "target_review_ref": tr,
                  "previous_result_ref": None, "result_ref": save(dest / "quality-result.json", result),
                  "producer_ref": pins()["quality_protocol"], "producer_version": q.VERSION, "actual_model_calls": 0}
        bundles.append(bundle)
        facts = ([("body", "OPT-002", "哑光"), ("trim", "COL-006", "黑色")] if i % 2 == 0 else
                 [("body", "TEX-002", "颗粒"), ("trim", "OPT-001", "金属外观")])
        facts += [("separate-paper", "COL-006", "金色")]
        local = [{"at": at, "p": pid, "v": value, "path": "/fixture/" + str(n), "source": "synthetic-neutral-source"}
                 for n, (at, pid, value) in enumerate(facts)]
        normalized, errors = model.r3.normalize([{"feature": f, "source": f["source"]} for f in local])
        assert not errors
        raw = {"schema_version": "prism.sol_r5.portable_result.v1", "algorithm_version": BASELINE,
               "image_id": iid, "image_sha256": image_ref["sha256"], "status": "accepted_for_pilot", "local_features": local, "features": normalized,
               "pending": [], "invalid": [], "decisions": [], "admission_adjustments": [],
               "source_binding": "named_flat_locations_no_boxes_or_object_tree", "model": "gpt-6-sol", "reasoning_effort": "low",
               "service_tier_requested": "default", "fast_mode": False, "fixture_only": True, "not_a_model_output": True, "model_calls": 0}
        raw_ref = save(dest / "R5-original.json", raw)
        r5asset = {**asset, "sha256": image_ref["sha256"], "image_path": image_ref["path"]}
        record = load_record(r5asset, raw_ref, None)
        records.append(record)
        endpoints = [{"endpoint_id": "body", "role": "primary surface", "original_at": "body",
                      "observation_ids": [o["observation_id"] for o in record["observations"] if o["at"] == "body"]},
                     {"endpoint_id": "trim", "role": "adjoining detail", "original_at": "trim",
                      "observation_ids": [o["observation_id"] for o in record["observations"] if o["at"] == "trim"]}]
        unit = {"unit_id": "unit-" + str(i + 1), "image_id": iid, "target_ref": target_ref, "endpoints": endpoints}
        binding = {"schema_version": "prism.cmf.target_binding.v4", "unit_id": unit["unit_id"], "image_ref": image_ref, "target_ref": target_ref,
                   "endpoints": endpoints, "record_digest": record["digest"], "quality_result_digest": digest(result), "original_image_seen": True,
                   "endpoint_reviews": [{**deepcopy(e), "selected_target_match": True, "reason": "synthetic endpoint assertion"} for e in endpoints],
                   "interface_review": {"same_object": True, "relation_visible": True, "description": "synthetic relation, not a real visual judgment"},
                   "review_provenance": provenance(trace, [image_ref])}
        unit["target_binding_ref"] = save(dest / "target-binding.json", binding)
        view = {"schema_version": "prism.cmf.view.v4", "unit_id": unit["unit_id"], "image_ref": image_ref, "target_ref": target_ref,
                "endpoints": endpoints, "pixels": [1, 1], "original_image_review_ref": unit["target_binding_ref"],
                "rectangle": {"x": 0, "y": 0, "width": 1, "height": 1}, "coordinate_frame": "original_pixels_no_rotation",
                "transform": "crop_only_no_retouch", "actual_view_ref": image_ref, "confirmed": True, "original_and_view_match": True,
                "reason": "Synthetic full-image view", "limits": ["No real visual evaluation"], "review_provenance": provenance(trace, [image_ref])}
        unit["view_ref"] = save(dest / "view.json", view)
        units.append(unit)
        images.append({**asset, "pixels": [1, 1], "source_role": "candidate", "dedup_keys": ["article:" + str(i)]})
    manifest = {"schema_version": "prism.cmf.candidate_manifest.v4", "dataset_mode": "synthetic_fixture",
                "brief_digest": digest(brief), "images": images, "units": units}
    return {"brief_ref": brief_ref, "manifest_ref": save(folder / "candidate-manifest.json", manifest),
            "records": records, "quality_bundles": bundles}


def proposal(prepared, trace):
    from .protocol import grouping_template
    value = grouping_template(prepared)
    for row in value["members"]:
        unit = next(u for u in prepared["units"] if u["unit_alias"] == row["unit_alias"])
        row.update(selection_reason="Synthetic comparison across categories using distinct original PIDs", original_image_seen=True, actual_view_seen=True)
        for c in row["conditions"]:
            c.update(verdict="supported", observation_aliases=[f["alias"] for f in unit["facts"]],
                     visual_inference="Synthetic inferred interface relation, not an additional DNA fact")
        for x in row["variations"]:
            x.update(verdict="within", reason="Synthetic category variation")
        for x in row["confounders"]:
            x.update(verdict="controlled", reason="Synthetic bystander exclusion")
    for row in value["negative_dispositions"]:
        row.update(status="future_product_obligation", reason="Preserve the exact phone-specific opinion for future validation",
                   scope_basis="Synthetic reference exploration; original quote has not been resolved", deferred_obligation_indices=[0])
    refs = [r for u in prepared["units"] if u["status"] == "eligible" for r in (u["image"]["image_ref"], u["view"]["actual_view_ref"])]
    value["review_provenance"] = provenance(trace, refs)
    return value


def board_review(grouping, request, trace):
    from .protocol import board_review_template
    review = board_review_template(grouping, request)
    review.update(board_seen=True, verdict="coherent", reason="SYNTHETIC protocol demonstration, no actual aesthetics judged")
    for m in review["members"]:
        for k in ("original_image_seen", "actual_view_seen", "target_and_endpoints_correct", "tile_matches_current_view", "apparent_scale_comparable"):
            m[k] = True
        m["reason"] = "Synthetic current tile and original comparison"
        for field, verdict in (("conditions", "supported"), ("variations", "within"), ("confounders", "controlled")):
            for c in m[field]:
                c.update(verdict=verdict, reason="Synthetic comparison assertion")
    for c in review["global_checks"]:
        c.update(verdict="supported", reason="Synthetic whole-board assertion")
    for c in review["negative_review"]:
        c.update(verdict="scope_and_disposition_supported", reason="Original disagreement remains unresolved on future product")
    review["review_provenance"] = provenance(trace, [request["rendered_board_ref"]] + [r for t in request["tiles"] for r in (t["image_ref"], t["actual_view_ref"])])
    return review
