#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  STORAGE_ROOT="$(dirname "$ROOT_DIR")"
  EXAMPLE_ENV="$ROOT_DIR/.env.docker.example"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      OPC_VAULT_ROOT=*) printf 'OPC_VAULT_ROOT="%s/Obsidian Vault"\n' "$STORAGE_ROOT" ;;
      OPC_DOCKER_DATA_ROOT=*) printf 'OPC_DOCKER_DATA_ROOT="%s/OPC-Data/docker"\n' "$STORAGE_ROOT" ;;
      VIDEO_ASSEMBLY_WORK_ROOT=*) printf 'VIDEO_ASSEMBLY_WORK_ROOT="%s/OPC-Data/Video-Assembly-hd"\n' "$STORAGE_ROOT" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < "$EXAMPLE_ENV" > "$ENV_FILE"
  printf '已按代码仓库所在盘自动创建配置：%s\n' "$ENV_FILE"
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

ensure_root_directory() {
  variable="$1"
  value="$2"
  if [ -z "$value" ]; then
    printf '%s 未配置。\n' "$variable" >&2
    exit 1
  fi
  if [ -e "$value" ] && [ ! -d "$value" ]; then
    printf '%s 不是目录：%s\n' "$variable" "$value" >&2
    exit 1
  fi
  if [ ! -d "$value" ]; then
    parent="$(dirname "$value")"
    if [ ! -d "$parent" ] || [ ! -w "$parent" ]; then
      printf '%s 的上一级目录或外置盘必须已经存在且可写：%s\n' "$variable" "$parent" >&2
      exit 1
    fi
    mkdir "$value"
  fi
}

for variable in OPC_VAULT_ROOT OPC_DOCKER_DATA_ROOT VIDEO_ASSEMBLY_WORK_ROOT; do
  value="${!variable:-}"
  ensure_root_directory "$variable" "$value"
  if [ ! -w "$value" ]; then
    printf '%s 必须指向已挂载且可写的目录：%s\n' "$variable" "$value" >&2
    exit 1
  fi
done

"$ROOT_DIR/scripts/create_storage_layout.sh" "$OPC_VAULT_ROOT"

mkdir -p \
  "$OPC_DOCKER_DATA_ROOT/config" \
  "$OPC_DOCKER_DATA_ROOT/finished-video-data" \
  "$OPC_DOCKER_DATA_ROOT/video-assembly-data" \
  "$OPC_DOCKER_DATA_ROOT/auto-publish-data"

docker compose --project-directory "$ROOT_DIR" config --quiet
docker compose --project-directory "$ROOT_DIR" build console
docker compose --project-directory "$ROOT_DIR" run --rm --no-deps \
  -v "$ROOT_DIR:/legacy:ro" \
  console python /workspace/scripts/migrate_legacy_ai_config.py \
  --repo-root /legacy --config-dir /config
docker compose --project-directory "$ROOT_DIR" up -d --build --wait --wait-timeout 300
"$ROOT_DIR/scripts/docker_health.sh"
