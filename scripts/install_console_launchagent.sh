#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/Library/Application Support/OPC-Agent-Suite"
ENV_FILE="${OPC_ENV_FILE:-$CONFIG_DIR/.env}"
RUNTIME_ROOT="${OPC_SERVICE_RUNTIME_ROOT:-$CONFIG_DIR/Service-Runtime}"
LABEL="com.kesai.opc-console"
DOMAIN="gui/$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
TEMPLATE_PATH="$ROOT_DIR/scripts/launchd/$LABEL.plist.template"
PYTHON_PATH="$RUNTIME_ROOT/OPC-Console/.venv/bin/python"
LAUNCHER_PATH="$RUNTIME_ROOT/scripts/run_console_foreground.py"
LOG_DIR="$HOME/Library/Logs/OPC-Agent-Suite"

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
if [ ! -x "$PYTHON_PATH" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
PORT="${KESAI_APP_PORT:-8888}"

if [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.collect.plist" ] || \
   [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.hybrid_adapt.plist" ] || \
   [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.hybrid_collect.plist" ] || \
   [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.hybrid_analyze.plist" ] || \
   [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.hybrid_script.plist" ] || \
   [ ! -f "$HOME/Library/LaunchAgents/com.kesai.opc-agent.hybrid_voice.plist" ]; then
  "$ROOT_DIR/scripts/install_agent_launchagents.sh"
fi

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

for pid in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  if [[ "$command_line" == *"$ROOT_DIR"* || "$command_line" == *"$RUNTIME_ROOT"* || "$process_cwd" == "$ROOT_DIR" || "$process_cwd" == "$ROOT_DIR/"* || "$process_cwd" == "$RUNTIME_ROOT" || "$process_cwd" == "$RUNTIME_ROOT/"* ]]; then
    kill "$pid" 2>/dev/null || true
  else
    echo "Port $PORT is occupied by an unrelated process: $command_line" >&2
    exit 1
  fi
done

mkdir -p "$PLIST_DIR" "$LOG_DIR"

sed_escape() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

python_escaped="$(sed_escape "$PYTHON_PATH")"
launcher_escaped="$(sed_escape "$LAUNCHER_PATH")"
stdout_escaped="$(sed_escape "$LOG_DIR/console-launchd.out.log")"
stderr_escaped="$(sed_escape "$LOG_DIR/console-launchd.err.log")"
env_file_escaped="$(sed_escape "$ENV_FILE")"

sed \
  -e "s|__PYTHON__|$python_escaped|g" \
  -e "s|__LAUNCHER__|$launcher_escaped|g" \
  -e "s|__ENV_FILE__|$env_file_escaped|g" \
  -e "s|__STDOUT__|$stdout_escaped|g" \
  -e "s|__STDERR__|$stderr_escaped|g" \
  "$TEMPLATE_PATH" > "$PLIST_PATH"

chmod 600 "$PLIST_PATH"
plutil -lint "$PLIST_PATH" >/dev/null
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"

URL="http://${KESAI_APP_HOST:-127.0.0.1}:$PORT/"
for _ in {1..40}; do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    echo "OPC Console LaunchAgent installed: $URL"
    echo "Service: $DOMAIN/$LABEL"
    echo "Plist: $PLIST_PATH"
    exit 0
  fi
  sleep 0.25
done

echo "LaunchAgent loaded but the console did not become healthy: $URL" >&2
tail -n 60 "$LOG_DIR/console-launchd.err.log" >&2 || true
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"
echo "The failed LaunchAgent was removed to prevent a restart loop." >&2
exit 1
