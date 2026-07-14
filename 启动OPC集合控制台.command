#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8888/"

"$ROOT_DIR/scripts/start_console.sh"
open "$URL"

echo "OPC 集合控制台已打开：$URL"
