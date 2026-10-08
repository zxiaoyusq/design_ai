# CMF reference board v4

Independent, local CMF intake and visual-group acceptance contract. The module does not execute inference, download, crop, render, or certify aesthetics from DNA values. The user-rejected v3 boards and every frozen v3/R5/quality source remain unchanged.

## Run and integration

Use the existing workspace Python with Pillow and the existing R5 `jsonschema` vendor on `sys.path`. No install is needed. `build_delivery.py` runs the meaningful boundary tests and writes only this owner's `CMF-REFERENCE-V4` delivery. It creates **synthetic** examples with native R5 normalization and native fresh-target quality replay, never a real visual PASS.

```python
from prism_runtime.clustering.cmf_reference_board_v4 import (
    prepare, grouping_view, grouping_template, accept_grouping,
    prepare_board_review, board_review_template, accept_board_review,
    check_expansion_gate,
)

p = prepare(brief_ref, manifest_ref, records, quality_bundles)
model_input = grouping_view(p)
response_shape = grouping_template(p)  # unknown/false defaults; not an approval
# Root supplies real review evidence and saves the actual model response.
g = accept_grouping(p, proposal_ref)
request = prepare_board_review(g, rendered_board_ref)
review_shape = board_review_template(g, request)
a = accept_board_review(g, request, board_review_ref)
gate = check_expansion_gate(a, user_decision_ref=None)  # remains closed
```

All references use local absolute paths and raw byte SHA256 (`common.identity(path)`). Input/output JSON digests use canonical finite JSON; duplicate keys/nonfinite numbers are rejected. The public functions replay current inputs on consumption. Do not edit files already referred to by an accepted snapshot; produce a new reference/review instead.

## Brief and input references

`CONTRACT.md` defines the visual brief. Current pilot is **target 10 / minimum 10 / maximum 12**, not a backfilled eight-image board. A future explicit brief can specify another count policy, but this module never changes it to fill a shortage.

The H01 selection may contain only direction IDs. In that case add:

```json
{
  "direction_id": "CMF02",
  "h01_ref": {"path":"ABSOLUTE", "sha256":"..."},
  "h01_pointer": "/selection/4",
  "direction_evidence": {"ref":{"path":"ABSOLUTE", "sha256":"..."}, "pointer":"/directions/4"},
  "audit_evidence": {
    "negative_audit":{"ref":{"path":"ABSOLUTE", "sha256":"..."},"pointer":"/directions/4/negative_audit"},
    "deferred_obligations":{"ref":{"path":"ABSOLUTE", "sha256":"..."},"pointer":"/directions/4/deferred_obligations"}
  }
}
```

The copied negative/deferred arrays must equal the full source arrays, not a filtered summary. `direction_evidence` retains full semantics and the exact selected direction. Audit linkage does not restrict new candidates to a former decoded-image pool. New target-quality selections must use the same H01, direction and full audit, with their own current candidate membership.

Manifest schema `prism.cmf.candidate_manifest.v4` has `dataset_mode` (`real` or `synthetic_fixture`), `brief_digest`, `images`, and `units`.

Each image includes `image_id`, `image_ref`, `pixels:[width,height]`, `source_kind` (`trend` or `public_design_reference` for eligible candidates), `source_role:"candidate"`, `source_status:"established"`, `source_group_id`, `provenance_refs:[FileRef]` and `dedup_keys:[string]`. Use stable namespaced article/project/series/product keys shared by any common-source images. Same source group, any dedup key, or identical image SHA is max1. Category never gives a quota or an eligibility bonus. Calibration files and derived tiles must retain calibration ancestry in `provenance_refs` and/or a non-candidate role. Equality/declared ancestry are checked; this is not a perceptual-duplicate detector.

Each unit includes `unit_id`, `image_id`, `target_ref`, `endpoints`, `target_binding_ref`, `view_ref`. Target is **exactly** `quality_selected_target_v2.prepare(...).target`, saved unchanged. Each endpoint contains `endpoint_id`, `role`, `original_at`, and nonempty `observation_ids` pointing to original known R5 facts. One endpoint for surface; at least two distinct original locations for same-object interface. Unknown, invalid, pending, ambiguous or non-CMF original facts cannot become anchors. An unknown ID or moved `at` is rejected rather than repaired.

R5 records come from frozen `r5_dual_v2.load_record(asset,result_ref,quality_ref=None)`. Keep any supplied real original records whole. New native quality bundles follow `prism.selected_target_quality.bundle.v2` verbatim: `prepared_ref`, `execution_ref`, `target_review_ref`, `previous_result_ref` (null for primary), `result_ref`, `target_ref`, `target_digest`, `producer_ref`, `producer_version`, `image_id`, `branch`, `source_kind`, `dataset_mode`. Do not wrap/replace the native result with `clustering_view`. Both primary and any preceding confirmation prerequisite are replayed. Missing quality is pending, not invented FAIL or PASS. Producer source/prompt pins are in `dependencies.json`.

