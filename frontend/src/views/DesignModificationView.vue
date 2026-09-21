<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { ArrowRightOutlined, BulbOutlined, CheckOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import {
  cmfImages, constrainedParams, initialParams, markets, modelVersion, numericParamMeta,
  previewStyle, promptVersion, renderImages, scoreDesign, seriesProfiles, silhouetteStyle,
} from '@/data/designModification'
import type { DesignParams, DesignVersion, MarketId, NumericParam, SeriesId } from '@/data/designModification'

type ImageItem = { id: string; label: string; url: string; source: string }
type UploadKind = 'render' | 'mood' | 'feedback' | 'parameters' | 'description'
type ChatMessage = { role: 'user' | 'assistant'; text: string }
type PendingInterpretation = { original: string; changes: Partial<DesignParams>; breakdown: string[] }

const storageKey = 'design-ai-design-modification-demo-v1'
const seriesId = ref<SeriesId>('hot')
const marketId = ref<MarketId>('southeast')
const benchmarkYear = ref<2025 | 2026>(2026)
const params = ref<DesignParams>({ ...initialParams })
const versions = ref<DesignVersion[]>([])
const selectedImageId = ref('cmf-blue')
const selectedMoodId = ref('cmf-pink')
const uploadedRenders = ref<ImageItem[]>([])
const uploadedMoods = ref<ImageItem[]>([])
const feedbackFiles = ref<string[]>([])
const parameterFile = ref('')
const descriptionFile = ref('')
const designDescription = ref('年轻化性能手机：清晰的三摄秩序、海蓝渐变背板、轻快的视觉节奏。')
const feedbackText = ref('访谈提要：希望背板有辨识度，手持观感轻盈；评审建议控制大面积高光。')
const referenceExtracted = ref<Partial<DesignParams> | null>(null)
const textureMode = ref<'original' | 'clear' | 'soft'>('original')
const rationaleDraft = ref('设计师调整：结合参考情绪版与系列约束')
const chatInput = ref('')
const chatMessages = ref<ChatMessage[]>([{ role: 'assistant', text: '可以说“把 R 角再圆润一些”或“更有高级感”。我会先拆成参数建议，确认后再生成演示版本。' }])
const pending = ref<PendingInterpretation | null>(null)
const compareLeftId = ref('')
const compareRightId = ref('')
const selectedIntent = ref<'premium' | 'performance' | 'young'>('premium')
const lastEvaluatedAt = ref(new Date().toISOString())
const objectUrls: string[] = []

const allImages = computed(() => [cmfImages[0]!, ...renderImages, ...uploadedRenders.value])
const moodImages = computed(() => [...cmfImages, ...uploadedMoods.value])
const selectedImage = computed(() => allImages.value.find(item => item.id === selectedImageId.value) ?? cmfImages[0]!)
const selectedMood = computed(() => moodImages.value.find(item => item.id === selectedMoodId.value) ?? cmfImages[2]!)
const profile = computed(() => seriesProfiles[seriesId.value])
const result = computed(() => scoreDesign(params.value, seriesId.value, marketId.value, benchmarkYear.value))
const lowDimensions = computed(() => [...result.value.dimensions].sort((a, b) => a.value - b.value).slice(0, 2))
const compareLeft = computed(() => versions.value.find(item => item.id === compareLeftId.value) ?? versions.value.at(-1))
const compareRight = computed(() => versions.value.find(item => item.id === compareRightId.value) ?? versions.value[0])

function makeVersion(source: string, rationale: string): DesignVersion {
  const score = result.value
  return {
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    name: `V${versions.value.length + 1}`,
    createdAt: new Date().toISOString(),
    params: { ...params.value }, score: score.total, risk: score.risk,
    rationale, source, imageSource: selectedImage.value.source,
    seriesId: seriesId.value, marketId: marketId.value, benchmarkYear: benchmarkYear.value, approved: false,
  }
}

function saveVersion(source: string, rationale = rationaleDraft.value.trim()) {
  const current = versions.value[0]
  if (current && JSON.stringify(current.params) === JSON.stringify(params.value)
    && current.seriesId === seriesId.value && current.marketId === marketId.value
    && current.benchmarkYear === benchmarkYear.value && source !== '回退') return
  const version = makeVersion(source, rationale || source)
  versions.value.unshift(version)
  compareRightId.value = version.id
  if (!compareLeftId.value) compareLeftId.value = versions.value.at(-1)?.id ?? version.id
  lastEvaluatedAt.value = version.createdAt
  message.success(`已记录 ${version.name} · ${source}`)
}

function restoreState() {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return
    const saved = JSON.parse(raw) as {
      seriesId?: SeriesId; marketId?: MarketId; benchmarkYear?: 2025 | 2026
      params?: DesignParams; versions?: DesignVersion[]; selectedImageId?: string
      description?: string; feedback?: string
    }
    if (saved.seriesId && saved.seriesId in seriesProfiles) seriesId.value = saved.seriesId
    if (saved.marketId && saved.marketId in markets) marketId.value = saved.marketId
    if (saved.benchmarkYear === 2025 || saved.benchmarkYear === 2026) benchmarkYear.value = saved.benchmarkYear
    if (saved.params && numericParamMeta.every(item => Number.isFinite(saved.params?.[item.key]))) {
      params.value = constrainedParams({ ...initialParams, ...saved.params }, seriesId.value)
    }
    if (Array.isArray(saved.versions)) versions.value = saved.versions.filter(item => item && item.params && item.seriesId in seriesProfiles && item.marketId in markets)
    if (saved.selectedImageId && [cmfImages[0]!, ...renderImages].some(item => item.id === saved.selectedImageId)) selectedImageId.value = saved.selectedImageId
    if (typeof saved.description === 'string') designDescription.value = saved.description
    if (typeof saved.feedback === 'string') feedbackText.value = saved.feedback
  } catch { /* 损坏的浏览器演示状态回到初始示例。 */ }
}

