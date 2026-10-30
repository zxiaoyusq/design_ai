import { http } from './http'
import type { HighTrendInputs, HighTrendCatalog, HighTrendPreview, HighTrendRequest, HighTrendTask, NativeHighTrendImagePage } from '@/types/highTrends'

export const NATIVE_HIGH_TREND_RESULT_ID = 'sol61-native-v2-20261006'

export async function fetchNativeHighTrendResult(id = NATIVE_HIGH_TREND_RESULT_ID) {
  return (await http.get<HighTrendTask>(`/high-trends/native-results/${encodeURIComponent(id)}`)).data
}

export async function fetchNativeHighTrendImages(id: string, directionId: string, page: number, scope: 'all' | 'cited' | 'associated' = 'all') {
  return (await http.get<NativeHighTrendImagePage>(`/high-trends/native-results/${encodeURIComponent(id)}/directions/${encodeURIComponent(directionId)}/images`, {
    params: { page, page_size: 12, scope },
  })).data
}

export function nativeHighTrendDownloadUrl(id: string, format: 'json' | 'selection' | 'sources' | 'markdown') {
  return `${http.defaults.baseURL}/high-trends/native-results/${encodeURIComponent(id)}/download?format=${format}`
}

export async function fetchTrendInputs() {
  return (await http.get<HighTrendInputs>('/high-trends/inputs')).data
}

export async function fetchTrendCatalog(dataset: HighTrendRequest['dataset'] = 'original') {
  return (await http.get<HighTrendCatalog>('/high-trends/catalog', { params: { dataset } })).data
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

export function trendDownloadUrl(id: string, format: 'json' | 'markdown' | 'images_markdown' | 'performance' | 'handoff' | 'sources') {
  return `${http.defaults.baseURL}/high-trends/tasks/${encodeURIComponent(id)}/download?format=${format}`
}
