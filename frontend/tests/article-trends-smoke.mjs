/**
 * 趋势页浏览器冒烟：mock 模式验证交互；live-readonly 只读真实资料并允许范围预估。
 * 不验证模型语义质量。真实模式在网络层阻止任务创建、恢复及所有其他写请求。
 * MODE=live-readonly BASE_URL=https://example.com PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node frontend/tests/article-trends-smoke.mjs
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const mode = process.env.MODE || 'mock'
assert.ok(['mock', 'live-readonly'].includes(mode), 'MODE must be mock or live-readonly')
const base = process.env.BASE_URL || 'http://127.0.0.1:24179'
const output = process.env.OUTPUT_DIR || fileURLToPath(new URL('../../data/result/article_trend_validation_20261021/', import.meta.url))
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
// Chromium 不自动继承 HTTPS_PROXY；真实站点冒烟沿用当前环境的网络出口。
const proxyUrl = mode === 'live-readonly' ? (process.env.SMOKE_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy) : undefined
const proxy = proxyUrl ? new URL(proxyUrl) : null
const browser = await chromium.launch({ headless: true, ...(proxy ? { proxy: { server: `${proxy.protocol}//${proxy.host}`, ...(proxy.username ? { username: decodeURIComponent(proxy.username), password: decodeURIComponent(proxy.password) } : {}) } } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(30_000)
const checks = []
const errors = []
const blockedWrites = []
const calls = []
const report = { mode, base_url: base, model_quality_tested: false, started_at: new Date().toISOString(), checks, errors, blocked_writes: blockedWrites }
page.on('pageerror', error => errors.push(error.message))
let mockStarted = false
const mockArticle = id => ({ article_id: String(id), title: `趋势文章 ${id}`, summary: '哑光表面与温暖色彩，保留明确设计语言。', published_at: '2026-09-30', source: 'design.example', source_url: 'https://design.example/article', category: '产品设计', image_count: 0, images: [] })
const mockTask = () => ({ id: 'fixture-task', status: 'completed', stage: '聚类完成', completed_steps: 4, total_steps: 4, calls: 4, article_count: 3, created_at: '2026-10-21T10:00:00', updated_at: '2026-10-21T10:01:00', error: null })

await page.route('**/api/v1/**', async route => {
  const request = route.request()
  const url = new URL(request.url())
  const apiPath = url.pathname.replace('/api/v1', '')
  const call = { method: request.method(), path: apiPath, body: request.postDataJSON() }
  calls.push(call)
  if (mode === 'live-readonly') {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(call.method) && !(call.method === 'POST' && apiPath === '/article-trends/preview')) {
      blockedWrites.push({ method: call.method, path: apiPath })
      return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Live smoke test blocks every write except selection preview.' }) })
    }
    return route.continue()
  }
  let response
  if (apiPath === '/llm/models') response = { models: [{ id: 'fixture-model', name: '离线测试模型', model_provider: 'offline' }] }
  else if (apiPath === '/article-trends/catalog') response = { total: 8833, sources: ['design.example'], categories: ['产品设计'], min_date: '2020-01-01', max_date: '2026-09-30', skill_version: 'fusion-fixture' }
  else if (apiPath === '/article-trends/articles') {
    const current = Number(url.searchParams.get('page'))
    const size = Number(url.searchParams.get('page_size'))
    response = { total: url.searchParams.get('q') ? 1 : 8833, page: current, page_size: size, items: Array.from({ length: url.searchParams.get('q') ? 1 : size }, (_, index) => mockArticle((current - 1) * size + index + 1)) }
  } else if (apiPath.startsWith('/article-trends/articles/')) response = mockArticle(apiPath.split('/').at(-1))
  else if (apiPath === '/article-trends/preview') {
    const count = request.postDataJSON().article_ids?.length || 8833
    response = { selection_digest: 'fixture-digest', article_count: count, source_group_count: count, batch_count: 1, estimated_calls: 4, input_characters: 250, warnings: [], skill_version: 'fusion-fixture' }
  } else if (apiPath === '/article-trends/tasks' && request.method() === 'POST') { mockStarted = true; response = mockTask() }
  else if (apiPath === '/article-trends/tasks') response = mockStarted ? [mockTask()] : []
  else if (apiPath === '/article-trends/history') response = []
  else if (apiPath === '/article-trends/tasks/fixture-task') response = { ...mockTask(), result: { trends: [{ theme_id: 'warm', priority_rank: 1, title: '温暖哑光表面', definition: '低反射表面与温暖色彩形成共同审美。', source_group_count: 3, article_count: 3, primary_article_count: 2, members: [{ article_id: '1', anchor: '哑光表面与温暖色彩' }], secondary_members: [] }], evidence_pool: [{ article_id: '2', pool_reason: '来源支持不足' }], coverage: { article_count: 3, covered_count: 3 } } }
  else return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Unknown mock route' }) })
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
})

function nextArticles(predicate = () => true) {
  return page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname === '/api/v1/article-trends/articles' && predicate(url) })
}

try {
  await mkdir(output, { recursive: true })
  const catalogResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/article-trends/catalog')
  const modelResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/llm/models')
  const articlesResponse = nextArticles()
  const [catalogHttp, modelsHttp, initialHttp] = await Promise.all([catalogResponse, modelResponse, articlesResponse, page.goto(`${base}/article-trends`, { waitUntil: 'domcontentloaded' })])
  const catalog = await catalogHttp.json()
  const availableModels = (await modelsHttp.json()).models
  const initialArticles = await initialHttp.json()
  await page.locator('.article-card').first().waitFor()
  assert.equal(catalog.total, 8833)
  assert.equal(initialArticles.total, 8833)
  assert.equal(await page.locator('.article-card').count(), 24)
  assert.equal(calls.filter(call => call.method === 'POST').length, 0)
  checks.push('8833 篇资料目录及每页 24 篇加载成功；进入页面未创建任务')
  report.skill_version = catalog.skill_version

  if (mode === 'live-readonly') {
    const image = page.locator('.card-image img').first()
    await image.waitFor()
    await image.evaluate(element => element.scrollIntoView())
    await page.waitForFunction(() => [...document.querySelectorAll('.card-image img')].some(image => image.complete && image.naturalWidth > 0))
    const loaded = await page.locator('.card-image img').evaluateAll(images => images.filter(image => image.complete && image.naturalWidth > 0).map(image => ({ url: image.src, width: image.naturalWidth, height: image.naturalHeight })))
    assert.ok(loaded.length > 0)
    assert.equal(new URL(loaded[0].url).origin, new URL(base).origin)
    report.local_image = loaded[0]
    checks.push('真实本地图片请求成功并解码，图片来自同站点')
  }

  const sampleTitle = initialArticles.items[0].title.slice(0, 12)
  const searched = nextArticles(url => url.searchParams.get('q') === sampleTitle)
  await page.locator('#article-keyword').fill(sampleTitle)
  const searchData = await (await searched).json()
  assert.ok(searchData.total > 0 && searchData.total <= 8833)
  const reset = nextArticles(url => !url.searchParams.get('q'))
  await page.getByRole('button', { name: '重置筛选' }).click()
  await reset
  if (catalog.sources.length) {
    const sourceFiltered = nextArticles(url => url.searchParams.get('source') === catalog.sources[0])
    await page.locator('#article-source').selectOption(catalog.sources[0])
    const data = await (await sourceFiltered).json()
    assert.ok(data.total > 0)
    assert.ok(data.items.every(article => article.source === catalog.sources[0]))
    const cleared = nextArticles(url => !url.searchParams.get('source'))
    await page.getByRole('button', { name: '重置筛选' }).click()
    await cleared
  }
  checks.push('关键词和来源筛选经服务端返回，重置恢复全部范围')

  await page.locator('.article-check').nth(0).click()
  await page.locator('.article-check').nth(1).click()
  const secondPage = nextArticles(url => url.searchParams.get('page') === '2')
  await page.locator('.ant-pagination-item-2').first().click()
  const pageTwo = await (await secondPage).json()
  await page.getByRole('heading', { name: pageTwo.items[0].title, exact: true }).waitFor()
  await page.locator('.article-check').first().click()
  await page.getByText('手动勾选（3 篇）').waitFor()
  assert.ok(availableModels.length, '至少需要一个已配置模型来进行只读预估')
  await page.locator('.model-field .ant-select').click()
  await page.locator('.ant-select-item-option').first().click()
  const previewResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/article-trends/preview')
  await page.getByRole('button', { name: '预估 3 篇' }).click()
  const previewHttp = await previewResponse
  assert.ok(previewHttp.ok(), `preview HTTP ${previewHttp.status()}`)
  const preview = await previewHttp.json()
  assert.equal(preview.article_count, 3)
  await page.locator('.estimate-box').waitFor()
  const estimateCall = calls.find(call => call.path.endsWith('/preview'))
  assert.equal(estimateCall.body.article_ids.length, 3)
  assert.deepEqual(estimateCall.body.filters, {})
  report.preview = { article_count: preview.article_count, source_group_count: preview.source_group_count, estimated_calls: preview.estimated_calls, batch_count: preview.batch_count }
  checks.push('跨两页勾选 3 篇文章，只读预估返回 3 篇；手动范围不叠加筛选')

  await page.locator('.cluster-controls .ant-input-number-input').last().fill('35')
  await page.locator('.cluster-controls .ant-input-number-input').last().blur()
  await page.locator('.estimate-box').waitFor({ state: 'hidden' })
  checks.push('更改调用预算立即使旧预估失效')

  if (mode === 'mock') {
    await page.getByRole('button', { name: '预估 3 篇' }).click()
    await page.getByRole('button', { name: '确认范围并启动' }).click()
    assert.equal(calls.filter(call => call.path.endsWith('/tasks') && call.method === 'POST').length, 0)
    await page.getByRole('button', { name: '确认并运行模型' }).click()
    await page.getByRole('heading', { name: '温暖哑光表面', exact: true }).waitFor()
    assert.equal(calls.filter(call => call.path.endsWith('/tasks') && call.method === 'POST').length, 1)
    await page.getByText('查看文章证据与次级关联').click()
    await page.getByText('哑光表面与温暖色彩', { exact: true }).waitFor()
    await page.getByRole('tab', { name: '候选池（1）' }).click()
    await page.getByText('来源支持不足', { exact: true }).waitFor()
    checks.push('仅模拟接口：明确确认后创建一次任务，显示 priority_rank、anchor 和 pool_reason')
    await page.getByRole('tab', { name: '文章资料库与聚类范围' }).click()
  } else {
    assert.equal(calls.filter(call => call.method === 'POST' && !call.path.endsWith('/preview')).length, 0)
    assert.deepEqual(blockedWrites, [])
    checks.push('真实模式未创建或恢复任务，未调用模型；网络保护阻止预估之外的写请求')
  }

  await page.waitForTimeout(400)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(output, `${mode}-desktop.png`), fullPage: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(output, `${mode}-mobile.png`), fullPage: false })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  assert.ok(await page.evaluate(() => document.querySelector('main').getBoundingClientRect().left >= 0))
  assert.deepEqual(errors, [])
  checks.push('桌面和手机截图完成；手机无水平溢出或焦点横移，未捕获页面错误')
  report.status = 'passed'
} catch (error) {
  report.status = 'failed'
  report.failure = error.stack || String(error)
  await page.screenshot({ path: path.join(output, `${mode}-failure.png`), fullPage: false }).catch(() => {})
  process.exitCode = 1
} finally {
  report.completed_at = new Date().toISOString()
  report.request_counts = { get: calls.filter(call => call.method === 'GET').length, preview: calls.filter(call => call.path === '/article-trends/preview').length, task_writes: calls.filter(call => call.method === 'POST' && call.path.startsWith('/article-trends/tasks')).length }
  await writeFile(path.join(output, `${mode}-browser-report.json`), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
