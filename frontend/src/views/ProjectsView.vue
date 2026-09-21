<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { ArrowLeftOutlined, ArrowRightOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'

import { fetchResult, fetchResults } from '@/api/dna'
import { fetchTrendTask, fetchTrendTasks } from '@/api/highTrends'
import dnaSnapshot from '@/data/projectDnaSnapshot.json'
import trendSnapshot from '@/data/projectTrendSnapshot.json'
import { researchCohorts, researchImages } from '@/data/userResearch'
import type { DesignDnaResultSummary } from '@/types/dna'
import type { HighTrendCard, HighTrendTask } from '@/types/highTrends'

type TrendTab = 'high' | 'gap' | 'observe'
type ResultTab = 'id' | 'cmf'
type DnaField = { key: string; group: string; name: string; value: string; evidence: string; confidence: number }
type Opportunity = {
  id: string
  title: string
  description: string
  sourceCount: number
  sourceIds: string[]
  mentionedUsers: number
  populationCount: number
  images: string[]
}
type TrendSet = { taskId: string; generatedAt: string; source: '接口' | '本地结果快照'; high: Opportunity[]; gap: Opportunity[]; observe: Opportunity[] }
type Solution = { id: string; title: string; type: ResultTab; image: string; fit: number; tags: string[] }

/** 项目仅存在浏览器本地，所选真实趋势与 DNA 结果保留来源 ID；演示生成不写回业务数据。 */
interface DemoProject {
  id: string
  name: string
  category: string
  price: string
  market: string
  audience: string
  tones: string[]
  sellingPoints: string
  confidentiality: string
  currentStep: number
  maxStep: number
  trendTaskId: string
  selectedTrendIds: string[]
  moodboardId: number
  dnaSourceId: string
  dnaReviewed: boolean
  dnaEdits: Record<string, string>
  dnaLocked: boolean
  generationModel: string
  solutionCount: number
  creativity: string
  generationPrompt: string
  generated: boolean
  favorites: string[]
  createdAt: string
  updatedAt: string
}

const STORAGE_KEY = 'design-ai-project-demo-v1'
const stepNames = ['项目定义', '机会筛选', '情绪板', 'DNA 萃取', 'DNA 卡', '方案生成', '方案结果']
const toneOptions = ['科技感', '年轻潮流', '极简主义', '高端尊享', '自然有机', '运动性能']
const modelOptions = [
  { id: 'nano', name: 'Nano Banana', detail: '快速出图 · 演示选项' },
  { id: 'lovart', name: 'Lovart', detail: '高质量渲染 · 演示选项' },
  { id: 'lab', name: '内部 Lab', detail: '品牌定制 · 演示选项' },
  { id: 'fusion', name: 'Fusion Design', detail: '多模型融合 · 演示选项' },
]
const moodNames = ['方案 A · 克制秩序', '方案 B · 机能光影', '方案 C · 柔和玩色']
const moodNotes = [
  '从现有用研偏好图片中组合冷静、简洁的外观参考。',
  '从现有用研偏好图片中组合更强的结构和功能表达。',
  '从现有用研偏好图片中组合柔和色彩与细节变化。',
]

function readProjects(): DemoProject[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(value) ? value.filter((item): item is DemoProject =>
      Boolean(item && typeof item === 'object' && typeof item.id === 'string' && typeof item.name === 'string' && typeof item.currentStep === 'number')) : []
  } catch {
    return []
  }
}

const projects = ref<DemoProject[]>(readProjects())
const activeId = ref('')
const step = ref(1)
const listFilter = ref<'all' | 'active' | 'done'>('all')
const trendTab = ref<TrendTab>('high')
const resultTab = ref<ResultTab>('id')
const trendSet = ref<TrendSet>({
  taskId: trendSnapshot.taskId,
  generatedAt: trendSnapshot.generatedAt,
  source: '本地结果快照',
  high: trendSnapshot.trends.map(fromSnapshot),
  gap: trendSnapshot.gaps.map(fromSnapshot),
  observe: trendSnapshot.diagnostics.map(fromSnapshot),
})
const trendTasks = ref<HighTrendTask[]>([])
const trendLoading = ref(false)
const dnaLoading = ref(false)
const dnaSummaries = ref<DesignDnaResultSummary[]>([])
const dnaContent = ref<Record<string, unknown>>(dnaSnapshot.content)
const extractionProgress = ref(0)
const generationProgress = ref(0)
const selectedSolution = ref<Solution | null>(null)
let extractionTimer: ReturnType<typeof setInterval> | undefined
let generationTimer: ReturnType<typeof setInterval> | undefined

const project = computed(() => projects.value.find(item => item.id === activeId.value) ?? null)
const visibleProjects = computed(() => projects.value.filter(item => listFilter.value === 'all' || (listFilter.value === 'done' ? item.generated : !item.generated)))
const allOpportunities = computed(() => [...trendSet.value.high, ...trendSet.value.gap, ...trendSet.value.observe])
const currentOpportunities = computed(() => trendSet.value[trendTab.value])
const selectedOpportunities = computed(() => allOpportunities.value.filter(item => project.value?.selectedTrendIds.includes(item.id)))
const primaryOpportunity = computed(() => selectedOpportunities.value[0])
const moodboards = computed(() => researchCohorts.filter(group => group.imageIds.some(id => researchImages[id])).slice(0, 3).map((group, index) => ({
  id: index + 1,
  name: moodNames[index] ?? group.name,
  note: moodNotes[index] ?? '现有图片组成的演示情绪板。',
  cohort: group.name,
  images: group.imageIds.map(id => researchImages[id]?.src).filter((src): src is string => Boolean(src)).slice(0, 6),
})))
const selectedMoodboard = computed(() => moodboards.value.find(item => item.id === project.value?.moodboardId) ?? moodboards.value[0])
const fallbackDnaSummary: DesignDnaResultSummary = {
  id: dnaSnapshot.id,
  image_name: dnaSnapshot.image_name,
  preview_url: null,
  created_at: '2026-09-02',
  category: dnaSnapshot.category,
  style_candidates: [],
  summary: dnaSnapshot.summary,
}
const shownDnaSummaries = computed(() => [...dnaSummaries.value, fallbackDnaSummary])
const selectedDnaSummary = computed(() => shownDnaSummaries.value.find(item => item.id === project.value?.dnaSourceId) ?? shownDnaSummaries.value[0])
const dnaFields = computed<DnaField[]>(() => {
  const raw = dnaContent.value.key_dna
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map((item, index) => ({
      key: String(item.group ?? '特征') + ':' + String(item.name ?? index),
      group: String(item.group ?? '设计特征'),
      name: String(item.name ?? '未命名特征'),
      value: String(item.value ?? '—'),
      evidence: String(item.evidence ?? ''),
      confidence: Math.round(Number(item.confidence_score ?? 0.75) * 100),
    }))
})
const dnaModules = computed(() => dnaFields.value.slice(0, 8))
const styleNames = computed(() => {
  const style = dnaContent.value.style
  if (!style || typeof style !== 'object') return []
  const data = style as Record<string, unknown>
  const entries = data.style_candidates ?? data.tags ?? data.candidates
  return Array.isArray(entries) ? entries.map(item => String((item as Record<string, unknown>).label_zh ?? (item as Record<string, unknown>).style_id ?? '')).filter(Boolean).slice(0, 4) : []
})
const solutionImages = computed(() => {
  const mood = selectedMoodboard.value?.images ?? []
  const extras = moodboards.value.flatMap(item => item.images)
  const dnaPreview = selectedDnaSummary.value?.preview_url
  return [...(dnaPreview ? [dnaPreview] : []), ...mood, ...extras].filter(Boolean)
})
const solutions = computed<Solution[]>(() => {
  const count = project.value?.solutionCount ?? 6
  const images = solutionImages.value
  const tones = project.value?.tones ?? []
  return Array.from({ length: count }, (_, index) => {
    const isCmf = index >= Math.ceil(count / 2)
    const number = isCmf ? index - Math.ceil(count / 2) + 1 : index + 1
    return {
      id: (isCmf ? 'CMF-' : 'ID-') + String(number).padStart(2, '0'),
      title: (isCmf ? 'CMF ' : 'ID ') + String(number).padStart(2, '0') + ' · ' + (isCmf ? ['雾面银灰', '清透青蓝', '暖调金属', '低饱和紫境'][index % 4] : ['轻量秩序', '精密切面', '柔和曲线', '机能轮廓'][index % 4]),
      type: isCmf ? 'cmf' : 'id',
      image: images[index % Math.max(images.length, 1)] ?? '',
      fit: Math.max(76, 94 - index * 3),
      tags: [primaryOpportunity.value?.title ?? '设计方向', tones[index % Math.max(tones.length, 1)] ?? '设计探索'],
    }
  })
})
const shownSolutions = computed(() => solutions.value.filter(item => item.type === resultTab.value))
const extractionBusy = computed(() => extractionProgress.value > 0 && extractionProgress.value < 100)
const generationBusy = computed(() => generationProgress.value > 0 && generationProgress.value < 100)

