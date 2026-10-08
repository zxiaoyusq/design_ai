<script setup lang="ts">
import { computed, ref } from 'vue'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import type { D02Result, D02ResultSummary } from '@/types/dnaV2'

const props = defineProps<{
  results: D02ResultSummary[]
  activeResultId: string | null
  result: D02Result | null
  loading: boolean
  deletingIds: string[]
}>()
const emit = defineEmits<{
  select: [resultId: string]
  refresh: []
  delete: [resultId: string]
}>()
const tab = ref<'overview' | 'raw'>('overview')
const r5Result = computed(() => props.result?.schema_version === 'prism_sol_r5_candidate_v1' ? props.result : null)
const legacyResult = computed(() => props.result?.schema_version === 'prism_d02_candidate_v1' ? props.result : null)
const r5AreaGroups = computed(() => {
  const groups = new Map<string, NonNullable<typeof r5Result.value>['r5_result']['local_features']>()
  for (const feature of r5Result.value?.r5_result.local_features ?? []) {
    const entries = groups.get(feature.at) ?? []
    entries.push(feature)
    groups.set(feature.at, entries)
  }
  return [...groups.entries()].map(([name, features]) => ({ name, features }))
})
const formatValue = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value)

interface WireObject { t: number; g: number[]; c: string; v: unknown[]; d: unknown[] }
const objects = computed<WireObject[]>(() => {
  const raw = legacyResult.value?.candidate?.o
  return Array.isArray(raw) ? raw.filter((item): item is WireObject => typeof item === 'object' && item !== null) : []
})
const preview = computed(() => props.results.find((item) => item.id === props.activeResultId)?.preview_url)
const reviewByKey = computed(() => new Map(
  (legacyResult.value?.reviews ?? []).map((row) => [`${row.object_index}:${row.field_id}`, row]),
))
const observationsByObject = (index: number) =>
  legacyResult.value?.observations.filter((row) => row.object_index === index) ?? []
const verdictText = (verdict?: string) => ({
  supported: '复核支持', contradicted: '复核冲突', unknown: '复核不确定',
}[verdict ?? ''] ?? '未复核')
const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN')
</script>

