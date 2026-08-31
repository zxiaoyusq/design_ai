<script setup lang="ts">
import { computed } from 'vue'

import { displayScalar, fieldLabel, isRecord } from './resultFormat'

defineOptions({ name: 'DataValue' })

const props = withDefaults(
  defineProps<{
    value: unknown
    depth?: number
  }>(),
  { depth: 0 },
)

const recordEntries = computed(() => (isRecord(props.value) ? Object.entries(props.value) : []))
const isPrimitiveArray = computed(
  () => Array.isArray(props.value) && props.value.every((item) => !isRecord(item) && !Array.isArray(item)),
)
</script>

<template>
  <span v-if="value === null || value === undefined || value === ''" class="data-empty">未提供</span>
  <span v-else-if="typeof value === 'boolean'" class="data-boolean" :class="{ positive: value }">
    {{ displayScalar(value) }}
  </span>
  <span v-else-if="typeof value === 'number'" class="data-number">{{ displayScalar(value) }}</span>
  <span v-else-if="typeof value === 'string'" class="data-text">{{ displayScalar(value) }}</span>

  <div v-else-if="isPrimitiveArray" class="data-tags">
    <template v-if="(value as unknown[]).length">
      <span v-for="(item, index) in (value as unknown[])" :key="index">{{ displayScalar(item) }}</span>
    </template>
    <span v-else class="data-empty">暂无</span>
  </div>

  <div v-else-if="Array.isArray(value)" class="data-list" :class="{ compact: depth > 1 }">
    <article v-for="(item, index) in value" :key="index" class="data-list-item">
      <span class="data-item-index">{{ index + 1 }}</span>
      <DataValue :value="item" :depth="depth + 1" />
    </article>
    <span v-if="!value.length" class="data-empty">暂无</span>
  </div>

  <div v-else-if="recordEntries.length" class="data-field-grid" :class="{ compact: depth > 0 }">
    <div v-for="([key, item]) in recordEntries" :key="key" class="data-field">
      <span class="data-field-label">{{ fieldLabel(key) }}</span>
      <DataValue :value="item" :depth="depth + 1" />
    </div>
  </div>

  <span v-else class="data-empty">暂无</span>
</template>
