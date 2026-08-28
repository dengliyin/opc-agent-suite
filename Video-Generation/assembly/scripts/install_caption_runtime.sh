#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${APP_ROOT}/.venv/bin/python}"
MODEL_KEY="${VIDEO_ASSEMBLY_WHISPER_MODEL:-medium}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "找不到应用 Python：$PYTHON_BIN" >&2
  exit 1
fi

case "$MODEL_KEY" in
  tiny|base|small|medium|large) ;;
  *)
    echo "不支持的 Whisper 模型：$MODEL_KEY" >&2
    exit 1
    ;;
esac

RUNTIME_BIN="$ROOT_DIR/runtime/bin"
export UV_CACHE_DIR="$ROOT_DIR/runtime/cache/uv"
export HF_HOME="$ROOT_DIR/runtime/cache/huggingface"
export PATH="$RUNTIME_BIN:$PATH"
mkdir -p "$RUNTIME_BIN" "$UV_CACHE_DIR" "$HF_HOME"

"$PYTHON_BIN" -m pip install --disable-pip-version-check uv
install -m 755 "$APP_ROOT/.venv/bin/uv" "$RUNTIME_BIN/uv"
install -m 755 "$APP_ROOT/.venv/bin/uvx" "$RUNTIME_BIN/uvx"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
"$ROOT_DIR/runtime/bin/ffmpeg" -hide_banner -loglevel error -y \
  -f lavfi -i "anullsrc=r=16000:cl=mono" -t 0.2 "$TMP_DIR/prewarm.wav"

"$RUNTIME_BIN/uvx" --from mlx-whisper mlx_whisper \
  "$TMP_DIR/prewarm.wav" \
  --model "mlx-community/whisper-${MODEL_KEY}-mlx" \
  --language en \
  --output-format json \
  --output-dir "$TMP_DIR" \
  --output-name prewarm \
  --word-timestamps True

test -s "$TMP_DIR/prewarm.json"
echo "TikTok 卡拉 OK 字幕运行环境已安装：Whisper $MODEL_KEY"
