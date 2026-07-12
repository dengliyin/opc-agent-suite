#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" -m compileall -q "$ROOT_DIR/app"
"$PYTHON_BIN" -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'

for path in \
  "$ROOT_DIR/runtime/bin/node" \
  "$ROOT_DIR/runtime/bin/ffmpeg" \
  "$ROOT_DIR/runtime/bin/ffprobe" \
  "$ROOT_DIR/runtime/hyperframes/package/dist/cli.js" \
  "$ROOT_DIR/runtime/chrome/chrome-headless-shell" \
  "$ROOT_DIR/vendor/gsap.min.js"
do
  test -f "$path"
done

HOST_ARCH="$(uname -m)"
for executable in \
  "$ROOT_DIR/runtime/bin/node" \
  "$ROOT_DIR/runtime/bin/ffmpeg" \
  "$ROOT_DIR/runtime/bin/ffprobe" \
  "$ROOT_DIR/runtime/chrome/chrome-headless-shell"
do
  description="$(file "$executable")"
  if ! printf '%s' "$description" | grep -Eq "$HOST_ARCH|universal"; then
    echo "运行时架构不匹配: $description" >&2
    exit 1
  fi
done

FFMPEG_VERSION="$($ROOT_DIR/runtime/bin/ffmpeg -version | sed -nE '1s/.*version ([0-9]+\.[0-9]+).*/\1/p')"
FFPROBE_VERSION="$($ROOT_DIR/runtime/bin/ffprobe -version | sed -nE '1s/.*version ([0-9]+\.[0-9]+).*/\1/p')"
if [ -z "$FFMPEG_VERSION" ] || [ "$FFMPEG_VERSION" != "$FFPROBE_VERSION" ]; then
  echo "FFmpeg/FFprobe 版本不一致: ${FFMPEG_VERSION:-unknown} / ${FFPROBE_VERSION:-unknown}" >&2
  exit 1
fi

if rg --pcre2 -n 'https?://(?!127\.0\.0\.1|localhost)|pnpm[[:space:]]+dlx|npx[[:space:]]+hyperframes' \
  "$ROOT_DIR/app" "$ROOT_DIR/static" "$ROOT_DIR/scripts"; then
  echo "检测到运行时代码中的联网引用" >&2
  exit 1
fi

echo "离线片段合成应用验证通过: FFmpeg/FFprobe $FFMPEG_VERSION ($HOST_ARCH)"
