/** 高潜趋势接口保留来源和统计口径，供人工复核，不把提及人数解释为偏好率。 */
export interface HighTrendRequest {
  dataset?: 'original' | 'article_table_2_selected_5'
  all_dates?: boolean
  start_date: string
  end_date: string
  model_id: string
  max_calls: number
  prompt?: string
  user_scope?: 'auto' | 'all' | 'first'
  user_limit?: number | null
}

/** 数量筛选在整理资料前生效，来源说明保留到历史任务。 */
export interface HighTrendScope {
  user_limit: number | null
  origin: 'option' | 'prompt' | 'default'
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

export interface HighTrendPreview {
  scope: HighTrendScope
  counts: { source_users: number; selected_trends: number; selected_users: number; users_with_text: number; user_records: number }
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
}

export interface TrendImage {
  image_id?: string | null
  code?: string | null
  source_record_id?: string
  role?: string
  kind?: string
  file_exists: boolean
  url?: string | null
}

export interface HighTrendCard {
  clustering_labels?: string[]
  id: string
  title: string
  description: string
  source_records: TrendSource[]
  /** 背景资料仅供追溯，不参与主卡图片关联；旧结果可能没有这些字段。 */
  background_source_records?: TrendSource[]
  background_source_ids?: string[]
  image_refs: TrendImage[]
  mention_statistics: { unique_mentioned_users: number; population_count: number; note: string }
  trend_coverage_note?: string
  reason?: string
}

export interface HighTrendResult {
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
