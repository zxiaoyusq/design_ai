"""Lossless R5 intake; flat names are never converted to boxes or object trees."""
from copy import deepcopy
import importlib.util
from pathlib import Path

from .common import BASELINE, canonical, checked_file, digest, identity, need, read, seal

_LOADER = None


def producer():
    global _LOADER
    registry = read(Path(__file__).with_name("producer.json"))
    registry["engine_path"] = str((Path(__file__).parent / registry["engine_path"]).resolve())
    for item in registry["pins"] + [registry["root_baseline_identity"]]:
        item["path"] = str((Path(__file__).parent / item["path"]).resolve())
    need(registry["baseline_id"] == BASELINE, "Unregistered R5 baseline")
    for ref in registry["pins"] + [registry["root_baseline_identity"]]:
        need(identity(ref["path"]) == ref, "Frozen R5 dependency changed")
    if _LOADER is None:
        spec = importlib.util.spec_from_file_location("_prism_frozen_r5_offline_adapter", registry["engine_path"])
        _LOADER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_LOADER)
    # This official portable method checks all source-manifest hashes and
    # loads only pure frozen functions. It has no model/CLI execution step.
    return _LOADER.load_original()


def _issues(value):
    if isinstance(value, dict):
        if isinstance(value.get("p"), str):
            yield {"parameter_id": value["p"], "at": value.get("at"), "original": deepcopy(value)}
        for child in value.values():
            yield from _issues(child)
    elif isinstance(value, list):
        for child in value:
            yield from _issues(child)


def adapt_r5(result, asset, quality=None):
    """In-memory validation/transport only. File identity is checked by load_record."""
    engine = producer()
    schema = result.get("schema_version")
    need(schema in {"prism.sol_r5.portable_result.v1", "prism.r5_dual_view.v1"}, "R5 result required; legacy R17 is incompatible")
    need(result.get("algorithm_version", result.get("parser_baseline")) == BASELINE, "R5 algorithm identity changed")
    need(result.get("image_id") == asset["image_id"] and result.get("image_sha256") == asset["sha256"], "Original image identity mismatch")
    if schema == "prism.sol_r5.portable_result.v1":
        need(result.get("status") in {"partial", "accepted_for_pilot"}, "No accepted R5 result")
        need(result.get("model") == "gpt-6-sol" and result.get("reasoning_effort") == "low"
             and result.get("service_tier_requested") == "default" and result.get("fast_mode") is False, "R5 requested execution policy changed")
        need(result.get("source_binding") == "named_flat_locations_no_boxes_or_object_tree", "Unexpected R5 position representation")
    local = result.get("local_features")
    need(isinstance(local, list), "Original local_features required")
    for row in local:
        need(row.get("p") in engine.ACTIVE and all(isinstance(row.get(k), str) and row[k].strip() for k in ("at", "path", "source")),
             "Incomplete/nonvisual original R5 observation")
        need(row.get("v") is not None, "An unknown cannot be a positive observation")
    index, excluded = engine.r3.normalize([{"feature": f, "source": f["source"]} for f in local])
    need(not excluded and canonical(index) == canonical(result.get("features", result.get("original_global_features"))),
         "R5 local observations and original image index disagree")
    if schema == "prism.r5_dual_view.v1":
        need(result["ID"]["features"] == [f for f in index if "ID" in f["views"]]
             and result["CMF"]["image_index"] == [f for f in index if "CMF" in f["views"]], "Dual views differ from original normalized index")
        expected = {}
        for fact in local:
            if "CMF" in engine.r3.views(fact["p"]): expected.setdefault(fact["at"], []).append(fact)
        actual = {loc["label"]: loc for loc in result["CMF"]["locations"]}
        need(len(actual) == len(result["CMF"]["locations"]) and set(actual) == set(expected), "Declared CMF locations changed")
        for label, loc in actual.items():
            need(loc["features"] == expected[label] and loc.get("binding_basis") == "exact_original_location_text"
                 and loc.get("bounding_box") is None and loc.get("physical_carrier_identity_verified") is False,
                 "Flat R5 positions cannot claim a physical carrier or bounding box")
    observations = []
    for row in local:
        observations.append({"observation_id": "r5obs:" + digest([asset["sha256"], row])[:24],
            "parameter_id": row["p"], "value": engine.r3.unwrap(row["v"]), "at": row["at"],
            "views": engine.r3.views(row["p"]), "source": row["source"], "path": row["path"],
            "original": deepcopy(row), "id_is_derived_not_producer_assigned": True})
    need(len({o["observation_id"] for o in observations}) == len(observations), "Duplicate original observation identity")
    audits = {key: deepcopy(result.get(key, [])) for key in ("pending", "invalid", "decisions", "admission_adjustments")}
    for key in audits:
        need(isinstance(audits[key], list), "Original audit must remain a list: " + key)
    issues = list(_issues([audits["pending"], audits["invalid"]]))
    locations = {o["at"] for o in observations} | {x["at"] for x in issues if isinstance(x.get("at"), str) and x["at"]}
    locations_by_view = {branch: sorted({o["at"] for o in observations if branch in o["views"]}
        | {x["at"] for x in issues if x["parameter_id"] in engine.ACTIVE and isinstance(x.get("at"), str)
           and x["at"] and branch in engine.r3.views(x["parameter_id"])}) for branch in ("ID", "CMF")}
    return seal({"schema_version": "prism.r5.cluster_record.v2", "image_id": asset["image_id"], "image_sha256": asset["sha256"],
        "asset": deepcopy(asset), "observations": observations, "image_index": deepcopy(index),
        "locations": sorted(locations), "quality": deepcopy(quality), "locations_by_view": locations_by_view,
        "original_audit": audits, "unresolved_feature_bindings": issues,
        "producer_result_digest": digest(result), "baseline": BASELINE,
        "producer_metadata": {k: deepcopy(result.get(k)) for k in ("schema_version", "status", "model", "reasoning_effort",
            "service_tier_requested", "actual_served_tier", "fast_mode", "model_calls", "fixture_only", "not_a_model_output")},
        "validation": {"original_normalizer_replayed": True, "file_identity_verified": False,
            "new_visual_review": False, "ordinary_features_all_independently_reviewed": False,
            "physical_carrier_identity_verified": False, "bounding_boxes_created": 0, "object_tree_created": False}})


def load_record(asset, result_ref, quality_ref=None):
    path = asset.get("image_path", asset.get("path"))
    need(path and identity(path)["sha256"] == asset["sha256"], "Original image file missing or changed")
    record = adapt_r5(checked_file(result_ref), asset, checked_file(quality_ref) if quality_ref else None)
    record["validation"].update(file_identity_verified=True, image_identity=identity(path), result_identity=deepcopy(result_ref),
                                 quality_identity=deepcopy(quality_ref))
    record.pop("digest")
    return seal(record)
