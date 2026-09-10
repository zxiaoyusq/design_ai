import { http } from './http'
import type { HighTrendCatalog, HighTrendPreview, HighTrendRequest, HighTrendTask } from '@/types/highTrends'

export async function fetchTrendCatalog() {
  return (await http.get<HighTrendCatalog>('/high-trends/catalog')).data
}

export async function previewTrends(request: HighTrendRequest) {
  return (await http.post<HighTrendPreview>('/high-trends/preview', request)).data
}

export async function createTrendTask(request: HighTrendRequest) {
  return (await http.post<HighTrendTask>('/high-trends/tasks', request)).data
}

export async function fetchTrendTasks() {
  return (await http.get<HighTrendTask[]>('/high-trends/tasks')).data
}

export async function fetchTrendTask(id: string) {
  return (await http.get<HighTrendTask>(`/high-trends/tasks/${encodeURIComponent(id)}`)).data
}

export async function resumeTrendTask(id: string, max_calls: number) {
  return (await http.post<HighTrendTask>(`/high-trends/tasks/${encodeURIComponent(id)}/resume`, { max_calls })).data
}

export function trendDownloadUrl(id: string, format: 'json' | 'markdown') {
  return `${http.defaults.baseURL}/high-trends/tasks/${encodeURIComponent(id)}/download?format=${format}`
}
