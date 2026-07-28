#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT_DIR/../.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/../.env"
  set +a
fi

exec "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/app/server.py" --host 127.0.0.1 --port 10000
