#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/Library/Application Support/OPC-Agent-Suite"
ENV_FILE="${OPC_ENV_FILE:-$CONFIG_DIR/.env}"
RUNTIME_ROOT="${OPC_SERVICE_RUNTIME_ROOT:-$CONFIG_DIR/Service-Runtime}"
DOMAIN="gui/$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"
TEMPLATE_PATH="$ROOT_DIR/scripts/launchd/com.kesai.opc-agent.plist.template"
LAUNCHER_PATH="$RUNTIME_ROOT/scripts/run_agent_foreground.py"
LOG_DIR="$HOME/Library/Logs/OPC-Agent-Suite"
SERVICE_IDS=(collect analyze script adapt assemble finished rewrite compose hybrid_adapt hybrid_mix hybrid_collect hybrid_analyze hybrid_script hybrid_voice)

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
    hybrid_mix) echo "Hybrid-Video-Mixer" ;;
    hybrid_collect) echo "Hybrid-Video-Collection" ;;
    hybrid_analyze) echo "Hybrid-Script-Analysis" ;;
    hybrid_script) echo "Hybrid-Script-Generation" ;;
    hybrid_voice) echo "Hybrid-Audio-Generation" ;;
    *) return 1 ;;
  esac
}

mkdir -p "$CONFIG_DIR"
if [ ! -f "$ENV_FILE" ] && [ -f "$ROOT_DIR/.env" ]; then
  cp "$ROOT_DIR/.env" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi
"$ROOT_DIR/scripts/stage_service_runtime.sh" >/dev/null
if [ ! -x "$RUNTIME_ROOT/OPC-Console/.venv/bin/python" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

sed_escape() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

bootstrap_agent() {
  local plist_path="$1"
  local attempt
  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "$DOMAIN" "$plist_path"; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

launcher_escaped="$(sed_escape "$LAUNCHER_PATH")"
env_file_escaped="$(sed_escape "$ENV_FILE")"

for service_id in "${SERVICE_IDS[@]}"; do
  agent_dir="$(service_dir "$service_id")"
  python_path="$RUNTIME_ROOT/$agent_dir/.venv/bin/python"
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
    -e "s|__ENV_FILE__|$env_file_escaped|g" \
    -e "s|__OUT_LOG__|$(sed_escape "$out_log_path")|g" \
    -e "s|__ERR_LOG__|$(sed_escape "$err_log_path")|g" \
    "$TEMPLATE_PATH" > "$temp_path"

  plutil -lint "$temp_path" >/dev/null
  if [ -f "$plist_path" ] && cmp -s "$temp_path" "$plist_path" && launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    rm -f "$temp_path"
    continue
  fi
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  mv "$temp_path" "$plist_path"
  chmod 600 "$plist_path"
  bootstrap_agent "$plist_path"
done

echo "Installed 14 on-demand Agent LaunchAgents."
