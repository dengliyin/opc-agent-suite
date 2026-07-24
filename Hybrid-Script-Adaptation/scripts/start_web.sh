#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${HYBRID_SCRIPT_ADAPTATION_APP_ROOT:-${SKILL_ROOT}/software/Hybrid-Script-Adaptation-app}"
PORT="${1:-9999}"
LOG_DIR="${SKILL_ROOT}/logs"
PID_FILE="${LOG_DIR}/Hybrid-Script-Adaptation-web-${PORT}.pid"
OUT_LOG="${LOG_DIR}/Hybrid-Script-Adaptation-web-${PORT}.out.log"
ERR_LOG="${LOG_DIR}/Hybrid-Script-Adaptation-web-${PORT}.err.log"
LABEL="com.kesai.Hybrid-Script-Adaptation.${PORT}"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
GUI_DOMAIN="gui/$(id -u)"
PYTHON_BIN="${PYTHON_BIN:-${SKILL_ROOT}/.venv/bin/python}"
SCREEN_NAME="Hybrid-Script-Adaptation-${PORT}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

cd "$APP_ROOT"
if PIDS="$(lsof -ti "tcp:${PORT}")" && [ -n "$PIDS" ]; then
  kill $PIDS
  sleep 0.3
fi

mkdir -p "$LOG_DIR"

if [ "${HYBRID_SCRIPT_ADAPTATION_FOREGROUND:-}" = "1" ]; then
  exec "$PYTHON_BIN" -m opc_engine.features.script_adaptation.script_adaptation_agent_web --port "$PORT"
fi

if command -v launchctl >/dev/null 2>&1; then
  launchctl bootout "${GUI_DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
  if [ -f "$PLIST" ]; then
    rm -f "$PLIST"
  fi
fi

if command -v screen >/dev/null 2>&1; then
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  screen -dmS "$SCREEN_NAME" bash -lc "cd '$APP_ROOT' && exec '$PYTHON_BIN' -m opc_engine.features.script_adaptation.script_adaptation_agent_web --port '$PORT' >>'$OUT_LOG' 2>>'$ERR_LOG'"
else
  nohup "$PYTHON_BIN" -m opc_engine.features.script_adaptation.script_adaptation_agent_web --port "$PORT" >"$OUT_LOG" 2>"$ERR_LOG" &
fi

sleep 1.2
PID="$(lsof -ti "tcp:${PORT}" | head -n 1 || true)"
if [ -n "$PID" ]; then
  echo "$PID" > "$PID_FILE"
fi

if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "钩子与 CTA 脚本适配智能体启动失败，错误日志：$ERR_LOG" >&2
  tail -n 80 "$ERR_LOG" >&2 || true
  exit 1
fi

echo "钩子与 CTA 脚本适配智能体 Web 界面: http://127.0.0.1:${PORT}"
echo "PID: ${PID}"
echo "日志: ${OUT_LOG}"
