<script setup lang="ts">
import { computed, ref } from 'vue'
import SafeMarkdown from './SafeMarkdown.vue'
import type { HighTrendCard, TrendImage, TrendSource } from '@/types/highTrends'

const props = defineProps<{ card: HighTrendCard; index: number; supplement?: boolean }>()
const expandedGroups = ref<string[]>([])
const associatedOpen = ref(false)
const associatedSourceLimit = ref(8)
const associatedImageLimits = ref<Record<string, number>>({})
const relationLabel = computed(() => ({
  direct_support: '直接支持', anchored_extension: '有依据的延展', exploratory_hypothesis: '探索假设', unknown: '未分级',
}[props.card.relation_basis ?? 'unknown']))
// 已有结构化分级在专属区域展示，正文不重复暴露模型枚举和同一组边界。
const displayDescription = computed(() => props.card.relation_basis
  ? props.card.description.split('\n').filter(line => !/^\s*(?:[-*]\s+)?(?:\*\*)?(?:依据类型|共同原则|适用边界|反向与未决)(?:\*\*)?\s*[:：]/.test(line)).join('\n')
  : props.card.description)
function semanticText(context: Record<string, unknown>) {
  return JSON.stringify(context, null, 2)
}
function isTrendImage(image: TrendImage) {
  return image.kind === 'trend' || image.role === 'trend_reference'
    || props.card.source_records.some(source => source.record_id === image.source_record_id && source.kind === 'trend')
}
const trendImages = computed(() => props.card.image_refs.filter(isTrendImage))
const userImages = computed(() => props.card.image_refs.filter(image => !isTrendImage(image)))

/** 文章引用仅说明配图的来源，不代表该文章的每张图片都经过视觉匹配。 */
const trendArticleGroups = computed(() => {
  const sources = new Map(props.card.source_records.map(source => [source.record_id, source]))
  const groups = new Map<string, { key: string; source?: TrendSource; images: TrendImage[] }>()
  for (const image of trendImages.value) {
    const key = image.source_record_id || 'unknown-trend-source'
    if (!groups.has(key)) groups.set(key, { key, source: sources.get(image.source_record_id), images: [] })
    groups.get(key)!.images.push(image)
  }
  return [...groups.values()]
})
/** 同簇资料可能有数千张图片，只在展开后分批挂载，避免隐藏图库占满 DOM。 */
const associatedGroups = computed(() => {
  const groups = new Map<string, { key: string; source?: TrendSource; images: TrendImage[] }>()
  for (const source of props.card.associated_source_records ?? []) {
    const key = source.record_id || source.short_id
    groups.set(key, { key, source, images: [] })
  }
  for (const image of props.card.associated_image_refs ?? []) {
    const key = image.source_record_id || 'unknown-associated-source'
    if (!groups.has(key)) groups.set(key, { key, images: [] })
    groups.get(key)!.images.push(image)
  }
  return [...groups.values()]
})
function toggleAssociated(event: Event) {
  associatedOpen.value = (event.target as HTMLDetailsElement).open
}
function associatedImages(key: string, images: TrendImage[]) {
  return availableImages(images).slice(0, associatedImageLimits.value[key] ?? 6)
}
function showMoreAssociatedImages(key: string) {
  associatedImageLimits.value[key] = (associatedImageLimits.value[key] ?? 6) + 12
}
function imageDetails(image: TrendImage) {
  return JSON.stringify({
    image_id: image.image_id, sha256: image.sha256, byte_size: image.byte_size,
    identity_status: image.identity_status, association_type: image.association_type,
    source_record_id: image.source_record_id, image_url: image.image_url,
  }, null, 2)
}
const sourceGroups = computed(() => [
  { title: '核心来源', sources: props.card.source_records },
  { title: '背景资料', sources: props.card.background_source_records || [] },
].filter(group => group.sources.length))

/** 图片只使用后端分配的同源接口，源文件路径和模型提供的链接不直接作为图片地址。 */
function imageUrl(image: TrendImage) {
  return image.url && /^\/api\/v1\/high-trends\/tasks\/[^/]+\/images\/\d+(?:\?v=[a-f0-9]{16})?$/.test(image.url) ? image.url : undefined
}
function imageKey(image: TrendImage, index: number) {
  return `${image.source_record_id || ''}:${image.image_id || image.code || index}:${image.url || ''}`
}
function availableImages(images: TrendImage[]) {
  return images.filter(image => image.file_exists && imageUrl(image))
}
function visibleImages(title: string, images: TrendImage[]) {
  const available = availableImages(images)
  return expandedGroups.value.includes(title) ? available : available.slice(0, 6)
}
function toggleImages(title: string) {
  expandedGroups.value = expandedGroups.value.includes(title) ? expandedGroups.value.filter(item => item !== title) : [...expandedGroups.value, title]
}
</script>

