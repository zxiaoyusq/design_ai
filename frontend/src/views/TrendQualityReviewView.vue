<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined, DownloadOutlined, PictureOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { downloadTrendQualityReview, fetchTrendQualityReview, saveTrendQualityReview } from '@/api/trendQualityReview'
import type { TrendQualityCategory, TrendQualityDecision, TrendQualityImage, TrendQualityManualFilter, TrendQualityReview } from '@/types/trendQualityReview'

const review = ref<TrendQualityReview | null>(null)
const modelFilter = ref<'all' | TrendQualityCategory>('all')
const manualFilter = ref<TrendQualityManualFilter>('all')
const directionId = ref('')
const searchInput = ref('')
const query = ref('')
const page = ref(1)
const pageSize = 60
const density = ref<'compact' | 'large'>('compact')
const gallery = ref<HTMLElement | null>(null)
const loading = ref(false)
const saving = ref(false)
const stale = ref(true)
const exporting = ref<TrendQualityDecision | 'all' | null>(null)
const error = ref('')
const saveState = ref<'ready' | 'saved' | 'failed'>('ready')
const selectedIds = ref<string[]>([])
const previewImages = ref<TrendQualityImage[]>([])
const previewIndex = ref(0)
let loadVersion = 0
let disposed = false
let searchTimer: ReturnType<typeof setTimeout> | undefined

const locked = computed(() => loading.value || saving.value)
const cannotSave = computed(() => locked.value || stale.value)
const images = computed(() => review.value?.images ?? [])
const selectedImages = computed(() => images.value.filter(image => selectedIds.value.includes(image.id)))
const allSelected = computed(() => images.value.length > 0 && selectedIds.value.length === images.value.length)
const pageCount = computed(() => Math.max(1, Math.ceil((review.value?.filtered_count ?? 0) / pageSize)))
const preview = computed(() => previewImages.value[previewIndex.value] ?? null)
const categoryLabels: Record<TrendQualityCategory, string> = { PASS: '模型通过', FAIL: '模型不通过', REVIEW: '待复核', ERROR: '执行异常' }
const modelOptions = computed(() => [
  { value: 'all' as const, label: '全部', count: review.value?.counts.total ?? 0 },
  ...(['PASS', 'FAIL', 'REVIEW', 'ERROR'] as const).map(value => ({ value, label: categoryLabels[value], count: review.value?.counts.model[value] ?? 0 })),
])
const manualOptions = computed(() => [
  { value: 'all', label: '全部人工状态' },
  { value: 'unreviewed', label: `未审核 · ${review.value?.counts.manual.unreviewed ?? 0}` },
  { value: 'PASS', label: `人工通过 · ${review.value?.counts.manual.PASS ?? 0}` },
  { value: 'FAIL', label: `人工不通过 · ${review.value?.counts.manual.FAIL ?? 0}` },
])
const directionOptions = computed(() => [
  { value: '', label: '全部握手方向' },
  ...(review.value?.directions ?? []).map(item => ({ value: item.id, label: `${item.id} · ${item.title} (${item.count})` })),
])

function readError(cause: unknown, fallback: string) {
  const detail = (cause as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : cause instanceof Error ? cause.message : fallback
}
function imageLabel(image: TrendQualityImage) { return image.image_id || image.image_ids[0] || image.id.slice(0, 12) }
function manualLabel(decision: TrendQualityDecision | null) { return decision === 'PASS' ? '人工通过' : decision === 'FAIL' ? '人工不通过' : '人工未审核' }
function dateTime(value: string | null) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
/** 文章来源仅接受普通网页协议，避免来源数据触发非网页脚本。 */
function articleUrl(value: string | null) {
  if (!value) return undefined
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined }
  catch { return undefined }
}
function toggleSelection(id: string, checked: boolean) {
  selectedIds.value = checked ? [...new Set([...selectedIds.value, id])] : selectedIds.value.filter(value => value !== id)
}
function selectPage(checked: boolean) { selectedIds.value = checked ? images.value.map(image => image.id) : [] }
function openPreview(image: TrendQualityImage) {
  previewImages.value = [...images.value]
  previewIndex.value = previewImages.value.findIndex(item => item.id === image.id)
}
function closePreview() { previewImages.value = []; previewIndex.value = 0 }
function changePage(next: number) {
  page.value = next
  gallery.value?.scrollIntoView({ block: 'start' })
}

