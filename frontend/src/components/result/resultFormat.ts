export type DataRecord = Record<string, unknown>

const FIELD_LABELS: Record<string, string> = {
  schema_version: '数据结构版本',
  source_schema_version: '来源数据结构版本',
  source_knowledge_base_version: '来源知识库版本',
  model_id: '生成模型',
  knowledge_base_version: '知识库版本',
  object: '目标物品',
  object_id: '物品标识',
  category: '品类',
  subcategory: '细分类',
  view: '拍摄视角',
  image_usability: '图片可用性',
  design_summary: '设计摘要',
  style: '风格结论',
  status: '状态',
  classification_status: '分类状态',
  tags: '已确认同层标签',
  style_tags: '已确认同层标签',
  tag_kind: '标签类型',
  facet_ids: '关联审美分面',
  dominance: '视觉占比',
  regions: '作用区域',
  feature_hits: '关键特征命中',
  composition_summary: '标签组合说明',
  derived_presets: '派生风格组合',
  derived_style_presets: '派生风格组合',
  preset_id: '组合标识',
  matched_style_ids: '命中的原子标签',
  pairwise_arbitrations: '标签两两仲裁',
  style_id_a: '风格标签 A',
  style_id_b: '风格标签 B',
  relation: '标签关系',
  scope: '作用范围',
  decision: '仲裁结论',
  primary: '主风格',
  primary_style: '主风格',
  secondary: '次要风格',
  secondary_styles: '次要风格',
  level_1: '一级风格',
  level_2: '二级风格',
  style_id: '稳定风格标识',
  parent_style_id: '一级导航标识',
  label_en: '英文标签',
  label_zh: '中文标签',
  display_name: '显示名称',
  aliases: '兼容别名',
  match_score: '匹配度',
  confidence: '置信等级',
  confidence_score: '置信度',
  keywords: '风格关键词',
  evidence: '判定依据',
  evidence_refs: '证据引用',
  conflict_note: '冲突说明',
  key_dna: '关键设计 DNA',
  group: '设计维度',
  name: 'DNA 名称',
  value: '提取值',
  design_role: '设计作用',
  inference_note: '推断说明',
  region: '所在区域',
  semantic_profile: '语义坐标',
  uncertain_fields: '不确定字段',
  field_id: '字段标识',
  field_name: '字段名称',
  source_path: '来源路径',
  best_estimate: '当前最佳判断',
  reason_type: '不确定原因类型',
  reason: '判断说明',
  needed_view: '建议补充视角',
  recommended_additional_view_or_info: '建议补充的视角或信息',
  candidate_values: '候选值',
  probability: '可能性',
  supporting_evidence_refs: '支持证据',
  contradicting_evidence_refs: '冲突证据',
  novel_dna: '新 DNA 候选',
  novel_dna_elements: '新 DNA 候选',
  quality: '结果质量',
  quality_summary: '质量摘要',
  overall_confidence: '整体置信等级',
  overall_confidence_score: '整体置信度',
  style_confidence: '风格置信度',
  visible_coverage: '可见区域覆盖度',
  warnings: '质量提醒',
  missing_critical_fields: '缺失关键字段',
  target_object: '目标物品',
  selection_basis: '选择依据',
  selection_confidence: '目标选择置信度',
  bbox_norm: '目标位置（归一化）',
  visible_regions: '可见区域',
  ignored_content: '忽略内容',
  image_quality: '图片质量',
  overall_quality: '整体画质',
  object_visible_ratio: '物品可见比例',
  occlusion_level: '遮挡程度',
  blur_level: '模糊程度',
  exposure_risk: '曝光风险',
  perspective_distortion: '透视畸变',
  background_interference: '背景干扰',
  lighting_bias: '光照偏差',
  color_reliability: '颜色可靠性',
  material_reliability: '材质可靠性',
  notes: '补充说明',
  module_applicability: '模块适用性',
  active_profiles: '已激活 Profile',
  applicable_modules: '适用模块',
  excluded_modules: '排除模块',
  rule_adaptations: '规则调整',
  module_id: '模块标识',
  module_name: '模块名称',
  explanation: '解释',
  style_result: '风格判定',
  candidate_ranking: '候选风格排名',
  candidates: '候选风格',
  rank: '排名',
  candidate_status: '候选状态',
  hard_rule_passed: '硬规则通过',
  rule_coverage: '规则覆盖率',
  applicable_rule_count: '适用规则数',
  passed_rule_count: '通过规则数',
  failed_rule_count: '失败规则数',
  unknown_rule_count: '未知规则数',
  not_applicable_rule_count: '不适用规则数',
  color_requirement: '色彩要求',
  core_feature_hits: '核心特征命中',
  auxiliary_feature_hits: '辅助特征命中',
  missing_required_items: '缺失必需项',
  exclusion_hits: '排除条件命中',
  conflict_arbitration: '冲突裁定',
  main_support: '主要支持项',
  main_conflicts: '主要冲突项',
  design_elements: '设计元素',
  original_md_dimensions: '兼容基础维度',
  extended_dna_modules: '规范 DNA 模块',
  dimension: '设计维度',
  elements: '元素明细',
  schema_source: 'Schema 来源',
  raw_visual_description: '原始视觉描述',
  value_type: '值类型',
  applicability: '适用性',
  applicability_status: '适用状态',
  observability: '可观察性',
  computation_status: '计算状态',
  evidence_mode: '证据模式',
  evidence_id: '证据标识',
  description: '证据描述',
  visual_cues: '视觉线索',
  supports: '支持字段',
  mean_confidence: '平均置信度',
  low_confidence_field_count: '低置信字段数',
  concise_summary: '简要结论',
  temp_id: '候选标识',
  existing_field_id: '既有字段标识',
}

