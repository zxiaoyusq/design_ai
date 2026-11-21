<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isAxiosError } from 'axios'

import { articleTrendsApi } from '@/api/articleTrends'
import type { ArticleImportPreview, ArticleImportResult } from '@/types/articleTrends'

const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ imported: [result: ArticleImportResult] }>()
const file = ref<File | null>(null)
const preview = ref<ArticleImportPreview | null>(null)
const busy = ref(false)
const error = ref('')
const okText = computed(() => preview.value?.new_count
  ? `确认导入 ${preview.value.new_count.toLocaleString()} 篇` : '预览增量')

watch(open, visible => {
  if (!visible) {
    file.value = null
    preview.value = null
    error.value = ''
  }
})

function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0]
  file.value = null
  preview.value = null
  error.value = ''
  if (!selected) return
  if (!selected.name.toLowerCase().endsWith('.xlsx')) {
    error.value = '请选择 .xlsx 格式的文件。'
  } else if (selected.size > 32 * 1024 * 1024) {
    error.value = 'Excel 文件不能超过 32 MB。'
  } else {
    file.value = selected
  }
}

async function submit() {
  if (!file.value || busy.value || preview.value?.new_count === 0) return
  busy.value = true
  error.value = ''
  try {
    if (preview.value) {
      const result = await articleTrendsApi.importWorkbook(file.value, preview.value.selection_digest)
      open.value = false
      emit('imported', result)
    } else {
      preview.value = await articleTrendsApi.previewImport(file.value)
    }
  } catch (cause) {
    if (isAxiosError(cause)) {
      if (cause.response?.status === 409) preview.value = null
      const detail = cause.response?.data?.detail
      error.value = typeof detail === 'string' ? detail : '导入请求失败，请重新预览后再试。'
    } else {
      error.value = '导入请求失败，请重试。'
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <a-modal
    v-model:open="open"
    title="导入趋势文章"
    :ok-text="okText"
    :cancel-text="preview?.new_count === 0 ? '关闭' : '取消'"
    :confirm-loading="busy"
    :ok-button-props="{ disabled: !file || preview?.new_count === 0 }"
    :cancel-button-props="{ disabled: busy }"
    :closable="!busy"
    :mask-closable="!busy"
    :keyboard="!busy"
    destroy-on-close
    @ok="submit"
  >
    <div class="import-fields">
      <label for="article-import-file">选择文章导出表</label>
      <input id="article-import-file" type="file" accept=".xlsx" :disabled="busy" aria-describedby="article-import-help" @change="chooseFile" />
      <p id="article-import-help" class="hint">支持 .xlsx，最大 32 MB。按文章 ID 和原文链接识别重复。</p>
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <template v-if="preview">
        <p class="hint">已读取 {{ preview.total_rows.toLocaleString() }} 行，待新增文章含 {{ preview.image_count.toLocaleString() }} 个配图链接。</p>
        <dl class="import-counts" aria-label="导入预览">
          <div><dt>待新增</dt><dd>{{ preview.new_count.toLocaleString() }}</dd></div>
          <div><dt>重复</dt><dd>{{ preview.duplicate_count.toLocaleString() }}</dd></div>
          <div><dt>异常</dt><dd>{{ preview.invalid_count.toLocaleString() }}</dd></div>
        </dl>
        <a-alert v-if="preview.new_count === 0" type="info" show-icon message="这份表没有可新增的文章。" />
        <ul v-if="preview.sample_articles.length" class="import-sample" aria-label="待新增文章示例">
          <li v-for="article in preview.sample_articles" :key="article.article_id">
            <time v-if="article.published_at">{{ article.published_at }}</time>
            <span>{{ article.title }}</span>
          </li>
        </ul>
        <details v-if="preview.issues.length" class="import-issues" open>
          <summary>将跳过 {{ preview.invalid_count.toLocaleString() }} 个异常行<template v-if="preview.invalid_count > preview.issues.length">，显示前 {{ preview.issues.length }} 行</template></summary>
          <ul><li v-for="issue in preview.issues" :key="issue.row">第 {{ issue.row }} 行 · {{ issue.reason }}</li></ul>
        </details>
      </template>
    </div>
  </a-modal>
</template>

<style scoped>
.import-fields { display: grid; gap: 12px; padding: 8px 0; }
.import-fields label { font-weight: 600; }
.import-fields input { display: block; max-width: 100%; min-width: 0; font: inherit; color: inherit; }
.hint { margin: 0; color: #6c627c; font-size: 13px; }
.import-counts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 0; }
.import-counts div { padding: 10px; border-radius: 8px; color: #594577; background: #f2eef9; }
.import-counts dd { margin: 2px 0 0; font-size: 19px; font-weight: 600; }
.import-sample { display: grid; gap: 6px; padding: 0; margin: 0; list-style: none; }
.import-sample li { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 8px; overflow-wrap: anywhere; }
.import-sample time { color: #6c627c; font-size: 12px; white-space: nowrap; }
.import-issues { color: #785c35; font-size: 13px; }
.import-issues ul { margin: 6px 0 0; padding-left: 20px; }
</style>
