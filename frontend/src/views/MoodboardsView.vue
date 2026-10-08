<script setup lang="ts">
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRightOutlined, BulbOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { fetchModels } from '@/api/dna'
import { createMoodboardTask, fetchMoodboardCatalog, fetchMoodboardTask, fetchMoodboardTasks, moodboardDownloadUrl, resumeMoodboardTask, previewNativeMoodboard } from '@/api/moodboards'
import MoodboardGallery from '@/components/MoodboardGallery.vue'
import type { ModelInfo } from '@/types/dna'
import type { MoodboardCatalog, MoodboardRequest, MoodboardResult, MoodboardTask } from '@/types/moodboards'

const route = useRoute()
const router = useRouter()
const catalog = ref<MoodboardCatalog>({ trend_tasks: [], dna_results: [] })
const models = ref<ModelInfo[]>([])
const modelId = ref('')
const trendTaskId = ref('')
const directionIds = ref<string[]>([])
const resultIds = ref<string[]>([])
const query = ref('')
const page = ref(1)
const pageSize = 12
const loading = ref(true)
const starting = ref(false)
const resuming = ref(false)
const historyLoading = ref(false)
const taskLoading = ref(false)
const error = ref('')
const pollError = ref('')
const history = ref<MoodboardTask[]>([])
const selectedTaskId = ref('')
const task = ref<MoodboardTask | null>(null)
const nativeResult = ref<MoodboardResult | null>(null)
const inspectedId = ref('')
const detailOpen = ref(false)
const showUnformed = ref(false)
const resultsPanel = ref<HTMLElement | null>(null)
let disposed = false
let selectionVersion = 0
let pollingTimer: ReturnType<typeof setTimeout> | undefined

