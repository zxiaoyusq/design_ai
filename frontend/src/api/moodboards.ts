import { http } from './http'
import type { ClusteringCatalog, ClusteringPreview, ClusteringRequest, ClusteringTask, MoodboardCatalog, MoodboardRequest, MoodboardResult, MoodboardTask, SavedMoodboardCatalog, SavedMoodboardResult } from '@/types/moodboards'

export async function fetchMoodboardCatalog() {
  return (await http.get<MoodboardCatalog>('/moodboards/catalog')).data
}

export async function createMoodboardTask(request: MoodboardRequest) {
  return (await http.post<MoodboardTask>('/moodboards/tasks', request)).data
}

export async function fetchMoodboardTasks() {
  return (await http.get<MoodboardTask[]>('/moodboards/tasks')).data
}

export async function fetchMoodboardTask(id: string) {
  return (await http.get<MoodboardTask>(`/moodboards/tasks/${encodeURIComponent(id)}`)).data
}

/** 继续失败任务时沿用已冻结输入，服务端复用已经完成的步骤。 */
export async function resumeMoodboardTask(id: string) {
  return (await http.post<MoodboardTask>(`/moodboards/tasks/${encodeURIComponent(id)}/resume`, { confirmed: true })).data
}

export function moodboardDownloadUrl(id: string) {
  return `${http.defaults.baseURL}/moodboards/tasks/${encodeURIComponent(id)}/download`
}

/** 读取已保存的原生 v2 板并复放验收；仅展示，不调用模型。 */
export async function previewNativeMoodboard(runPath: string) {
  return (await http.post<MoodboardResult>('/moodboards/native-results/preview', { run_path: runPath })).data
}

export async function fetchClusteringCatalog() {
  return (await http.get<ClusteringCatalog>('/moodboards/clustering/catalog')).data
}

export async function previewClusteringInput(sourceResultId: string, directionIds: string[]) {
  // 大图池需要逐图核 SHA 与旧 DNA 身份；仅本链路延长读取等待，不改变其他页面超时。
  return (await http.post<ClusteringPreview>('/moodboards/clustering/preview', { source_result_id: sourceResultId, direction_ids: directionIds }, { timeout: 180000 })).data
}

export async function createClusteringTask(request: ClusteringRequest) {
  return (await http.post<ClusteringTask>('/moodboards/clustering/tasks', request, { timeout: 180000 })).data
}

export async function fetchClusteringTasks() {
  return (await http.get<ClusteringTask[]>('/moodboards/clustering/tasks')).data
}

export async function fetchClusteringTask(id: string) {
  return (await http.get<ClusteringTask>(`/moodboards/clustering/tasks/${encodeURIComponent(id)}`)).data
}

export function clusteringDownloadUrl(id: string) {
  return `${http.defaults.baseURL}/moodboards/clustering/tasks/${encodeURIComponent(id)}/download`
}

/** 读取已登记的 Skill 交付目录；不创建任务或重新聚类。 */
export async function fetchSavedMoodboards() {
  return (await http.get<SavedMoodboardCatalog>('/moodboards/clustering/saved-results')).data
}

export async function fetchSavedMoodboard(id: string) {
  return (await http.get<SavedMoodboardResult>(`/moodboards/clustering/saved-results/${encodeURIComponent(id)}`)).data
}
