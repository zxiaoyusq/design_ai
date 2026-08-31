<script setup lang="ts">
import { ref } from 'vue'
import {
  AppstoreAddOutlined,
  CheckCircleFilled,
  FileImageOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  DeleteOutlined,
  LoadingOutlined,
} from '@ant-design/icons-vue'

import type { UploadedImage } from '@/types/dna'

const props = defineProps<{
  images: UploadedImage[]
  selectedIds: string[]
  uploading: boolean
  deletingIds: string[]
}>()

const emit = defineEmits<{
  upload: [files: File[]]
  toggle: [imageId: string]
  selectAll: []
  clear: []
  delete: [imageId: string]
}>()

const singleInput = ref<HTMLInputElement | null>(null)
const batchInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

function emitFiles(fileList: FileList | null) {
  if (!fileList) return
  const files = Array.from(fileList).filter((file) => file.type.startsWith('image/'))
  emit('upload', files)
}

function onInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  emitFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  emitFiles(event.dataTransfer?.files ?? null)
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <section class="workspace-card upload-panel">
    <div class="section-heading">
      <div>
        <span class="eyebrow">01 / 输入素材</span>
        <h2>选择需要理解的图片</h2>
        <p>每张图片独立提取一个主物品，批量任务会逐张执行。</p>
      </div>
      <div v-if="images.length" class="selection-actions">
        <button type="button" @click="emit('selectAll')">全选</button>
        <span></span>
        <button type="button" @click="emit('clear')">清空</button>
      </div>
    </div>

    <div
      class="drop-zone"
      :class="{ 'is-dragging': dragging, 'is-uploading': uploading }"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <div class="drop-icon"><InboxOutlined /></div>
      <div class="drop-copy">
        <strong>{{ uploading ? '正在整理图片…' : '拖拽图片到这里' }}</strong>
        <span>支持 JPG、PNG、WEBP、GIF，单张不超过 20 MB</span>
      </div>
      <div class="upload-methods">
        <a-button :disabled="uploading" @click="singleInput?.click()">
          <template #icon><FileImageOutlined /></template>
          单张上传
        </a-button>
        <a-button :disabled="uploading" @click="batchInput?.click()">
          <template #icon><AppstoreAddOutlined /></template>
          批量上传
        </a-button>
        <a-button :disabled="uploading" @click="folderInput?.click()">
          <template #icon><FolderOpenOutlined /></template>
          文件夹上传
        </a-button>
      </div>
    </div>

    <input
      ref="singleInput"
      class="visually-hidden"
      type="file"
      accept="image/jpeg,image/png,image/webp,image/gif"
      @change="onInputChange"
    />
    <input
      ref="batchInput"
      class="visually-hidden"
      type="file"
      accept="image/jpeg,image/png,image/webp,image/gif"
      multiple
      @change="onInputChange"
    />
    <input
      ref="folderInput"
      class="visually-hidden"
      type="file"
      accept="image/jpeg,image/png,image/webp,image/gif"
      multiple
      webkitdirectory
      directory
      @change="onInputChange"
    />

    <div v-if="images.length" class="image-library">
      <div class="library-meta">
        <span>素材库</span>
        <span>{{ selectedIds.length }} / {{ images.length }} 已选择</span>
      </div>
      <div class="image-grid">
        <div
          v-for="image in images"
          :key="image.id"
          class="image-tile"
          :class="{ selected: selectedIds.includes(image.id) }"
        >
          <button
            type="button"
            class="image-select-button"
            :aria-label="`${selectedIds.includes(image.id) ? '取消选择' : '选择'} ${image.filename}`"
            @click="emit('toggle', image.id)"
          >
            <img :src="image.preview_url" :alt="image.filename" />
            <div class="image-shade"></div>
            <CheckCircleFilled class="selected-mark" />
            <div class="image-caption">
              <strong>{{ image.filename }}</strong>
              <span>{{ formatBytes(image.size) }}</span>
            </div>
          </button>
          <button
            type="button"
            class="image-delete-button"
            :disabled="deletingIds.includes(image.id)"
            :aria-label="`删除素材 ${image.filename}`"
            @click="emit('delete', image.id)"
          >
            <LoadingOutlined v-if="deletingIds.includes(image.id)" />
            <DeleteOutlined v-else />
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