## Actual target and display correspondence

Target binding schema `prism.cmf.target_binding.v4`:

- Exact `unit_id`, `image_ref`, `target_ref`, full `endpoints`, `record_digest`, `quality_result_digest`.
- `original_image_seen`, `endpoint_reviews:[{endpoint_id,original_at,observation_ids,selected_target_match,reason}]`.
- For interfaces, `interface_review:{same_object,relation_visible,description}`. Shared frame or matching words do not establish a join. Each endpoint retains its own attributes.
- `review_provenance` as below.

View schema `prism.cmf.view.v4`:

- Exact `unit_id`, `image_ref`, `target_ref`, `endpoints`, original `pixels`, `original_image_review_ref` equal to the target binding ref.
- `rectangle:{x,y,width,height}` normalized in the original frame; `coordinate_frame:"original_pixels_no_rotation"`.
- `transform:"crop_only_no_retouch"` or `"crop_and_uniform_resize_no_retouch"`; actual output `actual_view_ref` is an existing image, with original retained.
- `confirmed`, `original_and_view_match`, `reason`, `limits`, `review_provenance`.

The original parent `at` need not fit entirely in a crop. The necessary feature/interface must remain visible in the actual displayed subregion. Actual view review checks correctness; no physical scale, material, manufacturing or measured gloss is inferred.

Every real visual review supplies `review_provenance:{actor_kind:"human"|"model",actor_id,source_ref,inspected_refs:[FileRef],basis}`. `source_ref` points to saved JSON evidence of the actual review (model call record/output or human original-image review record); `inspected_refs` must include all originals/current views/board required by that stage. Keep the real execution receipts alongside it. The function checks binding and provenance, **not whether an operator's claim to have looked is truthful**. Root must perform and independently audit those actual reviews. Synthetic provenance is rejected in real mode.

## Grouping and whole-board review

Short unit/endpoint/fact aliases freeze with `prepared.digest`; exact original IDs/values/at/source/path remain in `prepared.observation_aliases` and the complete original records. `grouping_view` removes long original observation IDs from model fact references and also exposes the original pending/invalid audit, unresolved bindings and withheld facts, including uncertainty outside the selected known anchors. No unknown or cross-unit alias repair. Every primary endpoint must be supported by exact known fact aliases; visible relationship inference is a separate field, never rewritten DNA. Different members may use entirely different PIDs.

`grouping_template` gives the exact proposal shape and unknown defaults. Assess every primary and secondary condition, every allowed variation and confounder. Required conditions must be supported, variation within bounds, confounders controlled. Partition every eligible unit between `members` and `excluded_eligible`; the adapter carries the complete pending/context/calibration ledger. Never count those as aesthetic failures. All negative aliases must retain a scope-specific disposition. Current conflict/uncertainty blocks. A `future_product_obligation` must point to original `deferred_obligation_indices` and stays unresolved; it does not automatically veto an exploratory reference board.

`accept_grouping` only returns `candidate_for_board_review` or `blocked`, always `visual_pass:false`. Root renders the member order as tile indices 1..n and passes the **binary image FileRef** to `prepare_board_review`. Its request binds all originals, views, targets/endpoints, current brief, negatives, grouping and board bytes. `board_review_template` supplies all required per-tile and global checks. Whole-board judgment cannot be inferred from captions, repeated PID values, target-quality PASS or count. Changing any current relevant input invalidates the old review.

Only a fully accepted current real review is `ready_for_user_feedback`, still `expansion_allowed:false`. `check_expansion_gate` requires a separately saved `prism.cmf.user_decision.v4` with current `acceptance_digest`, `rendered_board_ref`, `actor_kind:"human"`, `decision:"approve_expansion"`, `exact_quote`, and `original_user_message:{ref,pointer}`. The original message object has actual `role:"user"`, `origin_kind:"human"`, `delegated:false`, `message_id`, `thread_id`, `content`. Preserve the real message and its board context; do not relabel a delegated AI reply or the earlier “改吧” as user approval of the new sample. The executor authenticates the human source and interprets the actual approval; a local JSON assertion alone does not authenticate a person. Synthetic outputs never authorize expansion.

## Verification limits

The examples use explicitly synthetic tiny image bytes and invented facts with **zero model/network calls**. They verify native replay and gate behavior, not visual accuracy, source truth, real product properties, or user preference. The current real pilot brief can be checked read-only; real candidate intake, visual review and human acceptance belong to Root's one bounded pilot.
