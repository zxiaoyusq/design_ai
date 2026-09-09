<script setup lang="ts">
import { computed, h, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  ApiOutlined,
  ArrowRightOutlined,
  BulbOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons-vue'

import ExtractionComposer from '@/components/ExtractionComposer.vue'
import ImageUploadPanel from '@/components/ImageUploadPanel.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import { useDnaStore } from '@/stores/dna'

const store = useDnaStore()

const selectedModelName = computed(
  () => store.models.find((model) => model.id === store.selectedModelId)?.name ?? '',
)

onMounted(async () => {
  try {
    await store.initialize()
  } catch (error) {
    message.error(readError(error, '工作台初始化失败'))
  }
})

function readError(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail ?? fallback
  }
  return error instanceof Error ? error.message : fallback
}

async function handleUpload(files: File[]) {
  try {
    await store.addImages(files)
    message.success(`已加入 ${files.length} 张图片`)
  } catch (error) {
    message.error(readError(error, '图片上传失败'))
  }
}

function confirmImageDelete(imageId: string) {
  const image = store.images.find((item) => item.id === imageId)
  if (!image) return
  Modal.confirm({
    title: '删除这张素材？',
    icon: h(DeleteOutlined, { style: { color: '#bc5d5d' } }),
    content: `“${image.filename}”将从素材库移除，已经完成的提取结果会保留。`,
    okText: '删除素材',
    okType: 'danger',
    cancelText: '取消',
    centered: true,
    async onOk() {
      try {
        await store.removeImage(imageId)
        message.success('素材已删除')
      } catch (error) {
        message.error(readError(error, '素材删除失败'))
      }
    },
  })
}

function confirmResultDelete(resultId: string) {
  const result = store.results.find((item) => item.id === resultId)
  if (!result) return
  Modal.confirm({
    title: '删除这条提取结果？',
    icon: h(DeleteOutlined, { style: { color: '#bc5d5d' } }),
    content: `“${result.image_name}”对应的业务视图、完整详情和追溯信息将一并删除，此操作无法恢复。`,
    okText: '删除结果',
    okType: 'danger',
    cancelText: '取消',
    centered: true,
    async onOk() {
      try {
        await store.removeResult(resultId)
        message.success('提取结果已删除')
      } catch (error) {
        message.error(readError(error, '结果删除失败'))
      }
    },
  })
}

function confirmExtraction() {
  Modal.confirm({
    title: '确认开始设计 DNA 提取？',
    icon: h(SafetyCertificateOutlined, { style: { color: '#6257d8' } }),
    content: h('div', { class: 'confirm-copy' }, [
      h('p', `图片：${store.selectedImages.length} 张`),
      h('p', `模型：${selectedModelName.value}`),
      h('p', `要求：${store.prompt.trim() || '按标准协议完整提取'}`),
    ]),
    okText: '确认并开始',
    cancelText: '再检查一下',
    centered: true,
    onOk() {
      void runExtraction()
    },
  })
}

async function runExtraction() {
  try {
    await store.startExtraction()
    if (store.currentTask?.status === 'completed') {
      message.success('设计 DNA 提取完成')
    } else {
      message.warning('任务已结束，请检查失败图片')
    }
  } catch (error) {
    message.error(readError(error, '提取任务启动失败'))
  }
}

async function selectResult(resultId: string) {
  try {
    await store.selectResult(resultId)
  } catch (error) {
    message.error(readError(error, '结果读取失败'))
  }
}

async function changeResultView(view: 'business' | 'detail') {
  try {
    await store.setResultView(view)
  } catch (error) {
    message.error(readError(error, '详情读取失败'))
  }
}
</script>

<template>
  <div class="app-shell">
    <div class="ambient ambient-one"></div>
    <div class="ambient ambient-two"></div>

    <header class="topbar">
      <a class="brand" href="#top" aria-label="形鉴首页">
        <span class="brand-mark"><span></span></span>
        <span class="brand-copy">
        </span>
      </a>
      <nav>
        <a class="active" href="#extract">DNA 提取</a>
        <RouterLink to="/high-trends">高潜趋势</RouterLink>
        <a href="#results">结果档案</a>
      </nav>
      <div class="system-state"><span></span> Agent 服务在线</div>
    </header>

    <main id="top">
      <section class="hero">
        <div class="hero-badge"><BulbOutlined /> AI AESTHETIC INTELLIGENCE</div>
        <h1>用户审美洞察与趋势捕捉，<br /><em>DNA 元素提取</em></h1>
        <p>
          通过多模态 Agent 识别主物品，将风格、形态、构图、色彩与 CMF
          转化为可追溯、可计算的设计 DNA。
        </p>
      </section>

      <section class="flow-strip" aria-label="提取流程">
        <div class="flow-step active"><span>1</span><strong>上传素材</strong></div>
        <ArrowRightOutlined />
        <div class="flow-step"><span>2</span><strong>描述关注点</strong></div>
        <ArrowRightOutlined />
        <div class="flow-step"><span>3</span><strong>确认并提取</strong></div>
        <ArrowRightOutlined />
        <div class="flow-step"><span>4</span><strong>查看 DNA</strong></div>
      </section>

      <div id="extract" class="workspace-grid">
        <ImageUploadPanel
          :images="store.images"
          :selected-ids="store.selectedImageIds"
          :uploading="store.uploading"
          :deleting-ids="store.deletingImageIds"
          @upload="handleUpload"
          @toggle="store.toggleImage"
          @select-all="store.selectAllImages"
          @clear="store.clearSelectedImages"
          @delete="confirmImageDelete"
        />
        <ExtractionComposer
          :models="store.models"
          :selected-count="store.selectedImageIds.length"
          :selected-model-id="store.selectedModelId"
          :prompt="store.prompt"
          :task="store.currentTask"
          :running="store.taskRunning"
          @update:selected-model-id="store.selectedModelId = $event"
          @update:prompt="store.prompt = $event"
          @start="confirmExtraction"
        />
      </div>

      <div id="results">
        <ResultViewer
          :results="store.results"
          :active-result-id="store.activeResultId"
          :view="store.resultView"
          :content="store.resultContent"
          :loading="store.loadingResult"
          :deleting-ids="store.deletingResultIds"
          @select="selectResult"
          @change-view="changeResultView"
          @refresh="store.refreshResults"
          @delete="confirmResultDelete"
        />
      </div>
    </main>

    <footer>
      <span>形鉴 · AI 审美洞察平台</span>
      <span>Multi-tag Design DNA Schema v1.1</span>
    </footer>
  </div>
</template>