<template>
  <article class="trend-card" :class="{ supplement }">
    <div class="card-topline"><span>{{ supplement ? '用户研究补充' : '趋势 × 用户洞察' }}</span><span>{{ String(index + 1).padStart(2, '0') }}</span></div>
    <h3>{{ card.title }}</h3>
    <div v-if="card.clustering_labels?.length" class="category-labels"><a-tag v-for="label in card.clustering_labels" :key="label" color="purple">{{ label }}</a-tag></div>
    <div class="mention-pill">已引用去重用户 <strong>{{ card.mention_statistics.unique_mentioned_users }}</strong> / {{ card.mention_statistics.population_count }} 人</div>
    <div class="evidence-level"><a-tag color="purple">{{ card.relation_basis ? relationLabel : '历史结果 · 未分级' }}</a-tag><span>语义支持程度，待人工复核</span></div>
    <SafeMarkdown :text="displayDescription" />
    <dl v-if="card.shared_design_principle || card.conditions_and_limits || card.unresolved_questions" class="design-boundaries">
      <template v-if="card.shared_design_principle"><dt>共同设计原则</dt><dd><SafeMarkdown :text="card.shared_design_principle" /></dd></template>
      <template v-if="card.conditions_and_limits"><dt>成立条件与限制</dt><dd><SafeMarkdown :text="card.conditions_and_limits" /></dd></template>
      <template v-if="card.unresolved_questions"><dt>仍待确认</dt><dd><SafeMarkdown :text="card.unresolved_questions" /></dd></template>
    </dl>
    <p v-if="card.evidence_review_status" class="stat-note">这些依据尚未经过独立语义复核，保留供人工判断。</p>
    <p class="stat-note">{{ card.mention_statistics.note }}</p>
    <p v-if="card.trend_coverage_note" class="stat-note">{{ card.trend_coverage_note }}</p>
    <a-image-preview-group>
      <div v-if="trendImages.length" class="image-group">
        <h4>趋势参考 <span>{{ trendArticleGroups.length }} 篇文章 · {{ trendImages.length }} 张</span></h4>
        <p class="stat-note">按核心来源文章展示配图，未做视觉核验。</p>
        <details v-for="(group, groupIndex) in trendArticleGroups" :key="group.key" class="article-images" :open="groupIndex === 0">
          <summary>
            <span class="article-title">{{ group.source?.title || '未标明文章标题的趋势资料' }}</span>
            <span class="article-meta">{{ group.source?.short_id || group.key }} · {{ group.images.length }} 张</span>
          </summary>
          <div class="evidence-images">
            <figure v-for="(image, imageIndex) in visibleImages(group.key, group.images)" :key="imageKey(image, imageIndex)">
              <a-image :src="imageUrl(image)" :alt="`${group.source?.title || '趋势参考'} ${image.image_id || image.code || imageIndex + 1}`" :width="112" :height="96" loading="lazy" />
              <figcaption>{{ image.image_id || image.code || '来源图片' }}<details v-if="image.sha256 || image.identity_status || image.association_type || image.image_url" class="image-metadata"><summary>图片来源信息</summary><pre>{{ imageDetails(image) }}</pre></details></figcaption>
            </figure>
          </div>
          <p v-if="group.images.length > availableImages(group.images).length" class="stat-note">{{ group.images.length - availableImages(group.images).length }} 张引用图片没有可用本地文件，保留文字来源。</p>
          <a-button v-if="availableImages(group.images).length > 6" type="link" size="small" @click="toggleImages(group.key)">{{ expandedGroups.includes(group.key) ? '收起图片' : `查看本篇全部 ${availableImages(group.images).length} 张可用图片` }}</a-button>
        </details>
      </div>
      <div v-if="userImages.length" class="image-group">
        <h4>用研提及 <span>{{ userImages.length }} 张 · 来源关联，未做视觉核验</span></h4>
        <div class="evidence-images">
          <figure v-for="(image, imageIndex) in visibleImages('user-research', userImages)" :key="imageKey(image, imageIndex)">
            <a-image :src="imageUrl(image)" :alt="`用研提及 ${image.image_id || image.code || imageIndex + 1}`" :width="112" :height="96" loading="lazy" />
            <figcaption>{{ image.image_id || image.code || '来源图片' }}<details v-if="image.sha256 || image.identity_status || image.association_type || image.image_url" class="image-metadata"><summary>图片来源信息</summary><pre>{{ imageDetails(image) }}</pre></details></figcaption>
          </figure>
        </div>
        <p v-if="userImages.length > availableImages(userImages).length" class="stat-note">{{ userImages.length - availableImages(userImages).length }} 张引用图片没有可用本地文件，保留文字来源。</p>
        <a-button v-if="availableImages(userImages).length > 6" type="link" size="small" @click="toggleImages('user-research')">{{ expandedGroups.includes('user-research') ? '收起图片' : `查看全部 ${availableImages(userImages).length} 张可用图片` }}</a-button>
      </div>
    </a-image-preview-group>
    <p v-if="!card.image_refs.length" class="stat-note">当前引用没有可关联图片。</p>
    <details v-if="associatedGroups.length" class="associated-materials" @toggle="toggleAssociated">
      <summary>同簇关联资料 · {{ associatedGroups.length }} 条来源 / {{ card.associated_image_refs?.length ?? 0 }} 张图片</summary>
      <template v-if="associatedOpen">
        <p class="stat-note">这些文章与方向引用的趋势属于同一父簇，未被本方向直接引用，不作为方向成立的直接证据。图片仅做来源关联，尚未视觉核验。</p>
        <a-image-preview-group>
          <section v-for="group in associatedGroups.slice(0, associatedSourceLimit)" :key="group.key" class="associated-source">
            <h4>{{ group.source?.title || '未标明标题的同簇资料' }} <span>{{ group.images.length }} 张关联图片</span></h4>
            <details v-if="group.source" class="associated-source-text"><summary>查看来源与原文 · {{ group.source.short_id || group.key }}</summary><SafeMarkdown v-if="group.source.excerpt" :text="group.source.excerpt" /><p v-else class="stat-note">本条来源未提供原文摘要。</p><code>{{ group.source.source_path }}{{ group.source.json_pointer ? ` · ${group.source.json_pointer}` : '' }}</code><details v-if="group.source.semantic_context" class="semantic-context"><summary>原始对象、证据角色与父簇</summary><pre>{{ semanticText(group.source.semantic_context) }}</pre></details></details>
            <div class="evidence-images">
              <figure v-for="(image, imageIndex) in associatedImages(group.key, group.images)" :key="imageKey(image, imageIndex)">
                <a-image :src="imageUrl(image)" :alt="`同簇关联 · ${group.source?.title || image.image_id || '来源图片'}`" :width="112" :height="96" loading="lazy" />
                <figcaption>{{ image.image_id || image.code || '同簇图片' }}<details class="image-metadata"><summary>图片来源信息</summary><pre>{{ imageDetails(image) }}</pre></details></figcaption>
              </figure>
            </div>
            <p v-if="group.images.length > availableImages(group.images).length" class="stat-note">{{ group.images.length - availableImages(group.images).length }} 张关联图片没有可用本地文件，保留文字来源。</p>
            <a-button v-if="associatedImages(group.key, group.images).length < availableImages(group.images).length" type="link" size="small" @click="showMoreAssociatedImages(group.key)">继续显示图片（已显示 {{ associatedImages(group.key, group.images).length }} / {{ availableImages(group.images).length }}）</a-button>
          </section>
        </a-image-preview-group>
        <a-button v-if="associatedSourceLimit < associatedGroups.length" type="link" @click="associatedSourceLimit += 8">继续显示 8 条来源（已显示 {{ Math.min(associatedSourceLimit, associatedGroups.length) }} / {{ associatedGroups.length }}）</a-button>
      </template>
    </details>
    <details class="sources">
      <summary>查看 {{ card.source_records.length }} 条核心来源<span v-if="card.background_source_records?.length"> · {{ card.background_source_records.length }} 条背景资料</span>与原文</summary>
      <div v-for="group in sourceGroups" :key="group.title" class="source-group">
        <h4>{{ group.title }}</h4>
        <p v-if="group.title === '背景资料'" class="stat-note">用于理解相关背景，不作为本方向的核心依据，也不加入配图。</p>
        <section v-for="source in group.sources" :key="source.short_id" class="source-record">
          <div><a-tag :color="source.kind === 'trend' ? 'purple' : 'cyan'">{{ source.short_id }}</a-tag><strong>{{ source.title || (source.kind === 'trend' ? '趋势资料' : '用户研究') }}</strong></div>
          <p v-if="source.user_id != null" class="stat-note">用户 {{ source.user_id }}</p>
          <p v-if="source.question" class="question">{{ source.question }}</p>
          <SafeMarkdown v-if="source.excerpt" :text="source.excerpt" />
          <p v-else class="stat-note">本条来源未提供原文摘要。</p>
          <details v-if="source.semantic_context" class="semantic-context"><summary>原始对象、证据角色与父簇</summary><pre>{{ semanticText(source.semantic_context) }}</pre></details>
          <code>{{ source.source_path }}{{ source.json_pointer ? ` · ${source.json_pointer}` : '' }}</code>
        </section>
      </div>
    </details>
    <div class="review-note">待人工复核</div>
  </article>