/** 忽略过期响应；读取失败时阻止基于旧版本再次写入，直到刷新成功。 */
async function load(preservePreview = false) {
  const version = ++loadVersion
  loading.value = true
  stale.value = true
  selectedIds.value = []
  if (!preservePreview) closePreview()
  try {
    const next = await fetchTrendQualityReview({ model_category: modelFilter.value, manual: manualFilter.value, direction_id: directionId.value, q: query.value, page: page.value, page_size: pageSize })
    if (disposed || version !== loadVersion) return false
    review.value = next
    stale.value = false
    // 未审核筛选下保存后图片会离开列表，预览仍保留本页顺序供继续看图。
    if (preservePreview) previewImages.value = previewImages.value.map(item => next.images.find(image => image.id === item.id) ?? item)
    const lastPage = Math.max(1, Math.ceil(next.filtered_count / pageSize))
    if (page.value > lastPage) page.value = lastPage
    return true
  } catch (cause) {
    if (!disposed && version === loadVersion) error.value = readError(cause, '图库读取失败，请刷新后继续。')
    return false
  } finally {
    if (!disposed && version === loadVersion) loading.value = false
  }
}

/** 服务器确认后才改变标签；版本冲突仅刷新，不重放或覆盖本次选择。 */
async function saveSelection(targets: TrendQualityImage[], decision: TrendQualityDecision | null) {
  if (!review.value || cannotSave.value) return
  const ids = [...new Set(targets.filter(image => image.manual_decision !== decision).map(image => image.id))]
  if (!ids.length) return
  saving.value = true
  error.value = ''
  try {
    const result = await saveTrendQualityReview(review.value.revision, ids, decision)
    if (disposed) return
    const changed = new Map(result.changed.map(item => [item.id, item]))
    previewImages.value = previewImages.value.map(item => ({ ...item, ...changed.get(item.id) }))
    review.value = { ...review.value, revision: result.revision, updated_at: result.updated_at, counts: result.counts, images: images.value.map(item => ({ ...item, ...changed.get(item.id) })) }
    saveState.value = 'saved'
    if (await load(true)) message.success(`已保存 ${ids.length} 张图片的人工选择`)
    else error.value = '人工选择已保存到服务器，但最新列表读取失败。请刷新后继续。'
  } catch (cause) {
    if (disposed) return
    saveState.value = 'failed'
    if ((cause as { response?: { status?: number } })?.response?.status === 409) {
      const refreshed = await load()
      error.value = refreshed ? '其他页面更新了选择，本次操作未保存。已刷新最新状态，请重新选择。' : '其他页面更新了选择，本次操作未保存；最新状态读取失败，请刷新后继续。'
    } else error.value = `人工选择未保存：${readError(cause, '请重试。')}`
  } finally { if (!disposed) saving.value = false }
}

