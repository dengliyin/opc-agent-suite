#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p dist
timestamp="$(date +%Y%m%d-%H%M%S)"
package_name="omni-segment-agent-mac-${timestamp}.zip"
package_path="dist/${package_name}"

rm -f "$package_path"

zip -r "$package_path" \
  Dockerfile \
  docker-compose.yml \
  requirements.txt \
  README.md \
  INSTALL_OTHER_MAC.md \
  CODEX_INSTALL_PROMPT.md \
  .env.example \
  agent \
  static \
  scripts \
  tests \
  -x "*/__pycache__/*" \
  -x "*/.pytest_cache/*" \
  -x "*.pyc" \
  -x "*.pyo" \
  -x "*.DS_Store" \
  -x "dist/*" \
  -x "logs/*" \
  -x ".env" \
  -x ".venv/*"

echo "$ROOT_DIR/$package_path"

