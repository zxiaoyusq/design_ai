/** 高潜趋势接口保留来源和统计口径，供人工复核，不把提及人数解释为偏好率。 */
export interface HighTrendRequest {
  input_mode?: 'module_outputs' | 'raw'
  research_output_ids?: string[]
  trend_result_id?: string
  input_digest?: string
  dataset?: 'original' | 'article_table_2_selected_5'
  all_dates?: boolean
  start_date?: string
  end_date?: string
  model_id: string
  max_calls: number
  prompt?: string
  user_scope?: 'auto' | 'all' | 'first'
  user_limit?: number | null
}

/** 输入目录保留不可选产物及原因，避免把未确认资料当成正式用研依据。 */
export interface HighTrendInputOutput {
  id: string
  title: string
  status: string
  selectable: boolean
  created_at?: string | null
  warnings: string[]
  user_count?: number
  record_count?: number
  article_count?: number
  trend_count?: number
  model_id?: string
}

export interface HighTrendInputs {
  research_outputs: HighTrendInputOutput[]
  trend_outputs: HighTrendInputOutput[]
}

/** 保存任务创建时的上游范围；历史记录不借用当前目录替换来源。 */
export interface HighTrendUpstreamSelection {
  research_outputs?: HighTrendInputOutput[]
  trend_output?: HighTrendInputOutput
  [key: string]: unknown
}

/** 数量筛选在整理资料前生效，来源说明保留到历史任务。 */
export interface HighTrendScope {
  user_limit: number | null
  origin: 'option' | 'prompt' | 'default' | 'module_outputs'
  label: string
  note: string
}

export interface HighTrendCatalog {
  trend_count: number
  user_count: number
  min_date: string | null
  max_date: string | null
  undated_count: number
}

/** 区分本轮模型阅读的主题证据与仅归档关联的成员文章。 */
export interface HighTrendModelInputScope {
  mode: 'existing_theme_handshake'
  trend_theme_count: number
  representative_anchor_limit_per_theme: number
  full_member_articles_archived: number
  full_member_articles_reread: boolean
  research_records_read: number
  description: string
}

export interface HighTrendPreview {
  model_input_scope?: HighTrendModelInputScope
  input_digest: string
  upstream_selection?: HighTrendUpstreamSelection
  scope: HighTrendScope
  counts: { source_users: number; selected_trends: number; selected_users: number; users_with_text: number; user_records: number; trend_cluster_count?: number; model_trend_records?: number; model_user_records?: number }
  plan: { planned_calls: number; map_jobs: number; input_source_chars: number }
  warnings?: string[]
}

export interface TrendSource {
  short_id: string
  record_id?: string
  kind: string
  user_id?: string | number | null
  title?: string | null
  source_path?: string | null
  json_pointer?: string | null
  excerpt?: string | null
  question?: string | null
  semantic_context?: Record<string, unknown> | null
}

export interface TrendImage {
  sha256?: string | null
  byte_size?: number | null
  identity_status?: string | null
  association_type?: string | null
  image_url?: string | null
  image_id?: string | null
  code?: string | null
  source_record_id?: string
  role?: string
  kind?: string
  file_exists: boolean
  url?: string | null
  original_url?: string | null
  article_title?: string | null
  article_url?: string | null
  direction_ids?: string[]
}

/** 原生 H01 的证据保留人物、对象和证据角色，不能把分析备注显示成用户原话。 */
export interface NativeResearchCitation {
  unit_id: string
  text: string
  reason?: string
  role?: string
  person_id?: string | number | null
  object_scope?: string | string[] | Record<string, unknown> | null
  source_kind?: string
  source_id?: string
  original_text?: string
  source_attitude?: string
}

export interface NativeTrendCitation {
  evidence_id: string
  text: string
  text_kind?: string
  source_id?: string
  title?: string
  source_url?: string | null
  url?: string | null
  original_text?: string
  reason?: string
}

