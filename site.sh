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
START_LOCK_FILE="${RUNTIME_DIR}/site.lock"
STOP_REQUEST_FILE="${RUNTIME_DIR}/site.stop"

fail() {
  echo "操作失败：$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：./site.sh <start|stop|restart|status>

  start   自动释放目标端口并启动固定域名站点（前台运行，Ctrl+C 停止）
  stop    仅停止本脚本启动的前后端进程
  restart 先停止再启动
  status  查看本脚本管理的服务状态

可选环境变量：
  DESIGN_AI_DOMAIN          默认 gamedevcenter.ahagamecenter.com
  DESIGN_AI_BACKEND_PORT    默认 8000，仅本机监听
  DESIGN_AI_FRONTEND_PORT   默认 80，对外监听

注意：启动会停止上述端口原有的监听进程、对应容器或系统服务，不会自动恢复它们。
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
  [[ "${command}" == *"${expected_command}"* ]] || return 1
  # 过期 PID 即使复用给同类命令，也不能据此停止另一个工程的服务。
  case "${pid_file}" in
    "${BACKEND_PID_FILE}") [[ "$(readlink -f "/proc/${pid}/cwd")" == "${BACKEND_DIR}" ]] ;;
    "${FRONTEND_PID_FILE}") [[ "$(readlink -f "/proc/${pid}/cwd")" == "${FRONTEND_DIR}" ]] ;;
  esac
}

remove_pid_file() {
  rm -f "$1"
}

private_group_running() {
  # 同时核对 PGID 与 SID，并忽略已退出的僵尸进程；父进程退出不代表监听子进程都已退出。
  ps -eo pgid=,sid=,stat= | awk -v owner="$1" \
    '$1 == owner && $2 == owner && $3 !~ /^Z/ { found = 1 } END { exit !found }'
}

stop_component() {
  local service_name="$1"
  local pid_file="$2"
  local expected_command="$3"
  local pid
  local child_pid
  local attempt
  local process_group
  local started_at

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

  started_at="$(ps -p "${pid}" -o lstart= 2>/dev/null || true)"
  process_group="$(ps -p "${pid}" -o pgid= 2>/dev/null || true)"
  process_group="${process_group//[[:space:]]/}"
  if [[ "${process_group}" == "${pid}" ]]; then
    # 新启动的服务使用独立会话；一起停止 pnpm、shell 和 Vite，避免留下孙进程监听端口。
    kill -TERM -- "-${pid}" 2>/dev/null || true
  else
    # 兼容旧脚本留下的非独立会话进程，不能向其共享进程组发信号。
    while IFS= read -r child_pid; do
      [[ -n "${child_pid}" ]] && kill -TERM "${child_pid}" 2>/dev/null || true
    done < <(pgrep -P "${pid}" 2>/dev/null || true)
    kill -TERM "${pid}" 2>/dev/null || true
  fi

  for ((attempt = 1; attempt <= 100; attempt++)); do
    if { [[ "${process_group}" == "${pid}" ]] && ! private_group_running "${pid}"; } \
      || { [[ "${process_group}" != "${pid}" ]] && ! is_expected_process "${pid_file}" "${expected_command}"; }; then
      remove_pid_file "${pid_file}"
      echo "已停止${service_name}（PID ${pid}）。"
      return
    fi
    sleep 0.1
  done

  # 独立会话的父进程可能先退出，仍需清理同一会话内拒绝退出的子进程。
  if [[ "${process_group}" == "${pid}" ]] && private_group_running "${pid}"; then
    kill -KILL -- "-${pid}" 2>/dev/null || true
  elif is_expected_process "${pid_file}" "${expected_command}" \
    && [[ "$(ps -p "${pid}" -o lstart= 2>/dev/null || true)" == "${started_at}" ]]; then
    kill -KILL "${pid}" 2>/dev/null || true
  fi
  for ((attempt = 1; attempt <= 20; attempt++)); do
    if ! private_group_running "${pid}" && ! is_expected_process "${pid_file}" "${expected_command}"; then
      remove_pid_file "${pid_file}"
      echo "已强制停止${service_name}（PID ${pid}）。"
      return
    fi
    sleep 0.1
  done
  fail "${service_name}仍未退出（PID ${pid}），已保留状态便于排查"
}

cleanup() {
  local exit_code="$?"

  trap - EXIT INT TERM HUP
  # 只清理本次成功创建且仍对应同一 PID 的服务，启动预检失败不能误停旧站点。
  if [[ -n "${FRONTEND_PID}" && "$(read_pid "${FRONTEND_PID_FILE}" || true)" == "${FRONTEND_PID}" ]]; then
    stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm" || true
  fi
  if [[ -n "${BACKEND_PID}" && "$(read_pid "${BACKEND_PID_FILE}" || true)" == "${BACKEND_PID}" ]]; then
    stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app" || true
  fi
  exit "${exit_code}"
}

validate_ports() {
  local port
  for port in "${DESIGN_AI_BACKEND_PORT}" "${DESIGN_AI_FRONTEND_PORT}"; do
    [[ "${port}" =~ ^[1-9][0-9]{0,4}$ ]] && (( port <= 65535 )) \
      || fail "端口必须是 1–65535 的十进制整数：${port}"
  done
  [[ "${DESIGN_AI_BACKEND_PORT}" != "${DESIGN_AI_FRONTEND_PORT}" ]] \
    || fail "前后端不能使用相同端口"
}