restoreState()
if (!versions.value.length) versions.value = [makeVersion('演示基线', '手机图示例素材与 2026 年系列演示约束')]
compareLeftId.value = versions.value.at(-1)?.id ?? ''
compareRightId.value = versions.value[0]?.id ?? ''

watch([seriesId, marketId, benchmarkYear, params, versions, selectedImageId, designDescription, feedbackText], () => {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      seriesId: seriesId.value, marketId: marketId.value, benchmarkYear: benchmarkYear.value,
      params: params.value, versions: versions.value, selectedImageId: selectedImageId.value,
      description: designDescription.value, feedback: feedbackText.value,
    }))
  } catch { message.warning('浏览器本地空间不足，当前改动仅保留到页面关闭') }
}, { deep: true })

onUnmounted(() => objectUrls.forEach(url => URL.revokeObjectURL(url)))

function changeSeries(value: SeriesId) {
  if (value === seriesId.value) return
  seriesId.value = value
  params.value = constrainedParams(params.value, value)
  saveVersion('切换系列约束', `采用 ${seriesProfiles[value].knowledge}；${rationaleDraft.value}`)
}

function changeMarket(value: MarketId) {
  if (value === marketId.value) return
  marketId.value = value
  saveVersion('切换目标市场', `目标市场：${markets[value].name}；${rationaleDraft.value}`)
}

function changeYear(value: 2025 | 2026) {
  if (value === benchmarkYear.value) return
  benchmarkYear.value = value
  saveVersion('切换年度基准', `采用 ${value} 年演示约束；${rationaleDraft.value}`)
}

function commitSlider(key: NumericParam) {
  params.value = constrainedParams(params.value, seriesId.value)
  const label = numericParamMeta.find(item => item.key === key)?.label ?? key
  saveVersion('参数拖拽', `${rationaleDraft.value.trim() || '设计师手动调整'}；调整 ${label}`)
}

function appendImageFiles(files: FileList, kind: 'render' | 'mood') {
  const target = kind === 'render' ? uploadedRenders : uploadedMoods
  const accepted = [...files].filter(file => /\.(png|jpe?g|webp)$/i.test(file.name) && file.size <= 10 * 1024 * 1024)
  if (accepted.length !== files.length) message.warning('图片仅支持 PNG/JPG/WebP，单张不超过 10 MB')
  for (const file of accepted) {
    const url = URL.createObjectURL(file)
    objectUrls.push(url)
    const item = { id: `upload-${Date.now()}-${Math.random()}`, label: file.name, url, source: `本次会话上传：${file.name}` }
    target.value.push(item)
    if (kind === 'render') selectedImageId.value = item.id
    else selectedMoodId.value = item.id
  }
  if (accepted.length) message.success(`已加入 ${accepted.length} 张${kind === 'render' ? '方案' : '情绪版'}图片`)
}

async function onFileChange(event: Event, kind: UploadKind) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (!files?.length) return
  if (kind === 'render' || kind === 'mood') appendImageFiles(files, kind)
  if (kind === 'feedback') {
    for (const file of [...files]) {
      if (file.size <= 10 * 1024 * 1024 && /\.(txt|md|pdf|docx)$/i.test(file.name)) feedbackFiles.value.push(file.name)
      else message.warning(`${file.name} 不符合反馈文件格式或大小要求`)
    }
  }
  if (kind === 'description') {
    const file = files[0]!
    if (file.size <= 1024 * 1024 && /\.(txt|md)$/i.test(file.name)) {
      descriptionFile.value = file.name
      designDescription.value = (await file.text()).slice(0, 12000)
      message.success('设计说明已读入，可继续编辑')
    } else message.warning('设计说明支持 TXT/MD，最大 1 MB')
  }
  if (kind === 'parameters') {
    const file = files[0]!
    if (file.size > 1024 * 1024 || !/\.(json|csv)$/i.test(file.name)) message.warning('参数文件支持 JSON/CSV，最大 1 MB')
    else {
      try {
        const content = await file.text()
        const values = file.name.toLowerCase().endsWith('.json')
          ? JSON.parse(content) as Record<string, unknown>
          : Object.fromEntries(content.trim().split(/\r?\n/).slice(1).map(line => line.split(',').map(value => value.trim())).filter(parts => parts.length >= 2))
        if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('格式无效')
        const next = { ...params.value }
        let matched = 0
        for (const { key } of numericParamMeta) {
          if (values[key] == null) continue
          const value = Number(values[key])
          if (!Number.isFinite(value)) throw new Error(`${key} 必须是数字`)
          next[key] = value
          matched++
        }
        if (typeof values.material === 'string' && ['AG 玻璃', '亮面玻璃', '细砂复合材质'].includes(values.material)) {
          next.material = values.material as DesignParams['material']
          matched++
        }
        if (!matched) throw new Error('未找到可识别参数')
        params.value = constrainedParams(next, seriesId.value)
        parameterFile.value = file.name
        saveVersion('导入参数文件', `来自 ${file.name}；受 ${profile.value.knowledge} 限制`)
      } catch (cause) { message.error(`参数读取失败：${cause instanceof Error ? cause.message : '格式无效'}`) }
    }
  }
  input.value = ''
}