const VALUE_LABELS: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  clear: '清晰',
  partial: '部分可见',
  poor: '较差',
  good: '良好',
  excellent: '优秀',
  front: '正面',
  rear: '背面',
  back: '背面',
  side: '侧面',
  top: '顶部',
  unknown: '未知',
  applicable: '适用',
  not_applicable: '不适用',
  limited: '受限',
  visible: '可见',
  inferred: '推断',
  direct: '直接观察',
  derived: '派生计算',
  observed: '已观察',
  not_observable: '当前不可见',
  computed: '已计算',
  not_computable: '缺少计算条件',
  not_requested: '无需计算',
  none: '确认不存在',
  provisional: '暂定',
  unclassified: '未分类',
  reference_computed: '参考集计算',
  completed: '已完成',
  confirmed: '已确认',
  rejected: '已排除',
  pass: '通过',
  fail: '未通过',
  atomic: '原子标签',
  compatible: '可兼容',
  exclusive: '互斥',
  conditional: '条件兼容',
  global: '全局',
  same_region_same_mechanism: '同区域同机制',
  cross_region_or_mechanism: '跨区域或独立机制',
  coexist: '允许共存',
  reject_a: '排除标签 A',
  reject_b: '排除标签 B',
  unresolved: '未解决',
  matched: '已匹配',
  no_match: '未匹配',
}

export function isRecord(value: unknown): value is DataRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asRecord(value: unknown): DataRecord {
  return isRecord(value) ? value : {}
}

export function asRecordList(value: unknown): DataRecord[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

export function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

/** 将机器字段名转换为界面可读标签；未知字段仍会自动生成标签，避免 Schema 扩展后漏显。 */
export function fieldLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function displayScalar(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)))
  if (typeof value === 'string') return VALUE_LABELS[value.toLowerCase()] ?? value
  return String(value)
}

/** 结果中比例可能以 0~1 或 0~100 表示，此处统一为进度条所需的百分值。 */
export function toPercent(value: unknown): number {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.round(Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric)))
}

export function omitFields(record: DataRecord, keys: string[]): DataRecord {
  const excluded = new Set(keys)
  return Object.fromEntries(Object.entries(record).filter(([key]) => !excluded.has(key)))
}

export function pickExtraFields(record: DataRecord, knownKeys: string[]): DataRecord {
  return omitFields(record, knownKeys)
}

export function hasContent(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false
  if (Array.isArray(value)) return value.length > 0
  if (isRecord(value)) return Object.keys(value).length > 0
  return true
}
