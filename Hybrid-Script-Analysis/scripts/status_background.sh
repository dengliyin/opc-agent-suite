#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/web_app.pid"
APP_URL="http://127.0.0.1:10002"
SESSION_NAME="Hybrid-Script-Analysis-app"

if /usr/bin/python3 - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:10002/health", timeout=3) as response:
    data = json.load(response)
if not str(data.get("skill_root", "")).endswith("Hybrid-Script-Analysis"):
    raise SystemExit(1)
PY
then
  echo "运行中: $APP_URL"
  lsof -nP -iTCP:10002 -sTCP:LISTEN || true
  if [[ -f "$PID_FILE" ]]; then
    echo "PID 文件: $(cat "$PID_FILE")"
  fi
  if command -v screen >/dev/null 2>&1; then
    screen -ls | grep "$SESSION_NAME" || true
  fi
else
  echo "未运行: $APP_URL"
  if command -v screen >/dev/null 2>&1; then
    screen -ls | grep "$SESSION_NAME" || true
  fi
  exit 1
fi