function extractMood() {
  const pink = selectedMood.value.id.includes('pink') || selectedMood.value.id.includes('648') || selectedMood.value.id.includes('652')
  referenceExtracted.value = pink
    ? { hue: 336, brightness: 76, saturation: 55, gloss: 49, smoothness: 78, corner: 39, lineAngle: 12 }
    : { hue: 204, brightness: 67, saturation: 67, gloss: 51, smoothness: 72, corner: 28, lineAngle: 22 }
  message.info('已生成示例参数；请核对后手动应用')
}

function applyMood() {
  if (!referenceExtracted.value) return
  params.value = constrainedParams({ ...params.value, ...referenceExtracted.value }, seriesId.value)
  saveVersion('参考情绪版', `情绪版 ${selectedMood.value.label}；${rationaleDraft.value}`)
}

const suggestionSets = {
  premium: [
    { title: '克制的高级感', note: '降低彩度与高光，改用细砂表面；偏向安静精致。', patch: { material: '细砂复合材质', saturation: 42, gloss: 34, brightness: 68 } },
    { title: '精密的高级感', note: '保留玻璃质感，收紧夹角与 R 角；偏向精准秩序。', patch: { material: 'AG 玻璃', gloss: 46, corner: 22, lineAngle: 16 } },
  ],
  performance: [
    { title: '速度表达', note: '提高色彩强度与线条夹角，强化动态感。', patch: { saturation: 78, lineAngle: 36, smoothness: 73 } },
    { title: '稳健性能', note: '提升轮廓流畅度，保留克制光泽以控制风险。', patch: { saturation: 66, lineAngle: 26, smoothness: 84, gloss: 48 } },
  ],
  young: [
    { title: '轻快亲和', note: '提高明度和圆角，贴近年轻用户的轻盈偏好。', patch: { brightness: 78, saturation: 68, corner: 45 } },
    { title: '鲜明记忆点', note: '保留强色彩，降低表面光泽以突出轮廓。', patch: { brightness: 67, saturation: 82, gloss: 40, lineAngle: 25 } },
  ],
} satisfies Record<string, { title: string; note: string; patch: Partial<DesignParams> }[]>

const audienceSuggestion = computed<{ title: string; note: string; patch: Partial<DesignParams> }>(() => {
  const market = markets[marketId.value]
  const patch: Record<MarketId, Partial<DesignParams>> = {
    southeast: { brightness: 76, saturation: 65 },
    south: { saturation: 75, lineAngle: 28 },
    africa: { saturation: 72, gloss: 43 },
  }
  return { title: `${market.name} · 人群偏好微调`, note: market.note, patch: patch[marketId.value] }
})

const lowScoreSuggestion = computed<{ title: string; note: string; patch: Partial<DesignParams> }>(() => {
  const dimension = lowDimensions.value[0]!
  const target = profile.value.target
  const patches: Record<typeof dimension.id, Partial<DesignParams>> = {
    aesthetic: { hue: target.hue, brightness: target.brightness, saturation: target.saturation, smoothness: target.smoothness },
    brand: { material: target.material, corner: target.corner, lineAngle: target.lineAngle },
    craft: { gloss: Math.min(params.value.gloss, 55), corner: Math.min(params.value.corner, 52), lineAngle: Math.min(params.value.lineAngle, 38) },
    cost: { material: 'AG 玻璃', gloss: Math.min(params.value.gloss, 45) },
    trend: { hue: target.hue, saturation: target.saturation, lineAngle: target.lineAngle },
  }
  return {
    title: `优先修复 · ${dimension.label}`,
    note: `${dimension.reason} 先把关联参数拉近 ${profile.value.name} 的演示基准。`,
    patch: patches[dimension.id],
  }
})

function applySuggestion(item: { title: string; patch: Partial<DesignParams> }) {
  params.value = constrainedParams({ ...params.value, ...item.patch }, seriesId.value)
  saveVersion('方向建议', `${item.title}；${feedbackText.value.slice(0, 80) || rationaleDraft.value}`)
}

