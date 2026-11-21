let redirecting = false

/** 会话失效后整页进入独立登录页，保留当前页面、查询条件与锚点。 */
export function redirectToLogin() {
  if (redirecting) return
  redirecting = true
  const next = window.location.pathname + window.location.search + window.location.hash
  window.location.replace(`/login?next=${encodeURIComponent(next)}`)
}
