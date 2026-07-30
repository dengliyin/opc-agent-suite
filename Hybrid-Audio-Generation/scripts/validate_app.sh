#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
.venv/bin/python -m compileall -q audio_agent
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
echo "配音智能体校验通过"
