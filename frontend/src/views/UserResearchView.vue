<script setup lang="ts">
import MainNavigation from '@/components/MainNavigation.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { CloudUploadOutlined, DownloadOutlined, FilePptOutlined, PictureOutlined, ReloadOutlined, SearchOutlined, TeamOutlined } from '@ant-design/icons-vue'
import { fetchModels } from '@/api/dna'
import { confirmResearchTask, fetchResearchTasks, fetchResearchUser, fetchResearchUsers, importResearchPpt } from '@/api/userResearch'
import type { ModelInfo } from '@/types/dna'
import type { ResearchImage, ResearchImageEmotion, ResearchImportTask, ResearchUserDetail, ResearchUserSummary } from '@/types/researchIntake'

// 目录新增能力字段时直接采用；旧目录与 DNA 提取页共用，不另造模型名单。
type IntakeModel = ModelInfo & { vision?: boolean; recommended?: boolean }
const models = ref<IntakeModel[]>([])
const modelId = ref('')
const modelLoading = ref(false)
const modelError = ref('')
const users = ref<ResearchUserSummary[]>([])
const tasks = ref<ResearchImportTask[]>([])
const selectedId = ref('')
const detail = ref<ResearchUserDetail | null>(null)
const listLoading = ref(false)
const detailLoading = ref(false)
const listError = ref('')
const detailError = ref('')
const taskError = ref('')
const userQuery = ref('')
const name = ref('')
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')
const uploadNotice = ref('')
const confirming = ref(false)
const confirmError = ref('')
const activeTab = ref<'records' | 'images'>('records')
const answerQuery = ref('')
const section = ref('')
const emotion = ref<ResearchImageEmotion>('ENJOY')
const imageQuery = ref('')
const imageLimit = ref(24)
const preview = ref<ResearchImage | null>(null)
const brokenImages = ref(new Set<string>())
const detailPanel = ref<HTMLElement | null>(null)
const showAllTasks = ref(false)
const lifecycle = new AbortController()
let detailRequest: AbortController | null = null
let detailSequence = 0
let listSequence = 0
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let tasksInFlight = false

const filteredUsers = computed(() => {
  const q = userQuery.value.trim().toLocaleLowerCase()
  return users.value.filter(user => !q || `${user.name} ${user.id} ${JSON.stringify(user.profile)}`.toLocaleLowerCase().includes(q))
})
const sections = computed(() => [...new Set(detail.value?.records.map(record => record.section) ?? [])].filter(Boolean))
const filteredRecords = computed(() => {
  const q = answerQuery.value.trim().toLocaleLowerCase()
  return (detail.value?.records ?? []).filter(record => (!section.value || record.section === section.value) && (!q || `${record.question} ${record.answer} ${record.originalAnswer ?? ''}`.toLocaleLowerCase().includes(q)))
})
const filteredImages = computed(() => {
  const q = imageQuery.value.trim().toLocaleLowerCase()
  return (detail.value?.images ?? []).filter(image => image.emotion === emotion.value && (!q || `${image.code} ${image.description} ${questionFor(image)} ${image.sourceSlide ?? ''}`.toLocaleLowerCase().includes(q)))
})
const visibleImages = computed(() => filteredImages.value.slice(0, imageLimit.value))
const shownTasks = computed(() => showAllTasks.value ? tasks.value : tasks.value.slice(0, 5))
const reviewTaskId = computed(() => {
  if (!detail.value) return ''
  const id = detail.value.provenance.taskId
  return typeof id === 'string' ? id : tasks.value.find(task => task.userId === detail.value?.id && task.status === 'needs_review')?.id ?? ''
})
const stats = computed(() => ({
  records: users.value.reduce((sum, user) => sum + user.recordCount, 0),
  images: users.value.reduce((sum, user) => sum + user.enjoyCount + user.dislikeCount + user.referenceCount, 0),
}))
const imageTabs: { value: ResearchImageEmotion; label: string }[] = [
  { value: 'ENJOY', label: '喜欢 · ENJOY' }, { value: 'DISLIKE', label: '不喜欢 · DISLIKE' }, { value: 'REFERENCE', label: '参考 · REFERENCE' },
]
const taskLabels: Record<ResearchImportTask['status'], string> = { queued: '等待提取', extracting: '正在提取', needs_review: '待确认', completed: '已确认', failed: '提取失败' }

function errorText(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const value = error.response?.data?.detail
    if (typeof value === 'string' && value !== 'Not Found' && value !== 'Internal Server Error') return value
    if (Array.isArray(value)) return value.map(item => item.msg || '参数不正确').join('；')
    if (error.code === 'ECONNABORTED') return '请求超时，请刷新任务列表确认是否已受理。'
  }
  return fallback
}
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未填写'
  if (Array.isArray(value)) return value.map(formatValue).join('、') || '未填写'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
