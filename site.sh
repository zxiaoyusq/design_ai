#!/usr/bin/env bash

# 固定域名部署入口：前端直连 80 端口，API 仅由 Vite 的 /api 代理访问。
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
RUNTIME_DIR="${PROJECT_DIR}/.runtime"
LOG_DIR="${RUNTIME_DIR}/logs"

DESIGN_AI_DOMAIN="${DESIGN_AI_DOMAIN:-gamedevcenter.ahagamecenter.com}"
DESIGN_AI_BACKEND_HOST="${DESIGN_AI_BACKEND_HOST:-127.0.0.1}"
DESIGN_AI_BACKEND_PORT="${DESIGN_AI_BACKEND_PORT:-8000}"
DESIGN_AI_FRONTEND_HOST="${DESIGN_AI_FRONTEND_HOST:-0.0.0.0}"
DESIGN_AI_FRONTEND_PORT="${DESIGN_AI_FRONTEND_PORT:-80}"

BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"
BACKEND_LOG_FILE="${LOG_DIR}/backend.log"
FRONTEND_LOG_FILE="${LOG_DIR}/frontend.log"
BACKEND_PID=""
FRONTEND_PID=""

fail() {
  echo "操作失败：$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：./site.sh <start|stop|restart|status>

  start   启动固定域名站点（前台运行，按 Ctrl+C 也会停止）
  stop    仅停止本脚本启动的前后端进程
  restart 先停止再启动
  status  查看本脚本管理的服务状态

可选环境变量：
  DESIGN_AI_DOMAIN          默认 gamedevcenter.ahagamecenter.com
  DESIGN_AI_BACKEND_PORT    默认 8000，仅本机监听
  DESIGN_AI_FRONTEND_PORT   默认 80，对外监听
EOF
}

