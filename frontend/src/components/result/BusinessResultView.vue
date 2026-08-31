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
const primaryStyle = computed(() => asRecord(style.value.primary))
const secondaryStyles = computed(() => asRecordList(style.value.secondary))
const extraStyleFields = computed(() =>
  omitFields(style.value, ['status', 'primary', 'secondary', 'keywords', 'evidence', 'conflict_note']),
)
const keyDna = computed(() => asRecordList(props.data.key_dna))
const semanticProfile = computed(() => Object.entries(asRecord(props.data.semantic_profile)))
const uncertainFields = computed(() => asRecordList(props.data.uncertain_fields))
const novelDna = computed(() => (Array.isArray(props.data.novel_dna) ? props.data.novel_dna : []))
const quality = computed(() => asRecord(props.data.quality))
const extraRootFields = computed(() =>
  pickExtraFields(props.data, [
    'schema_version',
    'model_id',
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
        <div><span>02</span><div><h4>风格判定</h4><p>主风格、次要风格及视觉依据</p></div></div>
        <span class="status-pill">{{ displayScalar(style.status) }}</span>
      </div>

      <div class="style-primary-card">
        <div>
          <span>一级风格</span>
          <strong>{{ primaryStyle.level_1 || '待判定' }}</strong>
        </div>
        <div>
          <span>二级风格</span>
          <strong>{{ primaryStyle.level_2 || '待判定' }}</strong>
        </div>
        <div class="confidence-meter">
          <span>匹配度</span>
          <a-progress :percent="toPercent(primaryStyle.match_score)" :show-info="false" stroke-color="#8b79b9" />
          <b>{{ toPercent(primaryStyle.match_score) }}%</b>
        </div>
        <div class="confidence-meter">
          <span>置信度 · {{ displayScalar(primaryStyle.confidence) }}</span>
          <a-progress :percent="toPercent(primaryStyle.confidence_score)" :show-info="false" stroke-color="#c58f73" />
          <b>{{ toPercent(primaryStyle.confidence_score) }}%</b>
        </div>
      </div>

      <div class="result-inline-group">
        <span>风格关键词</span>
        <div class="data-tags">
          <span v-for="keyword in asStringList(style.keywords)" :key="keyword">{{ keyword }}</span>
          <span v-if="!asStringList(style.keywords).length" class="data-empty">暂无</span>
        </div>
      </div>

      <div v-if="asStringList(style.evidence).length" class="evidence-callout">
        <span>判定依据</span>
        <p v-for="item in asStringList(style.evidence)" :key="item">{{ item }}</p>
      </div>

      <div v-if="hasContent(style.conflict_note)" class="result-note">
        <span>冲突说明</span><p>{{ displayScalar(style.conflict_note) }}</p>
      </div>

      <div class="subsection-block">
        <h5>次要风格</h5>
        <div v-if="secondaryStyles.length" class="result-card-grid">
          <article v-for="(item, index) in secondaryStyles" :key="index" class="mini-data-card">
            <strong>{{ item.level_2 || item.level_1 || `次要风格 ${index + 1}` }}</strong>
            <DataValue :value="item" />
          </article>
        </div>
        <div v-else class="inline-empty">未识别到需要单列的次要风格</div>
      </div>

      <DataValue
        v-if="hasContent(itemBody(primaryStyle, ['level_1', 'level_2', 'match_score', 'confidence', 'confidence_score']))"
        :value="itemBody(primaryStyle, ['level_1', 'level_2', 'match_score', 'confidence', 'confidence_score'])"
      />
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
          <strong>{{ item.value || '未提供' }}</strong>
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
        <div><span>05</span><div><h4>不确定项</h4><p>仍需更多视角或信息才能确认的字段</p></div></div>
        <b class="count-badge warning">{{ uncertainFields.length }} 项</b>
      </div>
      <div v-if="uncertainFields.length" class="uncertain-list">
        <article v-for="(item, index) in uncertainFields" :key="index" class="uncertain-card">
          <div>
            <span>{{ item.field_name || `不确定项 ${index + 1}` }}</span>
            <strong>{{ item.best_estimate || '暂无可靠判断' }}</strong>
          </div>
          <div class="uncertain-score">
            <small>{{ displayScalar(item.confidence) }}</small>
            <b>{{ toPercent(item.confidence_score) }}%</b>
          </div>
          <DataValue :value="itemBody(item, ['field_name', 'best_estimate', 'confidence', 'confidence_score'])" />
        </article>
      </div>
      <div v-else class="inline-empty positive">未发现需要特别确认的不确定项</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>06</span><div><h4>新 DNA 候选</h4><p>知识库外、值得进一步沉淀的设计特征</p></div></div>
      </div>
      <DataValue v-if="novelDna.length" :value="novelDna" />
      <div v-else class="inline-empty">本次未发现知识库外的新 DNA 候选</div>
    </section>

    <section class="result-section-card">
      <div class="result-section-heading">
        <div><span>07</span><div><h4>结果质量</h4><p>本次提取的可靠性与完整性</p></div></div>
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
