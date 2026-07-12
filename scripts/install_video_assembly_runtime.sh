#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT_DIR/Video-Assembly-hd/runtime"
SOURCE="${1:-${OPC_VIDEO_ASSEMBLY_RUNTIME_SOURCE:-}}"

if [ -z "$SOURCE" ]; then
  echo "Usage: $0 /path/to/runtime-or-archive" >&2
  exit 2
fi

SOURCE="${SOURCE/#\~/$HOME}"
if [ ! -e "$SOURCE" ]; then
  echo "Runtime source does not exist: $SOURCE" >&2
  exit 1
fi

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/opc-video-runtime.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

if [ -d "$SOURCE" ]; then
  CANDIDATE="$SOURCE"
  if [ -f "$SOURCE/runtime/bin/node" ]; then
    CANDIDATE="$SOURCE/runtime"
  fi
  mkdir -p "$STAGING/runtime"
  rsync -a "$CANDIDATE/" "$STAGING/runtime/"
else
  case "$SOURCE" in
    *.zip)
      ditto -x -k "$SOURCE" "$STAGING/unpacked"
      ;;
    *.tar|*.tar.gz|*.tgz)
      mkdir -p "$STAGING/unpacked"
      tar -xf "$SOURCE" -C "$STAGING/unpacked"
      ;;
    *)
      echo "Supported runtime sources: directory, .zip, .tar, .tar.gz, or .tgz" >&2
      exit 1
      ;;
  esac
  NODE_PATH="$(find "$STAGING/unpacked" -type f -path '*/bin/node' -print -quit)"
  if [ -z "$NODE_PATH" ]; then
    echo "Archive does not contain runtime/bin/node" >&2
    exit 1
  fi
  CANDIDATE="$(cd "$(dirname "$NODE_PATH")/.." && pwd)"
  mkdir -p "$STAGING/runtime"
  rsync -a "$CANDIDATE/" "$STAGING/runtime/"
fi

REQUIRED=(
  "bin/node"
  "bin/ffmpeg"
  "bin/ffprobe"
  "hyperframes/package/dist/cli.js"
  "chrome/chrome-headless-shell"
)

for relative in "${REQUIRED[@]}"; do
  if [ ! -f "$STAGING/runtime/$relative" ]; then
    echo "Incomplete runtime; missing $relative" >&2
    exit 1
  fi
done

chmod +x \
  "$STAGING/runtime/bin/node" \
  "$STAGING/runtime/bin/ffmpeg" \
  "$STAGING/runtime/bin/ffprobe" \
  "$STAGING/runtime/chrome/chrome-headless-shell"

HOST_ARCH="$(uname -m)"
for executable in bin/node bin/ffmpeg bin/ffprobe chrome/chrome-headless-shell; do
  DESCRIPTION="$(file "$STAGING/runtime/$executable")"
  echo "$DESCRIPTION"
  if ! printf '%s' "$DESCRIPTION" | grep -Eq "$HOST_ARCH|universal"; then
    echo "Runtime rejected: $executable does not match host architecture $HOST_ARCH." >&2
    exit 1
  fi
done

FFMPEG_VERSION="$($STAGING/runtime/bin/ffmpeg -version | sed -nE '1s/.*version ([0-9]+\.[0-9]+).*/\1/p')"
FFPROBE_VERSION="$($STAGING/runtime/bin/ffprobe -version | sed -nE '1s/.*version ([0-9]+\.[0-9]+).*/\1/p')"
if [ -z "$FFMPEG_VERSION" ] || [ "$FFMPEG_VERSION" != "$FFPROBE_VERSION" ]; then
  echo "Runtime rejected: FFmpeg ${FFMPEG_VERSION:-unknown} and FFprobe ${FFPROBE_VERSION:-unknown} do not match." >&2
  exit 1
fi

rm -rf "$TARGET"
mv "$STAGING/runtime" "$TARGET"

echo "FFmpeg and FFprobe version: $FFMPEG_VERSION ($HOST_ARCH)"
echo "Video assembly runtime installed at $TARGET ($(du -sh "$TARGET" | awk '{print $1}'))."
