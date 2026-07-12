#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PORTS="$($ROOT_DIR/Script-Generation/.venv/bin/python - <<'PY'
import os
from urllib.parse import urlparse

urls = [
    f"http://{os.getenv('KESAI_APP_HOST', '127.0.0.1')}:{os.getenv('KESAI_APP_PORT', '8888')}/",
    os.getenv('OPC_HOT_VIDEO_AGENT_URL', 'http://127.0.0.1:9991/'),
    os.getenv('OPC_VIDEO_TEARDOWN_AGENT_URL', 'http://127.0.0.1:9992/'),
    os.getenv('OPC_SCRIPT_PRODUCTION_AGENT_URL', 'http://127.0.0.1:9993/'),
    os.getenv('OPC_SCRIPT_ADAPTATION_AGENT_URL', 'http://127.0.0.1:9994/'),
    os.getenv('OPC_VIDEO_OUTPUT_AGENT_URL', 'http://127.0.0.1:9995/'),
    os.getenv('OPC_FINISHED_VIDEO_MANAGER_URL', 'http://127.0.0.1:9996/'),
    os.getenv('OPC_PRODUCT_SCRIPT_REWRITE_URL', 'http://127.0.0.1:9997/'),
    os.getenv('OPC_VIDEO_ASSEMBLY_AGENT_URL', 'http://127.0.0.1:9998/'),
]
print(' '.join(str(urlparse(url).port) for url in urls if urlparse(url).port))
PY
)"

for port in $PORTS; do
  for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true); do
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"$ROOT_DIR"* ]]; then
      echo "Stopping isolated suite process $pid on port $port"
      kill "$pid" 2>/dev/null || true
    else
      echo "Leaving unrelated process $pid on port $port untouched"
    fi
  done
done

