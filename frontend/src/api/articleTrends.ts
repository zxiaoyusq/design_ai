import { http } from './http'
import type { ArticleImportPreview, ArticleImportResult, ArticlePage, ArticleRegionJob, TrendArticle, TrendCatalog, TrendClusterTask, TrendFilters, TrendModel, TrendPreview, TrendSelection } from '@/types/articleTrends'

const base = '/article-trends'

function workbookForm(file: File, selectionDigest?: string, regionModelId?: string) {
  const form = new FormData()
  form.append('file', file)
  if (selectionDigest) form.append('selection_digest', selectionDigest)
  if (regionModelId) form.append('region_model_id', regionModelId)
  return form
}

export const articleTrendsApi = {
  catalog: async () => (await http.get<TrendCatalog>(`${base}/catalog`)).data,
  articles: async (params: TrendFilters & { page: number; page_size: number }) => (await http.get<ArticlePage>(`${base}/articles`, { params })).data,
  article: async (id: string) => (await http.get<TrendArticle>(`${base}/articles/${encodeURIComponent(id)}`)).data,
  previewImport: async (file: File) => (await http.post<ArticleImportPreview>(`${base}/imports/preview`, workbookForm(file))).data,
  importWorkbook: async (file: File, digest: string, model: string) => (await http.post<ArticleImportResult>(`${base}/imports`, workbookForm(file, digest, model))).data,
  latestRegionJob: async () => (await http.get<ArticleRegionJob | null>(`${base}/region-jobs/latest`)).data,
  regionJob: async (id: string) => (await http.get<ArticleRegionJob>(`${base}/region-jobs/${id}`)).data,
  retryRegionJob: async (id: string) => (await http.post<ArticleRegionJob>(`${base}/region-jobs/${id}/retry`)).data,
  models: async () => (await http.get<{ models: TrendModel[] }>('/llm/models')).data.models,
  preview: async (request: TrendSelection) => (await http.post<TrendPreview>(`${base}/preview`, request)).data,
  start: async (request: TrendSelection & { selection_digest: string; confirm: true }) => (await http.post<TrendClusterTask>(`${base}/tasks`, request)).data,
  tasks: async () => (await http.get<TrendClusterTask[]>(`${base}/tasks`)).data,
  history: async () => (await http.get<TrendClusterTask[]>(`${base}/history`)).data,
  historicalTask: async (id: string) => (await http.get<TrendClusterTask>(`${base}/history/${encodeURIComponent(id)}`)).data,
  task: async (id: string) => (await http.get<TrendClusterTask>(`${base}/tasks/${encodeURIComponent(id)}`)).data,
  resume: async (id: string, max_calls: number) => (await http.post<TrendClusterTask>(`${base}/tasks/${encodeURIComponent(id)}/resume`, { max_calls })).data,
}
