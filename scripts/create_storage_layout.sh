#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"
TEMPLATE_ROOT="${ROOT_DIR}/storage-template"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

VAULT_ROOT="${1:-${OPC_VAULT_ROOT:?OPC_VAULT_ROOT must be configured}}"

if [ ! -d "$TEMPLATE_ROOT" ]; then
  echo "Storage template not found: $TEMPLATE_ROOT" >&2
  exit 1
fi

if [ -e "$VAULT_ROOT" ] && [ ! -d "$VAULT_ROOT" ]; then
  echo "Vault root is not a directory: $VAULT_ROOT" >&2
  exit 1
fi

if [ ! -d "$VAULT_ROOT" ]; then
  vault_parent="$(dirname "$VAULT_ROOT")"
  if [ ! -d "$vault_parent" ] || [ ! -w "$vault_parent" ]; then
    echo "Vault parent must already exist and be writable: $vault_parent" >&2
    exit 1
  fi
  mkdir "$VAULT_ROOT"
fi

if [ ! -w "$VAULT_ROOT" ]; then
  echo "Vault root is not writable: $VAULT_ROOT" >&2
  exit 1
fi

while IFS= read -r -d '' template_dir; do
  if [ "$template_dir" = "$TEMPLATE_ROOT" ]; then
    continue
  fi
  relative_path="${template_dir#"$TEMPLATE_ROOT"/}"
  mkdir -p "$VAULT_ROOT/$relative_path"
done < <(find "$TEMPLATE_ROOT" -type d -print0)

while IFS= read -r -d '' template_file; do
  relative_path="${template_file#"$TEMPLATE_ROOT"/}"
  target_file="$VAULT_ROOT/$relative_path"
  if [ ! -e "$target_file" ]; then
    cp "$template_file" "$target_file"
  fi
done < <(find "$TEMPLATE_ROOT" -type f ! -name '.gitkeep' -print0)

echo "Storage layout ready: $VAULT_ROOT"
