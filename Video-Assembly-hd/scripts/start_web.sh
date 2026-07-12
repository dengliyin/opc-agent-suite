#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${VIDEO_ASSEMBLY_PORT:-9998}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

exec "$PYTHON_BIN" "$ROOT_DIR/app/server.py" --host 127.0.0.1 --port "$PORT"
