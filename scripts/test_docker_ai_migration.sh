#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

LEGACY_ROOT="$TEMP_DIR/legacy"
CONFIG_ROOT="$TEMP_DIR/config"
mkdir -p "$LEGACY_ROOT/Script-Analysis/config" "$CONFIG_ROOT"
printf '%s\n' '{"base_url":"https://upgrade.example","model":"upgrade-model"}' > "$LEGACY_ROOT/Script-Analysis/config/settings.json"
printf '%s\n' '{"api_key":"upgrade-test-secret"}' > "$LEGACY_ROOT/Script-Analysis/config/settings.local.json"

docker compose --project-directory "$ROOT_DIR" build console >/dev/null
docker compose --project-directory "$ROOT_DIR" run --rm --no-deps \
  -v "$LEGACY_ROOT:/legacy:ro" \
  -v "$CONFIG_ROOT:/migration-config" \
  console python /workspace/scripts/migrate_legacy_ai_config.py \
  --repo-root /legacy --config-dir /migration-config >/dev/null

docker compose --project-directory "$ROOT_DIR" run --rm --no-deps \
  -v "$CONFIG_ROOT:/migration-config:ro" \
  console python -c "from pathlib import Path; p=Path('/migration-config/.env'); text=p.read_text(); assert 'OPC_VIDEO_ANALYSIS_API_BASE_URL=\"https://upgrade.example\"' in text; assert 'OPC_VIDEO_ANALYSIS_MODEL=\"upgrade-model\"' in text; assert 'OPC_VIDEO_ANALYSIS_API_KEY=\"upgrade-test-secret\"' in text"

printf 'Docker 旧配置升级测试通过。\n'
