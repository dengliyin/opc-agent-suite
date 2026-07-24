#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"

if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  echo "Created local configuration: $ENV_FILE"
fi
chmod 600 "$ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

find_python() {
  local candidate
  if [ -n "${OPC_PYTHON_BIN:-}" ]; then
    candidate="$OPC_PYTHON_BIN"
    if [ ! -x "$candidate" ]; then
      echo "OPC_PYTHON_BIN is not executable: $candidate" >&2
      return 1
    fi
    printf '%s\n' "$candidate"
    return 0
  fi

  for candidate in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.12 is required. Install it with Homebrew: brew install python@3.12" >&2
  echo "Then rerun this script, or set OPC_PYTHON_BIN to a Python 3.12 executable." >&2
  exit 1
fi

PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$PYTHON_VERSION" != "3.12" ]; then
  echo "Unsupported Python $PYTHON_VERSION at $PYTHON_BIN; this suite is locked to Python 3.12." >&2
  exit 1
fi

echo "Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

COMPONENTS=(
  "OPC-Console"
  "Video-Collection"
  "Script-Analysis"
  "Script-Generation"
  "Script-Adaptation"
  "Hybrid-Script-Adaptation"
  "Video-Generation"
  "Finished-Video-Manager"
  "Product-Script-Rewrite"
  "Video-Assembly-hd"
)

for component in "${COMPONENTS[@]}"; do
  component_dir="$ROOT_DIR/$component"
  venv_dir="$component_dir/.venv"
  lock_file="$component_dir/requirements.lock.txt"

  if [ -x "$venv_dir/bin/python" ]; then
    venv_version="$($venv_dir/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [ "$venv_version" != "3.12" ]; then
      echo "Recreating $component virtual environment (found Python $venv_version)."
      rm -rf "$venv_dir"
    fi
  fi

  if [ ! -x "$venv_dir/bin/python" ]; then
    echo "Creating $component/.venv"
    "$PYTHON_BIN" -m venv "$venv_dir"
  fi

  echo "Installing $component dependencies"
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$venv_dir/bin/python" -m pip install --requirement "$lock_file"
  "$venv_dir/bin/python" -m pip check
done

if [ "${OPC_SKIP_PLAYWRIGHT_BROWSER_INSTALL:-0}" != "1" ]; then
  echo "Installing the locked Playwright Chromium runtime"
  "$ROOT_DIR/Video-Collection/.venv/bin/playwright" install chromium
fi

if [ -n "${OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE:-}" ]; then
  "$ROOT_DIR/scripts/install_video_assembly_runtime.sh" "$OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE"
else
  echo "Video assembly runtime not installed. Set OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE and rerun when needed."
fi

"$ROOT_DIR/scripts/verify_install.sh"
echo "Installation verified. Start the console with: $ROOT_DIR/scripts/start_console.sh"
