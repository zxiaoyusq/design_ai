/**
 * 真实图片只读回归：封面不遮挡正文、历史趋势图库可预览/回查、坏图降级。
 * 所有非 GET/HEAD/OPTIONS 请求都在上下文层阻止，不创建聚类任务。
 * BASE_URL=http://127.0.0.1 node frontend/tests/article-trends-images-smoke.mjs
 * SKIP_HISTORY=1 可在后端图库接口准备前单独验证文章封面。
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const base = (process.env.BASE_URL || 'http://127.0.0.1').replace(/\/$/, '')
const output = process.env.OUTPUT_DIR || fileURLToPath(new URL('../../data/result/article_trend_images_validation_20261021/', import.meta.url))
const screenshots = path.join(output, 'screenshots')
const sampleOnly = process.env.SAMPLE_ONLY === '1'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/tmp/bubble-ui-check/node_modules/playwright/index.mjs')
const proxyUrl = ['localhost', '127.0.0.1'].includes(new URL(base).hostname) ? null : process.env.SMOKE_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy
const proxy = proxyUrl ? new URL(proxyUrl) : null
const browser = await chromium.launch({ headless: true, ...(proxy ? { proxy: { server: `${proxy.protocol}//${proxy.host}`, ...(proxy.username ? { username: decodeURIComponent(proxy.username), password: decodeURIComponent(proxy.password) } : {}) } } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage()
page.setDefaultTimeout(30_000)
const report = { base_url: base, started_at: new Date().toISOString(), model_invoked: false, checks: [], page_errors: [], blocked_writes: [], cover_metrics: [], gallery_metrics: [] }
let simulateBadImage = ''
page.on('pageerror', error => report.page_errors.push(error.message))
await context.route('**/*', async route => {
  const request = route.request()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
    report.blocked_writes.push({ method: request.method(), url: request.url() })
    return route.fulfill({ status: 403, body: 'Readonly image regression: writes are blocked.' })
  }
  if (simulateBadImage && request.url() === simulateBadImage) return route.fulfill({ status: 404, body: 'Missing image simulation' })
  return route.continue()
})

