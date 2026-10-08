import { http } from './http'
import type { TrendQualityDecision, TrendQualityReview, TrendQualityReviewQuery, TrendQualitySaveResult } from '@/types/trendQualityReview'

/** 读取服务端保存的人工审核状态及当前筛选页。 */
export async function fetchTrendQualityReview(params: TrendQualityReviewQuery) {
  return (await http.get<TrendQualityReview>('/trend-quality/review', { params })).data
}

/** 只更新人工选择；null 恢复未审核，不将模型判定填入人工结果。 */
export async function saveTrendQualityReview(revision: number, imageIds: string[], decision: TrendQualityDecision | null) {
  return (await http.patch<TrendQualitySaveResult>('/trend-quality/review', {
    revision, image_ids: imageIds, decision,
  })).data
}

/** 导出服务器已保存的人工选择，与模型分类和当前页无关。 */
export async function downloadTrendQualityReview(selection: TrendQualityDecision | 'all') {
  return (await http.get<Blob>('/trend-quality/review/download', {
    params: { selection }, responseType: 'blob', timeout: 120_000,
  })).data
}
