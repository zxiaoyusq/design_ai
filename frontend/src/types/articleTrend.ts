/** 文章趋势为源表静态快照，图片 URL 指向构建时打包的已下载原图。 */
export interface ArticleTrend {
  id: string
  sourceRow: number
  title: string
  originalTitle: string | null
  summary: string | null
  sourceUrl: string | null
  detailUrl: string | null
  releaseDate: string
  category: string | null
  subcategories: string[]
  tags: string[]
  images: string[]
}
