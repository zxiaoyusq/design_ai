"""A derived task-ID alias after complete original R5 validation."""
from copy import deepcopy

from ..id_reference_board_v5.common import checked, identity, need, seal, text
from ..r5_dual_v2 import adapter as native
from .registry import dependencies

VERSION = "r5-exact-byte-alias-v1.0.0"


def load_record(asset, result_ref, quality_ref=None):
    """Preserve the raw result and all original facts, audit and observation IDs.

    Same-ID input keeps the native behavior/output exactly. Different task IDs
    require the full original portable R5 execution metadata and identical image
    bytes. Fresh target quality remains independent and cannot be aliased here.
    """
    dependencies()
    raw = checked(result_ref)
    need(text(asset.get("image_id")) and text(raw.get("image_id")), "explicit_current_and_original_image_ids_required")
    if asset["image_id"] == raw["image_id"]:
        return native.load_record(asset, result_ref, quality_ref)
    need(quality_ref is None, "alias_requires_separate_current_target_quality")
    need(raw.get("schema_version") == "prism.sol_r5.portable_result.v1", "alias_requires_original_portable_R5_with_execution_metadata")
    image = identity(asset.get("image_path", asset.get("path", "")))
    need(image["sha256"] == asset.get("sha256") == raw.get("image_sha256"), "exact_image_bytes_required_for_alias")
    if asset.get("image_ref") is not None:
        checked(asset["image_ref"], False)
        need(identity(asset["image_ref"]["path"]) == image, "asset_image_ref_mismatch")
    # This is a validation asset derived from the caller's current asset; it is
    # not an invented historical source manifest or execution receipt.
    validation_asset = deepcopy(asset)
    validation_asset["image_id"] = raw["image_id"]
    original = native.load_record(validation_asset, result_ref, None)
    # Native checks baseline, model/effort/tier/Fast, bytes, status, known rows,
    # normalized index and complete audit. A partial result stays partial.
    derived = deepcopy(original)
    derived.pop("digest")
    derived["image_id"] = asset["image_id"]
    derived["asset"] = deepcopy(asset)
    derived["task_image_id_alias"] = {
        "schema_version": "prism.r5.exact_byte_alias.v1", "adapter_version": VERSION,
        "original_image_id": raw["image_id"], "current_image_id": asset["image_id"],
        "image_sha256": image["sha256"], "original_result_ref": deepcopy(result_ref),
        "original_record_digest": original["digest"], "validation_asset": validation_asset,
        "basis": "exact_image_bytes_and_fully_validated_original_portable_R5",
        "raw_modified": False, "facts_modified": False, "new_model_calls": 0,
        "quality_transferred": False, "new_visual_review": False,
    }
    return seal(derived)
