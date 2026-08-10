#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m auto_publish_pipeline.web --host 127.0.0.1 --port "${AUTO_PUBLISH_PIPELINE_PORT:-10005}"