activate_runtime() {
  local conda_command
  local conda_base
  local conda_profile

  [[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "请先在 frontend 目录执行 pnpm install"
  [[ -f "${BACKEND_DIR}/.env" ]] || fail "缺少 backend/.env"
  command -v lsof >/dev/null 2>&1 || fail "缺少 lsof"
  command -v flock >/dev/null 2>&1 || fail "缺少 flock"
  command -v setsid >/dev/null 2>&1 || fail "缺少 setsid"
  command -v curl >/dev/null 2>&1 || fail "缺少 curl"
  [[ -f "${BACKEND_DIR}/scripts/release_site_ports.py" ]] || fail "缺少端口接管脚本"
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
  pnpm --version >/dev/null 2>&1 || fail "314 环境中的 pnpm 无法运行"
  (
    cd "${BACKEND_DIR}"
    python -c "import app.main, fastapi, uvicorn, deepagents"
  ) 9>&- >/dev/null 2>&1 || fail "314 环境缺少后端依赖，请先安装 backend/requirements.txt"
}

wait_for_backend() {
  local attempt
  local backend_url="http://${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}/openapi.json"

  for ((attempt = 1; attempt <= 100; attempt++)); do
    [[ ! -f "${STOP_REQUEST_FILE}" ]] || exit 0
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
      tail -n 30 "${BACKEND_LOG_FILE}" >&2 || true
      fail "后端服务启动失败"
    fi
    if curl --noproxy '*' --fail --silent --show-error --max-time 1 "${backend_url}" >/dev/null 2>&1; then
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
    [[ ! -f "${STOP_REQUEST_FILE}" ]] || exit 0
    if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
      tail -n 30 "${FRONTEND_LOG_FILE}" >&2 || true
      fail "前端服务启动失败"
    fi
    if curl --noproxy '*' --fail --silent --show-error --max-time 1 \
      -H "Host: ${DESIGN_AI_DOMAIN}" "${frontend_url}" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  fail "前端服务未在 10 秒内就绪：${frontend_url}"
}

start() {
  mkdir -p "${LOG_DIR}"
  validate_ports
  command -v flock >/dev/null 2>&1 || fail "缺少 flock"
  exec 9>"${START_LOCK_FILE}"
  if ! flock -n 9; then
    echo "站点已在运行或启动中；无需重复启动。"
    status
    return
  fi
  remove_pid_file "${STOP_REQUEST_FILE}"
  # 先确认依赖可用，再接管端口，避免依赖缺失时先停掉仍可用的旧服务。
  activate_runtime
  trap cleanup EXIT
  trap 'exit 130' INT TERM HUP
  stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm"
  stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app"
  python "${BACKEND_DIR}/scripts/release_site_ports.py" \
    "${DESIGN_AI_BACKEND_PORT}" "${DESIGN_AI_FRONTEND_PORT}" 9>&- \
    || fail "无法接管目标端口，未启动新服务"

  (
    cd "${BACKEND_DIR}"
    exec setsid python -m uvicorn app.main:app \
      --host "${DESIGN_AI_BACKEND_HOST}" \
      --port "${DESIGN_AI_BACKEND_PORT}"
  ) 9>&- >"${BACKEND_LOG_FILE}" 2>&1 &
  BACKEND_PID=$!
  printf '%s\n' "${BACKEND_PID}" >"${BACKEND_PID_FILE}"
  wait_for_backend

  (
    cd "${FRONTEND_DIR}"
    export VITE_BACKEND_URL="http://${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}"
    exec setsid pnpm dev \
      --host "${DESIGN_AI_FRONTEND_HOST}" \
      --port "${DESIGN_AI_FRONTEND_PORT}" \
      --strictPort
  ) 9>&- >"${FRONTEND_LOG_FILE}" 2>&1 &
  FRONTEND_PID=$!
  printf '%s\n' "${FRONTEND_PID}" >"${FRONTEND_PID_FILE}"
  wait_for_frontend

  echo "站点已启动：http://${DESIGN_AI_DOMAIN}/"
  echo "后端仅监听 ${DESIGN_AI_BACKEND_HOST}:${DESIGN_AI_BACKEND_PORT}；日志目录：${LOG_DIR}"
  echo "按 Ctrl+C 或执行 ./site.sh stop 可停止站点。"

  while true; do
    if [[ -f "${STOP_REQUEST_FILE}" ]]; then
      echo "站点已停止。"
      return
    fi
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

stop() {
  mkdir -p "${RUNTIME_DIR}"
  # 正常 stop/restart 不是服务故障，通知原前台守护按成功状态退出。
  : >"${STOP_REQUEST_FILE}"
  stop_component "前端服务" "${FRONTEND_PID_FILE}" "pnpm"
  stop_component "后端服务" "${BACKEND_PID_FILE}" "uvicorn app.main:app"
  # 等待旧的前台守护退出并释放锁，restart 才不会把尚在清理的旧实例当作新实例。
  if [[ -f "${START_LOCK_FILE}" ]]; then
    flock -w 15 "${START_LOCK_FILE}" true || fail "等待旧站点退出超时"
  fi
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
    start
    ;;
  stop)
    stop
    ;;
  restart)
    stop
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
