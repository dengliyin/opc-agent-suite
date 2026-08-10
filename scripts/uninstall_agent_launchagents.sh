#!/usr/bin/env bash
set -euo pipefail

DOMAIN="gui/$(id -u)"
SERVICE_IDS=(collect analyze script adapt assemble finished rewrite compose hybrid_adapt hybrid_mix hybrid_collect hybrid_analyze hybrid_script hybrid_voice auto_publish)

for service_id in "${SERVICE_IDS[@]}"; do
  label="com.kesai.opc-agent.$service_id"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done

echo "Removed 15 Agent LaunchAgents."
