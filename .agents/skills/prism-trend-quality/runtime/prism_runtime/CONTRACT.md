# Prism shared contract v0.1

Owner: current coordination task only. Other modules must not modify this file.

All data is UTF-8 JSON; source IDs and unknown states are preserved. New modules may add fields without changing these meanings. No network call is required by this contract.

## ImageDNA

{
  "schema_version": "prism.image_dna.v0.1",
  "image_id": "stable image identity",
  "source_kind": "trend | research | generated | calibration | synthetic",
  "image_path": "absolute local path or null",
  "source_ref": "path to the original existing output",
  "observations": [
    {
      "observation_id": "stable within this image",
      "parameter_id": "original dictionary field ID, or clearly scoped synthetic fixture field",
      "object_id": "original carrier/object ID or unknown",
      "value": "typed original value, or null",
      "value_status": "known | unknown | not_applicable",
      "region_ref": "original evidence-region reference, object, or null",
      "evidence_refs": ["source evidence identity"]
    }
  ],
  "provenance": {"mode": "existing_model_output | synthetic", "parser_version": "original"}
}

Adapter preserves full original output as source_ref. It must not collapse original216/148 definitions into fewer claimed-equivalent fields. Unknown or unbindable input must stay explicitly unknown/error. Source kind is supplied by source provenance, not guessed from the picture or an arbitrary file extension.

## TrendQualityDecision

{
  "schema_version": "prism.trend_quality.v0.1",
  "image_id": "same identity as ImageDNA",
  "source_kind": "trend",
  "decision": "PASS | FAIL",
  "reason": "preserved model/human judgement",
  "evidence_refs": ["original result"],
  "rubric_version": "version",
  "provenance": {"mode": "existing_model_output | synthetic"}
}

Research, generated, calibration and unknown-source images are not eligible for the production trend-quality router. Calibration results may be exported as calibration-only, with applicable=false, but never reclassified as trend results just to satisfy the contract. Execution failure is an error, not FAIL.

## GroupingRequest

{
  "schema_version": "prism.grouping_request.v0.1",
  "request_id": "stable ID",
  "brief_id": "project/run scope",
  "direction_id": "H02 design direction",
  "alignment_mode": "consensus | extension | exploration",
  "alignment_label": "共识优先 | 适度延展 | 创新探索",
  "relation_basis": "direct_support | anchored_extension | exploratory_hypothesis",
  "title": "one concrete design question",
  "design_axis": "ID | CMF",
  "candidate_image_ids": ["images from the confirmed or synthetic theme pool"],
  "required_features": [
    {"parameter_id": "field", "allowed_values": ["value"], "evidence_refs": ["trend and/or preference evidence"]}
  ],
  "forbidden_features": [
    {"parameter_id": "field", "forbidden_values": ["value"], "evidence_refs": ["negative preference evidence"]}
  ],
  "comparison_features": ["field IDs used to explain distinctions within admitted images"],
  "preference_refs": ["evidence from U01/H02"],
  "trend_refs": ["evidence from T01/H01"],
  "hypothesis_refs": ["explicitly identified unverified extensions, may be empty"],
  "provenance": {"mode": "synthetic | real_evidence", "designer_confirmed": false}
}

Core required features must be known and satisfied on an actually identifiable carrier/region. Unknown does not match known or unknown. A known forbidden feature is a conflict; an unknown forbidden feature cannot be certified absent. Preserve image-level uncertainty/boundary status. Feature value comparison should be explicit and deterministic; no invented similarity probabilities. If no required feature is grounded, return needs_input rather than a catch-all cluster.

Alignment mode is chosen by the handshake module, not invented by clustering. 共识优先 requires direct shared preference support. 适度延展 keeps an explicit supported anchor and allows bounded additional design expressions, labelled as extensions. 创新探索 can propose cross-category or recombined expressions around an evidenced user need, with explicit hypotheses and anchors. All three preserve user exclusions, source identity and unknowns. This setting does not relax evidence validity, turn unknown into support, or relax the clustering module's truthfulness. Clustering must preserve the chosen mode and relation basis in its output and must not quietly switch modes when no cluster is possible.

Scope matters: an image can contain multiple objects or localized expressions. Do not combine observations on incompatible carriers to pretend a single object satisfies all requirements. Region-level matches may create candidate membership, with original region binding retained. Do not require the whole image to already look like a finished moodboard.

## CandidateClusters

{
  "schema_version": "prism.candidate_clusters.v0.1",
  "request_id": "input request ID",
  "alignment_mode": "copied from input",
  "clusters": [
    {
      "cluster_id": "stable within run",
      "shared_features": [{"parameter_id": "field", "value": "known supported value"}],
      "members": [{"image_id": "id", "object_id": "carrier", "observation_ids": ["evidence"], "region_refs": []}],
      "explanation": "commonality and distinction",
      "evidence_refs": ["input evidence"]
    }
  ],
  "boundary_members": [{"image_id": "id", "reason": "explicit uncertainty"}],
  "excluded": [{"image_id": "id", "reason": "explicit conflict/outside scope"}],
  "status": "complete | partial | needs_input",
  "provenance": {"mode": "synthetic | real_evidence"}
}

Cluster count and member count are not fixed. The current clustering task does not select a final representative, crop, lay out moodboards, generate images or claim customer validation.

## Module handoff

Each owner writes only its assigned module directory and outputs/prism-algorithm-loop-20260926/modules/<name>/handoff.json:

{
  "module": "dna | quality | trends | handshake | clustering",
  "status": "ready | partial | blocked",
  "contract_version": "0.1",
  "entrypoint": "reproducible command or import",
  "files": ["owned files"],
  "fixture_or_existing_output": ["usable example paths"],
  "verification": {"command": "offline test command", "result": "actual result"},
  "new_paid_calls": 0,
  "limitations": ["remaining data/semantic/validation gaps"]
}

Read existing frozen products; do not mutate them. Preserve other authors' edits. Propose contract changes in the handoff rather than editing the shared contract.

## TrendTheme

The trends module owns semantic theme grouping, before either handshake. It does not infer user preferences or perform the downstream conditional image clustering.

{
  "theme_id": "stable within the run",
  "title": "specific semantic design theme",
  "summary": "source-grounded theme description",
  "evidence_refs": ["original trend text evidence IDs"],
  "image_ids": ["images explicitly associated with those source records"],
  "source_group_ids": ["deduplicated original-source groups"],
  "scope": {"start_date": "optional", "end_date": "optional", "region": "optional"},
  "provenance": {"mode": "synthetic | real_evidence", "semantic_method": "model/host findings with validated sources"}
}

Semantic models/host can propose themes; deterministic code must retain source identity, dates and image links. Existing labels are inputs, not proof that new clustering occurred. Text-only trend records remain usable even without an admissible trend image; image admission is a separate trend-only quality route.

## Two independent handshake outputs

H01 consumes TrendTheme, ProjectBrief and thematic PreferenceProfile, and outputs ThemeHandshake: theme candidates, target user/need anchors, direct/extension/exploratory status, conflicts/gaps and designer-review state. H01 must work when evidence is text-only.

H02 consumes an explicitly selected theme pool, ImageDNA, element/thematic PreferenceProfile and H01 evidence. It outputs GroupingRequest records, or explicit gaps. It must not silently treat an unconfirmed real theme selection as designer approval. Synthetic fixtures may mark the selection as a synthetic assumption, never real approval.

New task ownership: trends task owns prism_runtime/trends/ and modules/trends/; handshake task owns prism_runtime/handshake/ and modules/handshake/. Root stops writing the handshake module after handoff and retains preferences, shared contracts, fixtures and integration only.
