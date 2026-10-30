/** 文章图片只用于浏览；聚类请求不携带图片内容或图片 DNA。 */
export interface TrendArticle {
  article_id: string
  title: string
  summary: string
  published_at: string | null
  source: string
  source_url: string | null
  category: string | null
  image_count: number
  images: { image_id: string; url: string }[]
}

/** 趋势展示用的关联文章原图；文章身份用于回查图片来源。 */
export interface TrendRelatedImage {
  article_id: string
  article_title: string
  image_id: string
  url: string
}

export interface TrendFilters {
  q?: string
  source?: string
  category?: string
  date_from?: string
  date_to?: string
}

export interface TrendCatalog {
  total: number
  sources: string[]
  categories: string[]
  min_date: string | null
  max_date: string | null
  skill_version: string
}

export interface ArticlePage {
  total: number
  page: number
  page_size: number
  items: TrendArticle[]
}

/** 范围先预估再凭摘要确认，防止预估后变更条件却执行旧范围。 */
export interface TrendSelection {
  filters: TrendFilters
  article_ids?: string[]
  limit?: number | null
  model_id: string
  min_source_groups: number
  max_calls: number
}

export interface TrendPreview {
  selection_digest: string
  article_count: number
  source_group_count: number
  batch_count: number
  estimated_calls: number
  input_characters: number
  warnings: string[]
  skill_version: string
}

export interface TrendClusterResult {
  trends: Record<string, unknown>[]
  evidence_pool: Record<string, unknown>[]
  coverage: Record<string, unknown>
  [key: string]: unknown
}

export interface TrendClusterTask {
  id: string
  status: 'queued' | 'running' | 'failed' | 'completed' | 'interrupted'
  stage: string
  completed_steps: number | null
  total_steps: number | null
  calls: number | null
  kind?: 'historical'
  title?: string
  legacy_notice?: string
  download_url?: string
  download_description?: string
  model_id?: string
  max_calls?: number
  min_source_groups?: number
  skill_version?: string
  usage?: { requests: number; input_tokens: number; output_tokens: number; requests_with_usage: number }
  article_count: number
  created_at: string
  updated_at: string
  error: string | null
  result?: TrendClusterResult
}

export interface TrendModel {
  id: string
  name: string
  model_provider: string
}
