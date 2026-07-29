#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for required in \
  "$ROOT_DIR/vendor/tiktok-karaoke-captions/caption.py" \
  "$ROOT_DIR/vendor/tiktok-karaoke-captions/LICENSE" \
  "$ROOT_DIR/vendor/tiktok-karaoke-captions/fonts/Roboto-Black.ttf"
do
  test -f "$required"
done
(
  cd "$ROOT_DIR"
  .venv/bin/python -m unittest discover -s tests -v
  .venv/bin/python -m py_compile app/mixer.py app/server.py
)
