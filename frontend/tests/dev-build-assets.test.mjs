import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, before, test } from 'node:test'

import { devBuildAssets } from '../dev-build-assets.ts'

let directory
let server
let origin

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'design-ai-assets-'))
  const assets = join(directory, 'assets')
  await mkdir(assets)
  await writeFile(join(assets, 'index-hash.js'), 'window.legacy = true;')
  await writeFile(join(assets, 'index-hash.css'), 'body { color: red; }')
  await writeFile(join(directory, 'private.txt'), 'not public')
  await symlink(join(directory, 'private.txt'), join(assets, 'outside.txt'))
  let middleware
  devBuildAssets(assets).configureServer({ middlewares: { use(handler) { middleware = handler } } })
  server = createServer((request, response) => middleware(request, response, () => {
    response.statusCode = 418
    response.end('next middleware')
  }))
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  origin = `http://127.0.0.1:${server.address().port}`
})

after(async () => {
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  await rm(directory, { recursive: true })
})

test('旧 JS 和 CSS 保留原字节与正确 MIME，忽略版本查询参数', async () => {
  const js = await fetch(`${origin}/assets/index-hash.js?v=old`)
  assert.equal(js.status, 200)
  assert.match(js.headers.get('content-type'), /^text\/javascript/)
  assert.equal(await js.text(), 'window.legacy = true;')
  const css = await fetch(`${origin}/assets/index-hash.css`)
  assert.match(css.headers.get('content-type'), /^text\/css/)
  assert.equal(await css.text(), 'body { color: red; }')
})

test('HEAD 返回资源元数据但不返回正文', async () => {
  const response = await fetch(`${origin}/assets/index-hash.js`, { method: 'HEAD' })
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('content-length'), '21')
  assert.equal(await response.text(), '')
})

test('缺失资源不允许回退为 SPA HTML', async () => {
  const response = await fetch(`${origin}/assets/missing.js`)
  assert.equal(response.status, 404)
  assert.equal(await response.text(), 'Asset not found')
})

test('路径穿越、符号链接逃逸及非法编码不泄漏其他目录', async () => {
  for (const path of ['..%2fprivate.txt', 'outside.txt', '%E0%A4%A']) {
    const response = await fetch(`${origin}/assets/${path}`)
    assert.equal(response.status, 404)
    assert.doesNotMatch(await response.text(), /not public/)
  }
})

test('不拦截新主页、源码或 API 路径', async () => {
  for (const path of ['/', '/src/main.ts', '/src/assets/base.css', '/api/v1/llm/models']) {
    const response = await fetch(origin + path)
    assert.equal(response.status, 418)
  }
})
