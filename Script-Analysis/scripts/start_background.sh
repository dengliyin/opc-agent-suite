#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_URL="http://127.0.0.1:9992"
PID_FILE="$PROJECT_DIR/logs/web_app.pid"
OUT_LOG="$PROJECT_DIR/logs/web_app.out.log"
ERR_LOG="$PROJECT_DIR/logs/web_app.err.log"
SESSION_NAME="Script-Analysis-app"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$PROJECT_DIR/logs"

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

listener_pid() {
  lsof -tiTCP:9992 -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$PROJECT_DIR" 2>/dev/null || true
fi

if ready; then
  pid="$(listener_pid)"
  if [[ -n "$pid" ]]; then
    echo "$pid" > "$PID_FILE"
  fi
  echo "Web 服务已在运行: $APP_URL"
  open "$APP_URL" >/dev/null 2>&1 || true
  exit 0
fi

if pid="$(listener_pid)" && [[ -n "$pid" ]]; then
  echo "端口 9992 已被其他程序占用，PID: $pid"
  lsof -nP -iTCP:9992 -sTCP:LISTEN || true
  exit 1
fi

cd "$PROJECT_DIR"
if command -v screen >/dev/null 2>&1; then
  screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
  screen -dmS "$SESSION_NAME" /bin/bash -lc "
cd '$PROJECT_DIR'
while true; do
  echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] start web_app.py\" >> '$OUT_LOG'
  '$PYTHON_BIN' '$PROJECT_DIR/scripts/web_app.py' --host 127.0.0.1 --port 9992 >> '$OUT_LOG' 2>> '$ERR_LOG'
  code=\$?
  echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] web_app.py exited with code \$code; restart in 2s\" >> '$ERR_LOG'
  sleep 2
done
"
else
  echo "系统缺少 screen，无法创建稳定后台会话。"
  exit 1
fi

for _ in $(seq 1 30); do
  if ready; then
    pid="$(listener_pid)"
    if [[ -n "$pid" ]]; then
      echo "$pid" > "$PID_FILE"
    fi
    echo "Web 服务已启动: $APP_URL"
    echo "PID: $pid"
    echo "screen 会话: $SESSION_NAME"
    echo "日志: $OUT_LOG / $ERR_LOG"
    open "$APP_URL" >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 0.5
done

echo "Web 服务启动超时，查看日志:"
echo "$ERR_LOG"
exit 1
