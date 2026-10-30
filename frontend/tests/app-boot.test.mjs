import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('../public/app-boot.js', import.meta.url), 'utf8')

function start({ href = 'https://example.com/dna-v2?filter=ID#results', storageBlocked = false, stored = new Map() } = {}) {
  const listeners = new Map()
  const navigation = []
  const timers = new Map()
  const elements = new Map(['app', 'app-startup', 'app-startup-title', 'app-startup-message', 'app-startup-reload'].map((id) => [id, {
    hidden: false, textContent: '', children: [], attributes: {},
    setAttribute(key, value) { this.attributes[key] = value },
  }]))
  let mutation
  const window = {
    location: Object.assign(new URL(href), { replace(url) { navigation.push(url) } }),
    sessionStorage: {
      getItem(key) { if (storageBlocked) throw Error('Storage denied'); return stored.get(key) ?? null },
      setItem(key, value) { if (storageBlocked) throw Error('Storage denied'); stored.set(key, value) },
    },
    addEventListener(type, callback) {
      listeners.set(type, [...(listeners.get(type) ?? []), callback])
    },
    setTimeout(callback) { const id = timers.size + 1; timers.set(id, callback); return id },
    clearTimeout(id) { timers.delete(id) },
    MutationObserver: class {
      constructor(callback) { mutation = callback }
      observe() {}
      disconnect() { mutation = undefined }
    },
  }
  runInNewContext(source, { window, document: { getElementById(id) { return elements.get(id) } }, URL })
  return {
    elements, navigation, stored,
    dispatch(type, event) { for (const callback of listeners.get(type) ?? []) callback(event) },
    mount() { elements.get('app').children.push({}); mutation?.() },
    timeout() { for (const callback of timers.values()) callback() },
  }
}

const scriptFailure = { target: { tagName: 'SCRIPT', src: 'https://example.com/src/main.ts' } }
const dynamicFailure = { reason: new Error('Failed to fetch dynamically imported module: /src/views/DnaV2View.vue') }

test('启动脚本失败只自动刷新一次，保留查询、锚点和其他会话数据', () => {
  const saved = new Map([['user-selection', 'keep']])
  const first = start({ stored: saved })
  first.dispatch('error', scriptFailure)
  first.dispatch('unhandledrejection', dynamicFailure)
  assert.equal(first.navigation.length, 1)
  const url = new URL(first.navigation[0])
  assert.equal(url.searchParams.get('filter'), 'ID')
  assert.equal(url.hash, '#results')
  assert.ok(url.searchParams.get('__app_cache'))
  assert.ok(url.searchParams.get('__app_retry'))
  assert.equal(saved.get('user-selection'), 'keep')

  const second = start({ href: url.href, stored: saved })
  second.dispatch('error', scriptFailure)
  assert.equal(second.navigation.length, 0)
  assert.equal(second.elements.get('app-startup-title').textContent, '页面加载失败')
  assert.equal(second.elements.get('app-startup').attributes.role, 'alert')
  second.elements.get('app-startup-reload').onclick()
  assert.equal(second.navigation.length, 1)
})

test('拒绝会话存储时仍以 URL 阻断重复自动刷新', () => {
  const first = start({ storageBlocked: true })
  first.dispatch('unhandledrejection', dynamicFailure)
  assert.equal(first.navigation.length, 1)
  const second = start({ href: first.navigation[0], storageBlocked: true })
  second.dispatch('unhandledrejection', dynamicFailure)
  assert.equal(second.navigation.length, 0)
  assert.equal(second.elements.get('app-startup').hidden, false)
})

test('会话 guard 在用户回到无重试参数的原链接时仍限制自动刷新', () => {
  const first = start()
  first.dispatch('error', scriptFailure)
  const second = start({ stored: first.stored })
  second.dispatch('error', scriptFailure)
  assert.equal(second.navigation.length, 0)
})

test('图片、API 失败与普通业务异常不会自动刷新或被吞掉', () => {
  const page = start()
  page.dispatch('error', { target: { tagName: 'IMG', src: 'https://example.com/missing.jpg' } })
  page.dispatch('error', { message: 'Cannot read properties of undefined' })
  page.dispatch('unhandledrejection', { reason: new Error('Request failed with status code 500') })
  page.dispatch('app:module-load-error', { detail: '普通业务异常' })
  assert.equal(page.navigation.length, 0)
  assert.equal(page.elements.get('app-startup').attributes.role, undefined)
})

test('成功显示后隐藏提示，后续路由模块失败显示重载入口并保留页面', () => {
  const page = start()
  page.mount()
  assert.equal(page.elements.get('app-startup').hidden, true)
  page.dispatch('app:module-load-error', { detail: dynamicFailure.reason.message })
  assert.equal(page.navigation.length, 0)
  assert.equal(page.elements.get('app-startup').hidden, false)
  assert.equal(page.elements.get('app').children.length, 1)
  assert.equal(page.elements.get('app-startup-title').textContent, '页面加载失败')
})

test('长时间未挂载只提示等待与手动加载，不因网络慢自动刷新', () => {
  const page = start()
  page.timeout()
  assert.equal(page.navigation.length, 0)
  assert.equal(page.elements.get('app-startup-title').textContent, '页面加载尚未完成')
  page.mount()
  assert.equal(page.elements.get('app-startup').hidden, true)
})
