#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-$PWD/.venv/bin/python}"
PORT="${FINISHED_VIDEO_MANAGER_PORT:-9996}"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

case "${1:-web}" in
  web)
    "$PYTHON_BIN" -m finished_video_manager.web --host 127.0.0.1 --port "$PORT"
    ;;
  publish)
    shift
    "$PYTHON_BIN" -m finished_video_manager.web publish "$@"
    ;;
  *)
    echo "用法: ./run_agent.sh web"
    echo "      ./run_agent.sh publish --profile-id <比特窗口ID> --video-path <视频路径> --caption <发布文案> --product-id <商品ID> --product-short-name <商品简称>"
    exit 1
    ;;
esac
