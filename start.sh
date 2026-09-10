#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
DESIGN_AI_HOST="${DESIGN_AI_HOST:-127.0.0.1}"
DESIGN_AI_BACKEND_PORT="${DESIGN_AI_BACKEND_PORT:-8000}"
DESIGN_AI_FRONTEND_PORT="${DESIGN_AI_FRONTEND_PORT:-5173}"
CLOUDFLARED_BIN="${DESIGN_AI_CLOUDFLARED:-}"
BACKEND_PID=""
FRONTEND_PID=""
TUNNEL_PID=""
TUNNEL_LOG_FILE=""
TUNNEL_URL=""

fail() {
  echo "启动失败：$1" >&2
  exit 1
}

cleanup() {
  trap - EXIT INT TERM
  # 先关闭公网 Tunnel，再停止本地服务，缩短退出时的外网暴露窗口。
  for pid in "${TUNNEL_PID}" "${FRONTEND_PID}" "${BACKEND_PID}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${TUNNEL_PID}" "${FRONTEND_PID}" "${BACKEND_PID}"; do
    if [[ -n "${pid}" ]]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
  if [[ -n "${TUNNEL_LOG_FILE}" ]]; then
    rm -f "${TUNNEL_LOG_FILE}"
  fi
}

wait_for_backend() {
  local attempt
  local backend_url="http://${DESIGN_AI_HOST}:${DESIGN_AI_BACKEND_PORT}"

  # 后端首次导入 Agent 与 Skill 时会比 Vite 更慢，先确认 API 已可用再启动前端，避免首次请求被代理拒绝。
  for ((attempt = 1; attempt <= 100; attempt++)); do
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
      fail "后端服务启动失败，请查看上方 Uvicorn 输出"
    fi
    if curl --fail --silent --show-error --max-time 1 "${backend_url}/openapi.json" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  fail "后端服务未在 10 秒内就绪：${backend_url}"
}

trap cleanup EXIT
trap 'exit 130' INT TERM

[[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "请先在 frontend 目录执行 pnpm install"
[[ -f "${BACKEND_DIR}/.env" ]] || fail "缺少 backend/.env"

if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
  CONDA_COMMAND="${CONDA_EXE}"
elif command -v conda >/dev/null 2>&1; then
  CONDA_COMMAND="$(command -v conda)"
else
  fail "未找到 conda"
fi

CONDA_BASE="$(${CONDA_COMMAND} info --base)"
CONDA_PROFILE="${CONDA_BASE}/etc/profile.d/conda.sh"
[[ -f "${CONDA_PROFILE}" ]] || fail "未找到 conda 初始化脚本"

# 按工程规范固定使用 314 环境，确保后端运行在 Python 3.14。
source "${CONDA_PROFILE}"
conda activate 314
command -v pnpm >/dev/null 2>&1 || fail "314 环境未找到 pnpm"
pnpm --version >/dev/null 2>&1 || fail "314 环境中的 pnpm 无法运行"
if [[ -n "${CLOUDFLARED_BIN}" ]]; then
  [[ -x "${CLOUDFLARED_BIN}" ]] || fail "DESIGN_AI_CLOUDFLARED 指定的文件不可执行"
elif command -v cloudflared >/dev/null 2>&1; then
  CLOUDFLARED_BIN="$(command -v cloudflared)"
else
  fail "未找到 cloudflared"
fi
(
  cd "${BACKEND_DIR}"
  python -c "import app.main, fastapi, uvicorn, deepagents"
) >/dev/null 2>&1 \
  || fail "314 环境缺少后端依赖，请先安装 backend/requirements.txt"

(
  cd "${BACKEND_DIR}"
  exec python -m uvicorn app.main:app \
    --host "${DESIGN_AI_HOST}" \
    --port "${DESIGN_AI_BACKEND_PORT}"
) &
BACKEND_PID=$!

wait_for_backend

(
  cd "${FRONTEND_DIR}"
  export VITE_BACKEND_URL="http://127.0.0.1:${DESIGN_AI_BACKEND_PORT}"
  exec pnpm dev \
    --host "${DESIGN_AI_HOST}" \
    --port "${DESIGN_AI_FRONTEND_PORT}" \
    --strictPort
) &
FRONTEND_PID=$!

TUNNEL_LOG_FILE="$(mktemp /tmp/design-ai-cloudflared.XXXXXX.log)"
(
  exec "${CLOUDFLARED_BIN}" tunnel \
    --no-autoupdate \
    --protocol http2 \
    --url "http://127.0.0.1:${DESIGN_AI_FRONTEND_PORT}"
) >"${TUNNEL_LOG_FILE}" 2>&1 &
TUNNEL_PID=$!

# 域名生成早于边缘连接可用，必须等到至少一个连接注册成功后再输出地址。
TUNNEL_READY=0
for _ in {1..240}; do
  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    tail -n 30 "${TUNNEL_LOG_FILE}" >&2 || true
    fail "Cloudflare Tunnel 启动失败"
  fi
  TUNNEL_URL="$(awk '
    match($0, /https:\/\/[a-z0-9-]+\.trycloudflare\.com/) {
      print substr($0, RSTART, RLENGTH)
      exit
    }
  ' "${TUNNEL_LOG_FILE}")"
  if [[ -n "${TUNNEL_URL}" ]] && awk '
    /Registered tunnel connection/ { ready=1 }
    END { exit !ready }
  ' "${TUNNEL_LOG_FILE}"; then
    TUNNEL_READY=1
    break
  fi
  sleep 0.25
done

if [[ "${TUNNEL_READY}" -ne 1 ]]; then
  tail -n 30 "${TUNNEL_LOG_FILE}" >&2 || true
  fail "等待 Cloudflare 临时域名超时"
fi

echo "前端：http://${DESIGN_AI_HOST}:${DESIGN_AI_FRONTEND_PORT}"
echo "后端：http://${DESIGN_AI_HOST}:${DESIGN_AI_BACKEND_PORT}/docs"
echo "Cloudflare：${TUNNEL_URL}"
echo "临时域名会在每次重启后变化；按 Ctrl+C 同时停止 Tunnel 和前后端服务。"

# Bash 3 兼容的多进程监控：任一服务退出时，清理其余服务并返回其退出码。
exit_code=0
while true; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    set +e
    wait "${BACKEND_PID}"
    exit_code=$?
    set -e
    break
  fi
  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    set +e
    wait "${FRONTEND_PID}"
    exit_code=$?
    set -e
    break
  fi
  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    set +e
    wait "${TUNNEL_PID}"
    exit_code=$?
    set -e
    break
  fi
  sleep 1
done

exit "${exit_code}"
