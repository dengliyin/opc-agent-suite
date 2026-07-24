#!/usr/bin/env bash
set -euo pipefail

LABEL="local.Hybrid-Script-Analysis"
launchctl remove "$LABEL" >/dev/null 2>&1 || true
echo "已停止 $LABEL"
