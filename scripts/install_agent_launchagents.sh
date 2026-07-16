#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="gui/$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"
TEMPLATE_PATH="$ROOT_DIR/scripts/launchd/com.kesai.opc-agent.plist.template"
PYTHON_PATH="$ROOT_DIR/OPC-Console/.venv/bin/python"
LAUNCHER_PATH="$ROOT_DIR/scripts/run_agent_foreground.py"
LOG_DIR="$HOME/Library/Logs/OPC-Agent-Suite"
SERVICE_IDS=(collect analyze script adapt assemble finished rewrite compose)

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "Missing $ROOT_DIR/.env. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi
if [ ! -x "$PYTHON_PATH" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

sed_escape() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

python_escaped="$(sed_escape "$PYTHON_PATH")"
launcher_escaped="$(sed_escape "$LAUNCHER_PATH")"

for service_id in "${SERVICE_IDS[@]}"; do
  label="com.kesai.opc-agent.$service_id"
  plist_path="$PLIST_DIR/$label.plist"
  out_log_path="$LOG_DIR/$service_id.log"
  err_log_path="$LOG_DIR/$service_id.err.log"
  temp_path="$(mktemp)"
  sed \
    -e "s|__LABEL__|$(sed_escape "$label")|g" \
    -e "s|__PYTHON__|$python_escaped|g" \
    -e "s|__LAUNCHER__|$launcher_escaped|g" \
    -e "s|__SERVICE_ID__|$(sed_escape "$service_id")|g" \
    -e "s|__OUT_LOG__|$(sed_escape "$out_log_path")|g" \
    -e "s|__ERR_LOG__|$(sed_escape "$err_log_path")|g" \
    "$TEMPLATE_PATH" > "$temp_path"

  plutil -lint "$temp_path" >/dev/null
  if [ -f "$plist_path" ] && cmp -s "$temp_path" "$plist_path" && launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    rm -f "$temp_path"
    continue
  fi
  if launchctl print "$DOMAIN/$label" 2>/dev/null | grep -q 'state = running'; then
    echo "Keeping running Agent unchanged: $service_id" >&2
    rm -f "$temp_path"
    continue
  fi
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  mv "$temp_path" "$plist_path"
  chmod 600 "$plist_path"
  launchctl bootstrap "$DOMAIN" "$plist_path"
done

echo "Installed 8 on-demand Agent LaunchAgents."
