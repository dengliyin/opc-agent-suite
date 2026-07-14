#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8888/"

if [ ! -f "$ROOT_DIR/.env" ] || [ ! -x "$ROOT_DIR/OPC-Console/.venv/bin/python" ]; then
  echo "首次启动需要初始化 OPC 运行环境，请稍候……"
  "$ROOT_DIR/scripts/bootstrap_macos.sh"
fi

"$ROOT_DIR/scripts/start_console.sh"
open "$URL"

echo "OPC 集合控制台已打开：$URL"
