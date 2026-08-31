#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
DESIGN_AI_HOST="${DESIGN_AI_HOST:-127.0.0.1}"
DESIGN_AI_BACKEND_PORT="${DESIGN_AI_BACKEND_PORT:-8000}"
DESIGN_AI_FRONTEND_PORT="${DESIGN_AI_FRONTEND_PORT:-5173}"
BACKEND_PID=""
FRONTEND_PID=""

fail() {
  echo "启动失败：$1" >&2
  exit 1
}

cleanup() {
  trap - EXIT INT TERM
  for pid in "${BACKEND_PID}" "${FRONTEND_PID}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${BACKEND_PID}" "${FRONTEND_PID}"; do
    if [[ -n "${pid}" ]]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT
trap 'exit 130' INT TERM

command -v pnpm >/dev/null 2>&1 || fail "未找到 pnpm"
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

# 按工程规范固定使用 base 环境，避免后端依赖落到其他 Python 环境。
source "${CONDA_PROFILE}"
conda activate base
python -c "import fastapi, uvicorn, deepagents" >/dev/null 2>&1 \
  || fail "base 环境缺少后端依赖，请先安装 backend/requirements.txt"

(
  cd "${BACKEND_DIR}"
  exec python -m uvicorn app.main:app \
    --host "${DESIGN_AI_HOST}" \
    --port "${DESIGN_AI_BACKEND_PORT}"
) &
BACKEND_PID=$!

(
  cd "${FRONTEND_DIR}"
  export VITE_BACKEND_URL="http://127.0.0.1:${DESIGN_AI_BACKEND_PORT}"
  exec pnpm dev \
    --host "${DESIGN_AI_HOST}" \
    --port "${DESIGN_AI_FRONTEND_PORT}" \
    --strictPort
) &
FRONTEND_PID=$!

echo "前端：http://${DESIGN_AI_HOST}:${DESIGN_AI_FRONTEND_PORT}"
echo "后端：http://${DESIGN_AI_HOST}:${DESIGN_AI_BACKEND_PORT}/docs"
echo "按 Ctrl+C 同时停止前后端服务。"

# Bash 3 兼容的双进程监控：任一服务退出时，清理另一服务并返回其退出码。
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
  sleep 1
done

exit "${exit_code}"
