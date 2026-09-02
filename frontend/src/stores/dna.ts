import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createExtraction,
  deleteDesignDnaResult,
  deleteUploadedImage,
  fetchExtraction,
  fetchModels,
  fetchResult,
  fetchResults,
  fetchUploadedImages,
  uploadImages,
} from '@/api/dna'
import type {
  DesignDnaResultSummary,
  ExtractionTask,
  ModelInfo,
  UploadedImage,
} from '@/types/dna'

const TERMINAL_TASK_STATUS = new Set(['completed', 'partial', 'failed'])

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

export const useDnaStore = defineStore('dna', () => {
  const models = ref<ModelInfo[]>([])
  const images = ref<UploadedImage[]>([])
  const selectedImageIds = ref<string[]>([])
  const selectedModelId = ref('')
  const prompt = ref('')
  const uploading = ref(false)
  const deletingImageIds = ref<string[]>([])
  const currentTask = ref<ExtractionTask | null>(null)
  const results = ref<DesignDnaResultSummary[]>([])
  const activeResultId = ref<string | null>(null)
  const resultView = ref<'business' | 'detail'>('business')
  const resultContent = ref<Record<string, unknown> | null>(null)
  const loadingResult = ref(false)
  const deletingResultIds = ref<string[]>([])

  const selectedImages = computed(() =>
    images.value.filter((image) => selectedImageIds.value.includes(image.id)),
  )
  const taskRunning = computed(
    () => currentTask.value !== null && !TERMINAL_TASK_STATUS.has(currentTask.value.status),
  )

  async function initialize() {
    const [availableModels, uploaded, completedResults] = await Promise.all([
      fetchModels(),
      fetchUploadedImages(),
      fetchResults(),
    ])
    models.value = availableModels
    images.value = uploaded
    results.value = completedResults
    if (!selectedModelId.value && models.value.length) {
      selectedModelId.value = models.value[0].id
    }
    if (!activeResultId.value && results.value.length) {
      await selectResult(results.value[0].id, 'business')
    }
  }

  async function addImages(files: File[]) {
    if (!files.length) return
    uploading.value = true
    try {
      const uploaded = await uploadImages(files)
      images.value = [...uploaded, ...images.value]
      selectedImageIds.value = Array.from(
        new Set([...selectedImageIds.value, ...uploaded.map((image) => image.id)]),
      )
    } finally {
      uploading.value = false
    }
  }

  function toggleImage(imageId: string) {
    selectedImageIds.value = selectedImageIds.value.includes(imageId)
      ? selectedImageIds.value.filter((id) => id !== imageId)
      : [...selectedImageIds.value, imageId]
  }

  function selectAllImages() {
    selectedImageIds.value = images.value.map((image) => image.id)
  }

  function clearSelectedImages() {
    selectedImageIds.value = []
  }

  async function removeImage(imageId: string) {
    deletingImageIds.value = [...deletingImageIds.value, imageId]
    try {
      await deleteUploadedImage(imageId)
      images.value = images.value.filter((image) => image.id !== imageId)
      selectedImageIds.value = selectedImageIds.value.filter((id) => id !== imageId)
    } finally {
      deletingImageIds.value = deletingImageIds.value.filter((id) => id !== imageId)
    }
  }

  async function startExtraction() {
    currentTask.value = await createExtraction({
      image_ids: selectedImageIds.value,
      model_id: selectedModelId.value,
      prompt: prompt.value,
    })
    await pollTask(currentTask.value.id)
  }

  async function pollTask(taskId: string) {
    while (currentTask.value && !TERMINAL_TASK_STATUS.has(currentTask.value.status)) {
      await wait(1200)
      currentTask.value = await fetchExtraction(taskId)
    }
    results.value = await fetchResults()
    const latestResultId = currentTask.value?.items.find((item) => item.result_id)?.result_id
    if (latestResultId) {
      await selectResult(latestResultId, 'business')
    }
  }

  async function refreshResults() {
    results.value = await fetchResults()
    const activeStillExists = results.value.some(
      (result) => result.id === activeResultId.value,
    )
    if (!activeStillExists && results.value.length) {
      await selectResult(results.value[0].id, 'business')
    } else if (!activeStillExists) {
      activeResultId.value = null
      resultContent.value = null
    }
  }

  async function selectResult(
    resultId: string,
    view: 'business' | 'detail' = resultView.value,
  ) {
    activeResultId.value = resultId
    resultView.value = view
    loadingResult.value = true
    try {
      const result = await fetchResult(resultId, view)
      resultContent.value = result.content
    } finally {
      loadingResult.value = false
    }
  }

  async function setResultView(view: 'business' | 'detail') {
    if (!activeResultId.value) return
    await selectResult(activeResultId.value, view)
  }

  async function removeResult(resultId: string) {
    deletingResultIds.value = [...deletingResultIds.value, resultId]
    try {
      await deleteDesignDnaResult(resultId)
      results.value = results.value.filter((result) => result.id !== resultId)
      if (activeResultId.value === resultId) {
        activeResultId.value = null
        resultContent.value = null
        if (results.value.length) {
          await selectResult(results.value[0].id, 'business')
        }
      }
    } finally {
      deletingResultIds.value = deletingResultIds.value.filter((id) => id !== resultId)
    }
  }

  return {
    models,
    images,
    selectedImageIds,
    selectedImages,
    selectedModelId,
    prompt,
    uploading,
    deletingImageIds,
    currentTask,
    taskRunning,
    results,
    activeResultId,
    resultView,
    resultContent,
    loadingResult,
    deletingResultIds,
    initialize,
    addImages,
    toggleImage,
    selectAllImages,
    clearSelectedImages,
    removeImage,
    startExtraction,
    refreshResults,
    selectResult,
    setResultView,
    removeResult,
  }
})
