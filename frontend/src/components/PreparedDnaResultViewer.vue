<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ExpandOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import PreparedImageCrop from '@/components/PreparedImageCrop.vue'
import type { PreparedCoverage, PreparedDesignCard, PreparedDnaResult, PreparedResultSummary } from '@/types/dnaV2'

const props = defineProps<{
  results: PreparedResultSummary[]
  coverage: PreparedCoverage | null
  activeResultId: string | null
  result: PreparedDnaResult | null
  loading: boolean
}>()
const emit = defineEmits<{ select: [id: string]; refresh: [] }>()
const search = ref('')
const branch = ref('all')
const status = ref('all')
const source = ref('all')
const style = ref('all')
const page = ref(1)
const pageSize = 24
const detailOpen = ref(false)
const originalOpen = ref(false)
const cardId = ref('')
const rawOpen = ref(false)
const catalog = computed(() => props.coverage?.style_catalog ?? props.result?.style_catalog ?? [])
const styleOptions = computed(() => [{ value: 'all', label: '全部风格' }, ...catalog.value.map((s) => ({ value: s.style_id, label: s.name }))])
const styleName = (id: string) => catalog.value.find((s) => s.style_id === id)?.name ?? id
const searchable = computed(() => props.results.map((item) => ({
  item, text: [item.id, item.image_name, ...(item.object_names ?? []), ...(item.style_names ?? []), ...(item.style_ids ?? [])].join(' ').toLowerCase(),
})))
const filtered = computed(() => searchable.value.filter(({ item, text }) => {
  if (search.value.trim() && !text.includes(search.value.trim().toLowerCase())) return false
  if (branch.value !== 'all' && !(item.branches ?? []).includes(branch.value as 'ID' | 'CMF')) return false
  if (source.value !== 'all' && item.source_kind !== source.value) return false
  if (status.value === 'valid' && item.object_count === 0) return false
  if (status.value === 'failed' && item.object_count !== 0) return false
  if (status.value === 'partial' && item.status !== 'partial') return false
  if (style.value !== 'all' && !(item.style_ids ?? []).includes(style.value) && !(item.style_names ?? []).includes(styleName(style.value))) return false
  return true
}).map(({ item }) => item))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const activeSummary = computed(() => props.results.find((item) => item.id === props.activeResultId))
const preview = computed(() => props.result?.preview_url || activeSummary.value?.preview_url || '')
const activeCard = computed(() => props.result?.cards.find((card) => card.card_id === cardId.value) ?? props.result?.cards[0])
// null 表示未显式覆盖模型默认值；缺失字段才表示历史记录没有登记。
const requestedEffort = computed(() => activeCard.value?.provenance.reasoning_effort === undefined
  ? props.result?.execution.reasoning_effort : activeCard.value.provenance.reasoning_effort)
const sourceEntries = computed(() => activeCard.value?.sources ?? props.result?.source.sources ?? [])
const relations: Array<{ key: keyof PreparedDesignCard['relations']; label: string; number: string }> = [
  { key: 'palette', label: '配色组织', number: '01' }, { key: 'silhouette', label: '廓形与比例', number: '02' },
  { key: 'planes', label: '块面与体量', number: '03' }, { key: 'lines', label: '线条关系', number: '04' },
  { key: 'optics', label: '可见光学质感', number: '05' }, { key: 'texture', label: '纹理与图案', number: '06' },
  { key: 'details', label: '构造与细节', number: '07' },
]
watch([search, branch, status, source, style], () => { page.value = 1 })
watch(() => props.activeResultId, (id) => { if (id) detailOpen.value = true })
watch(() => props.result?.id, () => { cardId.value = ''; rawOpen.value = false })
watch(() => props.results.length, () => { page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / pageSize))) })
function select(id: string) { detailOpen.value = true; emit('select', id) }
function statusLabel(item: PreparedResultSummary) {
  if (item.object_count === 0) return '无有效卡'
  return item.status === 'partial' ? '部分对象有效' : '有有效卡'
}
const qualityLabel = (level: string) => ({ strong: '表达鲜明', considered: '有明确设计组织', ordinary: '常规表达', uncertain: '证据不确定' }[level] ?? level)
const formatDate = (value?: string) => value ? new Date(value).toLocaleString('zh-CN') : '未登记'
const displayError = (error: unknown) => typeof error === 'string' ? error : JSON.stringify(error, null, 2)
const sourceUrl = (value?: string) => value && /^https?:\/\//i.test(value) ? value : undefined
const cardScope = (card: PreparedDesignCard) => card.display_scope === 'whole_object' ? '整对象视窗' : '代表性局部'
const reasoningEffortLabel = (value?: string | null) => value === null || value === 'model_default' || value === 'default' ? '按模型默认' : value || '未登记'
</script>

