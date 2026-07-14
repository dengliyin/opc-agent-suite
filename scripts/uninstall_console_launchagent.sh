#!/usr/bin/env bash
set -euo pipefail

LABEL="com.kesai.opc-console"
DOMAIN="gui/$(id -u)"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"
echo "OPC Console LaunchAgent removed."
