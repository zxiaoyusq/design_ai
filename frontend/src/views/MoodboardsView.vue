<script setup lang="ts">
import MainNavigation from '@/components/MainNavigation.vue'
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { Modal } from 'ant-design-vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRightOutlined, BulbOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { clusteringDownloadUrl, createClusteringTask, fetchClusteringCatalog, fetchClusteringTask, fetchClusteringTasks, previewClusteringInput } from '@/api/moodboards'
import LegacyMoodboardResults from '@/components/LegacyMoodboardResults.vue'
import ExistingSkillMoodboards from '@/components/ExistingSkillMoodboards.vue'
import type { ClusteringBoard, ClusteringCatalog, ClusteringPreview, ClusteringRequest, ClusteringTask } from '@/types/moodboards'

const route = useRoute()
const router = useRouter()
const catalog = ref<ClusteringCatalog>({ results: [], default_model: '', models: [], rules: { min_images: 6, max_images: 10, category_max_ratio: 0.5 }, warnings: [] })
const sourceId = ref('')
const directionIds = ref<string[]>([])
const modelId = ref('')
const prepareMissing = ref(false)
const maxCalls = ref(100)
const workers = ref(4)
const preview = ref<ClusteringPreview | null>(null)
const previewLoading = ref(false)
const previewPage = ref(1)
const previewFilter = ref('all')
const loading = ref(true)
const starting = ref(false)
const error = ref('')
const previewError = ref('')
const pollError = ref('')
const history = ref<ClusteringTask[]>([])
const task = ref<ClusteringTask | null>(null)
const selectedTaskId = ref('')
const taskLoading = ref(false)
const historyLoading = ref(false)
const resultTab = ref(typeof route.query.task === 'string' || typeof route.query.native_run === 'string' ? 'legacy' : typeof route.query.cluster_task === 'string' ? 'current' : 'saved')
const inspected = ref<ClusteringBoard['members'][number] | null>(null)
const detailOpen = ref(false)
let disposed = false
let previewVersion = 0
let taskVersion = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined
const source = computed(() => catalog.value.results.find(item => item.id === sourceId.value))
const allDirectionsSelected = computed(() => Boolean(source.value?.directions.length) && directionIds.value.length === source.value?.directions.length)
const candidateImages = computed(() => preview.value?.images.filter(item => previewFilter.value === 'all' || item.status === previewFilter.value) ?? [])
const visibleImages = computed(() => candidateImages.value.slice((previewPage.value - 1) * 12, previewPage.value * 12))
const participatingCount = computed(() => (preview.value?.counts.ready_images ?? 0) + (prepareMissing.value ? preview.value?.counts.missing_dna ?? 0 : 0))
const isActive = (item: ClusteringTask | null) => item?.status === 'queued' || item?.status === 'running'
const anyActive = computed(() => isActive(task.value) || history.value.some(isActive))
const validRequest = computed(() => Boolean(preview.value && modelId.value && participatingCount.value >= catalog.value.rules.min_images && Number.isInteger(maxCalls.value) && maxCalls.value > 0 && maxCalls.value <= 2000 && Number.isInteger(workers.value) && workers.value >= 1 && workers.value <= 10))
const statusLabels = { queued: '等待执行', running: '执行中', completed: '执行完成', partial: '部分完成', failed: '执行失败' }
const imageStatusLabels = { ready: 'DNA 可复用', missing_dna: '待补 DNA', unavailable: '原图不可用', excluded: '已排除' }
const stageLabels: Record<string, string> = { queued: '排队', preparing: 'DNA 准备', preparation: 'DNA 准备', dna_preparation: 'DNA 准备', clustering: '统一情绪聚类', discovery: '关系发现', merge: '跨批归并', routing: '全卡路由', nomination: '候选提名', visual_selection: '原图与冻结裁片选组', discover: '关系发现', route_including_catalogue: '目录路由', nominate: '候选提名', visual: '原图与冻结裁片选组', finished: '执行结束', completed: '完成', failed: '失败', partial: '部分完成' }

