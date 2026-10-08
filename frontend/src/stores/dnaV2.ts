import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { deleteUploadedImage, fetchUploadedImages, uploadImages } from '@/api/dna'
import {
  createD02Extraction,
  deleteD02Result,
  fetchD02PptBatch,
  fetchD02Extraction,
  fetchD02Result,
  fetchD02Results,
} from '@/api/dnaV2'
import type { ModelInfo, UploadedImage } from '@/types/dna'
import type { D02PptBatch, D02Result, D02ResultSummary, D02Task } from '@/types/dnaV2'

const terminal = new Set(['completed', 'partial', 'failed'])
const delay = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

export const useDnaV2Store = defineStore('dna-v2', () => {
  const models = ref<ModelInfo[]>([])
  const images = ref<UploadedImage[]>([])
  const selectedImageIds = ref<string[]>([])
  const selectedModelId = ref('')
  const prompt = ref('')
  const uploading = ref(false)
  const deletingImageIds = ref<string[]>([])
  const currentTask = ref<D02Task | null>(null)
  const results = ref<D02ResultSummary[]>([])
  const activeResultId = ref<string | null>(null)
  const result = ref<D02Result | null>(null)
  const loadingResult = ref(false)
  const deletingResultIds = ref<string[]>([])
  const pptBatch = ref<D02PptBatch | null>(null)
  const taskRunning = computed(() => currentTask.value !== null && !terminal.has(currentTask.value.status))

  async function initialize() {
    const [uploaded, saved] = await Promise.all([
      fetchUploadedImages(), fetchD02Results(),
    ])
    models.value = [{ id: 'gpt-6-sol', name: 'gpt-6-sol · 冻结 Sol R5', model_provider: 'openai' }]
    images.value = uploaded
    results.value = saved
    selectedModelId.value = 'gpt-6-sol'
    prompt.value = ''
    if (!activeResultId.value && saved.length) await selectResult(saved[0].id)
  }

  async function addImages(files: File[]) {
    if (!files.length) return
    uploading.value = true
    try {
      const uploaded = await uploadImages(files)
      images.value = [...uploaded, ...images.value]
      selectedImageIds.value = [...new Set([...selectedImageIds.value, ...uploaded.map((image) => image.id)])]
    } finally {
      uploading.value = false
    }
  }

  function toggleImage(imageId: string) {
    selectedImageIds.value = selectedImageIds.value.includes(imageId)
      ? selectedImageIds.value.filter((id) => id !== imageId)
      : [...selectedImageIds.value, imageId]
  }

  function selectAllImages() { selectedImageIds.value = images.value.map((image) => image.id) }
  function clearSelectedImages() { selectedImageIds.value = [] }

  async function removeImage(imageId: string) {
    deletingImageIds.value.push(imageId)
    try {
      await deleteUploadedImage(imageId)
      images.value = images.value.filter((image) => image.id !== imageId)
      selectedImageIds.value = selectedImageIds.value.filter((id) => id !== imageId)
    } finally {
      deletingImageIds.value = deletingImageIds.value.filter((id) => id !== imageId)
    }
  }

  async function startExtraction() {
    currentTask.value = await createD02Extraction({
      image_ids: selectedImageIds.value,
      model_id: selectedModelId.value,
      prompt: prompt.value,
    })
    const taskId = currentTask.value.id
    while (currentTask.value && !terminal.has(currentTask.value.status)) {
      await delay(1200)
      currentTask.value = await fetchD02Extraction(taskId)
    }
    await refreshResults()
    const latest = currentTask.value?.items.find((item) => item.result_id)?.result_id
    if (latest) await selectResult(latest)
  }

  async function refreshResults() {
    results.value = await fetchD02Results()
    if (!results.value.some((item) => item.id === activeResultId.value)) {
      result.value = null
      activeResultId.value = null
      if (results.value.length) await selectResult(results.value[0].id)
    }
  }

  async function refreshPptBatch() {
    try {
      const next = await fetchD02PptBatch()
      const previousCompleted = pptBatch.value?.counts.completed ?? 0
      pptBatch.value = next
      if (next.counts.completed !== previousCompleted) await refreshResults()
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status
      if (status !== 404) throw error
    }
  }

  async function selectResult(resultId: string) {
    loadingResult.value = true
    try {
      result.value = await fetchD02Result(resultId)
      activeResultId.value = resultId
    } finally {
      loadingResult.value = false
    }
  }

  async function removeResult(resultId: string) {
    deletingResultIds.value.push(resultId)
    try {
      await deleteD02Result(resultId)
      await refreshResults()
    } finally {
      deletingResultIds.value = deletingResultIds.value.filter((id) => id !== resultId)
    }
  }

  return {
    models, images, selectedImageIds, selectedModelId, prompt, uploading, deletingImageIds,
    currentTask, taskRunning, results, activeResultId, result, loadingResult, deletingResultIds, pptBatch,
    initialize, addImages, toggleImage, selectAllImages, clearSelectedImages,
    removeImage, startExtraction, refreshResults, refreshPptBatch, selectResult, removeResult,
  }
})
