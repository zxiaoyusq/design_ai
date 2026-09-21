<script setup lang="ts">
import { computed } from 'vue'

import DataValue from './DataValue.vue'
import {
  asRecord,
  asRecordList,
  displayScalar,
  hasContent,
  omitFields,
  pickExtraFields,
  toPercent,
  type DataRecord,
} from './resultFormat'

const props = defineProps<{ data: DataRecord }>()

const targetObject = computed(() => asRecord(props.data.target_object))
const imageQuality = computed(() => asRecord(props.data.image_quality))
const modules = computed(() => asRecord(props.data.module_applicability))
const styleResult = computed(() => asRecord(props.data.style_result))
const styleCandidates = computed(() => {
  const current = asRecordList(styleResult.value.style_candidates)
  if (current.length) return current
  // v1.1 历史结果优先展示当时已确认标签；没有确认项时回退到历史候选排名。
  const legacyTags = asRecordList(styleResult.value.style_tags)
  return legacyTags.length ? legacyTags : asRecordList(styleResult.value.candidate_ranking)
})
const derivedPresets = computed(() => asRecordList(styleResult.value.derived_style_presets))
const extraStyleFields = computed(() =>
  omitFields(styleResult.value, [
    'style_candidates',
    'style_tags',
    'candidate_ranking',
    'classification_status',
    'pairwise_arbitrations',
    'derived_style_presets',
    'composition_summary',
  ]),
)
const designElements = computed(() => asRecord(props.data.design_elements))
const dimensions = computed(() => asRecordList(designElements.value.original_md_dimensions))
const extendedModules = computed(() => asRecordList(designElements.value.extended_dna_modules))
const evidence = computed(() => asRecordList(props.data.evidence))
const novelDna = computed(() => (Array.isArray(props.data.novel_dna_elements) ? props.data.novel_dna_elements : []))
const quality = computed(() => asRecord(props.data.quality_summary))
const extraRootFields = computed(() =>
  pickExtraFields(props.data, [
    'schema_version',
    'knowledge_base_version',
    'target_object',
    'image_quality',
    'module_applicability',
    'style_result',
    'design_elements',
    'uncertain_fields',
    'novel_dna_elements',
    'evidence',
    'quality_summary',
  ]),
)

function without(record: DataRecord, keys: string[]) {
  return omitFields(record, keys)
}
</script>

