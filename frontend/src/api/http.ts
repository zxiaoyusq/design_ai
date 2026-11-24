import axios from 'axios'
import { redirectToLogin } from '@/auth/navigation'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
})

// 所有业务请求共用失效处理，避免某个页面继续展示过期会话并重复提交。
http.interceptors.response.use(
  response => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) redirectToLogin()
    return Promise.reject(error)
  },
)
