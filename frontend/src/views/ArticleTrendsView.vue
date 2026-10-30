<script setup lang="ts">
import MainNavigation from '@/components/MainNavigation.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BulbOutlined, LinkOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { isAxiosError } from 'axios'

import { articleTrendsApi } from '@/api/articleTrends'
import type { TrendArticle, TrendCatalog, TrendClusterTask, TrendFilters, TrendModel, TrendPreview, TrendRelatedImage, TrendSelection } from '@/types/articleTrends'

const catalog = ref<TrendCatalog | null>(null)
const models = ref<TrendModel[]>([])
const articles = ref<TrendArticle[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(24)
const keyword = ref('')
const source = ref('')
const category = ref('')
const startDate = ref('')
const endDate = ref('')
const loading = ref(false)
const listError = ref('')
const catalogError = ref('')
const selectedArticle = ref<TrendArticle | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const detailPanel = ref<HTMLElement | null>(null)
const selectedImage = ref(0)
const tab = ref('library')
const selectionMode = ref<'filtered' | 'manual'>('filtered')
const checkedIds = ref<string[]>([])
const articleDates = ref<Record<string, string | null>>({})
const limit = ref<number | null>(null)
const modelId = ref('')
const minSources = ref(3)
const maxCalls = ref(30)
const preview = ref<TrendPreview | null>(null)
const previewRequest = ref<TrendSelection | null>(null)
const estimating = ref(false)
const starting = ref(false)
const confirmOpen = ref(false)
const taskList = ref<TrendClusterTask[]>([])
const taskError = ref('')
const activeTaskId = ref('')
const activeTask = ref<TrendClusterTask | null>(null)
const refreshing = ref(false)
const resumeOpen = ref(false)
const resumeMaxCalls = ref(30)
const resuming = ref(false)
const resultPage = ref(1)
const candidatePage = ref(1)
const taskDetailLoading = ref(false)
const unavailableImages = ref(new Set<string>())
let articleRequest = 0
let detailRequest = 0
let taskRequest = 0
let filterTimer: ReturnType<typeof setTimeout> | undefined
let pollTimer: ReturnType<typeof setInterval> | undefined
let disposed = false

const invalidDates = computed(() => Boolean(startDate.value && endDate.value && startDate.value > endDate.value))
const filters = computed<TrendFilters>(() => ({ q: keyword.value.trim() || undefined, source: source.value || undefined, category: category.value || undefined, date_from: startDate.value || undefined, date_to: endDate.value || undefined }))
const filterKey = computed(() => JSON.stringify(filters.value))
const eligibleCheckedIds = computed(() => checkedIds.value.filter(id => {
  const date = articleDates.value[id]
  return (!startDate.value || Boolean(date && date >= startDate.value)) && (!endDate.value || Boolean(date && date <= endDate.value))
}))
const dateRangeLabel = computed(() => `${startDate.value || '不限起始日期'} 至 ${endDate.value || '不限结束日期'}（含首尾日期）`)
const selectedCount = computed(() => selectionMode.value === 'manual' ? eligibleCheckedIds.value.length : total.value)
const effectiveCount = computed(() => limit.value ? Math.min(limit.value, selectedCount.value) : selectedCount.value)
const selection = computed<TrendSelection>(() => ({
  // 手动勾选忽略关键词/分类变化；日期对两种范围都生效，范围外勾选保留但不送入本次聚类。
  filters: selectionMode.value === 'filtered' ? { ...filters.value } : { date_from: startDate.value || undefined, date_to: endDate.value || undefined },
  ...(selectionMode.value === 'manual' ? { article_ids: [...checkedIds.value].sort() } : {}),
  limit: limit.value || null, model_id: modelId.value, min_source_groups: minSources.value, max_calls: maxCalls.value,
}))
const selectionKey = computed(() => JSON.stringify(selection.value))
const allPageChecked = computed(() => articles.value.length > 0 && articles.value.every(article => checkedIds.value.includes(article.article_id)))
const canEstimate = computed(() => Boolean(modelId.value && effectiveCount.value >= 2 && !invalidDates.value && !loading.value && minSources.value >= 2 && maxCalls.value >= 1))
const result = computed(() => activeTask.value?.result)
const isHistorical = computed(() => activeTask.value?.kind === 'historical')
const historicalTask = computed(() => taskList.value.find(task => task.kind === 'historical'))
const rankedTrends = computed(() => [...(result.value?.trends ?? [])].sort((a, b) => Number(a.priority_rank ?? Infinity) - Number(b.priority_rank ?? Infinity)))
const visibleTrends = computed(() => rankedTrends.value.slice((resultPage.value - 1) * 12, resultPage.value * 12))
const candidatePool = computed(() => result.value?.evidence_pool ?? [])
const visibleCandidates = computed(() => candidatePool.value.slice((candidatePage.value - 1) * 15, candidatePage.value * 15))
const statusNames: Record<TrendClusterTask['status'], string> = { queued: '等待执行', running: '执行中', failed: '失败', completed: '已完成', interrupted: '已暂停／中断' }

function errorMessage(error: unknown) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    return typeof detail === 'string' ? detail : error.response?.status === 404 ? '数据接口暂不可用，请稍后重试。' : error.message
  }
  return error instanceof Error ? error.message : '请求失败，请重试。'
}
function dateLabel(value: string | null | undefined) { return value?.slice(0, 10) || '日期未提供' }
function safeLink(value: string | null | undefined) {
  if (!value) return undefined
  try { const url = new URL(value, window.location.origin); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}
function textField(row: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) { const value = row[key]; if (typeof value === 'string' || typeof value === 'number') return String(value) }
  return ''
}
function listField(row: Record<string, unknown>, key: string): Record<string, unknown>[] {
  const value = row[key]
  return Array.isArray(value) ? value.map(item => typeof item === 'object' && item !== null ? item as Record<string, unknown> : { article_id: String(item) }) : []
}
function relatedImages(trend: Record<string, unknown>): TrendRelatedImage[] {
  return listField(trend, 'images').filter((image): image is Record<string, unknown> & TrendRelatedImage =>
    typeof image.url === 'string' && typeof image.article_id === 'string' && typeof image.article_title === 'string'
    && typeof image.image_id === 'string' && !unavailableImages.value.has(image.url))
}
function hideUnavailableImage(url: string) { unavailableImages.value.add(url) }
function progress(task: TrendClusterTask) { return task.status === 'completed' ? 100 : task.total_steps ? Math.min(99, Math.round((task.completed_steps ?? 0) / task.total_steps * 100)) : 0 }
async function openHistory() {
  if (!historicalTask.value) return
  tab.value = 'tasks'
  await showTask(historicalTask.value.id)
}

