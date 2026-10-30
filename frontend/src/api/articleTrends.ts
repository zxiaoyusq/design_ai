import { http } from './http'
import type { ArticlePage, TrendArticle, TrendCatalog, TrendClusterTask, TrendFilters, TrendModel, TrendPreview, TrendSelection } from '@/types/articleTrends'

const base = '/article-trends'

export const articleTrendsApi = {
  catalog: async () => (await http.get<TrendCatalog>(`${base}/catalog`)).data,
  articles: async (params: TrendFilters & { page: number; page_size: number }) => (await http.get<ArticlePage>(`${base}/articles`, { params })).data,
  article: async (id: string) => (await http.get<TrendArticle>(`${base}/articles/${encodeURIComponent(id)}`)).data,
  models: async () => (await http.get<{ models: TrendModel[] }>('/llm/models')).data.models,
  preview: async (request: TrendSelection) => (await http.post<TrendPreview>(`${base}/preview`, request)).data,
  start: async (request: TrendSelection & { selection_digest: string; confirm: true }) => (await http.post<TrendClusterTask>(`${base}/tasks`, request)).data,
  tasks: async () => (await http.get<TrendClusterTask[]>(`${base}/tasks`)).data,
  history: async () => (await http.get<TrendClusterTask[]>(`${base}/history`)).data,
  historicalTask: async (id: string) => (await http.get<TrendClusterTask>(`${base}/history/${encodeURIComponent(id)}`)).data,
  task: async (id: string) => (await http.get<TrendClusterTask>(`${base}/tasks/${encodeURIComponent(id)}`)).data,
  resume: async (id: string, max_calls: number) => (await http.post<TrendClusterTask>(`${base}/tasks/${encodeURIComponent(id)}/resume`, { max_calls })).data,
}
