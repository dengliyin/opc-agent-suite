#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_URL="http://127.0.0.1:9992"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:9992/api/status", timeout=3) as response:
    data = json.load(response)
if not str(data.get("skill_root", "")).endswith("Script-Analysis"):
    raise SystemExit(1)
PY
}

if ready; then
  echo "Web 服务已在运行: $APP_URL"
  open "$APP_URL" >/dev/null 2>&1 || true
  exit 0
fi

if ! command -v osascript >/dev/null 2>&1; then
  echo "请手动打开终端运行:"
  echo "cd '$PROJECT_DIR' && ./start.command"
  exit 1
fi

osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "cd '$PROJECT_DIR' && ./start.command"
end tell
APPLESCRIPT

for _ in $(seq 1 20); do
  if ready; then
    echo "Web 服务已启动: $APP_URL"
    exit 0
  fi
  sleep 0.5
done

echo "已打开终端启动窗口，服务可能仍在启动中: $APP_URL"
