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
export type ExtractionStage =
  | 'queued'
  | 'preparing'
  | 'model_analysis'
  | 'parsing'
  | 'compiling'
  | 'semantic_review'
  | 'repairing'
  | 'validating'
  | 'generating_view'
  | 'finalizing'
  | 'completed'
  | 'failed'

export interface ExtractionProgressEvent {
  stage: ExtractionStage
  message: string
  progress: number
  level: 'info' | 'warning' | 'error'
  created_at: string
}

export interface ExtractionTaskItem {
  image_id: string
  filename: string
  status: ImageTaskStatus
  result_id: string | null
  error: string | null
  diagnostic_id: string | null
  diagnostics: ExtractionDiagnostic[]
  stage: ExtractionStage
  stage_progress: number
  events: ExtractionProgressEvent[]
}

export interface ExtractionDiagnostic {
  code: string
  repair_owner: 'compiler' | 'model' | 'fatal'
  message: string
  final_path: string
  source_pointer: string | null
  field_id?: string
  style_id?: string
  evidence_id?: string
  region?: string
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
  style_candidates: string[]
  summary: string | null
}

export interface DesignDnaResult {
  id: string
  view: 'business' | 'detail'
  content: Record<string, unknown>
}
