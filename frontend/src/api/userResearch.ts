import { http } from './http'
import type { ResearchImportTask, ResearchUserDetail, ResearchUserSummary } from '@/types/researchIntake'

/** 用研接口沿用全站 API 前缀；signal 用于页面卸载与切换时取消请求。 */
export async function fetchResearchUsers(signal?: AbortSignal) {
  return (await http.get<{ users: ResearchUserSummary[] }>('/user-research/users', { signal })).data.users
}

export async function fetchResearchUser(id: string, signal?: AbortSignal) {
  return (await http.get<ResearchUserDetail>(`/user-research/users/${encodeURIComponent(id)}`, { signal })).data
}

export async function fetchResearchTasks(signal?: AbortSignal) {
  return (await http.get<{ tasks: ResearchImportTask[] }>('/user-research/tasks', { signal })).data.tasks
}

export async function fetchResearchTask(id: string, signal?: AbortSignal) {
  return (await http.get<ResearchImportTask>(`/user-research/tasks/${encodeURIComponent(id)}`, { signal })).data
}

/** 只提交 PPT 与提取参数；结果写入确认由独立 confirm 接口执行。 */
export async function importResearchPpt(file: File, name: string, model: string, signal?: AbortSignal) {
  const form = new FormData()
  form.append('file', file, file.name)
  form.append('name', name)
  form.append('model', model)
  return (await http.post<ResearchImportTask>('/user-research/imports', form, { signal, timeout: 180_000 })).data
}

export async function confirmResearchTask(id: string, signal?: AbortSignal) {
  return (await http.post<ResearchImportTask>(`/user-research/tasks/${encodeURIComponent(id)}/confirm`, undefined, { signal })).data
}