/** 自然语言仅识别演示词组；先展示拆解结果，由设计师确认后才写入版本。 */
function interpret(text: string): PendingInterpretation | null {
  const changes: Partial<DesignParams> = {}
  const breakdown: string[] = []
  const less = /少一点|降低|收敛|减少|别太/.test(text)
  if (/圆润|R角|圆角/.test(text)) { changes.corner = params.value.corner + (less ? -14 : 14); breakdown.push(`R 角幅度 ${less ? '降低' : '提高'} 14 点`) }
  if (/亮一点|更亮|明度/.test(text)) { changes.brightness = params.value.brightness + (less ? -10 : 10); breakdown.push(`明度 ${less ? '降低' : '提高'} 10 点`) }
  if (/饱和|鲜艳|颜色更强/.test(text)) { changes.saturation = params.value.saturation + (less ? -12 : 12); breakdown.push(`饱和度 ${less ? '降低' : '提高'} 12 点`) }
  if (/光泽|反光|哑光/.test(text)) { changes.gloss = params.value.gloss + (/哑光/.test(text) || less ? -15 : 15); breakdown.push(`光泽调整到 ${changes.gloss}%`) }
  if (/流畅|顺滑/.test(text)) { changes.smoothness = params.value.smoothness + (less ? -12 : 12); breakdown.push(`形态流畅度 ${less ? '降低' : '提高'} 12 点`) }
  if (/高级感|精致/.test(text)) { Object.assign(changes, { material: '细砂复合材质', gloss: 36, saturation: 48 }); breakdown.push('高级感 → 细砂材质、低光泽、收敛饱和度') }
  if (/高性能|速度感|运动感/.test(text)) { Object.assign(changes, { saturation: 76, lineAngle: 34, smoothness: 76 }); breakdown.push('高性能 → 更鲜明的色彩、较大线条夹角、流畅轮廓') }
  return breakdown.length ? { original: text, changes: constrainedParams({ ...params.value, ...changes }, seriesId.value), breakdown } : null
}

function sendChat() {
  const text = chatInput.value.trim()
  if (!text) return
  chatMessages.value.push({ role: 'user', text })
  pending.value = interpret(text)
  chatMessages.value.push({ role: 'assistant', text: pending.value
    ? `我将这句话拆成：${pending.value.breakdown.join('；')}。已按 ${profile.value.name} 约束处理，请确认后应用。`
    : '当前演示支持 R 角、明度、饱和度、光泽、流畅度，以及“高级感”“高性能”等表达。请换一种说法。' })
  chatInput.value = ''
}

function confirmChat() {
  if (!pending.value) return
  params.value = { ...params.value, ...pending.value.changes }
  saveVersion('对话修改', `设计师确认：${pending.value.original}；拆解：${pending.value.breakdown.join('、')}`)
  chatMessages.value.push({ role: 'assistant', text: `已生成 ${versions.value[0]?.name} 演示版本。你可以继续描述下一轮修改。` })
  pending.value = null
}

function updateRationale(version: DesignVersion, event: Event) {
  const value = (event.target as HTMLInputElement).value.trim()
  version.rationale = value || '未填写修改依据'
  message.success('修改依据已保存到浏览器')
}

function approveVersion(version: DesignVersion) {
  version.approved = true
  message.success(`${version.name} 已确认用于评审`)
}

function rankVersion(version: DesignVersion, rank: 1 | 2) {
  if (!version.approved) { message.warning('请先由设计师确认该版本用于评审'); return }
  if (version.risk !== '低') { message.warning('仅低风险版本可标为 TOP1 / TOP2'); return }
  if (version.rank === rank) { version.rank = undefined; return }
  for (const item of versions.value) if (item.rank === rank) item.rank = undefined
  version.rank = rank
}

function rollback(version: DesignVersion) {
  Modal.confirm({
    title: `从 ${version.name} 创建回退版本？`,
    content: '历史版本会保留，当前参数和评分基准将恢复到所选版本，并新增一条版本记录。',
    okText: '确认回退', cancelText: '取消', centered: true,
    onOk() {
      seriesId.value = version.seriesId
      marketId.value = version.marketId
      benchmarkYear.value = version.benchmarkYear
      params.value = { ...version.params }
      saveVersion('回退', `回退至 ${version.name}；原依据：${version.rationale}`)
    },
  })
}

function compareDiff(key: NumericParam) {
  if (!compareLeft.value || !compareRight.value) return '—'
  const diff = compareRight.value.params[key] - compareLeft.value.params[key]
  return diff > 0 ? `+${diff}` : String(diff)
}

function versionImage(version: DesignVersion) {
  return allImages.value.find(item => item.source === version.imageSource)?.url ?? ''
}

function dateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function evaluateAgain() { lastEvaluatedAt.value = new Date().toISOString(); message.success('已按当前参数重新计算演示评分') }
</script>

