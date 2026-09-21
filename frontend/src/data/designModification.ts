/** 设计修改演示的可编辑 DNA 参数；数值用于前端视觉示意，不代表真实物理规格。 */
export interface DesignParams {
  material: 'AG 玻璃' | '亮面玻璃' | '细砂复合材质'
  hue: number
  brightness: number
  saturation: number
  gloss: number
  smoothness: number
  corner: number
  lineAngle: number
}

/** 参数滑块和导入文件共用的数值字段集合。 */
export type NumericParam = Exclude<keyof DesignParams, 'material'>
export type SeriesId = 'hot' | 'note' | 'zero'
export type MarketId = 'southeast' | 'south' | 'africa'
export type ScoreId = 'aesthetic' | 'brand' | 'craft' | 'cost' | 'trend'

/** 单项评分同时携带解释口径和演示知识库编号，供低分定位与依据查看复用。 */
export interface ScoreDimension {
  id: ScoreId
  label: string
  group: string
  weight: number
  value: number
  reason: string
  basis: string
  source: string
}

/** 所有分数由当前参数、系列、年度及市场确定性推导，置信度仅为演示值。 */
export interface ScoreResult {
  total: number
  trendFit: number
  userFit: number
  marketFit: number
  confidence: number
  audience: string
  emotion: string
  risk: '低' | '中' | '高'
  dimensions: ScoreDimension[]
}

/** 浏览器版本快照不含上传文件本体；会话结束后上传图需要重新选择。 */
export interface DesignVersion {
  id: string
  name: string
  createdAt: string
  params: DesignParams
  score: number
  risk: ScoreResult['risk']
  rationale: string
  source: string
  imageSource: string
  seriesId: SeriesId
  marketId: MarketId
  benchmarkYear: 2025 | 2026
  approved?: boolean
  rank?: 1 | 2
}

export const modelVersion = 'front-demo-rule-v1'
export const promptVersion = 'design-modification-demo-v1'

export const renderImages = [
  { id: 'render-1', label: '场景渲染 A', url: new URL('../../../ref/手机图/渲染图/20260917-105548.jpeg', import.meta.url).href, source: 'ref/手机图/渲染图/20260917-105548.jpeg' },
  { id: 'render-2', label: '场景渲染 B', url: new URL('../../../ref/手机图/渲染图/20260917-105555.jpeg', import.meta.url).href, source: 'ref/手机图/渲染图/20260917-105555.jpeg' },
  { id: 'render-3', label: '场景渲染 C', url: new URL('../../../ref/手机图/渲染图/20260917-105559.jpeg', import.meta.url).href, source: 'ref/手机图/渲染图/20260917-105559.jpeg' },
  { id: 'render-4', label: '场景渲染 D', url: new URL('../../../ref/手机图/渲染图/20260917-105604.jpeg', import.meta.url).href, source: 'ref/手机图/渲染图/20260917-105604.jpeg' },
]

export const cmfImages = [
  { id: 'cmf-blue', label: '海蓝 · 斜视', url: new URL('../../../ref/手机图/CMF图/20260917-105703.jpeg', import.meta.url).href, source: 'ref/手机图/CMF图/20260917-105703.jpeg' },
  { id: 'cmf-blue-flat', label: '海蓝 · 正视', url: new URL('../../../ref/手机图/CMF图/20260917-105657.jpeg', import.meta.url).href, source: 'ref/手机图/CMF图/20260917-105657.jpeg' },
  { id: 'cmf-pink', label: '霞粉 · 斜视', url: new URL('../../../ref/手机图/CMF图/20260917-105648.jpeg', import.meta.url).href, source: 'ref/手机图/CMF图/20260917-105648.jpeg' },
  { id: 'cmf-pink-flat', label: '霞粉 · 正视', url: new URL('../../../ref/手机图/CMF图/20260917-105652.jpeg', import.meta.url).href, source: 'ref/手机图/CMF图/20260917-105652.jpeg' },
]

export const initialParams: DesignParams = {
  material: '亮面玻璃', hue: 202, brightness: 62, saturation: 56,
  gloss: 60, smoothness: 68, corner: 24, lineAngle: 18,
}

export const numericParamMeta: { key: NumericParam; label: string; unit: string; min: number; max: number }[] = [
  { key: 'hue', label: '色相', unit: '°', min: 0, max: 360 },
  { key: 'brightness', label: '明度', unit: '%', min: 0, max: 100 },
  { key: 'saturation', label: '饱和度', unit: '%', min: 0, max: 100 },
  { key: 'gloss', label: '光泽', unit: '%', min: 0, max: 100 },
  { key: 'smoothness', label: '形态流畅度', unit: '%', min: 0, max: 100 },
  { key: 'corner', label: 'R 角幅度', unit: '%', min: 0, max: 100 },
  { key: 'lineAngle', label: '线条夹角', unit: '°', min: 0, max: 90 },
]

