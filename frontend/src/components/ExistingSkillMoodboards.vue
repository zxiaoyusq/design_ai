<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { fetchSavedMoodboard, fetchSavedMoodboards } from '@/api/moodboards'
import type { SavedMoodboardCatalog, SavedMoodboardMember, SavedMoodboardResult } from '@/types/moodboards'

const route = useRoute()
const router = useRouter()
const catalog = ref<SavedMoodboardCatalog>({ default_result_id: null, results: [] })
const selectedId = ref('')
const result = ref<SavedMoodboardResult | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const inspected = ref<SavedMoodboardMember | null>(null)
const detailOpen = ref(false)
const tones = { success: 'green', warning: 'orange', default: undefined, error: 'red' }
let disposed = false
let version = 0

function dateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function readError(value: unknown) {
  const detail = (value as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : value instanceof Error ? value.message : '已有情绪板读取失败'
}
/** 选择器切换后只接受当前请求，避免慢响应把另一版的结论和图片覆盖回来。 */
async function selectResult(id: string) {
  const current = ++version
  selectedId.value = id
  result.value = null
  detailOpen.value = false
  loading.value = true
  error.value = ''
  try {
    const response = await fetchSavedMoodboard(id)
    if (disposed || current !== version) return
    result.value = response
    void router.replace({ query: { ...route.query, saved_result: id, cluster_task: undefined, task: undefined, native_run: undefined } })
  } catch (cause) { if (!disposed && current === version) error.value = readError(cause) }
  finally { if (current === version) loading.value = false }
}
async function refresh() {
  refreshing.value = true
  error.value = ''
  try {
    const response = await fetchSavedMoodboards()
    if (disposed) return
    catalog.value = response
    const requested = typeof route.query.saved_result === 'string' ? route.query.saved_result : selectedId.value
    const id = response.results.some(item => item.id === requested) ? requested : response.default_result_id ?? response.results[0]?.id
    if (id) await selectResult(id)
    else { result.value = null; loading.value = false }
  } catch (cause) { if (!disposed) { error.value = readError(cause); loading.value = false } }
  finally { if (!disposed) refreshing.value = false }
}
function inspect(member: SavedMoodboardMember) { inspected.value = member; detailOpen.value = true }
onMounted(() => void refresh())
onUnmounted(() => { disposed = true; version++ })
</script>

<template>
  <div class="saved-moodboards">
    <div class="saved-selector">
      <div><label for="saved-moodboard-result">已生成的情绪板</label><a-select id="saved-moodboard-result" :value="selectedId || undefined" placeholder="选择已有结果" :options="catalog.results.map(item => ({ value: item.id, label: `${item.title} · ${item.board_count} 版 / ${item.image_count} 图` }))" @change="selectResult(String($event))" /></div>
      <a-button :loading="refreshing" @click="refresh"><ReloadOutlined /> 刷新已有结果</a-button>
    </div>
    <a-alert v-if="error" class="saved-alert" type="error" show-icon :message="error" />
    <a-spin :spinning="loading">
      <template v-if="result">
        <header class="saved-run-heading"><div><h3>{{ result.title }}</h3><p>{{ dateTime(result.created_at) }}<span v-if="result.model_id"> · {{ result.model_id }}</span></p></div><a-tag>{{ result.status_label }}</a-tag></header>
        <div class="saved-summary"><div v-for="(item, index) in result.summary" :key="index"><strong>{{ item.value }}</strong><span>{{ item.label }}</span></div></div>
        <div v-if="result.notes.length" class="run-notes"><p v-for="(note, index) in result.notes" :key="index">{{ note }}</p></div>
        <nav v-if="result.downloads?.length" class="saved-downloads" aria-label="原始结果下载"><a v-for="item in result.downloads" :key="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.label }}</a></nav>
        <article v-for="(board, index) in result.boards" :key="board.id" class="saved-board">
          <header class="saved-board-heading"><span class="board-number">{{ String(index + 1).padStart(2, '0') }}</span><div><h3>{{ board.title }}</h3><p>{{ board.description }}</p></div><div class="board-badges"><a-tag :color="tones[board.status_tone]">{{ board.status_label }}</a-tag><span>{{ board.members.length }} 张图片</span></div></header>
          <div v-if="board.review_notes.length" class="review-notes" :class="board.status_tone"><strong>原有评审结论</strong><p>{{ board.review_notes[0] }}</p><a-tag v-if="board.feedback_summary?.rejected" color="red">设计师已排除 {{ board.feedback_summary.rejected }} 张</a-tag></div>
          <div class="saved-member-grid">
            <article v-for="member in board.members" :key="member.id" class="saved-member" :class="{ rejected: member.feedback?.status === 'rejected' }">
              <button type="button" :aria-label="`查看 ${member.image_name} 的原图与入选依据`" @click="inspect(member)"><img v-if="member.preview_url" :src="member.preview_url" :alt="member.image_name" loading="lazy" /><span v-else class="saved-image-placeholder">原图暂不可读</span></button>
              <div class="member-caption"><a-tag>{{ member.category || '品类未核' }}</a-tag><a-tag v-if="member.feedback" :color="member.feedback.status === 'rejected' ? 'red' : undefined">{{ member.feedback.status === 'rejected' ? '设计师已排除' : '未标记' }}</a-tag><span :title="member.image_name">{{ member.image_name }}</span></div><p v-if="member.reason" class="member-reason">{{ member.reason }}</p><p v-if="member.source_label" class="member-source">来源：{{ member.source_label }}</p><button class="member-details" type="button" @click="inspect(member)">查看原图与详细依据</button>
            </article>
          </div>
          <details v-if="board.relations?.length" class="additional-reasoning"><summary>共同设计关系（{{ board.relations.length }} 维）</summary><dl class="board-relations"><template v-for="(relation, relationIndex) in board.relations" :key="relationIndex"><dt>{{ relation.label }}</dt><dd>{{ relation.value }}</dd></template></dl></details>
          <details v-if="board.review_notes.length > 1" class="additional-reasoning"><summary>完整评审意见与反馈</summary><p v-for="(note, noteIndex) in board.review_notes.slice(1)" :key="noteIndex">{{ note }}</p></details>
          <dl v-if="board.constraints?.length" class="board-constraints"><div v-for="(constraint, constraintIndex) in board.constraints" :key="constraintIndex"><dt>{{ constraint.label }}</dt><dd>{{ constraint.value }}</dd></div></dl>
          <details v-if="board.hardest_pair?.comparison || board.design_quality_choice" class="additional-reasoning"><summary>差异协调与设计表达依据</summary><p v-if="board.hardest_pair?.comparison"><strong>最难协调成员对：</strong>{{ board.hardest_pair.comparison }}</p><p v-if="board.design_quality_choice"><strong>设计表达取舍：</strong>{{ board.design_quality_choice }}</p></details>
          <div v-if="board.source_links?.length" class="saved-downloads"><a v-for="link in board.source_links" :key="link.url" :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.label }}</a></div>
        </article>
        <a-empty v-if="!result.boards.length" description="这次保存的结果中没有情绪板" />
        <p v-if="result.prompt_version" class="saved-trace">原始提示版本：{{ result.prompt_version }}</p>
      </template>
      <a-empty v-else-if="!loading && !error" description="暂无登记的 Skill 情绪板结果" />
    </a-spin>
    <a-modal v-model:open="detailOpen" :title="inspected?.image_name" :footer="null" :width="1040">
      <div v-if="inspected" class="saved-member-detail"><div class="detail-image"><a-image v-if="inspected.original_url || inspected.preview_url" :src="inspected.original_url || inspected.preview_url || undefined" :alt="inspected.image_name" /><a v-if="inspected.original_url" :href="inspected.original_url" target="_blank" rel="noopener noreferrer">打开完整原图</a></div><dl><dt>品类</dt><dd>{{ inspected.category || '未核实' }}</dd><template v-if="inspected.feedback"><dt>设计师反馈</dt><dd><a-tag :color="inspected.feedback.status === 'rejected' ? 'red' : undefined">{{ inspected.feedback.status === 'rejected' ? '设计师已排除' : '未标记' }}</a-tag><p v-if="inspected.feedback.status === 'rejected'">{{ inspected.feedback.reason || '未填写排除原因' }}</p><p v-if="inspected.feedback.updated_at">{{ dateTime(inspected.feedback.updated_at) }}</p></dd></template><template v-if="inspected.source_label"><dt>来源</dt><dd>{{ inspected.source_label }}</dd></template><template v-if="inspected.reason"><dt>入选依据</dt><dd>{{ inspected.reason }}</dd></template><template v-if="inspected.strongest_difference"><dt>最强差异</dt><dd>{{ inspected.strongest_difference }}</dd></template><template v-if="inspected.why_coordinated"><dt>差异如何协调</dt><dd>{{ inspected.why_coordinated }}</dd></template><dt>原图标识</dt><dd>{{ inspected.image_id }}</dd></dl></div>
    </a-modal>
  </div>
