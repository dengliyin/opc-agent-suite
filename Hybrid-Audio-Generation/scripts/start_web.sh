#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
exec .venv/bin/python -m audio_agent.web --host 127.0.0.1 --port "${PORT:-10004}"