/** 仅用于个人信息展示，保留 API 与 JSON 导出中的原始枚举。 */
function profileValue(key: string, value: unknown): string {
  if (key === 'using_mobile_phone_purchase_price_original' && value && typeof value === 'object' && !Array.isArray(value)) {
    const price = value as Record<string, unknown>
    if (typeof price.display === 'string' && price.display.trim()) return price.display
    const parts = [price.currency, price.amount].filter(part => part !== null && part !== undefined && part !== '')
    return parts.length ? parts.map(String).join(' ') : '未填写'
  }
  if (Array.isArray(value)) return value.map(item => profileValue(key, item)).join('、') || '未填写'
  const labels: Record<string, string> = {
    Indonesia: '印尼', Pakistan: '巴基斯坦', Student: '学生', GeneralOfficeWorker: '普通办公室职员',
    JuniorCollege: '专科', undergraduate: '本科', AppearanceDesign: '外观设计', CameraPerformance: '拍摄表现',
    Memory: '存储容量', TechnologyPioneer: '科技先锋', female: '女', male: '男', Gaming: '游戏',
    NoLimit: '未限定', ID_Samsung: '三星', ID_Oppo: 'OPPO',
  }
  return typeof value === 'string' ? labels[value] ?? formatValue(value) : formatValue(value)
}
function profileLabel(key: string) {
  return ({ country: '国家', city: '城市', age: '年龄', gender: '性别', profession: '职业', academic_qualification: '学历', using_mobile_phone_brand: '手机品牌', using_mobile_phone_model: '手机型号', using_mobile_phone_prices: '手机价格', purchase_drivers: '购买驱动', user_group_tags: '用户标签（原资料）', using_mobile_phone_purchase_price_original: '原币购机价格', mobile_function_usage_preferences: '手机使用偏好' } as Record<string, string>)[key] ?? key
}
function questionFor(image: ResearchImage) { return detail.value?.records.find(record => record.id === image.questionId)?.question ?? '' }
function sourceRoleLabel(role?: string) { return ({ brand_impression: '品牌印象', personal_wish: '个人愿望', example: '举例' } as Record<string, string>)[role ?? ''] ?? '' }
function slideLabel(slide: number | null) { return slide === null ? '页码未提供' : `第 ${slide} 页` }
function imageCount(value: ResearchImageEmotion) { return detail.value?.images.filter(image => image.emotion === value).length ?? 0 }
function imageFailed(id: string) { brokenImages.value = new Set([...brokenImages.value, id]) }
function progress(task: ResearchImportTask) { return task.totalSlides ? Math.min(100, Math.round(task.processedSlides / task.totalSlides * 100)) : 0 }