function fromSnapshot(item: (typeof trendSnapshot.trends)[number]): Opportunity {
  return { ...item, images: [] }
}

function fromApi(item: HighTrendCard): Opportunity {
  return {
    id: item.id,
    title: item.title,
    description: item.description,
    sourceCount: item.source_records.length,
    sourceIds: item.source_records.slice(0, 5).map(source => source.short_id),
    mentionedUsers: item.mention_statistics.unique_mentioned_users,
    populationCount: item.mention_statistics.population_count,
    images: item.image_refs.filter(image => image.file_exists && Boolean(image.url)).slice(0, 4).map(image => image.url as string),
  }
}

function saveProject() {
  if (project.value) project.value.updatedAt = new Date().toISOString()
}

watch(projects, value => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)) }
  catch { message.warning('浏览器本地存储已满，本次修改可能无法保留') }
}, { deep: true })

function createProject() {
  const now = new Date().toISOString()
  const item: DemoProject = {
    id: globalThis.crypto?.randomUUID?.() ?? 'project-' + Date.now() + '-' + Math.random().toString(36).slice(2),
    name: '',
    category: '智能手机',
    price: '中端（￥1000–2000）',
    market: '印度尼西亚',
    audience: '年轻消费人群',
    tones: ['科技感'],
    sellingPoints: '',
    confidentiality: '内部公开',
    currentStep: 1,
    maxStep: 1,
    trendTaskId: trendSet.value.taskId,
    selectedTrendIds: [],
    moodboardId: 1,
    dnaSourceId: shownDnaSummaries.value.find(result => result.category?.includes('手机'))?.id ?? dnaSnapshot.id,
    dnaReviewed: false,
    dnaEdits: {},
    dnaLocked: false,
    generationModel: 'nano',
    solutionCount: 6,
    creativity: '均衡',
    generationPrompt: '',
    generated: false,
    favorites: [],
    createdAt: now,
    updatedAt: now,
  }
  projects.value.unshift(item)
  openProject(item)
}

function openProject(item: DemoProject) {
  clearInterval(extractionTimer)
  clearInterval(generationTimer)
  extractionProgress.value = 0
  generationProgress.value = item.generated ? 100 : 0
  activeId.value = item.id
  step.value = item.currentStep
  if (item.trendTaskId && item.trendTaskId !== trendSet.value.taskId) void loadTrendTask(item.trendTaskId)
  if (item.dnaSourceId) void loadDna(item.dnaSourceId)
}

