import { http } from './http'
import type { ExtractionRequest } from '@/types/dna'
import type { D02PptBatch, D02Result, D02ResultSummary, D02Task } from '@/types/dnaV2'

export async function fetchD02PptBatch() {
  const { data } = await http.get<D02PptBatch>('/dna-v2/batches/ppt-enjoy')
  return data
}

export async function createD02Extraction(request: ExtractionRequest) {
  const { data } = await http.post<D02Task>('/dna-v2/extractions', request)
  return data
}

export async function fetchD02Extraction(taskId: string) {
  const { data } = await http.get<D02Task>(`/dna-v2/extractions/${taskId}`)
  return data
}

export async function fetchD02Results() {
  const { data } = await http.get<D02ResultSummary[]>('/dna-v2/results')
  return data
}

export async function fetchD02Result(resultId: string) {
  const { data } = await http.get<D02Result>(`/dna-v2/results/${resultId}`)
  return data
}

export async function deleteD02Result(resultId: string) {
  await http.delete(`/dna-v2/results/${resultId}`)
}
