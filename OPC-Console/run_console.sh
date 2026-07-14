#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  exec env KESAI_APP_PORT="${KESAI_APP_PORT:-8888}" .venv/bin/python kesai_app.py
fi

exec env KESAI_APP_PORT="${KESAI_APP_PORT:-8888}" python3 kesai_app.py
