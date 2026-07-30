#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"
PYTHON_BIN="$ROOT_DIR/OPC-Console/.venv/bin/python"

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

exec env KESAI_APP_NO_OPEN=1 PYTHONUNBUFFERED=1 \
  "$PYTHON_BIN" "$ROOT_DIR/scripts/run_console_foreground.py"
