#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
RUNTIME_ROOT="${HYBRID_MIX_RUNTIME_ROOT:-${ROOT_DIR}/../Video-Generation/assembly/runtime}"
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

RUNTIME_BIN="$RUNTIME_ROOT/bin"
export UV_CACHE_DIR="$RUNTIME_ROOT/cache/uv"
export HF_HOME="$RUNTIME_ROOT/cache/huggingface"
export PATH="$RUNTIME_BIN:$PATH"
mkdir -p "$RUNTIME_BIN" "$UV_CACHE_DIR" "$HF_HOME"

"$PYTHON_BIN" -m pip install --disable-pip-version-check uv
install -m 755 "$ROOT_DIR/.venv/bin/uv" "$RUNTIME_BIN/uv"
install -m 755 "$ROOT_DIR/.venv/bin/uvx" "$RUNTIME_BIN/uvx"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
"$RUNTIME_ROOT/bin/ffmpeg" -hide_banner -loglevel error -y \
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
echo "AI＋实拍混剪字幕运行环境已安装：Whisper $MODEL_KEY"