<template>
  <div class="app-shell modification-shell">
    <div class="ambient ambient-one"></div><div class="ambient ambient-two"></div>
    <header class="topbar">
      <RouterLink class="brand" to="/" aria-label="用户审美洞察与趋势捕捉首页"><span class="brand-mark"><span></span></span><span class="brand-copy"><strong>用户审美洞察与趋势捕捉</strong></span></RouterLink>
      <nav aria-label="主导航"><RouterLink to="/">DNA 提取</RouterLink><RouterLink to="/article-trends">趋势洞察</RouterLink><RouterLink to="/high-trends">高潜趋势</RouterLink><RouterLink class="active" to="/design-modification">设计修改</RouterLink><RouterLink to="/user-research">用研聚合</RouterLink><RouterLink to="/projects">我的项目</RouterLink></nav>
      <div class="system-state"><span></span> 审美洞察工作台</div>
    </header>

    <main>
      <section class="mod-hero">
        <div class="hero-badge"><BulbOutlined /> DESIGN ITERATION STUDIO</div>
        <div class="mod-hero-row"><div><h1>从设计判断，到可回退的每一次修改。</h1><p>上传方案，查看多维拟合依据；用参数和文字探索方向，再把每版变化留给评审。</p></div><span class="demo-pill">前端演示 · 规则模拟</span></div>
      </section>
      <div class="mod-flow"><a href="#mod-input">01 输入方案</a><ArrowRightOutlined /><a href="#mod-score">02 识别低分项</a><ArrowRightOutlined /><a href="#mod-studio">03 修改预览</a><ArrowRightOutlined /><a href="#mod-versions">04 对比版本</a></div>

      <section id="mod-input" class="mod-section">
        <div class="mod-heading"><div><span class="eyebrow">01 / INPUT &amp; CONSTRAINTS</span><h2>方案与参考输入</h2><p>已预置本地手机图样例。上传文件仅在本次页面会话中用于演示，版本参数保存在当前浏览器。</p></div></div>
        <div class="mod-input-grid">
          <div class="mod-panel asset-panel">
            <div class="panel-head"><h3>方案图片</h3><span>{{ allImages.length }} 个视角</span></div>
            <div class="asset-preview"><img :src="selectedImage.url" :alt="selectedImage.label" /><div class="asset-caption"><strong>{{ selectedImage.label }}</strong><span>{{ selectedImage.source }}</span></div></div>
            <div class="image-strip" aria-label="方案图片选择"><button v-for="item in allImages" :key="item.id" type="button" :class="{ chosen: item.id === selectedImageId }" :title="item.label" @click="selectedImageId = item.id"><img :src="item.url" :alt="item.label" loading="lazy" /></button></div>
            <label class="upload-action"><PlusOutlined /> 添加多角度渲染图<input type="file" accept="image/png,image/jpeg,image/webp" multiple @change="onFileChange($event, 'render')" /></label><small class="field-help">PNG / JPG / WebP；单张 ≤ 10 MB。可逐张加入并切换主图。</small>
          </div>
          <div class="input-stack">
            <div class="mod-panel"><div class="panel-head"><h3>设计说明与参数</h3><span>可编辑</span></div><label class="field-label" for="design-description">设计说明</label><textarea id="design-description" v-model="designDescription" rows="3" placeholder="说明目标用户、系列调性与关键设计意图"></textarea><label class="inline-upload">上传 TXT / MD 说明<input type="file" accept=".txt,.md,text/plain,text/markdown" @change="onFileChange($event, 'description')" /></label><span v-if="descriptionFile" class="file-chip">{{ descriptionFile }}</span><div class="divider"></div><label class="inline-upload">导入参数 JSON / CSV<input type="file" accept=".json,.csv,application/json,text/csv" @change="onFileChange($event, 'parameters')" /></label><span v-if="parameterFile" class="file-chip">{{ parameterFile }}</span><small class="field-help">JSON 使用 hue、brightness、saturation、gloss、smoothness、corner、lineAngle、material 字段；CSV 使用 key,value 两列。≤ 1 MB。</small></div>
            <div class="mod-panel"><div class="panel-head"><h3>历代反馈</h3><span>修改依据</span></div><textarea v-model="feedbackText" rows="3" placeholder="粘贴访谈、评测或评审共识要点"></textarea><label class="inline-upload">添加反馈文件<input type="file" accept=".txt,.md,.pdf,.docx" multiple @change="onFileChange($event, 'feedback')" /></label><div v-if="feedbackFiles.length" class="file-list"><span v-for="file in feedbackFiles" :key="file" class="file-chip">{{ file }}</span></div><small class="field-help">TXT / MD / PDF / DOCX；单个 ≤ 10 MB。演示页仅记录文件名，不解析内容。</small></div>
          </div>
          <div class="mod-panel constraint-panel"><div class="panel-head"><h3>系列专属约束库</h3><span>演示知识库</span></div><label class="field-label" for="series-select">产品系列</label><select id="series-select" :value="seriesId" @change="changeSeries(($event.target as HTMLSelectElement).value as SeriesId)"><option v-for="(item, id) in seriesProfiles" :key="id" :value="id">{{ item.name }}</option></select><label class="field-label" for="year-select">年度基准</label><select id="year-select" :value="benchmarkYear" @change="changeYear(Number(($event.target as HTMLSelectElement).value) as 2025 | 2026)"><option :value="2026">2026 演示版</option><option :value="2025">2025 演示版</option></select><div class="constraint-note"><span>系列调性</span><strong>{{ profile.tone }}</strong><span>目标人群</span><strong>{{ profile.audience }}</strong><span>依据编号</span><strong>{{ profile.knowledge.replace('26', String(benchmarkYear).slice(2)) }}</strong></div><p class="muted-note">切换系列或年度会重新计算并记录版本；这里的约束是前端样例。</p></div>
        </div>
      </section>

      <section id="mod-score" class="mod-section">
        <div class="mod-heading"><div><span class="eyebrow">02 / EXPLAINABLE SCORING</span><h2>评分、差距与依据</h2><p>设计 DNA 匹配、落地风险与市场用户分开展示。分数会随参数和基准实时变化。</p></div><button class="ghost-button" type="button" @click="evaluateAgain"><ReloadOutlined /> 重新评估</button></div>
        <div class="score-layout">
          <div class="mod-panel score-summary"><div class="score-title"><span>当前方案拟合度</span><span class="live-dot">LIVE DEMO</span></div><div class="score-number">{{ result.total }}<small>/ 100</small></div><p>审美、品牌与趋势的设计 DNA 匹配合计占 75%。</p><div class="fit-row"><div><span>趋势匹配</span><strong>{{ result.trendFit }}</strong></div><div><span>用户匹配</span><strong>{{ result.userFit }}</strong></div></div><div class="summary-tags"><span>{{ result.audience }}</span><span>{{ result.emotion }}</span><span>落地风险 {{ result.risk }}</span></div><small>最近评估：{{ dateTime(lastEvaluatedAt) }}</small></div>
          <div class="mod-panel dimensions-panel"><div class="panel-head"><h3>五维评分</h3><span>按权重计算</span></div><div v-for="dimension in result.dimensions" :key="dimension.id" class="dimension-row"><div class="dimension-label"><strong>{{ dimension.label }}</strong><small>{{ dimension.group }} · 权重 {{ dimension.weight }}%</small></div><div class="score-track"><div :style="{ width: `${dimension.value}%` }" :class="{ low: dimension.value < 75 }"></div></div><strong class="dimension-score">{{ dimension.value }}</strong></div></div>
          <div class="mod-panel market-panel"><div class="panel-head"><h3>目标市场模拟</h3><span>非预测结果</span></div><label class="field-label" for="market-select">目标区域</label><select id="market-select" :value="marketId" @change="changeMarket(($event.target as HTMLSelectElement).value as MarketId)"><option v-for="(item, id) in markets" :key="id" :value="id">{{ item.name }}</option></select><div class="market-number">{{ result.marketFit }}<small>匹配度</small></div><div class="confidence-line"><span>演示置信度</span><strong>{{ result.confidence }}%</strong></div><p>{{ markets[marketId].note }} · {{ result.audience }}</p><details class="basis-detail"><summary>查看市场与用户分数口径</summary><p>用户匹配：审美 46% + 品牌 22% + 地区模拟 32%。地区模拟以总分及当前地区的明度或饱和度偏好示意值计算。</p><p>来源：KB-MARKET-26 · 演示地区画像。置信度为地区固定展示值。</p></details><small class="field-help">分数和置信度为规则示意，不代表地区真实偏好。</small></div>
        </div>
        <div class="evidence-grid"><div class="mod-panel"><div class="panel-head"><h3>低分维度定位</h3><span>优先处理</span></div><article v-for="dimension in lowDimensions" :key="dimension.id" class="low-card"><span>{{ dimension.label }} · {{ dimension.value }} 分</span><p>{{ dimension.reason }}</p><small>判断依据：{{ dimension.basis }}</small><small>来源：{{ dimension.source }}</small></article></div><div class="mod-panel"><div class="panel-head"><h3>透明评分依据</h3><span>逐项可查</span></div><details v-for="dimension in result.dimensions" :key="dimension.id" class="basis-detail"><summary>{{ dimension.label }} <span>{{ dimension.source }}</span></summary><p>{{ dimension.reason }}</p><p>依据：{{ dimension.basis }}。当前权重 {{ dimension.weight }}%。</p></details><p class="muted-note">知识库编号、访谈与趋势文字均为演示样例，不连接真实共享知识库。</p></div></div>
      </section>

      <section id="mod-studio" class="mod-section">
        <div class="mod-heading"><div><span class="eyebrow">03 / LIVE DESIGN STUDIO</span><h2>拖拽参数，查看即时预览</h2><p>预览使用本地照片的色彩滤镜与轮廓示意；材料、R 角和形态修改不是真实重渲染。</p></div><span class="status-chip">待设计师确认的演示方案</span></div>
        <div class="studio-grid">
          <div class="mod-panel preview-panel"><div class="panel-head"><h3>方案实时预览</h3><span>{{ selectedImage.label }}</span></div><div class="studio-image" :class="`texture-${textureMode}`"><img :src="selectedImage.url" :alt="selectedImage.label" :style="previewStyle(params)" /><span class="preview-watermark">SIMULATED PREVIEW</span></div><div class="preview-foot"><div class="silhouette" :style="silhouetteStyle(params)"><span></span><span></span><span></span></div><div><strong>轮廓示意</strong><p>R 角 {{ params.corner }}% · 流畅度 {{ params.smoothness }}% · 夹角 {{ params.lineAngle }}°</p><small>{{ params.material }} · 光泽 {{ params.gloss }}%</small></div></div><div class="texture-tool"><strong>后期渲染质感提升</strong><div class="segmented"><button type="button" :class="{ selected: textureMode === 'original' }" @click="textureMode = 'original'">原图</button><button type="button" :class="{ selected: textureMode === 'clear' }" @click="textureMode = 'clear'">清晰质感</button><button type="button" :class="{ selected: textureMode === 'soft' }" @click="textureMode = 'soft'">柔和漫反射</button></div><small>前端图像处理入口，仅改变展示效果。</small></div></div>
          <div class="mod-panel param-panel"><div class="panel-head"><h3>设计 DNA 参数卡</h3><span>拖动实时预览 · 松开留版</span></div><label class="field-label" for="material-select">材质</label><select id="material-select" v-model="params.material" @change="saveVersion('材质调整', `${rationaleDraft}；材质改为 ${params.material}`)"><option>AG 玻璃</option><option>亮面玻璃</option><option>细砂复合材质</option></select><div v-for="item in numericParamMeta" :key="item.key" class="slider-row"><div class="slider-label"><label :for="`param-${item.key}`">{{ item.label }}</label><output>{{ params[item.key] }}{{ item.unit }}</output></div><input :id="`param-${item.key}`" v-model.number="params[item.key]" type="range" :min="profile.limits[item.key]?.[0] ?? item.min" :max="profile.limits[item.key]?.[1] ?? item.max" @change="commitSlider(item.key)" /></div><p class="muted-note">当前系列限制：饱和度 {{ profile.limits.saturation?.join('–') }}%，R 角 {{ profile.limits.corner?.join('–') }}%。建议和对话会自动落在范围内。</p></div>
          <div class="mod-panel mood-panel"><div class="panel-head"><h3>参考情绪版</h3><span>反向对照</span></div><div class="mood-image"><img :src="selectedMood.url" :alt="selectedMood.label" loading="lazy" /><span>{{ selectedMood.label }}</span></div><div class="image-strip compact"><button v-for="item in moodImages" :key="item.id" type="button" :class="{ chosen: item.id === selectedMoodId }" :title="item.label" @click="selectedMoodId = item.id; referenceExtracted = null"><img :src="item.url" :alt="item.label" loading="lazy" /></button></div><label class="inline-upload">上传参考情绪版<input type="file" accept="image/png,image/jpeg,image/webp" multiple @change="onFileChange($event, 'mood')" /></label><button class="outline-button" type="button" @click="extractMood">提取示例参数</button><div v-if="referenceExtracted" class="extracted-params"><span v-for="item in numericParamMeta" :key="item.key">{{ item.label }} {{ referenceExtracted[item.key] }}{{ item.unit }}</span><button class="primary-button" type="button" @click="applyMood"><CheckOutlined /> 确认应用到方案</button></div><p class="muted-note">情绪版参数为预设模拟值。选择参考图片后手动提取、核对和应用。</p></div>
        </div>
      </section>

      <section class="mod-section">
        <div class="mod-heading"><div><span class="eyebrow">04 / DIRECTIONS &amp; DIALOGUE</span><h2>从模糊诉求到多个修改方向</h2><p>先给设计师可解读的方向，再由设计师决定是否生成版本。</p></div></div>
        <div class="ideation-grid"><div class="mod-panel"><div class="panel-head"><h3>建议方向</h3><span>结合当前低分项与人群</span></div><p class="suggestion-context">当前优先关注 {{ lowDimensions.map(item => item.label).join('、') }}；目标人群：{{ result.audience }}。</p><div class="segmented intent-switch"><button type="button" :class="{ selected: selectedIntent === 'premium' }" @click="selectedIntent = 'premium'">高级感</button><button type="button" :class="{ selected: selectedIntent === 'performance' }" @click="selectedIntent = 'performance'">高性能</button><button type="button" :class="{ selected: selectedIntent === 'young' }" @click="selectedIntent = 'young'">年轻化</button></div><div v-for="item in [lowScoreSuggestion, ...suggestionSets[selectedIntent], audienceSuggestion]" :key="item.title" class="suggestion-card"><div><strong>{{ item.title }}</strong><p>{{ item.note }}</p><small>参考：{{ profile.knowledge }} · 演示人群偏好</small></div><button type="button" @click="applySuggestion(item)">应用方向 <ArrowRightOutlined /></button></div></div><div class="mod-panel chat-panel"><div class="panel-head"><h3>对话式修改</h3><span>多轮演示</span></div><div class="chat-log" aria-live="polite"><div v-for="(item, index) in chatMessages" :key="index" class="chat-bubble" :class="item.role">{{ item.text }}</div></div><div v-if="pending" class="pending-card"><strong>待设计师确认的解读</strong><ul><li v-for="part in pending.breakdown" :key="part">{{ part }}</li></ul><p>系列约束：{{ profile.name }}</p><div><button class="primary-button" type="button" @click="confirmChat">确认并生成演示版</button><button class="text-button" type="button" @click="pending = null">放弃本轮</button></div></div><div class="chat-composer"><input v-model="chatInput" aria-label="输入设计修改要求" placeholder="例如：把 R 角再圆润一些" @keydown.enter="sendChat" /><button type="button" @click="sendChat">发送</button></div><div class="prompt-chips"><button type="button" @click="chatInput = '把 R 角再圆润一些'">R 角圆润些</button><button type="button" @click="chatInput = '更有高级感'">更有高级感</button><button type="button" @click="chatInput = '更有高性能的速度感'">更有速度感</button></div></div></div>
      </section>

      <section id="mod-versions" class="mod-section version-section">
        <div class="mod-heading"><div><span class="eyebrow">05 / VERSION HISTORY</span><h2>每一版都有参数、分数和修改依据</h2><p>拖拽结束、应用方向、确认对话或回退都会新增版本。低风险版本可标为 TOP1 / TOP2。</p></div><span class="status-chip"><HistoryOutlined /> {{ versions.length }} 个版本</span></div>
        <div class="rationale-bar"><label for="version-rationale">下一版修改依据</label><input id="version-rationale" v-model="rationaleDraft" placeholder="填写访谈、评测或团队共识依据" /><small>例如：9 月访谈 / CMF 评审共识。保存版本后仍可逐版编辑。</small></div>
        <div class="version-list"><article v-for="version in versions" :key="version.id" class="version-card"><div class="version-top"><div><strong>{{ version.name }}</strong><span v-if="version.rank" class="rank-badge">TOP{{ version.rank }}</span><span class="risk-badge" :class="`risk-${version.risk}`">{{ version.risk }}风险</span><span class="review-badge">{{ version.approved ? '已确认' : '待确认' }}</span></div><small>{{ dateTime(version.createdAt) }}</small></div><p>{{ version.source }} · 拟合度 <b>{{ version.score }}</b> · {{ seriesProfiles[version.seriesId].name }} · {{ markets[version.marketId].name }} · {{ version.benchmarkYear }}</p><div class="version-rationale"><label :for="`rationale-${version.id}`">修改依据</label><input :id="`rationale-${version.id}`" :value="version.rationale" @change="updateRationale(version, $event)" /></div><div class="version-meta"><small>输入图：{{ version.imageSource }}</small><small>规则 {{ modelVersion }} · Prompt {{ promptVersion }}</small></div><div class="version-actions"><button v-if="!version.approved" type="button" @click="approveVersion(version)">确认用于评审</button><button type="button" :disabled="version.risk !== '低' || !version.approved" @click="rankVersion(version, 1)">标记 TOP1</button><button type="button" :disabled="version.risk !== '低' || !version.approved" @click="rankVersion(version, 2)">标记 TOP2</button><button type="button" @click="compareLeftId = version.id">设为对比 A</button><button type="button" @click="compareRightId = version.id">设为对比 B</button><button type="button" @click="rollback(version)">一键回退</button></div></article></div>
        <div class="mod-panel comparison-panel"><div class="panel-head"><h3>版本变更对比</h3><span>A → B</span></div><div class="compare-selects"><label>版本 A<select v-model="compareLeftId"><option v-for="version in versions" :key="version.id" :value="version.id">{{ version.name }} · {{ version.source }}</option></select></label><label>版本 B<select v-model="compareRightId"><option v-for="version in versions" :key="version.id" :value="version.id">{{ version.name }} · {{ version.source }}</option></select></label></div><div v-if="compareLeft && compareRight" class="comparison-grid"><div class="compare-visual"><img v-if="versionImage(compareLeft)" :src="versionImage(compareLeft)" :style="previewStyle(compareLeft.params)" alt="版本 A 视觉示意" loading="lazy" /><div v-else class="missing-image">本次会话上传的图片已失效，请重新上传</div><strong>{{ compareLeft.name }} · {{ compareLeft.score }} 分</strong></div><div class="compare-visual"><img v-if="versionImage(compareRight)" :src="versionImage(compareRight)" :style="previewStyle(compareRight.params)" alt="版本 B 视觉示意" loading="lazy" /><div v-else class="missing-image">本次会话上传的图片已失效，请重新上传</div><strong>{{ compareRight.name }} · {{ compareRight.score }} 分</strong></div></div><div v-if="compareLeft && compareRight" class="diff-grid"><div v-for="item in numericParamMeta" :key="item.key"><span>{{ item.label }}</span><strong>{{ compareLeft.params[item.key] }} → {{ compareRight.params[item.key] }}{{ item.unit }}</strong><em>{{ compareDiff(item.key) }}</em></div><div><span>材质</span><strong>{{ compareLeft.params.material }} → {{ compareRight.params.material }}</strong></div><div><span>拟合度变化</span><strong>{{ compareLeft.score }} → {{ compareRight.score }}</strong><em>{{ compareRight.score - compareLeft.score > 0 ? '+' : '' }}{{ compareRight.score - compareLeft.score }}</em></div></div></div>
        <p class="demo-footer">演示数据追溯：所选手机图路径、{{ modelVersion }}、{{ promptVersion }}、版本时间均记录在版本卡中。真实模型生成、成本测算、风险筛查与跨设备同步尚未接入。</p>
      </section>
    </main>
  </div>
</template>

<style scoped src="@/assets/designModification.css"></style>
