/** PPT 提取结果中的图片态度；参考图不能视作用户喜欢。 */
export type ResearchImageEmotion = 'ENJOY' | 'DISLIKE' | 'REFERENCE'

/** 用户列表摘要，待人工确认的提取结果仍可查看。 */
export interface ResearchUserSummary {
  id: string
  name: string
  profile: Record<string, unknown>
  sourceFile: string
  sourceSha256: string
  recordCount: number
  enjoyCount: number
  dislikeCount: number
  referenceCount: number
  missingImageCount: number
  status: 'ready' | 'needs_review'
  createdAt: string
}

/** 完整问答与 PPT 来源定位，不在展示层截断答案。 */
export interface ResearchRecord {
  id: string
  section: string
  question: string
  answer: string
  /** 新上传 PPT 可保留原语言回答；旧资料没有原文时不补造。 */
  originalAnswer?: string
  sourceSlide: number | null
  sourceFile: string
  imageIds: string[]
  sourceKind: 'ppt'
  /** 区分回答、品牌印象、个人愿望与举例，避免将展示内容误读为偏好。 */
  sourceRole?: 'respondent_answer' | 'brand_impression' | 'personal_wish' | 'example'
}

/** 图片可以只有编号和证据而缺少原图；此时 url 为 null。 */
export interface ResearchImage {
  id: string
  code: string
  emotion: ResearchImageEmotion
  url: string | null
  sourceSlide: number | null
  questionId: string | null
  description: string
  /** 原调研记录明确关联的副本，保留其与 PPT 原件不同的来源。 */
  recovery?: { label: string; sha256: string; originalSha256?: string; sourceImageId?: string }
  evidenceScope: string
  status: string
}

/** 用户详情同时携带提取溯源和需要人工复核的提示。 */
export interface ResearchUserDetail extends ResearchUserSummary {
  records: ResearchRecord[]
  images: ResearchImage[]
  provenance: Record<string, unknown>
  warnings: string[]
}

/** needs_review 表示提取完成，completed 表示用户已确认当前文本与图片标注。 */
export interface ResearchImportTask {
  id: string
  userId: string
  name: string
  filename: string
  status: 'queued' | 'extracting' | 'needs_review' | 'completed' | 'failed'
  stage: string
  message: string
  totalSlides: number
  processedSlides: number
  model: string
  error?: string
  createdAt: string
  updatedAt: string
}