const trendTask = computed(() => catalog.value.trend_tasks.find(item => item.id === trendTaskId.value))
const filteredDna = computed(() => {
  const text = query.value.trim().toLocaleLowerCase()
  return catalog.value.dna_results.filter(item => !text || [item.image_name, item.category, item.summary, ...item.style_candidates].join(' ').toLocaleLowerCase().includes(text))
})
const visibleDna = computed(() => filteredDna.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const selectedSet = computed(() => new Set(resultIds.value))
const pageSelected = computed(() => visibleDna.value.length > 0 && visibleDna.value.every(item => selectedSet.value.has(item.id)))
const nativeExecutionAvailable = computed(() => catalog.value.execution?.supported === true)
const validRequest = computed(() => nativeExecutionAvailable.value && Boolean(trendTaskId.value && directionIds.value.length && resultIds.value.length && resultIds.value.length <= 100 && modelId.value))
const isActive = (item: MoodboardTask | null) => item?.status === 'queued' || item?.status === 'running'
const anyRunning = computed(() => isActive(task.value) || history.value.some(isActive))
const result = computed(() => nativeResult.value ?? task.value?.result)
const images = computed(() => new Map((result.value?.images ?? []).map(item => [item.id, item])))
const assignments = computed(() => new Map((result.value?.assignments ?? []).map(item => [item.result_id, item])))
// 用实际结果字段区分协议，历史任务保持原来的“已归属”含义。
const isCurated = computed(() => result.value?.directions.some(item => item.excluded !== undefined) ?? false)
// 历史 v2 结果沿用 6 张门槛，新 v3 结果按 4 张门槛说明。
const curatedMinimum = computed(() => nativeResult.value ? 10 : task.value?.prompt_version?.endsWith('-v3') ? 4 : 6)
const unformedCount = computed(() => result.value?.directions.filter(item => !item.clusters.length).length ?? 0)
const visibleDirections = computed(() => result.value?.directions.filter(item => !isCurated.value || showUnformed.value || item.clusters.length) ?? [])
const selectedCount = computed(() => result.value?.directions.reduce((total, direction) => total + direction.clusters.reduce((count, cluster) => count + cluster.result_ids.length, 0), 0) ?? 0)
const excluded = computed(() => new Map((result.value?.directions ?? []).flatMap(direction => (direction.excluded ?? []).map(item => [item.result_id, item.reason] as const))))
const inspectedImage = computed(() => images.value.get(inspectedId.value))
const inspectedAssignment = computed(() => assignments.value.get(inspectedId.value))
const inspectedDirection = computed(() => result.value?.directions.find(item => item.id === inspectedAssignment.value?.direction_id))
const inspectedCompetitors = computed(() => (inspectedAssignment.value?.competing_direction_ids ?? []).map(id => result.value?.directions.find(item => item.id === id)?.title ?? id))
const percent = computed(() => task.value?.status === 'completed' ? 100 : task.value?.total_jobs ? Math.min(100, Math.round(task.value.completed_jobs / task.value.total_jobs * 100)) : 0)
const statusLabels: Record<MoodboardTask['status'], string> = { queued: '等待执行', running: '正在分析', completed: '已完成', failed: '执行失败' }
const assignmentStatusLabels = { matched: '趋势匹配', ambiguous: '方向存在歧义', insufficient: 'DNA 信息不足', unmatched: '未匹配趋势' }
const dominanceLabels = {
  strength: { strong: '强', moderate: '中等', weak: '弱', unknown: '未知' },
  scope: { global: '整体', local: '局部', unknown: '未知' },
  salience: { primary: '主导', secondary: '次要', unknown: '未知' },
}

watch(query, () => { page.value = 1 })
watch(trendTaskId, () => { directionIds.value = trendTask.value?.directions.slice(0, 3).map(item => item.id) ?? [] })
watch(() => route.query.task, value => { if (typeof value === 'string' && value !== selectedTaskId.value) void selectTask(value) })

function readError(value: unknown, fallback: string) {
  const detail = (value as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map(item => String(item.msg ?? '参数无效')).join('；')
  return typeof detail === 'string' ? detail : value instanceof Error ? value.message : fallback
}
function dateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function toggleResult(id: string, checked: boolean) {
  if (checked && resultIds.value.length >= 100) { message.warning('每次最多选择 100 张 DNA 图片'); return }
  resultIds.value = checked ? [...new Set([...resultIds.value, id])] : resultIds.value.filter(value => value !== id)
}
function togglePage(checked: boolean) {
  const ids = new Set(visibleDna.value.map(item => item.id))
  const next = checked ? [...new Set([...resultIds.value, ...ids])] : resultIds.value.filter(id => !ids.has(id))
  if (next.length > 100) message.info('本次只补选至 100 张上限')
  resultIds.value = next.slice(0, 100)
}
function selectFirstHundred() {
  // 明确替换选择，按当前检索后的目录顺序截取，不把跨页旧选择隐式追加到 100 张。
  resultIds.value = filteredDna.value.slice(0, 100).map(item => item.id)
}
function updateHistory(current: MoodboardTask) {
  const index = history.value.findIndex(item => item.id === current.id)
  if (index < 0) history.value.unshift(current)
  else history.value[index] = current
}
async function refreshHistory() {
  historyLoading.value = true
  try {
    const entries = await fetchMoodboardTasks()
    if (disposed) return false
    history.value = entries
    return true
  } catch (cause) { error.value = readError(cause, '历史任务读取失败'); return false }
  finally { historyLoading.value = false }
}
/** 刷新列表保留人工选择；明确点击最新结果才切换到最新完成任务。 */
async function showLatestResult() {
  const version = selectionVersion
  if (!await refreshHistory() || version !== selectionVersion) return
  const latest = history.value.find(item => item.status === 'completed')
  if (latest) await selectTask(latest.id, true)
  else message.info('暂无已完成的情绪版结果')
}
function historyLabel(item: MoodboardTask) {
  const edition = /-v[23]$/.test(item.prompt_version ?? '') ? '精选版' : '历史分类'
  return `${dateTime(item.created_at)} · ${statusLabels[item.status]} · ${edition} · ${item.request.result_ids.length} 张`
}

/** 选择任务时废弃旧轮询响应，防止历史切换和慢请求覆盖当前结果。 */
async function selectTask(id: string, scrollToResult = false) {
  nativeResult.value = null
  clearTimeout(pollingTimer)
  const version = ++selectionVersion
  selectedTaskId.value = id
  task.value = null
  detailOpen.value = false
  showUnformed.value = false
  taskLoading.value = true
  pollError.value = ''
  if (route.query.task !== id) void router.replace({ query: { ...route.query, task: id } })
  await loadTask(id, version)
  if (version === selectionVersion) {
    taskLoading.value = false
    if (scrollToResult && !disposed) {
      await nextTick()
      resultsPanel.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }
  }
}
async function loadTask(id: string, version: number) {
  try {
    const current = await fetchMoodboardTask(id)
    if (disposed || version !== selectionVersion) return
    task.value = current
    updateHistory(current)
    pollError.value = ''
    if (isActive(current)) pollingTimer = setTimeout(() => void loadTask(id, version), 2500)
  } catch (cause) {
    if (disposed || version !== selectionVersion) return
    pollError.value = readError(cause, '任务进度读取失败')
    pollingTimer = setTimeout(() => void loadTask(id, version), 5000)
  }
}
function inspect(id: string) { inspectedId.value = id; detailOpen.value = true }
/** 确认内容来自失败任务的冻结请求，避免当前表单选择被误认为续跑输入。 */
function confirmResume() {
  const current = task.value
  if (!nativeExecutionAvailable.value || !current || current.status !== 'failed' || anyRunning.value || resuming.value || starting.value) return
  const frozen = current.request
  const trend = catalog.value.trend_tasks.find(item => item.id === frozen.trend_task_id)
  const titles = frozen.direction_ids.map(id => trend?.directions.find(item => item.id === id)?.title ?? id)
  Modal.confirm({
    title: '确认继续生成这份情绪版？', centered: true, okText: '确认继续', cancelText: '返回检查',
    content: h('div', { class: 'confirm-copy' }, [
      h('p', `沿用原趋势结果：${trend ? dateTime(trend.created_at) : frozen.trend_task_id}`),
      h('p', `趋势方向（${titles.length}）：${titles.join('、')}`),
      h('p', `DNA 图片：${frozen.result_ids.length} 张；模型：${models.value.find(item => item.id === frozen.model_id)?.name ?? frozen.model_id}`),
      h('p', `复用已完成的 ${current.completed_jobs} 个步骤，从未完成步骤继续。剩余步骤会调用模型并保存结果。`),
    ]),
    async onOk() {
      if (disposed || resuming.value || starting.value) return
      resuming.value = true
      error.value = ''
      try {
        const updated = await resumeMoodboardTask(current.id)
        if (!disposed) { updateHistory(updated); await selectTask(updated.id, true) }
      } catch (cause) { error.value = readError(cause, '任务继续执行失败') }
      finally { resuming.value = false }
    },
  })
}
function confirmStart() {
  if (!validRequest.value || starting.value || resuming.value || anyRunning.value) return
  const body: MoodboardRequest = { trend_task_id: trendTaskId.value, direction_ids: [...directionIds.value], result_ids: [...resultIds.value], model_id: modelId.value, confirmed: true }
  const selectedDirections = trendTask.value?.directions.filter(item => body.direction_ids.includes(item.id)) ?? []
  Modal.confirm({
    title: '确认开始情绪版生成？', centered: true, okText: '确认并开始', cancelText: '返回检查',
    content: h('div', { class: 'confirm-copy' }, [
      h('p', `趋势结果：${dateTime(trendTask.value?.created_at ?? '')}`),
      h('p', `所选方向（${selectedDirections.length}）：${selectedDirections.map(item => item.title).join('、')}`),
      h('p', `已提取 DNA：${body.result_ids.length} 张；模型：${models.value.find(item => item.id === body.model_id)?.name ?? body.model_id}`),
      h('p', '新版流程先冻结可指认的视觉条件，再检查真实裁图并独立审阅整板；最终 10 张来自 10 个可追溯的独立项目，不足时记录未完成。当前网页旧生成入口已停用，不会发送模型请求。'),
      h('p', '开始后将调用模型并保存本次选择、分析结果与追溯信息。'),
    ]),
    async onOk() {
      if (disposed || starting.value) return
      starting.value = true
      error.value = ''
      try {
        const created = await createMoodboardTask(body)
        if (!disposed) { updateHistory(created); await selectTask(created.id, true) }
      } catch (cause) { error.value = readError(cause, '情绪版任务启动失败') }
      finally { starting.value = false }
    },
  })
}

onMounted(async () => {
  const [catalogResponse, modelResponse, historyResponse] = await Promise.allSettled([fetchMoodboardCatalog(), fetchModels(), fetchMoodboardTasks()])
  if (disposed) return
  const problems: string[] = []
  if (catalogResponse.status === 'fulfilled') {
    catalog.value = catalogResponse.value
    trendTaskId.value = catalog.value.trend_tasks[0]?.id ?? ''
  } else problems.push(readError(catalogResponse.reason, '输入目录读取失败'))
  if (modelResponse.status === 'fulfilled') {
    models.value = modelResponse.value
    modelId.value = models.value[0]?.id ?? ''
  } else problems.push(readError(modelResponse.reason, '模型列表读取失败'))
  if (historyResponse.status === 'fulfilled') history.value = historyResponse.value
  else problems.push(readError(historyResponse.reason, '历史任务读取失败'))
  const initialTask = typeof route.query.task === 'string' ? route.query.task : (history.value.find(isActive) ?? history.value[0])?.id
  if (typeof route.query.native_run === 'string') {
    try { nativeResult.value = await previewNativeMoodboard(route.query.native_run) }
    catch (cause) { problems.push(readError(cause, '原生 v2 板读取失败')) }
  } else if (initialTask) void selectTask(initialTask)
  error.value = problems.join('；')
  loading.value = false
})
onUnmounted(() => { disposed = true; selectionVersion++; clearTimeout(pollingTimer) })
</script>

<template>
  <div class="app-shell moodboards-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink to="/article-trends">趋势洞察</RouterLink><RouterLink to="/high-trends">高潜趋势</RouterLink><RouterLink class="active" to="/moodboards">情绪版生成</RouterLink><RouterLink to="/design-modification">设计修改</RouterLink><RouterLink to="/user-research">用研聚合</RouterLink><RouterLink to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>
    <main>
      <section class="hero moodboard-hero"><div class="hero-badge"><BulbOutlined /> DNA TO MOODBOARD</div><h1>情绪版生成</h1><p>按同事 v2 流程完成设计转译、实际裁图与独立整板复核；候选数量与最终数量分开，最终目标约 10 张，不足记录未完成。历史结果保留原数量口径。</p></section>
      <a-alert v-if="error" class="page-alert" type="error" show-icon :message="error" closable @close="error = ''" />
      <section ref="resultsPanel" class="workspace-card results-panel">
        <div class="panel-heading"><div><span class="eyebrow">情绪版结果与生成记录</span><p>按方向查看设计主题，并逐张核对归属理由与 DNA 依据。</p></div><div class="result-actions"><a-button type="primary" :loading="historyLoading" @click="showLatestResult">查看最新结果</a-button><a-button :loading="historyLoading" @click="refreshHistory"><ReloadOutlined /> 刷新记录</a-button><a href="#moodboard-new">新建情绪版</a></div></div>
        <div class="history-row"><a-select :value="selectedTaskId || undefined" placeholder="选择生成记录" :options="history.map(item => ({ value: item.id, label: historyLabel(item) }))" @change="selectTask(String($event))" /><a v-if="result && task" :href="moodboardDownloadUrl(task.id)" download>下载完整 JSON</a></div>
        <a-alert v-if="pollError" class="page-alert" type="warning" show-icon :message="pollError" description="正在自动重试读取；已有结果会保留。" />
        <a-spin :spinning="taskLoading">
          <div v-if="task" class="task-status"><div><strong>{{ statusLabels[task.status] }}</strong><span>{{ task.message || task.stage }}</span><small>{{ task.completed_jobs }} / {{ task.total_jobs }} 步 · 更新于 {{ dateTime(task.updated_at) }}</small></div><a-progress :percent="percent" :status="task.status === 'failed' ? 'exception' : isActive(task) ? 'active' : undefined" /></div>
          <a-alert v-if="task?.error" class="page-alert" type="error" show-icon :message="task.error" />
          <div v-if="task?.status === 'failed'" class="resume-row"><a-button type="primary" :loading="resuming" :disabled="!nativeExecutionAvailable || anyRunning || starting" @click="confirmResume">继续执行未完成步骤</a-button><span>沿用原输入，保留 {{ task.completed_jobs }} 个已完成步骤。</span></div>
          <template v-if="result">
            <a-alert v-if="nativeResult" type="info" show-icon message="原生 v2 结果仅做网页投影；验收状态见追溯，仍待用户反馈。" />
            <div class="result-summary">
              <span>{{ result.directions.length }} 个趋势方向</span>
              <span>{{ Math.max(0, (nativeResult ? result.images.length : result.assignments.length) - result.unmatched_result_ids.length) }} 张{{ isCurated ? '匹配候选' : '已归属' }}</span>
              <template v-if="isCurated"><span>{{ selectedCount }} 张精选</span><span>{{ excluded.size }} 张候选未入选</span></template>
              <span>{{ result.unmatched_result_ids.length }} 张未匹配</span>
            </div>
            <div v-if="isCurated && unformedCount" class="unformed-toggle"><a-button :aria-expanded="showUnformed" @click="showUnformed = !showUnformed">{{ showUnformed ? '收起' : '展开' }}未成板方向（{{ unformedCount }}）</a-button><span>默认展示已形成正式主题的方向，未成板方向保留候选与原因。</span></div>
            <article v-for="(direction, index) in visibleDirections" :key="`${task?.id}-${direction.id}`" class="result-direction" :class="{ 'curated-direction': isCurated }">
              <header><span class="direction-index">{{ String(index + 1).padStart(2, '0') }}</span><div><h2>{{ direction.title }}</h2><p>{{ direction.description }}</p></div><span class="count-badge">{{ isCurated ? '精选 ' : '' }}{{ direction.clusters.reduce((count, cluster) => count + cluster.result_ids.length, 0) }} 张</span></header>
              <section v-for="cluster in direction.clusters" :key="cluster.id" class="result-cluster">
                <div class="cluster-heading"><h3>{{ cluster.name }}</h3><span>{{ cluster.result_ids.length }} 张{{ isCurated ? '精选' : '' }}</span></div>
                <p>{{ cluster.description }}</p>
                <dl v-if="cluster.primary_axis" class="theme-definition">
                  <div><dt>主导风格</dt><dd>{{ cluster.primary_axis }}</dd></div>
                  <div v-if="cluster.required_features?.length"><dt>入选条件</dt><dd>{{ cluster.required_features.join('；') }}</dd></div>
                  <div v-if="cluster.exclusions?.length"><dt>排除特征</dt><dd>{{ cluster.exclusions.join('；') }}</dd></div>
                </dl>
                <MoodboardGallery :result-ids="cluster.result_ids" :images="images" :curated="isCurated" @inspect="inspect" />
                <p v-if="isCurated" class="subtle">点击图片查看归属理由与 DNA 依据。</p>
              </section>
              <p v-if="!direction.clusters.length" class="subtle">{{ isCurated ? `尚无 ${curatedMinimum} 张主导视觉语言一致的图片，暂不形成正式主题。` : '此方向暂无匹配图片，未形成子类别。' }}</p>
              <details v-if="direction.excluded?.length" class="candidate-details">
                <summary>{{ direction.excluded.length }} 张匹配候选未入选 · 查看原因</summary>
                <ul><li v-for="item in direction.excluded" :key="item.result_id"><button type="button" @click="inspect(item.result_id)">{{ images.get(item.result_id)?.image_name ?? item.result_id }}</button><p>{{ item.reason }}</p></li></ul>
              </details>
            </article>
            <article class="result-direction unmatched"><header><div><h2>未匹配图片</h2><p>{{ isCurated ? '包含方向歧义、DNA 信息不足及主导特征不符的图片，保留供人工复核。' : '当前所选方向中尚无充分 DNA 依据支持归属，保留供人工复核。' }}</p></div><span class="count-badge">{{ result.unmatched_result_ids.length }} 张</span></header><details v-if="result.unmatched_result_ids.length" class="candidate-details"><summary>查看未匹配图片与依据</summary><MoodboardGallery :result-ids="result.unmatched_result_ids" :images="images" @inspect="inspect" /></details><p v-else class="subtle">本次所有图片均已匹配趋势方向{{ isCurated ? '，精选结果见各主题。' : '。' }}</p></article>
            <details class="trace-details"><summary>查看执行追溯</summary><pre>{{ JSON.stringify(result.trace, null, 2) }}</pre></details>
          </template>
          <a-empty v-else-if="!taskLoading && !isActive(task)" :description="task?.status === 'failed' ? '本次任务尚未完成，可点击“继续执行未完成步骤”，沿用原输入并复用已完成阶段。' : '选择趋势与 DNA 图片，开始生成第一份情绪版。'" />
        </a-spin>
      </section>
      <a-spin :spinning="loading">
        <section id="moodboard-new" class="workspace-card input-panel">
          <div class="panel-heading"><div><span class="eyebrow">01 / 选择趋势方向</span><p>选择已有高潜趋势结果，再勾选本次需要探索的方向。</p></div><span class="count-badge">已选 {{ directionIds.length }} 个方向</span></div>
          <div class="input-row"><label for="moodboard-trend">高潜趋势结果</label><a-select id="moodboard-trend" v-model:value="trendTaskId" placeholder="选择已有结果" :options="catalog.trend_tasks.map(item => ({ value: item.id, label: `${dateTime(item.created_at)} · ${item.directions.length} 个方向 · ${item.id.slice(0, 8)}` }))" /></div>
          <a-empty v-if="!loading && !catalog.trend_tasks.length" description="暂无可用高潜趋势结果，请先生成高潜趋势。" />
          <a-checkbox-group v-model:value="directionIds" class="direction-grid">
            <div v-for="direction in trendTask?.directions ?? []" :key="direction.id" class="direction-option" :class="{ selected: directionIds.includes(direction.id) }"><a-checkbox :value="direction.id">{{ direction.title }}</a-checkbox><p>{{ direction.description }}</p></div>
          </a-checkbox-group>
          <p v-if="trendTask" class="subtle">默认选中当前结果的前 3 个方向，可自行调整。</p>
        </section>
        <section class="workspace-card input-panel">
          <div class="panel-heading"><div><span class="eyebrow">02 / 批量选择已提取 DNA 的图片</span><p>历史 DNA 目录供查阅；新版候选池在项目中独立冻结，原图与真实裁图在后续视觉链分别审阅。</p></div><span class="count-badge">已选 {{ resultIds.length }} 张</span></div>
          <div class="selection-toolbar"><a-input v-model:value="query" allow-clear placeholder="检索图片名称、品类、风格或 DNA 摘要" aria-label="检索 DNA 图片" /><a-button :disabled="!filteredDna.length" @click="selectFirstHundred">选择当前顺序前 100 张</a-button><a-button :disabled="!resultIds.length" @click="resultIds = []">清空选择</a-button></div>
          <div class="selection-meta"><a-checkbox :checked="pageSelected" :indeterminate="!pageSelected && visibleDna.some(item => selectedSet.has(item.id))" :disabled="!visibleDna.length" @change="togglePage($event.target.checked)">选择本页</a-checkbox><span>按提取时间从新到旧 · 检索到 {{ filteredDna.length }} 张 · “前 100 张”会替换当前选择</span></div>
          <div class="dna-grid"><div v-for="dna in visibleDna" :key="dna.id" class="dna-option" :class="{ selected: selectedSet.has(dna.id) }"><a-checkbox :checked="selectedSet.has(dna.id)" :disabled="resultIds.length >= 100 && !selectedSet.has(dna.id)" @change="toggleResult(dna.id, $event.target.checked)"><span class="sr-label">选择 {{ dna.image_name }}</span></a-checkbox><img v-if="dna.preview_url" :src="dna.preview_url" :alt="dna.image_name" loading="lazy" /><span v-else class="image-placeholder">暂无预览</span><strong :title="dna.image_name">{{ dna.image_name }}</strong><span>{{ dna.category || '未标注品类' }}</span><small>{{ dna.style_candidates.join(' · ') || '暂无风格标签' }}</small><p :title="dna.summary ?? undefined">{{ dna.summary || '已完成 DNA 提取' }}</p></div></div>
          <a-empty v-if="!loading && !filteredDna.length" description="暂无符合条件的 DNA 图片" />
          <a-pagination v-if="filteredDna.length" v-model:current="page" :page-size="pageSize" :total="filteredDna.length" :show-size-changer="false" size="small" />
          <a-alert v-if="!nativeExecutionAvailable" type="info" show-icon :message="catalog.execution?.reason || '旧生成入口已停用，等待原生 v2 结果。'" /><div class="start-row"><div class="model-field"><label for="moodboard-model">分析模型</label><a-select id="moodboard-model" :disabled="!nativeExecutionAvailable" v-model:value="modelId" placeholder="选择模型" :options="models.map(item => ({ value: item.id, label: item.name }))" /></div><p>{{ directionIds.length }} 个趋势方向 · {{ resultIds.length }} 张 DNA<br /><small>新流程按冻结数量与独立项目要求验收</small></p><a-button type="primary" size="large" :loading="starting" :disabled="!validRequest || anyRunning || resuming || loading" @click="confirmStart">确认并生成情绪版 <ArrowRightOutlined /></a-button></div>
          <p v-if="anyRunning" class="subtle">已有任务正在执行，完成后可继续创建。</p>
        </section>
      </a-spin>
    </main>
    <a-modal v-model:open="detailOpen" :title="inspectedImage?.image_name ?? inspectedId" :footer="null" :width="760"><div class="image-detail"><img v-if="inspectedImage?.preview_url" :src="inspectedImage.preview_url" :alt="inspectedImage.image_name" /><div><h3>{{ inspectedDirection?.title ?? '未匹配' }}</h3><a-tag v-if="inspectedAssignment?.status">{{ assignmentStatusLabels[inspectedAssignment.status] }}</a-tag><p>{{ inspectedAssignment?.reason ?? '暂无归属说明' }}</p><template v-if="excluded.has(inspectedId)"><h4>未入选原因</h4><p>{{ excluded.get(inspectedId) }}</p></template><template v-if="inspectedAssignment?.dominant_style"><h4>主导视觉语言</h4><p>{{ inspectedAssignment.dominant_style }}</p></template>
      <dl v-if="inspectedAssignment?.dominance" class="theme-definition">
        <div><dt>特征强度</dt><dd>{{ dominanceLabels.strength[inspectedAssignment.dominance.strength] }}</dd></div>
        <div><dt>影响范围</dt><dd>{{ dominanceLabels.scope[inspectedAssignment.dominance.scope] }}</dd></div>
        <div><dt>视觉显著性</dt><dd>{{ dominanceLabels.salience[inspectedAssignment.dominance.salience] }}</dd></div>
      </dl>
      <template v-if="inspectedCompetitors.length"><h4>竞争方向</h4><ul><li v-for="title in inspectedCompetitors" :key="title">{{ title }}</li></ul></template>
      <h4>{{ nativeResult ? '原生板审依据路径' : 'DNA 依据路径' }}</h4><ul v-if="inspectedAssignment?.evidence_paths.length"><li v-for="path in inspectedAssignment.evidence_paths" :key="path"><code>{{ path }}</code><pre v-if="inspectedAssignment?.evidence?.some(item => item.path === path)" class="evidence-value">{{ JSON.stringify(inspectedAssignment.evidence.find(item => item.path === path)?.value, null, 2) }}</pre></li></ul><p v-else>未提供证据路径</p><h4>{{ nativeResult ? '当前取景范围' : 'DNA 摘要' }}</h4><p>{{ inspectedImage?.summary || '暂无摘要' }}</p><p class="subtle">{{ nativeResult ? '原生图片 ID' : 'DNA 结果 ID' }}：{{ inspectedId }}</p></div></div></a-modal>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>设计转译 → 裁图复核 → 整板审阅 → 用户反馈</span></footer>
  </div>
</template>

<style scoped>
.moodboard-hero { padding: 45px 0 30px; }
.moodboard-hero h1 { margin: 14px 0; font-size: 32px; }
.moodboard-hero p { max-width: 700px; }
.input-panel, .results-panel { margin-bottom: 22px; scroll-margin-top: 24px; }
.result-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-bottom: 20px; }
.panel-heading p, .subtle, .selection-meta, .result-direction p { color: #8a8197; font-size: 12px; line-height: 1.8; }
.panel-heading p { margin: 8px 0 0; }
.input-row, .history-row { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.input-row label, .model-field label { font-size: 12px; color: #645773; }
.input-row .ant-select, .history-row .ant-select { width: min(100%, 650px); }
.direction-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.direction-option, .dna-option { min-width: 0; padding: 14px; background: #faf9fc; border: 1px solid #ece8f2; border-radius: 12px; cursor: pointer; }
.direction-option.selected, .dna-option.selected { background: #f5f1fc; border-color: #aa97d5; }
.direction-option { white-space: normal; overflow-wrap: anywhere; }
.direction-option p { margin: 10px 0 0; color: #898091; line-height: 1.7; font-size: 12px; }
.selection-toolbar { display: flex; gap: 10px; flex-wrap: wrap; }
.selection-toolbar .ant-input-affix-wrapper { flex: 1; min-width: 220px; }
.selection-meta { display: flex; gap: 18px; justify-content: space-between; margin: 16px 0; }
.dna-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.dna-option { position: relative; display: flex; flex-direction: column; gap: 5px; padding: 9px; }
.dna-option > .ant-checkbox-wrapper { position: absolute; top: 15px; left: 15px; z-index: 1; }
.dna-option img, .image-placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 120px; object-fit: contain; background: #fff; border-radius: 8px; }
.dna-option strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.dna-option > span, .dna-option small { overflow-wrap: anywhere; color: #92889d; font-size: 10px; }
.dna-option p { display: -webkit-box; margin: 0; overflow: hidden; color: #8b8194; font-size: 11px; line-height: 1.6; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.sr-label { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
.start-row { display: flex; gap: 24px; align-items: center; margin-top: 24px; padding-top: 24px; border-top: 1px solid #ece8f2; }
.model-field { display: flex; flex: 1; flex-direction: column; gap: 8px; min-width: 200px; }
.start-row p { margin: 0; color: #6c5b86; font-size: 12px; }
.start-row small { color: #9a90a7; font-size: 11px; }
.page-alert { margin: 14px 0; }
.resume-row { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; margin: 18px 0; }
.resume-row span { color: #8d829b; font-size: 12px; }
.task-status { padding: 16px 20px; margin: 18px 0; background: #f7f4fb; border-radius: 12px; }
.task-status > div { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
.task-status strong { color: #76609e; }
.task-status span, .task-status small { color: #8d829b; font-size: 12px; }
.result-summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 24px 0; }
.result-summary span { padding: 8px 12px; color: #776388; background: #f0eaf7; border-radius: 30px; font-size: 12px; }
.unformed-toggle { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; color: #8a8197; font-size: 12px; }
.result-direction { padding: 24px; margin-top: 20px; background: #fcfbfd; border: 1px solid #eae4f0; border-radius: 18px; }
.result-direction > header { display: flex; align-items: flex-start; gap: 16px; }
.result-direction > header > div { flex: 1; }
.direction-index { color: #ac9abe; font-size: 25px; }
.result-direction h2 { margin: 0; color: #59466d; font-size: 20px; }
.result-direction p { margin: 8px 0; }
.result-cluster { margin-top: 24px; padding-top: 20px; border-top: 1px solid #ebe5f0; }
.cluster-heading { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.cluster-heading h3 { margin: 0; color: #6f597d; font-size: 16px; }
.cluster-heading span { color: #97879f; font-size: 12px; }
.curated-direction { background: #fff; }
.theme-definition { display: grid; gap: 5px; margin: 12px 0; font-size: 12px; line-height: 1.7; }
.theme-definition > div { display: grid; grid-template-columns: 65px minmax(0, 1fr); gap: 8px; }
.theme-definition dt { color: #665575; }
.theme-definition dd { margin: 0; color: #8a8197; }
.candidate-details { margin-top: 18px; color: #82748f; font-size: 12px; }
.candidate-details summary { cursor: pointer; }
.candidate-details ul { max-height: 360px; overflow: auto; padding: 0; list-style: none; }
.candidate-details li { padding: 10px 0; border-bottom: 1px solid #eee9f2; }
.candidate-details button { max-width: 100%; padding: 0; border: 0; color: #75618b; background: transparent; text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.candidate-details button:hover { text-decoration: underline; }
.unmatched { background: #f9f8fa; }
.trace-details { margin-top: 24px; color: #82748f; font-size: 12px; }
.trace-details pre { max-height: 350px; padding: 16px; overflow: auto; background: #f7f5fa; white-space: pre-wrap; overflow-wrap: anywhere; }
.image-detail { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 22px; padding: 16px 0; }
.image-detail > img { width: 100%; max-height: 450px; object-fit: contain; border-radius: 12px; }
.image-detail p { color: #7d7188; line-height: 1.8; overflow-wrap: anywhere; }
.image-detail code { font-size: 11px; overflow-wrap: anywhere; }
.image-detail ul { padding-left: 20px; }
.evidence-value { padding: 8px; overflow-wrap: anywhere; white-space: pre-wrap; background: #f6f3fa; font-size: 12px; border-radius: 6px; }
@media (max-width: 1050px) { .dna-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } .direction-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .dna-grid, .direction-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .selection-meta, .start-row, .input-row, .history-row { flex-direction: column; align-items: stretch; } .panel-heading { align-items: flex-start; } .result-direction { padding: 16px; } .image-detail { grid-template-columns: 1fr; } }
</style>