async function loadArticles() {
  const request = ++articleRequest
  if (invalidDates.value) { loading.value = false; return }
  loading.value = true
  listError.value = ''
  try {
    const response = await articleTrendsApi.articles({ ...filters.value, page: page.value, page_size: pageSize.value })
    if (request !== articleRequest || disposed) return
    articles.value = response.items
    for (const article of response.items) articleDates.value[article.article_id] = article.published_at
    total.value = response.total
    if (!selectedArticle.value && response.items[0]) void selectArticle(response.items[0].article_id)
  } catch (error) { if (request === articleRequest) listError.value = errorMessage(error) }
  finally { if (request === articleRequest) loading.value = false }
}
async function selectArticle(id: string) {
  const request = ++detailRequest
  detailLoading.value = true
  detailError.value = ''
  selectedArticle.value = null
  selectedImage.value = 0
  try {
    const article = await articleTrendsApi.article(id)
    if (request === detailRequest && !disposed) selectedArticle.value = article
  } catch (error) { if (request === detailRequest) detailError.value = errorMessage(error) }
  finally { if (request === detailRequest) detailLoading.value = false }
}
async function openEvidence(id: string) {
  if (!id) return
  tab.value = 'library'
  await selectArticle(id)
  await nextTick()
  detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function toggleArticle(id: string) {
  checkedIds.value = checkedIds.value.includes(id) ? checkedIds.value.filter(item => item !== id) : [...checkedIds.value, id]
  selectionMode.value = 'manual'
}
function togglePage() {
  checkedIds.value = allPageChecked.value ? checkedIds.value.filter(id => !articles.value.some(article => article.article_id === id)) : [...new Set([...checkedIds.value, ...articles.value.map(article => article.article_id)])]
  selectionMode.value = 'manual'
}
function resetFilters() { keyword.value = ''; source.value = ''; category.value = ''; startDate.value = ''; endDate.value = '' }
async function loadCatalog() {
  catalogError.value = ''
  const responses = await Promise.allSettled([articleTrendsApi.catalog(), articleTrendsApi.models()])
  const [catalogResponse, modelResponse] = responses
  if (disposed) return
  if (catalogResponse.status === 'fulfilled') catalog.value = catalogResponse.value
  else catalogError.value = `文章目录：${errorMessage(catalogResponse.reason)}`
  if (modelResponse.status === 'fulfilled') {
    models.value = modelResponse.value
    // 只加载可选目录；用户明确选择模型并确认后才创建任务。
  } else catalogError.value += `${catalogError.value ? '；' : ''}模型目录：${errorMessage(modelResponse.reason)}`
}
async function estimate() {
  if (!canEstimate.value || estimating.value) return
  const request = JSON.parse(selectionKey.value) as TrendSelection
  const key = selectionKey.value
  estimating.value = true
  preview.value = null
  try {
    const response = await articleTrendsApi.preview(request)
    if (key !== selectionKey.value) { message.info('范围或参数已改变，请重新预估。'); return }
    previewRequest.value = request
    preview.value = response
  } catch (error) { message.error(errorMessage(error)) }
  finally { estimating.value = false }
}
async function startCluster() {
  if (!preview.value || !previewRequest.value || starting.value) return
  const request = { ...previewRequest.value, selection_digest: preview.value.selection_digest, confirm: true as const }
  starting.value = true
  try {
    const task = await articleTrendsApi.start(request)
    activeTaskId.value = task.id
    activeTask.value = task
    confirmOpen.value = false
    preview.value = null
    previewRequest.value = null
    tab.value = 'tasks'
    message.success('聚类任务已创建。')
    await refreshTasks()
  } catch (error) { message.error(errorMessage(error)) }
  finally { starting.value = false }
}
async function showTask(id: string) {
  const request = ++taskRequest
  if (id !== activeTaskId.value) { activeTask.value = null; resultPage.value = 1; candidatePage.value = 1 }
  activeTaskId.value = id
  taskDetailLoading.value = true
  try {
    const task = taskList.value.find(task => task.id === id)?.kind === 'historical'
      ? await articleTrendsApi.historicalTask(id) : await articleTrendsApi.task(id)
    if (request === taskRequest && !disposed) activeTask.value = task
  } catch (error) { if (request === taskRequest) taskError.value = errorMessage(error) }
  finally { if (request === taskRequest) taskDetailLoading.value = false }
}
async function refreshTasks() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const responses = await Promise.allSettled([articleTrendsApi.tasks(), articleTrendsApi.history()])
    const [current, history] = responses
    taskList.value = [...(current.status === 'fulfilled' ? current.value : taskList.value.filter(task => task.kind !== 'historical')),
      ...(history.status === 'fulfilled' ? history.value : taskList.value.filter(task => task.kind === 'historical'))]
    taskError.value = ''
    if (current.status === 'rejected') taskError.value = `新任务加载失败：${errorMessage(current.reason)}`
    if (history.status === 'rejected') taskError.value += `${taskError.value ? '；' : ''}历史结果加载失败：${errorMessage(history.reason)}`
    if (activeTaskId.value) {
      const latest = taskList.value.find(task => task.id === activeTaskId.value)
      if (latest && (latest.updated_at !== activeTask.value?.updated_at || latest.status !== activeTask.value?.status || latest.status === 'completed' && !activeTask.value?.result)) await showTask(latest.id)
    } else if (taskList.value[0]) await showTask(taskList.value[0].id)
  } catch (error) { taskError.value = errorMessage(error) }
  finally { refreshing.value = false }
}
function askResume() { resumeMaxCalls.value = Math.max(maxCalls.value, (activeTask.value?.calls ?? 0) + 10); resumeOpen.value = true }
async function resumeTask() {
  if (!activeTask.value || resuming.value) return
  resuming.value = true
  try {
    activeTask.value = await articleTrendsApi.resume(activeTask.value.id, resumeMaxCalls.value)
    resumeOpen.value = false
    await refreshTasks()
  } catch (error) { message.error(errorMessage(error)) }
  finally { resuming.value = false }
}

