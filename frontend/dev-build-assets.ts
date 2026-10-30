import { createReadStream, realpathSync, statSync } from 'node:fs'
import { extname, resolve, sep } from 'node:path'
import type { Plugin } from 'vite'

const CONTENT_TYPES: Record<string, string> = {
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

/** 保留旧部署的哈希资源，避免缓存主页或旧标签页在切换到 Vite 后因 MIME 错误白屏。 */
export function devBuildAssets(directory: string): Plugin {
  return {
    name: 'dev-build-assets-compatibility',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = (request.url ?? '').split('?')[0] ?? ''
        if (!pathname.startsWith('/assets/') || !['GET', 'HEAD'].includes(request.method ?? '')) {
          next()
          return
        }
        try {
          const root = realpathSync(directory)
          const file = realpathSync(resolve(root, decodeURIComponent(pathname.slice('/assets/'.length))))
          // 同时限制规范路径和符号链接最终目标，不把 dist 之外的文件作为兼容资源公开。
          if (!file.startsWith(root + sep) || !statSync(file).isFile()) {
            response.statusCode = 404
            response.end('Asset not found')
            return
          }
          response.setHeader('Content-Type', CONTENT_TYPES[extname(file)] ?? 'application/octet-stream')
          response.setHeader('Content-Length', statSync(file).size)
          response.setHeader('Cache-Control', 'no-cache')
          response.setHeader('X-Content-Type-Options', 'nosniff')
          if (request.method === 'HEAD') {
            response.end()
            return
          }
          const stream = createReadStream(file)
          stream.on('error', () => response.destroy())
          stream.pipe(response)
        } catch {
          // 缺失脚本必须返回 404，不能继续落入 SPA 的 200 HTML 兜底。
          response.statusCode = 404
          response.end('Asset not found')
        }
      })
    },
  }
}
