<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loggingOut = ref(false)
const logoutError = ref('')

async function logout() {
  loggingOut.value = true
  logoutError.value = ''
  try {
    await auth.logout()
  } catch {
    logoutError.value = '退出失败，请重试。'
    loggingOut.value = false
  }
}

function reload() { window.location.reload() }
</script>

<template>
  <RouterView />
  <div v-if="auth.error && !auth.user" class="auth-unavailable" role="alert">
    <p>{{ auth.error }}</p>
    <button type="button" @click="reload">重新加载</button>
  </div>
  <aside v-if="auth.user" class="session-control" aria-label="当前登录用户">
    <span class="session-user">{{ auth.user.username }}</span>
    <button type="button" :disabled="loggingOut" @click="logout">{{ loggingOut ? '退出中…' : '退出登录' }}</button>
    <span v-if="logoutError" class="session-error" role="alert">{{ logoutError }}</span>
  </aside>
</template>

<style scoped>
.session-control {
  position: fixed;
  right: 20px;
  bottom: 18px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 14px;
  max-width: calc(100vw - 32px);
  padding: 10px 15px;
  border: 1px solid rgba(98, 87, 216, .18);
  border-radius: 14px;
  background: rgba(255, 255, 255, .97);
  box-shadow: 0 5px 24px rgba(53, 44, 105, .12);
  color: #51496d;
  font-size: 12px;
}
.session-user { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-control button, .auth-unavailable button {
  border: 0;
  border-radius: 7px;
  padding: 6px 9px;
  background: #ece9ff;
  color: #453aa9;
  cursor: pointer;
}
.session-control button:disabled { cursor: wait; opacity: .6; }
.session-error { color: #a7344c; }
.auth-unavailable { margin: 20vh auto; padding: 32px; max-width: 420px; text-align: center; }
@media (max-width: 600px) {
  .session-control { right: 12px; bottom: 12px; gap: 8px; padding: 8px 10px; flex-wrap: wrap; }
}
</style>
