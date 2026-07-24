#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m opc_engine.features.script_generation.script_generation_agent_web \
    --port "${KESAI_APP_PORT:-10003}"
fi

exec python3 -m opc_engine.features.script_generation.script_generation_agent_web \
  --port "${KESAI_APP_PORT:-10003}"
