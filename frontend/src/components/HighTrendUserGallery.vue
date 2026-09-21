<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UserResearchImage } from '@/types/highTrends'

const props = defineProps<{
  images: UserResearchImage[]
  positiveOnly?: boolean
  scopeNote?: string
}>()
const page = ref(1)
const filter = ref('all')
const selected = computed(() => props.images.filter(image => filter.value === 'all' || (filter.value === 'linked' ? image.linked_to_result : !image.linked_to_result)))
const visible = computed(() => selected.value.slice((page.value - 1) * 24, page.value * 24))
watch(filter, () => { page.value = 1 })
watch(() => props.images.length, () => { page.value = 1 })
/** 仅加载后端分配的图片接口，分页避免同时请求上千张图片。 */
function safeUrl(image: UserResearchImage) {
  return image.file_exists && image.url && /^\/api\/v1\/high-trends\/tasks\/[^/]+\/images\/\d+(?:\?v=[a-f0-9]{16})?$/.test(image.url) ? image.url : undefined
}
</script>

<template>
  <section class="user-gallery">
    <div class="gallery-heading"><div><h2>{{ positiveOnly ? '用户喜欢的图片' : '用户图片资料' }} <span>{{ images.length }}</span></h2><p>{{ scopeNote || (positiveOnly ? '仅展示明确标记 LIKE / ENJOY 的图片；未关联方向的图片仅提供资料入口，本轮未读取图片内容。' : '包含结果引用与已选用户的补充附件。附件仅提供资料入口，不代表已支持某个结论；本轮未读取图片内容。') }}</p></div></div>
    <div class="gallery-controls"><a-radio-group v-model:value="filter" button-style="solid"><a-radio-button value="all">{{ positiveOnly ? '全部喜欢图片' : '全部图片' }}</a-radio-button><a-radio-button value="linked">结果关联</a-radio-button><a-radio-button value="attachments">{{ positiveOnly ? '其他喜欢图片' : '补充附件' }}</a-radio-button></a-radio-group><span>{{ selected.length }} 张 · 每页 24 张</span></div>
    <a-image-preview-group>
      <div class="gallery-grid">
        <figure v-for="item in visible" :key="item.path">
          <a-image v-if="safeUrl(item)" :src="safeUrl(item)" :alt="item.image_ids?.[0] || '用户研究图片'" loading="lazy" width="100%" :height="146" />
          <div v-else class="unavailable">本地图片不可用</div>
          <figcaption><span :class="{ linked: item.linked_to_result }">{{ item.linked_to_result ? '结果关联' : (positiveOnly ? 'LIKE / ENJOY' : '补充附件') }}</span><p>用户 {{ item.user_ids.join('、') }}</p><details><summary>本地路径</summary><code>{{ item.path }}</code></details></figcaption>
        </figure>
      </div>
    </a-image-preview-group>
    <p v-if="!selected.length" class="gallery-empty">当前筛选没有图片。</p>
    <a-pagination v-if="selected.length > 24" v-model:current="page" :total="selected.length" :page-size="24" :show-size-changer="false" show-less-items />
  </section>
</template>

<style scoped>
.user-gallery { margin-top: 32px; padding: 24px; background: #fff; border: 1px solid #e8e3f2; border-radius: 20px; }
h2 { margin: 0; color: #5b486c; font-size: 20px; } h2 span { color: #ad9cbd; margin-left: 8px; font-size: 16px; }
.gallery-heading p { color: #92819f; font-size: 12px; line-height: 1.8; }
.gallery-controls { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 20px 0; }
.gallery-controls > span { color: #9a8ca5; font-size: 11px; }
.gallery-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 24px; }
figure { min-width: 0; margin: 0; border: 1px solid #eee8f3; border-radius: 12px; overflow: hidden; }
:deep(.ant-image-img) { object-fit: contain; background: #f8f6fa; }
figcaption { padding: 12px; font-size: 11px; color: #8e7c9e; } figcaption > span { border-radius: 6px; padding: 3px 6px; background: #f3f0f7; }
figcaption > .linked { background: #eaf4ec; color: #578265; }
figcaption p { margin: 10px 0; } details { font-size: 10px; } summary { cursor: pointer; } code { display: block; margin-top: 8px; overflow-wrap: anywhere; line-height: 1.7; }
.unavailable { display: grid; height: 146px; place-items: center; background: #f7f4f9; color: #9e91aa; font-size: 11px; }
.gallery-empty { color: #9e91aa; font-size: 12px; }
@media(max-width: 1050px) { .gallery-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media(max-width: 600px) { .gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .user-gallery { padding: 16px; } }
</style>