</template>

<style scoped>
.associated-materials { margin-top: 22px; padding: 16px; border: 1px solid #e8e3f2; border-radius: 12px; background: #faf8fc; font-size: 12px; }
.associated-source { padding: 15px 0; border-bottom: 1px solid #eee9f3; }
.associated-source-text { margin-bottom: 12px; }
.associated-source-text code { font-size: 10px; color: #a095ab; overflow-wrap: anywhere; }
.image-metadata { margin-top: 5px; }
.image-metadata pre { font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 180px; overflow: auto; }

.evidence-level { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 0 0 16px; }
.evidence-level span { color: #93899f; font-size: 11px; }
.design-boundaries { padding: 15px; background: #faf8fc; border-radius: 12px; }
.design-boundaries dt { color: #685b7b; font-size: 12px; font-weight: 500; margin-top: 12px; }
.design-boundaries dt:first-child { margin-top: 0; }
.design-boundaries dd { margin: 6px 0 0; font-size: 12px; }
.semantic-context { margin: 12px 0; }
.semantic-context pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; color: #93899f; font-size: 11px; }

.trend-card { min-width: 0; padding: 28px; background: #fff; border: 1px solid #e8e3f2; border-radius: 20px; box-shadow: 0 12px 40px #4a386508; }
.card-topline { display: flex; justify-content: space-between; color: #817398; font-size: 10px; letter-spacing: .12em; }
.card-topline > span:last-child { font-size: 21px; font-family: 'DM Mono', monospace; color: #b9add3; }
h3 { margin: 10px 0 14px; font-size: 23px; line-height: 1.5; color: #352b4e; }
.mention-pill { display: inline-block; margin-bottom: 20px; padding: 7px 12px; color: #75628d; font-size: 11px; background: #f4f0fa; border-radius: 20px; }
.mention-pill strong { color: #6550a1; }
.stat-note { margin: 10px 0; color: #93899f; font-size: 11px; line-height: 1.75; }
.image-group { margin-top: 20px; }
.category-labels { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
h4 { margin: 0 0 10px; font-size: 12px; color: #685b7b; }
h4 span { margin-left: 8px; font-size: 10px; font-weight: 400; color: #a199ad; }
.evidence-images { display: flex; gap: 10px; flex-wrap: wrap; }
.article-images { margin: 8px 0; padding: 12px; background: #faf8fc; border: 1px solid #eee9f3; border-radius: 12px; }
.article-images summary { font-size: 12px; line-height: 1.7; }
.article-title { font-weight: 500; }
.article-meta { margin-left: 8px; color: #a199ad; font-size: 10px; white-space: nowrap; }
.article-images[open] summary { margin-bottom: 12px; }
figure { width: 112px; margin: 0; }
:deep(.ant-image) { overflow: hidden; border-radius: 10px; background: #f1edf6; }
:deep(.ant-image-img) { object-fit: cover; }
figcaption { margin-top: 5px; color: #958a9f; font-size: 9px; overflow-wrap: anywhere; }
.missing-image { display: grid; height: 96px; place-items: center; background: #f5f2f7; border-radius: 10px; color: #aaa0b5; font-size: 11px; }
.sources { margin-top: 22px; padding-top: 18px; border-top: 1px solid #eee9f3; font-size: 12px; }
summary { cursor: pointer; color: #76628e; }
.source-record { padding: 16px 0; border-bottom: 1px solid #f1edf6; }
.source-group { margin-top: 18px; }
.source-group h4 { margin-bottom: 0; }
.source-record strong { font-size: 12px; font-weight: 500; }
.source-record code { color: #a095ab; font-size: 10px; overflow-wrap: anywhere; }
.question { white-space: pre-wrap; font-size: 12px; line-height: 1.7; }
.review-note { color: #a59aae; font-size: 10px; margin-top: 16px; text-align: right; }
.supplement { background: #fcfdfb; border-color: #e2e9dc; }
.supplement .mention-pill { background: #edf3e8; color: #657f59; }
@media (max-width: 600px) { .trend-card { padding: 20px; } h3 { font-size: 20px; } }
</style>
