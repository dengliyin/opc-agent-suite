#!/usr/bin/env bash
set -euo pipefail

DOMAIN="gui/$(id -u)"
SERVICE_IDS=(collect analyze script adapt assemble finished rewrite compose hybrid_adapt)

for service_id in "${SERVICE_IDS[@]}"; do
  label="com.kesai.opc-agent.$service_id"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done

echo "Removed 9 Agent LaunchAgents."
