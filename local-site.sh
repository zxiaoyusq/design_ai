#!/usr/bin/env bash

# 复用现有静态发布与本机API，管理仅供SSH端口转发访问的站点。
set -Eeuo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/deploy/visual-local-compose.yml"

case "${1:-start}" in
  start)
    [[ -f "${PROJECT_DIR}/frontend/dist/index.html" ]] || {
      echo "缺少 frontend/dist/index.html，请先准备前端构建产物。" >&2
      exit 1
    }
    docker compose -p design-ai-local -f "${COMPOSE_FILE}" up -d
    echo "本机站点：http://127.0.0.1:5174（通过SSH端口转发访问）"
    ;;
  stop)
    docker compose -p design-ai-local -f "${COMPOSE_FILE}" stop
    ;;
  restart)
    docker compose -p design-ai-local -f "${COMPOSE_FILE}" restart
    ;;
  status)
    docker compose -p design-ai-local -f "${COMPOSE_FILE}" ps
    ;;
  *)
    echo "用法：$0 [start|stop|restart|status]" >&2
    exit 2
    ;;
esac
