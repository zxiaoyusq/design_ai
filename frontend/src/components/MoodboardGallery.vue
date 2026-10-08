<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MoodboardDnaSummary } from '@/types/moodboards'

const props = defineProps<{ resultIds: string[]; images: Map<string, MoodboardDnaSummary>; curated?: boolean }>()
const emit = defineEmits<{ inspect: [id: string] }>()
const page = ref(1)
const pageSize = 12
// 每组只挂载当前页缩略图，100 张以上结果也不会一次请求所有原图。
const visibleIds = computed(() => props.resultIds.slice((page.value - 1) * pageSize, page.value * pageSize))
watch(() => props.resultIds, () => { page.value = 1 })
</script>

<template>
  <div class="moodboard-gallery" :class="{ curated }">
    <div class="gallery-grid" :style="curated ? { '--collage-columns': resultIds.length <= 6 ? 3 : 4 } : undefined">
      <button v-for="id in visibleIds" :key="id" class="gallery-item" type="button" :aria-label="`查看 ${images.get(id)?.image_name ?? id} 的归属理由与 DNA 证据`" :title="images.get(id)?.image_name ?? id" @click="emit('inspect', id)">
        <img v-if="images.get(id)?.preview_url" :src="images.get(id)?.preview_url ?? undefined" :alt="images.get(id)?.image_name ?? id" loading="lazy" />
        <span v-else class="image-placeholder">暂无预览</span>
        <strong>{{ images.get(id)?.image_name ?? id }}</strong>
        <small>查看归属理由与 DNA 证据</small>
      </button>
    </div>
    <a-pagination v-if="resultIds.length > pageSize" v-model:current="page" :page-size="pageSize" :total="resultIds.length" :show-size-changer="false" size="small" />
  </div>
</template>

<style scoped>
.gallery-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.gallery-item { min-width: 0; padding: 8px; text-align: left; background: #fff; border: 1px solid #ece8f3; border-radius: 12px; cursor: pointer; }
.gallery-item:hover, .gallery-item:focus-visible { border-color: #8b7bd0; }
.gallery-item img, .image-placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 140px; object-fit: contain; background: #f8f7fa; border-radius: 8px; }
.gallery-item strong { display: block; margin-top: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #514762; font-size: 12px; }
.gallery-item small, .image-placeholder { color: #91899d; font-size: 11px; }
.curated .gallery-grid { grid-template-columns: repeat(var(--collage-columns), minmax(0, 1fr)); gap: 4px; padding: 4px; background: #fff; }
.curated .gallery-item { padding: 0; border-color: transparent; border-radius: 0; }
.curated .gallery-item:hover, .curated .gallery-item:focus-visible { border-color: #8b7bd0; }
.curated .gallery-item img, .curated .image-placeholder { height: 185px; background: #fff; border-radius: 0; }
.curated .gallery-item strong, .curated .gallery-item small { display: none; }
@media (max-width: 760px) { .gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .curated .gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .curated .gallery-item img { height: 145px; } }
</style>
