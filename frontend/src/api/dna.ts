import { http } from './http'
import type {
  DesignDnaResult,
  DesignDnaResultSummary,
  ExtractionRequest,
  ExtractionTask,
  ModelListResponse,
  UploadedImage,
} from '@/types/dna'

export async function fetchModels() {
  const { data } = await http.get<ModelListResponse>('/llm/models')
  return data.models
}

export async function fetchUploadedImages() {
  const { data } = await http.get<UploadedImage[]>('/dna/images')
  return data
}

export async function uploadImages(files: File[]) {
  const form = new FormData()
  files.forEach((file) => {
    form.append('files', file, file.name)
    form.append('paths', file.webkitRelativePath || file.name)
  })
  const { data } = await http.post<UploadedImage[]>('/dna/images', form)
  return data
}

export async function deleteUploadedImage(imageId: string) {
  await http.delete(`/dna/images/${imageId}`)
}

export async function createExtraction(request: ExtractionRequest) {
  const { data } = await http.post<ExtractionTask>('/dna/extractions', request)
  return data
}

export async function fetchExtraction(taskId: string) {
  const { data } = await http.get<ExtractionTask>(`/dna/extractions/${taskId}`)
  return data
}

export async function fetchResults() {
  const { data } = await http.get<DesignDnaResultSummary[]>('/dna/results')
  return data
}

export async function fetchResult(resultId: string, view: 'business' | 'detail') {
  const { data } = await http.get<DesignDnaResult>(`/dna/results/${resultId}`, {
    params: { view },
  })
  return data
}

export async function deleteDesignDnaResult(resultId: string) {
  await http.delete(`/dna/results/${resultId}`)
}
