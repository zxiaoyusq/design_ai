/** 用研聚合静态快照只承载展示字段；图片偏好、摘录和分组都可回查源记录。 */
/** 源图片 ID 对应的本地展示资源与本次样本中的喜欢人数。 */
export interface ResearchImage {
  id: string
  src: string
  enjoyedBy: number
}

/** 问答分析和需求文本来自不同源字段，不将分析文本冒充逐字访谈。 */
export interface ResearchExcerpt {
  id: string
  kind: '问答分析' | '需求记录'
  question: string
  answer: string
}

/** 只保存页面使用的画像和少量源记录，完整内容仍以 data 目录为准。 */
export interface ResearchUser {
  id: string
  bid: string
  cohortId: string
  country: string
  age: number | null
  gender: string
  profession: string
  phoneBrand: string
  enjoyCount: number
  dislikeCount: number
  images: string[]
  excerpts: ResearchExcerpt[]
}

/** 按 ENJOY 图片共现划分的演示人群组，不代表视觉风格的语义聚类。 */
export interface ResearchCohort {
  id: string
  name: string
  country: string
  userIds: string[]
  enjoyCount: number
  imageIds: string[]
  imageVotes: Record<string, number>
  /** 每格统计本组有多少不同用户喜欢对应图集中的任意图片。 */
  overlaps: number[]
}