/** 系列上下限是演示约束；应用建议或对话修改时先钳制参数，保持相同系列的预览口径。 */
export const seriesProfiles: Record<SeriesId, {
  name: string
  tone: string
  audience: string
  target: DesignParams
  limits: Partial<Record<NumericParam, [number, number]>>
  knowledge: string
}> = {
  hot: {
    name: 'HOT 性能系列', tone: '轻快、速度感与高辨识度', audience: '年轻手游与性能体验人群',
    target: { material: 'AG 玻璃', hue: 205, brightness: 65, saturation: 70, gloss: 54, smoothness: 72, corner: 26, lineAngle: 24 },
    limits: { saturation: [38, 88], gloss: [24, 78], corner: [10, 58], lineAngle: [8, 48] },
    knowledge: 'KB-HOT-26 · 演示系列约束',
  },
  note: {
    name: 'NOTE 轻盈系列', tone: '柔和、亲近与精致层次', audience: '日常记录与影像分享人群',
    target: { material: '细砂复合材质', hue: 330, brightness: 76, saturation: 46, gloss: 38, smoothness: 82, corner: 42, lineAngle: 13 },
    limits: { saturation: [18, 72], gloss: [12, 65], corner: [22, 72], lineAngle: [0, 34] },
    knowledge: 'KB-NOTE-26 · 演示系列约束',
  },
  zero: {
    name: 'ZERO 极简系列', tone: '克制、清晰与精密感', audience: '关注简洁品质的城市人群',
    target: { material: 'AG 玻璃', hue: 214, brightness: 55, saturation: 34, gloss: 42, smoothness: 62, corner: 22, lineAngle: 17 },
    limits: { saturation: [8, 56], gloss: [14, 62], corner: [8, 45], lineAngle: [4, 35] },
    knowledge: 'KB-ZERO-26 · 演示系列约束',
  },
}

export const markets: Record<MarketId, { name: string; audience: string; note: string }> = {
  southeast: { name: '东南亚', audience: '年轻内容创作者', note: '偏好轻快配色与清晰识别' },
  south: { name: '南亚', audience: '注重表达与性能的人群', note: '偏好鲜明层次与性能叙事' },
  africa: { name: '非洲', audience: '注重耐用与活力的人群', note: '偏好耐用印象与饱满色彩' },
}

const clamp = (value: number, min = 0, max = 100) => Math.round(Math.min(max, Math.max(min, value)))
const near = (value: number, target: number, tolerance: number) => clamp(100 - Math.abs(value - target) / tolerance * 100)
const hueNear = (value: number, target: number) => near(Math.min(Math.abs(value - target), 360 - Math.abs(value - target)), 0, 180)

export function constrainedParams(params: DesignParams, series: SeriesId): DesignParams {
  const next = { ...params }
  for (const { key, min, max } of numericParamMeta) {
    const [lower, upper] = seriesProfiles[series].limits[key] ?? [min, max]
    next[key] = clamp(next[key], lower, upper)
  }
  return next
}

