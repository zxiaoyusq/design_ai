/**
 * 日期输入与历史 100 趋势的真实只读冒烟；唯一允许的 POST 为无模型调用的范围预估。
 * BASE_URL=http://127.0.0.1 PLAYWRIGHT_MODULE=/tmp/bubble-ui-check/node_modules/playwright/index.mjs node frontend/tests/article-trends-date-history-smoke.mjs
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const base = (process.env.BASE_URL || 'http://127.0.0.1').replace(/\/$/, '')
const output = process.env.OUTPUT_DIR || fileURLToPath(new URL('../../data/result/article_trend_date_history_validation_20261021/', import.meta.url))
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/tmp/bubble-ui-check/node_modules/playwright/index.mjs')
const proxyUrl = new URL(base).hostname === '127.0.0.1' || new URL(base).hostname === 'localhost'
  ? undefined : process.env.SMOKE_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy
const proxy = proxyUrl ? new URL(proxyUrl) : null
const browser = await chromium.launch({ headless: true, ...(proxy ? { proxy: { server: `${proxy.protocol}//${proxy.host}`, ...(proxy.username ? { username: decodeURIComponent(proxy.username), password: decodeURIComponent(proxy.password) } : {}) } } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(30_000)
const checks = [], errors = [], calls = [], blockedWrites = []
const report = { base_url: base, started_at: new Date().toISOString(), mode: 'live-readonly', model_invoked: false, checks, errors, blocked_writes: blockedWrites }
page.on('pageerror', error => errors.push(error.message))
// 守卫覆盖整个浏览器上下文，包含新窗口；不只是阻止已知任务按钮。
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url()), method = request.method()
  const isPreview = method === 'POST' && url.origin === new URL(base).origin && url.pathname === '/api/v1/article-trends/preview'
  if (url.pathname.startsWith('/api/v1/')) calls.push({ method, path: url.pathname, body: request.postDataJSON() })
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !isPreview) {
    blockedWrites.push({ method, path: url.pathname })
    return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: '只读验证禁止创建、恢复任务及其它写操作。' }) })
  }
  return route.continue()
})

function articlesResponse(predicate = () => true) {
  return page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname === '/api/v1/article-trends/articles' && predicate(url) })
}
async function getJson(endpoint) {
  const response = await context.request.get(`${base}/api/v1${endpoint}`)
  assert.ok(response.ok(), `${endpoint}: HTTP ${response.status()}`)
  return response.json()
}
async function setDates(start, end) {
  const response = articlesResponse(url => url.searchParams.get('date_from') === start && url.searchParams.get('date_to') === end)
  await page.locator('#article-start').fill(start)
  await page.locator('#article-end').fill(end)
  const http = await response
  assert.ok(http.ok(), `date range HTTP ${http.status()}`)
  const data = await http.json()
  await page.waitForFunction(expected => document.querySelectorAll('.article-card').length === Math.min(expected, 24), data.total)
  if (data.items[0]) await page.locator('.article-card').first().getByRole('heading', { name: data.items[0].title, exact: true }).waitFor()
  return data
}
async function preview(count) {
  const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/article-trends/preview')
  await page.getByRole('button', { name: `预估 ${count.toLocaleString()} 篇`, exact: true }).click()
  const http = await response
  assert.ok(http.ok(), `preview HTTP ${http.status()}`)
  const value = await http.json()
  assert.equal(value.article_count, count)
  await page.locator('.estimate-box').waitFor()
  return value
}
async function screenshot(name, locator) {
  if (locator) await locator.scrollIntoViewIfNeeded()
  await page.waitForTimeout(200)
  await page.screenshot({ path: path.join(output, name), fullPage: false })
}

try {
  await mkdir(output, { recursive: true })
  const initial = articlesResponse()
  const [initialHttp] = await Promise.all([initial, page.goto(`${base}/article-trends`, { waitUntil: 'domcontentloaded' })])
  const first = await initialHttp.json()
  await page.locator('.article-card').first().waitFor()
  assert.equal(first.total, 8833)
  assert.equal(await page.locator('.cluster-panel #article-start').count(), 1)
  assert.equal(await page.locator('.cluster-panel #article-end').count(), 1)
  checks.push('开始趋势语义聚类面板内提供趋势日期起止，目录共 8,833 篇。')

  // 从少量真实目录挑选两个各有至少两篇文章的日期，不读取全量语义内容、不调用模型。
  const dateCounts = new Map()
  for (let index = 1; index <= 8 && [...dateCounts.values()].filter(count => count >= 2).length < 2; index++) {
    const sample = await getJson(`/article-trends/articles?page=${index}&page_size=96`)
    for (const article of sample.items) if (article.published_at) dateCounts.set(article.published_at, (dateCounts.get(article.published_at) || 0) + 1)
  }
  const dates = [...dateCounts].filter(([, count]) => count >= 2).map(([date]) => date).sort().reverse().slice(0, 2).sort()
  assert.equal(dates.length, 2, '小范围目录中需要两个可各勾选两篇的不同日期')
  const [older, newer] = dates
  report.dates = { older, newer }
  const range = await setDates(older, newer)
  assert.ok(range.items.every(article => article.published_at >= older && article.published_at <= newer))
  const [olderDay, newerDay] = await Promise.all([getJson(`/article-trends/articles?page=1&page_size=24&date_from=${older}&date_to=${older}`), getJson(`/article-trends/articles?page=1&page_size=24&date_from=${newer}&date_to=${newer}`)])
  assert.ok(olderDay.total >= 2 && newerDay.total >= 2)
  assert.ok(range.total >= olderDay.total + newerDay.total)
  assert.ok(olderDay.items.every(article => article.published_at === older))
  assert.ok(newerDay.items.every(article => article.published_at === newer))
  await page.locator('.model-field .ant-select').click()
  await page.locator('.ant-select-item-option').first().click()
  await preview(range.total)
  assert.deepEqual(calls.filter(call => call.path.endsWith('/preview')).at(-1).body.filters, { date_from: older, date_to: newer })
  checks.push(`筛选范围 ${older} 至 ${newer}（含首尾）返回 ${range.total} 篇，预估输入数一致。`)

  await setDates(older, older)
  await page.locator('.estimate-box').waitFor({ state: 'hidden' })
  await page.locator('.article-check').nth(0).click()
  await page.locator('.article-check').nth(1).click()
  await setDates(newer, newer)
  await page.locator('.article-check').nth(0).click()
  await page.locator('.article-check').nth(1).click()
  await setDates(older, newer)
  const keywordResponse = articlesResponse(url => url.searchParams.get('q') === 'NO_MATCH_DATE_HISTORY_SMOKE_20261021')
  await page.locator('#article-keyword').fill('NO_MATCH_DATE_HISTORY_SMOKE_20261021')
  assert.equal((await (await keywordResponse).json()).total, 0)
  await preview(4)
  const manual = calls.filter(call => call.path.endsWith('/preview')).at(-1).body
  assert.equal(manual.article_ids.length, 4)
  assert.deepEqual(manual.filters, { date_from: older, date_to: newer })
  await setDates(newer, newer)
  await page.locator('.estimate-box').waitFor({ state: 'hidden' })
  await preview(2)
  const narrowed = calls.filter(call => call.path.endsWith('/preview')).at(-1).body
  assert.equal(narrowed.article_ids.length, 4, '跨日期勾选保留，由后端按日期收窄输入')
  assert.deepEqual(narrowed.filters, { date_from: newer, date_to: newer })
  report.manual_preview = { checked: 4, eligible: 2 }
  checks.push('跨日期勾选 4 篇；手动模式忽略关键词，只叠加日期。收窄到单日输入 2 篇，旧预估立即失效。')
  await screenshot('desktop-date-input.png', page.locator('.cluster-panel'))
  await page.setViewportSize({ width: 390, height: 844 })
  await screenshot('mobile-date-input.png', page.locator('.cluster-date-row'))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  const mobileDateInputs = await page.locator('.cluster-date-row input').evaluateAll(inputs => inputs.map(input => ({ width: input.getBoundingClientRect().width, top: input.getBoundingClientRect().top })))
  assert.ok(mobileDateInputs.every(input => input.width >= 250), '手机日期输入需要足够宽度显示完整年月日，不得依赖 overflow 隐藏截断')
  assert.ok(mobileDateInputs[1].top > mobileDateInputs[0].top, '手机日期输入应分行显示')
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.getByRole('button', { name: '查看历史 100 个趋势结果', exact: true }).click()
  await page.locator('.trend-result').first().waitFor()
  const historical = (await getJson('/article-trends/history'))[0]
  const details = await getJson(`/article-trends/history/${historical.id}`)
  assert.equal(details.kind, 'historical')
  assert.equal(details.result.trends.length, 100)
  assert.equal(details.review_status, 'pending_human_review')
  assert.match(details.legacy_notice, /旧版.*100/)
  assert.match(details.legacy_notice, /待人工审阅/)
  assert.equal(await page.locator('.trend-result').count(), 12)
  await page.locator('.task-detail .ant-alert').filter({ hasText: '待人工审阅' }).waitFor()
  assert.equal(await page.getByRole('button', { name: '恢复任务', exact: true }).count(), 0)
  const download = page.getByRole('link', { name: /下载历史.*原档/ })
  assert.equal(await download.getAttribute('href'), details.download_url)
  assert.equal(new URL(details.download_url, base).pathname, `/api/v1/article-trends/history/${historical.id}/download`)
  await screenshot('desktop-history-results.png', page.locator('.task-detail'))
  const lastPage = page.locator('.task-detail .ant-pagination-item-9')
  await lastPage.click()
  await page.locator('.rank-number').filter({ hasText: /^100$/ }).waitFor()
  assert.equal(await page.locator('.trend-result').count(), 4)
  assert.deepEqual(await page.locator('.rank-number').allTextContents(), ['97', '98', '99', '100'])
  const lastTitles = await page.locator('.trend-result h3').allTextContents()
  assert.deepEqual(lastTitles, details.result.trends.slice(96).map(trend => trend.title))
  checks.push('历史 100 趋势按原排序分页展示；末页为 97–100，保留待人工审阅警告及原档下载链接，无恢复任务入口。')
  await screenshot('desktop-history-page-9.png', page.locator('.task-detail'))
  await page.setViewportSize({ width: 390, height: 844 })
  await screenshot('mobile-history-results.png', page.locator('.result-heading'))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const card = page.locator('.trend-result').first()
  await card.locator('summary').first().click()
  const evidence = details.result.trends[96].members[0]
  assert.ok(evidence.article_id)
  const detailResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/article-trends/articles/${evidence.article_id}`)
  await card.locator('.evidence-row .text-button').first().click()
  const article = await (await detailResponse).json()
  assert.equal(article.article_id, evidence.article_id)
  await page.locator('.detail-title-block h3').filter({ hasText: article.title }).waitFor()
  checks.push('历史代表证据可跳转到对应真实文章详情；手机日期面板与历史结果无水平溢出。')
  assert.deepEqual(errors, [])
  assert.deepEqual(blockedWrites, [])
  assert.equal(calls.filter(call => !['GET', 'HEAD', 'OPTIONS'].includes(call.method) && call.path !== '/api/v1/article-trends/preview').length, 0)
  checks.push('所有交互仅 GET 与只读 preview；未创建/恢复任务、未调用模型，无浏览器页面错误。')
  report.status = 'passed'
} catch (error) {
  report.status = 'failed'
  report.failure = error.stack || String(error)
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: false }).catch(() => {})
  process.exitCode = 1
} finally {
  report.completed_at = new Date().toISOString()
  report.request_counts = { get: calls.filter(call => call.method === 'GET').length, preview: calls.filter(call => call.method === 'POST' && call.path.endsWith('/preview')).length, task_writes: calls.filter(call => call.method === 'POST' && call.path.includes('/tasks')).length }
  await writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
