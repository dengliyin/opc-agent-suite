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

VAULT_ROOT="${1:-${OPC_VAULT_ROOT:-$HOME/Documents/Obsidian Vault}}"

if [ ! -d "$TEMPLATE_ROOT" ]; then
  echo "Storage template not found: $TEMPLATE_ROOT" >&2
  exit 1
fi

while IFS= read -r -d '' template_dir; do
  if [ "$template_dir" = "$TEMPLATE_ROOT" ]; then
    continue
  fi
  relative_path="${template_dir#"$TEMPLATE_ROOT"/}"
  mkdir -p "$VAULT_ROOT/$relative_path"
done < <(find "$TEMPLATE_ROOT" -type d -print0)

echo "Storage layout ready: $VAULT_ROOT"
