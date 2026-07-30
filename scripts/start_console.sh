#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"
PYTHON_BIN="$ROOT_DIR/OPC-Console/.venv/bin/python"
LOG_DIR="$ROOT_DIR/.runtime/logs"
PID_FILE="$ROOT_DIR/.runtime/console.pid"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

"$ROOT_DIR/scripts/install_agent_launchagents.sh"

HOST="${KESAI_APP_HOST:-127.0.0.1}"
PORT="${KESAI_APP_PORT:-8888}"
URL="http://${HOST}:${PORT}/"

if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
  EXISTING_PID="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  EXISTING_COMMAND="$(ps -p "$EXISTING_PID" -o command= 2>/dev/null || true)"
  if [[ "$EXISTING_COMMAND" == *"$ROOT_DIR"* ]]; then
    echo "Console is already reachable: $URL"
    exit 0
  fi
  echo "Port $PORT is served by another installation and was left untouched." >&2
  echo "Use a different KESAI_APP_PORT for this copy, or stop the other installation first." >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is occupied by another process." >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/com.kesai.opc-console.plist"
if command -v launchctl >/dev/null 2>&1 && [ -f "$LAUNCH_AGENT_PLIST" ]; then
  exec "$ROOT_DIR/scripts/install_console_launchagent.sh"
fi

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/console-${PORT}.log"
SESSION_NAME="opc-agent-suite-${PORT}"

if command -v screen >/dev/null 2>&1; then
  screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
  screen -dmS "$SESSION_NAME" bash -lc "exec env KESAI_APP_NO_OPEN=1 PYTHONUNBUFFERED=1 '$PYTHON_BIN' '$ROOT_DIR/scripts/run_console_foreground.py' >>'$LOG_FILE' 2>&1"
else
  nohup env KESAI_APP_NO_OPEN=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" "$ROOT_DIR/scripts/run_console_foreground.py" >"$LOG_FILE" 2>&1 </dev/null &
fi

for _ in {1..30}; do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    PID="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [ -n "$PID" ]; then
      echo "$PID" > "$PID_FILE"
    fi
    echo "Console started: $URL"
    echo "PID: ${PID:-unknown}"
    echo "Log: $LOG_FILE"
    exit 0
  fi
  sleep 0.5
done

echo "Console failed to start. Log: $LOG_FILE" >&2
tail -n 80 "$LOG_FILE" >&2 || true
exit 1