function readError(value: unknown, fallback: string) {
  const detail = (value as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map(item => String(item.msg ?? '参数无效')).join('；')
  return typeof detail === 'string' ? detail : value instanceof Error ? value.message : fallback
}
function dateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
/** 输入一变即丢弃快照和在途旧响应，不把旧方向的图片用于新方向的确认。 */
function invalidatePreview() {
  previewVersion++
  preview.value = null
  previewError.value = ''
  previewLoading.value = false
  previewPage.value = 1
}
watch(sourceId, () => { directionIds.value = source.value?.directions.map(item => item.id) ?? []; invalidatePreview() }, { flush: 'sync' })
watch(directionIds, invalidatePreview, { deep: true, flush: 'sync' })
watch(previewFilter, () => { previewPage.value = 1 })
watch(() => route.query.cluster_task, value => { if (typeof value === 'string' && value !== selectedTaskId.value) void selectTask(value) })

async function inspectInput() {
  if (!sourceId.value || !directionIds.value.length) return
  const version = ++previewVersion
  preview.value = null
  previewLoading.value = true
  previewError.value = ''
  try {
    const response = await previewClusteringInput(sourceId.value, [...directionIds.value])
    if (!disposed && version === previewVersion) { preview.value = response; previewPage.value = 1 }
  } catch (cause) { if (!disposed && version === previewVersion) previewError.value = readError(cause, '图片范围预览失败') }
  finally { if (version === previewVersion) previewLoading.value = false }
}
function updateHistory(current: ClusteringTask) {
  const index = history.value.findIndex(item => item.id === current.id)
  if (index < 0) history.value.unshift(current)
  else history.value[index] = current
}
async function refreshHistory() {
  historyLoading.value = true
  try { const response = await fetchClusteringTasks(); if (!disposed) history.value = response }
  catch (cause) { if (!disposed) error.value = readError(cause, '任务记录读取失败') }
  finally { historyLoading.value = false }
}
async function loadTask(id: string, version: number) {
  try {
    const response = await fetchClusteringTask(id)
    if (disposed || version !== taskVersion) return
    task.value = response
    updateHistory(response)
    pollError.value = ''
    if (isActive(response)) pollTimer = setTimeout(() => void loadTask(id, version), 2500)
  } catch (cause) {
    if (disposed || version !== taskVersion) return
    pollError.value = readError(cause, '任务读取失败，正在重试')
    pollTimer = setTimeout(() => void loadTask(id, version), 5000)
  } finally { if (version === taskVersion) taskLoading.value = false }
}
async function selectTask(id: string) {
  clearTimeout(pollTimer)
  const version = ++taskVersion
  task.value = null
  selectedTaskId.value = id
  taskLoading.value = true
  resultTab.value = 'current'
  pollError.value = ''
  void router.replace({ query: { ...route.query, cluster_task: id, task: undefined, native_run: undefined } })
  await loadTask(id, version)
}
function confirmStart() {
  const frozen = preview.value
  if (!frozen || !validRequest.value || starting.value || anyActive.value) return
  const body: ClusteringRequest = { preview_id: frozen.preview_id, model_id: modelId.value, prepare_missing: prepareMissing.value, max_calls: maxCalls.value, workers: workers.value, confirmed: true }
  const titles = source.value?.directions.filter(item => directionIds.value.includes(item.id)).map(item => item.title) ?? []
  Modal.confirm({
    title: '确认按当前图片范围开始聚类？', centered: true, okText: '确认并开始', cancelText: '返回检查',
    content: h('div', [
      h('p', `${source.value?.title ?? '高潜趋势结果'} · ${titles.join('、')}`),
      h('p', `可读候选原图 ${frozen.counts.total_images} 张；现有 DNA 可复用 ${frozen.counts.ready_images} 张（${frozen.counts.ready_cards} 张设计卡）。`),
      h('p', body.prepare_missing ? `授权先补 ${frozen.counts.missing_dna} 张缺失 DNA，完成并冻结后再聚类；未成功补齐的图片会单独记录。` : `不补 DNA，仅聚类 ${frozen.counts.ready_images} 张已有兼容设计卡的图片；${frozen.counts.missing_dna} 张缺失 DNA 不参与。`),
      h('p', `原图不可用 ${frozen.counts.unavailable_images} 张，已排除 ${frozen.counts.excluded_images} 张。`),
      h('p', `模型 ${catalog.value.models.find(item => item.id === body.model_id)?.name ?? body.model_id}；并发 ${body.workers}；DNA 补查与聚类合计最多 ${body.max_calls} 次模型调用。`),
      h('p', '各趋势图片合并探索，不按原趋势或批次分成独占组。不预设板数；预算不足保留部分结果，不自动兑换额度或重试。'),
    ]),
    async onOk() {
      // 确认框打开期间若输入被改动，必须重新预览，不能执行旧的隐藏选择。
      if (disposed || starting.value || preview.value?.preview_id !== body.preview_id) throw new Error('输入已变化，请重新预览并确认')
      starting.value = true
      error.value = ''
      try {
        const created = await createClusteringTask(body)
        if (!disposed) { updateHistory(created); await selectTask(created.id) }
      } catch (cause) { error.value = readError(cause, '聚类任务启动失败'); throw cause }
      finally { starting.value = false }
    },
  })
}
function inspectMember(member: ClusteringBoard['members'][number]) { inspected.value = member; detailOpen.value = true }

onMounted(async () => {
  const [catalogResponse, historyResponse] = await Promise.allSettled([fetchClusteringCatalog(), fetchClusteringTasks()])
  if (disposed) return
  const problems: string[] = []
  if (catalogResponse.status === 'fulfilled') {
    catalog.value = catalogResponse.value
    modelId.value = catalog.value.default_model || catalog.value.models[0]?.id || ''
    sourceId.value = catalog.value.results[0]?.id ?? ''
  } else problems.push(readError(catalogResponse.reason, '高潜趋势目录读取失败'))
  if (historyResponse.status === 'fulfilled') history.value = historyResponse.value
  else problems.push(readError(historyResponse.reason, '聚类任务记录读取失败'))
  error.value = problems.join('；')
  loading.value = false
  if (resultTab.value === 'current') {
    const id = typeof route.query.cluster_task === 'string' ? route.query.cluster_task : (history.value.find(isActive) ?? history.value[0])?.id
    if (id) void selectTask(id)
  }
})
onUnmounted(() => { disposed = true; previewVersion++; taskVersion++; clearTimeout(pollTimer) })
</script>

<template>
  <div class="app-shell moodboards-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar"><RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink><MainNavigation /><div class="system-state"><span></span> 审美洞察工作台</div></header>
    <main>
      <section class="hero moodboard-hero"><div class="hero-badge"><BulbOutlined /> DESIGN EMOTION CLUSTERING</div><h1>情绪版生成</h1><p>选择高潜趋势结果中的方向，汇集其图片。先复用／补齐 DNA，再由大模型跨批比较设计关系，并结合原图与冻结裁片选组。</p><div class="rule-chips"><span>统一设计情绪 · 不分 ID / CMF</span><span>每板 {{ catalog.rules.min_images }}–{{ catalog.rules.max_images }} 张</span><span>同品类 ≤ {{ catalog.rules.category_max_ratio * 100 }}%</span><span>跨品类、跨材质 · 不强凑</span></div></section>
      <a-alert v-if="error" class="page-alert" type="error" show-icon :message="error" closable @close="error = ''" />
      <a-alert v-for="warning in catalog.warnings" :key="warning" class="page-alert" type="warning" show-icon :message="warning" />
      <a-spin :spinning="loading">
        <section id="moodboard-new" class="workspace-card input-panel">
          <div class="panel-heading"><div><span class="eyebrow">01 / 选择图片来源</span><h2>高潜趋势结果</h2><p>趋势决定候选范围，不预设最终情绪板。所选方向的图片去重后合并聚类。</p></div><span class="count-badge">已选 {{ directionIds.length }} 个方向</span></div>
          <label class="field-label" for="moodboard-source">选择已有结果</label><a-select id="moodboard-source" v-model:value="sourceId" class="source-select" placeholder="选择高潜趋势结果" :options="catalog.results.map(item => ({ value: item.id, label: `${item.title} · ${dateTime(item.created_at)} · ${item.directions.length} 个方向` }))" />
          <a-empty v-if="!loading && !catalog.results.length" description="暂无可选高潜趋势结果，请先在高潜趋势页面生成结果。" />
          <div v-if="source" class="direction-toolbar"><a-checkbox :checked="allDirectionsSelected" :indeterminate="directionIds.length > 0 && !allDirectionsSelected" @change="directionIds = $event.target.checked ? source.directions.map(item => item.id) : []">选择全部方向</a-checkbox><span>至少选择一个方向；不会只截取前 100 张。</span></div>
          <a-checkbox-group v-model:value="directionIds" class="direction-grid"><div v-for="direction in source?.directions ?? []" :key="direction.id" class="direction-option" :class="{ selected: directionIds.includes(direction.id) }"><a-checkbox :value="direction.id">{{ direction.title }}</a-checkbox><p>{{ direction.description }}</p><small v-if="direction.image_reference_count !== undefined">{{ direction.image_reference_count }} 张图片引用 · 去重结果见预览</small></div></a-checkbox-group>
          <div class="preview-action"><a-button type="primary" :loading="previewLoading" :disabled="!sourceId || !directionIds.length || loading || starting" @click="inspectInput">预览图片范围与 DNA 状态 <ArrowRightOutlined /></a-button><span>此步骤只核对输入，不调用模型。</span></div>
          <a-alert v-if="previewError" class="page-alert" type="error" show-icon :message="previewError" />
        </section>
        <section v-if="preview || previewLoading" class="workspace-card input-panel">
          <div class="panel-heading"><div><span class="eyebrow">02 / 核对输入并设置执行</span><h2>先看清本次会处理什么</h2></div></div>
          <a-spin :spinning="previewLoading">
            <template v-if="preview">
              <div class="metrics"><div><strong>{{ preview.counts.total_images }}</strong><span>可读候选原图</span></div><div><strong>{{ preview.counts.ready_images }}</strong><span>DNA 可复用</span></div><div><strong>{{ preview.counts.missing_dna }}</strong><span>待补 DNA</span></div><div><strong>{{ preview.counts.unavailable_images }}</strong><span>原图不可用</span></div><div><strong>{{ preview.counts.excluded_images }}</strong><span>已排除</span></div></div>
              <a-alert v-for="warning in preview.warnings" :key="warning" class="page-alert" type="warning" show-icon :message="warning" />
              <div class="preview-toolbar"><span>图片与状态 · {{ preview.counts.ready_cards }} 张可用设计卡</span><a-select v-model:value="previewFilter" aria-label="筛选图片状态" :options="[{ value: 'all', label: '全部图片' }, ...Object.entries(imageStatusLabels).filter(([value]) => value === 'ready' || value === 'missing_dna').map(([value, label]) => ({ value, label }))]" /></div>
              <div class="preview-grid"><article v-for="item in visibleImages" :key="item.id" class="preview-card"><a-image v-if="item.preview_url" :src="item.preview_url" :alt="item.image_name" :height="150" :width="'100%'" /><span v-else class="image-placeholder">暂无可读原图</span><strong :title="item.image_name">{{ item.image_name }}</strong><a-tag :color="item.status === 'ready' ? 'green' : item.status === 'missing_dna' ? 'orange' : undefined">{{ imageStatusLabels[item.status] }}</a-tag><p>{{ item.reason || item.category || '按实际对象与来源核验' }}</p></article></div>
              <a-empty v-if="!candidateImages.length" description="当前筛选下暂无图片" /><a-pagination v-if="candidateImages.length > 12" v-model:current="previewPage" :total="candidateImages.length" :page-size="12" :show-size-changer="false" size="small" />
              <details v-if="preview.unavailable?.length"><summary>查看不可用图片及原因（{{ preview.counts.unavailable_images }}）</summary><pre>{{ JSON.stringify(preview.unavailable, null, 2) }}</pre></details><details v-if="preview.excluded?.length"><summary>查看已排除图片及原因（{{ preview.counts.excluded_images }}）</summary><pre>{{ JSON.stringify(preview.excluded, null, 2) }}</pre></details><div class="execution-settings"><a-checkbox v-model:checked="prepareMissing" :disabled="!preview.counts.missing_dna">先补齐本次缺失的 DNA（{{ preview.counts.missing_dna }} 张）</a-checkbox><p v-if="preview.counts.missing_dna">{{ prepareMissing ? '仅补查缺失项，准备阶段终结并冻结后再进入聚类；可复用 DNA 不重提。' : `当前只聚类 ${preview.counts.ready_images} 张已有兼容 DNA 的图片；${preview.counts.missing_dna} 张缺失 DNA 将不参与。` }}</p><div class="settings-grid"><div><label for="moodboard-model">分析模型</label><a-select id="moodboard-model" v-model:value="modelId" :options="catalog.models.map(item => ({ value: item.id, label: item.name }))" /></div><div><label for="moodboard-calls">总模型调用预算</label><a-input-number id="moodboard-calls" v-model:value="maxCalls" :min="1" :max="2000" :precision="0" /><small>包含 DNA 补查 + 图片聚类</small></div><div><label for="moodboard-workers">最大并发</label><a-input-number id="moodboard-workers" v-model:value="workers" :min="1" :max="10" :precision="0" /><small>最多 10 路，受实际限流影响</small></div></div><div class="start-row"><p>本次候选上限 <strong>{{ participatingCount }}</strong> 张 · 不预设成板数量<br /><small>按配色、廓形、块面、线条和表面关系综合判断；有设计感不豁免组合冲突。</small></p><a-button type="primary" size="large" :loading="starting" :disabled="!validRequest || anyActive || previewLoading" @click="confirmStart">确认并开始聚类 <ArrowRightOutlined /></a-button></div><p v-if="participatingCount < catalog.rules.min_images" class="warning-copy">可参与图片少于 {{ catalog.rules.min_images }} 张，请调整方向或授权补齐 DNA。</p><p v-if="anyActive" class="warning-copy">已有任务执行中，请等待其结束后再创建新任务。</p><p class="subtle">先完成 DNA 准备，再统一聚类。达到预算会保留部分结果与未完成范围；不自动重试、兑换额度，也不会把未处理图片判为低质量。</p></div>
            </template>
          </a-spin>
        </section>
      </a-spin>
      <section id="moodboard-results" class="workspace-card results-panel">
        <div class="panel-heading"><div><span class="eyebrow">03 / 结果与执行记录</span><h2>情绪板工作区</h2><p>模型选组、约束检查和人工认可分别记录；没有正式板时如实保留小组与缺口。</p></div><a-button v-if="resultTab === 'current'" :loading="historyLoading" @click="refreshHistory"><ReloadOutlined /> 刷新记录</a-button><a href="#moodboard-new">新建聚类</a></div>
        <a-tabs v-model:active-key="resultTab">
          <a-tab-pane key="saved" tab="Skill 已有结果"><ExistingSkillMoodboards v-if="resultTab === 'saved'" /></a-tab-pane>
          <a-tab-pane key="current" tab="当前聚类流程">
            <div class="history-row"><a-select :value="selectedTaskId || undefined" placeholder="选择聚类任务" :options="history.map(item => ({ value: item.id, label: `${dateTime(item.created_at)} · ${statusLabels[item.status]} · ${item.counts?.total_images ?? 0} 张` }))" @change="selectTask(String($event))" /><a v-if="task?.result" :href="clusteringDownloadUrl(task.id)" download>下载结果与追溯</a></div>
            <a-alert v-if="pollError" class="page-alert" type="warning" show-icon :message="pollError" description="正在重试读取任务，已有结果保留。" />
            <a-spin :spinning="taskLoading">
              <template v-if="task"><div class="task-status"><div><a-spin v-if="isActive(task)" size="small" /><strong>{{ statusLabels[task.status] }}</strong><span>{{ stageLabels[task.stage] ?? task.stage }}</span></div><p>{{ task.message }}</p><div><span>已启动 {{ task.progress.calls_started }} / {{ task.progress.max_calls }} 次模型调用</span><span>更新于 {{ dateTime(task.updated_at) }}</span></div><small>调用数是预算消耗，不是完成百分比；后续工作量取决于真实模型输出。</small></div><a-alert v-if="task.error" class="page-alert" type="error" show-icon :message="task.error" /><a-alert v-if="task.status === 'partial'" class="page-alert" type="warning" show-icon message="本次仅部分完成；当前板不代表全量候选均已完成比较。未完成范围见执行摘要。" />
                <template v-if="task.result"><div class="result-summary"><span>{{ task.result.boards.length }} 张正式候选板</span><span>{{ task.result.small_groups.length }} 个未成板小组</span><span>待设计师复核</span></div><article v-for="(board, index) in task.result.boards" :key="board.id" class="result-board"><header><span class="board-index">{{ String(index + 1).padStart(2, '0') }}</span><div><h3>{{ board.title }}</h3><p>{{ board.description }}</p></div><span class="count-badge">{{ board.members.length }} 张</span></header><p class="board-status">状态：{{ board.status === 'model_selected_not_human_approved' ? '模型已选组 · 待人工复核' : board.status }} · 模型选组不等于人工批准</p><div class="board-grid"><button v-for="member in board.members" :key="member.id" type="button" class="board-image" :aria-label="`查看 ${member.image_name} 的原图及依据`" @click="inspectMember(member)"><img v-if="member.preview_url" :src="member.preview_url" :alt="member.image_name" loading="lazy" /><span v-else class="image-placeholder">暂无图片</span><span>{{ member.category || '品类未核' }}</span></button></div><p class="subtle">完整展示冻结视窗，点击查看原图与入选依据。网页不另行裁切或修改 DNA。</p><details v-if="board.constraints"><summary>查看本板约束核验</summary><pre>{{ JSON.stringify(board.constraints, null, 2) }}</pre></details></article><a-empty v-if="!task.result.boards.length" description="本次暂无正式候选板；不降低关系一致性标准或强行凑图。" /><details v-if="task.result.small_groups.length"><summary>查看未成板小组（{{ task.result.small_groups.length }}）</summary><pre>{{ JSON.stringify(task.result.small_groups, null, 2) }}</pre></details><details><summary>执行摘要与覆盖范围</summary><pre>{{ JSON.stringify(task.result.summary, null, 2) }}</pre></details></template>
                <a-empty v-else-if="!isActive(task)" description="本次尚未产生可展示的结果；请查看执行信息。" />
              </template><a-empty v-else-if="!taskLoading" description="先选择高潜趋势方向并核对图片，确认后开始聚类。" />
            </a-spin>
          </a-tab-pane>
          <a-tab-pane key="legacy" tab="旧版结果（只读）"><LegacyMoodboardResults v-if="resultTab === 'legacy'" /></a-tab-pane>
        </a-tabs>
      </section>
    </main>
    <a-modal v-model:open="detailOpen" :title="inspected?.image_name" :footer="null" :width="900"><div v-if="inspected" class="member-detail"><a-image v-if="inspected.original_url || inspected.preview_url" :src="inspected.original_url || inspected.preview_url || undefined" :alt="inspected.image_name" /><p><a-tag>{{ inspected.category || '品类未核' }}</a-tag>{{ inspected.reason || '本成员未附独立文字说明，详见下载的追溯记录。' }}</p><a v-if="inspected.original_url" :href="inspected.original_url" target="_blank" rel="noopener noreferrer">打开原图</a><p class="subtle">对象 / 图片 ID：{{ inspected.id }}</p></div></a-modal>
    <footer><span>用户审美洞察与趋势捕捉 · AI 审美洞察平台</span><span>趋势图片 → DNA 准备 → 设计关系聚类 → 人工反馈</span></footer>
  </div>
</template>

<style scoped>
.moodboard-hero { padding: 42px 0 30px; }
.moodboard-hero h1 { margin: 14px 0; font-size: 32px; }
.moodboard-hero p { max-width: 790px; }
.rule-chips, .result-summary { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 20px; }
.rule-chips span, .result-summary span { padding: 7px 12px; color: #776388; background: #f0eaf7; border-radius: 24px; font-size: 12px; }
.input-panel, .results-panel { margin-bottom: 24px; }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-bottom: 20px; }
.panel-heading h2 { margin: 8px 0; color: #5b496d; font-size: 20px; }
.panel-heading p, .subtle, .preview-action > span, .direction-toolbar > span, .execution-settings > p { color: #8a8197; font-size: 12px; line-height: 1.8; }
.panel-heading p { margin: 0; }
.field-label, .settings-grid label { display: block; margin-bottom: 8px; color: #645773; font-size: 12px; }
.source-select { width: 100%; min-width: 0; }
.source-select :deep(.ant-select-selection-item) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.direction-toolbar, .preview-toolbar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0 14px; }
.direction-grid { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.direction-option { min-width: 0; padding: 16px; border: 1px solid #ece8f2; border-radius: 12px; background: #faf9fc; overflow-wrap: anywhere; }
.direction-option.selected { background: #f5f1fc; border-color: #b3a0d9; }
.direction-option p { margin: 10px 0 5px; color: #83758e; font-size: 12px; line-height: 1.8; white-space: normal; overflow-wrap: anywhere; }
.direction-option small { color: #9d91a7; font-size: 11px; }
.preview-action { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; margin-top: 22px; }
.page-alert { margin: 16px 0; }
.metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.metrics > div { display: flex; flex-direction: column; gap: 6px; padding: 18px; border-radius: 12px; background: #f7f4fb; }
.metrics strong { font-size: 25px; color: #715a91; font-weight: 600; }
.metrics span, .preview-toolbar > span { color: #8d7e9b; font-size: 12px; }
.preview-toolbar .ant-select { width: 160px; }
.preview-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.preview-card { min-width: 0; padding: 8px; border: 1px solid #ece7f2; border-radius: 12px; }
.preview-card :deep(.ant-image-img) { height: 150px; object-fit: contain; background: #faf9fc; }
.preview-card strong { display: block; margin: 9px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: #665574; }
.preview-card p { margin: 6px 0; color: #92869d; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.image-placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 150px; background: #faf9fc; color: #a59aaf; font-size: 12px; }
.execution-settings { border-top: 1px solid #ece7f2; margin-top: 24px; padding-top: 24px; }
.settings-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 22px; margin-top: 22px; }
.settings-grid .ant-select, .settings-grid .ant-input-number { width: 100%; }
.settings-grid small { display: block; margin-top: 6px; color: #9b8fa7; font-size: 11px; }
.start-row { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-top: 22px; }
.start-row p { color: #705c85; line-height: 1.8; font-size: 13px; }
.start-row small { color: #95879e; font-size: 11px; }
.execution-settings .warning-copy { color: #ad743c; }
.history-row { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin: 12px 0 22px; }
.history-row .ant-select { flex: 1; min-width: 220px; }
.task-status { padding: 20px; background: #f7f4fb; border-radius: 12px; color: #715e86; }
.task-status > div { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
.task-status p { line-height: 1.8; font-size: 13px; }
.task-status span, .task-status small { font-size: 12px; color: #8a7a99; }
.task-status small { display: block; margin-top: 10px; }
.result-board { padding: 22px; margin-top: 22px; border: 1px solid #e9e2f0; border-radius: 18px; background: #fcfbfd; }
.result-board header { display: flex; align-items: flex-start; gap: 16px; }
.result-board header > div { flex: 1; }
.board-index { font-size: 26px; color: #ad9cbe; }
.result-board h3 { margin: 0; color: #5a476c; font-size: 21px; }
.result-board header p { margin: 8px 0 0; color: #8a7c97; line-height: 1.8; font-size: 13px; }
.board-status { margin-top: 16px; color: #9a8da5; font-size: 11px; }
.board-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 10px; background: #fff; }
.board-image { min-width: 0; padding: 0; border: 1px solid transparent; background: #fff; cursor: pointer; }
.board-image:hover, .board-image:focus-visible { border-color: #ac94c5; }
.board-image img { width: 100%; height: 240px; object-fit: contain; }
.board-image > span:not(.image-placeholder) { display: block; margin: 6px; color: #9988a6; font-size: 11px; }
details { margin-top: 18px; }
summary { color: #83718f; font-size: 12px; cursor: pointer; }
pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: #f4f0f8; color: #766482; font-size: 12px; }
.member-detail :deep(.ant-image) { width: 100%; text-align: center; }
.member-detail :deep(.ant-image-img) { max-height: 65vh; object-fit: contain; }
.member-detail p { color: #82738f; font-size: 13px; line-height: 1.8; }
@media (max-width: 1100px) { .preview-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } .direction-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .moodboard-hero h1 { font-size: 26px; } .panel-heading { align-items: flex-start; flex-wrap: wrap; } .direction-grid, .settings-grid { grid-template-columns: 1fr; } .preview-grid, .board-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .metrics { grid-template-columns: repeat(3, 1fr); gap: 8px; } .metrics > div { padding: 12px; } .metrics strong { font-size: 21px; } .start-row { flex-direction: column; align-items: stretch; } .result-board { padding: 12px; } .board-grid { gap: 5px; padding: 4px; } .board-image img { height: 180px; } .result-board h3 { font-size: 18px; } }
</style>
