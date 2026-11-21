import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Duplex } from 'node:stream'
import type { Connect, HttpServer, Plugin } from 'vite'

type SessionStatus = 'authenticated' | 'unauthenticated' | 'unavailable'

/** 登录页和 API 交给后端处理；其余源码、旧构建、数据与独立交付页均先验证会话。 */
function isBackendPath(request: IncomingMessage) {
  const pathname = (request.url ?? '/').split('?')[0] ?? '/'
  return pathname === '/login' || pathname === '/api' || pathname.startsWith('/api/')
}

function isNavigation(request: IncomingMessage) {
  return ['GET', 'HEAD'].includes(request.method ?? '') && (
    request.headers['sec-fetch-mode'] === 'navigate' ||
    ['document', 'iframe'].includes(String(request.headers['sec-fetch-dest'])) ||
    String(request.headers.accept ?? '').includes('text/html')
  )
}

function denyRequest(request: IncomingMessage, response: ServerResponse, status: SessionStatus) {
  response.setHeader('Cache-Control', 'private, no-store')
  if (status === 'unauthenticated' && isNavigation(request)) {
    response.statusCode = 302
    response.setHeader('Location', `/login?next=${encodeURIComponent(request.url ?? '/')}`)
    response.end()
    return
  }
  response.statusCode = status === 'unauthenticated' ? 401 : 503
  response.setHeader('Content-Type', 'application/json; charset=utf-8')
  response.end(JSON.stringify({ detail: status === 'unauthenticated' ? '请先登录' : '登录服务暂不可用，请稍后重试' }))
}

/** Vite 自身也提供源码与 public 文件，因此在全部静态中间件之前校验后端 HttpOnly 会话。 */
export function sessionGuard(backendUrl: string): Plugin {
  async function checkSession(request: IncomingMessage): Promise<SessionStatus> {
    try {
      const response = await fetch(new URL('/api/v1/auth/me', backendUrl), {
        headers: { cookie: request.headers.cookie ?? '' },
        redirect: 'manual',
        signal: AbortSignal.timeout(5_000),
      })
      await response.body?.cancel()
      if (response.status === 200) return 'authenticated'
      if (response.status === 401 || response.status === 403) return 'unauthenticated'
    } catch {
      // 后端不可用时不能继续提供文件，否则故障会变成静态资源的鉴权旁路。
    }
    return 'unavailable'
  }

  const middleware: Connect.NextHandleFunction = async (request, response, next) => {
    if (isBackendPath(request)) {
      next()
      return
    }
    const status = await checkSession(request)
    if (response.destroyed) return
    if (status === 'authenticated') {
      // 含用户资料的静态内容不得被共享缓存，也不能在退出后继续从浏览器缓存读取。
      response.setHeader('Cache-Control', 'private, no-store')
      next()
      return
    }
    denyRequest(request, response, status)
  }

  function guardWebSocket(server: HttpServer | null) {
    if (!server) return
    // Vite 的 HMR 在 upgrade 事件直接处理连接，不经过 HTTP 静态中间件。
    const listeners = server.listeners('upgrade')
    for (const listener of listeners) server.removeListener('upgrade', listener)
    server.on('upgrade', async (request: IncomingMessage, socket: Duplex, head: Buffer<ArrayBuffer>) => {
      // upgrade 不允许复用 HTTP 的 /api 旁路，避免 HMR 接受伪装成 API 的连接。
      const status = await checkSession(request)
      if (socket.destroyed) return
      if (status !== 'authenticated') {
        const code = status === 'unauthenticated' ? '401 Unauthorized' : '503 Service Unavailable'
        socket.end(`HTTP/1.1 ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`)
        return
      }
      for (const listener of listeners) listener.call(server, request, socket, head)
    })
  }

  return {
    name: 'design-ai-session-guard',
    enforce: 'pre',
    configureServer(server) {
      server.middlewares.use(middleware)
      guardWebSocket(server.httpServer)
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware)
    },
  }
}