async function loadModels() {
  modelLoading.value = true
  modelError.value = ''
  try {
    const available = (await fetchModels()) as IntakeModel[]
    if (disposed) return
    models.value = available.filter(model => model.vision !== false)
    if (!models.value.some(model => model.id === modelId.value)) modelId.value = models.value.find(model => model.recommended)?.id ?? models.value.find(model => model.id === 'gpt-6-sol')?.id ?? models.value[0]?.id ?? ''
  } catch (error) { if (!disposed) modelError.value = errorText(error, '模型目录加载失败，请重试。') }
  finally { if (!disposed) modelLoading.value = false }
}
async function loadUsers() {
  const sequence = ++listSequence
  listLoading.value = true
  listError.value = ''
  try {
    const result = await fetchResearchUsers(lifecycle.signal)
    if (disposed || sequence !== listSequence) return
    users.value = result
    if (!selectedId.value && result[0]) void selectUser(result[0].id, false)
  } catch (error) { if (!disposed && sequence === listSequence) listError.value = errorText(error, '用户列表加载失败，请重试。') }
  finally { if (!disposed && sequence === listSequence) listLoading.value = false }
}
async function selectUser(id: string, scroll = true) {
  // 即使旧请求先后交错返回，也不能覆盖当前所选用户。
  const sequence = ++detailSequence
  detailRequest?.abort()
  detailRequest = new AbortController()
  selectedId.value = id
  detail.value = null
  detailError.value = ''
  confirmError.value = ''
  detailLoading.value = true
  answerQuery.value = ''; section.value = ''; imageQuery.value = ''; imageLimit.value = 24
  emotion.value = 'ENJOY'; preview.value = null; brokenImages.value = new Set()
  try {
    const result = await fetchResearchUser(id, detailRequest.signal)
    if (disposed || sequence !== detailSequence) return
    detail.value = result
    if (scroll && window.matchMedia('(max-width: 780px)').matches) await nextTick(() => detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  } catch (error) { if (!disposed && sequence === detailSequence) detailError.value = errorText(error, '用户详情加载失败，请重试。') }
  finally { if (!disposed && sequence === detailSequence) detailLoading.value = false }
}
async function loadTasks() {
  if (disposed || tasksInFlight) return
  tasksInFlight = true
  taskError.value = ''
  try {
    const result = await fetchResearchTasks(lifecycle.signal)
    if (disposed) return
    const changed = result.filter(task => ['needs_review', 'completed'].includes(task.status) && tasks.value.find(old => old.id === task.id)?.status !== task.status)
    tasks.value = result.slice().sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    if (changed.length) {
      await loadUsers()
      if (changed.some(task => task.userId === selectedId.value)) await selectUser(selectedId.value, false)
    }
  } catch (error) { if (!disposed) taskError.value = errorText(error, '任务状态暂时无法更新，请重试。') }
  finally { tasksInFlight = false }
}
async function poll() {
  await loadTasks()
  // 串行轮询防止慢请求重叠；卸载后不再创建计时器。
  if (!disposed) timer = setTimeout(poll, 5000)
}
function chooseFile(event: Event) {
  const candidate = (event.target as HTMLInputElement).files?.[0]
  file.value = null
  uploadError.value = ''; uploadNotice.value = ''
  if (!candidate) return
  if (/\.ppt$/i.test(candidate.name)) uploadError.value = '暂不支持 .ppt，请在 PowerPoint 中另存为 .pptx 后上传。'
  else if (!/\.pptx$/i.test(candidate.name)) uploadError.value = '请选择 .pptx 格式的调研文件。'
  else if (candidate.size > 100 * 1024 * 1024) uploadError.value = '文件不能超过 100 MB。'
  else if (!candidate.size) uploadError.value = '文件为空，请重新选择。'
  else file.value = candidate
  if (!file.value && fileInput.value) fileInput.value.value = ''
}
async function upload() {
  uploadError.value = ''; uploadNotice.value = ''
  if (!file.value || !name.value.trim() || !modelId.value) { uploadError.value = '请填写用户姓名，并选择 PPTX 文件和提取模型。'; return }
  uploading.value = true
  try {
    const task = await importResearchPpt(file.value, name.value.trim(), modelId.value, lifecycle.signal)
    if (disposed) return
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)]
    uploadNotice.value = `已创建 ${task.name} 的提取任务，可在下方查看进度。`
    file.value = null; name.value = ''; if (fileInput.value) fileInput.value.value = ''
    if (task.status === 'needs_review' || task.status === 'completed') { await loadUsers(); await selectUser(task.userId) }
  } catch (error) { if (!disposed) uploadError.value = errorText(error, '上传失败，请检查文件或网络后重试。') }
  finally { if (!disposed) uploading.value = false }
}
async function confirmResult() {
  if (!reviewTaskId.value || !detail.value || confirming.value) return
  const id = detail.value.id
  const taskId = reviewTaskId.value
  confirming.value = true; confirmError.value = ''
  try {
    const task = await confirmResearchTask(taskId, lifecycle.signal)
    if (disposed) return
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)]
    await loadUsers()
    if (selectedId.value === id) await selectUser(id, false)
  } catch (error) { if (!disposed && selectedId.value === id) confirmError.value = errorText(error, '确认失败，请重试。') }
  finally { if (!disposed) confirming.value = false }
}
function exportJson() {
  if (!detail.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify(detail.value, null, 2)], { type: 'application/json;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = `${detail.value.name.replace(/[\\/:*?"<>|]/g, '_')}-调研提取.json`
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function showQuestion(id: string) {
  preview.value = null; activeTab.value = 'records'; answerQuery.value = ''; section.value = ''
  await nextTick()
  document.getElementById(`research-record-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
function openRecordImage(id: string) {
  const image = detail.value?.images.find(item => item.id === id)
  if (image) preview.value = image
}
watch([emotion, imageQuery], () => { imageLimit.value = 24 })
onMounted(() => { void Promise.allSettled([loadUsers(), loadModels(), poll()]) })
onBeforeUnmount(() => { disposed = true; lifecycle.abort(); detailRequest?.abort(); clearTimeout(timer) })
</script>

<template>
  <div class="app-shell research-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <MainNavigation />
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>
    <main>
      <section class="research-hero">
        <div><span class="hero-badge"><TeamOutlined /> USER RESEARCH</span><h1>用户调研</h1><p>从一份 PPT 开始，整理每位用户的回答与图片偏好。</p></div>
        <div class="sample-stats"><div><strong>{{ users.length }}</strong><span>位用户</span></div><div><strong>{{ stats.records }}</strong><span>条问答记录</span></div><div><strong>{{ stats.images }}</strong><span>条图片记录</span></div></div>
      </section>

      <section class="upload-panel" aria-labelledby="upload-title">
        <div class="panel-heading"><div><span class="eyebrow">PPT INFORMATION EXTRACTION</span><h2 id="upload-title">PPT 信息提取</h2><p>上传调研文件，提取完整问答、个人信息与图片标注；完成后由你确认。</p></div><span class="step-label">01 上传 → 02 提取 → 03 确认</span></div>
        <form class="upload-form" @submit.prevent="upload">
          <label class="file-picker" :class="{ filled: file }"><CloudUploadOutlined /><strong>{{ file?.name ?? '选择调研 PPTX' }}</strong><span>{{ file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · 点击更换` : 'PPTX · 最大 100 MB' }}</span><input ref="fileInput" type="file" accept=".pptx,.ppt" :disabled="uploading" aria-label="选择调研PPTX" @change="chooseFile" /></label>
          <label class="field">用户姓名<input v-model="name" maxlength="120" placeholder="例如：调研参与者姓名" :disabled="uploading" /></label>
          <label class="field">提取模型<select v-model="modelId" :disabled="uploading || modelLoading || !models.length"><option disabled value="">{{ modelLoading ? '加载模型…' : '选择模型' }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.name }}{{ model.recommended ? ' · 推荐' : '' }}</option></select></label>
          <button class="primary-button" type="submit" :disabled="uploading || modelLoading || !file || !name.trim() || !modelId">{{ uploading ? '正在上传…' : '开始提取' }} <CloudUploadOutlined /></button>
        </form>
        <div v-if="modelError" class="error-note" role="alert">{{ modelError }} <button type="button" @click="loadModels">重试模型目录</button></div>
        <p v-else-if="!modelLoading && !models.length" class="error-note">暂无可用的视觉模型，请配置模型目录后重试。<button type="button" @click="loadModels">刷新目录</button></p>
        <p v-if="uploadError" class="error-note" role="alert">{{ uploadError }}</p><p v-if="uploadNotice" class="success-note" role="status">{{ uploadNotice }}</p>
      </section>

      <section v-if="tasks.length || taskError" class="task-panel" aria-label="提取任务" aria-live="polite">
        <div class="panel-heading compact"><h2>提取任务 <span>{{ tasks.length }}</span></h2><button type="button" class="text-button" @click="loadTasks"><ReloadOutlined /> 更新状态</button></div>
        <p v-if="taskError" class="error-note" role="alert">{{ taskError }}</p>
        <article v-for="task in shownTasks" :key="task.id" class="task-row">
          <FilePptOutlined class="task-icon" /><div class="task-content"><strong>{{ task.name }}</strong><span class="task-file">{{ task.filename }}</span><p>{{ task.error || task.message || task.stage || taskLabels[task.status] }}</p><div v-if="task.status === 'extracting' || task.status === 'queued'" class="progress-track"><span :style="{ width: `${progress(task)}%` }"></span></div><small>{{ task.model }}<template v-if="task.totalSlides"> · {{ task.processedSlides }} / {{ task.totalSlides }} 页</template></small></div>
          <span class="status-tag" :class="task.status">{{ taskLabels[task.status] }}</span><button v-if="task.status === 'needs_review' || task.status === 'completed'" type="button" class="secondary-button" @click="selectUser(task.userId)">查看结果</button>
        </article>
        <button v-if="tasks.length > 5" type="button" class="text-button" @click="showAllTasks = !showAllTasks">{{ showAllTasks ? '收起历史任务' : `查看全部 ${tasks.length} 个任务` }}</button>
      </section>

      <div class="workspace-heading"><div><span class="eyebrow">RESEARCH LIBRARY</span><h2>用户资料库</h2></div><button type="button" class="text-button" :disabled="listLoading" @click="loadUsers"><ReloadOutlined /> 刷新用户</button></div>
      <p v-if="listError" class="error-note" role="alert">{{ listError }} <button type="button" @click="loadUsers">重试</button></p>
      <div class="user-layout">
        <aside class="user-sidebar" aria-label="用户列表">
          <label class="search-field"><SearchOutlined /><input v-model="userQuery" type="search" placeholder="搜索姓名或个人信息" aria-label="搜索用户" /></label>
          <div v-if="listLoading && !users.length" class="empty-state"><a-spin /><p>正在加载用户…</p></div>
          <button v-for="user in filteredUsers" :key="user.id" type="button" class="user-card" :class="{ selected: selectedId === user.id }" :aria-pressed="selectedId === user.id" @click="selectUser(user.id)">
            <span class="user-avatar">{{ user.name.slice(0, 1) }}</span><span class="user-main"><strong>{{ user.name }}</strong><small>{{ user.profile.country ? profileValue('country', user.profile.country) : '未填写国家' }} · {{ user.recordCount }} 条问答</small><span class="user-counts"><span>{{ user.enjoyCount }} 喜欢</span><span>{{ user.dislikeCount }} 不喜欢</span></span></span><span v-if="user.status === 'needs_review'" class="review-dot" title="待确认" aria-label="待确认"></span>
          </button>
          <div v-if="!listLoading && !filteredUsers.length" class="empty-state"><TeamOutlined /><p>{{ userQuery ? '没有匹配的用户' : listError ? '用户列表暂不可用' : '还没有用户资料' }}</p><small v-if="!userQuery && !listError">上传 PPTX，创建第一份调研记录。</small></div>
        </aside>
        <section ref="detailPanel" class="user-detail" aria-label="用户详情" :aria-busy="detailLoading">
          <div v-if="detailLoading" class="empty-state detail-empty"><a-spin /><p>正在读取用户资料…</p></div>
          <div v-else-if="detailError" class="empty-state detail-empty" role="alert"><p>{{ detailError }}</p><button class="secondary-button" type="button" @click="selectUser(selectedId, false)">重新加载详情</button></div>
          <template v-else-if="detail">
            <div class="detail-heading"><div><span class="eyebrow">USER PROFILE</span><h2>{{ detail.name }}</h2><span class="status-tag" :class="detail.status">{{ detail.status === 'ready' ? '已保存资料' : '提取草稿 · 待确认' }}</span></div><button class="secondary-button" type="button" @click="exportJson"><DownloadOutlined /> 导出 JSON</button></div>
            <div class="source-strip"><FilePptOutlined /><span>{{ detail.sourceFile || '来源文件未提供' }}</span></div>
            <dl class="profile-grid"><div v-for="(value, key) in detail.profile" :key="key"><dt>{{ profileLabel(String(key)) }}</dt><dd>{{ profileValue(String(key), value) }}</dd></div></dl><p v-if="!Object.keys(detail.profile).length" class="muted">暂无个人信息。</p>
            <details class="provenance"><summary>查看提取来源与追溯信息</summary><p>文件 SHA-256：{{ detail.sourceSha256 || '未提供' }}</p><p>用户 ID：{{ detail.id }} · 创建时间：{{ detail.createdAt || '未提供' }}</p><dl><div v-for="(value, key) in detail.provenance" :key="key"><dt>{{ key }}</dt><dd>{{ formatValue(value) }}</dd></div></dl></details>
            <div v-if="detail.warnings.length || detail.missingImageCount" class="warning-note"><strong>需要留意</strong><p v-if="detail.missingImageCount">{{ detail.missingImageCount }} 条图片记录缺少原图，已保留编号与来源。</p><ul v-if="detail.warnings.length"><li v-for="(warning, index) in detail.warnings" :key="index">{{ warning }}</li></ul></div>
            <div v-if="detail.status === 'needs_review'" class="confirm-panel"><div><strong>请核对提取结果</strong><p>确认表示你已核对当前文本与图片的喜欢、不喜欢及参考标注。</p></div><a-popconfirm title="确认当前文本与图片标注正确？" ok-text="确认结果" cancel-text="继续核对" :disabled="!reviewTaskId || confirming" @confirm="confirmResult"><button class="primary-button" type="button" :disabled="!reviewTaskId || confirming">{{ confirming ? '正在确认…' : '确认提取结果' }}</button></a-popconfirm><p v-if="!reviewTaskId" class="error-note">未找到关联提取任务，请刷新任务状态。</p></div>
            <p v-if="confirmError" class="error-note" role="alert">{{ confirmError }}</p>
            <div class="detail-tabs" role="tablist" aria-label="用户资料视图"><button type="button" role="tab" :aria-selected="activeTab === 'records'" :class="{ active: activeTab === 'records' }" @click="activeTab = 'records'">问答文本 <span>{{ detail.records.length }}</span></button><button type="button" role="tab" :aria-selected="activeTab === 'images'" :class="{ active: activeTab === 'images' }" @click="activeTab = 'images'">图片偏好 <span>{{ detail.images.length }}</span></button></div>
            <section v-if="activeTab === 'records'" aria-label="分类问答">
              <div class="filter-row"><label class="search-field"><SearchOutlined /><input v-model="answerQuery" type="search" placeholder="搜索问题与完整回答" aria-label="搜索问答" /></label><select v-model="section" aria-label="筛选问答主题"><option value="">全部主题</option><option v-for="topic in sections" :key="topic" :value="topic">{{ topic }}</option></select></div>
              <p class="result-note">{{ filteredRecords.length }} 条记录 · 保留完整提取文本，可按来源页核对</p>
              <article v-for="record in filteredRecords" :id="`research-record-${record.id}`" :key="record.id" class="answer-card"><div class="answer-meta"><span>{{ record.section || '未分类' }}</span><span v-if="sourceRoleLabel(record.sourceRole)" class="source-role">{{ sourceRoleLabel(record.sourceRole) }}</span><small>{{ slideLabel(record.sourceSlide) }}</small></div><h3>{{ record.question || '未提取到问题' }}</h3><p class="answer-text">{{ record.answer || '未填写回答' }}</p><details v-if="record.originalAnswer?.trim()" class="original-answer"><summary>查看原文</summary><p class="answer-text">{{ record.originalAnswer }}</p></details><div v-if="record.imageIds.length" class="linked-images"><span>关联图片</span><button v-for="id in record.imageIds" :key="id" type="button" :disabled="!detail.images.some(image => image.id === id)" @click="openRecordImage(id)">{{ detail.images.find(image => image.id === id)?.code || id }}</button></div><small class="record-source">{{ record.sourceFile || detail.sourceFile }} · {{ record.id }}</small></article>
              <div v-if="!filteredRecords.length" class="empty-state"><p>{{ detail.records.length ? '没有匹配的问答，试试其他主题或关键词。' : '暂无可展示的问答文本。' }}</p></div>
            </section>
            <section v-else aria-label="图片偏好图库">
              <div class="emotion-tabs" role="tablist" aria-label="图片态度"><button v-for="tab in imageTabs" :key="tab.value" type="button" role="tab" :aria-selected="emotion === tab.value" :class="[tab.value.toLowerCase(), { active: emotion === tab.value }]" @click="emotion = tab.value">{{ tab.label }} <span>{{ imageCount(tab.value) }}</span></button></div>
              <p class="result-note">{{ emotion === 'REFERENCE' ? '参考图仅表示提及或展示，不代表用户喜欢。' : '按用户明确标注的态度展示；点击缩略图放大核对。' }}</p>
              <label class="search-field gallery-search"><SearchOutlined /><input v-model="imageQuery" type="search" placeholder="搜索编号、关联问题或页码" aria-label="搜索图片" /></label>
              <div class="gallery-grid"><article v-for="image in visibleImages" :key="image.id" class="image-card"><button class="image-thumb" type="button" :aria-label="`查看图片 ${image.code || image.id}`" @click="preview = image"><img v-if="image.url && !brokenImages.has(image.id)" :src="image.url" :alt="image.description || image.code || '调研图片'" loading="lazy" @error="imageFailed(image.id)" /><span v-else class="missing-image"><PictureOutlined /><span>{{ image.url ? '图片加载失败' : '原图缺失' }}</span><small>编号与来源仍保留</small></span></button><div class="research-image-caption"><div><strong>{{ image.code || '未编号' }}</strong><span :class="['emotion-tag', image.emotion.toLowerCase()]">{{ image.emotion }}</span></div><small>{{ slideLabel(image.sourceSlide) }}</small><p v-if="image.recovery">{{ image.recovery.label }}</p><p v-if="image.description">{{ image.description }}</p><button v-if="image.questionId && questionFor(image)" type="button" class="question-link" @click="showQuestion(image.questionId)">{{ questionFor(image) }}</button><small v-else>未关联具体问题</small></div></article></div>
              <div v-if="!filteredImages.length" class="empty-state"><PictureOutlined /><p>{{ imageQuery ? '没有匹配的图片记录。' : `暂无 ${emotion} 图片记录。` }}</p></div>
              <div v-else class="load-more"><span>已展示 {{ visibleImages.length }} / {{ filteredImages.length }} 张</span><button v-if="visibleImages.length < filteredImages.length" type="button" class="secondary-button" @click="imageLimit += 24">加载更多图片</button></div>
            </section>
          </template>
          <div v-else class="empty-state detail-empty"><FilePptOutlined /><h3>每一份回答，都有来源</h3><p>选择左侧用户，查看个人信息、完整问答和图片偏好。</p></div>
        </section>
      </div>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>PPT 信息提取与人工核对</span></footer>
    <a-modal :open="Boolean(preview)" :footer="null" centered :width="900" :title="`${preview?.code || '图片详情'} · ${preview?.emotion || ''}`" @cancel="preview = null">
      <div v-if="preview" class="preview-body"><img v-if="preview.url && !brokenImages.has(preview.id)" :src="preview.url" :alt="preview.description || preview.code" @error="imageFailed(preview.id)" /><div v-else class="empty-state"><PictureOutlined /><p>{{ preview.url ? '图片暂时无法加载' : '这条记录缺少原图' }}</p><button v-if="preview.url" class="secondary-button" type="button" @click="brokenImages = new Set([...brokenImages].filter(id => id !== preview?.id))">重试加载</button></div><p v-if="preview.recovery">{{ preview.recovery.label }}</p><p>{{ preview.description || '暂无图片描述' }}</p><p>{{ detail?.sourceFile }} · {{ slideLabel(preview.sourceSlide) }} · {{ preview.code || preview.id }}</p><p>证据范围：{{ preview.evidenceScope || '未说明' }} · 图片状态：{{ preview.status || '未说明' }}</p><button v-if="preview.questionId && questionFor(preview)" type="button" class="question-link" @click="showQuestion(preview.questionId)">查看关联问题：{{ questionFor(preview) }}</button></div>
    </a-modal>
  </div>
</template>

<style scoped>
.research-hero{display:flex;align-items:end;justify-content:space-between;gap:24px;padding:54px 0 30px}.research-hero h1{font-size:40px;margin:14px 0 8px;letter-spacing:-1px}.research-hero p,.panel-heading p{color:#887e98;margin:0;line-height:1.8;font-size:13px}.sample-stats{display:flex;gap:28px}.sample-stats div{display:grid;gap:6px}.sample-stats strong{font-size:28px;font-weight:600;color:#6850ae}.sample-stats span{font-size:11px;color:#91869e}.upload-panel,.task-panel,.user-sidebar,.user-detail{background:rgba(255,255,255,.94);border:1px solid #e8e1ef;border-radius:18px;box-shadow:0 8px 28px #4e397a05}.upload-panel{padding:25px;margin-bottom:20px}.panel-heading,.workspace-heading,.detail-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.panel-heading h2,.workspace-heading h2{font-size:20px;margin:6px 0 7px}.step-label{font-size:11px;color:#a297b5;white-space:nowrap}.upload-form{display:grid;grid-template-columns:1.3fr 1fr 1.2fr auto;align-items:end;gap:16px;margin-top:22px}.field{display:grid;gap:9px;color:#766885;font-size:12px}.field input,.field select,.filter-row>select{width:100%;min-width:0;height:43px;border:1px solid #e5deed;border-radius:9px;background:#fff;padding:0 12px;color:#50435f;font-size:12px}.file-picker{position:relative;display:grid;justify-items:center;gap:5px;min-width:0;padding:16px 12px;border:1px dashed #bba9de;border-radius:12px;background:#f8f5ff;color:#8164b6;cursor:pointer}.file-picker>.anticon{font-size:26px}.file-picker strong{font-size:12px;max-width:100%;overflow-wrap:anywhere}.file-picker>span:not(.anticon){font-size:10px;color:#9988af}.file-picker input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}.file-picker:focus-within{outline:2px solid #9d80cf;outline-offset:3px}.primary-button,.secondary-button,.text-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;cursor:pointer;font:inherit;font-size:12px;border-radius:9px}.primary-button{background:#8664b5;border:1px solid #8664b5;color:white;padding:12px 17px;white-space:nowrap}.primary-button:hover:not(:disabled){background:#70519e}.secondary-button{border:1px solid #e1d8ed;background:#faf8fe;padding:8px 12px;color:#79619b}.text-button{background:none;border:0;color:#8b70b0;padding:5px}.primary-button:disabled,.secondary-button:disabled,button:disabled{cursor:not-allowed;opacity:.5}.error-note,.warning-note,.success-note{padding:11px 14px;border-radius:9px;font-size:12px;line-height:1.8;overflow-wrap:anywhere}.error-note{color:#aa4951;background:#fff2f2}.error-note button{border:0;background:none;color:inherit;text-decoration:underline;cursor:pointer}.success-note{color:#49826b;background:#eff9f3}.task-panel{padding:18px 22px;margin-bottom:25px}.compact h2{font-size:15px;margin:0}.compact h2 span{font-weight:400;color:#a397af;font-size:12px}.task-row{display:flex;gap:13px;align-items:center;padding:15px 0;border-bottom:1px solid #f0eaf5}.task-row:last-of-type{border-bottom:0}.task-icon{font-size:25px;color:#b995d0}.task-content{flex:1;min-width:0}.task-content strong{font-size:13px;color:#51405f}.task-file{font-size:11px;color:#a499b0;margin-left:10px;overflow-wrap:anywhere}.task-content p{font-size:12px;color:#8d7f99;white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0}.task-content small{font-size:10px;color:#ab9eb5}.progress-track{height:4px;border-radius:4px;background:#eee7f6;margin:8px 0;width:100%;max-width:420px;overflow:hidden}.progress-track span{display:block;height:100%;background:#ad8bce;transition:width .3s}.status-tag{display:inline-block;white-space:nowrap;background:#f2edf7;color:#9783ac;border-radius:6px;padding:4px 8px;font-size:10px}.status-tag.needs_review{color:#a87b2d;background:#fff6e3}.status-tag.ready,.status-tag.completed{color:#629780;background:#edf7f1}.status-tag.failed{color:#bc6671;background:#fff0f1}.workspace-heading{margin:30px 0 16px}.user-layout{display:grid;grid-template-columns:275px minmax(0,1fr);gap:22px;align-items:start;margin-bottom:65px}.user-sidebar{padding:12px;position:sticky;top:18px;max-height:85vh;overflow:auto}.search-field{display:flex;align-items:center;gap:8px;padding:0 11px;border:1px solid #e7dfed;background:#fcfaff;border-radius:9px;color:#ac9bbb;height:39px;min-width:0}.search-field input{min-width:0;flex:1;width:100%;border:0;outline:0;background:transparent;color:#665475;font-size:12px}.search-field:focus-within{outline:2px solid #c4afdf;outline-offset:1px}.user-card{display:flex;align-items:center;gap:10px;width:100%;padding:15px 10px;border:1px solid transparent;background:transparent;border-radius:11px;margin-top:7px;text-align:left;cursor:pointer}.user-card:hover{background:#faf7fe}.user-card.selected{background:#f4eefb;border-color:#e7daf3}.user-avatar{flex-shrink:0;display:grid;place-items:center;width:34px;height:38px;border-radius:11px;background:#ede2f7;color:#9b7bbd;font-size:16px}.user-main{min-width:0;display:grid;gap:5px}.user-main strong{font-size:12px;color:#5d486b;overflow-wrap:anywhere}.user-main small{font-size:10px;color:#a18fae}.user-counts{display:flex;gap:8px;font-size:10px;color:#a08bb2}.review-dot{margin-left:auto;flex-shrink:0;width:6px;height:6px;border-radius:50%;background:#d8ad61}.user-detail{padding:27px;min-width:0;scroll-margin-top:15px}.detail-heading{align-items:start}.detail-heading h2{font-size:24px;margin:6px 0 10px;color:#51405f;overflow-wrap:anywhere}.source-strip{display:flex;align-items:start;gap:8px;color:#a695b4;font-size:11px;margin:17px 0;overflow-wrap:anywhere}.profile-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:20px 0}.profile-grid dt,.provenance dt{font-size:10px;color:#a294ad;margin-bottom:5px}.profile-grid dd,.provenance dd{font-size:12px;color:#6d5e79;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.provenance{font-size:11px;color:#a395ad;border-top:1px solid #f0eaf4;padding:12px 0;overflow-wrap:anywhere}.provenance summary{cursor:pointer}.provenance dl{display:grid;gap:10px}.warning-note{background:#fffaed;color:#9d854b;margin:12px 0}.warning-note ul{padding-left:18px;margin:5px 0}.warning-note p{margin:5px 0}.confirm-panel{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;padding:16px;background:#f5effb;border-radius:12px;margin:16px 0;color:#7e639a}.confirm-panel strong{font-size:13px}.confirm-panel p{font-size:11px;line-height:1.8;margin:4px 0 0}.detail-tabs{display:flex;gap:22px;border-bottom:1px solid #eae2f1;margin:20px 0}.detail-tabs button{border:0;border-bottom:2px solid transparent;background:none;cursor:pointer;color:#a797b2;padding:12px 2px;font-size:13px}.detail-tabs button.active{color:#8b65b3;border-color:#9870bd}.detail-tabs span{font-size:10px;margin-left:6px}.filter-row{display:flex;gap:12px}.filter-row .search-field{flex:1}.filter-row>select{width:180px;height:39px}.result-note,.muted{font-size:11px;color:#a799b1;line-height:1.7}.answer-card{padding:19px 0;border-bottom:1px solid #f0eaf5;scroll-margin-top:30px}.answer-meta{display:flex;align-items:center;justify-content:space-between;gap:10px}.answer-meta>span{color:#9777b4;background:#f4effa;padding:4px 8px;border-radius:5px;font-size:10px}.answer-meta small{font-size:10px;color:#b2a5bd}.answer-card h3{font-size:13px;line-height:1.8;color:#685475;margin:12px 0 8px}.answer-text{white-space:pre-wrap;overflow-wrap:anywhere;color:#887792;font-size:12px;line-height:1.95;margin:0}.original-answer{margin-top:12px;padding:10px 12px;background:#faf7fd;border-radius:8px}.original-answer summary{cursor:pointer;color:#9b7bb4;font-size:11px}.original-answer .answer-text{margin-top:9px}.record-source{display:block;font-size:9px;color:#b6a9be;margin-top:12px;overflow-wrap:anywhere}.linked-images{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin-top:12px;font-size:10px;color:#ac9bb7}.linked-images button{border:1px solid #e8dff0;border-radius:5px;background:white;color:#9978b3;font-size:10px;cursor:pointer;padding:3px 7px}.emotion-tabs{display:flex;flex-wrap:wrap;gap:8px}.emotion-tabs button{border:1px solid #e9e1ef;color:#a493b2;background:white;border-radius:8px;padding:9px 12px;font-size:11px;cursor:pointer}.emotion-tabs button.active{background:#f2ebfa;border-color:#d9c5eb;color:#8964a9}.emotion-tabs button.dislike.active{background:#fff0f3;border-color:#edccd5;color:#b47788}.emotion-tabs button.reference.active{background:#f1f3f8;border-color:#d8dce7;color:#7c879c}.emotion-tabs span{font-size:10px;margin-left:5px}.gallery-search{margin:15px 0}.gallery-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.image-card{overflow:hidden;border:1px solid #eae3f0;border-radius:12px;min-width:0}.image-thumb{display:flex;align-items:center;justify-content:center;overflow:hidden;width:100%;height:185px;border:0;border-bottom:1px solid #eee8f4;background:#f8f5fb;cursor:pointer;padding:10px}.image-thumb img{width:100%;height:100%;min-height:0;max-height:100%;object-fit:contain}.missing-image{display:grid;justify-items:center;gap:8px;color:#bdafc8;font-size:11px}.missing-image>.anticon{font-size:25px}.missing-image small{font-size:9px}.research-image-caption{padding:11px;display:grid;gap:6px}.research-image-caption>div{display:flex;align-items:center;justify-content:space-between;gap:4px}.research-image-caption strong{font-size:12px;color:#816792;overflow-wrap:anywhere}.research-image-caption small{color:#b1a0bd;font-size:9px}.research-image-caption p{font-size:10px;color:#9c89aa;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}.emotion-tag{font-size:8px;color:#91a699}.emotion-tag.dislike{color:#bd8597}.emotion-tag.reference{color:#9399ae}.question-link{border:0;background:none;text-align:left;padding:0;font-size:10px;color:#9e7ab9;line-height:1.6;cursor:pointer;text-decoration:underline;overflow-wrap:anywhere}.empty-state{display:grid;justify-items:center;text-align:center;padding:35px 15px;gap:8px;color:#b5a5c0;font-size:12px}.empty-state>.anticon{font-size:28px}.empty-state p,.empty-state h3{margin:0;line-height:1.8}.empty-state h3{color:#9b83ad;font-size:16px;font-weight:500}.empty-state small{font-size:10px}.detail-empty{min-height:350px;align-content:center}.load-more{display:flex;justify-content:center;align-items:center;gap:14px;margin-top:20px;color:#b19fbe;font-size:10px}.preview-body{display:grid;gap:10px}.preview-body>img{max-width:100%;max-height:65vh;object-fit:contain;justify-self:center}.preview-body p{margin:0;font-size:12px;line-height:1.8;color:#8b779a;white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:1100px){.upload-form{grid-template-columns:1fr 1fr}.file-picker{grid-row:span 2;align-self:stretch;align-content:center}.upload-form>.primary-button{grid-column:2}.user-layout{grid-template-columns:230px minmax(0,1fr);gap:15px}.gallery-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.profile-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.step-label{display:none}}
@media(max-width:780px){.research-hero{display:block;padding-top:35px}.sample-stats{margin-top:24px}.user-layout{grid-template-columns:1fr}.user-sidebar{position:static;max-height:290px}.user-detail{padding:20px}.task-row{flex-wrap:wrap}.task-content{flex-basis:65%}.task-row>.status-tag{margin-left:38px}.task-row>.secondary-button{margin-left:auto}.detail-heading{flex-wrap:wrap}.upload-panel{padding:20px}}
@media(max-width:480px){.research-hero h1{font-size:34px}.upload-form{grid-template-columns:1fr}.file-picker{grid-row:auto}.upload-form>.primary-button{grid-column:auto}.sample-stats{justify-content:space-between;gap:12px}.sample-stats strong{font-size:24px}.filter-row{flex-wrap:wrap}.filter-row>.search-field,.filter-row>select{width:100%;flex-basis:100%}.user-detail{padding:15px}.profile-grid{gap:12px}.gallery-grid{gap:8px}.image-thumb{height:145px}.emotion-tabs button{padding:8px;font-size:10px}.task-file{display:block;margin:4px 0}.confirm-panel>.primary-button{width:100%}.research-image-caption>div{flex-wrap:wrap}}
</style>