function goToList() {
  clearInterval(extractionTimer)
  clearInterval(generationTimer)
  extractionProgress.value = 0
  generationProgress.value = 0
  saveProject()
  activeId.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function removeProject(item: DemoProject) {
  Modal.confirm({
    title: '删除这个本地演示项目？',
    content: '项目步骤、选择与方案展示记录将从当前浏览器移除。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => { projects.value = projects.value.filter(entry => entry.id !== item.id) },
  })
}

function moveTo(nextStep: number) {
  if (!project.value || nextStep < 1 || nextStep > 7 || nextStep > project.value.maxStep + 1) return
  step.value = nextStep
  project.value.currentStep = nextStep
  project.value.maxStep = Math.max(project.value.maxStep, nextStep)
  saveProject()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function next() {
  const item = project.value
  if (!item) return
  if (step.value === 1 && (!item.name.trim() || !item.category)) return void message.warning('请填写项目名称和产品品类')
  if (step.value === 2 && !item.selectedTrendIds.length) return void message.warning('请先选择至少一个真实趋势方向')
  if (step.value === 3 && !item.moodboardId) return void message.warning('请先选择一组情绪板')
  if (step.value === 4 && !item.dnaReviewed) return void message.warning('请先查看并确认 DNA 演示特征')
  if (step.value === 5 && !item.dnaLocked) return void message.warning('请先人工确认并锁定 DNA 卡')
  if (step.value === 6 && !item.generated) return void message.warning('请先生成演示方案')
  moveTo(step.value + 1)
}

function toggleTone(tone: string) {
  if (!project.value) return
  project.value.tones = project.value.tones.includes(tone) ? project.value.tones.filter(value => value !== tone) : [...project.value.tones, tone]
}

function toggleTrend(id: string) {
  if (!project.value) return
  project.value.selectedTrendIds = project.value.selectedTrendIds.includes(id)
    ? project.value.selectedTrendIds.filter(value => value !== id) : [...project.value.selectedTrendIds, id]
  project.value.maxStep = Math.min(project.value.maxStep, 2)
  project.value.dnaReviewed = false
  project.value.dnaEdits = {}
  project.value.dnaLocked = false
  project.value.generated = false
}

function chooseMoodboard(id: number) {
  if (!project.value || project.value.moodboardId === id) return
  project.value.moodboardId = id
  project.value.maxStep = Math.min(project.value.maxStep, 3)
  project.value.dnaReviewed = false
  project.value.dnaEdits = {}
  project.value.dnaLocked = false
  project.value.generated = false
}

async function refreshTrends() {
  trendLoading.value = true
  try {
    const tasks = (await fetchTrendTasks()).filter(item => item.status === 'completed' || item.status === 'partial')
    trendTasks.value = tasks
    const preferred = project.value?.trendTaskId
    const target = tasks.find(item => item.id === preferred) ?? tasks[0]
    if (target) await loadTrendTask(target.id)
  } catch {
    message.info('当前使用已完成高潜趋势任务的本地结果快照')
  } finally {
    trendLoading.value = false
  }
}

async function loadTrendTask(id: string) {
  trendLoading.value = true
  try {
    const task = await fetchTrendTask(id)
    if (!task.result?.trends?.length) throw new Error('当前任务没有可选趋势')
    trendSet.value = {
      taskId: task.id,
      generatedAt: task.updated_at,
      source: '接口',
      high: task.result.trends.map(fromApi),
      gap: (task.result.user_research_gaps?.directions ?? []).map(fromApi),
      observe: (task.result.diagnostics ?? []).map(fromApi),
    }
    if (project.value) {
      if (project.value.trendTaskId !== id) {
        project.value.selectedTrendIds = []
        project.value.maxStep = Math.min(project.value.maxStep, 2)
        project.value.dnaReviewed = false
        project.value.dnaLocked = false
        project.value.generated = false
      }
      project.value.trendTaskId = id
    }
  } catch {
    trendSet.value = {
      taskId: trendSnapshot.taskId,
      generatedAt: trendSnapshot.generatedAt,
      source: '本地结果快照',
      high: trendSnapshot.trends.map(fromSnapshot),
      gap: trendSnapshot.gaps.map(fromSnapshot),
      observe: trendSnapshot.diagnostics.map(fromSnapshot),
    }
    if (project.value) {
      if (project.value.trendTaskId !== trendSnapshot.taskId) {
        project.value.selectedTrendIds = []
        project.value.maxStep = Math.min(project.value.maxStep, 2)
        project.value.dnaReviewed = false
        project.value.dnaLocked = false
        project.value.generated = false
      }
      project.value.trendTaskId = trendSnapshot.taskId
    }
  } finally {
    trendLoading.value = false
  }
}

async function refreshDna() {
  dnaLoading.value = true
  try {
    dnaSummaries.value = await fetchResults()
    const preferred = project.value?.dnaSourceId
    const target = dnaSummaries.value.find(item => item.id === preferred)
      ?? dnaSummaries.value.find(item => item.category?.includes('手机'))
      ?? dnaSummaries.value[0]
    if (target) await loadDna(target.id)
  } catch {
    dnaSummaries.value = []
    dnaContent.value = dnaSnapshot.content
  } finally {
    dnaLoading.value = false
  }
}

async function loadDna(id: string) {
  if (id === dnaSnapshot.id) {
    dnaContent.value = dnaSnapshot.content
    if (project.value) project.value.dnaSourceId = id
    return
  }
  dnaLoading.value = true
  try {
    const result = await fetchResult(id, 'business')
    dnaContent.value = result.content
    if (project.value) project.value.dnaSourceId = id
  } catch {
    dnaContent.value = dnaSnapshot.content
    if (project.value) project.value.dnaSourceId = dnaSnapshot.id
    message.warning('DNA 结果暂不可读，已使用仓库中的真实结果快照')
  } finally {
    dnaLoading.value = false
  }
}

function chooseDna(id: string) {
  if (!project.value || project.value.dnaSourceId === id) return
  project.value.dnaReviewed = false
  project.value.dnaLocked = false
  project.value.dnaEdits = {}
  project.value.generated = false
  project.value.maxStep = Math.min(project.value.maxStep, 4)
  void loadDna(id)
}

function startExtraction() {
  if (!project.value || extractionBusy.value) return
  project.value.dnaReviewed = false
  extractionProgress.value = 1
  clearInterval(extractionTimer)
  extractionTimer = setInterval(() => {
    extractionProgress.value = Math.min(100, extractionProgress.value + 9)
    if (extractionProgress.value === 100) clearInterval(extractionTimer)
  }, 100)
}

function confirmDna() {
  if (!project.value) return
  project.value.dnaReviewed = true
  project.value.dnaLocked = false
  next()
}

function editDna(key: string, value: string) {
  if (!project.value || project.value.dnaLocked) return
  project.value.dnaEdits[key] = value
  project.value.generated = false
  project.value.maxStep = Math.min(project.value.maxStep, 5)
}

function lockDna() {
  if (!project.value) return
  Modal.confirm({
    title: '锁定当前 DNA 卡？',
    content: '请确认人工修订后的字段。锁定仅作用于此浏览器中的演示项目。',
    okText: '确认锁定',
    cancelText: '继续修改',
    onOk: () => { if (project.value) project.value.dnaLocked = true },
  })
}

function startGeneration() {
  if (!project.value || generationBusy.value || !project.value.dnaLocked) return
  project.value.generated = false
  project.value.maxStep = Math.min(project.value.maxStep, 6)
  generationProgress.value = 1
  clearInterval(generationTimer)
  generationTimer = setInterval(() => {
    generationProgress.value = Math.min(100, generationProgress.value + 8)
    if (generationProgress.value === 100) {
      clearInterval(generationTimer)
      if (project.value) project.value.generated = true
      message.success('演示方案已准备好')
    }
  }, 100)
}

function invalidateGeneration() {
  if (!project.value) return
  clearInterval(generationTimer)
  project.value.generated = false
  project.value.maxStep = Math.min(project.value.maxStep, 6)
  generationProgress.value = 0
}

function toggleFavorite(id: string) {
  if (!project.value) return
  project.value.favorites = project.value.favorites.includes(id)
    ? project.value.favorites.filter(value => value !== id) : [...project.value.favorites, id]
}

function exportProject() {
  if (!project.value) return
  const payload = {
    note: '前端演示项目；情绪板、方案图片及拟合度是基于已有素材构造的展示数据。',
    project: project.value,
    trend_source: { task_id: trendSet.value.taskId, generated_at: trendSet.value.generatedAt },
    selected_trends: selectedOpportunities.value.map(item => ({ id: item.id, title: item.title, source_ids: item.sourceIds })),
    dna_source_id: project.value.dnaSourceId,
    dna_card: dnaModules.value.map(field => ({ group: field.group, name: field.name, value: project.value?.dnaEdits[field.key] ?? field.value })),
    solutions: solutions.value.map(({ id, title, type, fit }) => ({ id, title, type, demo_fit: fit })),
  }
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'project-demo-' + project.value.id.slice(0, 8) + '.json'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function dateLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

onMounted(() => {
  void refreshTrends()
  void refreshDna()
})
onUnmounted(() => {
  clearInterval(extractionTimer)
  clearInterval(generationTimer)
})
</script>

<template>
  <div class="app-shell projects-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink to="/article-trends">趋势洞察</RouterLink><RouterLink to="/high-trends">高潜趋势</RouterLink><RouterLink to="/design-modification">设计修改</RouterLink><RouterLink to="/user-research">用研聚合</RouterLink><RouterLink class="active" to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>

    <main class="project-main">
      <template v-if="!project">
        <section class="project-hero">
          <div><span class="hero-badge">PROJECT WORKFLOW</span><h1>我的项目</h1><p>从趋势机会到方案结果，将设计探索串成一条可回看的演示流程。</p></div>
          <button class="primary-button" type="button" @click="createProject"><PlusOutlined /> 创建新项目</button>
        </section>
        <div class="demo-notice">前端演示 · 项目保存在当前浏览器。趋势选择读取高潜趋势结果；其余步骤使用已有图片与 DNA 结果模拟。</div>
        <div class="project-toolbar">
          <div class="tab-buttons"><button v-for="entry in [{ id: 'all', label: '全部' }, { id: 'active', label: '进行中' }, { id: 'done', label: '已完成' }]" :key="entry.id" type="button" :class="{ active: listFilter === entry.id }" @click="listFilter = entry.id as typeof listFilter">{{ entry.label }}</button></div>
          <span>{{ visibleProjects.length }} 个项目</span>
        </div>
        <div class="project-grid">
          <button class="new-project-tile" type="button" @click="createProject"><span>＋</span><strong>创建新项目</strong><small>开始 1 至 7 的完整流程</small></button>
          <article v-for="item in visibleProjects" :key="item.id" class="project-tile">
            <button class="project-cover" type="button" @click="openProject(item)">
              <span>{{ item.category }}</span>
              <img v-if="moodboards[(item.moodboardId || 1) - 1]?.images[0]" :src="moodboards[(item.moodboardId || 1) - 1]?.images[0]" :alt="item.name + ' 的参考图片'" />
            </button>
            <div class="project-tile-body">
              <button type="button" class="text-button project-title" @click="openProject(item)">{{ item.name || '未命名项目' }}</button>
              <p>{{ item.market }} · {{ item.audience }}</p>
              <div class="project-tile-footer"><span>{{ dateLabel(item.updatedAt) }}</span><b>{{ item.generated ? '方案已完成' : stepNames[item.currentStep - 1] }}</b></div>
              <div class="project-actions"><button type="button" @click="openProject(item)">继续项目 <ArrowRightOutlined /></button><button type="button" class="danger-text" @click="removeProject(item)">删除</button></div>
            </div>
          </article>
        </div>
        <p v-if="!visibleProjects.length && projects.length" class="empty-filter">此分类暂无项目。</p>
      </template>

      <template v-else>
        <button class="back-link" type="button" @click="goToList"><ArrowLeftOutlined /> 返回我的项目</button>
        <div class="wizard-header"><div><span class="eyebrow">PROJECT / {{ String(step).padStart(2, '0') }} OF 07</span><h1>{{ step === 1 ? '创建新项目' : stepNames[step - 1] }}</h1><p>{{ project.name || '新项目' }} · {{ project.category }} · {{ project.market }}</p></div><span class="demo-pill">前端交互演示</span></div>
        <div class="wizard-steps" aria-label="项目流程">
          <button v-for="(name, index) in stepNames" :key="name" type="button" :disabled="index + 1 > project.maxStep" :class="{ active: step === index + 1, done: index + 1 < step }" @click="moveTo(index + 1)"><span>{{ index + 1 < step ? '✓' : index + 1 }}</span><strong>{{ name }}</strong></button>
        </div>

        <section v-if="step === 1" class="wizard-section">
          <div class="section-intro"><h2>项目定义</h2><p>填写基本信息，后续页面会沿用这些选择。</p></div>
          <div class="surface form-surface">
            <label class="field full"><span>项目名称 *</span><input v-model="project.name" maxlength="80" placeholder="例如：印尼市场新一代手机外观设计" /></label>
            <label class="field"><span>产品品类 *</span><select v-model="project.category"><option>智能手机</option><option>功能手机</option><option>TWS 耳机</option><option>智能手表</option><option>智能音箱</option><option>其他消费电子</option></select></label>
            <label class="field"><span>价格段</span><select v-model="project.price"><option>入门（￥1000 以下）</option><option>中端（￥1000–2000）</option><option>中高端（￥2000–3000）</option><option>旗舰（￥3000 以上）</option></select></label>
            <label class="field"><span>目标市场</span><select v-model="project.market"><option>印度尼西亚</option><option>印度</option><option>尼日利亚</option><option>肯尼亚</option><option>马来西亚</option><option>全球</option></select></label>
            <label class="field"><span>目标人群</span><select v-model="project.audience"><option>年轻消费人群</option><option>科技先锋人群</option><option>务实简约人群</option><option>质感理性人群</option><option>全部人群</option></select></label>
            <div class="field full"><span>品牌调性</span><div class="chip-row"><button v-for="tone in toneOptions" :key="tone" type="button" class="chip" :class="{ selected: project.tones.includes(tone) }" @click="toggleTone(tone)">{{ tone }}</button></div></div>
            <label class="field full"><span>核心卖点</span><textarea v-model="project.sellingPoints" rows="3" placeholder="描述产品希望突出哪些体验和差异化设计" /></label>
            <div class="field full"><span>保密等级</span><div class="radio-row"><label v-for="level in ['内部公开', '机密', '绝密']" :key="level"><input v-model="project.confidentiality" type="radio" :value="level" />{{ level }}</label></div></div>
          </div>
        </section>

        <section v-else-if="step === 2" class="wizard-section">
          <div class="section-intro split"><div><h2>机会筛选引擎</h2><p>选择真实高潜趋势结果。来源任务：{{ trendSet.taskId }} · {{ trendSet.source }} · {{ dateLabel(trendSet.generatedAt) }}</p></div><button type="button" class="secondary-button" :disabled="trendLoading" @click="refreshTrends"><ReloadOutlined /> 刷新结果</button></div>
          <div v-if="trendTasks.length" class="surface source-selector"><label for="trend-task">高潜趋势任务</label><select id="trend-task" :value="trendSet.taskId" @change="loadTrendTask(($event.target as HTMLSelectElement).value)"><option v-for="item in trendTasks" :key="item.id" :value="item.id">{{ dateLabel(item.created_at) }} · {{ item.id.slice(0, 17) }}</option><option v-if="trendSet.source === '本地结果快照'" :value="trendSet.taskId">仓库中的已完成结果快照</option></select></div>
          <div class="tab-buttons stage-tabs"><button type="button" :class="{ active: trendTab === 'high' }" @click="trendTab = 'high'">高潜趋势 {{ trendSet.high.length }}</button><button type="button" :class="{ active: trendTab === 'gap' }" @click="trendTab = 'gap'">用户补充方向 {{ trendSet.gap.length }}</button><button type="button" :class="{ active: trendTab === 'observe' }" @click="trendTab = 'observe'">待观察方向 {{ trendSet.observe.length }}</button></div>
          <div class="opportunity-grid">
            <button v-for="(entry, index) in currentOpportunities" :key="entry.id" type="button" class="opportunity-card" :class="{ selected: project.selectedTrendIds.includes(entry.id) }" @click="toggleTrend(entry.id)">
              <div class="opportunity-images"><img v-for="(src, imageIndex) in (entry.images.length ? entry.images : moodboards[index % Math.max(moodboards.length, 1)]?.images.slice(0, 3) ?? [])" :key="src + imageIndex" :src="src" :alt="entry.title + ' 参考图 ' + (imageIndex + 1)" /></div>
              <div class="opportunity-body"><div class="opportunity-meta"><span>{{ entry.id }} · {{ trendTab === 'high' ? '高潜趋势' : trendTab === 'gap' ? '用户补充' : '待观察' }}</span><b>{{ project.selectedTrendIds.includes(entry.id) ? '✓ 已选择' : '选择方向' }}</b></div><h3>{{ entry.title }}</h3><p>{{ entry.description }}</p><div class="opportunity-stats"><span>关联来源 {{ entry.sourceCount }}</span><span>提及用户 {{ entry.mentionedUsers }} / {{ entry.populationCount }}</span></div><small class="opportunity-refs">来源编号 {{ entry.sourceIds.join(' · ') || '详见高潜趋势结果' }}</small></div>
            </button>
          </div>
          <p class="helper-note">提及人数是来源引用中的去重下限，不能解释为偏好率。卡片图片只作参考展示。</p>
        </section>

        <section v-else-if="step === 3" class="wizard-section">
          <div class="section-intro split"><div><h2>选择情绪板方向</h2><p>根据「{{ primaryOpportunity?.title }}」组合三组演示情绪板，图片来自已有用研偏好图库。</p></div><span class="stage-mark">已选 {{ selectedOpportunities.length }} 个趋势</span></div>
          <div class="mood-grid">
            <button v-for="mood in moodboards" :key="mood.id" type="button" class="mood-card" :class="{ selected: project.moodboardId === mood.id }" @click="chooseMoodboard(mood.id)">
              <div class="mood-images"><img v-for="(src, index) in mood.images" :key="src" :src="src" :alt="mood.name + ' 参考图 ' + (index + 1)" /></div>
              <div class="mood-body"><div><h3>{{ mood.name }}</h3><span>{{ project.moodboardId === mood.id ? '✓ 已选择' : '选择此组' }}</span></div><p>{{ mood.note }}</p><small>图片来源：{{ mood.cohort }} · ENJOY 反馈图</small></div>
            </button>
          </div>
        </section>

        <section v-else-if="step === 4" class="wizard-section">
          <div class="section-intro split"><div><h2>设计 DNA 萃取</h2><p>从已有 DNA 提取结果中选一张参考图，组合为当前项目的演示 DNA；此步骤不会调用模型。</p></div><span class="stage-mark">{{ selectedMoodboard?.name }}</span></div>
          <div class="surface dna-source-bar"><label for="dna-source">参考 DNA 结果</label><select id="dna-source" :value="project.dnaSourceId" :disabled="dnaLoading" @change="chooseDna(($event.target as HTMLSelectElement).value)"><option v-for="item in shownDnaSummaries" :key="item.id" :value="item.id">{{ item.image_name }} · {{ item.category || '未分类' }}</option></select><button type="button" class="secondary-button" :disabled="dnaLoading" @click="startExtraction"><ReloadOutlined /> {{ extractionProgress === 100 ? '重新演示' : '演示萃取过程' }}</button></div>
          <div v-if="extractionBusy" class="surface progress-surface"><h3>正在整理演示 DNA 特征…</h3><div class="progress-track"><span :style="{ width: extractionProgress + '%' }"></span></div><p>{{ extractionProgress }}% · 使用已有结果字段与图片展示</p></div>
          <div class="dna-overview"><div class="surface dna-reference"><img :src="selectedDnaSummary?.preview_url || selectedMoodboard?.images[0]" :alt="selectedDnaSummary?.image_name || '参考图片'" /><h3>{{ selectedDnaSummary?.image_name }}</h3><p>{{ selectedDnaSummary?.summary || dnaSnapshot.summary }}</p><div class="chip-row"><span v-for="name in styleNames" :key="name" class="chip passive">{{ name }}</span></div><small>结果来源 ID：{{ project.dnaSourceId }} · {{ String(dnaContent.model_id || '历史结果') }}</small></div><div class="feature-list"><article v-for="field in dnaFields.slice(0, 8)" :key="field.key" class="surface feature-card"><div><span>{{ field.group }}</span><strong>{{ field.name }}</strong><p>{{ field.evidence || '来自所选 DNA 结果的业务字段。' }}</p></div><div class="feature-value"><b>{{ field.value }}</b><small>源结果置信度 {{ field.confidence }}%</small></div></article></div></div>
          <div class="inline-actions"><button type="button" class="primary-button" :disabled="dnaLoading || extractionBusy" @click="confirmDna">人工确认特征，生成 DNA 卡 <ArrowRightOutlined /></button></div>
        </section>

        <section v-else-if="step === 5" class="wizard-section">
          <div class="section-intro split"><div><h2>设计 DNA 参数卡</h2><p>核对源结果字段，可修改演示值；锁定后用于后续方案展示。</p></div><span v-if="project.dnaLocked" class="locked-pill">✓ DNA 已锁定</span></div>
          <div class="dna-card surface"><div class="dna-card-head"><div><span class="eyebrow">DESIGN DNA / DEMO</span><h3>{{ project.name }} · 设计 DNA</h3><p>参考：{{ selectedDnaSummary?.image_name }} · 情绪板：{{ selectedMoodboard?.name }}</p></div><span>{{ project.dnaSourceId.slice(0, 18) }}</span></div><div class="dna-module-grid"><label v-for="field in dnaModules" :key="field.key" class="dna-module"><span>{{ field.group }}</span><strong>{{ field.name }}</strong><input :value="project.dnaEdits[field.key] ?? field.value" :disabled="project.dnaLocked" :aria-label="field.name + ' 演示值'" @input="editDna(field.key, ($event.target as HTMLInputElement).value)" /><small>源置信度 {{ field.confidence }}% · {{ field.key }}</small></label></div></div>
          <div class="inline-actions"><button type="button" class="secondary-button" @click="exportProject"><DownloadOutlined /> 导出参数 JSON</button><button v-if="!project.dnaLocked" type="button" class="primary-button" @click="lockDna">人工确认并锁定 DNA</button><button v-else type="button" class="secondary-button" @click="project.dnaLocked = false; project.generated = false; project.maxStep = Math.min(project.maxStep, 5)">解锁修订</button></div>
        </section>

        <section v-else-if="step === 6" class="wizard-section">
          <div class="section-intro"><h2>生成设计方案</h2><p>选择演示参数。方案图片由现有素材组合，所选模型不会执行调用。</p></div>
          <div class="surface current-dna"><div><span>当前 DNA</span><strong>{{ project.name }} · {{ primaryOpportunity?.title }}</strong><small>{{ project.dnaLocked ? '已人工锁定' : '尚未锁定' }} · {{ dnaModules.length }} 个展示字段</small></div><button type="button" class="secondary-button" @click="moveTo(5)">查看 DNA 卡</button></div>
          <div class="surface generation-config"><h3>选择生成模型 <small>仅作为演示配置</small></h3><div class="model-grid"><button v-for="model in modelOptions" :key="model.id" type="button" :class="{ selected: project.generationModel === model.id }" @click="project.generationModel = model.id; invalidateGeneration()"><span>{{ model.name.slice(0, 2).toUpperCase() }}</span><strong>{{ model.name }}</strong><small>{{ model.detail }}</small></button></div><div class="form-surface generation-fields"><label class="field"><span>方案数量</span><select v-model.number="project.solutionCount" @change="invalidateGeneration"><option :value="4">4 个方案</option><option :value="6">6 个方案</option><option :value="8">8 个方案</option></select></label><label class="field"><span>创意自由度</span><select v-model="project.creativity" @change="invalidateGeneration"><option>保守</option><option>均衡</option><option>奔放</option></select></label><label class="field full"><span>补充提示词</span><textarea v-model="project.generationPrompt" rows="3" placeholder="输入额外设计要求，供演示结果摘要展示" @input="invalidateGeneration" /></label></div><button type="button" class="primary-button wide-button" :disabled="generationBusy" @click="startGeneration">{{ generationBusy ? '正在准备演示方案…' : '开始生成演示方案' }}</button></div>
          <div v-if="generationProgress" class="surface progress-surface"><h3>{{ project.generated ? '演示方案已准备好' : '正在组合已有图片与设计字段…' }}</h3><div class="progress-track"><span :style="{ width: generationProgress + '%' }"></span></div><p>{{ generationProgress }}% · {{ project.generated ? '可查看全部方案结果' : '不会调用图片生成模型' }}</p><button v-if="project.generated" type="button" class="primary-button" @click="next">查看方案结果 <ArrowRightOutlined /></button></div>
        </section>

        <section v-else class="wizard-section">
          <div class="section-intro split"><div><h2>方案结果</h2><p>共 {{ solutions.length }} 个演示方案 · 基于 {{ primaryOpportunity?.title }} 与 {{ selectedMoodboard?.name }}</p></div><button type="button" class="secondary-button" @click="exportProject"><DownloadOutlined /> 导出项目摘要</button></div>
          <div class="demo-notice">方案图片取自现有素材；名称、拟合度与组合是前端演示数据，未发生真实方案生成或评分。</div>
          <div class="tab-buttons stage-tabs"><button type="button" :class="{ active: resultTab === 'id' }" @click="resultTab = 'id'">ID 造型方案</button><button type="button" :class="{ active: resultTab === 'cmf' }" @click="resultTab = 'cmf'">CMF 方案</button></div>
          <div class="solution-grid"><article v-for="solution in shownSolutions" :key="solution.id" class="solution-card"><button class="solution-image" type="button" @click="selectedSolution = solution"><img :src="solution.image" :alt="solution.title + ' 演示图片'" /><span>演示拟合 {{ solution.fit }}%</span></button><div class="solution-body"><button type="button" class="text-button" @click="selectedSolution = solution">{{ solution.title }}</button><div class="chip-row"><span v-for="tag in solution.tags" :key="tag" class="chip passive">{{ tag }}</span></div><div class="solution-footer"><span>{{ solution.type === 'id' ? 'ID 造型' : 'CMF' }} · {{ modelOptions.find(model => model.id === project?.generationModel)?.name }}</span><button type="button" @click="toggleFavorite(solution.id)">{{ project.favorites.includes(solution.id) ? '★ 已收藏' : '☆ 收藏' }}</button></div></div></article></div>
        </section>

        <div class="wizard-footer"><div><strong>{{ stepNames[step - 1] }}</strong><span v-if="step === 2">已选择 {{ project.selectedTrendIds.length }} 个方向</span><span v-else-if="step === 5">{{ project.dnaLocked ? 'DNA 已锁定' : '请人工确认 DNA' }}</span><span v-else-if="step === 7">已收藏 {{ project.favorites.length }} 个方案</span><span v-else>步骤 {{ step }} / 7</span></div><div><button type="button" class="secondary-button" @click="step === 1 ? goToList() : moveTo(step - 1)">{{ step === 1 ? '取消' : '返回上一步' }}</button><button v-if="step < 7 && step !== 4" type="button" class="primary-button" @click="next">下一步：{{ stepNames[step] }} <ArrowRightOutlined /></button><button v-if="step === 7" type="button" class="primary-button" @click="goToList">完成并返回项目</button></div></div>
      </template>
    </main>

    <a-modal :open="Boolean(selectedSolution)" :footer="null" centered :width="760" :title="selectedSolution?.title" @cancel="selectedSolution = null"><div v-if="selectedSolution" class="solution-detail"><img :src="selectedSolution.image" :alt="selectedSolution.title + ' 演示图片'" /><div><span class="stage-mark">演示拟合度 {{ selectedSolution.fit }}%</span><h3>设计说明</h3><p>围绕「{{ primaryOpportunity?.title }}」和「{{ selectedMoodboard?.name }}」组织已有图片素材。{{ project?.generationPrompt || '保留所选品牌调性与 DNA 卡中的核心视觉线索。' }}</p><h3>关联 DNA</h3><ul><li v-for="field in dnaModules.slice(0, 4)" :key="field.key">{{ field.name }}：{{ project?.dnaEdits[field.key] ?? field.value }}</li></ul><p class="helper-note">此图为参考素材，拟合度仅供演示交互。</p></div></div></a-modal>
  </div>
</template>

<style scoped>
.projects-shell { color: #322d43; }
.project-main { padding: 36px 0 90px; }
.project-hero, .wizard-header, .section-intro.split, .project-toolbar, .wizard-footer, .inline-actions, .dna-card-head, .opportunity-meta, .opportunity-stats, .mood-body > div, .project-tile-footer, .project-actions, .solution-footer { display: flex; justify-content: space-between; align-items: center; gap: 18px; }
.project-hero { min-height: 180px; padding: 14px 0 28px; }
.project-hero h1, .wizard-header h1 { margin: 12px 0 8px; font-size: clamp(28px, 3vw, 38px); letter-spacing: -.03em; }
.project-hero p, .wizard-header p, .section-intro p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.8; }
.hero-badge, .eyebrow { color: #735fc1; font-size: 10px; font-weight: 700; letter-spacing: .14em; }
.primary-button, .secondary-button { display: inline-flex; justify-content: center; align-items: center; gap: 8px; min-height: 39px; padding: 9px 16px; border: 1px solid transparent; border-radius: 10px; cursor: pointer; font-size: 12px; font-weight: 600; white-space: nowrap; }
.primary-button { color: white; background: #6257d8; box-shadow: 0 8px 18px #6257d82a; }
.primary-button:hover { background: #4d42ba; }
.secondary-button { color: #6253a2; background: white; border-color: #ddd5ee; }
.secondary-button:hover { background: #f7f4fd; }
.primary-button:disabled, .secondary-button:disabled { opacity: .52; cursor: not-allowed; }
.demo-notice { padding: 12px 15px; color: #776489; background: #f2ecfa; border: 1px solid #e8dcf2; border-radius: 11px; font-size: 11px; line-height: 1.7; }
.project-toolbar { margin: 24px 0 15px; color: #8a8395; font-size: 12px; }
.tab-buttons { display: inline-flex; gap: 4px; padding: 4px; background: #eeebf3; border-radius: 11px; }
.tab-buttons button { padding: 8px 14px; color: #83798f; background: none; border: 0; border-radius: 8px; cursor: pointer; font-size: 11px; white-space: nowrap; }
.tab-buttons button.active { color: #5947a9; background: white; box-shadow: 0 2px 8px #4e3e7614; font-weight: 700; }
.project-grid, .opportunity-grid, .mood-grid, .solution-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.new-project-tile, .project-tile, .surface, .opportunity-card, .mood-card, .solution-card { min-width: 0; background: #fff; border: 1px solid #e7e1ef; border-radius: 17px; box-shadow: 0 10px 30px #382c540a; }
.new-project-tile { display: grid; place-content: center; justify-items: center; gap: 7px; min-height: 288px; color: #6652af; border-style: dashed; cursor: pointer; }
.new-project-tile:hover, .opportunity-card:hover, .mood-card:hover { border-color: #a99be5; }
.new-project-tile span { display: grid; width: 52px; height: 52px; place-items: center; background: #f0ebff; border-radius: 16px; font-size: 28px; }
.new-project-tile strong { font-size: 14px; }
.new-project-tile small { color: #a39aaf; font-size: 10px; }
.project-tile { overflow: hidden; }
.project-cover { position: relative; display: block; width: 100%; height: 150px; overflow: hidden; padding: 0; background: linear-gradient(130deg, #aaa0e5, #c5e0e9); border: 0; cursor: pointer; }
.project-cover img { width: 100%; height: 100%; object-fit: cover; }
.project-cover span { position: absolute; z-index: 1; top: 12px; left: 12px; padding: 5px 9px; color: #fff; background: #30273fab; border-radius: 6px; font-size: 10px; }
.project-tile-body { padding: 17px; }
.text-button { padding: 0; background: none; border: 0; cursor: pointer; text-align: left; }
.project-title { color: #342943; font-size: 15px; font-weight: 700; }
.project-tile-body p { min-height: 32px; margin: 8px 0 13px; color: #8b8195; font-size: 11px; }
.project-tile-footer { padding-top: 11px; color: #a49aaa; border-top: 1px solid #f0edf4; font-size: 10px; }
.project-tile-footer b { color: #6c55ae; }
.project-actions { margin-top: 13px; }
.project-actions button, .solution-footer button { padding: 0; color: #6453b0; background: none; border: 0; cursor: pointer; font-size: 11px; }
.project-actions .danger-text { color: #b2707b; }
.empty-filter { color: #968aa0; font-size: 12px; }
.back-link { display: inline-flex; gap: 8px; align-items: center; padding: 0; color: #75698c; background: none; border: 0; cursor: pointer; font-size: 12px; }
.wizard-header { margin: 26px 0 22px; }
.demo-pill, .stage-mark, .locked-pill { padding: 7px 10px; color: #6d5db5; background: #eeeafe; border-radius: 999px; font-size: 10px; white-space: nowrap; }
.locked-pill { color: #337f66; background: #e6f5ee; }
.wizard-steps { display: flex; overflow-x: auto; gap: 5px; padding: 8px; background: #fff; border: 1px solid #e9e4f0; border-radius: 14px; }
.wizard-steps button { display: flex; flex: 1; min-width: 112px; align-items: center; gap: 7px; padding: 8px 10px; color: #a49aae; background: transparent; border: 0; border-radius: 9px; cursor: pointer; text-align: left; font-size: 11px; white-space: nowrap; }
.wizard-steps button span { display: grid; flex-shrink: 0; width: 23px; height: 23px; place-items: center; background: #f1eef5; border-radius: 50%; font-size: 10px; }
.wizard-steps button.active { color: #5445a7; background: #f2efff; }
.wizard-steps button.active span { color: white; background: #6257d8; }
.wizard-steps button.done { color: #468a70; }
.wizard-steps button.done span { color: white; background: #64b591; }
.wizard-steps button:disabled { cursor: default; }
.wizard-section { margin-top: 32px; }
.section-intro { margin-bottom: 18px; }
.section-intro h2 { margin: 0 0 5px; font-size: 19px; }
.section-intro.split { align-items: flex-start; }
.surface { padding: 22px; }
.form-surface { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.field { display: grid; gap: 7px; min-width: 0; color: #655d72; font-size: 11px; }
.field.full { grid-column: 1 / -1; }
.field input, .field select, .field textarea, .source-selector select, .dna-source-bar select, .dna-module input { width: 100%; min-width: 0; padding: 9px 11px; color: #41394f; background: #fdfcff; border: 1px solid #e3ddea; border-radius: 9px; outline: none; font-size: 12px; }
.field input:focus, .field select:focus, .field textarea:focus, .source-selector select:focus, .dna-source-bar select:focus, .dna-module input:focus { border-color: #9c8bdb; box-shadow: 0 0 0 2px #9c8bdb20; }
.field textarea { resize: vertical; }
.chip-row, .radio-row { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { padding: 6px 10px; color: #85768f; background: #f5f2f8; border: 1px solid #e9e1ee; border-radius: 7px; cursor: pointer; font-size: 10px; }
.chip.selected { color: #6251b1; background: #eeebff; border-color: #ad9ee8; }
.chip.passive { cursor: default; }
.radio-row label { display: flex; align-items: center; gap: 5px; cursor: pointer; }
.source-selector, .dna-source-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 17px; color: #71677b; font-size: 11px; }
.source-selector select, .dna-source-bar select { flex: 1; }
.stage-tabs { margin: 0 0 17px; }
.opportunity-card, .mood-card { overflow: hidden; padding: 0; cursor: pointer; text-align: left; }
.opportunity-card.selected, .mood-card.selected, .model-grid button.selected { border-color: #7d67d4; box-shadow: 0 0 0 2px #8b79d824; }
.opportunity-images { display: flex; height: 113px; overflow: hidden; background: linear-gradient(120deg, #ece5fb, #d9e9f0); }
.opportunity-images img { flex: 1; min-width: 0; width: 33%; object-fit: cover; }
.opportunity-body { padding: 15px; }
.opportunity-meta { color: #9a8bab; font-size: 10px; }
.opportunity-meta b { color: #6854b6; font-weight: 600; }
.opportunity-body h3 { min-height: 42px; margin: 10px 0 7px; font-size: 14px; line-height: 1.5; }
.opportunity-body p { display: -webkit-box; overflow: hidden; min-height: 57px; margin: 0; color: #867c91; font-size: 11px; line-height: 1.75; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.opportunity-stats { margin-top: 13px; padding-top: 10px; color: #a198aa; border-top: 1px solid #f0edf3; font-size: 10px; }
.opportunity-refs { display: block; overflow: hidden; margin-top: 6px; color: #b2a9ba; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.helper-note { margin: 11px 0 0; color: #998ea3; font-size: 10px; line-height: 1.6; }
.mood-images { display: grid; height: 260px; grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(2, 1fr); gap: 4px; padding: 4px; background: #f1edf5; }
.mood-images img { width: 100%; height: 100%; min-height: 0; object-fit: cover; border-radius: 4px; }
.mood-body { padding: 17px; }
.mood-body h3 { margin: 0; font-size: 14px; }
.mood-body span { color: #705abb; font-size: 10px; }
.mood-body p { min-height: 40px; margin: 9px 0; color: #827789; font-size: 11px; line-height: 1.7; }
.mood-body small { color: #a79cab; font-size: 10px; }
.dna-overview { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 18px; }
.dna-reference img { width: 100%; height: 220px; object-fit: cover; background: #f3f0f6; border-radius: 10px; }
.dna-reference h3 { margin: 14px 0 7px; font-size: 14px; }
.dna-reference p { color: #766c80; font-size: 11px; line-height: 1.8; }
.dna-reference small { display: block; margin-top: 14px; color: #a096a8; font-size: 9px; overflow-wrap: anywhere; }
.feature-list { display: grid; gap: 10px; }
.feature-card { display: flex; justify-content: space-between; gap: 15px; padding: 15px; }
.feature-card span, .feature-card small { display: block; color: #9a8da4; font-size: 10px; }
.feature-card strong { display: block; margin: 4px 0; font-size: 12px; }
.feature-card p { margin: 0; color: #877e90; font-size: 10px; line-height: 1.6; }
.feature-value { flex-shrink: 0; max-width: 120px; text-align: right; }
.feature-value b { display: block; color: #6755a9; font-size: 11px; overflow-wrap: anywhere; }
.inline-actions { justify-content: flex-end; margin-top: 18px; }
.dna-card { padding: 0; overflow: hidden; }
.dna-card-head { padding: 22px; color: white; background: linear-gradient(115deg, #5642a9, #756ad1, #5caec6); }
.dna-card-head .eyebrow { color: #d7d0ff; }
.dna-card-head h3 { margin: 7px 0; font-size: 18px; }
.dna-card-head p, .dna-card-head > span { margin: 0; color: #ece7ff; font-size: 10px; }
.dna-module-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: #eee9f3; }
.dna-module { display: grid; gap: 6px; min-width: 0; padding: 20px; background: #fff; }
.dna-module span { color: #8471a5; font-size: 10px; }
.dna-module strong { font-size: 12px; }
.dna-module input { font-size: 11px; }
.dna-module input:disabled { color: #655a76; background: #f8f6fa; }
.dna-module small { color: #aea4b4; font-size: 9px; overflow-wrap: anywhere; }
.current-dna { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; background: #f3f0fc; }
.current-dna div { display: grid; gap: 5px; }
.current-dna span, .current-dna small { color: #85799d; font-size: 10px; }
.current-dna strong { font-size: 13px; }
.generation-config h3 { margin: 0 0 14px; font-size: 14px; }
.generation-config h3 small { margin-left: 6px; color: #a49aaf; font-size: 10px; font-weight: 400; }
.model-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.model-grid button { display: grid; justify-items: start; gap: 7px; padding: 15px; color: #4d445d; background: #faf9fc; border: 1px solid #e9e4f0; border-radius: 10px; cursor: pointer; text-align: left; }
.model-grid button span { display: grid; width: 30px; height: 30px; place-items: center; color: white; background: linear-gradient(130deg, #846fd0, #73adc4); border-radius: 8px; font-size: 10px; }
.model-grid button strong { font-size: 11px; }
.model-grid button small { color: #9a90a3; font-size: 9px; }
.generation-fields { margin-top: 19px; padding: 0; border: 0; box-shadow: none; }
.wide-button { width: 100%; margin-top: 18px; }
.progress-surface { margin-top: 17px; }
.progress-surface h3 { margin: 0 0 12px; font-size: 13px; }
.progress-surface p { color: #93899f; font-size: 10px; }
.progress-track { height: 7px; overflow: hidden; background: #eeeaf6; border-radius: 99px; }
.progress-track span { display: block; height: 100%; background: linear-gradient(90deg, #725dd1, #68b5c4); transition: width .12s; }
.solution-card { overflow: hidden; }
.solution-image { position: relative; display: block; width: 100%; height: 230px; padding: 0; background: #f2eef5; border: 0; cursor: zoom-in; }
.solution-image img { width: 100%; height: 100%; object-fit: cover; }
.solution-image span { position: absolute; top: 11px; right: 11px; padding: 6px 9px; color: #fff; background: #322543bc; border-radius: 7px; font-size: 10px; }
.solution-body { padding: 16px; }
.solution-body > .text-button { margin-bottom: 12px; color: #3d344b; font-size: 13px; font-weight: 700; }
.solution-footer { margin-top: 13px; padding-top: 11px; color: #9e94a9; border-top: 1px solid #f1edf4; font-size: 10px; }
.wizard-footer { position: sticky; z-index: 4; bottom: 14px; margin-top: 28px; padding: 13px 17px; background: #fffffff2; border: 1px solid #e7e0ed; border-radius: 14px; box-shadow: 0 18px 42px #44365b1f; backdrop-filter: blur(12px); }
.wizard-footer > div { display: flex; align-items: center; gap: 10px; }
.wizard-footer > div:first-child { display: grid; gap: 3px; }
.wizard-footer strong { font-size: 11px; }
.wizard-footer span { color: #9b90a5; font-size: 10px; }
.solution-detail { display: grid; grid-template-columns: minmax(0, 1fr) 240px; gap: 20px; }
.solution-detail img { width: 100%; max-height: 470px; object-fit: contain; background: #f3eff6; border-radius: 10px; }
.solution-detail h3 { margin: 17px 0 7px; font-size: 12px; }
.solution-detail p, .solution-detail li { color: #756b7e; font-size: 11px; line-height: 1.7; }
.solution-detail ul { padding-left: 17px; }
@media (max-width: 1080px) { .project-grid, .opportunity-grid, .mood-grid, .solution-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .dna-module-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .model-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 760px) { .projects-shell .topbar { grid-template-columns: 1fr; gap: 12px; height: auto; padding: 17px 0; } .projects-shell .topbar nav { gap: 15px; } .projects-shell .system-state { display: none; } .project-hero, .wizard-header, .section-intro.split { align-items: flex-start; flex-direction: column; } .dna-overview { grid-template-columns: 1fr; } .dna-reference img { height: 270px; object-fit: contain; } .source-selector, .dna-source-bar { flex-wrap: wrap; } .source-selector select, .dna-source-bar select { flex-basis: 100%; } }
@media (max-width: 570px) { .project-main { width: min(100% - 28px, 1180px); } .project-grid, .opportunity-grid, .mood-grid, .solution-grid, .form-surface { grid-template-columns: 1fr; } .field.full { grid-column: auto; } .wizard-header { margin-top: 17px; } .wizard-footer { bottom: 8px; flex-direction: column; align-items: stretch; } .wizard-footer > div:last-child { justify-content: flex-end; } .wizard-footer .primary-button, .wizard-footer .secondary-button { padding-inline: 10px; font-size: 10px; } .mood-images { height: 220px; } .dna-module-grid { grid-template-columns: 1fr; } .model-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .solution-detail { grid-template-columns: 1fr; } }
</style>
