<script setup lang="ts">
import { computed } from 'vue'
import {
  CheckCircleOutlined,
  LoadingOutlined,
  MessageOutlined,
  RobotOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'

import type {
  ExtractionDiagnostic,
  ExtractionProgressEvent,
  ExtractionStage,
  ExtractionTask,
  ExtractionTaskItem,
  ModelInfo,
} from '@/types/dna'

const props = defineProps<{
  models: ModelInfo[]
  selectedCount: number
  selectedModelId: string
  prompt: string
  task: ExtractionTask | null
  running: boolean
}>()

const emit = defineEmits<{
  'update:selectedModelId': [value: string]
  'update:prompt': [value: string]
  start: []
}>()

const canStart = computed(
  () => props.selectedCount > 0 && Boolean(props.selectedModelId) && !props.running,
)

const taskStatusText = computed(() => {
  const labels: Record<string, string> = {
    queued: '任务已进入队列',
    running: 'DeepAgent 正在并行提取设计 DNA',
    completed: '全部图片提取完成',
    partial: '任务完成，部分图片需要检查',
    failed: '任务未能完成',
  }
  return props.task ? labels[props.task.status] : ''
})

function itemStatusLabel(status: string) {
  return {
    pending: '等待中',
    running: '提取中',
    completed: '已完成',
    failed: '失败',
  }[status]
}

function diagnosticLabel(item: ExtractionDiagnostic) {
  if (item.code.startsWith('FIELD_')) return '字段规则'
  if (item.code.startsWith('STYLE_')) return '风格证据'
  if (item.code.startsWith('REGION_')) return '区域声明'
  if (item.code.includes('SCHEMA')) return '结构校验'
  return '语义校验'
}

function diagnosticTarget(item: ExtractionDiagnostic) {
  const target = item.field_id || item.style_id || item.evidence_id || item.final_path
  return target === item.message ? '' : target
}

const stageLabels: Record<ExtractionStage, string> = {
  queued: '等待执行',
  preparing: '准备环境',
  model_analysis: '图片分析',
  parsing: '解析结果',
  compiling: '确定性整理',
  semantic_review: '风格复核',
  repairing: '局部修复',
  validating: '最终校验',
  generating_view: '生成业务视图',
  finalizing: '保存结果',
  completed: '已完成',
  failed: '已失败',
}

function recentEvents(item: ExtractionTaskItem) {
  return item.events.slice(-10)
}

function eventTime(event: ExtractionProgressEvent) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(event.created_at))
}

function errorSummary(item: ExtractionTaskItem) {
  if (item.diagnostics.length) {
    return `发现 ${item.diagnostics.length} 项未闭合规则，未写入结果。`
  }
  const error = item.error?.toLowerCase() ?? ''
  if (error.includes('524') || error.includes('timeout') || error.includes('timed out')) {
    return '远程模型服务响应超时，未生成可供最终校验的完整结果。'
  }
  return '提取流程异常结束，请查看错误详情。'
}
</script>

<template>
  <section class="workspace-card composer-panel">
    <div class="section-heading compact">
      <div>
        <span class="eyebrow">02 / 描述任务</span>
        <h2>告诉 Agent 你关注什么</h2>
        <p>可补充品类、业务场景或希望重点观察的区域。</p>
      </div>
      <div class="skill-chip">
        <span class="status-dot"></span>
        Multi-tag Design DNA Skill
      </div>
    </div>

    <div class="model-field">
      <label for="model-select">推理模型</label>
      <a-select
        id="model-select"
        :value="selectedModelId"
        size="large"
        placeholder="选择模型"
        :options="
          models.map((model) => ({
            value: model.id,
            label: model.name,
            provider: model.model_provider,
          }))
        "
        @update:value="emit('update:selectedModelId', $event)"
      >
        <template #option="option">
          <div class="model-option">
            <span>{{ option.label }}</span>
            <small>{{ option.provider }}</small>
          </div>
        </template>
      </a-select>
    </div>

    <div class="chat-box">
      <div class="agent-avatar"><RobotOutlined /></div>
      <div class="chat-content">
        <div class="chat-label"><MessageOutlined /> 用户具体要求</div>
        <a-textarea
          :value="prompt"
          :rows="6"
          :maxlength="4000"
          show-count
          placeholder="例如：这是一组户外运动产品，请重点关注防护结构、材质关系和动感语义；背景道具不要纳入分析。"
          @update:value="emit('update:prompt', $event)"
        />
      </div>
    </div>

    <div class="run-bar">
      <div class="selection-summary">
        <span>{{ selectedCount }}</span>
        张图片将并行提取，最多同时 4 张
      </div>
      <a-button
        type="primary"
        size="large"
        class="run-button"
        :disabled="!canStart"
        :loading="running"
        @click="emit('start')"
      >
        {{ running ? 'Agent 执行中' : '确认并开始提取' }}
      </a-button>
    </div>

    <div v-if="task" class="task-progress">
      <div class="task-progress-head">
        <div>
          <LoadingOutlined v-if="running" spin />
          <CheckCircleOutlined v-else-if="task.status === 'completed'" />
          <WarningOutlined v-else />
          <strong>{{ taskStatusText }}</strong>
        </div>
        <span>{{ task.progress }}% · 阶段估算</span>
      </div>
      <a-progress
        :percent="task.progress"
        :show-info="false"
        :status="task.status === 'failed' ? 'exception' : 'active'"
        stroke-color="#6257d8"
      />
      <div class="task-items">
        <div v-for="item in task.items" :key="item.image_id" class="task-item">
          <span class="task-item-name">{{ item.filename }}</span>
          <span :class="['task-status', item.status]">
            {{ itemStatusLabel(item.status) }}
          </span>
          <div v-if="item.events.length" class="task-log" aria-live="polite">
            <div class="task-log-head">
              <span>实时执行记录</span>
              <strong>{{ stageLabels[item.stage] }} · {{ item.stage_progress }}%</strong>
            </div>
            <ol>
              <li
                v-for="(event, index) in recentEvents(item)"
                :key="`${event.created_at}-${event.stage}-${index}`"
                :class="event.level"
              >
                <time>{{ eventTime(event) }}</time>
                <span class="task-log-dot"></span>
                <p>{{ event.message }}</p>
              </li>
            </ol>
          </div>
          <div v-if="item.error" class="task-diagnostics">
            <p>{{ errorSummary(item) }}</p>
            <details>
              <summary>查看诊断详情</summary>
              <ul v-if="item.diagnostics.length">
                <li v-for="(diagnostic, index) in item.diagnostics" :key="`${diagnostic.code}-${index}`">
                  <span>{{ diagnosticLabel(diagnostic) }}</span>
                  <strong v-if="diagnosticTarget(diagnostic)">{{ diagnosticTarget(diagnostic) }}</strong>
                  <p>{{ diagnostic.message }}</p>
                </li>
              </ul>
              <pre v-else>{{ item.error }}</pre>
              <code v-if="item.diagnostic_id">诊断编号：{{ item.diagnostic_id }}</code>
            </details>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
