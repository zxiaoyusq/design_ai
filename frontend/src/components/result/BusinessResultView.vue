<script setup lang="ts">
import { computed } from 'vue'

import DataValue from './DataValue.vue'
import {
  asRecord,
  asRecordList,
  asStringList,
  displayScalar,
  hasContent,
  omitFields,
  pickExtraFields,
  toPercent,
  type DataRecord,
} from './resultFormat'

const props = defineProps<{ data: DataRecord }>()

const objectInfo = computed(() => asRecord(props.data.object))
const style = computed(() => asRecord(props.data.style))
const styleCandidates = computed(() => {
  const current = asRecordList(style.value.style_candidates)
  if (current.length) return current
  // 历史多标签业务视图使用 tags；只读回退可避免升级后旧结果显示为空。
  const legacyTags = asRecordList(style.value.tags)
  return legacyTags.length ? legacyTags : asRecordList(style.value.candidates)
})
const derivedPresets = computed(() => asRecordList(style.value.derived_presets))
const extraStyleFields = computed(() =>
  omitFields(style.value, [
    'style_candidates',
    'tags',
    'candidates',
    'derived_presets',
    'composition_summary',
    'keywords',
  ]),
)
const keyDna = computed(() => asRecordList(props.data.key_dna))
const semanticProfile = computed(() => Object.entries(asRecord(props.data.semantic_profile)))
const novelDna = computed(() => (Array.isArray(props.data.novel_dna) ? props.data.novel_dna : []))
const quality = computed(() => asRecord(props.data.quality))
const extraRootFields = computed(() =>
  pickExtraFields(props.data, [
    'schema_version',
    'model_id',
    'source_schema_version',
    'source_knowledge_base_version',
    'object',
    'design_summary',
    'style',
    'key_dna',
    'semantic_profile',
    'uncertain_fields',
    'novel_dna',
    'quality',
  ]),
)

function itemBody(item: DataRecord, headingKeys: string[]) {
  return omitFields(item, headingKeys)
}
</script>

<template>
  <div class="structured-result business-result">
    <section class="result-hero-card">
      <div class="result-hero-copy">
        <span class="section-kicker">设计洞察摘要</span>
        <h3>{{ objectInfo.category || '目标物品' }}<template v-if="objectInfo.subcategory"> · {{ objectInfo.subcategory }}</template></h3>
        <p>{{ data.design_summary || '已完成设计 DNA 提取。' }}</p>
        <div class="version-tags">
          <span>生成模型 {{ data.model_id || '未记录' }}</span>
          <span v-if="data.source_schema_version">Schema {{ data.source_schema_version }}</span>
          <span v-if="data.source_knowledge_base_version">知识库 {{ data.source_knowledge_base_version }}</span>
        </div>
      </div>
      <div class="result-hero-score">
        <a-progress
          type="circle"
          :percent="toPercent(quality.overall_confidence_score)"
          :size="78"
          :stroke-width="9"
          stroke-color="#7462a8"
        />
        <span>整体置信度</span>
      </div>
      <div class="result-version">{{ data.schema_version || '业务视图' }}</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>01</span><div><h4>目标物品</h4><p>提取对象与图片基础信息</p></div></div>
      </div>
      <DataValue :value="objectInfo" />
    </section>

    <section class="result-section-card style-card">
      <div class="result-section-heading">
        <div><span>02</span><div><h4>风格候选</h4><p>按图片中的实际视觉支持排序，不区分确认、主风格或次要风格</p></div></div>
        <b class="count-badge">{{ styleCandidates.length }} 项</b>
      </div>

      <div v-if="styleCandidates.length" class="style-tag-grid">
        <article v-for="candidate in styleCandidates" :key="String(candidate.style_id)" class="style-tag-card">
          <div class="style-tag-head">
            <div>
              <span>#{{ candidate.rank }} · {{ candidate.style_id }}</span>
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
              <span>置信度 · {{ displayScalar(candidate.confidence) }}</span>
              <a-progress :percent="toPercent(candidate.confidence_score)" :show-info="false" stroke-color="#c58f73" />
              <b>{{ toPercent(candidate.confidence_score) }}%</b>
            </div>
          </div>
          <div class="result-inline-group compact-row">
            <span>作用区域</span>
            <div class="data-tags">
              <span v-for="region in asStringList(candidate.regions)" :key="region">{{ region }}</span>
            </div>
          </div>
          <DataValue :value="itemBody(candidate, ['rank', 'style_id', 'label_zh', 'label_en', 'match_score', 'confidence', 'confidence_score', 'regions'])" />
        </article>
      </div>
      <div v-else class="inline-empty">当前图片没有可输出的风格候选</div>

      <div v-if="hasContent(style.composition_summary)" class="result-note">
        <span>组合说明</span><p>{{ displayScalar(style.composition_summary) }}</p>
      </div>

      <div class="result-inline-group">
        <span>风格关键词</span>
        <div class="data-tags">
          <span v-for="keyword in asStringList(style.keywords)" :key="keyword">{{ keyword }}</span>
          <span v-if="!asStringList(style.keywords).length" class="data-empty">暂无</span>
        </div>
      </div>

      <div v-if="derivedPresets.length" class="subsection-block">
        <h5>确定性派生的风格组合</h5>
        <div class="result-card-grid">
          <article v-for="item in derivedPresets" :key="String(item.preset_id)" class="mini-data-card">
            <strong>{{ item.label_zh || item.label_en || item.preset_id }}</strong>
            <DataValue :value="item" />
          </article>
        </div>
      </div>

      <DataValue v-if="hasContent(extraStyleFields)" :value="extraStyleFields" />
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>03</span><div><h4>关键设计 DNA</h4><p>最能定义该物品审美特征的设计元素</p></div></div>
        <b class="count-badge">{{ keyDna.length }} 项</b>
      </div>
      <div v-if="keyDna.length" class="dna-card-grid">
        <article v-for="(item, index) in keyDna" :key="index" class="dna-card">
          <div class="dna-card-head">
            <span>{{ item.group || '设计特征' }}</span>
            <small>{{ displayScalar(item.confidence) }}</small>
          </div>
          <h5>{{ item.name || `DNA ${index + 1}` }}</h5>
          <div class="dna-value"><DataValue :value="item.value" /></div>
          <div class="dna-confidence">
            <a-progress :percent="toPercent(item.confidence_score)" :show-info="false" stroke-color="#8b79b9" />
            <span>{{ toPercent(item.confidence_score) }}%</span>
          </div>
          <DataValue :value="itemBody(item, ['group', 'name', 'value', 'confidence', 'confidence_score'])" />
        </article>
      </div>
      <div v-else class="inline-empty">暂无关键 DNA</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>04</span><div><h4>语义坐标</h4><p>主要审美维度上的相对位置</p></div></div>
      </div>
      <div v-if="semanticProfile.length" class="semantic-grid">
        <div v-for="([label, score]) in semanticProfile" :key="label" class="semantic-item">
          <div><span>{{ label }}</span><b>{{ toPercent(score) }}</b></div>
          <a-progress :percent="toPercent(score)" :show-info="false" stroke-color="#aa90bc" />
        </div>
      </div>
      <div v-else class="inline-empty">暂无语义坐标</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>05</span><div><h4>新 DNA 候选</h4><p>知识库外、值得进一步沉淀的设计特征</p></div></div>
      </div>
      <DataValue v-if="novelDna.length" :value="novelDna" />
      <div v-else class="inline-empty">本次未发现知识库外的新 DNA 候选</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>06</span><div><h4>结果质量</h4><p>本次提取的可靠性与完整性</p></div></div>
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
