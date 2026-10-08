import { http } from './http'
import type { MoodboardCatalog, MoodboardRequest, MoodboardResult, MoodboardTask } from '@/types/moodboards'

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
