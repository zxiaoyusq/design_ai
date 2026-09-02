#!/usr/bin/env bash

set -Eeuo pipefail

DESIGN_AI_BACKEND_PORT="${DESIGN_AI_BACKEND_PORT:-8000}"
DESIGN_AI_FRONTEND_PORT="${DESIGN_AI_FRONTEND_PORT:-5173}"

stop_service() {
  local service_name="$1"
  local port="$2"
  local expected_command="$3"
  local pid
  local command
  local stopped=0

  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"

    # 端口可能被其他本地服务占用，只停止由本工程启动的服务。
    if [[ "${command}" != *"${expected_command}"* ]]; then
      echo "跳过 ${port} 端口的非项目进程（PID ${pid}）。"
      continue
    fi

    kill "${pid}"
    echo "已停止${service_name}（PID ${pid}，端口 ${port}）。"
    stopped=1
  done < <(lsof -nP -t -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)

  if [[ "${stopped}" -eq 0 ]]; then
    echo "${service_name}未运行（端口 ${port}）。"
  fi
}

stop_service "后端服务" "${DESIGN_AI_BACKEND_PORT}" "uvicorn app.main:app"
stop_service "前端服务" "${DESIGN_AI_FRONTEND_PORT}" "vite"
