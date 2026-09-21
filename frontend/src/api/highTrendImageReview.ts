import { http } from './http'
import type { HighTrendImageReview, ReviewCollection } from '@/types/highTrendImageReview'

function reviewPath(taskId: string) {
  return `/high-trends/tasks/${encodeURIComponent(taskId)}/image-review`
}

/** 首次复制当前结果图片，已有整理档案则沿用保存的选择。 */
export async function openImageReview(taskId: string, collection: ReviewCollection = 'result') {
  return (await http.post<HighTrendImageReview>(reviewPath(taskId), undefined, { params: { collection }, timeout: 120_000 })).data
}

export async function fetchImageReview(taskId: string, collection: ReviewCollection = 'result') {
  return (await http.get<HighTrendImageReview>(reviewPath(taskId), { params: { collection } })).data
}

export async function saveImageReview(taskId: string, revision: number, imageIds: string[], retained: boolean, collection: ReviewCollection = 'result') {
  return (await http.patch<HighTrendImageReview>(reviewPath(taskId), { revision, image_ids: imageIds, retained }, { params: { collection } })).data
}

/** 导出服务器已保存的保留集，和页面当前的搜索条件无关。 */
export async function downloadImageReview(taskId: string, format: 'zip' | 'json', collection: ReviewCollection = 'result') {
  return (await http.get<Blob>(`${reviewPath(taskId)}/download`, {
    params: { format, collection }, responseType: 'blob', timeout: 120_000,
  })).data
}
