import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { connect } from 'node:net'
import { after, before, test } from 'node:test'

import { sessionGuard } from '../auth-guard.ts'

let backend
let frontend
let origin
let forwardedCookie

before(async () => {
  backend = createServer((request, response) => {
    assert.equal(request.url, '/api/v1/auth/me')
    forwardedCookie = request.headers.cookie
    response.statusCode = request.headers.cookie === 'design_ai_session=valid' ? 200 : request.headers.cookie === 'unavailable' ? 500 : 401
    response.end()
  })
  await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve))
  let middleware
  frontend = createServer((request, response) => middleware(request, response, () => {
    response.statusCode = 200
    response.end('protected content')
  }))
  frontend.on('upgrade', (_request, socket) => socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n'))
  sessionGuard(`http://127.0.0.1:${backend.address().port}`).configureServer({
    httpServer: frontend,
    middlewares: { use(handler) { middleware = handler } },
  })
  await new Promise(resolve => frontend.listen(0, '127.0.0.1', resolve))
  origin = `http://127.0.0.1:${frontend.address().port}`
})

after(async () => {
  await Promise.all([backend, frontend].map(server => new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))))
})

test('未登录的页面导航跳转登录页并完整保留路径及查询条件', async () => {
  const response = await fetch(`${origin}/user-research?country=ID&q=a%26b`, { headers: { Accept: 'text/html' }, redirect: 'manual' })
  assert.equal(response.status, 302)
  const login = new URL(response.headers.get('location'), origin)
  assert.equal(login.pathname, '/login')
  assert.equal(login.searchParams.get('next'), '/user-research?country=ID&q=a%26b')
  assert.match(response.headers.get('cache-control'), /no-store/)
})

test('源码、历史构建、公开目录数据和独立 HTML 均不能绕过登录', async () => {
  for (const path of ['/src/main.ts', '/@vite/client', '/assets/index-old.js', '/user-research/users.json', '/visual-workflow/board/index.html']) {
    const response = await fetch(origin + path)
    assert.equal(response.status, 401, path)
    assert.doesNotMatch(await response.text(), /protected content/)
  }
})

test('有效 Cookie 转交后端验证后才提供文件，且不允许缓存资料', async () => {
  const response = await fetch(`${origin}/assets/index-old.js`, { headers: { cookie: 'design_ai_session=valid' } })
  assert.equal(response.status, 200)
  assert.equal(forwardedCookie, 'design_ai_session=valid')
  assert.equal(await response.text(), 'protected content')
  assert.match(response.headers.get('cache-control'), /private.*no-store/)
})

test('登录页和 API 继续交给后端，近似登录路径仍须鉴权', async () => {
  for (const path of ['/login?next=%2F', '/api/v1/auth/login', '/api']) {
    assert.equal((await fetch(origin + path)).status, 200, path)
  }
  for (const path of ['/login/', '/login-extra', '/api-other']) {
    assert.equal((await fetch(origin + path)).status, 401, path)
  }
})

test('后端故障时拒绝继续提供静态内容', async () => {
  const response = await fetch(`${origin}/user-research`, { headers: { cookie: 'unavailable', accept: 'text/html' }, redirect: 'manual' })
  assert.equal(response.status, 503)
  assert.equal(response.headers.get('location'), null)
  assert.doesNotMatch(await response.text(), /protected content/)
})

async function upgrade(cookie = '', path = '/?token=vite-token') {
  return await new Promise((resolve, reject) => {
    const socket = connect(frontend.address().port, '127.0.0.1', () => {
      socket.write(`GET ${path} HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Protocol: vite-hmr\r\nCookie: ${cookie}\r\n\r\n`)
    })
    socket.on('error', reject)
    socket.once('data', data => { socket.destroy(); resolve(data.toString()) })
  })
}

test('HMR 升级连接同样要求会话，拒绝匿名连接并放行有效会话', async () => {
  assert.match(await upgrade(), /^HTTP\/1.1 401 /)
  assert.match(await upgrade('design_ai_session=valid'), /^HTTP\/1.1 101 /)
  assert.match(await upgrade('unavailable'), /^HTTP\/1.1 503 /)
  assert.match(await upgrade('', '/api?token=vite-token'), /^HTTP\/1.1 401 /)
})
