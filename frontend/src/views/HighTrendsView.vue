<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { Modal } from 'ant-design-vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRightOutlined, BulbOutlined, MessageOutlined, RobotOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { fetchModels } from '@/api/dna'
import { createTrendTask, fetchTrendCatalog, fetchTrendTask, fetchTrendTasks, previewTrends, resumeTrendTask, trendDownloadUrl } from '@/api/highTrends'
import HighTrendCard from '@/components/HighTrendCard.vue'
import HighTrendUserGallery from '@/components/HighTrendUserGallery.vue'
import SafeMarkdown from '@/components/SafeMarkdown.vue'
import type { ModelInfo } from '@/types/dna'
import type { HighTrendCatalog, HighTrendPreview, HighTrendRequest, HighTrendStatus, HighTrendTask } from '@/types/highTrends'

function localDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const today = new Date()
const earlier = new Date(today)
// 月底回退时钳制到目标月末，避免 31 日溢出到下一个月。
earlier.setDate(1)
earlier.setMonth(earlier.getMonth() - 2)
earlier.setDate(Math.min(today.getDate(), new Date(earlier.getFullYear(), earlier.getMonth() + 1, 0).getDate()))
const route = useRoute()
const router = useRouter()
const dataset = ref<NonNullable<HighTrendRequest['dataset']>>('article_table_2_selected_5')
const allDates = ref(false)
const category = ref('')
const startDate = ref(localDate(earlier))
const endDate = ref(localDate(today))
const modelId = ref('')
const prompt = ref('')
const userScope = ref<'auto' | 'all' | 'first'>('auto')
const userLimit = ref<number | null>(20)
const maxCalls = ref<number | null>(24)
const models = ref<ModelInfo[]>([])
const catalog = ref<HighTrendCatalog | null>(null)
const preview = ref<HighTrendPreview | null>(null)
const previewLoading = ref(false)
const starting = ref(false)
const resuming = ref(false)
const resumeMaxCalls = ref<number | null>(24)
const historyLoading = ref(false)
const taskLoading = ref(false)
const history = ref<HighTrendTask[]>([])
const task = ref<HighTrendTask | null>(null)
const selectedId = ref('')
const error = ref('')
const pollError = ref('')
let disposed = false
let pollingTimer: ReturnType<typeof setTimeout> | undefined
let selectionVersion = 0
let previewVersion = 0

const statusLabels: Record<HighTrendStatus, string> = {
  queued: '等待执行', running: '正在归纳', completed: '已完成', partial: '部分完成', empty: '未形成正文', failed: '执行失败',
}
const isActive = (item: HighTrendTask | null) => item?.status === 'queued' || item?.status === 'running'
const running = computed(() => isActive(task.value))
const anyRunning = computed(() => history.value.some(isActive) || running.value)
const validRange = computed(() => allDates.value || Boolean(startDate.value && endDate.value && startDate.value <= endDate.value))
const validRequest = computed(() => validRange.value && (userScope.value !== 'first' || (Number.isInteger(userLimit.value) && (userLimit.value ?? 0) > 0)) && Boolean(modelId.value) && Number.isInteger(maxCalls.value) && (maxCalls.value ?? 0) >= 1 && (maxCalls.value ?? 0) <= 100)
const result = computed(() => task.value?.result)
const cards = computed(() => result.value?.trends ?? [])
const categories = computed(() => result.value?.trend_categories ?? [])
const filteredCards = computed(() => !category.value ? cards.value : cards.value.filter(card => card.clustering_labels?.includes(category.value)))
const missingImageWarnings = computed(() => (result.value?.warnings ?? []).filter(warning => /来源 trend:.*图片.*不可用/.test(warning)))
const otherWarnings = computed(() => (result.value?.warnings ?? []).filter(warning => !/来源 trend:.*图片.*不可用/.test(warning)))
const gaps = computed(() => result.value?.user_research_gaps?.directions ?? [])
const percent = computed(() => {
  const current = task.value
  if (!current?.total_jobs) return 0
  return Math.min(100, Math.round(current.completed_jobs / current.total_jobs * 100))
})