/** 分数与解释共用同一组确定性规则，避免拖拽后分数和低分定位脱节。 */
export function scoreDesign(params: DesignParams, series: SeriesId, market: MarketId, benchmarkYear: 2025 | 2026 = 2026): ScoreResult {
  const profile = seriesProfiles[series]
  // 2025/2026 两套演示基准仅做轻微参数偏移，用于展示年度切换会改变评分依据。
  const target = benchmarkYear === 2026 ? profile.target : { ...profile.target, saturation: clamp(profile.target.saturation - 8), gloss: clamp(profile.target.gloss - 6) }
  const seriesSource = profile.knowledge.replace('26', String(benchmarkYear).slice(2))
  const hueFit = hueNear(params.hue, target.hue)
  const satFit = near(params.saturation, target.saturation, 85)
  const brightFit = near(params.brightness, target.brightness, 85)
  const formFit = Math.round((near(params.smoothness, target.smoothness, 90) + near(params.corner, target.corner, 75) + near(params.lineAngle, target.lineAngle, 80)) / 3)
  const materialFit = params.material === target.material ? 94 : params.material === '亮面玻璃' ? 72 : 78
  const aesthetic = clamp((hueFit + satFit + brightFit + formFit) / 4)
  const brand = clamp((hueFit + formFit + materialFit) / 3)
  const craft = clamp(92 - Math.max(0, params.gloss - 66) * 0.7 - Math.max(0, params.corner - 60) * 0.5 - Math.max(0, params.lineAngle - 45) * 0.6)
  const cost = clamp(88 - (params.material === '亮面玻璃' ? 14 : 0) - Math.max(0, params.gloss - 60) * 0.45)
  const trend = clamp((hueFit * 0.36 + satFit * 0.35 + formFit * 0.29))
  const dimensions: ScoreDimension[] = [
    { id: 'aesthetic', label: '审美表现', group: '设计 DNA 匹配', weight: 25, value: aesthetic, reason: aesthetic < 75 ? '当前色彩与轮廓参数距离本系列样例较远。' : '色彩和轮廓与本系列样例接近。', basis: '色相、明度、饱和度、流畅度、R 角与线条夹角', source: seriesSource },
    { id: 'brand', label: '品牌一致性', group: '设计 DNA 匹配', weight: 25, value: brand, reason: brand < 75 ? `材质或形态表达与“${profile.tone}”的样例约束有偏差。` : '材质与轮廓延续了系列调性。', basis: `系列调性：${profile.tone}`, source: seriesSource },
    { id: 'craft', label: '工艺可行性', group: '落地风险', weight: 15, value: craft, reason: craft < 75 ? '高光泽、极大 R 角或大夹角增加了示意工艺风险。' : '当前参数处在演示工艺安全区间。', basis: '光泽 ≤ 66、R 角 ≤ 60、夹角 ≤ 45 为演示参考线', source: 'KB-CMF-26 · 演示工艺规则' },
    { id: 'cost', label: '成本合理性', group: '落地风险', weight: 10, value: cost, reason: cost < 75 ? '亮面处理或高光泽增加演示成本负担。' : '所选材料与表面处理接近演示成本目标。', basis: '材质选择与光泽档位', source: 'KB-CMF-26 · 演示成本规则' },
    { id: 'trend', label: '趋势匹配', group: '市场与用户', weight: 25, value: trend, reason: trend < 75 ? '色彩强度或轮廓节奏与演示趋势样本有距离。' : '视觉参数与演示趋势方向接近。', basis: '明快配色、可识别轮廓、情绪表达', source: 'KB-TREND-26 · 演示趋势样本' },
  ]
  const total = clamp(dimensions.reduce((sum, item) => sum + item.value * item.weight / 100, 0))
  const marketBias = market === 'south' ? params.saturation * 0.12 : market === 'africa' ? params.saturation * 0.1 + craft * 0.05 : brightFit * 0.1
  const marketFit = clamp(total * 0.84 + marketBias)
  const userFit = clamp(aesthetic * 0.46 + brand * 0.22 + marketFit * 0.32)
  const risk = Math.min(craft, cost) < 68 ? '高' : Math.min(craft, cost) < 82 ? '中' : '低'
  return {
    total, trendFit: trend, userFit, marketFit, confidence: market === 'africa' ? 63 : market === 'south' ? 67 : 71,
    audience: markets[market].audience, emotion: params.saturation >= 66 ? '活力 · 速度感' : params.brightness >= 68 ? '轻盈 · 亲和' : '克制 · 精致',
    risk, dimensions,
  }
}

export function previewStyle(params: DesignParams) {
  return {
    filter: `hue-rotate(${params.hue - 202}deg) brightness(${0.77 + params.brightness / 270}) saturate(${0.45 + params.saturation / 115}) contrast(${0.96 + params.gloss / 700})`,
  }
}

export function silhouetteStyle(params: DesignParams) {
  return {
    borderRadius: `${5 + params.corner * 0.24 + params.smoothness * 0.1}px`,
    transform: `skewX(${(params.lineAngle - 18) / 11}deg)`,
    boxShadow: `inset -14px 0 ${Math.round(params.gloss / 2)}px rgba(255,255,255,${(params.gloss / 170).toFixed(2)}), 0 16px 35px rgba(21,28,65,.15)`,
    background: params.material === '亮面玻璃' ? 'linear-gradient(150deg,#d4f5ff,#5798db 58%,#173a91)' : params.material === '细砂复合材质' ? 'linear-gradient(150deg,#e8edf7,#98a8c7 58%,#7186af)' : 'linear-gradient(150deg,#d7fbff,#69c8ec 55%,#2977bc)',
  }
}