</template>

<style scoped>
.saved-selector { display: flex; align-items: flex-end; gap: 16px; margin: 8px 0 22px; }
.saved-selector > div { flex: 1; min-width: 0; }
.saved-selector label { display: block; margin-bottom: 9px; color: #756582; font-size: 12px; }
.saved-selector .ant-select { width: 100%; }
.saved-selector :deep(.ant-select-selection-item) { overflow: hidden; text-overflow: ellipsis; }
.saved-alert { margin: 16px 0; }
.saved-run-heading, .saved-board-heading { display: flex; align-items: flex-start; gap: 16px; }
.saved-run-heading > div, .saved-board-heading > div:not(.board-badges) { flex: 1; min-width: 0; }
h3 { margin: 0; color: #5b476e; font-size: 20px; }
p { margin: 8px 0 0; color: #897993; font-size: 12px; line-height: 1.8; white-space: normal; overflow-wrap: anywhere; }
.saved-run-heading > div > p, .saved-trace { color: #9b8ca4; font-size: 11px; }
.saved-summary { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.saved-summary > div { display: flex; min-width: 100px; flex-direction: column; gap: 5px; padding: 14px 18px; background: #f6f2fa; border-radius: 12px; }
.saved-summary strong { color: #76608f; font-size: 20px; }
.saved-summary span { color: #96879f; font-size: 11px; }
.run-notes { padding: 2px 16px 12px; background: #faf8fc; border-left: 3px solid #cbbbe0; border-radius: 6px; }
.saved-downloads { display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; font-size: 12px; }
.saved-board { padding: 24px; margin-top: 26px; border: 1px solid #e9e2ef; border-radius: 18px; background: #fcfbfd; }
.board-number { color: #b09ec0; font-size: 26px; }
.board-badges { display: flex; flex-direction: column; align-items: flex-end; gap: 7px; color: #9987a4; font-size: 11px; }
.board-badges .ant-tag { margin: 0; white-space: normal; }
.review-notes { margin: 18px 0; padding: 12px 16px; background: #f3eff8; border-radius: 9px; }
.review-notes strong { color: #786387; font-size: 12px; }
.review-notes.success { background: #eef7f1; }
.review-notes.warning { background: #fff7e9; }
.review-notes.error { background: #fceeee; }
.board-relations { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 8px 14px; margin: 18px 0; font-size: 12px; line-height: 1.85; }
dt { color: #786385; }
dd { min-width: 0; margin: 0; color: #8a7a95; overflow-wrap: anywhere; white-space: normal; }
.saved-member-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 20px; }
.saved-member { min-width: 0; padding: 10px; background: #fff; border: 1px solid #ede7f1; border-radius: 10px; }
.saved-member.rejected { border-color: #e4a6a6; background: #fff8f8; }
.saved-member > button:first-child { width: 100%; padding: 0; border: 1px solid transparent; background: #fff; cursor: pointer; }
.saved-member > button:first-child:hover, .saved-member > button:first-child:focus-visible { border-color: #b29cc7; }
.saved-member img, .saved-image-placeholder { width: 100%; height: 245px; object-fit: contain; }
.saved-image-placeholder { display: flex; align-items: center; justify-content: center; background: #f8f6fa; font-size: 12px; color: #9a8ba6; }
.member-caption { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 12px; }
.member-caption .ant-tag { max-width: 100%; margin: 0; white-space: normal; }
.member-caption > span { min-width: 0; overflow: hidden; color: #a090aa; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.member-reason { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.member-source { color: #a394ac; font-size: 10px; }
.member-details { padding: 0; margin-top: 9px; border: 0; background: transparent; color: #877099; font-size: 11px; cursor: pointer; }
.board-constraints { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 20px 0 0; font-size: 11px; }
.board-constraints > div { padding: 12px; background: #f4f0f8; border-radius: 8px; }
.board-constraints dd { margin-top: 6px; line-height: 1.8; }
.additional-reasoning { margin-top: 18px; }
summary { color: #806d8e; font-size: 12px; cursor: pointer; }
.saved-member-detail { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 24px; padding-top: 12px; }
.detail-image { min-width: 0; }
.detail-image :deep(.ant-image) { width: 100%; }
.detail-image :deep(.ant-image-img) { max-height: 68vh; object-fit: contain; }
.detail-image > a { display: inline-block; margin-top: 12px; font-size: 12px; }
.saved-member-detail dl { margin: 0; font-size: 12px; line-height: 1.85; }
.saved-member-detail dt { margin-top: 13px; margin-bottom: 4px; }
.saved-member-detail dt:first-child { margin-top: 0; }
.saved-trace { margin-top: 22px; }
@media (max-width: 1000px) { .saved-member-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .saved-selector { align-items: stretch; flex-direction: column; } .saved-run-heading, .saved-board-heading { flex-wrap: wrap; } .saved-board { padding: 14px; } .saved-board h3 { font-size: 18px; } .board-number { font-size: 23px; } .board-badges { width: 100%; flex-direction: row; flex-wrap: wrap; align-items: center; } .board-relations { grid-template-columns: 1fr; gap: 4px; } .board-relations dd { margin-bottom: 8px; } .saved-member-grid { gap: 8px; } .saved-member { padding: 6px; } .saved-member img, .saved-image-placeholder { height: 165px; } .board-constraints { grid-template-columns: 1fr; } .saved-member-detail { grid-template-columns: 1fr; } .saved-summary > div { flex: 1; min-width: 80px; } }
</style>
