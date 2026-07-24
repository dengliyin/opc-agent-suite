#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
APP_URL="http://127.0.0.1:10002"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${BOLD}Video Teardown Agent${RESET}\n"

mkdir -p "$PROJECT_DIR/logs"

if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$PROJECT_DIR" 2>/dev/null || true
fi

ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:10002/api/status", timeout=3) as response:
    data = json.load(response)
if not str(data.get("skill_root", "")).endswith("Hybrid-Script-Analysis"):
    raise SystemExit(1)
PY
}

if ready; then
  echo -e "${GREEN}Web 服务已在运行：$APP_URL${RESET}"
  open "$APP_URL" >/dev/null 2>&1 || true
  exit 0
fi

if lsof -nP -iTCP:10002 -sTCP:LISTEN >/dev/null 2>&1; then
  echo -e "${RED}端口 10002 已被其他程序占用：${RESET}"
  lsof -nP -iTCP:10002 -sTCP:LISTEN || true
  echo "请先关闭占用端口的程序后重试。"
  read -r -p "按回车键退出..."
  exit 1
fi

echo -e "${GREEN}启动后台 Web 服务：$APP_URL${RESET}"
"$PROJECT_DIR/scripts/start_background.sh"
echo ""
echo "服务已在后台运行。可以关闭此终端窗口，网页不会因此停止。"
sleep 2