<template>
  <section class="workspace-card result-panel">
    <div class="section-heading result-heading">
      <div>
        <span class="eyebrow">03 / D02 候选结果</span>
        <h2>查看图片 DNA 与局部 CMF</h2>
        <p>新版按可见区域展示 ID 与 CMF，历史 R17 对象结果继续可查。</p>
      </div>
      <a-button type="text" @click="emit('refresh')"><ReloadOutlined /> 刷新</a-button>
    </div>
    <div v-if="!results.length" class="result-empty">
      <strong>还没有 D02 结果</strong>
      <span>选择图片和模型后开始提取。</span>
    </div>
    <div v-else class="result-workbench">
      <aside class="result-list">
        <div v-for="item in results" :key="item.id" class="result-list-item" :class="{ active: item.id === activeResultId }">
          <button type="button" class="result-select-button" @click="emit('select', item.id)">
            <div class="result-thumbnail"><img :src="item.preview_url" :alt="item.image_name" /></div>
            <div class="result-list-copy">
              <strong>{{ item.image_name }}</strong>
              <span>{{ item.research?.preferences[0]?.user_name || item.model_id }} · {{ item.schema_version === 'prism_sol_r5_candidate_v1' ? `${item.feature_count} 项图级特征` : `${item.object_count} 个对象` }}</span>
              <small>{{ formatDate(item.created_at) }}</small>
            </div>
          </button>
          <button v-if="!item.research?.source_path" type="button" class="result-delete-button" :disabled="deletingIds.includes(item.id)" :aria-label="`删除 ${item.image_name}`" @click="emit('delete', item.id)"><DeleteOutlined /></button>
        </div>
      </aside>
      <div class="result-detail d02-detail">
        <div class="view-switcher">
          <div>
            <button type="button" :class="{ active: tab === 'overview' }" @click="tab = 'overview'">{{ r5Result ? '局部与图级特征' : '对象与复核' }}</button>
            <button type="button" :class="{ active: tab === 'raw' }" @click="tab = 'raw'">原始 JSON</button>
          </div>
          <span>D02 · {{ r5Result ? 'Sol R5 候选' : 'R17 历史候选' }}</span>
        </div>
        <a-spin :spinning="loading">
          <template v-if="result">
            <div v-if="tab === 'overview' && r5Result" class="d02-content">
              <a-alert type="info" show-icon :message="r5Result.validation.note" />
              <div class="d02-summary">
                <img v-if="preview" :src="preview" :alt="r5Result.image_name" />
                <div>
                  <h3>{{ r5Result.image_name }}</h3>
                  <p>模型：{{ r5Result.execution.model_id }} · {{ r5Result.execution.adapter === 'codex_cli_frozen_r5' ? '冻结 Codex CLI' : '历史 DeepAgents' }} · 执行 {{ r5Result.execution.duration_seconds }} 秒</p>
                  <p>图级特征 {{ r5Result.r5_result.image_unique_features }} 项（ID {{ r5Result.r5_result.ID_unique }}、CMF {{ r5Result.r5_result.CMF_unique }}）；局部特征 {{ r5Result.r5_result.local_features.length }} 项</p>
                  <p>定点复核：{{ r5Result.validation.focus_complete ? '完成或无需复核' : '未完成' }} · 未决 {{ r5Result.validation.pending_count }} 项 · 无效 {{ r5Result.validation.invalid_count }} 项</p>
                  <p>原图 SHA256：<code>{{ r5Result.source.image_sha256 }}</code></p>
                  <p>Prompt：{{ r5Result.execution.prompt_version }} · 调用 {{ r5Result.execution.attempted_calls }}/{{ r5Result.execution.max_calls }}</p>
                </div>
              </div>
              <a-alert v-if="r5Result.execution.focus_error" type="warning" show-icon message="困难项复核未完成" :description="r5Result.execution.focus_error" />
              <h3>按可见位置保留的局部特征</h3>
              <p v-if="!r5AreaGroups.length">没有可采纳的局部特征；请查看未决项和原始记录。</p>
              <article v-for="area in r5AreaGroups" :key="area.name" class="d02-object">
                <h4>{{ area.name }}</h4>
                <div class="d02-observations">
                  <div v-for="feature in area.features" :key="`${feature.path}:${feature.p}`" class="d02-observation">
                    <span><code>{{ feature.p }}</code></span><strong>{{ formatValue(feature.v) }}</strong>
                    <a-tag>{{ feature.source }}</a-tag>
                    <small v-if="feature.evidence">{{ feature.evidence }}</small>
                  </div>
                </div>
              </article>
              <h3>图级特征索引</h3>
              <article v-for="(feature, index) in r5Result.r5_result.features" :key="`${feature.parameter_id}:${index}`" class="d02-object">
                <strong>{{ feature.parameter_name }} <code>{{ feature.parameter_id }}</code> · {{ formatValue(feature.value) }}</strong>
                <p>视图：{{ feature.views.join(' / ') }} · 位置：{{ feature.locations.join('、') }}</p>
              </article>
            </div>
            <div v-else-if="tab === 'overview' && legacyResult" class="d02-content">
              <a-alert type="warning" show-icon :message="legacyResult.validation.note" />
              <div class="d02-summary">
                <img v-if="preview" :src="preview" :alt="legacyResult.image_name" />
                <div>
                  <h3>{{ legacyResult.image_name }}</h3>
                  <p>模型：{{ legacyResult.execution.model_id }} · 执行 {{ legacyResult.execution.duration_seconds }} 秒</p>
                  <p>R41 Schema：{{ legacyResult.validation.r41_schema_valid ? '通过' : '未通过' }} · 基础关系：{{ legacyResult.validation.basic_protocol_valid ? '通过' : '未通过' }} · 独立 CMF 复核：{{ legacyResult.validation.review_complete ? '完成' : '未完成' }}</p>
                  <p>原图 SHA256：<code>{{ legacyResult.source.image_sha256 }}</code></p>
                  <p>Prompt：{{ legacyResult.execution.prompt_version }}</p>
                  <p v-if="legacyResult.source.research">用研来源：{{ legacyResult.source.research.preferences.map((item) => item.user_name).join('、') }} · {{ legacyResult.source.research.source_path }}</p>
                </div>
              </div>
              <a-alert v-if="legacyResult.validation.schema_issues.length" type="error" show-icon message="结构校验问题" :description="legacyResult.validation.schema_issues.slice(0, 8).join('；')" />
              <a-alert v-if="legacyResult.validation.protocol_issues.length" type="error" show-icon message="基础关系问题" :description="legacyResult.validation.protocol_issues.slice(0, 8).join('；')" />
              <a-alert v-if="legacyResult.validation.review_issues.length" type="info" show-icon message="复核未闭合" :description="legacyResult.validation.review_issues.join('；')" />
              <h3>对象与可见 CMF</h3>
              <p v-if="!objects.length">模型没有返回可展示的对象；请查看原始 JSON 和校验问题。</p>
              <article v-for="(object, index) in objects" :key="index" class="d02-object">
                <div class="d02-object-head"><strong>对象 {{ index + 1 }} · 类型 {{ object.t }}</strong><code>c: {{ object.c }}</code></div>
                <small>原始几何坐标：{{ object.g?.join(', ') }}</small>
                <div v-if="observationsByObject(index).length" class="d02-observations">
                  <div v-for="item in observationsByObject(index)" :key="item.field_id" class="d02-observation">
                    <span>{{ item.field_name }} <small>{{ item.field_id }}</small></span>
                    <strong>{{ item.value }}</strong>
                    <a-tag :color="reviewByKey.get(`${index}:${item.field_id}`)?.verdict === 'supported' ? 'green' : reviewByKey.get(`${index}:${item.field_id}`)?.verdict === 'contradicted' ? 'red' : 'default'">{{ verdictText(reviewByKey.get(`${index}:${item.field_id}`)?.verdict) }}</a-tag>
                    <small v-if="reviewByKey.get(`${index}:${item.field_id}`)?.reason">{{ reviewByKey.get(`${index}:${item.field_id}`)?.reason }}</small>
                  </div>
                </div>
                <p v-else>此对象没有可解码的核心局部 CMF 观察。</p>
              </article>
            </div>
            <div v-else-if="tab === 'raw' && r5Result" class="d02-content">
              <h3>Sol R5 完整结构结果</h3><pre>{{ JSON.stringify(r5Result.r5_result, null, 2) }}</pre>
              <h3>主提取原回复</h3><pre>{{ r5Result.raw_responses.primary }}</pre>
              <h3>困难项复核原回复</h3><pre>{{ r5Result.raw_responses.focus || '未执行或未完成' }}</pre>
              <small>调用记录：{{ r5Result.execution.trace_dir }}</small>
            </div>
            <div v-else-if="tab === 'raw' && legacyResult" class="d02-content">
              <h3>R17 模型候选</h3><pre>{{ JSON.stringify(legacyResult.candidate, null, 2) }}</pre>
              <h3>主提取原回复</h3><pre>{{ legacyResult.raw_responses.primary }}</pre>
              <h3>独立复核原回复</h3><pre>{{ legacyResult.raw_responses.review || '未执行' }}</pre>
            </div>
          </template>
        </a-spin>
      </div>
    </div>
  </section>
</template>

<style scoped>
.d02-detail { min-width: 0; }
.d02-content { display: grid; gap: 16px; padding: 20px; }
.d02-content h3 { margin: 0; color: #312c4b; }
.d02-content pre { overflow: auto; max-height: 500px; padding: 14px; border-radius: 12px; background: #f4f2fa; white-space: pre-wrap; word-break: break-word; }
.d02-summary { display: flex; align-items: flex-start; gap: 20px; }
.d02-summary img { width: 140px; max-height: 160px; object-fit: contain; border-radius: 12px; background: #f5f4f9; }
.d02-summary code { word-break: break-all; }
.d02-object { padding: 16px; border: 1px solid #e9e5f2; border-radius: 14px; }
.d02-object-head { display: flex; justify-content: space-between; margin-bottom: 6px; }
.d02-observations { display: grid; gap: 8px; margin-top: 12px; }
.d02-observation { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(100px, 1fr) auto; align-items: center; gap: 8px; }
.d02-observation > small { grid-column: 1 / -1; }
@media (max-width: 800px) { .d02-summary { flex-direction: column; } .d02-observation { grid-template-columns: 1fr auto; } }
</style>
