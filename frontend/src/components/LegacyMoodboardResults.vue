<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMoodboardTask, fetchMoodboardTasks, moodboardDownloadUrl, previewNativeMoodboard } from '@/api/moodboards'
import MoodboardGallery from '@/components/MoodboardGallery.vue'
import type { MoodboardResult, MoodboardTask } from '@/types/moodboards'
const route = useRoute()
const router = useRouter()
const history = ref<MoodboardTask[]>([])
const selectedId = ref('')
const task = ref<MoodboardTask | null>(null)
const result = ref<MoodboardResult | null>(null)
const loading = ref(false)
const error = ref('')
const inspectedId = ref('')
const detailOpen = ref(false)
const images = computed(() => new Map((result.value?.images ?? []).map(item => [item.id, item])))
const inspectedImage = computed(() => images.value.get(inspectedId.value))
const assignment = computed(() => result.value?.assignments.find(item => item.result_id === inspectedId.value))
const exclusions = computed(() => result.value?.directions.flatMap(direction => (direction.excluded ?? []).filter(item => item.result_id === inspectedId.value)) ?? [])
let version = 0
let disposed = false
function dateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function inspect(id: string) { inspectedId.value = id; detailOpen.value = true }
async function select(id: string) {
  const current = ++version
  selectedId.value = id
  loading.value = true
  error.value = ''
  task.value = null
  result.value = null
  void router.replace({ query: { ...route.query, task: id, native_run: undefined, cluster_task: undefined } })
  try {
    const response = await fetchMoodboardTask(id)
    if (disposed || current !== version) return
    task.value = response
    result.value = response.result ?? null
  } catch (cause) { if (!disposed && current === version) error.value = cause instanceof Error ? cause.message : '历史结果读取失败' }
  finally { if (current === version) loading.value = false }
}
async function refresh() {
  try { const response = await fetchMoodboardTasks(); if (!disposed) history.value = response }
  catch (cause) { if (!disposed) error.value = cause instanceof Error ? cause.message : '历史记录读取失败' }
}
watch(() => route.query.task, value => { if (typeof value === 'string' && value !== selectedId.value) void select(value) })
onMounted(async () => {
  loading.value = true
  await refresh()
  if (disposed) return
  if (typeof route.query.native_run === 'string') {
    try { const response = await previewNativeMoodboard(route.query.native_run); if (!disposed) result.value = response }
    catch (cause) { error.value = cause instanceof Error ? cause.message : '原生历史结果读取失败' }
    finally { loading.value = false }
  } else {
    const id = typeof route.query.task === 'string' ? route.query.task : history.value[0]?.id
    if (id) await select(id)
    else loading.value = false
  }
})
onUnmounted(() => { disposed = true; version++ })
</script>

<template>
  <div class="legacy-results">
    <a-alert type="info" show-icon message="历史结果只读，沿用当时的规则与状态，不代表已通过当前聚类标准。" />
    <div class="history-controls"><a-select :value="selectedId || undefined" placeholder="选择历史任务" :options="history.map(item => ({ value: item.id, label: `${dateTime(item.created_at)} · ${item.id.slice(0, 8)} · ${item.status}` }))" @change="select(String($event))" /><a-button @click="refresh">刷新记录</a-button><a v-if="task?.result" :href="moodboardDownloadUrl(task.id)" download>下载历史 JSON</a></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-spin :spinning="loading">
      <p v-if="task">{{ task.message || task.stage }}<span v-if="task.error"> · {{ task.error }}</span></p>
      <template v-if="result">
        <article v-for="direction in result.directions" :key="direction.id" class="legacy-board"><h3>{{ direction.title }}</h3><p>{{ direction.description }}</p><section v-for="cluster in direction.clusters" :key="cluster.id"><h4>{{ cluster.name }} · {{ cluster.result_ids.length }} 张</h4><p>{{ cluster.description }}</p><p v-if="cluster.primary_axis">主导关系：{{ cluster.primary_axis }}</p><p v-if="cluster.required_features?.length">入选条件：{{ cluster.required_features.join('；') }}</p><p v-if="cluster.exclusions?.length">排除特征：{{ cluster.exclusions.join('；') }}</p><MoodboardGallery :result-ids="cluster.result_ids" :images="images" :curated="true" @inspect="inspect" /></section><p v-if="!direction.clusters.length">此方向未成板，保留历史判断。</p><details v-if="direction.excluded?.length"><summary>未入选候选（{{ direction.excluded.length }}）</summary><p v-for="item in direction.excluded" :key="item.result_id"><a-button type="link" @click="inspect(item.result_id)">{{ images.get(item.result_id)?.image_name ?? item.result_id }}</a-button>{{ item.reason }}</p></details></article>
        <details v-if="result.unmatched_result_ids.length"><summary>未匹配图片（{{ result.unmatched_result_ids.length }}）</summary><MoodboardGallery :result-ids="result.unmatched_result_ids" :images="images" @inspect="inspect" /></details>
        <details><summary>历史执行追溯</summary><pre>{{ JSON.stringify(result.trace, null, 2) }}</pre></details>
      </template><a-empty v-else-if="!loading" description="暂无可查看的历史结果" />
    </a-spin>
    <a-modal v-model:open="detailOpen" :title="inspectedImage?.image_name ?? inspectedId" :footer="null" :width="800"><a-image v-if="inspectedImage?.preview_url" :src="inspectedImage.preview_url" :alt="inspectedImage.image_name" /><p>{{ assignment?.reason ?? '暂无归属说明' }}</p><p v-for="(item, index) in exclusions" :key="index">未入选原因：{{ item.reason }}</p><p>{{ inspectedImage?.summary }}</p><details><summary>历史 DNA 证据</summary><pre>{{ JSON.stringify(assignment, null, 2) }}</pre></details></a-modal>
  </div>
</template>

<style scoped>
.history-controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0; }
.history-controls .ant-select { flex: 1; min-width: 220px; }
.legacy-board { padding: 22px; margin: 20px 0; border: 1px solid #ece7f3; border-radius: 16px; background: #fcfbfd; }
.legacy-board h3 { color: #615173; }
p, summary { color: #81728f; font-size: 13px; line-height: 1.8; }
details { margin: 18px 0; }
summary { cursor: pointer; }
pre { max-height: 380px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: #f7f5fa; font-size: 12px; }
</style>