export interface NativeHighTrendDetail {
  design_question: string
  selected: boolean
  selected_branches: string[]
  suggested_branches: string[]
  selection_reason?: string
  extension_explanation?: string
  hypotheses?: string[]
  research_citations: NativeResearchCitation[]
  trend_citations: NativeTrendCitation[]
  conditions: { reference_id?: string; text: string; implication?: string; basis_kind?: string }[]
  unresolved_questions: string[]
  negative_counts: { applicable: number; unresolved: number; not_applicable: number }
  source_article_count: number
  direct_article_count: number
  total_image_count: number
  preview_images?: TrendImage[]
}

/** 历史原生运行的真实出处单独展示，不借用今天的 Skill 或生成时间。 */
export interface NativeHighTrendProvenance {
  model_id?: string
  algorithm_version?: string
  confirmed_at?: string
  completed_at?: string
  run_started_at?: string
  actor?: string
  selected_count?: number
  candidate_count?: number
  [key: string]: unknown
}

export interface NativeHighTrendImagePage {
  items: TrendImage[]
  total: number
  page: number
  page_size: number
}

export interface HighTrendCard {
  native_detail?: NativeHighTrendDetail
  relation_basis?: 'direct_support' | 'anchored_extension' | 'exploratory_hypothesis' | 'unknown'
  shared_design_principle?: string
  conditions_and_limits?: string
  unresolved_questions?: string
  evidence_review_status?: string
  clustering_labels?: string[]
  id: string
  title: string
  description: string
  source_records: TrendSource[]
  /** 同父簇资料仅保留关联，不作为方向的直接语义证据。 */
  associated_source_records?: TrendSource[]
  associated_image_refs?: TrendImage[]
  /** 背景资料仅供追溯，不参与主卡图片关联；旧结果可能没有这些字段。 */
  background_source_records?: TrendSource[]
  background_source_ids?: string[]
  image_refs: TrendImage[]
  mention_statistics: { unique_mentioned_users: number; population_count: number; note: string }
  trend_coverage_note?: string
  reason?: string
}

export interface HighTrendResult {
  provenance?: NativeHighTrendProvenance
  handoff_file?: string
  model_input_scope?: HighTrendModelInputScope
  upstream_selection?: HighTrendUpstreamSelection
  trend_categories?: { clustering_label: string; article_count: number; trend_ids: string[] }[]
  user_images?: UserResearchImage[]
  user_image_filter?: 'like_or_enjoy'
  user_images_scope_note?: string
  trends: HighTrendCard[]
  user_research_gaps: { directions: HighTrendCard[]; scope_note?: string; count_note?: string }
  warnings: string[]
  scope_note?: string
  unlinked_notes?: { title: string; text: string }[]
  diagnostics?: HighTrendCard[]
  has_content: boolean
  partial: boolean
}

export type HighTrendStatus = 'queued' | 'running' | 'completed' | 'partial' | 'empty' | 'failed'

/** 新结果只包含 LIKE / ENJOY；旧历史结果可能仍包含未标注附件。 */
export interface UserResearchImage {
  path: string
  file_exists: boolean
  user_ids: (string | number)[]
  image_ids: string[]
  emotion_tags?: string[]
  linked_to_result: boolean
  url?: string | null
}

export interface HighTrendTask {
  kind?: 'native_h01' | string
  provenance?: NativeHighTrendProvenance
  model_input_scope?: HighTrendModelInputScope
  upstream_selection?: HighTrendUpstreamSelection
  id: string
  status: HighTrendStatus
  stage: string
  message: string
  completed_jobs: number
  total_jobs: number
  created_at: string
  updated_at: string
  request: HighTrendRequest
  scope?: HighTrendScope
  counts?: HighTrendPreview['counts']
  error?: string | null
  error_detail?: { code: string; message: string; exception_type: string; job_id?: string | null; seconds?: number | null; http_status?: number | null; time: string }
  error_history?: HighTrendTask['error_detail'][]
  resume?: { can_resume: boolean; used_calls: number; remaining_jobs: number; minimum_max_calls: number }
  events: { time: string; stage: string; message: string }[]
  result?: HighTrendResult | null
  performance?: Record<string, unknown> | null
}
