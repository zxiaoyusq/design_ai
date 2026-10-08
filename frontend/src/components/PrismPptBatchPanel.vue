<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { D02PptBatch } from '@/types/dnaV2'

const props = defineProps<{ batch: D02PptBatch | null }>()
const emit = defineEmits<{ select: [resultId: string]; refresh: [] }>()
const query = ref('')
const status = ref('all')
const page = ref(1)
const pageSize = 20
const filtered = computed(() => (props.batch?.entries ?? []).filter((entry) => {
  if (status.value !== 'all' && entry.status !== status.value) return false
  const text = [entry.source_path, ...entry.user_names, ...entry.ref_pic_codes].join(' ').toLowerCase()
  return text.includes(query.value.trim().toLowerCase())
}))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([query, status], () => { page.value = 1 })
const labels: Record<string, string> = {
  pending: '待处理', running: '提取中', completed: '已完成', failed: '失败',
  prepared: '已准备', partial: '部分完成', blocked: '已暂停',
}
</script>

<template>
  <section v-if="batch" class="workspace-card batch-panel">
    <div class="section-heading result-heading">
      <div>
        <span class="eyebrow">PT 补录 / ENJOY 图片</span>
        <h2>551 张 D02 R17 历史批次</h2>
        <p>{{ batch.model_id }} · 最多 {{ batch.max_concurrency }} 张并行 · {{ batch.unique_image_sha256 }} 份不同原图</p>
      </div>
      <a-button type="text" @click="emit('refresh')">刷新进度</a-button>
    </div>
    <div class="batch-stats">
      <div><strong>{{ batch.counts.completed }}</strong><span>已完成</span></div>
      <div><strong>{{ batch.counts.running }}</strong><span>提取中</span></div>
      <div><strong>{{ batch.counts.pending }}</strong><span>待处理</span></div>
      <div><strong>{{ batch.counts.failed }}</strong><span>失败</span></div>
    </div>
    <p class="batch-caption">已完成中：R41 Schema 通过 {{ batch.quality_counts.schema_valid }} 张，基础关系通过 {{ batch.quality_counts.protocol_valid }} 张，独立 CMF 复核完成 {{ batch.quality_counts.review_complete }} 张。完成执行不等于通过校验。</p>
    <a-progress :percent="Math.round((batch.counts.completed + batch.counts.failed) / batch.total_paths * 100)" :status="batch.status === 'blocked' ? 'exception' : 'active'" />
    <a-alert v-if="batch.status === 'blocked'" type="warning" show-icon message="批次已暂停" description="检测到模型额度或鉴权错误，未继续提交剩余图片；已保留逐图记录。" />
    <div class="batch-controls">
      <a-input v-model:value="query" placeholder="搜索用户、图片路径或图片编号" allow-clear />
      <a-select v-model:value="status" :options="[
        { value: 'all', label: '全部状态' },
        { value: 'completed', label: '已完成' },
        { value: 'running', label: '提取中' },
        { value: 'pending', label: '待处理' },
        { value: 'failed', label: '失败' },
      ]" />
    </div>
    <div class="batch-list">
      <div v-for="entry in visible" :key="entry.source_path" class="batch-item">
        <button v-if="entry.result_id" type="button" class="batch-image" @click="emit('select', entry.result_id)">
          <img :src="`/api/v1/dna-v2/results/${entry.result_id}/image`" :alt="entry.source_path" />
        </button>
        <div v-else class="batch-image batch-placeholder">{{ entry.status === 'failed' ? '!' : '…' }}</div>
        <div class="batch-copy">
          <strong>{{ entry.user_names.join('、') }} · {{ entry.ref_pic_codes.join('、') || 'PPT 图片' }}</strong>
          <small>{{ entry.source_path }}</small>
          <small v-if="entry.error" class="batch-error">{{ entry.error }}</small>
          <small v-else-if="entry.status === 'completed'">{{ entry.protocol_valid ? (entry.review_complete ? '结构与局部 CMF 复核完成' : '结构通过，复核未完成') : '候选存在结构问题，请查看详情' }}</small>
        </div>
        <span :class="['batch-status', entry.status]">{{ labels[entry.status] }}</span>
        <button v-if="entry.result_id" type="button" class="batch-open" @click="emit('select', entry.result_id)">查看 DNA</button>
      </div>
    </div>
    <a-pagination v-if="filtered.length > pageSize" v-model:current="page" :page-size="pageSize" :total="filtered.length" size="small" show-less-items />
    <p class="batch-caption">{{ labels[batch.status] || batch.status }} · 当前筛选 {{ filtered.length }} 张 · 失败项保留原始错误，不自动重试</p>
  </section>
</template>

<style scoped>
.batch-panel { margin-bottom: 22px; }
.batch-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }
.batch-stats div { padding: 14px 16px; background: #f7f5fb; border-radius: 12px; display: grid; }
.batch-stats strong { font-size: 24px; color: #40376d; }
.batch-stats span, .batch-caption { color: #817d90; font-size: 12px; }
.batch-controls { display: flex; gap: 12px; margin: 18px 0 10px; }
.batch-controls > :first-child { flex: 1; }
.batch-controls > :last-child { width: 150px; }
.batch-list { display: grid; gap: 6px; margin-bottom: 16px; }
.batch-item { display: flex; align-items: center; gap: 12px; padding: 9px; border: 1px solid #ebe8f2; border-radius: 10px; }
.batch-image { width: 48px; height: 48px; flex: none; padding: 0; overflow: hidden; border: 0; border-radius: 8px; background: #f1eef8; }
.batch-image img { width: 100%; height: 100%; object-fit: cover; }
.batch-placeholder { display: grid; place-items: center; color: #8983a3; }
.batch-copy { display: grid; min-width: 0; flex: 1; }
.batch-copy strong, .batch-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-copy small { color: #817d90; }
.batch-copy .batch-error { color: #b44747; white-space: normal; }
.batch-status { font-size: 12px; white-space: nowrap; }
.batch-status.completed { color: #25815d; }
.batch-status.failed { color: #b44747; }
.batch-open { border: 0; background: transparent; color: #6257d8; cursor: pointer; white-space: nowrap; }
@media(max-width: 700px) { .batch-stats { grid-template-columns: repeat(2, 1fr); } .batch-controls { flex-direction: column; } .batch-controls > :last-child { width: 100%; } }
</style>
