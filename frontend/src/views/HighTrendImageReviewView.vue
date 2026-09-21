<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { useRoute } from 'vue-router'
import { ArrowLeftOutlined, CheckOutlined, DownloadOutlined, PictureOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { downloadImageReview, fetchImageReview, openImageReview, saveImageReview } from '@/api/highTrendImageReview'
import type { HighTrendImageReview, ReviewImage, ReviewImageSource, ReviewCollection } from '@/types/highTrendImageReview'

const route = useRoute()
const collection = computed<ReviewCollection>(() => route.query.collection === 'remaining' ? 'remaining' : 'result')
const isRemaining = computed(() => collection.value === 'remaining')
const sourceKind = ref<ReviewImageSource>('trend')
const density = ref<'compact' | 'large'>('compact')
const page = ref(1)
const pageSize = 60
const gallery = ref<HTMLElement | null>(null)
const taskId = computed(() => typeof route.query.task === 'string' ? route.query.task : '')
const review = ref<HighTrendImageReview | null>(null)
const loading = ref(false)
const saving = ref(false)
const exporting = ref<'zip' | 'json' | null>(null)
const error = ref('')
const filter = ref<'all' | 'retained' | 'excluded'>('all')
const query = ref('')
const directionId = ref('')
const previewId = ref<string | null>(null)
let loadVersion = 0
let disposed = false

const filterOptions = computed(() => [{ value: 'all', label: '全部' }, { value: 'retained', label: '已保留' }, { value: 'excluded', label: isRemaining.value ? '未保留' : '已排除' }])
const directions = computed(() => {
  const entries = new Map<string, string>()
  for (const image of review.value?.images ?? []) for (const item of image.directions) entries.set(item.id, item.title)
  return [{ value: '', label: '全部设计方向' }, ...Array.from(entries, ([value, label]) => ({ value, label }))]
})
const visibleImages = computed(() => {
  const words = query.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return (review.value?.images ?? []).filter(image => {
    if (!image.source_kinds.includes(sourceKind.value)) return false
    if (filter.value !== 'all' && image.retained !== (filter.value === 'retained')) return false
    if (directionId.value && !image.directions.some(item => item.id === directionId.value)) return false
    if (!words.length) return true
    const text = [image.file_name, ...image.image_ids, ...image.directions.map(item => `${item.id} ${item.title}`), ...image.origins.map(origin => `${origin.code ?? ''} ${origin.user_id ?? ''} ${origin.source_title ?? ''} ${origin.source_record_id ?? ''} ${origin.source_aliases.join(' ')}`)].join(' ').toLocaleLowerCase()
    return words.every(word => text.includes(word))
  })
})
const pageImages = computed(() => visibleImages.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pageRetained = computed(() => pageImages.value.filter(image => image.retained).length)
const pageCount = computed(() => Math.max(1, Math.ceil(visibleImages.value.length / pageSize)))
const preview = computed(() => review.value?.images.find(image => image.id === previewId.value) ?? null)
const sharedCount = computed(() => review.value?.images.filter(image => image.source_kinds.length > 1).length ?? 0)
const locked = computed(() => loading.value || saving.value)

function readError(value: unknown, fallback: string) {
  const detail = (value as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : value instanceof Error ? value.message : fallback
}
function imageLabel(image: ReviewImage) {
  return image.origins.find(origin => origin.code)?.code || image.image_ids[0] || image.file_name
}
/** 同一文件可能来自多个反馈，保留所有原始态度，不以某一个标签覆盖其余来源。 */
function emotionLabel(image: ReviewImage) {
  const labels = new Set(image.origins.filter(origin => origin.source_kind === 'user').flatMap(origin => (origin.emotion_tag?.toUpperCase().split(/\s*\/\s*/) || ['']).map(tag => {
    if (tag === 'LIKE' || tag === 'ENJOY') return '喜欢'
    if (tag === 'DISLIKE') return '不喜欢'
    if (tag === 'REFERENCE') return '参考'
    return tag || '未标注'
  })))
  return [...labels].join(' / ') || '未标注'
}
function notRetainedLabel() { return isRemaining.value ? '未保留' : '已排除' }
function changePage(next: number) {
  page.value = next
  gallery.value?.scrollIntoView({ block: 'start' })
}
function byteSize(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
}
function dateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
/** 图片只走当前任务分配的副本接口，避免把来源 URL 当作可信的展示地址。 */
function imageUrl(image: ReviewImage, thumbnail = false) {
  const url = image.image_url || `/api/v1/high-trends/tasks/${encodeURIComponent(taskId.value)}/image-review/images/${encodeURIComponent(image.id)}?collection=${collection.value}`
  return thumbnail ? `${url}${url.includes('?') ? '&' : '?'}thumbnail=true` : url
}

async function load() {
  const version = ++loadVersion
  const id = taskId.value
  const activeCollection = collection.value
  review.value = null
  previewId.value = null
  error.value = ''
  if (!id) { loading.value = false; error.value = '请从一份高潜趋势结果进入图片整理。'; return }
  loading.value = true
  try {
    const next = await openImageReview(id, activeCollection)
    if ((next.collection || 'result') !== activeCollection) throw new Error('图库服务尚未更新，请稍后刷新；未改动任何选择。')
    if (!disposed && version === loadVersion) review.value = next
  } catch (cause) {
    if (version === loadVersion) error.value = readError(cause, '图片整理档案读取失败，请重试。')
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

/** 先保存再更新卡片；版本冲突只刷新并提示，不擅自覆盖其他窗口的选择。 */
async function saveSelection(images: ReviewImage[], retained: boolean) {
  if (!review.value || locked.value) return
  const ids = [...new Set(images.filter(image => image.retained !== retained).map(image => image.id))]
  if (!ids.length) return
  const version = loadVersion
  const id = taskId.value
  const activeCollection = collection.value
  saving.value = true
  error.value = ''
  try {
    const updated = await saveImageReview(id, review.value.revision, ids, retained, activeCollection)
    if (!disposed && version === loadVersion) review.value = updated
  } catch (cause) {
    if (disposed || version !== loadVersion) return
    if ((cause as { response?: { status?: number } })?.response?.status === 409) {
      error.value = '其他页面更新了图片选择，本次操作未覆盖。已读取最新状态，请重新选择。'
      try {
        const latest = await fetchImageReview(id, activeCollection)
        if (!disposed && version === loadVersion) review.value = latest
      } catch (refreshCause) {
        if (!disposed && version === loadVersion) error.value = readError(refreshCause, '最新状态读取失败，请刷新后继续。')
      }
    } else error.value = readError(cause, '保存失败，选择尚未更改，请重试。')
  } finally {
    saving.value = false
  }
}

function bulkSelection(retained: boolean) {
  const images = pageImages.value.filter(image => image.retained !== retained)
  if (!images.length || locked.value) return
  if (retained) { void saveSelection(images, true); return }
  const version = loadVersion
  Modal.confirm({
    title: `取消保留本页的 ${images.length} 张图片？`,
    content: '这些图片将移出保留集，之后可以恢复。原始图片和整理副本都会保留。',
    okText: '取消保留', cancelText: '取消', centered: true,
    onOk: () => !disposed && version === loadVersion ? saveSelection(images, false) : undefined,
  })
}

async function download(format: 'zip' | 'json') {
  if (!review.value || locked.value || exporting.value) return
  const id = taskId.value
  const activeCollection = collection.value
  exporting.value = format
  try {
    const blob = await downloadImageReview(id, format, activeCollection)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${id}_${activeCollection}_retained.${format}`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
    message.success(format === 'zip' ? '保留图片与来源清单已开始下载' : '保留图片清单已开始下载')
  } catch (cause) {
    const data = (cause as { response?: { data?: unknown } })?.response?.data
    if (data instanceof Blob) {
      try { error.value = JSON.parse(await data.text()).detail || '导出失败，请重试。' }
      catch { error.value = '导出失败，请重试。' }
    } else error.value = readError(cause, '导出失败，请重试。')
  } finally { exporting.value = null }
}

watch([taskId, collection], () => { query.value = ''; directionId.value = ''; filter.value = 'all'; page.value = 1; void load() }, { immediate: true })
watch([query, directionId, filter, sourceKind], () => { page.value = 1 })
watch(pageCount, count => { if (page.value > count) page.value = count })
onUnmounted(() => { disposed = true; loadVersion++ })
</script>

<template>
  <div class="review-page">
    <header class="review-header">
      <RouterLink class="back-link" :to="{ name: 'high-trends', query: taskId ? { task: taskId } : {} }"><ArrowLeftOutlined /> 高潜趋势</RouterLink>
      <h1>图片挑选</h1>
      <span v-if="review" class="save-state" aria-live="polite"><span :class="{ busy: saving }"></span>{{ saving ? '保存中…' : '已自动保存' }}</span>
    </header>
    <main class="review-main">
      <nav class="collection-tabs" aria-label="选择图库">
        <RouterLink :class="{ active: !isRemaining }" :to="{ query: { task: taskId, collection: 'result' } }">结果图片</RouterLink>
        <RouterLink :class="{ active: isRemaining }" :to="{ query: { task: taskId, collection: 'remaining' } }">其他图片 · 未进入结果</RouterLink>
      </nav>
      <a-alert v-if="error" class="review-alert" type="error" show-icon :message="error" closable @close="error = ''" />
      <section v-if="loading" class="loading-panel"><a-spin size="large" /><h2>正在准备图片副本</h2><p>正在整理来源与文件信息，已有选择会自动恢复。</p></section>
      <section v-else-if="!review" class="empty-panel"><PictureOutlined /><p>暂时无法打开图片整理档案。</p><a-button v-if="taskId" @click="load"><ReloadOutlined /> 重试</a-button></section>
      <template v-else>
        <div class="collection-summary"><span>共 <b>{{ review.counts.total }}</b> 张</span><span class="kept">已保留 <b>{{ review.counts.retained }}</b></span><span>{{ isRemaining ? '待挑选' : '已排除' }} {{ review.counts.excluded }}</span><details class="archive-info"><summary>范围与档案</summary><div class="archive-content"><p>{{ review.scope || '本次结果引用的全部图片，按文件内容去重。' }}</p><p v-if="isRemaining">已按 SHA-256 排除本次结果的全部图片，不受结果图库保留状态影响。两份图库独立保存选择；其他图片默认未保留。</p><p v-if="review.dedup_summary">候选 {{ review.dedup_summary.candidate_unique_files }} 张 · 与结果重复 {{ review.dedup_summary.excluded_result_files }} 张<span v-if="review.dedup_summary.user_dislike_filtered_files"> · 不喜欢已过滤 {{ review.dedup_summary.user_dislike_filtered_files }} 张</span> · 剩余 {{ review.dedup_summary.remaining_unique_files }} 张</p><p v-if="sharedCount">{{ sharedCount }} 张图片有两种来源，会在两个来源中展示，状态同步。</p><dl><dt>保存位置</dt><dd><code>{{ review.folder }}</code></dd><dt>最近保存</dt><dd>{{ dateTime(review.updated_at) }}</dd></dl><p>来源清单保留原始路径、图号、态度和文件指纹。操作不删除原图。</p><details v-if="review.warnings?.length"><summary>来源信息提示 · {{ review.warnings.length }}</summary><p v-for="(warning, index) in review.warnings" :key="index"><code>{{ warning.source_file }}</code><br />{{ warning.message }}</p></details></div></details></div>
        <a-alert v-if="review.counts.missing" class="review-alert" type="warning" show-icon :message="`${review.counts.missing} 条图片引用没有可复制文件，详情见来源清单。`" />
        <section class="review-toolbar" aria-label="筛选图片">
          <div class="source-row"><div class="source-tabs" role="group" aria-label="图片来源"><button :class="{ active: sourceKind === 'trend' }" @click="sourceKind = 'trend'">趋势来源 <span>{{ review.counts.trend }}</span></button><button :class="{ active: sourceKind === 'user' }" @click="sourceKind = 'user'">用户来源 <span>{{ review.counts.user }}</span></button></div><a-radio-group v-model:value="density" size="small" aria-label="图片大小"><a-radio-button value="compact">紧凑</a-radio-button><a-radio-button value="large">大图</a-radio-button></a-radio-group></div>
          <div class="filter-row"><a-radio-group v-model:value="filter" size="small" button-style="solid" :options="filterOptions" option-type="button" /><a-input v-model:value="query" size="small" class="search-input" allow-clear placeholder="搜索图号、标题、用户" aria-label="搜索图片"><template #prefix><SearchOutlined /></template></a-input></div>
          <details class="more-controls"><summary>批量选择、下载与方向筛选</summary><div class="extra-controls"><a-select v-if="directions.length > 1" v-model:value="directionId" size="small" class="direction-filter" :options="directions" aria-label="按设计方向筛选" /><a-button size="small" :disabled="locked || pageRetained === pageImages.length" @click="bulkSelection(true)">保留本页全部</a-button><a-button size="small" :disabled="locked || pageRetained === 0" @click="bulkSelection(false)">取消本页保留</a-button><a-button size="small" :loading="exporting === 'json'" :disabled="locked || !!exporting" @click="download('json')">下载来源清单</a-button><a-button size="small" type="primary" :loading="exporting === 'zip'" :disabled="locked || !!exporting" @click="download('zip')"><DownloadOutlined /> 下载全部保留图 · {{ review.counts.retained }}</a-button><p>批量操作只影响本页 {{ pageImages.length }} 张；下载包含本图库全部保留图片，不受筛选条件影响。</p></div></details>
        </section>
        <section ref="gallery" class="source-section" :aria-label="sourceKind === 'trend' ? '趋势来源图片' : '用户来源图片'">
          <div class="page-navigation"><span>筛选到 {{ visibleImages.length }} 张 · 每页 {{ pageSize }} 张</span><a-pagination :current="page" :total="visibleImages.length" :page-size="pageSize" simple :show-size-changer="false" size="small" @change="changePage" /></div>
          <div v-if="pageImages.length" class="review-image-grid" :class="density">
            <article v-for="image in pageImages" :key="image.id" class="image-card" :class="{ excluded: !image.retained }">
              <button class="image-preview" :aria-label="`查看 ${imageLabel(image)} 大图与来源`" @click="previewId = image.id"><img :src="imageUrl(image, true)" :alt="imageLabel(image)" loading="lazy" decoding="async" /><span class="image-state" :class="{ retained: image.retained }"><CheckOutlined v-if="image.retained" />{{ image.retained ? '保留' : notRetainedLabel() }}</span><span v-if="sourceKind === 'user'" class="emotion-tag">{{ emotionLabel(image) }}</span><span class="preview-hint">查看大图与来源</span></button>
              <div class="image-card-body"><button class="image-name" :title="image.image_ids.join('、')" @click="previewId = image.id">{{ imageLabel(image) }}</button><button class="selection-button" :class="{ restore: !image.retained }" :disabled="locked" @click="saveSelection([image], !image.retained)">{{ image.retained ? '取消保留' : '保留' }}</button></div>
            </article>
          </div>
          <div v-else class="section-empty"><PictureOutlined /><p>这个来源下没有符合当前筛选的图片。</p></div>
          <div v-if="pageImages.length" class="page-navigation bottom"><span>第 {{ page }} / {{ pageCount }} 页</span><a-pagination :current="page" :total="visibleImages.length" :page-size="pageSize" simple :show-size-changer="false" size="small" @change="changePage" /></div>
        </section>
      </template>
    </main>
    <a-modal :open="Boolean(preview)" :title="preview ? imageLabel(preview) : ''" :width="1040" :footer="null" centered class="review-preview-modal" @cancel="previewId = null">
      <div v-if="preview" class="preview-layout">
        <div class="preview-image-panel"><img :src="imageUrl(preview)" :alt="imageLabel(preview)" /><a-button :danger="preview.retained" :disabled="locked" :loading="saving" @click="saveSelection([preview], !preview.retained)">{{ preview.retained ? '排除这张图片' : '保留这张图片' }}</a-button><p>{{ preview.retained ? '当前已保留' : notRetainedLabel() }} · {{ byteSize(preview.byte_size) }}<template v-if="preview.width && preview.height"> · {{ preview.width }} × {{ preview.height }}</template></p></div>
        <div class="preview-info"><h3 v-if="preview.directions.length">关联设计方向</h3><div class="direction-tags"><span v-for="item in preview.directions" :key="item.id">{{ item.title }}</span></div><h3>来源记录 <small>{{ preview.origins.length }}</small></h3><details v-for="(origin, index) in preview.origins" :key="index" class="origin-detail" :open="index === 0"><summary><span>{{ origin.source_kind === 'trend' ? '趋势' : '用研' }}</span>{{ origin.source_title || origin.code || origin.image_id || origin.source_record_id || '来源记录' }}</summary><dl><template v-if="origin.image_id"><dt>原始图号</dt><dd>{{ origin.image_id }}</dd></template><template v-if="origin.code"><dt>图片代码</dt><dd>{{ origin.code }}</dd></template><template v-if="origin.user_id != null"><dt>用户</dt><dd>{{ origin.user_id }}</dd></template><template v-if="origin.source_kind === 'user'"><dt>原始态度</dt><dd>{{ origin.emotion_tag || '未标注' }}</dd></template><dt>记录</dt><dd>{{ origin.source_record_id }} {{ origin.source_aliases.join('、') }}</dd><template v-if="origin.direction_title"><dt>引用方向</dt><dd>{{ origin.direction_title }}</dd></template><dt>原始路径</dt><dd><code>{{ origin.original_absolute_path || origin.original_path || '未提供' }}</code></dd><template v-if="origin.source_file"><dt>来源文件</dt><dd><code>{{ origin.source_file }}{{ origin.json_pointer ? `#${origin.json_pointer}` : '' }}</code></dd></template><template v-if="origin.urls.length"><dt>来源链接</dt><dd v-for="url in origin.urls" :key="url"><code>{{ url }}</code></dd></template></dl></details><details class="fingerprint-info"><summary>文件副本与去重信息</summary><dl><dt>副本路径</dt><dd><code>{{ preview.copy_path }}</code></dd><dt>SHA-256</dt><dd><code>{{ preview.sha256 }}</code></dd><dt>关联图号</dt><dd>{{ preview.image_ids.join('、') }}</dd></dl></details></div>
      </div>
    </a-modal>
  </div>
</template>

<style scoped>
.review-page { min-height: 100vh; background: #f7f6fa; color: #443a51; }
.review-header { display: flex; align-items: center; gap: 20px; min-height: 48px; padding: 8px 18px; border-bottom: 1px solid #e7e1ed; background: #fff; }
.back-link { display: flex; align-items: center; gap: 7px; color: #79628f; font-size: 12px; }
h1 { margin: 0; font-size: 17px; font-weight: 600; }
.save-state { display: flex; gap: 6px; align-items: center; margin-left: auto; color: #64815f; font-size: 11px; }
.save-state > span { width: 6px; height: 6px; border-radius: 50%; background: #88a982; }
.save-state .busy { background: #b093cc; }
.review-main { width: 100%; max-width: none; margin: 0; box-sizing: border-box; padding: 0 18px 16px; }
.collection-tabs { display: flex; gap: 18px; padding: 12px 0 8px; }
.collection-tabs a { font-size: 14px; color: #8e7e9b; padding-bottom: 7px; border-bottom: 2px solid transparent; }
.collection-tabs .active { color: #6e488c; border-color: #9972b4; font-weight: 600; }
.collection-summary { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; font-size: 11px; color: #8f7c9a; padding-bottom: 10px; }
.collection-summary b { color: #655072; font-size: 13px; }
.kept, .kept b { color: #64836a; }
.archive-info { position: relative; margin-left: auto; }
.archive-content { position: absolute; z-index: 4; top: 24px; right: 0; width: min(440px, calc(100vw - 36px)); background: #fff; padding: 14px; box-shadow: 0 4px 24px #3e294526; border: 1px solid #e8dfef; border-radius: 8px; line-height: 1.7; }
summary { cursor: pointer; }
dl { margin: 12px 0; }
dt { color: #a69aac; font-size: 10px; margin-top: 9px; }
dd { margin: 3px 0 0; line-height: 1.7; font-size: 11px; overflow-wrap: anywhere; }
code { font-size: 10px; overflow-wrap: anywhere; }
.review-alert { margin-bottom: 10px; }
.review-toolbar { padding: 10px 12px; border: 1px solid #e5dced; border-radius: 9px; background: #fff; }
.source-row, .filter-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.source-row { justify-content: space-between; margin-bottom: 9px; }
.source-tabs { display: flex; gap: 4px; }
.source-tabs button { border: 0; border-radius: 5px; padding: 6px 10px; background: transparent; color: #907a9e; cursor: pointer; font-size: 12px; }
.source-tabs button.active { background: #eee5f6; color: #694480; font-weight: 600; }
.source-tabs span { margin-left: 4px; font-size: 11px; font-weight: 400; }
.search-input { min-width: 160px; flex: 1; max-width: 480px; }
.more-controls { margin-top: 8px; font-size: 11px; color: #927e9d; }
.extra-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 10px; }
.extra-controls p { width: 100%; margin: 0; font-size: 11px; }
.direction-filter { width: min(280px, 100%); }
.source-section { scroll-margin-top: 8px; }
.page-navigation { display: flex; justify-content: space-between; align-items: center; min-height: 42px; gap: 10px; color: #92809e; font-size: 11px; }
.page-navigation.bottom { margin-top: 8px; }
/* 独立类名隔离全局图库的 370px 限高，使用页面滚动而非狭小的内部滚动框。 */
.review-image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(175px, 1fr)); gap: 10px; }
.review-image-grid.large { grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); }
.image-card { min-width: 0; border: 1px solid #e6dfee; border-radius: 8px; overflow: hidden; background: #fff; }
.image-card:hover { border-color: #bba5ce; }
.image-card.excluded { border-style: dashed; }
.image-preview { position: relative; display: block; width: 100%; aspect-ratio: 1; padding: 5px; border: none; background: #f0edf3; cursor: zoom-in; }
.image-preview > img { display: block; width: 100%; height: 100%; object-fit: contain; }
/* 未保留的图片仍以原亮度展示，避免人工挑选时看不清材质和颜色。 */
.image-state { position: absolute; top: 6px; left: 6px; display: flex; align-items: center; gap: 4px; padding: 3px 5px; border-radius: 4px; background: #fffef2ed; color: #8b7a63; font-size: 10px; }
.image-state.retained { background: #eff8edee; color: #487451; }
.emotion-tag { position: absolute; bottom: 5px; left: 5px; max-width: calc(100% - 10px); background: #fffffff0; color: #76627d; border-radius: 4px; font-size: 10px; padding: 2px 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-hint { position: absolute; left: 50%; bottom: 24px; transform: translateX(-50%); white-space: nowrap; padding: 5px 8px; border-radius: 5px; background: #45334bcc; color: #fff; font-size: 10px; opacity: 0; }
.image-preview:hover .preview-hint, .image-preview:focus-visible .preview-hint { opacity: 1; }
.image-card-body { display: flex; align-items: center; gap: 5px; padding: 5px 6px; min-height: 34px; }
.image-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: #766180; background: none; padding: 0; border: 0; cursor: pointer; text-align: left; }
.selection-button { padding: 4px 6px; font-size: 10px; background: #faf4f5; border: 1px solid #eee0e5; border-radius: 4px; color: #9a6875; cursor: pointer; white-space: nowrap; }
.selection-button.restore { color: #54795b; background: #edf6ec; border-color: #d6e5d3; }
.selection-button:disabled { opacity: .5; cursor: wait; }
.section-empty, .empty-panel, .loading-panel { padding: 55px 20px; text-align: center; color: #a797b1; font-size: 12px; border: 1px dashed #ddd2e6; border-radius: 9px; }
.loading-panel h2 { margin-top: 25px; font-size: 16px; color: #7a628d; font-weight: 500; }
.preview-layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 26px; }
.preview-image-panel { text-align: center; }
.preview-image-panel > img { display: block; width: 100%; height: min(55vh, 500px); object-fit: contain; background: #f7f5f9; border-radius: 10px; margin: 8px 0 16px; }
.preview-image-panel > p { font-size: 11px; color: #a797b1; }
.preview-info { max-height: 70vh; overflow-y: auto; padding-right: 6px; color: #877191; }
.preview-info h3 { font-size: 13px; color: #695174; margin: 12px 0; }
.preview-info h3 small { font-size: 11px; color: #af9abc; }
.direction-tags { display: flex; flex-wrap: wrap; gap: 7px; }
.direction-tags span { font-size: 10px; line-height: 1.7; padding: 4px 8px; border-radius: 6px; background: #f3edf8; color: #9676aa; }
.origin-detail { border-bottom: 1px solid #eee7f2; padding: 12px 0; }
.origin-detail summary { font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.origin-detail summary > span { color: #ae99bc; margin-right: 7px; }
.fingerprint-info { padding: 16px 0; font-size: 11px; color: #a390b0; }
@media (max-width: 800px) { .preview-layout { grid-template-columns: 1fr; } .preview-info { max-height: none; } .preview-image-panel > img { height: 38vh; } }
@media (max-width: 620px) {
  .review-header { padding: 8px 10px; gap: 12px; }
  .review-main { padding: 0 10px 12px; }
  .collection-tabs { gap: 16px; }
  .collection-tabs a { font-size: 13px; }
  .collection-summary { gap: 9px; font-size: 10px; }
  .review-toolbar { padding: 8px; }
  .source-tabs button { padding: 5px 7px; font-size: 11px; }
  .source-row { gap: 6px; }
  .filter-row { gap: 6px; }
  .search-input { min-width: 130px; }
  .page-navigation { gap: 4px; font-size: 10px; }
  .review-image-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .review-image-grid.large { grid-template-columns: 1fr; }
  .preview-hint { display: none; }
}
</style>
