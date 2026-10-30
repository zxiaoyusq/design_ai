<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { fetchNativeHighTrendImages, nativeHighTrendDownloadUrl } from '@/api/highTrends'
import type { HighTrendCard, HighTrendTask, NativeResearchCitation, TrendImage } from '@/types/highTrends'

const props = defineProps<{ task: HighTrendTask }>()
const filter = ref<'all' | 'selected' | 'exploratory'>('selected')
type ImageScope = 'all' | 'cited' | 'associated'
interface GalleryState { items: TrendImage[]; page: number; total: number; scope: ImageScope; loading: boolean; error: string; version: number }
const galleries = ref<Record<string, GalleryState>>({})
let disposed = false
const cards = computed(() => props.task.result?.trends ?? [])
const selectedCount = computed(() => cards.value.filter(card => card.native_detail?.selected).length)
const visibleCards = computed(() => cards.value.filter(card => filter.value === 'all' || (filter.value === 'selected' ? card.native_detail?.selected : !card.native_detail?.selected)))
const provenance = computed(() => props.task.provenance ?? props.task.result?.provenance ?? {})
const relationLabels = { direct_support: '直接支持', anchored_extension: '有依据的延展', exploratory_hypothesis: '探索假设', unknown: '未分级' }
function relationLabel(card: HighTrendCard) { return relationLabels[card.relation_basis ?? 'unknown'] }
function branchLabel(value: string) { return value === 'ID' ? 'ID · 形态与结构' : value === 'CMF' ? 'CMF · 色彩材质表面' : value }
function displayValue(value: unknown): string {
  if (value == null || value === '') return '未记录'
  if (Array.isArray(value)) return value.map(displayValue).join('、') || '未记录'
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}：${displayValue(item)}`).join('；') || '未记录'
  return String(value)
}
function sourceKind(citation: NativeResearchCitation) {
  const kind = citation.source_kind ?? ''
  if (/existing_analysis|analyst|analysis|reference/.test(kind) || citation.role === 'reference') return '分析资料 · 供参考'
  if (/quote|verbatim|utterance|interview/.test(kind)) return '用研原文'
  const kinds: Record<string, string> = { brand_preference_or_impression: '品牌偏好或印象', elicited_concept_image_example: '概念图片评价', explicit_cmf_caption: '明确的色彩材质说明', phone_preference_reason: '手机偏好理由' }
  return kinds[kind] || '用研来源'
}
function roleLabel(value?: string) {
  const labels: Record<string, string> = { direct_support: '直接支持', brand_association: '品牌关联', background: '背景资料', illustration: '举例说明', boundary: '边界条件', unresolved: '关系未决', support: '支持依据', supporting: '支持依据', positive: '正向', negative: '负向', conditional: '有条件', reference: '参考资料', anchor: '锚点', direct: '直接依据', user_quote: '用户原话' }
  return value ? labels[value] ?? '其他证据角色' : '未标明角色'
}
function objectScope(value: NativeResearchCitation['object_scope']) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return displayValue(value)
  const object = displayValue(value.object)
  const context = typeof value.context === 'string' ? value.context : ''
  return context ? `${object}；情境：${context}` : object
}
function textKind(value?: string) {
  return ({ title: '文章标题', summary: '文章摘要', summary_zh: '文章中文摘要', source_paraphrase: '存档释义', verbatim: '原文引用', quote: '原文引用' } as Record<string, string>)[value ?? ''] ?? '趋势文本依据'
}
function safeArticleUrl(value?: string | null) {
  if (!value) return undefined
  try { const url = new URL(value); return /^https?:$/.test(url.protocol) ? url.href : undefined } catch { return undefined }
}
/** 原图和缩略图只能来自本次冻结结果的图片接口，资料中的任意 URL 不进入 img。 */
function safeImageUrl(image: TrendImage, original = false) {
  const value = original ? image.original_url : image.url
  if (!image.file_exists || !value) return undefined
  const prefix = `/api/v1/high-trends/native-results/${encodeURIComponent(props.task.id)}/images/`
  if (!value.startsWith(prefix)) return undefined
  const suffix = value.slice(prefix.length)
  return /^[A-Za-z0-9_-]+(?:\?thumbnail=true)?$/.test(suffix) ? value : undefined
}
function dateLabel(value?: string) {
  if (!value) return '未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function gallery(card: HighTrendCard): GalleryState {
  return galleries.value[card.id] ?? { items: [], page: 1, total: card.native_detail?.total_image_count ?? 0, scope: 'all', loading: true, error: '', version: 0 }
}
async function loadImages(card: HighTrendCard, page = 1, scope: ImageScope = gallery(card).scope) {
  if (!galleries.value[card.id]) galleries.value[card.id] = { ...gallery(card) }
  const state = galleries.value[card.id]!
  const version = ++state.version
  state.loading = true
  state.error = ''
  try {
    const result = await fetchNativeHighTrendImages(props.task.id, card.id, page, scope)
    if (disposed || galleries.value[card.id] !== state || version !== state.version) return
    Object.assign(state, { items: result.items, page: result.page, total: result.total, scope })
  } catch {
    if (!disposed && version === state.version) state.error = '图片读取失败，请重试。'
  } finally {
    if (!disposed && version === state.version) state.loading = false
  }
}
function changeScope(card: HighTrendCard, event: Event) {
  void loadImages(card, 1, (event.target as HTMLSelectElement).value as ImageScope)
}
watch(() => props.task.id, () => {
  galleries.value = {}
  for (const card of cards.value) {
    const preview = card.native_detail?.preview_images
    if (preview) galleries.value[card.id] = { items: preview, page: 1, total: card.native_detail?.total_image_count ?? 0, scope: 'all', loading: false, error: '', version: 0 }
    else void loadImages(card)
  }
}, { immediate: true })
onUnmounted(() => { disposed = true })
</script>

<template>
  <div class="native-results">
    <section class="workspace-card native-summary">
      <div class="summary-heading"><div><span class="eyebrow">02 / 高潜趋势结果</span><h2>上次高潜筛选</h2><p>趋势与用研的第一次语义握手，保留候选、选向依据与完整来源。</p></div><div class="summary-counts"><div><strong>{{ cards.length }}</strong><span>个候选方向</span></div><div><strong>{{ selectedCount }}</strong><span>个已选方向</span></div><div><strong>{{ cards.length - selectedCount }}</strong><span>个探索备选</span></div></div></div>
      <p class="run-note">模型 {{ provenance.model_id || task.request.model_id }} · 原运行 {{ dateLabel(task.created_at) }}</p>
      <p class="scope-note">{{ task.result?.scope_note }}</p>
      <div class="native-downloads"><a :href="nativeHighTrendDownloadUrl(task.id, 'markdown')" download>结果说明 ↓</a><a :href="nativeHighTrendDownloadUrl(task.id, 'json')" download>完整结果 JSON ↓</a><a :href="nativeHighTrendDownloadUrl(task.id, 'selection')" download>选向记录 ↓</a><a :href="nativeHighTrendDownloadUrl(task.id, 'sources')" download>文章与图片来源 ↓</a></div>
      <details class="provenance-details"><summary>原运行与选向记录</summary><p>模型：{{ provenance.model_id || task.request.model_id }}</p><p>算法版本：{{ provenance.algorithm_version || '未记录' }}</p><p>选向时间：{{ dateLabel(provenance.confirmed_at) }}</p><p>执行角色：{{ provenance.actor === 'user_delegated_ai' ? '用户授权 AI 代选' : displayValue(provenance.actor) }}</p><p>本页呈现原运行结果，支持分级、未决事项与选向记录均按该次产物保留。</p></details>
    </section>
    <div class="native-filters" aria-label="方向筛选"><button :class="{ active: filter === 'all' }" @click="filter = 'all'">全部 {{ cards.length }}</button><button :class="{ active: filter === 'selected' }" @click="filter = 'selected'">已选方向 {{ selectedCount }}</button><button :class="{ active: filter === 'exploratory' }" @click="filter = 'exploratory'">探索备选 {{ cards.length - selectedCount }}</button></div>
    <article v-for="card in visibleCards" :key="card.id" class="native-direction workspace-card" :data-direction-id="card.id">
      <div class="direction-top"><span>{{ card.id }} · 趋势 × 用研</span><a-tag :color="card.native_detail?.selected ? 'purple' : 'default'">{{ card.native_detail?.selected ? '已选方向' : '探索备选' }}</a-tag></div>
      <h3>{{ card.title }}</h3>
      <div class="direction-tags"><a-tag :color="card.relation_basis === 'direct_support' ? 'green' : card.relation_basis === 'anchored_extension' ? 'blue' : 'orange'">{{ relationLabel(card) }}</a-tag><a-tag v-for="branch in (card.native_detail?.selected_branches.length ? card.native_detail.selected_branches : card.native_detail?.suggested_branches ?? [])" :key="branch">{{ branchLabel(branch) }}</a-tag></div>
      <dl class="direction-principles"><dt>共同设计原则</dt><dd>{{ card.shared_design_principle || card.description }}</dd><template v-if="card.native_detail?.design_question"><dt>设计问题</dt><dd>{{ card.native_detail.design_question }}</dd></template><template v-if="card.native_detail?.selection_reason"><dt>{{ card.native_detail.selected ? '选择理由' : '保留为探索的理由' }}</dt><dd>{{ card.native_detail.selection_reason }}</dd></template><template v-if="card.native_detail?.extension_explanation"><dt>延展依据</dt><dd>{{ card.native_detail.extension_explanation }}</dd></template></dl>
      <div v-if="card.native_detail?.hypotheses?.length" class="direction-boundaries"><h4>待验证的设计假设</h4><ul><li v-for="hypothesis in card.native_detail.hypotheses" :key="hypothesis">{{ hypothesis }}</li></ul></div>
      <div class="evidence-columns">
        <details class="evidence-block"><summary>用研依据 <span>{{ card.native_detail?.research_citations.length ?? 0 }} 条</span></summary><section v-for="citation in card.native_detail?.research_citations" :key="citation.unit_id" class="evidence-item"><div class="citation-meta"><strong>{{ citation.person_id != null ? `人物 ${citation.person_id}` : '人物未记录' }}</strong><span>{{ sourceKind(citation) }}</span><span>{{ roleLabel(citation.role) }}</span></div><p class="object-scope">原始对象：{{ objectScope(citation.object_scope) }}</p><blockquote>{{ citation.text }}</blockquote><p v-if="citation.reason" class="citation-reason">关联依据：{{ citation.reason }}</p><details v-if="citation.original_text && citation.original_text !== citation.text" class="original-source"><summary>查看来源全文</summary><p>{{ citation.original_text }}</p></details><code>{{ citation.unit_id }}</code></section></details>
        <details class="evidence-block"><summary>趋势依据 <span>{{ card.native_detail?.trend_citations.length ?? 0 }} 条 · {{ card.native_detail?.direct_article_count ?? 0 }} 篇直接引用文章</span></summary><section v-for="citation in card.native_detail?.trend_citations" :key="citation.evidence_id" class="evidence-item"><strong>{{ citation.title || citation.source_id || '趋势文本' }}</strong><p class="object-scope">{{ textKind(citation.text_kind) }}</p><blockquote>{{ citation.text }}</blockquote><p v-if="citation.reason" class="citation-reason">关联依据：{{ citation.reason }}</p><details v-if="citation.original_text && citation.original_text !== citation.text" class="original-source"><summary>查看存档全文</summary><p>{{ citation.original_text }}</p></details><a v-if="safeArticleUrl(citation.url || citation.source_url)" :href="safeArticleUrl(citation.url || citation.source_url)" target="_blank" rel="noopener noreferrer">打开原文章 ↗</a><code>{{ citation.evidence_id }} · {{ citation.source_id }}</code></section></details>
      </div>
      <details class="conditions-block"><summary>成立条件、负向审计与未决问题</summary><div v-if="card.native_detail?.conditions.length"><h4>成立条件与适用范围</h4><section v-for="(condition, index) in card.native_detail.conditions" :key="`${condition.reference_id}-${index}`" class="condition-item"><p>{{ condition.text }}</p><p v-if="condition.implication" class="citation-reason">设计影响：{{ condition.implication }}</p><code v-if="condition.reference_id">{{ condition.reference_id }}</code></section></div><div class="negative-counts"><span>适用于本方向的负向 {{ card.native_detail?.negative_counts.applicable ?? 0 }}</span><span>关系未决 {{ card.native_detail?.negative_counts.unresolved ?? 0 }}</span><span>不适用 {{ card.native_detail?.negative_counts.not_applicable ?? 0 }}</span></div><p class="scope-note">以上为原始负向条目与本方向的审计关系数量，完整审计见下载结果。</p><div v-if="card.native_detail?.unresolved_questions.length"><h4>仍待确认</h4><ul><li v-for="question in card.native_detail.unresolved_questions" :key="question">{{ question }}</li></ul></div></details>
      <section class="native-gallery">
        <div class="gallery-heading"><div><h4>相关图片 <span>{{ card.native_detail?.total_image_count ?? 0 }} 张来源关联</span></h4><p>{{ card.native_detail?.source_article_count ?? 0 }} 篇相关文章。文章配图保留来源，尚未进行视觉匹配。</p></div><label>图片来源<select :value="gallery(card).scope" :disabled="gallery(card).loading" @change="changeScope(card, $event)"><option value="all">全部关联</option><option value="cited">直接引用文章配图</option><option value="associated">同簇关联配图</option></select></label></div>
        <a-alert v-if="gallery(card).error" type="warning" :message="gallery(card).error" show-icon><template #action><a-button size="small" @click="loadImages(card, gallery(card).page)">重试</a-button></template></a-alert>
        <a-spin :spinning="gallery(card).loading">
          <a-image-preview-group><div class="native-image-grid"><figure v-for="(image, index) in gallery(card).items" :key="`${image.image_id}-${index}`"><a-image v-if="safeImageUrl(image)" :src="safeImageUrl(image)" :preview="{ src: safeImageUrl(image, true) || safeImageUrl(image) }" :alt="image.article_title || image.image_id || '趋势来源图片'" loading="lazy" /><div v-else class="unavailable-image">本地图片不可用</div><figcaption><span class="association-badge" :class="{ cited: image.association_type === 'cited' }">{{ image.association_type === 'cited' ? '直接引用文章配图' : '同簇关联' }}</span><a v-if="safeArticleUrl(image.article_url)" :href="safeArticleUrl(image.article_url)" target="_blank" rel="noopener noreferrer">{{ image.article_title || image.source_record_id || '来源文章' }} ↗</a><span v-else>{{ image.article_title || image.source_record_id || '来源文章未记录' }}</span><small>{{ image.image_id }}</small><small v-if="image.direction_ids?.length">关联方向：{{ image.direction_ids.join('、') }}</small></figcaption></figure></div></a-image-preview-group>
          <p v-if="!gallery(card).loading && !gallery(card).items.length" class="scope-note">该范围暂无图片。</p>
        </a-spin>
        <div class="gallery-pagination"><span>共 {{ gallery(card).total }} 张 · 每页 12 张</span><a-pagination size="small" :current="gallery(card).page" :total="gallery(card).total" :page-size="12" :show-size-changer="false" :disabled="gallery(card).loading" @change="(page: number) => loadImages(card, page)" /></div>
      </section>
    </article>
  </div>
</template>

<style scoped>
.native-summary { padding: 28px; }
.summary-heading { display: flex; justify-content: space-between; gap: 25px; }
h2 { margin: 10px 0; font-size: 25px; color: #49385d; }
.summary-heading p, .scope-note, .run-note { color: #8b7d99; font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.summary-counts { display: flex; align-items: center; gap: 30px; flex-shrink: 0; }
.summary-counts div { display: grid; gap: 5px; text-align: center; }
.summary-counts strong { color: #6c50a2; font-size: 29px; font-weight: 500; }
.summary-counts span { color: #9b8aaa; font-size: 11px; }
.native-downloads { display: flex; flex-wrap: wrap; gap: 18px; margin: 18px 0; font-size: 12px; }
a { color: #755795; }
.provenance-details { font-size: 11px; color: #95869f; border-top: 1px solid #eee7f4; padding-top: 15px; }
.provenance-details p { margin: 7px 0; }
summary { cursor: pointer; line-height: 1.8; }
.native-filters { display: flex; gap: 10px; margin: 22px 0; flex-wrap: wrap; }
.native-filters button { cursor: pointer; border: 1px solid #e4d9ee; border-radius: 10px; color: #8a759a; background: #fcfaff; padding: 10px 17px; font-size: 12px; }
.native-filters button.active { background: #eee5f9; border-color: #baa2d5; color: #664587; }
.native-direction { padding: 28px; margin-bottom: 24px; min-width: 0; }
.direction-top { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #9e8eac; }
h3 { margin: 9px 0 14px; font-size: 25px; line-height: 1.5; color: #49345f; }
.direction-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 18px; }
.direction-tags :deep(.ant-tag) { margin: 0; }
.direction-principles { background: #f8f5fc; border-radius: 14px; padding: 19px 22px; margin: 0 0 18px; }
dt { color: #6c5182; font-size: 12px; font-weight: 600; margin-top: 16px; }
dt:first-child { margin-top: 0; }
dd { margin: 7px 0 0; color: #7d6b8c; line-height: 1.9; font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
h4 { color: #6a527d; margin: 16px 0 10px; font-size: 13px; }
.direction-boundaries, .conditions-block { font-size: 12px; color: #8b7998; line-height: 1.9; }
.evidence-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px; margin-top: 20px; align-items: start; }
.evidence-block { border: 1px solid #eae2f0; border-radius: 12px; padding: 14px 16px; color: #79628c; font-size: 12px; }
.evidence-block summary span { color: #a291af; font-size: 11px; margin-left: 6px; }
.evidence-block[open] { max-height: 570px; overflow: auto; }
.evidence-item { padding: 17px 0; border-bottom: 1px solid #eee7f3; }
.evidence-item:last-child { border: 0; }
.citation-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.citation-meta span { font-size: 10px; border-radius: 5px; background: #f3eff8; padding: 3px 6px; }
.object-scope, .citation-reason { color: #a08bad; font-size: 11px; line-height: 1.8; }
.original-source { font-size: 11px; color: #9b86aa; margin: 10px 0; }
.original-source p { white-space: pre-wrap; line-height: 1.8; overflow-wrap: anywhere; }
blockquote { margin: 10px 0; padding: 10px 13px; border-left: 2px solid #d6c5e7; background: #faf8fc; white-space: pre-wrap; line-height: 1.9; overflow-wrap: anywhere; }
code { display: block; color: #aa9ab6; font-size: 10px; overflow-wrap: anywhere; margin-top: 8px; }
.conditions-block { margin-top: 18px; padding: 15px 18px; background: #fcfbfd; border: 1px solid #ede6f2; border-radius: 12px; }
.condition-item { border-bottom: 1px solid #eee7f3; padding: 6px 0; }
.negative-counts { display: flex; flex-wrap: wrap; gap: 10px 20px; margin-top: 20px; font-size: 11px; color: #927e9f; }
ul { margin: 10px 0; padding-left: 20px; }
.native-gallery { border-top: 1px solid #ede5f3; margin-top: 24px; padding-top: 5px; }
.gallery-heading { display: flex; justify-content: space-between; align-items: start; gap: 20px; margin-bottom: 16px; }
.gallery-heading h4 span { font-weight: 400; font-size: 11px; color: #aa95b8; margin-left: 8px; }
.gallery-heading p { font-size: 11px; color: #a28fb0; line-height: 1.8; margin: 0; }
.gallery-heading label { display: grid; gap: 8px; margin-top: 16px; font-size: 10px; color: #947da4; flex-shrink: 0; }
select { border: 1px solid #e5d9ee; color: #7b6091; background: #fff; border-radius: 8px; padding: 7px 9px; font-size: 11px; }
.native-image-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 15px; }
figure { min-width: 0; margin: 0; }
figure :deep(.ant-image) { width: 100%; height: 150px; background: #f5f2f7; border-radius: 10px; overflow: hidden; display: flex; align-items: center; justify-content: center; }
figure :deep(.ant-image-img) { width: 100%; height: 100%; object-fit: contain; }
.unavailable-image { height: 150px; display: grid; place-items: center; color: #b0a0bc; font-size: 11px; background: #f7f4fa; border-radius: 10px; }
figcaption { display: flex; flex-direction: column; gap: 6px; margin-top: 9px; line-height: 1.6; font-size: 10px; color: #9a85a9; overflow-wrap: anywhere; }
figcaption > a, figcaption > span:not(.association-badge) { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; }
figcaption small { font-size: 9px; color: #b3a2bf; }
.association-badge { align-self: flex-start; background: #f3eff7; color: #9b84ad; border-radius: 4px; padding: 2px 5px; font-size: 9px; }
.association-badge.cited { background: #efe6f9; color: #8661a3; }
.gallery-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 15px; margin-top: 20px; font-size: 11px; color: #a08cac; }
@media (max-width: 1100px) { .native-image-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 760px) { .summary-heading { flex-direction: column; } .summary-counts { align-self: start; } .evidence-columns { grid-template-columns: minmax(0, 1fr); } .native-image-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .native-direction, .native-summary { padding: 21px; } .gallery-heading { flex-direction: column; gap: 4px; } .gallery-heading label { margin-top: 5px; } h3 { font-size: 22px; } }
@media (max-width: 480px) { .native-image-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } figure :deep(.ant-image), .unavailable-image { height: 140px; } .direction-principles { padding: 16px; } .summary-counts { gap: 25px; } }
</style>
