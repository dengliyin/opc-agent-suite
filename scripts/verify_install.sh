#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPONENTS=(
  "OPC-Console"
  "Video-Collection"
  "Script-Analysis"
  "Script-Generation"
  "Script-Adaptation"
  "Hybrid-Script-Adaptation"
  "Hybrid-Video-Collection"
  "Hybrid-Script-Analysis"
  "Hybrid-Script-Generation"
  "Hybrid-Video-Mixer"
  "Video-Generation"
  "Finished-Video-Manager"
  "Product-Script-Rewrite"
  "Video-Assembly-hd"
)

for component in "${COMPONENTS[@]}"; do
  python_bin="$ROOT_DIR/$component/.venv/bin/python"
  if [ ! -x "$python_bin" ]; then
    echo "Missing virtual environment: $component/.venv" >&2
    exit 1
  fi
  version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$version" != "3.12" ]; then
    echo "$component uses Python $version, expected 3.12" >&2
    exit 1
  fi
  "$python_bin" -m pip check >/dev/null
done

"$ROOT_DIR/OPC-Console/.venv/bin/python" -m compileall -q "$ROOT_DIR/OPC-Console/kesai_app.py"
"$ROOT_DIR/Video-Collection/.venv/bin/python" -m compileall -q "$ROOT_DIR/Video-Collection/hot_video_agent"
"$ROOT_DIR/Script-Analysis/.venv/bin/python" -m compileall -q "$ROOT_DIR/Script-Analysis/scripts"
"$ROOT_DIR/Script-Generation/.venv/bin/python" -m compileall -q "$ROOT_DIR/Script-Generation/opc_engine"
"$ROOT_DIR/Script-Adaptation/.venv/bin/python" -m compileall -q "$ROOT_DIR/Script-Adaptation/software/Script-Adaptation-app/opc_engine"
"$ROOT_DIR/Hybrid-Script-Adaptation/.venv/bin/python" -m compileall -q "$ROOT_DIR/Hybrid-Script-Adaptation/software/Hybrid-Script-Adaptation-app/opc_engine"
"$ROOT_DIR/Hybrid-Video-Collection/.venv/bin/python" -m compileall -q "$ROOT_DIR/Hybrid-Video-Collection/hot_video_agent"
"$ROOT_DIR/Hybrid-Script-Analysis/.venv/bin/python" -m compileall -q "$ROOT_DIR/Hybrid-Script-Analysis/scripts"
"$ROOT_DIR/Hybrid-Script-Generation/.venv/bin/python" -m compileall -q "$ROOT_DIR/Hybrid-Script-Generation/opc_engine"
"$ROOT_DIR/Hybrid-Video-Mixer/.venv/bin/python" -m compileall -q "$ROOT_DIR/Hybrid-Video-Mixer/app"
"$ROOT_DIR/Video-Generation/.venv/bin/python" -m compileall -q "$ROOT_DIR/Video-Generation/agent"
"$ROOT_DIR/Finished-Video-Manager/.venv/bin/python" -m compileall -q "$ROOT_DIR/Finished-Video-Manager/finished_video_manager"
"$ROOT_DIR/Product-Script-Rewrite/.venv/bin/python" -m compileall -q "$ROOT_DIR/Product-Script-Rewrite/product_script_rewrite"
"$ROOT_DIR/Video-Assembly-hd/.venv/bin/python" -m compileall -q "$ROOT_DIR/Video-Assembly-hd/app"

(cd "$ROOT_DIR/OPC-Console" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Script-Analysis" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Script-Generation" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Hybrid-Script-Adaptation" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Hybrid-Video-Collection" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Hybrid-Script-Analysis" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Hybrid-Script-Generation" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Hybrid-Video-Mixer" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Finished-Video-Manager" && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q)
(cd "$ROOT_DIR/Video-Generation" && .venv/bin/python -m pytest -q)
bash "$ROOT_DIR/Video-Assembly-hd/scripts/validate_app.sh"

echo "All locked environments, imports, and automated tests passed."