watch(selectionKey, () => { preview.value = null; previewRequest.value = null; confirmOpen.value = false })
watch([filterKey, page, pageSize], (values, previous) => {
  clearTimeout(filterTimer)
  if ((values[0] !== previous[0] || values[2] !== previous[2]) && page.value !== 1) { page.value = 1; return }
  // 输入后立即使旧响应失效，避免慢响应覆盖新筛选。
  articleRequest += 1
  loading.value = true
  filterTimer = setTimeout(() => void loadArticles(), 250)
})
onMounted(() => {
  void loadCatalog()
  void loadArticles()
  void refreshTasks()
  pollTimer = setInterval(() => { if (!document.hidden && (tab.value === 'tasks' || taskList.value.some(task => ['queued', 'running'].includes(task.status)))) void refreshTasks() }, 5000)
})
onBeforeUnmount(() => { disposed = true; clearTimeout(filterTimer); clearInterval(pollTimer); articleRequest += 1; detailRequest += 1; taskRequest += 1 })
</script>

<template>
  <div class="app-shell article-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <MainNavigation />
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>
    <main>
      <section class="hero article-hero">
        <div class="hero-badge"><BulbOutlined /> TREND LIBRARY</div>
        <h1>趋势洞察</h1>
        <p>浏览 {{ catalog?.total.toLocaleString() ?? '全部' }} 篇文章，选择范围，以标题和摘要进行纯文本语义聚类。</p>
        <div class="principles"><span>多篇文章共同支持</span><span>来源去重后排序</span><span>趋势数量无上限</span><span>图片仅供浏览</span></div>
        <a-button v-if="historicalTask" class="history-entry" @click="openHistory">查看历史 100 个趋势结果</a-button>
      </section>
      <a-alert v-if="catalogError" type="warning" show-icon :message="catalogError" class="notice"><template #action><a-button size="small" @click="loadCatalog">重试</a-button></template></a-alert>
      <a-tabs v-model:active-key="tab">
        <a-tab-pane key="library" tab="文章资料库与聚类范围">
          <section class="filter-panel" aria-label="文章筛选">
            <div class="filter-field keyword-field"><label for="article-keyword">关键词</label><div class="search-input"><SearchOutlined /><input id="article-keyword" v-model="keyword" type="search" placeholder="搜索标题与摘要" /></div></div>
            <div class="filter-field"><label for="article-source">来源</label><select id="article-source" v-model="source"><option value="">全部来源</option><option v-for="item in catalog?.sources" :key="item" :value="item">{{ item }}</option></select></div>
            <div class="filter-field"><label for="article-category">分类</label><select id="article-category" v-model="category"><option value="">全部分类</option><option v-for="item in catalog?.categories" :key="item" :value="item">{{ item }}</option></select></div>
            <button class="reset-button" type="button" @click="resetFilters">重置筛选</button>
          </section>

          <section class="cluster-panel" aria-labelledby="cluster-heading">
            <div class="section-heading"><div><h2 id="cluster-heading">开始趋势语义聚类</h2><p>先预估范围与调用量，再确认启动。只有点击确认才会运行模型。</p></div><a-tag color="purple">纯文本</a-tag></div>
            <div class="cluster-date-row">
              <div class="filter-field"><label for="article-start">趋势日期起（文章发布日期）</label><input id="article-start" v-model="startDate" type="date" :max="endDate || undefined" /></div>
              <div class="filter-field"><label for="article-end">趋势日期止（文章发布日期）</label><input id="article-end" v-model="endDate" type="date" :min="startDate || undefined" /></div>
              <a-button @click="startDate = ''; endDate = ''">不限日期</a-button>
            </div>
            <p v-if="invalidDates" class="date-error">开始日期不能晚于结束日期。</p>
            <p class="muted">输入日期：{{ dateRangeLabel }}。日期同时用于下方文章浏览和聚类输入；设置范围后不包含日期缺失的文章。</p>
            <div class="scope-row">
              <a-radio-group v-model:value="selectionMode"><a-radio value="filtered">当前筛选范围（{{ total.toLocaleString() }} 篇）</a-radio><a-radio value="manual">手动勾选（{{ checkedIds.length }} 篇）</a-radio></a-radio-group>
              <a-button v-if="checkedIds.length" type="link" size="small" @click="checkedIds = []">清空勾选</a-button>
              <span class="muted">勾选跨页保留；日期范围对两种方式均生效<span v-if="selectionMode === 'manual'">，本范围内 {{ eligibleCheckedIds.length }} 篇</span></span>
            </div>
            <div class="cluster-controls">
              <div class="filter-field"><label>取范围内最新 N 篇</label><a-input-number v-model:value="limit" :min="2" :max="20000" :precision="0" placeholder="留空使用全部" /></div>
              <div class="filter-field model-field"><label>执行模型</label><a-select v-model:value="modelId" placeholder="选择已配置模型" :options="models.map(model => ({ value: model.id, label: `${model.name} · ${model.model_provider}` }))" /></div>
              <div class="filter-field"><label>每个趋势最少来源组</label><a-input-number v-model:value="minSources" :min="2" :max="100" :precision="0" /></div>
              <div class="filter-field"><label>模型调用预算上限</label><a-input-number v-model:value="maxCalls" :min="1" :max="5000" :precision="0" /></div>
              <a-button type="primary" :loading="estimating" :disabled="!canEstimate" @click="estimate">预估 {{ effectiveCount.toLocaleString() }} 篇</a-button>
            </div>
            <p class="muted budget-note">来源组按重复／转载文章去重，不等于网站数量。趋势按共同支持优先级呈现，不代表市场热度；单篇和弱证据保留在候选池。</p>
            <div v-if="preview" class="estimate-box">
              <p class="muted">本次输入日期：{{ dateRangeLabel }}</p>
              <div class="estimate-metrics"><span><strong>{{ preview.article_count.toLocaleString() }}</strong> 篇文章</span><span><strong>{{ preview.source_group_count.toLocaleString() }}</strong> 个来源组</span><span><strong>{{ preview.batch_count }}</strong> 个文本批次</span><span>预计 <strong>{{ preview.estimated_calls }}</strong> 次调用</span><span>{{ preview.input_characters.toLocaleString() }} 字符</span></div>
              <p v-for="warning in preview.warnings" :key="warning" class="warning-text">{{ warning }}</p>
              <div class="estimate-footer"><span class="muted">调用量为预估；达到预算会暂停。Skill {{ preview.skill_version }}</span><a-button type="primary" :disabled="preview.article_count < 2" @click="confirmOpen = true">确认范围并启动</a-button></div>
            </div>
          </section>

          <section class="article-layout">
            <div class="article-list">
              <div class="list-heading"><div><h2>文章资料 <span>{{ total.toLocaleString() }} / {{ catalog?.total.toLocaleString() ?? '—' }}</span></h2><p>按发布日期最新优先 · 每页 {{ pageSize }} 篇</p></div><a-checkbox :checked="allPageChecked" :indeterminate="!allPageChecked && articles.some(article => checkedIds.includes(article.article_id))" :disabled="loading || !articles.length" @change="togglePage">勾选本页</a-checkbox></div>
              <a-alert v-if="listError" type="error" show-icon :message="listError" class="notice"><template #action><a-button size="small" @click="loadArticles">重试</a-button></template></a-alert>
              <a-spin :spinning="loading">
                <div v-if="articles.length && !invalidDates" class="article-grid">
                  <article v-for="article in articles" :key="article.article_id" class="article-card" :class="{ selected: selectedArticle?.article_id === article.article_id }">
                    <a-checkbox class="article-check" :checked="checkedIds.includes(article.article_id)" :aria-label="`勾选 ${article.title}`" @change="toggleArticle(article.article_id)" />
                    <button class="card-open" type="button" :aria-label="`查看 ${article.title}`" @click="selectArticle(article.article_id)">
                      <div class="card-image"><img v-if="article.images[0]" :src="article.images[0].url" :alt="article.title" loading="lazy" /><span v-else>暂无本地图片</span><span class="image-count">{{ article.image_count }} 图</span></div>
                      <div class="card-content"><span class="card-category">{{ article.category || '未分类' }}</span><h3>{{ article.title }}</h3><p class="card-summary">{{ article.summary || '未提供摘要' }}</p><div class="card-meta"><span>{{ article.source || '来源未提供' }}</span><time>{{ dateLabel(article.published_at) }}</time></div></div>
                    </button>
                  </article>
                </div>
                <a-empty v-else-if="!loading" :description="invalidDates ? '请调整日期范围' : '没有符合条件的文章'" class="empty-state" />
              </a-spin>
              <a-pagination v-model:current="page" v-model:page-size="pageSize" :total="total" :page-size-options="['12', '24', '48', '96']" show-size-changer show-quick-jumper :disabled="loading" class="pagination" />
            </div>
            <aside ref="detailPanel" class="detail-panel" aria-label="文章详情">
              <div class="detail-heading"><div><span class="eyebrow">ARTICLE DETAIL</span><h2>文章详情</h2></div><a v-if="safeLink(selectedArticle?.source_url)" :href="safeLink(selectedArticle?.source_url)" target="_blank" rel="noopener noreferrer" aria-label="打开文章原文"><LinkOutlined /></a></div>
              <a-spin :spinning="detailLoading"><div class="detail-content">
                <a-alert v-if="detailError" type="error" :message="detailError" />
                <template v-else-if="selectedArticle">
                  <a-image-preview-group v-if="selectedArticle.images.length"><div class="featured-image"><a-image :src="selectedArticle.images[selectedImage]?.url" :alt="selectedArticle.title" /></div></a-image-preview-group>
                  <div class="detail-title-block"><p class="detail-overline">{{ selectedArticle.category || '未分类' }} · {{ selectedArticle.source }}</p><h3>{{ selectedArticle.title }}</h3><time>发布于 {{ dateLabel(selectedArticle.published_at) }}</time></div>
                  <div class="detail-section"><h4>文章摘要 · 聚类文字依据</h4><p class="summary">{{ selectedArticle.summary || '源表未提供摘要。' }}</p></div>
                  <div v-if="selectedArticle.images.length" class="detail-section"><h4>关联原图 {{ selectedArticle.images.length }} 张 · 点击放大</h4><a-image-preview-group><div class="image-grid"><a-image v-for="image in selectedArticle.images" :key="image.image_id" :src="image.url" :alt="selectedArticle.title" loading="lazy" /></div></a-image-preview-group></div>
                  <p class="source-note">文章 ID {{ selectedArticle.article_id }} · 图片不参与语义聚类</p>
                  <a-button block :type="checkedIds.includes(selectedArticle.article_id) ? 'default' : 'primary'" @click="toggleArticle(selectedArticle.article_id)">{{ checkedIds.includes(selectedArticle.article_id) ? '移出勾选范围' : '加入勾选范围' }}</a-button>
                </template>
                <div v-else class="empty-state">选择文章查看原文摘要与图片</div>
              </div></a-spin>
            </aside>
          </section>
        </a-tab-pane>
        <a-tab-pane key="tasks" :tab="`聚类任务与结果（${taskList.length}）`">
          <div class="section-heading"><div><h2>聚类任务</h2><p>支持优先级由去重来源组和文章证据决定；数量由语义与证据形成，不设上限。</p></div><a-button :loading="refreshing" @click="refreshTasks">刷新状态</a-button></div>
          <a-alert v-if="taskError" type="error" :message="taskError" show-icon class="notice" />
          <div class="tasks-layout">
            <div class="task-list">
              <button v-for="task in taskList" :key="task.id" type="button" class="task-card" :class="{ selected: activeTaskId === task.id }" @click="showTask(task.id)">
                <div><strong>{{ task.title || `${task.article_count.toLocaleString()} 篇文章` }}</strong><a-tag :color="task.kind === 'historical' ? 'gold' : task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : 'purple'">{{ task.kind === 'historical' ? '历史存档' : statusNames[task.status] }}</a-tag></div>
                <p>{{ task.stage }}</p>
                <a-progress v-if="task.kind !== 'historical'" :percent="progress(task)" size="small" :status="task.status === 'failed' ? 'exception' : undefined" />
                <small>{{ dateLabel(task.created_at) }}<template v-if="task.calls !== null"> · 已尝试 {{ task.calls }} 次</template><template v-else> · 仅展示已有结果</template></small>
                <small class="task-id">{{ task.id }}</small>
              </button>
              <a-empty v-if="!taskList.length" description="尚未创建聚类任务" />
            </div>
            <div class="task-detail"><a-spin :spinning="taskDetailLoading"><template v-if="activeTask">
              <div class="section-heading"><div><h2>{{ activeTask.title || `${statusNames[activeTask.status]} · ${activeTask.article_count.toLocaleString()} 篇` }}</h2><p v-if="!isHistorical">{{ activeTask.stage }} · {{ activeTask.completed_steps }} / {{ activeTask.total_steps }} 步 · {{ activeTask.calls }} / {{ activeTask.max_calls ?? '—' }} 次尝试</p><p v-else>原始范围 {{ activeTask.article_count.toLocaleString() }} 篇 · {{ dateLabel(activeTask.created_at) }}</p></div><a-button v-if="!isHistorical && ['failed', 'interrupted'].includes(activeTask.status)" @click="askResume">恢复任务</a-button></div>
              <a-alert v-if="activeTask.legacy_notice" type="warning" :message="activeTask.legacy_notice" show-icon class="notice" />
              <p v-if="activeTask.download_description" class="muted">下载内容：{{ activeTask.download_description }}</p>
              <p v-if="activeTask.model_id" class="muted">模型：{{ models.find(model => model.id === activeTask?.model_id)?.name || activeTask.model_id }} · Skill {{ activeTask.skill_version }} · 入选至少 {{ activeTask.min_source_groups }} 个来源组</p>
              <p v-if="activeTask.usage" class="muted">已记录 {{ activeTask.usage.requests }} 次模型请求，其中 {{ activeTask.usage.requests_with_usage }} 次有完整用量；已知输入 / 输出 Token：{{ activeTask.usage.input_tokens.toLocaleString() }} / {{ activeTask.usage.output_tokens.toLocaleString() }}。预算按尝试预扣，缺失回执不代表零消耗。</p>
              <a-progress v-if="!isHistorical" :percent="progress(activeTask)" :status="activeTask.status === 'failed' ? 'exception' : undefined" />
              <a-alert v-if="activeTask.error" type="warning" show-icon :message="activeTask.error" class="notice" />
              <p v-if="['running', 'queued'].includes(activeTask.status)" class="muted">任务在后台执行，页面每 5 秒更新。可以切换页面，稍后查看。</p>
              <template v-if="result">
                <div class="result-heading"><div><h2>共同趋势 <span>{{ rankedTrends.length }} 条</span></h2><p>{{ isHistorical ? '沿用历史排序与统计口径，不受当前输入日期筛选影响。' : '按支持优先级排序；单篇线索不进入正式趋势。' }}</p></div><a-button :href="activeTask.download_url || `/api/v1/article-trends/tasks/${encodeURIComponent(activeTask.id)}/download`" target="_blank">{{ isHistorical ? '下载历史完整趋势原档' : '下载完整结果' }}</a-button></div>
                <a-tabs>
                  <a-tab-pane key="trends" :tab="isHistorical ? '历史排序趋势' : '优先级趋势'">
                    <article v-for="(trend, index) in visibleTrends" :key="textField(trend, 'theme_id', 'title')" class="trend-result">
                      <div class="trend-title"><span class="rank-number">{{ trend.priority_rank ?? (resultPage - 1) * 12 + index + 1 }}</span><h3>{{ textField(trend, 'title', 'name', 'label') || '未命名趋势' }}</h3></div>
                      <p>{{ textField(trend, 'definition', 'summary') }}</p>
                      <div class="support-metrics"><a-tag color="purple">{{ textField(trend, 'source_group_count') || '—' }} 个来源组</a-tag><a-tag>{{ textField(trend, 'article_count') || listField(trend, 'members').length }} {{ isHistorical ? '篇关联文章（历史口径）' : '篇支持文章' }}</a-tag><a-tag v-if="trend.primary_article_count !== undefined">{{ trend.primary_article_count }} 篇主成员</a-tag></div>
                      <section v-if="isHistorical" class="trend-gallery" aria-label="趋势关联文章图片">
                        <div class="trend-gallery-heading"><h4>关联文章图片</h4><span>点击图片放大 · 点击标题查看文章</span></div>
                        <a-image-preview-group v-if="relatedImages(trend).length">
                          <div class="trend-image-grid">
                            <figure v-for="image in relatedImages(trend)" :key="image.url" class="trend-image-item" :data-article-id="image.article_id">
                              <a-image :src="image.url" :alt="image.article_title" loading="lazy" @error="hideUnavailableImage(image.url)" />
                              <figcaption><button type="button" class="text-button" @click="openEvidence(image.article_id)">{{ image.article_title }}</button></figcaption>
                            </figure>
                          </div>
                        </a-image-preview-group>
                        <p v-else class="muted">暂无可显示的本地图片</p>
                      </section>
                      <p v-if="isHistorical" class="muted">{{ textField(trend, 'counting_note') }} · 下方展示 {{ listField(trend, 'members').length }} 篇代表文章证据，全部证据见历史原档。</p>
                      <p v-if="trend.boundary" class="muted">边界：{{ textField(trend, 'boundary') }}</p>
                      <p v-if="trend.design_question">设计议题：{{ textField(trend, 'design_question') }}</p>
                      <details><summary>查看文章证据与次级关联</summary><div v-for="(member, memberIndex) in listField(trend, 'members')" :key="memberIndex" class="evidence-row"><button type="button" class="text-button" @click="openEvidence(textField(member, 'article_id', 'id'))">{{ textField(member, 'title', 'article_title', 'article_id', 'id') || '文章证据' }}</button><blockquote v-if="textField(member, 'anchor', 'quote', 'evidence_quote', 'evidence')">{{ textField(member, 'anchor', 'quote', 'evidence_quote', 'evidence') }}</blockquote><p v-if="textField(member, 'reason', 'rationale')">{{ textField(member, 'reason', 'rationale') }}</p><details><summary>原始证据字段</summary><pre>{{ JSON.stringify(member, null, 2) }}</pre></details></div><div v-if="listField(trend, 'secondary_members').length"><h4>次级关联（不重复计主成员）</h4><div v-for="(member, memberIndex) in listField(trend, 'secondary_members')" :key="memberIndex" class="evidence-row"><button type="button" class="text-button" @click="openEvidence(textField(member, 'article_id', 'id'))">{{ textField(member, 'title', 'article_title', 'article_id', 'id') }}</button><blockquote>{{ textField(member, 'anchor', 'quote') }}</blockquote></div></div></details>
                    </article>
                    <a-empty v-if="!rankedTrends.length" description="当前范围没有达到多篇共同支持要求的趋势，可查看候选池。" />
                    <a-pagination v-if="rankedTrends.length > 12" v-model:current="resultPage" :total="rankedTrends.length" :page-size="12" :show-size-changer="false" class="pagination" />
                  </a-tab-pane>
                  <a-tab-pane key="candidates" :tab="`候选池（${candidatePool.length}）`"><p class="muted">保留单篇、弱证据和未入选线索，以及对应原因，供后续补证和人工审阅。</p><div v-for="(candidate, index) in visibleCandidates" :key="index" class="candidate-row"><h3>{{ textField(candidate, 'title', 'name', 'theme_id', 'article_id') || '待补证线索' }}</h3><p>{{ textField(candidate, 'pool_reason', 'reason', 'exclusion_reason', 'definition', 'summary') }}</p><button v-if="candidate.article_id" type="button" class="text-button" @click="openEvidence(String(candidate.article_id))">查看文章 {{ candidate.article_id }}</button><details><summary>查看证据与未入选原因</summary><pre>{{ JSON.stringify(candidate, null, 2) }}</pre></details></div><a-empty v-if="!candidatePool.length" description="没有候选池记录" /><a-pagination v-if="candidatePool.length > 15" v-model:current="candidatePage" :total="candidatePool.length" :page-size="15" :show-size-changer="false" class="pagination" /></a-tab-pane>
                  <a-tab-pane key="audit" tab="覆盖与审计"><p class="muted">保留输入覆盖、来源分组和主次归属，完整记录可下载查看。</p><pre class="audit-json">{{ JSON.stringify(result.coverage, null, 2) }}</pre></a-tab-pane>
                </a-tabs>
              </template>
              <a-empty v-else-if="activeTask.status === 'completed'" description="该任务未提供结果，请刷新或查看任务记录。" />
            </template><a-empty v-else description="选择任务查看进度与结果" /></a-spin></div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </main>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>本地文章资料库 · Skill {{ catalog?.skill_version || '—' }}</span></footer>
    <a-modal v-model:open="confirmOpen" title="确认启动纯文本趋势聚类" ok-text="确认并运行模型" cancel-text="返回调整" :confirm-loading="starting" :closable="!starting" :mask-closable="!starting" :cancel-button-props="{ disabled: starting }" @ok="startCluster">
      <template v-if="preview">
        <p>输入趋势日期：{{ dateRangeLabel }}</p>
        <p>本次将处理 {{ preview.article_count.toLocaleString() }} 篇文章、{{ preview.source_group_count.toLocaleString() }} 个去重来源组，预计 {{ preview.estimated_calls }} 次模型调用。</p>
        <p>模型：{{ models.find(model => model.id === modelId)?.name || modelId }}；调用上限 {{ maxCalls }} 次。每个正式趋势至少 {{ minSources }} 个来源组支持，趋势总数不限。</p>
        <p>聚类只读取标题与摘要；图片用于文章浏览。任务创建后可在任务页查看进度和结果。</p>
      </template>
    </a-modal>
    <a-modal v-model:open="resumeOpen" title="恢复聚类任务" ok-text="确认恢复" cancel-text="取消" :confirm-loading="resuming" @ok="resumeTask"><p>从已保存的步骤继续，已完成的步骤不会重复执行。请设置整个任务累计尝试上限。</p><a-input-number v-model:value="resumeMaxCalls" :min="(activeTask?.calls ?? 0) + 1" :max="5000" :precision="0" /></a-modal>
  </div>
