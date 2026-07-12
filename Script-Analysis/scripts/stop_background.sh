#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/web_app.pid"
SESSION_NAME="Script-Analysis-app"

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ps -p "$pid" -o command= 2>/dev/null | grep -q "scripts/web_app.py"; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
}

if [[ -f "$PID_FILE" ]]; then
  stop_pid "$(cat "$PID_FILE")"
  rm -f "$PID_FILE"
fi

if command -v screen >/dev/null 2>&1; then
  screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
fi

for pid in $(lsof -tiTCP:9992 -sTCP:LISTEN 2>/dev/null || true); do
  stop_pid "$pid"
done

echo "Web 服务已停止"