<template>
  <section class="workspace-card prepared-results" id="results">
    <div class="prepared-heading">
      <div><span class="eyebrow">DESIGN DNA / 设计卡图库</span><h2>从图片，看见具体的设计关系</h2><p>逐对象查看 ID 与 CMF，保留可见依据、未知项和反向信号。</p></div>
      <a-button @click="emit('refresh')" aria-label="刷新设计卡结果"><ReloadOutlined /> 刷新结果</a-button>
    </div>
    <div v-if="coverage" class="coverage-grid" data-testid="preparation-coverage">
      <div><strong>{{ coverage.counts.images.toLocaleString() }}</strong><span>历史冻结原图</span></div>
      <div><strong>{{ coverage.counts.observed.toLocaleString() }}</strong><span>至少一张有效卡的图片</span></div>
      <div><strong>{{ coverage.counts.cards.toLocaleString() }}</strong><span>对象设计卡 · ID {{ coverage.counts.cards_by_branch.ID }} / CMF {{ coverage.counts.cards_by_branch.CMF }}</span></div>
      <div class="coverage-gap"><strong>{{ coverage.counts.failed }}</strong><span>无有效卡 · 待处理 {{ coverage.counts.pending }}</span></div>
    </div>
    <p class="coverage-note">{{ coverage?.coverage_limit || '每图最多 1 个 ID、2 个 CMF；不代表穷尽全部对象。' }} 有效卡表示结构与追溯可消费，视觉准确性和人工批准另行判断。<span v-if="coverage?.new_extractions"> 网页新增 {{ coverage.new_extractions }} 条记录，已并入下方图库。</span></p>
    <a-alert v-if="coverage?.unavailable_new_results?.length" type="warning" show-icon :message="`${coverage.unavailable_new_results.length} 条新增结果暂时无法读取`" class="unavailable-results">
      <template #description><ul><li v-for="item in coverage.unavailable_new_results" :key="item.id"><code>{{ item.id }}</code>：{{ item.error }}</li></ul></template>
    </a-alert>
    <div class="prepared-filters">
      <a-input v-model:value="search" allow-clear placeholder="搜索图片、对象或风格" aria-label="搜索图片、对象或风格" data-testid="preparation-search"><template #prefix><SearchOutlined /></template></a-input>
      <a-select v-model:value="branch" aria-label="按设计分支筛选" data-testid="preparation-branch-filter" :options="[{ value: 'all', label: '全部分支' }, { value: 'ID', label: 'ID · 形态构造' }, { value: 'CMF', label: 'CMF · 表面色彩' }]" />
      <a-select v-model:value="status" aria-label="按设计卡状态筛选" data-testid="preparation-status-filter" :options="[{ value: 'all', label: '全部状态' }, { value: 'valid', label: '有有效卡' }, { value: 'partial', label: '部分对象有效' }, { value: 'failed', label: '无有效卡' }]" />
      <a-select v-model:value="source" aria-label="按素材来源筛选" data-testid="preparation-source-filter" :options="[{ value: 'all', label: '全部来源' }, { value: 'trend', label: '趋势素材' }, { value: 'upload', label: '上传素材' }]" />
      <a-select v-model:value="style" show-search option-filter-prop="label" :options="styleOptions" aria-label="按同层风格筛选" data-testid="preparation-style-filter" />
    </div>
    <div class="gallery-caption"><span>共 {{ filtered.length.toLocaleString() }} 张图片<span v-if="filtered.length !== results.length"> / {{ results.length.toLocaleString() }} 张</span></span><span>点击图片查看设计卡与原图</span></div>
    <div v-if="!filtered.length" class="prepared-empty"><strong>没有符合条件的图片</strong><p>调整关键词或筛选条件后再试。</p></div>
    <div v-else class="prepared-gallery">
      <article v-for="item in visible" :key="item.id" class="gallery-card" data-testid="preparation-gallery-item">
        <button class="gallery-select" type="button" :aria-label="`查看 ${item.image_name} 的设计卡`" @click="select(item.id)">
          <div class="gallery-image"><img :src="item.preview_url" :alt="item.image_name" loading="lazy" decoding="async" /><span class="image-source">{{ item.source_kind === 'research' ? '用研' : item.source_kind === 'trend' ? '趋势' : '上传' }}</span><span class="image-open"><ExpandOutlined /> 查看</span></div>
          <div class="gallery-copy"><div class="gallery-status"><span :class="{ 'no-cards': item.object_count === 0, partial: item.status === 'partial' }">{{ statusLabel(item) }}</span><small>{{ item.card_count ?? item.object_count }} 张卡</small></div><h3>{{ item.image_name }}</h3><p>{{ item.object_names?.join(' · ') || '保留原图和处理记录' }}</p><div class="gallery-branches"><span v-for="b in item.branches" :key="b">{{ b }}</span><small>{{ item.style_names?.slice(0, 2).join(' / ') || '未登记风格候选' }}</small></div></div>
        </button>
      </article>
    </div>
    <div v-if="filtered.length" class="prepared-pagination"><a-pagination v-model:current="page" :page-size="pageSize" :total="filtered.length" :show-size-changer="false" show-quick-jumper :show-total="(total: number) => `共 ${total} 张`" /></div>
  </section>

  <a-drawer v-model:open="detailOpen" width="min(1180px, 100vw)" :title="result?.image_name || activeSummary?.image_name || '设计卡详情'" class="prepared-detail-drawer" :keyboard="true" :destroy-on-close="true">
    <a-spin :spinning="loading">
      <div v-if="result" class="prepared-detail" data-testid="preparation-detail">
        <div class="detail-notice"><strong>{{ result.cards.length ? `本图 ${result.cards.length} 张有效设计卡` : '本图没有有效设计卡' }}</strong><span>{{ result.validation.note || '保留原生提取结果；不表示视觉审阅或人工批准。' }}</span></div>
        <div v-if="result.invalid_objects.length" class="invalid-objects"><h3>对象错误与处理缺口</h3><p v-for="(error, index) in result.invalid_objects" :key="index">{{ displayError(error) }}</p></div>
        <div v-if="!result.cards.length" class="empty-card-original"><button type="button" @click="originalOpen = true"><img :src="preview" :alt="result.image_name" /><span><ExpandOutlined /> 查看原图</span></button><p>没有有效卡不等于图片没有设计价值；本图的错误记录完整保留。</p></div>
        <div v-if="result.cards.length" class="object-switcher" aria-label="切换对象设计卡"><button v-for="card in result.cards" :key="card.card_id" type="button" :class="{ active: activeCard?.card_id === card.card_id }" @click="cardId = card.card_id"><b>{{ card.branch }}</b><span>{{ card.category }}</span></button></div>
        <template v-if="activeCard">
          <article class="object-overview" data-testid="preparation-card">
            <div class="object-visual"><button class="crop-open" type="button" aria-label="放大查看完整原图" @click="originalOpen = true"><PreparedImageCrop :key="activeCard.card_id" :src="preview" :bbox="activeCard.display_bbox" :alt="`${activeCard.subject.identity} · ${cardScope(activeCard)}`" /><span><ExpandOutlined /> 查看完整原图</span></button><small>按冻结展示框呈现 · {{ cardScope(activeCard) }}</small></div>
            <div class="object-copy"><span class="object-branch">{{ activeCard.branch }} · {{ activeCard.category }}</span><h2>{{ activeCard.subject.identity }}</h2><p>{{ activeCard.crop_reason }}</p><p class="whole-state">对象完整可见：{{ activeCard.subject.whole_visible ? '是' : '否，画外部分未知' }}</p><dl class="bbox-list"><dt>展示框</dt><dd>{{ activeCard.display_bbox.join(', ') }}</dd><dt>对象框</dt><dd>{{ activeCard.subject.bbox.join(', ') }}</dd><dt>事实框</dt><dd>{{ activeCard.evidence_bbox.join(', ') }}</dd></dl><small>原图归一化 xywh：左、上、宽、高。</small></div>
          </article>
          <section class="card-section"><div class="detail-section-heading"><h3>七组可见设计关系</h3><span>事实 · 证据 · 未知</span></div><div class="relation-grid"><article v-for="group in relations" :key="group.key" class="relation-card"><div class="relation-title"><span>{{ group.number }}</span><h4>{{ group.label }}</h4><b v-if="activeCard.relations[group.key].unknown" class="unknown-badge">存在未知</b></div><p>{{ activeCard.relations[group.key].observation }}</p><ul><li v-for="(evidence, index) in activeCard.relations[group.key].evidence" :key="index">{{ evidence }}</li></ul></article></div></section>
          <section class="card-section"><div class="detail-section-heading"><h3>同层风格候选</h3><span>支持与冲突并列，不设主风格</span></div><p v-if="!activeCard.style_candidates.length">当前对象没有可支持的风格候选。</p><div class="style-card-grid"><article v-for="candidate in activeCard.style_candidates" :key="candidate.style_id" class="style-candidate"><h4>{{ styleName(candidate.style_id) }}</h4><small>{{ candidate.style_id }} · 匹配分 {{ candidate.match_score }} · 置信度 {{ candidate.confidence }}</small><h5>可见支持</h5><ul><li v-for="(entry, index) in candidate.main_support" :key="index">{{ entry }}</li></ul><h5 class="counter-title">冲突与边界</h5><ul><li v-for="(entry, index) in candidate.main_conflicts" :key="index">{{ entry }}</li></ul><p v-if="!candidate.main_conflicts.length" class="empty-note">未登记冲突信号，不表示没有冲突。</p></article></div><p class="section-footnote">分数是本次单对象推断，不是校准概率，也不证明图片之间适合组板。</p></section>
          <section class="card-section emotion-quality"><article><h3>设计情绪</h3><p class="emotion-expression">{{ activeCard.design_emotion.expression }}</p><p>{{ activeCard.design_emotion.coordination_reason }}</p><h4>反向信号</h4><ul><li v-for="(signal, index) in activeCard.design_emotion.counter_signals" :key="index">{{ signal }}</li></ul><p v-if="!activeCard.design_emotion.counter_signals.length" class="empty-note">未登记反向信号。</p></article><article><h3>设计感依据</h3><span class="quality-label">{{ qualityLabel(activeCard.design_quality.level) }}</span><ul><li v-for="(evidence, index) in activeCard.design_quality.evidence" :key="index">{{ evidence }}</li></ul><p class="section-footnote">设计表达的单图推断，不等于品质验收或人工通过。</p></article></section>
          <section class="limitations card-section"><h3>证据能力与限制</h3><ul><li v-for="(limit, index) in activeCard.limitations" :key="index">{{ limit }}</li></ul><p v-if="!activeCard.limitations.length">原卡未登记补充限制；不能据此推断全部细节可辨。</p></section>
        </template>
        <section class="card-section"><h3>素材来源</h3><div v-for="(entry, index) in sourceEntries" :key="index" class="source-entry"><a v-if="sourceUrl(entry.article_url)" :href="sourceUrl(entry.article_url)" target="_blank" rel="noopener noreferrer">{{ entry.title || entry.source_id || '查看来源文章' }} ↗</a><strong v-else>{{ entry.title || entry.source_id || '来源记录' }}</strong><span v-if="entry.publisher">{{ entry.publisher }}</span></div><p v-if="!sourceEntries.length">当前记录没有公开文章链接。</p></section>
        <details class="trace-section" data-testid="preparation-provenance"><summary>提取与来源追溯</summary><dl><dt>Skill</dt><dd>{{ result.skill }}</dd><dt>图片 ID</dt><dd>{{ result.source.image_id }}</dd><dt>原图 SHA256</dt><dd><code>{{ result.source.image_sha256 }}</code></dd><dt>请求模型</dt><dd>{{ activeCard?.provenance.requested_model || result.execution.model_id }} / {{ reasoningEffortLabel(requestedEffort) }}</dd><dt>实际模型回执</dt><dd>{{ activeCard?.provenance.actual_model || result.execution.actual_model || '未单独登记，不补写' }}</dd><dt>本条 Prompt</dt><dd>{{ activeCard?.provenance.prompt_version || result.execution.prompt_version || '未登记' }}</dd><dt>执行时间</dt><dd>{{ formatDate(activeCard?.provenance.assessed_at ?? result.execution.started_at ?? result.created_at) }}</dd><template v-if="activeCard"><dt>原答指针</dt><dd><code>{{ activeCard.provenance.pointer }}</code></dd><dt>原答 SHA256</dt><dd><code>{{ activeCard.provenance.answer_ref.sha256 }}</code></dd><dt>Prompt SHA256</dt><dd><code>{{ activeCard.provenance.prompt_ref.sha256 }}</code></dd><dt>回执 SHA256</dt><dd><code>{{ activeCard.provenance.receipt_ref.sha256 }}</code></dd></template><dt>当前新提取 Prompt</dt><dd>{{ coverage?.current_prompt_version || '以本次冻结任务为准' }}</dd></dl><p>历史设计卡保留原始提取版本；当前规则更新不会回写旧事实。</p><a-button size="small" @click="rawOpen = !rawOpen">{{ rawOpen ? '收起原生 JSON' : '查看原生 JSON' }}</a-button><pre v-if="rawOpen">{{ JSON.stringify(result, null, 2) }}</pre></details>
      </div>
      <div v-else-if="!loading" class="prepared-empty"><strong>详情暂未加载</strong><p>关闭后重新点击图片再试。</p></div>
      <div v-else class="detail-loading">正在读取对象设计卡…</div>
    </a-spin>
  </a-drawer>
  <a-modal v-model:open="originalOpen" :title="result?.image_name || '完整原图'" width="min(1100px, calc(100vw - 24px))" :footer="null" centered :keyboard="true" :z-index="1200" :destroy-on-close="true"><img v-if="originalOpen" class="prepared-original" :src="preview" :alt="result?.image_name || '完整原图'" data-testid="preparation-original" /><p class="original-note">完整原图 · 放大不增加原始图像的证据能力</p></a-modal>
