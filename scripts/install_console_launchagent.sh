#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"
LABEL="com.kesai.opc-console"
DOMAIN="gui/$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
TEMPLATE_PATH="$ROOT_DIR/scripts/launchd/$LABEL.plist.template"
RUNNER_PATH="$ROOT_DIR/scripts/run_console_foreground.sh"
LOG_DIR="$ROOT_DIR/.runtime/logs"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi
if [ ! -x "$ROOT_DIR/OPC-Console/.venv/bin/python" ]; then
  echo "Missing OPC-Console virtual environment. Run scripts/bootstrap_macos.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
PORT="${KESAI_APP_PORT:-8888}"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

for pid in $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true); do
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  if [[ "$command_line" == *"$ROOT_DIR"* || "$process_cwd" == "$ROOT_DIR" || "$process_cwd" == "$ROOT_DIR/"* ]]; then
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

root_escaped="$(sed_escape "$ROOT_DIR")"
runner_escaped="$(sed_escape "$RUNNER_PATH")"
stdout_escaped="$(sed_escape "$LOG_DIR/console-launchd.out.log")"
stderr_escaped="$(sed_escape "$LOG_DIR/console-launchd.err.log")"

sed \
  -e "s|__ROOT__|$root_escaped|g" \
  -e "s|__RUNNER__|$runner_escaped|g" \
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
echo "If the repository is under Documents, grant /bin/bash Full Disk Access and rerun this installer." >&2
exit 1