async function refresh() {
  if (locked.value) return
  error.value = ''
  saveState.value = 'ready'
  await load()
}
async function download(selection: TrendQualityDecision | 'all') {
  if (!review.value || locked.value || exporting.value) return
  exporting.value = selection
  try {
    const blob = await downloadTrendQualityReview(selection)
    if (disposed) return
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${review.value.collection_id}_manual_${selection}.json`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
    message.success('服务器保存的人工选择清单已开始下载')
  } catch (cause) {
    const data = (cause as { response?: { data?: unknown } })?.response?.data
    if (data instanceof Blob) {
      try { error.value = JSON.parse(await data.text()).detail || '清单导出失败，请重试。' }
      catch { error.value = '清单导出失败，请重试。' }
    } else error.value = readError(cause, '清单导出失败，请重试。')
  } finally { exporting.value = null }
}

watch(searchInput, value => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { query.value = value.trim() }, 300)
})
watch([modelFilter, manualFilter, directionId, query], () => { page.value = 1 })
watch([modelFilter, manualFilter, directionId, query, page], () => { error.value = ''; void load() }, { immediate: true })
onUnmounted(() => { disposed = true; loadVersion++; clearTimeout(searchTimer) })
</script>

<template>
  <div class="quality-page">
    <header class="quality-header">
      <RouterLink class="back-link" to="/"><ArrowLeftOutlined /> 工作台</RouterLink>
      <h1>趋势图片筛选</h1>
      <span class="save-state" :class="{ failed: saveState === 'failed' || stale, busy: saving }" aria-live="polite">{{ saving ? '正在保存…' : saveState === 'failed' ? '本次选择未保存' : stale ? '等待读取最新状态' : saveState === 'saved' ? '人工选择已保存到服务器' : '已读取服务器记录' }}</span>
    </header>
    <main class="quality-main">
      <div class="collection-summary">
        <span v-if="review">{{ review.title }} · 共 <b>{{ review.counts.total.toLocaleString() }}</b> 张</span>
        <span v-if="review" class="passed">人工通过 <b>{{ review.counts.manual.PASS.toLocaleString() }}</b></span>
        <span v-if="review">人工不通过 {{ review.counts.manual.FAIL.toLocaleString() }}</span>
        <span v-if="review">未审核 {{ review.counts.manual.unreviewed.toLocaleString() }}</span>
        <a-button size="small" :disabled="locked" @click="refresh"><ReloadOutlined /> 刷新</a-button>
      </div>
      <a-alert v-if="error" class="quality-alert" type="error" show-icon :message="error" />
      <section class="quality-toolbar" aria-label="筛选和批量审核">
        <div class="model-tabs" aria-label="模型结果分类">
          <button v-for="option in modelOptions" :key="option.value" :class="{ active: modelFilter === option.value }" :disabled="saving" @click="modelFilter = option.value">{{ option.label }} <span>{{ option.count.toLocaleString() }}</span></button>
        </div>
        <div class="filter-row">
          <a-select v-model:value="manualFilter" class="manual-filter" size="small" :options="manualOptions" :disabled="saving" aria-label="人工审核状态" />
          <a-select v-model:value="directionId" class="direction-filter" size="small" :options="directionOptions" :disabled="saving" show-search option-filter-prop="label" aria-label="握手方向" />
          <a-input v-model:value="searchInput" class="search-input" size="small" placeholder="搜索文章标题 / 图号" allow-clear :disabled="saving" aria-label="搜索文章标题或图号"><template #prefix><SearchOutlined /></template></a-input>
          <a-segmented v-model:value="density" size="small" :options="[{ value: 'compact', label: '小图' }, { value: 'large', label: '大图' }]" aria-label="图片密度" />
        </div>
        <div class="bulk-row">
          <a-checkbox :checked="allSelected" :indeterminate="selectedIds.length > 0 && !allSelected" :disabled="cannotSave || !images.length" @change="selectPage($event.target.checked)">选中本页</a-checkbox>
          <span>已选 {{ selectedIds.length }} 张</span>
          <a-button size="small" :disabled="cannotSave || !selectedIds.length" @click="saveSelection(selectedImages, 'PASS')">批量通过</a-button>
          <a-button size="small" danger :disabled="cannotSave || !selectedIds.length" @click="saveSelection(selectedImages, 'FAIL')">批量不通过</a-button>
          <details class="download-controls"><summary><DownloadOutlined /> 导出清单</summary><div class="download-menu"><p>导出服务器已保存的人工选择。</p><a-button size="small" :disabled="locked || !review || !!exporting" :loading="exporting === 'PASS'" @click="download('PASS')">人工通过</a-button><a-button size="small" :disabled="locked || !review || !!exporting" :loading="exporting === 'FAIL'" @click="download('FAIL')">人工不通过</a-button><a-button size="small" :disabled="locked || !review || !!exporting" :loading="exporting === 'all'" @click="download('all')">全部记录</a-button></div></details>
        </div>
        <p class="review-note">模型结果供筛选参考；人工选择从未审核开始，点击通过或不通过后保存。</p>
      </section>
      <section ref="gallery" class="gallery-section" :aria-busy="loading">
        <div class="page-navigation"><span>{{ loading ? '正在读取…' : `符合筛选 ${review?.filtered_count.toLocaleString() ?? 0} 张` }} · 每页 {{ pageSize }} 张</span><a-pagination :current="page" :total="review?.filtered_count ?? 0" :page-size="pageSize" :disabled="locked" simple :show-size-changer="false" size="small" @change="changePage" /></div>
        <a-spin :spinning="loading">
          <div v-if="images.length" class="quality-image-grid" :class="density">
            <article v-for="image in images" :key="image.id" class="image-card" :class="{ selected: selectedIds.includes(image.id) }">
              <button class="image-preview" :aria-label="`查看 ${imageLabel(image)} 大图与来源`" @click="openPreview(image)"><img :src="image.thumbnail_url || image.image_url" :alt="imageLabel(image)" loading="lazy" decoding="async" /><span class="model-label" :class="image.model_category.toLowerCase()">{{ categoryLabels[image.model_category] }}</span></button>
              <div class="image-info"><a-checkbox :checked="selectedIds.includes(image.id)" :disabled="cannotSave" :aria-label="`选中 ${imageLabel(image)}`" @change="toggleSelection(image.id, $event.target.checked)" /><button class="image-name" :title="image.image_ids.join('、')" @click="openPreview(image)">{{ imageLabel(image) }}</button><span class="manual-label" :class="image.manual_decision?.toLowerCase()">{{ manualLabel(image.manual_decision) }}</span></div>
              <div class="image-actions"><button :class="{ chosen: image.manual_decision === 'PASS' }" class="pass-button" :disabled="cannotSave" @click="saveSelection([image], 'PASS')">通过</button><button :class="{ chosen: image.manual_decision === 'FAIL' }" class="fail-button" :disabled="cannotSave" @click="saveSelection([image], 'FAIL')">不通过</button><button class="reset-button" :disabled="cannotSave || image.manual_decision === null" @click="saveSelection([image], null)">恢复未审核</button></div>
            </article>
          </div>
          <div v-else class="empty-panel"><PictureOutlined /><p>{{ loading ? '正在读取趋势图片…' : '没有符合当前筛选的图片。' }}</p><a-button v-if="!review && !loading" @click="refresh">重新读取</a-button></div>
        </a-spin>
        <div v-if="images.length" class="page-navigation bottom"><span>第 {{ page }} / {{ pageCount }} 页</span><a-pagination :current="page" :total="review?.filtered_count ?? 0" :page-size="pageSize" :disabled="locked" simple :show-size-changer="false" size="small" @change="changePage" /></div>
      </section>
    </main>
    <a-modal :open="Boolean(preview)" :title="preview ? imageLabel(preview) : ''" :width="1080" :footer="null" centered @cancel="closePreview">
      <div v-if="preview" class="preview-layout">
        <div class="preview-image-panel">
          <img :src="preview.image_url" :alt="imageLabel(preview)" />
          <div class="preview-tags"><span class="model-label" :class="preview.model_category.toLowerCase()">{{ categoryLabels[preview.model_category] }}</span><span class="manual-label" :class="preview.manual_decision?.toLowerCase()">{{ manualLabel(preview.manual_decision) }}</span></div>
          <div class="preview-actions"><a-button :type="preview.manual_decision === 'PASS' ? 'primary' : 'default'" :disabled="cannotSave" @click="saveSelection([preview], 'PASS')">人工通过</a-button><a-button danger :type="preview.manual_decision === 'FAIL' ? 'primary' : 'default'" :disabled="cannotSave" @click="saveSelection([preview], 'FAIL')">人工不通过</a-button><a-button :disabled="cannotSave || preview.manual_decision === null" @click="saveSelection([preview], null)">恢复未审核</a-button></div>
          <div class="preview-navigation"><a-button size="small" :disabled="locked || previewIndex === 0" @click="previewIndex--">上一张</a-button><span>本页 {{ previewIndex + 1 }} / {{ previewImages.length }}</span><a-button size="small" :disabled="locked || previewIndex >= previewImages.length - 1" @click="previewIndex++">下一张</a-button><a :href="preview.image_url" target="_blank" rel="noopener noreferrer">打开原图</a></div>
          <p v-if="preview.width && preview.height" class="dimension">{{ preview.width }} × {{ preview.height }}</p>
          <a-alert v-if="error" type="error" show-icon :message="error" />
        </div>
        <div class="preview-info">
          <h3>关联握手方向</h3><div class="direction-tags"><span v-for="item in preview.directions" :key="item.id">{{ item.id }} · {{ item.title }}</span><span v-if="!preview.directions.length">未提供方向</span></div>
          <h3>文章来源</h3><ul class="articles"><li v-for="article in preview.articles" :key="article.id"><a v-if="articleUrl(article.url)" :href="articleUrl(article.url)" target="_blank" rel="noopener noreferrer">{{ article.title || article.id }} ↗</a><span v-else>{{ article.title || article.id }}</span></li><li v-if="!preview.articles.length">{{ preview.article_title || '未提供来源' }}</li></ul>
          <a-alert v-if="preview.model_error" type="warning" show-icon :message="preview.model_error" />
          <details class="trace-info"><summary>审核与模型记录</summary><dl><dt>人工更新时间</dt><dd>{{ dateTime(preview.manual_updated_at) }}</dd><dt>全部图号</dt><dd>{{ preview.image_ids.join('、') || imageLabel(preview) }}</dd><dt>模型</dt><dd>{{ preview.model || '未提供' }}</dd><dt>模型执行状态</dt><dd>{{ preview.model_status }}</dd><dt>模型原始判定</dt><dd>{{ preview.model_decision || '无判定' }}</dd><dt>Prompt 版本</dt><dd>{{ preview.prompt_version || '未提供' }}</dd><dt>Prompt 指纹</dt><dd>{{ preview.prompt_sha256 || '未提供' }}</dd><dt>执行时间</dt><dd>{{ dateTime(preview.model_finished_at) }}</dd><dt>批次</dt><dd>{{ preview.batch }}</dd><dt>原始图片路径</dt><dd>{{ preview.source_path }}</dd><dt>图片指纹</dt><dd>{{ preview.id }}</dd></dl></details>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.quality-page { min-height: 100vh; background: #f7f6fa; color: #443a51; }
.quality-header { display: flex; align-items: center; gap: 20px; min-height: 48px; padding: 8px 18px; border-bottom: 1px solid #e7e1ed; background: #fff; }
.back-link { display: flex; align-items: center; gap: 7px; color: #79628f; font-size: 12px; }
h1 { margin: 0; font-size: 17px; font-weight: 600; }
.save-state { margin-left: auto; color: #64815f; font-size: 11px; }
.save-state.busy { color: #9275aa; }
.save-state.failed { color: #ac7373; }
.quality-main { padding: 12px 18px 16px; }
.collection-summary { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; font-size: 11px; color: #8f7c9a; margin-bottom: 10px; }
.collection-summary b { color: #655072; font-size: 13px; }
.collection-summary .passed, .collection-summary .passed b { color: #64836a; }
.collection-summary > :last-child { margin-left: auto; }
.quality-alert { margin-bottom: 10px; }
.quality-toolbar { padding: 10px 12px; border: 1px solid #e5dced; border-radius: 9px; background: #fff; }
.model-tabs, .filter-row, .bulk-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.model-tabs { margin-bottom: 10px; gap: 4px; }
.model-tabs button { border: 0; border-radius: 5px; padding: 6px 10px; background: transparent; color: #907a9e; cursor: pointer; font-size: 12px; }
.model-tabs button.active { background: #eee5f6; color: #694480; font-weight: 600; }
.model-tabs button span { margin-left: 4px; font-size: 11px; font-weight: 400; }
.manual-filter { width: 180px; }
.direction-filter { width: min(340px, 100%); }
.search-input { min-width: 160px; flex: 1; max-width: 480px; }
.bulk-row { margin-top: 10px; font-size: 11px; color: #92809e; }
.bulk-row :deep(.ant-checkbox-wrapper) { font-size: 11px; }
.review-note { margin: 8px 0 0; font-size: 11px; color: #a08dac; }
.download-controls { margin-left: auto; position: relative; }
summary { cursor: pointer; }
.download-menu { position: absolute; right: 0; top: 22px; z-index: 5; width: 300px; padding: 12px; border: 1px solid #e8dfef; border-radius: 8px; background: #fff; box-shadow: 0 4px 24px #3e294526; }
.download-menu p { margin: 0 0 10px; }
.download-menu :deep(.ant-btn + .ant-btn) { margin-left: 6px; }
.gallery-section { scroll-margin-top: 8px; }
.page-navigation { display: flex; justify-content: space-between; align-items: center; min-height: 42px; gap: 10px; color: #92809e; font-size: 11px; }
.page-navigation.bottom { margin-top: 8px; }
/* 独立图库类避免全局限高，全部图片通过页面自然滚动展示。 */
.quality-image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(185px, 1fr)); gap: 10px; }
.quality-image-grid.large { grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); }
.image-card { min-width: 0; border: 1px solid #e6dfee; border-radius: 8px; overflow: hidden; background: #fff; }
.image-card:hover { border-color: #bba5ce; }
.image-card.selected { border-color: #9373b0; box-shadow: 0 0 0 1px #9373b0; }
.image-preview { position: relative; display: block; width: 100%; aspect-ratio: 1; padding: 5px; border: none; background: #f0edf3; cursor: zoom-in; }
.image-preview > img { display: block; width: 100%; height: 100%; object-fit: contain; }
.model-label { display: inline-block; padding: 3px 5px; border-radius: 4px; background: #eeebf5ee; color: #79638c; font-size: 10px; }
.image-preview .model-label { position: absolute; top: 6px; left: 6px; }
.model-label.pass { color: #52705b; background: #eff6efee; }
.model-label.fail { color: #91626d; background: #faf0f2ee; }
.model-label.error { color: #9d7b43; background: #fff6e7ee; }
.image-info { display: flex; align-items: center; gap: 5px; padding: 6px; }
.image-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: #766180; background: none; padding: 0; border: 0; cursor: pointer; text-align: left; }
.manual-label { font-size: 10px; white-space: nowrap; color: #9889a1; }
.manual-label.pass { color: #54815e; }
.manual-label.fail { color: #a06876; }
.image-actions { display: flex; gap: 4px; padding: 0 6px 7px; }
.image-actions button { flex: 1; padding: 4px 3px; border-radius: 4px; font-size: 10px; white-space: nowrap; cursor: pointer; border: 1px solid #e8e1ee; background: #faf8fc; color: #8a769a; }
.image-actions .pass-button { color: #5f7e65; border-color: #dbe7d9; background: #f3f8f2; }
.image-actions .fail-button { color: #a1727b; border-color: #eedfe4; background: #fcf5f6; }
.image-actions .pass-button.chosen { background: #dfeedd; border-color: #91b98c; }
.image-actions .fail-button.chosen { background: #f1dfe3; border-color: #c49aa5; }
button:disabled { opacity: .55; cursor: default; }
.empty-panel { padding: 55px 20px; text-align: center; color: #a797b1; font-size: 12px; border: 1px dashed #ddd2e6; border-radius: 9px; }
.preview-layout { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 24px; }
.preview-image-panel { text-align: center; }
.preview-image-panel > img { display: block; width: 100%; height: min(55vh, 520px); object-fit: contain; background: #f7f5f9; border-radius: 10px; margin: 8px 0 12px; }
.preview-tags, .preview-actions, .preview-navigation { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.preview-navigation, .dimension { font-size: 11px; color: #9a87a6; }
.preview-info { max-height: 70vh; overflow-y: auto; padding-right: 6px; color: #877191; }
.preview-info h3 { font-size: 13px; color: #695174; margin: 12px 0; }
.direction-tags { display: flex; flex-wrap: wrap; gap: 7px; }
.direction-tags span { font-size: 10px; line-height: 1.7; padding: 4px 8px; border-radius: 6px; background: #f3edf8; color: #9676aa; }
.articles { padding-left: 18px; font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.articles li { margin-bottom: 9px; }
.articles a { color: #82649b; }
.trace-info { margin-top: 20px; font-size: 11px; color: #a390b0; }
dt { color: #a69aac; font-size: 10px; margin-top: 9px; }
dd { margin: 3px 0 0; line-height: 1.7; font-size: 11px; overflow-wrap: anywhere; }
@media (max-width: 800px) { .preview-layout { grid-template-columns: 1fr; } .preview-info { max-height: none; } .preview-image-panel > img { height: 38vh; } }
@media (max-width: 620px) {
  .quality-header { padding: 8px 10px; gap: 12px; flex-wrap: wrap; }
  .save-state { font-size: 10px; }
  .quality-main { padding: 10px; }
  .collection-summary { gap: 9px; font-size: 10px; }
  .quality-toolbar { padding: 8px; }
  .model-tabs button { padding: 5px 7px; font-size: 11px; }
  .manual-filter { width: 150px; }
  .direction-filter { flex: 1; width: 160px; }
  .search-input { min-width: 170px; }
  .bulk-row { gap: 6px; }
  .download-menu { width: min(300px, calc(100vw - 40px)); }
  .page-navigation { gap: 4px; font-size: 10px; }
  .quality-image-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .quality-image-grid.large { grid-template-columns: 1fr; }
}
</style>