function requestBody(): HighTrendRequest {
  return { dataset: dataset.value, all_dates: allDates.value, start_date: startDate.value, end_date: endDate.value, model_id: modelId.value, max_calls: maxCalls.value ?? 24, prompt: prompt.value.trim(), user_scope: userScope.value, user_limit: userScope.value === 'first' ? userLimit.value : null }
}
function datasetLabel(value: HighTrendRequest['dataset']) {
  return value === 'article_table_2_selected_5' ? '文章信息表 2 × 精选 5 位用户' : '原版趋势 × 全部用户资料'
}
function dateScope(request: HighTrendRequest) {
  return request.all_dates ? '全部日期（含无日期资料）' : `${request.start_date} — ${request.end_date}`
}
/** 历史任务只展示冻结的实际数量，不能按原提示词重新推算范围。 */
function taskScope(current: HighTrendTask) {
  const label = current.scope?.label ?? '原任务冻结范围'
  return current.counts ? `${label} · 实际选中 ${current.counts.selected_users} 位，其中 ${current.counts.users_with_text} 位有有效文本` : label
}
function readError(value: unknown, fallback: string) {
  const detail = (value as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map(item => String(item.msg ?? '参数无效').replace(/^Value error, /, '')).join('；')
  return typeof detail === 'string' ? detail : value instanceof Error ? value.message : fallback
}
function dateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function performanceValue(key: string) {
  const value = task.value?.performance?.[key]
  return typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '未提供'
}
function updateHistory(current: HighTrendTask) {
  const index = history.value.findIndex(item => item.id === current.id)
  if (index < 0) history.value.unshift(current)
  else history.value[index] = current
}

watch([startDate, endDate, modelId, maxCalls, prompt, userScope, userLimit, dataset, allDates], () => {
  previewVersion++
  preview.value = null
  previewLoading.value = false
})

watch(dataset, async value => {
  catalog.value = null
  try {
    const next = await fetchTrendCatalog(value)
    if (!disposed && dataset.value === value) catalog.value = next
  } catch (cause) { if (dataset.value === value) error.value = readError(cause, '资料目录读取失败') }
})
watch(() => route.query.task, value => {
  if (typeof value === 'string' && value !== selectedId.value) void selectTask(value)
})

async function estimate() {
  if (!validRequest.value) return
  const version = ++previewVersion
  previewLoading.value = true
  error.value = ''
  try {
    const estimate = await previewTrends(requestBody())
    if (!disposed && version === previewVersion) preview.value = estimate
  } catch (cause) {
    if (version === previewVersion) error.value = readError(cause, '范围预估失败')
  } finally {
    if (version === previewVersion) previewLoading.value = false
  }
}

async function refreshHistory() {
  historyLoading.value = true
  try {
    const entries = await fetchTrendTasks()
    if (!disposed) history.value = entries
  } catch (cause) { error.value = readError(cause, '历史任务读取失败') }
  finally { historyLoading.value = false }
}

/** 每次选择使旧请求失效；串行定时轮询，避免慢响应覆盖新任务或卸载后的状态。 */
async function selectTask(id: string) {
  clearTimeout(pollingTimer)
  const version = ++selectionVersion
  selectedId.value = id
  category.value = ''
  if (route.query.task !== id) void router.replace({ query: { ...route.query, task: id } })
  task.value = null
  taskLoading.value = true
  pollError.value = ''
  await loadTask(id, version)
  if (version === selectionVersion) taskLoading.value = false
}

function confirmResume() {
  const current = task.value
  const cap = resumeMaxCalls.value
  if (!current?.resume?.can_resume || anyRunning.value || resuming.value || !cap || !Number.isInteger(cap) || cap > 100 || cap < current.resume.minimum_max_calls) return
  Modal.confirm({
    title: '从未完成步骤继续？',
    content: `沿用本任务冻结的资料（${taskScope(current)}）、模型与文字要求，复用 ${current.completed_jobs} 个已完成步骤。已尝试 ${current.resume.used_calls} 次，剩余预计 ${current.resume.remaining_jobs} 步；累计调用上限 ${cap} 次。继续会产生新的模型调用。`,
    okText: '确认继续', cancelText: '暂不继续', centered: true,
    async onOk() {
      if (resuming.value || disposed) return
      resuming.value = true
      try {
        const updated = await resumeTrendTask(current.id, cap)
        if (!disposed) { updateHistory(updated); await selectTask(updated.id) }
      } catch (cause) { error.value = readError(cause, '继续任务失败') }
      finally { resuming.value = false }
    },
  })
}

async function loadTask(id: string, version: number) {
  try {
    const current = await fetchTrendTask(id)
    if (disposed || version !== selectionVersion) return
    if (!task.value) resumeMaxCalls.value = current.request.max_calls
    task.value = current
    updateHistory(current)
    pollError.value = ''
    if (isActive(current)) pollingTimer = setTimeout(() => void loadTask(id, version), 2000)
  } catch (cause) {
    if (disposed || version !== selectionVersion) return
    pollError.value = readError(cause, '任务进度读取失败')
    // 网络短暂失败保留当前结果并继续查询，不把读取失败误标为任务失败。
    pollingTimer = setTimeout(() => void loadTask(id, version), 2000)
  }
}

function confirmStart() {
  if (!preview.value || !validRequest.value || anyRunning.value || starting.value) return
  const body = requestBody()
  const modelName = models.value.find(model => model.id === body.model_id)?.name ?? body.model_id
  Modal.confirm({
    title: '确认生成高潜趋势洞察？',
    content: h('div', { class: 'confirm-copy' }, [
      h('p', `数据来源：${datasetLabel(body.dataset)}`),
      h('p', `趋势日期：${dateScope(body)}`),
      h('p', `模型：${modelName}`),
      body.prompt ? h('p', { style: 'white-space: pre-wrap; max-height: 160px; overflow: auto;' }, `你的要求：${body.prompt}`) : null,
      h('p', `用户范围：${preview.value.scope.label}；实际选中 ${preview.value.counts.selected_users} 位。`),
      h('p', preview.value.scope.note),
      h('p', `纳入 ${preview.value.counts.selected_trends} 条趋势、${preview.value.counts.users_with_text} 位有文本的用户。`),
      h('p', `预计调用 ${preview.value.plan.planned_calls} 次，上限 ${body.max_calls} 次；开始后将调用模型并保存结果。`),
    ]),
    okText: '确认并开始', cancelText: '返回检查', centered: true,
    async onOk() {
      if (disposed || starting.value) return
      starting.value = true
      error.value = ''
      try {
        const created = await createTrendTask(body)
        if (disposed) return
        updateHistory(created)
        await selectTask(created.id)
      } catch (cause) { error.value = readError(cause, '任务启动失败') }
      finally { starting.value = false }
    },
  })
}

onMounted(async () => {
  const loaded = await Promise.allSettled([fetchModels(), fetchTrendCatalog(dataset.value), fetchTrendTasks()])
  if (disposed) return
  const [modelResponse, catalogResponse, historyResponse] = loaded
  const problems: string[] = []
  if (modelResponse.status === 'fulfilled') {
    models.value = modelResponse.value
    modelId.value = models.value[0]?.id ?? ''
  } else problems.push(readError(modelResponse.reason, '模型列表读取失败'))
  if (catalogResponse.status === 'fulfilled') catalog.value = catalogResponse.value
  else problems.push(readError(catalogResponse.reason, '资料目录读取失败'))
  if (historyResponse.status === 'fulfilled') {
    history.value = historyResponse.value
    const latest = history.value.find(isActive) ?? history.value[0]
    if (typeof route.query.task !== 'string' && latest) void selectTask(latest.id)
  } else problems.push(readError(historyResponse.reason, '历史任务读取失败'))
  if (typeof route.query.task === 'string') void selectTask(route.query.task)
  error.value = problems.join('；')
})
onUnmounted(() => {
  disposed = true
  selectionVersion++
  previewVersion++
  clearTimeout(pollingTimer)
})
</script>

<template>
  <div class="app-shell trends-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink to="/article-trends">趋势洞察</RouterLink><RouterLink class="active" to="/high-trends">高潜趋势</RouterLink><RouterLink to="/design-modification">设计修改</RouterLink><RouterLink to="/user-research">用研聚合</RouterLink><RouterLink to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>
    <main>
      <section class="hero trend-hero">
        <div class="hero-badge"><BulbOutlined /> TREND &amp; PEOPLE</div>
        <p>从趋势资料与用户研究的交集中，提炼值得关注的通用设计方向。每个方向保留来源、用户提及与图片线索，方便你继续判断。</p>
      </section>
      <div v-if="error" class="page-alert"><a-alert type="error" show-icon :message="error" closable @close="error = ''" /></div>
      <section class="workspace-card scope-panel">
        <div class="section-heading"><div><span class="eyebrow">01 / 选择观察范围</span><p>日期筛选趋势资料；用户范围可在下方选择，也可从文字要求中识别。</p></div><span class="range-badge">按已有趋势大类归纳</span></div>
        <div class="dataset-controls"><label for="trend-dataset">资料来源</label><a-select id="trend-dataset" v-model:value="dataset" :options="[{ value: 'article_table_2_selected_5', label: '文章信息表 2 × 精选 5 位用户' }, { value: 'original', label: '原版趋势 × 全部用户资料' }]" /><a-checkbox v-model:checked="allDates">全部日期（含无日期资料）</a-checkbox></div>
        <div class="scope-form">
          <div class="date-field"><label for="trend-start">开始日期 <span>*</span></label><input id="trend-start" v-model="startDate" type="date" :disabled="allDates" :required="!allDates" :max="endDate || undefined" /></div>
          <ArrowRightOutlined class="date-arrow" />
          <div class="date-field"><label for="trend-end">结束日期 <span>*</span></label><input id="trend-end" v-model="endDate" type="date" :disabled="allDates" :required="!allDates" :min="startDate || undefined" /></div>
          <div class="model-field"><label for="trend-model">推理模型 <span>*</span></label><a-select id="trend-model" v-model:value="modelId" size="large" placeholder="选择模型" :options="models.map(model => ({ value: model.id, label: model.name }))" /></div>
          <a-button :loading="previewLoading" :disabled="!validRequest" size="large" @click="estimate">预估范围</a-button>
        </div>
        <div class="user-scope-controls">
          <label for="trend-user-scope">用户研究范围</label>
          <a-select id="trend-user-scope" v-model:value="userScope" :options="[{ value: 'auto', label: '从文字识别，未指定则全部' }, { value: 'first', label: '前 N 位用户' }, { value: 'all', label: '全部用户' }]" />
          <template v-if="userScope === 'first'"><label for="trend-user-limit">用户数量</label><a-input-number id="trend-user-limit" v-model:value="userLimit" :min="1" :precision="0" /></template>
          <p>按原始资料顺序选用户，再保留有效回答。文字与选项冲突时会提示修改。</p>
        </div>
        <p v-if="!validRange" class="field-error">请填写完整日期，开始日期不能晚于结束日期。</p>
        <details class="advanced-options"><summary>高级选项</summary><label for="trend-max-calls">模型调用上限</label><a-input-number id="trend-max-calls" v-model:value="maxCalls" :min="1" :max="100" :precision="0" /><p>默认 24 次，可设为 1–100 次；提高上限可能增加模型用量。</p></details>
        <p v-if="catalog" class="catalog-note">资料库：{{ catalog.trend_count }} 条趋势 · {{ catalog.user_count }} 位用户<span v-if="catalog.min_date"> · 趋势日期 {{ catalog.min_date }} — {{ catalog.max_date }}</span><span v-if="catalog.undated_count"> · {{ catalog.undated_count }} 条无日期趋势{{ allDates ? '纳入本轮' : '不纳入筛选' }}</span></p>
        <div class="chat-box trend-chat">
          <div class="agent-avatar"><RobotOutlined /></div>
          <div class="chat-content">
            <label for="trend-prompt" class="chat-label"><MessageOutlined /> 告诉 Agent 你关注什么</label>
            <a-textarea id="trend-prompt" v-model:value="prompt" :rows="4" :maxlength="4000" show-count
              placeholder="例如：重点关注色彩、材质和触感上的共性，不限定产品品类。每个方向请给出具体的设计启发，并保留用户之间不同的偏好。" />
            <p class="catalog-note">可填写“只选择前 20 个用户”，代码会在整理资料前筛选。支持前 N 位或全部用户；其他人群条件暂不自动筛选。也可补充设计关注方向。</p>
          </div>
        </div>
        <div v-if="preview" class="preview-result">
          <p class="resolved-scope">采用范围：{{ preview.scope.label }} · 实际选中 {{ preview.counts.selected_users }} / {{ preview.counts.source_users }} 位用户 · {{ preview.scope.origin === 'prompt' ? '从文字识别' : preview.scope.origin === 'option' ? '来自范围选项' : '未指定数量，采用全部' }}<br /><small>{{ preview.scope.note }}</small></p>
          <div class="preview-stats"><div><strong>{{ preview.counts.selected_trends }}</strong><span>条趋势</span></div><div><strong>{{ preview.counts.users_with_text }}</strong><span>位有文本用户</span></div><div><strong>{{ preview.counts.user_records }}</strong><span>条用研记录</span></div><div><strong>{{ preview.plan.planned_calls }}</strong><span>次预计模型调用</span></div></div>
          <a-button class="run-button" type="primary" :loading="starting" :disabled="anyRunning || !preview.counts.selected_trends || !preview.counts.users_with_text" @click="confirmStart">确认并生成洞察 <ArrowRightOutlined /></a-button>
          <p class="estimate-note">预计处理 {{ preview.plan.input_source_chars.toLocaleString() }} 字符，{{ preview.plan.map_jobs ? `分 ${preview.plan.map_jobs} 组归纳` : '直接归纳' }}；模型调用上限 {{ maxCalls }} 次。{{ anyRunning ? '已有任务执行中，可在历史任务中查看进度。' : '' }}</p>
          <a-alert v-for="warning in preview.warnings ?? []" :key="warning" type="warning" :message="warning" show-icon />
          <a-alert v-if="!preview.counts.selected_trends || !preview.counts.users_with_text" type="info" message="当前范围缺少趋势或用户文本，请调整日期或补充资料。" show-icon />
        </div>
      </section>

      <section class="insights-workspace">
        <aside class="history-panel workspace-card">
          <div class="history-head"><h2>历史任务</h2><a-button type="text" aria-label="刷新历史任务" :loading="historyLoading" @click="refreshHistory"><ReloadOutlined /></a-button></div>
          <p v-if="!history.length" class="empty-copy">生成后，洞察与执行记录会保留在这里。</p>
          <button v-for="entry in history" :key="entry.id" class="history-item" :class="{ selected: selectedId === entry.id }" @click="selectTask(entry.id)">
            <span class="history-date">{{ dateScope(entry.request) }}</span><a-tag :color="entry.status === 'completed' ? 'green' : entry.status === 'failed' ? 'red' : 'purple'">{{ statusLabels[entry.status] }}</a-tag><small>{{ datasetLabel(entry.request.dataset) }}</small><small>{{ taskScope(entry) }}</small><small>{{ dateTime(entry.created_at) }}</small>
          </button>
        </aside>
        <div class="insights-content">
          <a-alert v-if="pollError" type="warning" :message="pollError" description="正在自动重试读取任务，不会重复启动模型。" show-icon />
          <a-spin v-if="taskLoading" class="task-spinner" tip="正在读取任务…" />
          <section v-if="task" class="workspace-card task-overview" aria-live="polite">
            <div class="section-heading"><div><span class="eyebrow">02 / 洞察档案</span><h2>{{ statusLabels[task.status] }}</h2><p>{{ task.message }}</p></div><div v-if="result" class="downloads"><a :href="trendDownloadUrl(task.id, 'markdown')" download>Markdown ↓</a><a :href="trendDownloadUrl(task.id, 'json')" download>JSON ↓</a><a :href="trendDownloadUrl(task.id, 'images_markdown')" download>图片路径 ↓</a><a :href="trendDownloadUrl(task.id, 'performance')" download>用量记录 ↓</a></div></div>
            <p class="resolved-scope">{{ datasetLabel(task.request.dataset) }} · {{ dateScope(task.request) }}<br />{{ taskScope(task) }}</p>
            <template v-if="running"><a-progress :percent="percent" :show-info="false" status="active" stroke-color="#6257d8" /><p class="catalog-note">已完成 {{ task.completed_jobs }} / {{ task.total_jobs }} 项 · 每 2 秒更新</p></template>
            <a-alert v-if="task.status === 'partial'" type="warning" message="本轮部分完成，已保留可用结果。请结合下方提示与来源判断。" show-icon />
            <a-alert v-if="task.status === 'empty'" type="info" message="本轮没有可交付的研究正文，可以查看执行记录或调整范围重新生成。" show-icon />
            <a-alert v-if="task.error" type="error" :message="task.error" show-icon />
            <details v-if="task.error_history?.length" class="execution-details"><summary>错误详情 · {{ task.error_history.length }} 次</summary><div v-for="(failure, index) in task.error_history" :key="index"><template v-if="failure"><p>{{ dateTime(failure.time) }} · {{ failure.job_id || '流程阶段' }} · {{ failure.code }}</p><p>{{ failure.message }} 类型：{{ failure.exception_type }}<span v-if="failure.seconds != null"> · 耗时 {{ failure.seconds }} 秒</span><span v-if="failure.http_status"> · HTTP {{ failure.http_status }}</span></p></template></div></details>
            <div v-if="task.resume?.can_resume" class="resume-panel">
              <p>已完成 {{ task.completed_jobs }} 步将直接复用；已尝试 {{ task.resume.used_calls }} 次，剩余预计 {{ task.resume.remaining_jobs }} 步。</p>
              <label for="resume-max-calls">累计调用上限</label>
              <a-input-number id="resume-max-calls" v-model:value="resumeMaxCalls" :min="1" :max="100" :precision="0" />
              <a-button type="primary" :loading="resuming" :disabled="anyRunning || !resumeMaxCalls || !Number.isInteger(resumeMaxCalls) || resumeMaxCalls < task.resume.minimum_max_calls || resumeMaxCalls > 100" @click="confirmResume">从失败步骤继续</a-button>
              <p v-if="(resumeMaxCalls ?? 0) < task.resume.minimum_max_calls" class="field-error">完成剩余流程，累计调用上限至少需要 {{ task.resume.minimum_max_calls }} 次。</p>
            </div>
            <details v-if="task.events?.length" class="execution-details"><summary>执行记录 · {{ task.events.length }} 条</summary><ol><li v-for="(event, index) in task.events" :key="index"><time>{{ dateTime(event.time) }}</time><span>{{ event.message }}</span></li></ol></details>
            <details v-if="task.performance" class="execution-details"><summary>调用与用量记录</summary><p v-if="task.performance.engine">执行方式：{{ task.performance.engine }}<span v-if="task.performance.host_analysis_steps"> · 归纳步骤 {{ task.performance.host_analysis_steps }}</span></p><p>实际模型调用 {{ performanceValue('actual_model_calls') }} 次 · 调用耗时 {{ performanceValue('call_seconds') }} 秒</p><p>已知输入 {{ performanceValue('input_tokens_known') }} tokens · 已知输出 {{ performanceValue('output_tokens_known') }} tokens · 缺少用量记录 {{ performanceValue('missing_usage_calls') }} 次</p><p>仅统计已取得的用量。宿主模型或服务商未返回用量时显示“未提供”，不记作 0。</p></details>
            <p class="task-meta">{{ dateScope(task.request) }} · {{ models.find(model => model.id === task?.request.model_id)?.name || task.request.model_id }} · {{ dateTime(task.created_at) }}</p>
            <div v-if="task.request.prompt" class="task-prompt"><span><MessageOutlined /> 你的要求</span><p>{{ task.request.prompt }}</p></div>
          </section>
          <div v-if="!task && !taskLoading" class="welcome-empty"><BulbOutlined /><h2>下一份灵感，从交集开始</h2><p>选好日期并预估范围，或打开一份历史洞察。</p></div>
          <template v-if="result">
            <div v-if="task" class="image-review-entry"><div><strong>整理这份结果的图片</strong><p>按趋势与用户来源浏览，选择保留或排除，并下载保留的图片与来源清单。</p></div><RouterLink :to="{ name: 'high-trend-image-review', query: { task: task.id } }">整理结果图片 <ArrowRightOutlined /></RouterLink></div>
            <div v-if="missingImageWarnings.length" class="warnings-panel">{{ missingImageWarnings.length }} 条趋势图片引用没有可用本地文件。趋势文字仍参与分析，下方用户图片资料可正常查看。<details><summary>查看缺图提示示例</summary><ul><li v-for="warning in missingImageWarnings.slice(0, 3)" :key="warning">{{ warning }}</li></ul><p>完整提示保留在下载的 JSON 中。</p></details></div><details v-if="otherWarnings.length" class="warnings-panel"><summary>其他提示 · {{ otherWarnings.length }} 项</summary><ul><li v-for="warning in otherWarnings.slice(0, 20)" :key="warning">{{ warning }}</li></ul><p v-if="otherWarnings.length > 20">更多提示见下载的 JSON。</p></details>
            <div class="result-section-heading"><h2>趋势与用户共同方向 <span>{{ cards.length }}</span></h2><p>{{ result.scope_note }}</p></div>
            <div v-if="categories.length" class="category-filters"><button :class="{ active: !category }" @click="category = ''">全部方向 <strong>{{ cards.length }}</strong></button><button v-for="item in categories" :key="item.clustering_label" :class="{ active: category === item.clustering_label }" @click="category = item.clustering_label"><span>{{ item.clustering_label }}</span><small>{{ item.article_count }} 篇文章 · {{ item.trend_ids.length }} 个方向</small></button></div>
            <div v-if="filteredCards.length" class="trend-card-grid"><HighTrendCard v-for="(card, index) in filteredCards" :key="card.id" :card="card" :index="index" /></div>
            <p v-else class="section-empty">{{ category ? '该大类本轮没有形成同时关联趋势与用户来源的方向。' : '本轮未形成同时关联趋势与用户来源的主方向。' }}</p>
            <div class="result-section-heading"><h2>用研补充 <span>{{ gaps.length }}</span></h2><p>{{ result.user_research_gaps?.scope_note }}</p></div>
            <div v-if="gaps.length" class="trend-card-grid"><HighTrendCard v-for="(card, index) in gaps" :key="card.id" :card="card" :index="index" supplement /></div>
            <p v-else class="section-empty">本轮没有已引用去重人数严格超过分母一半的用户补充方向。</p>
            <HighTrendUserGallery v-if="result.user_images?.length" :key="task?.id" :images="result.user_images" :positive-only="result.user_image_filter === 'like_or_enjoy'" :scope-note="result.user_images_scope_note" />
            <details v-if="result.unlinked_notes?.length" class="notes-panel"><summary>未关联笔记 · {{ result.unlinked_notes.length }} 段</summary><p class="catalog-note">保留模型原文，但有效来源关联不完整。</p><section v-for="(note, index) in result.unlinked_notes" :key="index"><h3>{{ note.title }}</h3><SafeMarkdown :text="note.text" /></section></details>
          </template>
        </div>
      </section>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>趋势启发 · 来源可追溯 · 人工复核</span></footer>
  </div>
</template>

<style scoped>
.image-review-entry { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 22px; padding: 20px 24px; border: 1px solid #d9ceec; border-radius: 16px; background: #f4effb; color: #645079; }
.image-review-entry strong { font-size: 15px; }
.image-review-entry p { margin: 7px 0 0; font-size: 12px; line-height: 1.8; color: #907da1; }
.image-review-entry a { flex-shrink: 0; padding: 10px 14px; border-radius: 10px; background: #fff; color: #695094; font-size: 12px; }
@media (max-width: 600px) { .image-review-entry { align-items: start; flex-direction: column; } }
.dataset-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; margin-bottom: 24px; color: #76628e; font-size: 12px; }
.dataset-controls :deep(.ant-select) { width: 290px; }
.category-filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }
.category-filters button { display: flex; flex-direction: column; gap: 7px; justify-content: center; text-align: left; border: 1px solid #e5ddef; border-radius: 12px; padding: 13px 17px; background: #fcfafe; color: #826f97; cursor: pointer; font-size: 12px; }
.category-filters button.active { color: #614a8b; border-color: #aa94cd; background: #eee7f8; }
.category-filters small { font-size: 10px; opacity: .8; }
.date-field input:disabled { opacity: .5; }
.trend-hero { padding: 68px 0 44px; }
.trend-hero h1 { font-size: clamp(38px, 5vw, 61px); }
.trend-hero h1 em { font-style: normal; }
.trend-hero > p { max-width: 740px; font-size: 14px; }
.range-badge { padding: 7px 12px; white-space: nowrap; color: #91859f; background: #f3eff8; border-radius: 20px; font-size: 11px; }
.scope-form { display: grid; grid-template-columns: 1fr 16px 1fr 1.35fr auto; gap: 14px; align-items: end; }
.date-field, .model-field { display: flex; flex-direction: column; gap: 9px; margin: 0; min-width: 0; }
.scope-form label { color: #81748f; font-size: 11px; }
.scope-form label span { color: #bb8a9e; }
.date-field input { min-width: 0; width: 100%; height: 40px; padding: 0 11px; border: 1px solid #e5dfec; border-radius: 10px; color: #51445f; background: #fcfbfd; }
.date-arrow { align-self: end; margin-bottom: 14px; color: #b6a9c6; }
.catalog-note, .estimate-note, .task-meta { color: #9b90a7; font-size: 11px; line-height: 1.8; margin: 13px 0 0; overflow-wrap: anywhere; }
.field-error { margin-top: 10px; color: #b45a65; font-size: 12px; }
.advanced-options { margin-top: 15px; color: #9686a5; font-size: 11px; }
.advanced-options label { display: inline-block; margin: 12px 12px 0 0; }
.advanced-options p { margin: 8px 0 0; line-height: 1.7; }
.preview-result { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 18px; padding-top: 22px; margin-top: 22px; border-top: 1px solid #eee7f3; }
.preview-stats { display: flex; gap: 34px; }
.preview-stats > div { display: flex; flex-direction: column; gap: 5px; }
.preview-stats strong { font-family: 'DM Mono', monospace; font-weight: 500; font-size: 25px; color: #685195; }
.preview-stats span { color: #9c8fab; font-size: 10px; }
.estimate-note, .preview-result > :deep(.ant-alert) { flex-basis: 100%; margin: 0; }
.insights-workspace { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 24px; margin: 28px 0 60px; align-items: start; }
.history-panel { padding: 18px 14px; }
.history-head { display: flex; justify-content: space-between; align-items: center; padding: 0 6px; }
.history-head h2 { margin: 0; font-size: 14px; }
.history-item { display: grid; grid-template-columns: 1fr auto; gap: 10px 4px; width: 100%; margin-top: 10px; padding: 13px 10px; text-align: left; cursor: pointer; background: transparent; border: 1px solid transparent; border-radius: 12px; }
.history-item.selected { background: #f3effb; border-color: #e5dcf3; }
.history-item:hover { background: #f8f5fb; }
.history-item :deep(.ant-tag) { align-self: start; margin: 0; font-size: 10px; }
.history-date { font-size: 11px; color: #6f627f; line-height: 1.8; }
.history-item small { grid-column: 1 / -1; color: #aca1b7; font-size: 9px; }
.empty-copy { font-size: 12px; padding: 16px 8px; line-height: 1.8; color: #9b90a7; }
.insights-content { min-width: 0; }
.task-overview { padding: 25px; margin-bottom: 22px; }
.downloads { display: flex; gap: 12px; flex-wrap: wrap; font-size: 11px; padding-top: 8px; }
.downloads a { color: #826d9f; }
.execution-details { margin-top: 18px; color: #9686a5; font-size: 11px; }
summary { cursor: pointer; line-height: 1.8; }
.execution-details ol { list-style: none; padding: 0; max-height: 240px; overflow: auto; }
.execution-details li { display: grid; grid-template-columns: 142px 1fr; gap: 10px; margin: 12px 0; }
.execution-details time { color: #b0a2be; font-size: 10px; }
.task-meta { border-top: 1px solid #f0ebf5; padding-top: 12px; }
.resume-panel { margin-top: 18px; padding: 16px; border: 1px solid #e5dcf3; border-radius: 12px; font-size: 12px; color: #76628e; }
.resume-panel label, .resume-panel :deep(.ant-input-number) { margin-right: 12px; margin-bottom: 10px; }
.user-scope-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 20px; font-size: 12px; color: #76628e; }
.user-scope-controls :deep(.ant-select) { width: 240px; }
.user-scope-controls p { flex-basis: 100%; margin: 0; color: #9686a5; }
.resolved-scope { width: 100%; font-size: 12px; line-height: 1.8; color: #76628e; }
.resolved-scope small { color: #9686a5; }
.trend-chat { margin-top: 24px; }
.trend-chat .catalog-note { margin-top: 22px; }
.task-prompt { margin-top: 16px; padding: 14px 18px; background: #f5f1fb; border-radius: 14px; font-size: 12px; color: #76628e; }
.task-prompt > span { font-size: 11px; }
.task-prompt p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.welcome-empty { display: grid; justify-items: center; padding: 90px 25px; color: #a79aad; border: 1px dashed #dbd1e5; border-radius: 24px; text-align: center; }
.welcome-empty > :deep(.anticon) { font-size: 35px; color: #b6a1d2; }
.welcome-empty h2 { margin: 20px 0 8px; font-size: 20px; font-weight: 500; color: #716080; }
.welcome-empty p { font-size: 12px; }
.result-section-heading { margin: 30px 0 16px; }
.result-section-heading h2 { color: #5b486c; font-size: 20px; }
.result-section-heading h2 span { margin-left: 8px; color: #b8a7c8; font-size: 17px; }
.result-section-heading p { color: #a394ad; font-size: 11px; line-height: 1.8; }
.trend-card-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
.section-empty { margin: 0; padding: 25px; border-radius: 14px; border: 1px dashed #ded4e6; color: #a191ad; font-size: 12px; line-height: 1.8; }
.warnings-panel { padding: 16px 20px; background: #fdf7ed; border: 1px solid #ede1cb; border-radius: 14px; color: #9b7d49; font-size: 12px; }
.warnings-panel ul { margin-bottom: 0; padding-left: 20px; line-height: 1.85; }
.notes-panel { padding: 20px; margin-top: 20px; background: #faf8fc; border: 1px solid #e8e0ef; border-radius: 14px; color: #8d7b9d; font-size: 12px; }
.notes-panel h3 { margin-top: 20px; font-size: 15px; }
.task-spinner { display: block; padding: 45px; }
.page-alert { margin-bottom: 20px; }
@media (max-width: 980px) { .scope-form { grid-template-columns: 1fr 16px 1fr; } .scope-form .model-field { grid-column: 1 / 3; } .insights-workspace { grid-template-columns: 190px minmax(0, 1fr); gap: 16px; } .preview-stats { gap: 22px; } }
@media (max-width: 760px) { .trends-shell .topbar { grid-template-columns: 1fr; gap: 14px; } .trends-shell .topbar nav { display: flex; gap: 20px; justify-content: start; } .trends-shell .system-state { display: none; } .insights-workspace { grid-template-columns: 1fr; } .history-panel { max-height: 275px; overflow: auto; } .history-item { grid-template-columns: 1fr auto 1fr; align-items: center; } .history-item small { grid-column: auto; text-align: right; } .history-date br { display: none; } .trend-hero { padding-top: 46px; } .range-badge { display: none; } .execution-details li { grid-template-columns: 1fr; gap: 2px; } }
@media (max-width: 480px) { .preview-stats { width: 100%; display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; } .scope-form { gap: 10px; } .scope-form .model-field { grid-column: 1 / -1; } .scope-form > :deep(.ant-btn) { grid-column: 1 / -1; } .downloads { flex-direction: column; } }
</style>
