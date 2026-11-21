import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../../backend/app/templates/login.html', import.meta.url), 'utf8')
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1]

function login(search = '', status = 200) {
  const navigation = []
  const elements = new Map(['login-form', 'username', 'password', 'visibility', 'submit', 'error'].map(id => [id, {
    value: id === 'username' ? ' test-user ' : id === 'password' ? 'test-secret' : '',
    type: id === 'password' ? 'password' : '',
    hidden: false,
    disabled: false,
    events: new Map(),
    attributes: new Map(),
    reportValidity() { return true },
    addEventListener(name, callback) { this.events.set(name, callback) },
    setAttribute(name, value) { this.attributes.set(name, value) },
  }]))
  const requests = []
  runInNewContext(source, {
    document: { getElementById(id) { return elements.get(id) } },
    window: { location: { origin: 'https://design.example', search, replace(url) { navigation.push(url) } } },
    URL, URLSearchParams,
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: status === 200, status } },
  })
  return {
    navigation, elements, requests,
    submit: () => elements.get('login-form').events.get('submit')({ preventDefault() {} }),
  }
}

test('登录页自包含，成功登录使用 JSON 账号密码且保留目标页面', async () => {
  assert.doesNotMatch(html, /<(?:script|link)[^>]+(?:src|href)=/i)
  const page = login('?next=%2Fuser-research%3Fcountry%3DID%26q%3Da%2526b%23gallery')
  await page.submit()
  assert.equal(page.requests[0].url, '/api/v1/auth/login')
  assert.deepEqual(JSON.parse(page.requests[0].options.body), { username: 'test-user', password: 'test-secret' })
  assert.equal(page.requests[0].options.credentials, 'same-origin')
  assert.deepEqual(page.navigation, ['/user-research?country=ID&q=a%26b#gallery'])
  assert.equal(page.elements.get('password').value, '')
})

test('nginx 原样附带的 URI 也完整保留查询参数及已有转义', async () => {
  const page = login('?next=/article-trends?country=ID&q=a%26b&date=2026-10-30')
  await page.submit()
  assert.deepEqual(page.navigation, ['/article-trends?country=ID&q=a%26b&date=2026-10-30'])
})

test('拒绝外站跳转、反斜杠、控制字符和登录页循环', async () => {
  for (const target of ['https://evil.example/', '//evil.example/', '/\\evil.example/', '/%5cevil.example/', '/%2fevil.example/', '/login', '/login/', '/%6cogin?next=/user-research', '/%00hidden']) {
    const page = login(`?next=${encodeURIComponent(target)}`)
    await page.submit()
    assert.deepEqual(page.navigation, ['/'], target)
  }
})

test('失败保持在登录页并提供通用提示，可继续重试', async () => {
  const page = login('', 401)
  await page.submit()
  assert.deepEqual(page.navigation, [])
  assert.equal(page.elements.get('error').hidden, false)
  assert.match(page.elements.get('error').textContent, /用户名或密码不正确/)
  assert.equal(page.elements.get('submit').disabled, false)
})

test('显示密码开关同步输入类型和辅助技术状态', () => {
  const page = login()
  const toggle = page.elements.get('visibility')
  toggle.events.get('click')()
  assert.equal(page.elements.get('password').type, 'text')
  assert.equal(toggle.attributes.get('aria-pressed'), 'true')
  toggle.events.get('click')()
  assert.equal(page.elements.get('password').type, 'password')
  assert.equal(toggle.attributes.get('aria-pressed'), 'false')
})
