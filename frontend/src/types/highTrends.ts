/** 高潜趋势接口保留来源和统计口径，供人工复核，不把提及人数解释为偏好率。 */
export interface HighTrendRequest {
  start_date: string
  end_date: string
  model_id: string
  max_calls: number
  prompt?: string
}

export interface HighTrendCatalog {
  trend_count: number
  user_count: number
  min_date: string | null
  max_date: string | null
  undated_count: number
}

export interface HighTrendPreview {
  counts: { selected_trends: number; selected_users: number; users_with_text: number; user_records: number }
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
  id: string
  title: string
  description: string
  source_records: TrendSource[]
  image_refs: TrendImage[]
  mention_statistics: { unique_mentioned_users: number; population_count: number; note: string }
  trend_coverage_note?: string
  reason?: string
}

export interface HighTrendResult {
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
  error?: string | null
  error_detail?: { code: string; message: string; exception_type: string; job_id?: string | null; seconds?: number | null; http_status?: number | null; time: string }
  error_history?: HighTrendTask['error_detail'][]
  resume?: { can_resume: boolean; used_calls: number; remaining_jobs: number; minimum_max_calls: number }
  events: { time: string; stage: string; message: string }[]
  result?: HighTrendResult | null
  performance?: Record<string, unknown> | null
}
