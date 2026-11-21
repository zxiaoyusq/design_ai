import { defineStore } from 'pinia'
import { ref } from 'vue'

import { http } from '@/api/http'

/** 当前会话只保存展示身份；认证凭据始终由浏览器的 HttpOnly Cookie 管理。 */
export interface SessionUser {
  username: string
  role: string
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<SessionUser | null>(null)
  const error = ref('')
  let pending: Promise<void> | undefined

  async function checkSession() {
    if (!pending) {
      pending = (async () => {
        error.value = ''
        try {
          user.value = (await http.get<SessionUser>('/auth/me')).data
        } catch (cause) {
          user.value = null
          error.value = '无法验证登录状态，请稍后重试。'
          throw cause
        } finally {
          pending = undefined
        }
      })()
    }
    await pending
  }

  async function logout() {
    await http.post('/auth/logout')
    user.value = null
    window.location.replace('/login')
  }

  return { user, error, checkSession, logout }
})
