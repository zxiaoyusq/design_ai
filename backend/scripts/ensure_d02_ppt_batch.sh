#!/usr/bin/env bash
# 当前批次进程意外退出后才接管；正常完成或额度暂停不重新提交。
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BATCH_FILE="${PROJECT_DIR}/data/userreseach_data/liked_images_d02_results/batches/ppt_enjoy_20260928_gemini38/manifest.json"
ACTIVE_PID="${1:?需要当前批次进程 PID}"

while kill -0 "${ACTIVE_PID}" 2>/dev/null; do
  PROCESS_STATE="$(ps -p "${ACTIVE_PID}" -o stat= 2>/dev/null || true)"
  [[ "${PROCESS_STATE}" == Z* ]] && break
  sleep 20
done

STATUS="$(/root/miniconda3/envs/314/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "${BATCH_FILE}")"
if [[ "${STATUS}" == "running" ]]; then
  cd "${PROJECT_DIR}"
  exec /root/miniconda3/envs/314/bin/python -u backend/scripts/run_d02_ppt_enjoy_batch.py run
fi
