#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OPC_VAULT_ROOT="${1:-${OPC_VAULT_ROOT:-$HOME/Documents/Obsidian Vault}}"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 Docker。请先安装并启动 Docker Desktop for Mac。"
  echo "下载地址：https://www.docker.com/products/docker-desktop/"
  exit 1
fi

mkdir -p \
  "$OPC_VAULT_ROOT/wiki/视频/06产品适配后的脚本/omni" \
  "$OPC_VAULT_ROOT/wiki/视频/06产品适配后的脚本/grok" \
  "$OPC_VAULT_ROOT/wiki/产品/产品底图" \
  "$OPC_VAULT_ROOT/wiki/视频/10omni视频片段" \
  "$OPC_VAULT_ROOT/wiki/视频/10grok视频片段"

if [ ! -f .env ]; then
  cp .env.example .env
fi

tmp_env="$(mktemp)"
awk -v vault_root="$OPC_VAULT_ROOT" '
  BEGIN { written = 0 }
  /^OPC_VAULT_ROOT=/ {
    print "OPC_VAULT_ROOT=\"" vault_root "\""
    written = 1
    next
  }
  { print }
  END {
    if (!written) {
      print "OPC_VAULT_ROOT=\"" vault_root "\""
    }
  }
' .env > "$tmp_env"
mv "$tmp_env" .env

echo "Vault 根目录：$OPC_VAULT_ROOT"
echo "如果还没有填写 API Key，请打开 .env 或网页 API 设置页补充。"
docker compose up -d --build

echo "安装完成："
echo "  http://127.0.0.1:9995"
