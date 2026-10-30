import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { deleteUploadedImage, fetchModels, fetchUploadedImages, uploadImages } from '@/api/dna'
import {
  createD02Extraction,
  fetchDnaPreparation,
  fetchD02Extraction,
  fetchD02Result,
  fetchD02Results,
} from '@/api/dnaV2'
import type { ModelInfo, UploadedImage } from '@/types/dna'
import type { PreparedCoverage, PreparedDnaResult, PreparedResultSummary, D02Task } from '@/types/dnaV2'

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
  const results = ref<PreparedResultSummary[]>([])
  const activeResultId = ref<string | null>(null)
  const result = ref<PreparedDnaResult | null>(null)
  const loadingResult = ref(false)
  const preparation = ref<PreparedCoverage | null>(null)
  let resultRequest = 0
  const taskRunning = computed(() => currentTask.value !== null && !terminal.has(currentTask.value.status))

  async function initialize() {
    const [uploaded, saved, coverage, configuredModels] = await Promise.all([
      fetchUploadedImages(), fetchD02Results(), fetchDnaPreparation(), fetchModels(),
    ])
    models.value = coverage.available_models?.length ? coverage.available_models : configuredModels
    images.value = uploaded
    results.value = saved
    preparation.value = coverage
    const defaultModel = coverage.default_model || 'gemini-3.8-flash'
    selectedModelId.value = models.value.find((model) => model.id === defaultModel)?.id ?? models.value[0]?.id ?? ''
    prompt.value = ''
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
      // Skill 的事实提取规则保持冻结，模型选择不允许顺带注入额外 Prompt。
      prompt: '',
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
    const [saved, coverage] = await Promise.all([fetchD02Results(), fetchDnaPreparation()])
    results.value = saved
    preparation.value = coverage
    if (!results.value.some((item) => item.id === activeResultId.value)) {
      result.value = null
      activeResultId.value = null
    }
  }

  async function selectResult(resultId: string) {
    const request = ++resultRequest
    activeResultId.value = resultId
    result.value = null
    loadingResult.value = true
    try {
      const saved = await fetchD02Result(resultId)
      // 连续切换图片时只接收最后一次请求，避免慢响应覆盖当前对象。
      if (request === resultRequest) result.value = saved
    } finally {
      if (request === resultRequest) loadingResult.value = false
    }
  }

  return {
    models, images, selectedImageIds, selectedModelId, prompt, uploading, deletingImageIds,
    currentTask, taskRunning, results, activeResultId, result, loadingResult, preparation,
    initialize, addImages, toggleImage, selectAllImages, clearSelectedImages,
    removeImage, startExtraction, refreshResults, selectResult,
  }
})