</template>

<style scoped>
.article-shell { overflow: clip; }
.history-entry { margin-top: 16px; }
.article-hero { padding: 48px 0 24px; }
.article-hero h1 { margin: 18px 0 10px; font-size: 29px; color: #342c47; }
.article-hero p, .section-heading p, .result-heading p { margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.principles { display: flex; flex-wrap: wrap; gap: 8px; margin: 17px 0 0; }
.principles span { padding: 5px 10px; background: #eeebf8; border-radius: 20px; color: #736196; font-size: 11px; }
.filter-panel { display: grid; grid-template-columns: minmax(190px, 1.4fr) repeat(2, minmax(120px, 1fr)) auto; gap: 12px; align-items: end; padding: 20px; background: var(--card); border: 1px solid var(--line); border-radius: 18px; }
.cluster-date-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)) auto; gap: 14px; align-items: end; margin-bottom: 12px; }
.filter-field { display: grid; gap: 7px; min-width: 0; }
.filter-field label { color: #867d94; font-size: 11px; }
.filter-field input, .filter-field select { width: 100%; min-width: 0; height: 36px; padding: 0 10px; color: #4b405b; background: #fcfbfe; border: 1px solid #e6e0ed; border-radius: 8px; font-size: 12px; }
.filter-field input:focus, .filter-field select:focus { outline: 2px solid #bbb0ed; outline-offset: 1px; }
.filter-field :deep(.ant-input-number), .filter-field :deep(.ant-select) { width: 100%; }
.search-input { position: relative; }
.search-input :deep(.anticon) { position: absolute; top: 12px; left: 11px; color: #a199ae; }
.search-input input { padding-left: 32px; }
.reset-button { height: 36px; padding: 0 14px; color: #695b8a; background: #f2eef9; border: 0; border-radius: 9px; cursor: pointer; font-size: 12px; }
.date-error, .warning-text { color: #a46b25; font-size: 12px; }
.date-error { grid-column: 1 / -1; margin: 0; }
.cluster-panel { padding: 22px; margin-top: 16px; background: linear-gradient(125deg, #fff, #f8f6ff); border: 1px solid #ded5f0; border-radius: 18px; }
.section-heading, .result-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.section-heading h2, .result-heading h2 { margin: 0; font-size: 18px; color: #3c3052; }
.scope-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
.muted { color: #8e829d; font-size: 12px; line-height: 1.7; }
.cluster-controls { display: grid; grid-template-columns: 1fr 1.7fr 1fr 1fr auto; gap: 14px; align-items: end; }
.budget-note { margin: 14px 0 0; }
.estimate-box { margin-top: 18px; padding: 18px; background: #f0ecfb; border-radius: 12px; }
.estimate-metrics { display: flex; flex-wrap: wrap; gap: 16px; color: #706382; font-size: 12px; }
.estimate-metrics strong { color: #594697; font-size: 18px; }
.estimate-footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-top: 16px; }
.article-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; align-items: start; margin: 28px 0 45px; }
.article-list { min-width: 0; }
.list-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
.list-heading h2 { margin: 0; color: #342c47; font-size: 18px; }
.list-heading h2 span, .result-heading h2 span { margin-left: 7px; color: #9e93ad; font-size: 13px; font-weight: 400; }
.list-heading p { margin: 5px 0 0; color: #9e93ad; font-size: 11px; }
.article-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.article-card { position: relative; overflow: hidden; min-width: 0; background: white; border: 1px solid #e8e2ee; border-radius: 16px; box-shadow: 0 8px 26px rgba(53, 44, 105, .04); transition: border-color .2s; }
.article-card.selected { border-color: #8e7adf; box-shadow: 0 0 0 2px rgba(98, 87, 216, .13); }
.article-check { position: absolute; top: 10px; left: 10px; z-index: 1; padding: 3px; background: #fffffff2; border-radius: 5px; }
.card-open { display: block; padding: 0; width: 100%; background: transparent; border: 0; text-align: left; cursor: pointer; }
.card-open:focus-visible { outline: 3px solid #8e7adf; outline-offset: -3px; }
.card-image { position: relative; height: 150px; overflow: hidden; background: #eeeaf3; color: var(--muted); display: grid; place-items: center; }
/* 原图脱离网格的固有最小尺寸，竖图也只占封面区域，不能覆盖下方标题和摘要。 */
.card-image img { position: absolute; inset: 0; display: block; width: 100%; height: 100%; min-height: 0; object-fit: cover; }
.image-count { position: absolute; right: 8px; bottom: 8px; padding: 3px 6px; background: #ffffffdf; color: #6d5e80; border-radius: 4px; font-size: 10px; }
.card-content { padding: 13px; }
.card-category { color: #6953a5; font-size: 10px; }
.card-content h3 { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; min-height: 40px; margin: 7px 0 10px; color: #342c47; font-size: 13px; line-height: 1.5; }
.card-summary { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; color: #9a90a4; font-size: 11px; line-height: 1.6; min-height: 35px; }
.card-meta { display: flex; justify-content: space-between; gap: 5px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #f0edf3; color: #9c93a8; font-size: 10px; }
.card-meta span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.card-meta time { flex-shrink: 0; }
.detail-panel { position: sticky; top: 18px; max-height: calc(100vh - 36px); overflow-y: auto; background: white; border: 1px solid #e7e1ee; border-radius: 18px; }
.detail-heading { display: flex; justify-content: space-between; align-items: center; padding: 17px 18px; border-bottom: 1px solid #eee8f3; }
.eyebrow { color: #a692c4; font-size: 9px; letter-spacing: .12em; }
.detail-heading h2 { margin: 4px 0 0; color: #3c3052; font-size: 16px; }
.detail-heading a { color: #7663aa; padding: 8px; }
.detail-content { padding: 18px; min-height: 160px; }
.featured-image { display: flex; justify-content: center; overflow: hidden; width: 100%; max-height: 240px; background: #f1edf6; border-radius: 12px; }
.featured-image :deep(img) { max-height: 240px; object-fit: contain; }
.detail-title-block { padding: 16px 0 19px; border-bottom: 1px solid #f0edf3; }
.detail-overline { margin: 0 0 8px; color: #765db5; font-size: 10px; }
.detail-title-block h3 { margin: 0; color: #332943; font-size: 17px; line-height: 1.55; }
.detail-title-block time { display: block; margin-top: 10px; color: #a69cad; font-size: 10px; }
.detail-section { margin-top: 19px; }
.detail-section h4 { margin: 0 0 9px; color: #8a7d9b; font-size: 11px; font-weight: 500; }
.summary { margin: 0; color: #5d5368; font-size: 12px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.image-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.image-grid :deep(.ant-image) { aspect-ratio: 1; overflow: hidden; border-radius: 7px; }
.image-grid :deep(img) { width: 100%; height: 100%; object-fit: cover; }
.source-note { margin: 20px 0 14px; color: #aaa0b1; font-size: 10px; }
.empty-state { padding: 45px 12px; color: #9c91aa; text-align: center; }
.pagination { margin: 24px 0; display: flex; flex-wrap: wrap; gap: 4px; justify-content: center; }
.notice { margin-bottom: 16px; }
.tasks-layout { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 24px; margin-bottom: 50px; }
.task-list { display: grid; align-content: start; gap: 12px; }
.task-card { width: 100%; text-align: left; padding: 17px; border: 1px solid #e7e1ef; border-radius: 14px; background: white; cursor: pointer; }
.task-card.selected { border-color: #9682d7; background: #f9f7ff; }
.task-card > div:first-child { display: flex; justify-content: space-between; align-items: center; }
.task-card strong { font-size: 14px; color: #4c3c64; }
.task-card p, .task-card small { font-size: 11px; color: #94859e; }
.task-card p { margin: 9px 0 0; }
.task-id { display: block; margin-top: 8px; overflow-wrap: anywhere; font-size: 9px !important; }
.task-detail { padding: 24px; background: white; border: 1px solid #e7e1ef; border-radius: 18px; min-width: 0; }
.result-heading { margin-top: 26px; }
.trend-result, .candidate-row { padding: 18px; margin-bottom: 13px; border: 1px solid #e9e3f0; border-radius: 12px; }
.trend-title { display: flex; align-items: center; gap: 12px; }
.rank-number { display: grid; min-width: 30px; height: 30px; padding: 0 5px; place-items: center; color: #7257b5; background: #f0ebfa; border-radius: 8px; font-weight: 600; }
.trend-title h3, .candidate-row h3 { margin: 0; font-size: 16px; color: #4c3b63; }
.trend-result p, .candidate-row p { color: #786c85; font-size: 13px; line-height: 1.8; white-space: pre-wrap; }
.support-metrics { margin-bottom: 12px; }
.trend-gallery { margin: 16px 0; }
.trend-gallery-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 14px; margin-bottom: 10px; }
.trend-gallery-heading h4 { margin: 0; color: #685678; font-size: 12px; }
.trend-gallery-heading span { color: #9a8ea5; font-size: 11px; }
.trend-image-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.trend-image-item { min-width: 0; margin: 0; }
.trend-image-item :deep(.ant-image) { display: block; width: 100%; aspect-ratio: 4 / 3; overflow: hidden; border-radius: 8px; background: #f1edf6; }
.trend-image-item :deep(.ant-image-img) { display: block; width: 100%; height: 100%; object-fit: contain; }
.trend-image-item figcaption { padding-top: 7px; }
.trend-image-item .text-button { display: -webkit-box; width: 100%; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
@media (max-width: 900px) { .trend-image-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
details { margin-top: 12px; }
summary { cursor: pointer; font-size: 12px; color: #7860a8; }
pre { overflow: auto; max-height: 350px; padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.7; background: #f7f5fa; border-radius: 8px; }
.audit-json { max-height: 650px; }
.evidence-row { padding: 12px 0; border-bottom: 1px solid #eee8f3; }
.text-button { padding: 0; color: #6c54a3; background: none; border: 0; cursor: pointer; text-align: left; font-size: 12px; }
blockquote { margin: 10px 0; padding-left: 12px; border-left: 3px solid #d7cbea; color: #756284; font-size: 12px; line-height: 1.8; white-space: pre-wrap; }
@media (max-width: 1200px) { .article-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .filter-panel { grid-template-columns: repeat(3, minmax(0, 1fr)); } .cluster-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .article-layout { grid-template-columns: minmax(0, 1fr) 300px; } .article-grid { grid-template-columns: 1fr; } .tasks-layout { grid-template-columns: 220px minmax(0, 1fr); } }
@media (max-width: 700px) { .article-hero h1 { font-size: 24px; } .filter-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); } .keyword-field { grid-column: 1 / -1; } .article-layout, .tasks-layout { grid-template-columns: 1fr; } .article-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .detail-panel { position: static; max-height: none; } .task-list { grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: 290px; overflow-y: auto; } .estimate-footer { align-items: flex-start; flex-direction: column; } .task-detail { padding: 16px; } }
@media (max-width: 480px) { .article-grid, .cluster-controls, .cluster-date-row, .task-list { grid-template-columns: 1fr; } .filter-panel, .cluster-panel { padding: 15px; } .section-heading, .result-heading { align-items: flex-start; } }
</style>