<template>
  <div class="structured-result detail-result">
    <section class="result-hero-card detail-hero">
      <div class="result-hero-copy">
        <span class="section-kicker">完整提取详情</span>
        <h3>{{ targetObject.category || '目标物品' }}<template v-if="targetObject.subcategory"> · {{ targetObject.subcategory }}</template></h3>
        <p>{{ quality.concise_summary || '完整呈现目标选择、图片质量、设计元素、风格规则与可定位证据。' }}</p>
        <div class="version-tags">
          <span>Schema {{ data.schema_version || '—' }}</span>
          <span>知识库 {{ data.knowledge_base_version || '—' }}</span>
        </div>
      </div>
      <div class="result-hero-score">
        <a-progress
          type="circle"
          :percent="toPercent(quality.mean_confidence)"
          :size="78"
          :stroke-width="9"
          stroke-color="#7462a8"
        />
        <span>平均置信度</span>
      </div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>01</span><div><h4>目标物品</h4><p>主物品选择、范围与可见区域</p></div></div>
      </div>
      <DataValue :value="targetObject" />
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>02</span><div><h4>图片质量</h4><p>影响视觉判断可靠性的图像条件</p></div></div>
        <span class="status-pill">{{ displayScalar(imageQuality.overall_quality) }}</span>
      </div>
      <DataValue :value="imageQuality" />
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>03</span><div><h4>模块适用性</h4><p>本次启用、排除及调整的 DNA 规则模块</p></div></div>
      </div>
      <div class="module-columns">
        <div class="module-group">
          <h5>适用模块 <span>{{ asRecordList(modules.applicable_modules).length }}</span></h5>
          <DataValue :value="modules.applicable_modules" />
        </div>
        <div class="module-group muted">
          <h5>排除模块 <span>{{ asRecordList(modules.excluded_modules).length }}</span></h5>
          <DataValue :value="modules.excluded_modules" />
        </div>
      </div>
      <div v-if="hasContent(modules.rule_adaptations)" class="subsection-block">
        <h5>规则调整</h5>
        <DataValue :value="modules.rule_adaptations" />
      </div>
      <DataValue
        v-if="hasContent(without(modules, ['applicable_modules', 'excluded_modules', 'rule_adaptations']))"
        :value="without(modules, ['applicable_modules', 'excluded_modules', 'rule_adaptations'])"
      />
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>04</span><div><h4>扁平多标签风格候选</h4><p>真实候选排名、支持与冲突，以及基于候选命中的组合</p></div></div>
        <b class="count-badge">{{ styleCandidates.length }} 项</b>
      </div>

      <div v-if="styleCandidates.length" class="candidate-list">
        <article v-for="candidate in styleCandidates" :key="String(candidate.style_id)" class="candidate-card">
          <div class="candidate-rank">{{ candidate.rank }}</div>
          <div>
          <div class="style-tag-head">
            <div>
              <span>{{ candidate.style_id }}</span>
              <strong>{{ candidate.label_zh || candidate.label_en || '未命名风格' }}</strong>
              <small v-if="candidate.label_en">{{ candidate.label_en }}</small>
            </div>
          </div>
          <div class="style-score-row">
            <div class="confidence-meter">
              <span>匹配度</span>
              <a-progress :percent="toPercent(candidate.match_score)" :show-info="false" stroke-color="#8b79b9" />
              <b>{{ toPercent(candidate.match_score) }}%</b>
            </div>
            <div class="confidence-meter">
              <span>置信度</span>
              <a-progress :percent="toPercent(candidate.confidence)" :show-info="false" stroke-color="#c58f73" />
              <b>{{ toPercent(candidate.confidence) }}%</b>
            </div>
          </div>
          <DataValue :value="without(candidate, ['rank', 'style_id', 'label_zh', 'label_en', 'match_score', 'confidence'])" />
          </div>
        </article>
      </div>
      <div v-else class="inline-empty">当前图片没有可输出的风格候选</div>

      <div class="result-note">
        <span>组合说明</span>
        <p>{{ displayScalar(styleResult.composition_summary) }}</p>
      </div>

      <div class="subsection-block">
        <h5>确定性派生的风格组合</h5>
        <div v-if="derivedPresets.length" class="result-card-grid">
          <article v-for="item in derivedPresets" :key="String(item.preset_id)" class="mini-data-card">
            <strong>{{ item.label_zh || item.label_en || item.preset_id }}</strong>
            <DataValue :value="item" />
          </article>
        </div>
        <div v-else class="inline-empty">当前原子标签组合未命中命名预设</div>
      </div>

      <DataValue v-if="hasContent(extraStyleFields)" :value="extraStyleFields" />
    </section>

    <section class="result-section-card design-elements-section">
      <div class="result-section-heading">
        <div><span>05</span><div><h4>设计元素</h4><p>多标签 Skill 的规范扩展 DNA 模块逐字段结果</p></div></div>
        <b class="count-badge">{{ dimensions.length + extendedModules.length }} 组</b>
      </div>

      <div v-if="dimensions.length" class="element-family">
        <h5>基础设计维度</h5>
        <a-collapse ghost>
          <a-collapse-panel v-for="(dimension, index) in dimensions" :key="`dimension-${index}`">
            <template #header>
              <div class="collapse-heading">
                <strong>{{ dimension.dimension || `设计维度 ${index + 1}` }}</strong>
                <span>{{ asRecordList(dimension.elements).length }} 个字段</span>
              </div>
            </template>
            <DataValue :value="without(dimension, ['elements'])" />
            <div class="element-card-list">
              <article v-for="(item, itemIndex) in asRecordList(dimension.elements)" :key="itemIndex" class="element-card">
                <div class="element-card-title">
                  <span>{{ item.field_name || `字段 ${itemIndex + 1}` }}</span>
                  <small>{{ displayScalar(item.confidence) }}</small>
                </div>
                <DataValue :value="item" />
              </article>
            </div>
          </a-collapse-panel>
        </a-collapse>
      </div>

      <div class="element-family">
        <h5>扩展 DNA 模块</h5>
        <a-collapse v-if="extendedModules.length" ghost>
          <a-collapse-panel v-for="(module, index) in extendedModules" :key="`module-${index}`">
            <template #header>
              <div class="collapse-heading">
                <strong>{{ module.module_name || module.module_id || `扩展模块 ${index + 1}` }}</strong>
                <span>{{ asRecordList(module.elements).length }} 个字段</span>
              </div>
            </template>
            <DataValue :value="without(module, ['elements'])" />
            <div class="element-card-list">
              <article v-for="(item, itemIndex) in asRecordList(module.elements)" :key="itemIndex" class="element-card">
                <div class="element-card-title">
                  <span>{{ item.field_name || `字段 ${itemIndex + 1}` }}</span>
                  <small>{{ displayScalar(item.confidence) }}</small>
                </div>
                <DataValue :value="item" />
              </article>
            </div>
          </a-collapse-panel>
        </a-collapse>
        <div v-else class="inline-empty">暂无扩展 DNA 模块</div>
      </div>

      <DataValue
        v-if="hasContent(without(designElements, ['original_md_dimensions', 'extended_dna_modules']))"
        :value="without(designElements, ['original_md_dimensions', 'extended_dna_modules'])"
      />
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>06</span><div><h4>新 DNA 候选</h4><p>尚未收录进知识库的视觉特征候选</p></div></div>
      </div>
      <DataValue v-if="novelDna.length" :value="novelDna" />
      <div v-else class="inline-empty">本次未发现知识库外的新 DNA 候选</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>07</span><div><h4>可定位证据</h4><p>连接图片区域与提取结论的证据记录</p></div></div>
        <b class="count-badge">{{ evidence.length }} 条</b>
      </div>
      <div v-if="evidence.length" class="evidence-card-list">
        <article v-for="(item, index) in evidence" :key="index" class="evidence-card">
          <div class="evidence-card-index">{{ String(index + 1).padStart(2, '0') }}</div>
          <div>
            <strong>{{ item.region || item.evidence_id || `证据 ${index + 1}` }}</strong>
            <DataValue :value="item" />
          </div>
        </article>
      </div>
      <div v-else class="inline-empty">暂无可定位证据</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>08</span><div><h4>质量汇总</h4><p>结果完整度、低置信字段与质量提醒</p></div></div>
      </div>
      <DataValue :value="quality" />
    </section>

    <section v-if="hasContent(extraRootFields)" class="result-section-card">
      <div class="result-section-heading">
        <div><span>+</span><div><h4>其他信息</h4><p>当前版本新增的结果字段</p></div></div>
      </div>
      <DataValue :value="extraRootFields" />
    </section>
  </div>
</template>
