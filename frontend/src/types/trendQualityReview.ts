/** 模型判定与人工选择分别存储；null 表示人工尚未审核。 */
export type TrendQualityDecision = 'PASS' | 'FAIL'
export type TrendQualityCategory = TrendQualityDecision | 'REVIEW' | 'ERROR'
export type TrendQualityManualFilter = 'all' | 'unreviewed' | TrendQualityDecision

/** 人工图库使用文件内容指纹作为唯一标识，保留全部关联图号和来源。 */
export interface TrendQualityImage {
  id: string
  image_id: string
  image_ids: string[]
  article_title: string
  articles: { id: string; title: string; url: string | null }[]
  directions: { id: string; title: string }[]
  model_category: TrendQualityCategory
  model_decision: TrendQualityDecision | null
  model_status: string
  model_error: string | null
  manual_decision: TrendQualityDecision | null
  manual_updated_at: string | null
  width: number | null
  height: number | null
  batch: string
  model: string
  prompt_version: string
  prompt_sha256: string
  model_finished_at: string | null
  thumbnail_url: string
  image_url: string
  source_path: string
}

/** 汇总数量涵盖整个图库，filtered_count 仅计当前筛选范围。 */
export interface TrendQualityCounts {
  total: number
  model: Record<TrendQualityCategory, number>
  manual: { PASS: number; FAIL: number; unreviewed: number }
}

/** 列表由服务器过滤和分页，避免将全部大图库一次载入浏览器。 */
export interface TrendQualityReview {
  collection_id: string
  title: string
  revision: number
  updated_at: string
  counts: TrendQualityCounts
  directions: { id: string; title: string; count: number }[]
  filtered_count: number
  page: number
  page_size: number
  images: TrendQualityImage[]
}

/** 查询条件与服务端接口保持一致；每页固定展示 60 张。 */
export interface TrendQualityReviewQuery {
  model_category: 'all' | TrendQualityCategory
  manual: TrendQualityManualFilter
  direction_id: string
  q: string
  page: number
  page_size: number
}

/** 保存应携带最近读取的版本，冲突时由用户读取新状态后重新选择。 */
export interface TrendQualitySaveResult {
  revision: number
  updated_at: string
  changed: Pick<TrendQualityImage, 'id' | 'manual_decision' | 'manual_updated_at'>[]
  counts: TrendQualityCounts
}
