import type { ExtractionTask, ModelInfo } from './dna'

/** 历史 R17／R5 的兼容摘要；当前 V2 图库使用下方 PreparedResultSummary。 */
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

/** 设计卡保留模型原生对象和坐标，缺项不会被显示层补成已知事实。 */
export type PreparedBranch = 'ID' | 'CMF'
export type PreparedBbox = [number, number, number, number]
export interface PreparedFileRef { path: string; sha256: string }
export interface PreparedRelation {
  observation: string
  evidence: string[]
  unknown: boolean
}
export interface PreparedStyle {
  style_id: string
  main_support: string[]
  main_conflicts: string[]
  match_score: number
  confidence: number
}
export interface PreparedDesignCard {
  card_id: string
  branch: PreparedBranch
  image_id: string
  image_sha256: string
  category: string
  subject: { identity: string; role: string; bbox: PreparedBbox; whole_visible: boolean }
  bbox_format: 'xywh_normalized'
  display_bbox: PreparedBbox
  evidence_bbox: PreparedBbox
  display_scope: 'whole_object' | 'representative_detail'
  crop_reason: string
  relations: Record<'palette' | 'silhouette' | 'planes' | 'lines' | 'optics' | 'texture' | 'details', PreparedRelation>
  style_candidates: PreparedStyle[]
  design_emotion: { expression: string; coordination_reason: string; counter_signals: string[] }
  design_quality: { level: 'ordinary' | 'considered' | 'uncertain' | 'strong'; evidence: string[] }
  limitations: string[]
  source_kind: string
  sources: PreparedSource[]
  provenance: {
    actual_model: string | null
    requested_model: string
    reasoning_effort: string | null
    prompt_version: string
    assessed_at: string
    pointer: string
    answer_ref: PreparedFileRef
    prompt_ref: PreparedFileRef
    receipt_ref: PreparedFileRef
  }
}
export interface PreparedSource {
  title?: string
  article_url?: string
  image_url?: string
  source_id?: string
  publisher?: string
  category?: string
  subcategory?: string
  [key: string]: unknown
}
export interface PreparedResultSummary extends D02ResultSummary {
  status: string
  branches: PreparedBranch[]
  object_names: string[]
  style_names: string[]
  style_ids?: string[]
  source_kind: string
  card_count?: number
  frozen?: boolean
}
export interface PreparedCoverage {
  /** 新请求使用的工程模型目录；历史设计卡仍保留各自的模型与 Prompt。 */
  available_models?: ModelInfo[]
  default_model?: string
  framework?: string
  transport?: string
  agent_runtime_version?: string
  counts: {
    images: number
    observed: number
    failed: number
    pending: number
    cards: number
    cards_by_branch: Record<PreparedBranch, number>
    images_by_branch: Record<PreparedBranch, number>
    success_rate: number
    [key: string]: unknown
  }
  created_at: string
  coverage_limit?: string
  historical_prompt_version?: string
  current_prompt_version?: string
  style_catalog?: Array<{ style_id: string; name: string }>
  unavailable_new_results?: Array<{ id: string; error: string }>
  [key: string]: unknown
}
export interface PreparedDnaResult {
  id: string
  skill: string
  schema_version: 'prism_prepared_design_cards_v1'
  image_name: string
  created_at: string
  status: string
  preview_url?: string
  source: {
    image_id: string
    image_sha256: string
    image_filename: string
    source_kind?: string
    sources?: PreparedSource[]
    [key: string]: unknown
  }
  execution: {
    model_id: string
    actual_model?: string | null
    prompt_version?: string
    reasoning_effort?: string | null
    started_at?: string
    [key: string]: unknown
  }
  validation: { note?: string; [key: string]: unknown }
  cards: PreparedDesignCard[]
  invalid_objects: unknown[]
  style_catalog: Array<{ style_id: string; name: string }>
  [key: string]: unknown
}
