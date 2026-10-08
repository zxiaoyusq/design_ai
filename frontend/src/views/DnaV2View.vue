<script setup lang="ts">
import { computed, h, onMounted, onUnmounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { DeleteOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'

import ExtractionComposer from '@/components/ExtractionComposer.vue'
import ImageUploadPanel from '@/components/ImageUploadPanel.vue'
import PrismDnaResultViewer from '@/components/PrismDnaResultViewer.vue'
import PrismPptBatchPanel from '@/components/PrismPptBatchPanel.vue'
import { useDnaV2Store } from '@/stores/dnaV2'

const store = useDnaV2Store()
const modelName = computed(() => store.models.find((model) => model.id === store.selectedModelId)?.name ?? '')
let batchTimer: number | undefined

function errorText(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail ?? fallback
  }
  return error instanceof Error ? error.message : fallback
}

onMounted(async () => {
  try {
    await store.initialize()
    await store.refreshPptBatch()
    batchTimer = window.setInterval(() => { void store.refreshPptBatch() }, 15000)
  } catch (error) { message.error(errorText(error, 'D02 工作台初始化失败')) }
})
onUnmounted(() => { if (batchTimer !== undefined) window.clearInterval(batchTimer) })

async function upload(files: File[]) {
  try { await store.addImages(files); message.success(`已加入 ${files.length} 张图片`) }
  catch (error) { message.error(errorText(error, '上传失败')) }
}

function removeImage(imageId: string) {
  const image = store.images.find((item) => item.id === imageId)
  if (!image) return
  Modal.confirm({
    title: '删除这张素材？', icon: h(DeleteOutlined),
    content: `“${image.filename}”将从共享素材库移除，已完成的结果会保留。`,
    okText: '删除素材', okType: 'danger', cancelText: '取消',
    async onOk() {
      try { await store.removeImage(imageId) } catch (error) { message.error(errorText(error, '删除失败')) }
    },
  })
}

function removeResult(resultId: string) {
  Modal.confirm({
    title: '删除这条 D02 候选结果？', icon: h(DeleteOutlined),
    content: '原始模型回复、独立复核记录及追溯信息会一并删除。',
    okText: '删除结果', okType: 'danger', cancelText: '取消',
    async onOk() {
      try { await store.removeResult(resultId) } catch (error) { message.error(errorText(error, '结果删除失败')) }
    },
  })
}

function confirmExtraction() {
  Modal.confirm({
    title: '开始 D02 图片 DNA 提取？', icon: h(SafetyCertificateOutlined),
    content: `图片 ${store.selectedImageIds.length} 张；模型 ${modelName.value}。将按 Sol R5 新版规则提取可见 ID/CMF 特征，并对困难项至多定点复核一次。`,
    okText: '确认并开始', cancelText: '再检查一下',
    onOk() { void runExtraction() },
  })
}

async function runExtraction() {
  try {
    await store.startExtraction()
    if (store.currentTask?.status === 'completed') message.success('D02 候选提取完成，请检查校验状态')
    else message.warning('任务已结束，请检查失败图片')
  } catch (error) { message.error(errorText(error, 'D02 提取失败')) }
}

async function selectResult(resultId: string) {
  try { await store.selectResult(resultId) } catch (error) { message.error(errorText(error, '结果读取失败')) }
}
</script>

<template>
  <div class="app-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页">
        <span class="brand-mark"><span></span></span>
        <span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span>
      </RouterLink>
      <nav>
        <RouterLink to="/">DNA 提取</RouterLink>
        <RouterLink class="active" to="/dna-v2">DNA 提取 V2</RouterLink>
        <RouterLink to="/article-trends">趋势洞察</RouterLink>
        <RouterLink to="/high-trends">高潜趋势</RouterLink>
        <RouterLink to="/moodboards">情绪版生成</RouterLink>
        <RouterLink to="/projects">我的项目</RouterLink>
      </nav>
      <div class="system-state"><span></span> Agent 服务在线</div>
    </header>
    <main id="top">
      <section class="hero">
        <div class="hero-badge">D02 · SOL R5 IMAGE DNA</div>
        <p>使用冻结 Sol R5 原生提取可见位置的 ID/CMF 特征；历史 R17 和其他模型结果仍可在下方查看。</p>
      </section>
      <section class="flow-strip" aria-label="D02 提取流程">
        <div class="flow-step active"><span>1</span><strong>上传素材</strong></div>
        <div class="flow-step"><span>2</span><strong>核对冻结配置</strong></div>
        <div class="flow-step"><span>3</span><strong>确认并提取</strong></div>
        <div class="flow-step"><span>4</span><strong>查看候选结果</strong></div>
      </section>
      <div id="extract" class="workspace-grid">
        <ImageUploadPanel
          :images="store.images" :selected-ids="store.selectedImageIds"
          :uploading="store.uploading" :deleting-ids="store.deletingImageIds"
          @upload="upload" @toggle="store.toggleImage" @select-all="store.selectAllImages"
          @clear="store.clearSelectedImages" @delete="removeImage"
        />
        <ExtractionComposer
          :models="store.models" :selected-count="store.selectedImageIds.length"
          :selected-model-id="store.selectedModelId" :prompt="store.prompt"
          :task="store.currentTask" :running="store.taskRunning"
          skill-label="D02 · Sol R5 图片 DNA" concurrency-label="最多同时 2 张"
          :frozen-configuration="true" executor-label="Codex CLI"
          @update:selected-model-id="store.selectedModelId = $event"
          @update:prompt="store.prompt = $event" @start="confirmExtraction"
        />
      </div>
      <div id="results">
        <PrismPptBatchPanel
          :batch="store.pptBatch"
          @select="selectResult"
          @refresh="store.refreshPptBatch"
        />
        <PrismDnaResultViewer
          :results="store.results" :active-result-id="store.activeResultId"
          :result="store.result" :loading="store.loadingResult" :deleting-ids="store.deletingResultIds"
          @select="selectResult" @refresh="store.refreshResults" @delete="removeResult"
        />
      </div>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>D02 Sol R5 · 冻结提取</span></footer>
  </div>
</template>
