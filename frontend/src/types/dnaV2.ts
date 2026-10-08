import type { ExtractionTask } from './dna'

/** 同一 V2 页面并列展示冻结 R17 历史结果和新版 Sol R5 平面特征结果。 */
export interface D02ResultSummary {
  id: string
  image_name: string
  created_at: string
  model_id: string
  schema_version: string
  preview_url: string
  schema_valid: boolean
  review_complete: boolean
  object_count: number
  feature_count: number
  research: { source_path: string; preferences: Array<{ user_name: string }> } | null
}

export interface D02Observation {
  object_index: number
  object_type: number
  object_name: string
  geometry: number[]
  field_id: string
  field_name: string
  value: string
}

export interface D02Review {
  object_index: number
  field_id: string
  verdict: 'supported' | 'contradicted' | 'unknown'
  reason: string
}

export interface D02LegacyResult {
  id: string
  skill: string
  schema_version: 'prism_d02_candidate_v1'
  image_name: string
  created_at: string
  source: {
    image_id: string
    image_sha256: string
    image_filename: string
    content_type: string
    upload_metadata: Record<string, unknown> | null
    upload_metadata_sha256: string | null
    research: { source_path: string; preferences: Array<{ user_name: string }> } | null
  }
  execution: {
    model_id: string
    user_prompt: string
    started_at: string
    finished_at: string
    duration_seconds: number
    prompt_version: string
    prompt_sha256: string
    schema_sha256: string
    skill_sha256: string
    review_version: string
    primary_usage: Record<string, number | boolean>
    review_usage: Record<string, number | boolean>
  }
  validation: {
    r41_schema_valid: boolean
    schema_issues: string[]
    basic_protocol_valid: boolean
    protocol_issues: string[]
    review_complete: boolean
    review_issues: string[]
    official_projection_verified: boolean
    note: string
  }
  observations: D02Observation[]
  reviews: D02Review[]
  candidate: Record<string, unknown> | null
  raw_responses: { primary: string; review: string | null }
}

export interface D02R5LocalFeature {
  at: string
  p: string
  v: unknown
  path: string
  source: string
  evidence?: string
}

export interface D02R5Feature {
  parameter_id: string
  parameter_name: string
  value: unknown
  locations: string[]
  views: string[]
  provenance: string[]
}

export interface D02R5Result {
  id: string
  skill: 'prism-dna-sol-r5'
  schema_version: 'prism_sol_r5_candidate_v1'
  image_name: string
  created_at: string
  source: D02LegacyResult['source']
  execution: {
    model_id: string
    adapter: 'deepagents' | 'codex_cli_frozen_r5'
    duration_seconds: number
    prompt_version: string
    skill_sha256: string
    prompt_asset_sha256: string
    schema_asset_sha256: string
    attempted_calls: number
    max_calls: number
    focus_error: string | null
    trace_dir: string
  }
  validation: {
    primary_schema_valid: boolean
    focus_complete: boolean
    pending_count: number
    invalid_count: number
    full_216_visual_qualified: boolean
    human_gold_accuracy_established: boolean
    note: string
  }
  r5_result: {
    algorithm_version: string
    features: D02R5Feature[]
    local_features: D02R5LocalFeature[]
    pending: unknown[]
    invalid: unknown[]
    decisions: unknown[]
    admission_adjustments: unknown[]
    image_unique_features: number
    image_unique_CMF: number
    ID_unique: number
    CMF_unique: number
    pending_count: number
  }
  raw_responses: { primary: string; focus: string | null }
}

export type D02Result = D02LegacyResult | D02R5Result

export type D02Task = ExtractionTask

export interface D02PptBatch {
  batch_id: string
  status: 'prepared' | 'running' | 'completed' | 'partial' | 'blocked'
  model_id: string
  total_paths: number
  unique_image_sha256: number
  max_concurrency: number
  updated_at: string
  stopped_reason: string | null
  counts: { pending: number; running: number; completed: number; failed: number }
  quality_counts: { schema_valid: number; protocol_valid: number; review_complete: number }
  entries: Array<{
    source_path: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    result_id: string | null
    error: string | null
    duration_seconds: number | null
    reused_from_result_id: string | null
    schema_valid: boolean | null
    protocol_valid: boolean | null
    review_complete: boolean | null
    user_names: string[]
    ref_pic_codes: string[]
  }>
}
