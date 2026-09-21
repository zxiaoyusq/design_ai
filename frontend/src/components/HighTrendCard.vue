<script setup lang="ts">
import { computed, ref } from 'vue'
import SafeMarkdown from './SafeMarkdown.vue'
import type { HighTrendCard, TrendImage, TrendSource } from '@/types/highTrends'

const props = defineProps<{ card: HighTrendCard; index: number; supplement?: boolean }>()
const expandedGroups = ref<string[]>([])
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
    <SafeMarkdown :text="card.description" />
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
              <figcaption>{{ image.image_id || image.code || '来源图片' }}</figcaption>
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
            <figcaption>{{ image.image_id || image.code || '来源图片' }}</figcaption>
          </figure>
        </div>
        <p v-if="userImages.length > availableImages(userImages).length" class="stat-note">{{ userImages.length - availableImages(userImages).length }} 张引用图片没有可用本地文件，保留文字来源。</p>
        <a-button v-if="availableImages(userImages).length > 6" type="link" size="small" @click="toggleImages('user-research')">{{ expandedGroups.includes('user-research') ? '收起图片' : `查看全部 ${availableImages(userImages).length} 张可用图片` }}</a-button>
      </div>
    </a-image-preview-group>
    <p v-if="!card.image_refs.length" class="stat-note">当前引用没有可关联图片。</p>
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
          <code>{{ source.source_path }}{{ source.json_pointer ? ` · ${source.json_pointer}` : '' }}</code>
        </section>
      </div>
    </details>
    <div class="review-note">待人工复核</div>
  </article>
</template>

<style scoped>
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