read_pid() {
  local pid_file="$1"
  local pid

  [[ -f "${pid_file}" ]] || return 1
  pid="$(<"${pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "${pid}"
}

is_expected_process() {
  local pid_file="$1"
  local expected_command="$2"
  local pid
  local command

  pid="$(read_pid "${pid_file}")" || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  command="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
  [[ "${command}" == *"${expected_command}"* ]]
}

remove_pid_file() {
  rm -f "$1"
}

stop_component() {
  local service_name="$1"
  local pid_file="$2"
  local expected_command="$3"
  local pid
  local child_pid
  local attempt

  if ! pid="$(read_pid "${pid_file}")"; then
    echo "${service_name}未运行。"
    return
  fi

  if ! kill -0 "${pid}" 2>/dev/null; then
    remove_pid_file "${pid_file}"
    echo "${service_name}未运行（已清理过期状态）。"
    return
  fi

  if ! is_expected_process "${pid_file}" "${expected_command}"; then
    # PID 可能已被系统复用；此时宁可保留进程，也不能误杀其他服务。
    remove_pid_file "${pid_file}"
    echo "未停止${service_name}：PID ${pid} 不属于本工程，已清理过期状态。" >&2
    return
  fi

  # pnpm 会派生 Vite；先结束直接子进程，避免只杀包装进程留下监听端口的 Vite。
  while IFS= read -r child_pid; do
    [[ -n "${child_pid}" ]] && kill -TERM "${child_pid}" 2>/dev/null || true
  done < <(pgrep -P "${pid}" 2>/dev/null || true)
  kill -TERM "${pid}"

  for ((attempt = 1; attempt <= 100; attempt++)); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      remove_pid_file "${pid_file}"
      echo "已停止${service_name}（PID ${pid}）。"
      return
    fi
    sleep 0.1
  done

  # 正常退出超时后只终止已确认属于本工程的主进程。
  kill -KILL "${pid}" 2>/dev/null || true
  remove_pid_file "${pid_file}"
  echo "已强制停止${service_name}（PID ${pid}）。"
}

cleanup() {
  local exit_code="$?"

  trap - EXIT INT TERM HUP
  stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm" || true
  stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app" || true
  exit "${exit_code}"
}

ensure_port_available() {
  local port="$1"
  local pids

  pids="$(lsof -nP -t -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "${pids}" ]] || fail "端口 ${port} 已被其他进程占用（PID：${pids//$'\n'/, }）"
}

ensure_not_running() {
  if is_expected_process "${BACKEND_PID_FILE}" "uvicorn app.main:app" \
    || is_expected_process "${FRONTEND_PID_FILE}" "pnpm"; then
    fail "站点已在运行；请使用 ./site.sh status 或 ./site.sh stop"
  fi
  remove_pid_file "${BACKEND_PID_FILE}"
  remove_pid_file "${FRONTEND_PID_FILE}"
}

activate_runtime() {
  local conda_command
  local conda_base
  local conda_profile

  [[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "请先在 frontend 目录执行 pnpm install"
  [[ -f "${BACKEND_DIR}/.env" ]] || fail "缺少 backend/.env"
  if (( DESIGN_AI_FRONTEND_PORT < 1024 )) && (( EUID != 0 )); then
    fail "监听 ${DESIGN_AI_FRONTEND_PORT} 端口需要 root 权限"
  fi

  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
    conda_command="${CONDA_EXE}"
  elif command -v conda >/dev/null 2>&1; then
    conda_command="$(command -v conda)"
  elif [[ -x "/root/miniconda3/bin/conda" ]]; then
    # systemd 的默认 PATH 不包含 Miniconda；本机的工程运行环境固定安装在此处。
    conda_command="/root/miniconda3/bin/conda"
  else
    fail "未找到 conda"
  fi

  conda_base="$(${conda_command} info --base)"
  conda_profile="${conda_base}/etc/profile.d/conda.sh"
  [[ -f "${conda_profile}" ]] || fail "未找到 conda 初始化脚本"

  # 按工程规范固定使用 Python 3.14 环境。
  source "${conda_profile}"
  conda activate 314
  command -v pnpm >/dev/null 2>&1 || fail "314 环境未找到 pnpm"
  (
    cd "${BACKEND_DIR}"
    python -c "import app.main, fastapi, uvicorn, deepagents"
  ) >/dev/null 2>&1 || fail "314 环境缺少后端依赖，请先安装 backend/requirements.txt"
}

wait_for_backend() {
  local attempt
  local backend_url="http://${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}/openapi.json"

  for ((attempt = 1; attempt <= 100; attempt++)); do
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
      tail -n 30 "${BACKEND_LOG_FILE}" >&2 || true
      fail "后端服务启动失败"
    fi
    if curl --fail --silent --show-error --max-time 1 "${backend_url}" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  fail "后端服务未在 10 秒内就绪：${backend_url}"
}

wait_for_frontend() {
  local attempt
  local frontend_url="http://127.0.0.1:${DESIGN_AI_FRONTEND_PORT}/"

  for ((attempt = 1; attempt <= 100; attempt++)); do
    if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
      tail -n 30 "${FRONTEND_LOG_FILE}" >&2 || true
      fail "前端服务启动失败"
    fi
    if curl --fail --silent --show-error --max-time 1 \
      -H "Host: ${DESIGN_AI_DOMAIN}" "${frontend_url}" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  fail "前端服务未在 10 秒内就绪：${frontend_url}"
}

start() {
  mkdir -p "${LOG_DIR}"
  ensure_not_running
  ensure_port_available "${DESIGN_AI_BACKEND_PORT}"
  ensure_port_available "${DESIGN_AI_FRONTEND_PORT}"
  activate_runtime

  (
    cd "${BACKEND_DIR}"
    exec python -m uvicorn app.main:app \
      --host "${DESIGN_AI_BACKEND_HOST}" \
      --port "${DESIGN_AI_BACKEND_PORT}"
  ) >"${BACKEND_LOG_FILE}" 2>&1 &
  BACKEND_PID=$!
  printf '%s\n' "${BACKEND_PID}" >"${BACKEND_PID_FILE}"
  wait_for_backend

  (
    cd "${FRONTEND_DIR}"
    export VITE_BACKEND_URL="http://${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}"
    exec pnpm dev \
      --host "${DESIGN_AI_FRONTEND_HOST}" \
      --port "${DESIGN_AI_FRONTEND_PORT}" \
      --strictPort
  ) >"${FRONTEND_LOG_FILE}" 2>&1 &
  FRONTEND_PID=$!
  printf '%s\n' "${FRONTEND_PID}" >"${FRONTEND_PID_FILE}"
  wait_for_frontend

  echo "站点已启动：http://${DESIGN_AI_DOMAIN}/"
  echo "后端仅监听 ${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}；日志目录：${LOG_DIR}"
  echo "按 Ctrl+C 或执行 ./site.sh stop 可停止站点。"

  while true; do
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
      wait "${BACKEND_PID}" || true
      fail "后端服务已退出"
    fi
    if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
      wait "${FRONTEND_PID}" || true
      fail "前端服务已退出"
    fi
    sleep 1
  done
}

status() {
  if is_expected_process "${BACKEND_PID_FILE}" "uvicorn app.main:app"; then
    echo "后端服务：运行中（PID $(<"${BACKEND_PID_FILE}")）"
  else
    echo "后端服务：未运行"
  fi
  if is_expected_process "${FRONTEND_PID_FILE}" "pnpm"; then
    echo "前端服务：运行中（PID $(<"${FRONTEND_PID_FILE}")）"
  else
    echo "前端服务：未运行"
  fi
}

case "${1:-}" in
  start)
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    start
    ;;
  stop)
    stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm"
    stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app"
    ;;
  restart)
    stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm"
    stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app"
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    start
    ;;
  status)
    status
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
