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
