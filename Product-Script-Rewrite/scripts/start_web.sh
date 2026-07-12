#!/usr/bin/env bash
set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-9997}"
LOG_DIR="${AGENT_ROOT}/logs"
PID_FILE="${LOG_DIR}/Product-Script-Rewrite-${PORT}.pid"
OUT_LOG="${LOG_DIR}/Product-Script-Rewrite-${PORT}.out.log"
ERR_LOG="${LOG_DIR}/Product-Script-Rewrite-${PORT}.err.log"
PYTHON_BIN="${PYTHON_BIN:-${AGENT_ROOT}/.venv/bin/python}"
SCREEN_NAME="Product-Script-Rewrite-${PORT}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

cd "$AGENT_ROOT"
if PIDS="$(lsof -ti "tcp:${PORT}" 2>/dev/null)" && [ -n "$PIDS" ]; then
  kill $PIDS
  sleep 0.3
fi

mkdir -p "$LOG_DIR"
if [ "${PRODUCT_SCRIPT_REWRITE_FOREGROUND:-}" = "1" ]; then
  exec "$PYTHON_BIN" -m product_script_rewrite.web --port "$PORT"
fi

if command -v screen >/dev/null 2>&1; then
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  screen -dmS "$SCREEN_NAME" bash -lc "cd '$AGENT_ROOT' && exec '$PYTHON_BIN' -m product_script_rewrite.web --port '$PORT' >>'$OUT_LOG' 2>>'$ERR_LOG'"
else
  nohup "$PYTHON_BIN" -m product_script_rewrite.web --port "$PORT" >"$OUT_LOG" 2>"$ERR_LOG" &
fi

sleep 1.2
PID="$(lsof -ti "tcp:${PORT}" | head -n 1 || true)"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "产品脚本改写智能体启动失败，错误日志：$ERR_LOG" >&2
  tail -n 80 "$ERR_LOG" >&2 || true
  exit 1
fi

echo "$PID" > "$PID_FILE"
echo "产品脚本改写智能体 Web 界面: http://127.0.0.1:${PORT}"
echo "PID: ${PID}"
echo "日志: ${OUT_LOG}"
