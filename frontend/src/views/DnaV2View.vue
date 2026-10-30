<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { DeleteOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'

import ExtractionComposer from '@/components/ExtractionComposer.vue'
import ImageUploadPanel from '@/components/ImageUploadPanel.vue'
import MainNavigation from '@/components/MainNavigation.vue'
import PreparedDnaResultViewer from '@/components/PreparedDnaResultViewer.vue'
import { useDnaV2Store } from '@/stores/dnaV2'

const store = useDnaV2Store()
const modelName = computed(() => store.models.find((model) => model.id === store.selectedModelId)?.name ?? '')
const extractionOpen = ref(false)
const initializing = ref(true)
const initializationError = ref('')

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
  } catch (error) {
    initializationError.value = errorText(error, '设计卡工作台初始化失败')
    message.error(initializationError.value)
  } finally { initializing.value = false }
})

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

function confirmExtraction() {
  Modal.confirm({
    title: '开始设计 DNA 预提取？', icon: h(SafetyCertificateOutlined),
    content: `图片 ${store.selectedImageIds.length} 张；模型 ${modelName.value}。将通过工程 DeepAgents 执行 prism-design-dna-preparation，先复用可核验的可见事实，再提取对象的七组关系、同层风格、设计情绪与限制，每图最多 1 个 ID、2 个 CMF。确认后会发起真实模型请求。`,
    okText: '确认并开始', cancelText: '再检查一下',
    onOk() { void runExtraction() },
  })
}

async function runExtraction() {
  try {
    await store.startExtraction()
    if (store.currentTask?.status === 'completed') message.success('设计卡提取完成，请检查有效对象与限制')
    else message.warning('任务已结束，请检查失败图片')
  } catch (error) { message.error(errorText(error, '设计卡提取失败')) }
}

async function selectResult(resultId: string) {
  try { await store.selectResult(resultId) } catch (error) { message.error(errorText(error, '结果读取失败')) }
}

async function refreshResults() {
  try { await store.refreshResults() } catch (error) { message.error(errorText(error, '结果刷新失败')) }
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
      <MainNavigation />
      <div class="system-state"><span></span> Agent 服务在线</div>
    </header>
    <main id="top">
      <section class="hero preparation-hero">
        <div class="hero-badge">DESIGN DNA PREPARATION</div>
        <div class="preparation-hero-row"><div><h1>DNA提取V2</h1><p>从可见对象出发，理解形态、配色、表面与细节，保留每一项判断的依据。</p></div><a-button type="primary" size="large" @click="extractionOpen = !extractionOpen" data-testid="preparation-extraction-toggle">{{ extractionOpen ? '收起提取工作区' : '提取新图片' }}</a-button></div>
      </section>
      <div v-if="extractionOpen" id="extract" class="workspace-grid preparation-extract">
        <ImageUploadPanel
          :images="store.images" :selected-ids="store.selectedImageIds"
          :uploading="store.uploading" :deleting-ids="store.deletingImageIds"
          description="逐图登记可见对象与代表性局部，每图最多 1 张 ID、2 张 CMF 设计卡；不穷尽全部对象。"
          @upload="upload" @toggle="store.toggleImage" @select-all="store.selectAllImages"
          @clear="store.clearSelectedImages" @delete="removeImage"
        />
        <ExtractionComposer
          :models="store.models" :selected-count="store.selectedImageIds.length"
          :selected-model-id="store.selectedModelId" :prompt="store.prompt"
          :task="store.currentTask" :running="store.taskRunning"
          skill-label="prism-design-dna-preparation" concurrency-label="最多同时 2 张"
          :frozen-prompt="true" executor-label="DeepAgents"
          configuration-title="设计 DNA 预提取与冻结"
          configuration-description="使用工程配置中的模型，通过 DeepAgents 逐对象提取七组关系、同层风格、反向信号与限制。"
          frozen-prompt-placeholder="使用 Skill 当前冻结的设计卡 Prompt；不注入额外要求，未知与失败原样保留。"
          @update:selected-model-id="store.selectedModelId = $event"
          @update:prompt="store.prompt = $event" @start="confirmExtraction"
        />
      </div>
      <a-alert v-if="initializationError" type="error" show-icon :message="initializationError" class="preparation-error" />
      <a-spin :spinning="initializing" tip="正在读取冻结设计卡图库…">
        <PreparedDnaResultViewer
          :results="store.results" :active-result-id="store.activeResultId"
          :result="store.result" :loading="store.loadingResult"
          :coverage="store.preparation"
          @select="selectResult" @refresh="refreshResults"
        />
      </a-spin>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>设计 DNA 预提取 · 对象级设计关系</span></footer>
  </div>
</template>

<style scoped>
.preparation-hero { max-width: none; padding: 46px 0 30px; }
.preparation-hero-row { display: flex; justify-content: space-between; align-items: center; gap: 28px; }
.preparation-hero h1 { margin: 18px 0 13px; font-size: clamp(28px, 3.8vw, 43px); letter-spacing: -.04em; }
.preparation-hero p { margin: 0; font-size: 13px; line-height: 1.8; }
.preparation-hero-row > button { flex-shrink: 0; }
.preparation-extract { margin-bottom: 28px; }
.preparation-error { margin: 0 0 20px; }
@media (max-width: 700px) { .preparation-hero { padding-top: 30px; } .preparation-hero-row { display: block; } .preparation-hero-row > button { margin-top: 20px; } }
</style>