</template>

<style scoped>
.prepared-results { margin: 0 0 28px; }
.prepared-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; }
.prepared-heading h2 { margin: 10px 0; font-size: 26px; color: #2e2844; letter-spacing: -.03em; }
.prepared-heading p { margin: 0; color: #858093; font-size: 13px; }
.coverage-grid { display: grid; grid-template-columns: .8fr 1.1fr 1.6fr .9fr; gap: 18px; padding: 24px 0 17px; margin-top: 18px; border-top: 1px solid #eeebf5; }
.coverage-grid > div { display: grid; gap: 5px; }
.coverage-grid strong { color: #5145af; font-size: 29px; font-weight: 600; font-variant-numeric: tabular-nums; }
.coverage-grid span { color: #7a738a; font-size: 11px; }
.coverage-gap strong { color: #9b7852; }
.coverage-note { padding: 12px 15px; color: #8a8198; font-size: 11px; line-height: 1.8; background: #f7f5fb; border-radius: 9px; }
.unavailable-results { margin-top: 14px; overflow-wrap: anywhere; }
.unavailable-results ul { margin: 0; padding-left: 18px; }
.prepared-filters { display: grid; grid-template-columns: minmax(190px, 1.5fr) repeat(3, minmax(115px, .8fr)) minmax(140px, 1fr); gap: 10px; margin: 22px 0 16px; }
.gallery-caption { display: flex; justify-content: space-between; color: #8e889b; font-size: 11px; margin-bottom: 16px; }
.prepared-gallery { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.gallery-card { position: relative; min-width: 0; border: 1px solid #eeeaf5; border-radius: 15px; overflow: hidden; background: white; transition: border-color .15s, box-shadow .15s; }
.gallery-card:hover { border-color: #c7bfe5; box-shadow: 0 7px 24px #4f3c8720; }
.gallery-select { display: block; width: 100%; padding: 0; border: 0; background: transparent; text-align: left; cursor: pointer; }
.gallery-select:focus-visible { outline: 3px solid #7667d5; outline-offset: -3px; }
.gallery-image { position: relative; height: 188px; background: #f4f2f7; }
.gallery-image img { width: 100%; height: 100%; object-fit: contain; }
.image-source { position: absolute; top: 10px; left: 10px; padding: 3px 7px; color: #60576f; background: #ffffffdf; border-radius: 5px; font-size: 10px; }
.image-open { position: absolute; bottom: 9px; right: 9px; padding: 5px 8px; color: #fff; background: #322347a8; border-radius: 6px; font-size: 10px; opacity: 0; transition: opacity .15s; }
.gallery-select:hover .image-open, .gallery-select:focus .image-open { opacity: 1; }
.gallery-copy { padding: 12px 13px 14px; }
.gallery-status { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.gallery-status > span { color: #5f6387; background: #eff0fa; font-size: 9px; padding: 2px 6px; border-radius: 4px; }
.gallery-status > span.no-cards, .gallery-status > span.partial { background: #fff3df; color: #9c7140; }
.gallery-status small { font-size: 10px; color: #918a9d; }
.gallery-copy h3 { margin: 9px 0 6px; color: #3b354a; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gallery-copy p { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 34px; margin: 0; font-size: 11px; color: #8a8296; line-height: 1.6; }
.gallery-branches { display: flex; gap: 4px; align-items: center; margin-top: 10px; min-width: 0; }
.gallery-branches > span { color: #7566ad; background: #f4f0fc; border-radius: 4px; padding: 2px 5px; font-size: 9px; }
.gallery-branches small { margin-left: 3px; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; color: #9e96aa; font-size: 9px; }
.prepared-pagination { display: flex; justify-content: center; margin: 28px 0 0; }
.prepared-empty { text-align: center; padding: 55px 20px; color: #8b819c; }
.prepared-empty strong { color: #5d526e; }
.prepared-detail { display: grid; gap: 23px; min-width: 0; }
.detail-notice { display: grid; gap: 7px; padding: 16px 18px; border-radius: 11px; color: #675c84; background: #f6f3fb; font-size: 12px; }
.detail-notice strong { color: #534574; }
.object-switcher { display: flex; flex-wrap: wrap; gap: 9px; }
.object-switcher button { display: flex; gap: 9px; align-items: center; border: 1px solid #e7e0f2; border-radius: 9px; padding: 10px 12px; background: #fff; color: #82758f; font-size: 12px; text-align: left; cursor: pointer; }
.object-switcher button.active { color: #5b46a3; background: #f5f0fe; border-color: #b8a5de; }
.object-overview { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 24px; align-items: start; padding: 20px; border: 1px solid #eae4f3; border-radius: 15px; }
.object-visual { min-width: 0; }
.object-visual > small { display: block; color: #9a8fa9; font-size: 10px; margin-top: 9px; }
.crop-open { display: block; position: relative; width: 100%; max-height: 480px; overflow: auto; padding: 0; border: 0; background: #f6f3fa; border-radius: 12px; cursor: zoom-in; }
.crop-open > span { position: sticky; display: block; bottom: 0; padding: 7px; text-align: center; color: #7d6a9a; background: #f7f3fcf2; font-size: 11px; }
.object-copy { min-width: 0; }
.object-branch { color: #85719e; font-size: 11px; }
.object-copy h2 { margin: 10px 0 13px; color: #3b2d50; font-size: 22px; line-height: 1.5; }
.object-copy p { color: #84758e; font-size: 12px; line-height: 1.9; }
.object-copy .whole-state { color: #aa8465; }
.bbox-list { display: grid; grid-template-columns: 55px minmax(0, 1fr); gap: 6px 10px; color: #93869f; font-size: 11px; }
.bbox-list dd { margin: 0; font-variant-numeric: tabular-nums; }
.object-copy > small { color: #a499ae; font-size: 10px; }
.card-section { min-width: 0; }
.card-section h3 { margin: 0 0 13px; font-size: 16px; color: #4c3d62; }
.detail-section-heading { display: flex; justify-content: space-between; gap: 14px; align-items: baseline; }
.detail-section-heading > span { color: #a193ac; font-size: 10px; }
.relation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.relation-card { padding: 17px; border: 1px solid #eee8f4; border-radius: 11px; }
.relation-title { display: flex; align-items: center; gap: 8px; }
.relation-title > span { font-size: 10px; color: #ac9cbf; }
.relation-title h4 { margin: 0; font-size: 13px; color: #655278; }
.unknown-badge { margin-left: auto; color: #ad855d; background: #fff4e5; padding: 3px 5px; font-size: 9px; border-radius: 4px; }
.relation-card p { color: #74637f; line-height: 1.9; font-size: 12px; margin: 11px 0; }
.prepared-detail ul { padding-left: 17px; margin: 10px 0 0; color: #9989a5; font-size: 11px; line-height: 1.9; }
.prepared-detail li + li { margin-top: 5px; }
.style-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.style-candidate { padding: 18px; background: #f9f7fc; border-radius: 11px; }
.style-candidate h4 { color: #654c87; margin: 0 0 7px; font-size: 15px; }
.style-candidate > small { color: #ac9db9; font-size: 10px; }
.style-candidate h5 { color: #8c769d; margin: 16px 0 0; font-size: 11px; }
.style-candidate .counter-title { color: #af8e71; }
.section-footnote, .empty-note { color: #ab9bb8; font-size: 10px; line-height: 1.8; margin: 10px 0 0; }
.emotion-quality { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.emotion-quality article { padding: 18px; background: #faf8fd; border-radius: 11px; }
.emotion-quality p { color: #907e9e; font-size: 12px; line-height: 1.9; }
.emotion-quality .emotion-expression { color: #74578e; font-size: 15px; }
.emotion-quality h4 { margin: 18px 0 0; font-size: 11px; color: #ae8a70; }
.quality-label { display: inline-block; padding: 5px 10px; border-radius: 6px; color: #8664a0; background: #eee6f6; font-size: 11px; }
.limitations { border-left: 3px solid #dcc4a8; padding: 14px 18px; border-radius: 0 10px 10px 0; background: #fcf8f2; }
.limitations h3 { color: #9d805f; font-size: 14px; }
.limitations ul { color: #ac947e; }
.source-entry { display: grid; gap: 4px; padding: 10px 0; border-bottom: 1px solid #f1edf5; font-size: 12px; }
.source-entry span { color: #ab9ab8; font-size: 10px; }
.source-entry a { color: #8863a8; overflow-wrap: anywhere; }
.trace-section { border: 1px solid #e9e0f0; border-radius: 11px; padding: 16px; color: #9984a8; font-size: 11px; }
.trace-section summary { color: #7b6290; cursor: pointer; font-size: 12px; }
.trace-section dl { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 10px 15px; margin: 20px 0; }
.trace-section dd { margin: 0; overflow-wrap: anywhere; }
.trace-section code { font-size: 10px; word-break: break-all; }
.trace-section pre { max-height: 500px; overflow: auto; background: #f8f5fc; padding: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
.invalid-objects { padding: 16px; border-radius: 10px; color: #a27f58; background: #fff6e9; }
.invalid-objects h3 { font-size: 14px; margin: 0 0 8px; }
.invalid-objects p { font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.empty-card-original button { display: grid; gap: 8px; max-width: 500px; width: 100%; padding: 12px; border: 1px solid #e7def0; border-radius: 10px; color: #887096; background: #fbf9fd; cursor: zoom-in; }
.empty-card-original img { max-width: 100%; max-height: 400px; margin: auto; }
.empty-card-original p { font-size: 12px; color: #aa97b6; }
.prepared-original { display: block; width: 100%; height: auto; max-height: 76vh; object-fit: contain; }
.original-note { margin: 10px 0 0; text-align: center; color: #9f8cae; font-size: 11px; }
.detail-loading { min-height: 300px; padding: 70px 15px; text-align: center; color: #aa9ab5; }
@media (max-width: 1000px) { .prepared-filters { grid-template-columns: repeat(3, minmax(0, 1fr)); } .prepared-filters > :first-child { grid-column: span 2; } .prepared-gallery { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .prepared-results { padding: 20px 16px; } .prepared-heading { display: block; } .prepared-heading h2 { font-size: 22px; } .prepared-heading > button { margin-top: 15px; } .coverage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 14px; } .coverage-grid strong { font-size: 25px; } .prepared-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } .prepared-filters > :first-child { grid-column: 1 / -1; } .prepared-gallery { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .gallery-image { height: 150px; } .gallery-copy { padding: 10px; } .gallery-copy h3 { font-size: 11px; } .gallery-branches { flex-wrap: wrap; } .gallery-branches small { width: 100%; margin: 3px 0 0; } .gallery-caption { gap: 8px; font-size: 10px; } .prepared-pagination { overflow: auto; justify-content: flex-start; } .object-overview, .relation-grid, .style-card-grid, .emotion-quality { grid-template-columns: 1fr; } .object-overview { padding: 14px; gap: 16px; } .object-copy h2 { font-size: 20px; } .detail-section-heading { display: block; } .detail-section-heading > span { display: block; margin: -5px 0 12px; } .trace-section dl { grid-template-columns: 1fr; gap: 4px; } .trace-section dd { margin-bottom: 8px; } .object-switcher button { width: 100%; } }
</style>
