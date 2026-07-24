#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

export KESAI_APP_PORT="${KESAI_APP_PORT:-10003}"
export KESAI_APP_NO_OPEN="${KESAI_APP_NO_OPEN:-1}"
export KESAI_MAX_CONCURRENT_TASK_GROUPS="${KESAI_MAX_CONCURRENT_TASK_GROUPS:-3}"
export KESAI_MAX_API_CONCURRENT_REQUESTS="${KESAI_MAX_API_CONCURRENT_REQUESTS:-10}"

LOG_DIR="$APP_DIR/runtime/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/kesai_web_service_$(date +%Y%m%d).log"

echo "============================================================"
echo "OPC 脚本产出独立 Agent"
echo "目录: $APP_DIR"
echo "地址: http://127.0.0.1:$KESAI_APP_PORT/"
echo "日志: $LOG_FILE"
echo "任务组并发: $KESAI_MAX_CONCURRENT_TASK_GROUPS"
echo "API 并发: $KESAI_MAX_API_CONCURRENT_REQUESTS"
echo "启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -tiTCP:"$KESAI_APP_PORT" -sTCP:LISTEN || true)"
  for pid in $PIDS; do
    if ps -p "$pid" -o command= | grep -q "script_generation_agent_web"; then
      echo "发现旧 Web 服务进程 PID=$pid，正在停止..."
      kill "$pid" || true
    else
      echo "端口 $KESAI_APP_PORT 被其他进程 PID=$pid 占用，请先处理该进程。"
      ps -p "$pid" -o pid,ppid,command || true
      exit 1
    fi
  done
  if [ -n "$PIDS" ]; then
    sleep 1
  fi
fi

PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

echo "使用 Python: $PYTHON_BIN"
echo "服务运行中。要停止服务，请在这个 Terminal 窗口按 Control-C。"
echo

"$PYTHON_BIN" -u -m opc_engine.features.script_generation.script_generation_agent_web --port "$KESAI_APP_PORT" 2>&1 | tee -a "$LOG_FILE"
