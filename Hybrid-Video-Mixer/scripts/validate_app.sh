#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
(
  cd "$ROOT_DIR"
  .venv/bin/python -m unittest discover -s tests -v
  .venv/bin/python -m py_compile app/mixer.py app/server.py
)
