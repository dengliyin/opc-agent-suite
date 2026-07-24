#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="gui/$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"
TEMPLATE_PATH="$ROOT_DIR/scripts/launchd/com.kesai.opc-agent.plist.template"
LAUNCHER_PATH="$ROOT_DIR/scripts/run_agent_foreground.py"
LOG_DIR="$HOME/Library/Logs/OPC-Agent-Suite"
SERVICE_IDS=(collect analyze script adapt assemble finished rewrite compose hybrid_adapt hybrid_collect hybrid_analyze hybrid_script)

service_dir() {
  case "$1" in
    collect) echo "Video-Collection" ;;
    analyze) echo "Script-Analysis" ;;
    script) echo "Script-Generation" ;;
    adapt) echo "Script-Adaptation" ;;
    assemble) echo "Video-Generation" ;;
    finished) echo "Finished-Video-Manager" ;;
    rewrite) echo "Product-Script-Rewrite" ;;
    compose) echo "Video-Assembly-hd" ;;
    hybrid_adapt) echo "Hybrid-Script-Adaptation" ;;
    hybrid_collect) echo "Hybrid-Video-Collection" ;;
    hybrid_analyze) echo "Hybrid-Script-Analysis" ;;
    hybrid_script) echo "Hybrid-Script-Generation" ;;
    *) return 1 ;;
  esac
}

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "Missing $ROOT_DIR/.env. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi
if [ ! -x "$ROOT_DIR/OPC-Console/.venv/bin/python" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

sed_escape() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

launcher_escaped="$(sed_escape "$LAUNCHER_PATH")"

for service_id in "${SERVICE_IDS[@]}"; do
  agent_dir="$(service_dir "$service_id")"
  python_path="$ROOT_DIR/$agent_dir/.venv/bin/python"
  if [ ! -x "$python_path" ]; then
    echo "Missing Agent virtual environment: $agent_dir/.venv" >&2
    exit 1
  fi
  label="com.kesai.opc-agent.$service_id"
  plist_path="$PLIST_DIR/$label.plist"
  out_log_path="$LOG_DIR/$service_id.log"
  err_log_path="$LOG_DIR/$service_id.err.log"
  temp_path="$(mktemp)"
  sed \
    -e "s|__LABEL__|$(sed_escape "$label")|g" \
    -e "s|__PYTHON__|$(sed_escape "$python_path")|g" \
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
    mv "$temp_path" "$plist_path"
    chmod 600 "$plist_path"
    echo "Updated plist without restarting running Agent: $service_id" >&2
    continue
  fi
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  mv "$temp_path" "$plist_path"
  chmod 600 "$plist_path"
  launchctl bootstrap "$DOMAIN" "$plist_path"
done

echo "Installed 12 on-demand Agent LaunchAgents."
