/** 情绪版只把已提取的 DNA 文本送入模型；预览地址仅供人工查看。 */
export interface MoodboardDnaSummary {
  id: string
  image_name: string
  preview_url: string | null
  created_at: string
  category: string | null
  style_candidates: string[]
  summary: string | null
}

export interface MoodboardDirection {
  id: string
  title: string
  description: string
}

export interface MoodboardCatalog {
  /** v2 原生视觉链与历史纯文本任务分离；停用旧执行不影响历史浏览。 */
  execution?: { supported: boolean; workflow: string; reason: string }
  trend_tasks: { id: string; created_at: string; directions: MoodboardDirection[] }[]
  dna_results: MoodboardDnaSummary[]
}

/** 提交前由界面展示实际方向、图片数量与模型，并获得人工确认。 */
export interface MoodboardRequest {
  trend_task_id: string
  direction_ids: string[]
  result_ids: string[]
  model_id: string
  confirmed: true
}

export interface MoodboardAssignment {
  result_id: string
  direction_id: string | null
  reason: string
  evidence_paths: string[]
  /** v2 区分主导风格匹配、方向歧义、信息不足；旧记录没有这些字段。 */
  status?: 'matched' | 'ambiguous' | 'insufficient' | 'unmatched'
  dominant_style?: string
  dominance?: {
    strength: 'strong' | 'moderate' | 'weak' | 'unknown'
    scope: 'global' | 'local' | 'unknown'
    salience: 'primary' | 'secondary' | 'unknown'
  }
  competing_direction_ids?: string[]
  /** 服务端从冻结 DNA 中解析实际值，便于人工核对模型引用。 */
  evidence?: { path: string; value: unknown }[]
}

export interface MoodboardResult {
  directions: (MoodboardDirection & {
    clusters: {
      id: string
      name: string
      description: string
      result_ids: string[]
      /** v2 正式主题为 6–8 张，v3 为 4–8 张；主轴与边界用于人工复核。 */
      primary_axis?: string
      required_features?: string[]
      exclusions?: string[]
    }[]
    /** 已匹配趋势但未被正式主题选中；缺省表示旧版全量聚类。 */
    excluded?: { result_id: string; reason: string }[]
  })[]
  assignments: MoodboardAssignment[]
  images: MoodboardDnaSummary[]
  unmatched_result_ids: string[]
  trace: Record<string, unknown>
}

export interface MoodboardTask {
  id: string
  /** 历史选择器用冻结协议区分新版精选与旧版分类。 */
  prompt_version?: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  stage: string
  message: string
  created_at: string
  updated_at: string
  request: MoodboardRequest
  completed_jobs: number
  total_jobs: number
  error?: string | null
  result?: MoodboardResult | null
}

/** 新聚类协议独立于旧纯文本归属协议，历史结果不能被标成当前 Skill 已验收。 */
export interface ClusteringCatalog {
  results: { id: string; title: string; created_at: string; directions: (MoodboardDirection & { image_reference_count?: number })[] }[]
  default_model: string
  models: { id: string; name: string }[]
  rules: { min_images: number; max_images: number; category_max_ratio: number }
  warnings: string[]
}

export interface ClusteringCounts {
  total_images: number
  ready_images: number
  missing_dna: number
  unavailable_images: number
  excluded_images: number
  ready_cards: number
}

export interface ClusteringPreview {
  preview_id: string
  counts: ClusteringCounts
  images: {
    id: string
    image_name: string
    preview_url: string | null
    status: 'ready' | 'missing_dna' | 'unavailable' | 'excluded'
    reason?: string
    category?: string
    card_count?: number
  }[]
  warnings: string[]
  source: { title?: string; [key: string]: unknown }
  /** 不可用和人工排除是来源缺口，不混进可读图片池或冒充模型拒绝。 */
  unavailable?: unknown[]
  excluded?: unknown[]
}

/** 预览快照是实际执行边界；只有人工确认后才允许模型调用与缺失 DNA 补查。 */
export interface ClusteringRequest {
  preview_id: string
  model_id: string
  prepare_missing: boolean
  max_calls: number
  workers: number
  confirmed: true
}

export interface ClusteringBoard {
  id: string
  title: string
  description: string
  status: string
  members: { id: string; image_name: string; preview_url: string | null; original_url: string | null; category?: string; reason?: string }[]
  constraints?: Record<string, unknown>
}

export interface ClusteringTask {
  id: string
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed'
  stage: string
  message: string
  created_at: string
  updated_at: string
  request: ClusteringRequest
  counts: ClusteringCounts
  progress: { calls_started: number; max_calls: number }
  result?: { boards: ClusteringBoard[]; small_groups: unknown[]; summary: Record<string, unknown> } | null
  error?: string | null
  can_resume: false
}

/** 已有 Skill 产物的只读投影，沿用该次运行的原始成员与评审结论。 */
export interface SavedMoodboardMember {
  id: string
  image_id: string
  image_name: string
  preview_url: string | null
  original_url: string | null
  category: string | null
  reason?: string | null
  strongest_difference?: string | null
  why_coordinated?: string | null
  source_label?: string | null
  display_bbox?: number[]
  /** 未标记不等于认可，原人工排除意见直接随历史结果展示。 */
  feedback?: { status: 'rejected' | 'unmarked'; reason?: string | null; updated_at?: string | null }
}

export interface SavedMoodboard {
  id: string
  title: string
  description: string
  status_label: string
  status_tone: 'success' | 'warning' | 'default' | 'error'
  review_notes: string[]
  relations?: { label: string; value: string | number }[]
  constraints?: { label: string; value: string | number; status?: string }[]
  members: SavedMoodboardMember[]
  hardest_pair?: { comparison?: string; [key: string]: unknown } | null
  design_quality_choice?: string | null
  source_links?: { label: string; url: string }[]
  feedback_summary?: { rejected: number; unmarked: number }
}

export interface SavedMoodboardSummary {
  id: string
  title: string
  created_at: string
  board_count: number
  image_count: number
  status_label: string
  notes: string[]
}

export interface SavedMoodboardCatalog {
  default_result_id: string | null
  results: SavedMoodboardSummary[]
}

export interface SavedMoodboardResult {
  id: string
  title: string
  created_at: string
  model_id?: string | null
  prompt_version?: string | null
  status_label: string
  notes: string[]
  summary: { label: string; value: string | number }[]
  boards: SavedMoodboard[]
  downloads?: { label: string; url: string }[]
}