async function json(endpoint) {
  const response = await context.request.get(`${base}/api/v1/article-trends${endpoint}`)
  assert.ok(response.ok(), `${endpoint}: HTTP ${response.status()}`)
  return response.json()
}
async function shot(name, locator) {
  if (locator) await locator.scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(screenshots, name), fullPage: false })
}
async function imageReady(locator) {
  await locator.scrollIntoViewIfNeeded()
  await locator.evaluate(async image => {
    if (image.complete) return
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Image load timeout: ${image.src}`)), 20_000)
      image.addEventListener('load', () => { clearTimeout(timer); resolve() }, { once: true })
      image.addEventListener('error', () => { clearTimeout(timer); reject(new Error(`Image failed: ${image.src}`)) }, { once: true })
    })
  })
  assert.ok(await locator.evaluate(image => image.complete && image.naturalWidth > 0), '图片应成功解码')
}
async function verifyCovers(width, height) {
  await page.setViewportSize({ width, height })
  const cards = page.locator('.article-card')
  const shapeCounts = { portrait: 0, landscape: 0 }
  const count = sampleOnly ? Math.min(await cards.count(), 3) : await cards.count()
  for (let index = 0; index < count; index++) {
    const card = cards.nth(index), image = card.locator('.card-image img')
    if (!await image.count()) continue
    await imageReady(image)
    await card.locator('h3').scrollIntoViewIfNeeded()
    const metric = await card.evaluate(node => {
      const img = node.querySelector('.card-image img'), cover = node.querySelector('.card-image'), content = node.querySelector('.card-content'), title = node.querySelector('h3')
      const i = img.getBoundingClientRect(), c = cover.getBoundingClientRect(), t = content.getBoundingClientRect(), h = title.getBoundingClientRect()
      const point = document.elementFromPoint(h.x + Math.min(20, h.width / 2), h.y + Math.min(10, h.height / 2))
      return { image_bottom: i.bottom, cover_bottom: c.bottom, content_top: t.top, image_height: i.height, cover_height: c.height, natural_width: img.naturalWidth, natural_height: img.naturalHeight, title: title.textContent, title_clickable: Boolean(point && node.querySelector('.card-open').contains(point)) }
    })
    assert.ok(metric.image_bottom <= metric.cover_bottom + 1, `封面不得越出固定区域：${metric.title}`)
    assert.ok(metric.image_bottom <= metric.content_top + 1, `图片不得覆盖正文：${metric.title}`)
    assert.ok(metric.image_height <= metric.cover_height + 1)
    assert.ok(metric.title_clickable, `标题不得被图片盖住：${metric.title}`)
    assert.ok(metric.title.trim())
    shapeCounts[metric.natural_height > metric.natural_width ? 'portrait' : 'landscape']++
    report.cover_metrics.push({ viewport_width: width, index, ...metric })
  }
  assert.ok(shapeCounts.portrait > 0 && shapeCounts.landscape > 0, '真实首页应覆盖竖图与横图')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  const title = (await cards.first().locator('h3').textContent()).trim()
  const response = page.waitForResponse(response => /\/api\/v1\/article-trends\/articles\/[^/]+$/.test(new URL(response.url()).pathname))
  await cards.first().locator('h3').click()
  assert.equal((await (await response).json()).title, title)
  await page.locator('.detail-title-block h3').filter({ hasText: title }).waitFor()
  await shot(`${width > 700 ? 'desktop' : 'mobile'}-article-covers.png`, cards.first())
  report.checks.push(`${width}px 文章封面：${shapeCounts.portrait} 张竖图、${shapeCounts.landscape} 张横图均未遮挡正文，标题可点击回查。`)
}
async function verifyVisibleGallery(label) {
  const cards = page.locator('.trend-result')
  for (let index = 0; index < await cards.count(); index++) {
    if (sampleOnly && index !== 0 && index !== await cards.count() - 1) continue
    const card = cards.nth(index), items = card.locator('.trend-image-item')
    assert.ok(await items.count() > 0, `历史结果 ${label} 第 ${index + 1} 趋势需有图片`)
    for (let itemIndex = 0; itemIndex < await items.count(); itemIndex++) {
      const item = items.nth(itemIndex), image = item.locator('img').first()
      await imageReady(image)
      const metric = await item.evaluate(node => {
        const image = node.querySelector('img'), frame = node.querySelector('.ant-image'), caption = node.querySelector('figcaption')
        const i = image.getBoundingClientRect(), f = frame.getBoundingClientRect(), c = caption.getBoundingClientRect()
        return { article_id: node.dataset.articleId, src: image.getAttribute('src'), image_bottom: i.bottom, frame_bottom: f.bottom, caption_top: c.top }
      })
      assert.ok(metric.image_bottom <= metric.frame_bottom + 1 && metric.image_bottom <= metric.caption_top + 1, '历史趋势图不应遮住文章标题')
      assert.match(new URL(metric.src, base).pathname, new RegExp(`/articles/${metric.article_id}/images/\\d+$`), '图片 URL 与对应文章 ID 一致')
      report.gallery_metrics.push({ page: label, ...metric })
    }
  }
}
async function openHistory() {
  await page.getByRole('button', { name: '查看历史 100 个趋势结果', exact: true }).click()
  await page.locator('.trend-result').first().waitFor()
}

try {
  await mkdir(screenshots, { recursive: true })
  await page.goto(`${base}/article-trends`, { waitUntil: 'domcontentloaded' })
  await page.locator('.article-card').first().waitFor()
  await verifyCovers(1440, 1000)
  await verifyCovers(390, 844)
  if (!process.env.SKIP_HISTORY) {
    await page.setViewportSize({ width: 1440, height: 1000 })
    const history = (await json('/history'))[0]
    const detail = await json(`/history/${history.id}`)
    assert.equal(detail.result.trends.length, 100)
    assert.ok(detail.result.trends.every(trend => Array.isArray(trend.images) && trend.images.length > 0), '历史 100 趋势都应匹配到本地图片')
    report.history_trends = detail.result.trends.length
    report.history_image_count = detail.result.trends.reduce((count, trend) => count + trend.images.length, 0)
    await openHistory()
    await verifyVisibleGallery('1')
    const firstCard = page.locator('.trend-result').first(), firstImage = firstCard.locator('.trend-image-item').first()
    await firstImage.locator('.ant-image').click()
    await page.locator('.ant-image-preview').waitFor()
    await page.locator('.ant-image-preview-operations-operation').first().click()
    await page.locator('.ant-image-preview').waitFor({ state: 'hidden' })
    await shot('desktop-history-gallery.png', firstCard)
    const articleId = await firstImage.getAttribute('data-article-id')
    const response = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/article-trends/articles/${articleId}`)
    await firstImage.locator('figcaption button').click()
    const article = await (await response).json()
    await page.locator('.detail-title-block h3').filter({ hasText: article.title }).waitFor()
    assert.equal(article.article_id, articleId)
    report.checks.push('历史 100 趋势均含本地关联图片，首个图库可点图放大并关闭、点标题回查对应文章。')
    await openHistory()
    await page.locator('.task-detail .ant-pagination-item-9').click()
    await page.locator('.rank-number').filter({ hasText: /^100$/ }).waitFor()
    assert.equal(await page.locator('.trend-result').count(), 4)
    await verifyVisibleGallery('9')
    await shot('desktop-history-gallery-page-9.png', page.locator('.trend-result').first())
    await page.setViewportSize({ width: 390, height: 844 })
    await verifyVisibleGallery('9-mobile')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await shot('mobile-history-gallery.png', page.locator('.trend-result').first())
    report.checks.push('历史首末页图库逐图成功解码，图片与文章 ID 匹配；桌面及手机图片均未覆盖标题。')

    simulateBadImage = new URL(detail.result.trends[0].images[0].url, base).href
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: '查看历史 100 个趋势结果', exact: true }).waitFor()
    await openHistory()
    const affected = page.locator('.trend-result').first()
    await affected.scrollIntoViewIfNeeded()
    await page.waitForFunction(src => !Array.from(document.querySelectorAll('.trend-result:first-child .trend-image-item img')).some(image => image.src === src), simulateBadImage)
    assert.equal(await affected.locator('.trend-image-item').count(), detail.result.trends[0].images.length - 1)
    await imageReady(affected.locator('.trend-image-item img').first())
    await shot('mobile-history-missing-image.png', affected)
    report.checks.push('模拟一张关联图片 404 后自动移除该图片，其余关联图片正常呈现。')
  }
  assert.deepEqual(report.page_errors, [])
  assert.deepEqual(report.blocked_writes, [])
  report.checks.push('全程仅允许 GET/HEAD/OPTIONS，无任务创建、无模型调用、无页面异常。')
  report.status = 'passed'
} catch (error) {
  report.status = 'failed'
  report.failure = error.stack || String(error)
  await page.screenshot({ path: path.join(screenshots, 'failure.png') }).catch(() => {})
  process.exitCode = 1
} finally {
  report.completed_at = new Date().toISOString()
  await writeFile(path.join(output, process.env.SKIP_HISTORY ? 'covers-report.json' : 'browser-report.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ ...report, cover_metrics: `${report.cover_metrics.length} records`, gallery_metrics: `${report.gallery_metrics.length} records` }, null, 2))
  await browser.close()
}
