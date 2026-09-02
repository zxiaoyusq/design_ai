<script setup lang="ts">
import {
  BarsOutlined,
  DeleteOutlined,
  EyeOutlined,
  FileSearchOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'

import BusinessResultView from '@/components/result/BusinessResultView.vue'
import DetailResultView from '@/components/result/DetailResultView.vue'
import type { DesignDnaResultSummary } from '@/types/dna'

const props = defineProps<{
  results: DesignDnaResultSummary[]
  activeResultId: string | null
  view: 'business' | 'detail'
  content: Record<string, unknown> | null
  loading: boolean
  deletingIds: string[]
}>()

const emit = defineEmits<{
  select: [resultId: string]
  changeView: [view: 'business' | 'detail']
  refresh: []
  delete: [resultId: string]
}>()

function displayDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <section class="workspace-card result-panel">
    <div class="section-heading result-heading">
      <div>
        <span class="eyebrow">03 / 提取结果</span>
        <h2>查看图片的设计 DNA</h2>
        <p>业务视图聚焦核心洞察；显示详情可查看完整字段与可定位证据。</p>
      </div>
      <a-button type="text" @click="emit('refresh')">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <div v-if="!results.length" class="result-empty">
      <div><FileSearchOutlined /></div>
      <strong>还没有提取结果</strong>
      <span>上传并选择图片，确认需求后开始第一次分析。</span>
    </div>

    <div v-else class="result-workbench">
      <aside class="result-list">
        <div
          v-for="result in results"
          :key="result.id"
          class="result-list-item"
          :class="{ active: activeResultId === result.id }"
        >
          <button type="button" class="result-select-button" @click="emit('select', result.id)">
            <div class="result-thumbnail">
              <img v-if="result.preview_url" :src="result.preview_url" :alt="result.image_name" />
              <span v-else>{{ result.image_name.slice(0, 1).toUpperCase() }}</span>
            </div>
            <div class="result-list-copy">
              <strong>{{ result.image_name }}</strong>
              <span>{{ result.style_tags.join(' · ') || result.category || '设计 DNA 已提取' }}</span>
              <small>{{ displayDate(result.created_at) }}</small>
            </div>
          </button>
          <button
            type="button"
            class="result-delete-button"
            :disabled="deletingIds.includes(result.id)"
            :aria-label="`删除提取结果 ${result.image_name}`"
            @click="emit('delete', result.id)"
          >
            <DeleteOutlined />
          </button>
        </div>
      </aside>

      <div class="result-detail">
        <div class="view-switcher">
          <div>
            <button
              type="button"
              :class="{ active: view === 'business' }"
              @click="emit('changeView', 'business')"
            >
              <EyeOutlined /> 业务视图
            </button>
            <button
              type="button"
              :class="{ active: view === 'detail' }"
              @click="emit('changeView', 'detail')"
            >
              <BarsOutlined /> 显示详情
            </button>
          </div>
          <span>{{ view === 'business' ? '核心洞察' : '完整字段' }}</span>
        </div>

        <a-spin :spinning="loading">
          <BusinessResultView v-if="content && view === 'business'" :data="content" />
          <DetailResultView v-else-if="content && view === 'detail'" :data="content" />
        </a-spin>
      </div>
    </div>
  </section>
</template>
