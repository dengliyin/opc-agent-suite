#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_URL="http://127.0.0.1:9992"
PID_FILE="$PROJECT_DIR/logs/web_app.pid"
OUT_LOG="$PROJECT_DIR/logs/web_app.out.log"
ERR_LOG="$PROJECT_DIR/logs/web_app.err.log"
SESSION_NAME="Script-Analysis-app"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"
LABEL="com.kesai.opc-agent.analyze"
DOMAIN="gui/$(id -u)"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

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

# Remove the legacy screen watchdog so launchd is the only process manager.
legacy_session=""
if command -v screen >/dev/null 2>&1; then
  legacy_session="$(screen -list 2>/dev/null | awk -v name="$SESSION_NAME" '$1 ~ ("[.]" name "$") { print $1; exit }')"
fi
if [[ -n "$legacy_session" ]]; then
  legacy_listener="$(listener_pid)"
  legacy_pgid=""
  if [[ -n "$legacy_listener" ]]; then
    legacy_pgid="$(ps -o pgid= -p "$legacy_listener" 2>/dev/null | tr -d '[:space:]')"
  fi
  screen -S "$legacy_session" -X quit >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    [[ -z "$(listener_pid)" ]] && break
    sleep 0.2
  done
  if [[ -n "$legacy_listener" ]] && kill -0 "$legacy_listener" 2>/dev/null; then
    if [[ -n "$legacy_pgid" ]]; then
      kill -TERM -- "-$legacy_pgid" 2>/dev/null || true
    else
      kill -TERM "$legacy_listener" 2>/dev/null || true
    fi
  fi
fi

if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$PROJECT_DIR" 2>/dev/null || true
fi

if [[ ! -f "$PLIST_PATH" ]]; then
  echo "缺少 LaunchAgent：$PLIST_PATH" >&2
  echo "请先运行项目根目录 scripts/install_agent_launchagents.sh。" >&2
  exit 1
fi

if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
fi
launchctl kickstart -k "$DOMAIN/$LABEL"

for _ in $(seq 1 30); do
  if ready; then
    pid="$(listener_pid)"
    if [[ -n "$pid" ]]; then
      echo "$pid" > "$PID_FILE"
    fi
    echo "Web 服务已启动: $APP_URL"
    echo "PID: $pid"
    echo "LaunchAgent: $LABEL"
    echo "日志: $HOME/Library/Logs/OPC-Agent-Suite/analyze.log"
    open "$APP_URL" >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 0.5
done

echo "Web 服务启动超时，查看日志:"
echo "$ERR_LOG"
exit 1
