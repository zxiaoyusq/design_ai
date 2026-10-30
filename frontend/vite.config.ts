import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

import { devBuildAssets } from './dev-build-assets.ts'

const backendUrl = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue(), devBuildAssets(fileURLToPath(new URL('./dist/assets/', import.meta.url)))],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 固定域名通过现有负载均衡回源到 site.sh 启动的 80 端口。
    allowedHosts: ['.trycloudflare.com', 'gamedevcenter.ahagamecenter.com'],
    // 前端静态快照与设计修改演示引用本地原图，仅开放所需图片目录供开发服务读取。
    fs: {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../data/trend_data/images/', import.meta.url)),
        fileURLToPath(new URL('../data/userreseach_data/images/', import.meta.url)),
        fileURLToPath(new URL('../ref/手机图/', import.meta.url)),
      ],
    },
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
})
