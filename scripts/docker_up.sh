#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  printf '缺少 %s，请复制 .env.docker.example 并填写真实路径。\n' "$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for variable in OPC_VAULT_ROOT OPC_DOCKER_DATA_ROOT VIDEO_ASSEMBLY_WORK_ROOT; do
  value="${!variable:-}"
  if [ -z "$value" ] || [ ! -d "$value" ] || [ ! -w "$value" ]; then
    printf '%s 必须指向已挂载且可写的目录：%s\n' "$variable" "$value" >&2
    exit 1
  fi
done

mkdir -p \
  "$OPC_DOCKER_DATA_ROOT/config" \
  "$OPC_DOCKER_DATA_ROOT/finished-video-data" \
  "$OPC_DOCKER_DATA_ROOT/video-assembly-data" \
  "$OPC_DOCKER_DATA_ROOT/auto-publish-data"

docker compose --project-directory "$ROOT_DIR" config --quiet
docker compose --project-directory "$ROOT_DIR" up -d --build --wait --wait-timeout 300
"$ROOT_DIR/scripts/docker_health.sh"
