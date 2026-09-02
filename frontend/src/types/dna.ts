export interface ModelInfo {
  id: string
  name: string
  model_provider: 'anthropic' | 'openai'
}

export interface ModelListResponse {
  models: ModelInfo[]
}

export interface UploadedImage {
  id: string
  filename: string
  relative_path: string | null
  content_type: string
  size: number
  created_at: string
  preview_url: string
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed'
export type ImageTaskStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ExtractionTaskItem {
  image_id: string
  filename: string
  status: ImageTaskStatus
  result_id: string | null
  error: string | null
}

export interface ExtractionTask {
  id: string
  status: TaskStatus
  model_id: string
  prompt: string
  progress: number
  created_at: string
  updated_at: string
  items: ExtractionTaskItem[]
}

export interface ExtractionRequest {
  image_ids: string[]
  model_id: string
  prompt: string
}

export interface DesignDnaResultSummary {
  id: string
  image_name: string
  preview_url: string | null
  created_at: string
  category: string | null
  style_tags: string[]
  summary: string | null
}

export interface DesignDnaResult {
  id: string
  view: 'business' | 'detail'
  content: Record<string, unknown>
}
