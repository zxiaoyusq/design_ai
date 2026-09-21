export type ReviewCollection = 'result' | 'remaining'

export type ReviewImageSource = 'trend' | 'user'

/** 同一内容只保留一份副本，所有来源和方向关系仍完整保留，供后续去重对照。 */
export interface ReviewImageOrigin {
  source_kind: ReviewImageSource
  image_id: string | null
  source_record_id: string | null
  source_aliases: string[]
  source_title: string | null
  user_id: string | number | null
  code: string | null
  emotion_tag: string | null
  original_path: string | null
  original_absolute_path: string | null
  source_file: string | null
  json_pointer: string | null
  urls: string[]
  direction_id: string | null
  direction_title: string | null
}

export interface ReviewImage {
  id: string
  sha256: string
  file_name: string
  copy_path: string
  byte_size: number
  width: number | null
  height: number | null
  retained: boolean
  source_kinds: ReviewImageSource[]
  image_ids: string[]
  directions: { id: string; title: string }[]
  origins: ReviewImageOrigin[]
  image_url: string
}

/** revision 用于避免多个页面的选择互相覆盖；用户确认的保留状态由后端持久化。 */
export interface HighTrendImageReview {
  warnings?: { source_file: string; message: string }[]
  collection: ReviewCollection
  scope: string
  dedup_summary?: { candidate_unique_files: number; excluded_result_files: number; remaining_unique_files: number; user_dislike_filtered_files?: number }
  task_id: string
  title: string
  created_at: string
  updated_at: string
  revision: number
  folder: string
  source_result_sha256: string
  counts: {
    total: number
    retained: number
    excluded: number
    trend: number
    user: number
    missing: number
    reference_count: number
  }
  images: ReviewImage[]
  missing: Record<string, unknown>[]
}
