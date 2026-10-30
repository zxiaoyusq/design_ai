<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PreparedBbox } from '@/types/dnaV2'

const props = defineProps<{ src: string; bbox: PreparedBbox; alt: string }>()
const naturalRatio = ref(1)
const cropRatio = computed(() => naturalRatio.value * props.bbox[2] / props.bbox[3])
const cropStyle = computed(() => ({
  width: `${100 / props.bbox[2]}%`, height: `${100 / props.bbox[3]}%`,
  left: `${-props.bbox[0] / props.bbox[2] * 100}%`, top: `${-props.bbox[1] / props.bbox[3] * 100}%`,
}))
function imageLoaded(event: Event) {
  const image = event.target as HTMLImageElement
  naturalRatio.value = image.naturalWidth / image.naturalHeight
}
</script>

<template>
  <!-- xywh 坐标只改变原图视窗，不放大重绘或裁掉原卡已登记的反向信号。 -->
  <div class="prepared-crop" :style="{ aspectRatio: String(cropRatio) }">
    <img :src="src" :alt="alt" :style="cropStyle" @load="imageLoaded" />
  </div>
</template>

<style scoped>
.prepared-crop { position: relative; width: 100%; overflow: hidden; background: #efedf5; border-radius: 12px; }
.prepared-crop img { position: absolute; max-width: none; display: block; }
</style>
