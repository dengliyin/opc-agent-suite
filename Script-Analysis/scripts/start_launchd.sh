#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="local.Script-Analysis"
OUT_LOG="$PROJECT_DIR/logs/launchd.submit.out.log"
ERR_LOG="$PROJECT_DIR/logs/launchd.submit.err.log"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$PROJECT_DIR/logs"

ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:9992/api/status", timeout=3) as response:
    data = json.load(response)
if not str(data.get("skill_root", "")).endswith("Script-Analysis"):
    raise SystemExit(1)
PY
}

if ready; then
  echo "Web 服务已在运行: http://127.0.0.1:9992"
  exit 0
fi

launchctl remove "$LABEL" >/dev/null 2>&1 || true

launchctl submit \
  -l "$LABEL" \
  -o "$OUT_LOG" \
  -e "$ERR_LOG" \
  -- "$PYTHON_BIN" "$PROJECT_DIR/scripts/web_app.py" --host 127.0.0.1 --port 9992

for _ in $(seq 1 20); do
  if ready; then
    echo "Web 服务已启动: http://127.0.0.1:9992"
    exit 0
  fi
  sleep 0.5
done

echo "服务启动失败，错误日志:"
tail -40 "$ERR_LOG" 2>/dev/null || true
exit 1
