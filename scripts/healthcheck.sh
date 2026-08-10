#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${OPC_ENV_FILE:-${ROOT_DIR}/.env}"
MODE="${1:---all}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

LABELS=("控制台")
URLS=("http://${KESAI_APP_HOST:-127.0.0.1}:${KESAI_APP_PORT:-8888}/")
PATHS=("health")

if [ "$MODE" != "--console-only" ]; then
  LABELS+=("视频采集" "脚本解析" "脚本产出" "脚本适配" "片段产出" "成品管理" "产品脚本改写" "片段合成" "钩子与CTA脚本适配" "AI＋实拍混剪" "混剪参考视频采集" "混剪参考视频解析" "钩子与CTA脚本复刻裂变" "配音" "自动发布流水线")
  URLS+=(
    "${OPC_HOT_VIDEO_AGENT_URL:-http://127.0.0.1:9991/}"
    "${OPC_VIDEO_TEARDOWN_AGENT_URL:-http://127.0.0.1:9992/}"
    "${OPC_SCRIPT_PRODUCTION_AGENT_URL:-http://127.0.0.1:9993/}"
    "${OPC_SCRIPT_ADAPTATION_AGENT_URL:-http://127.0.0.1:9994/}"
    "${OPC_VIDEO_OUTPUT_AGENT_URL:-http://127.0.0.1:9995/}"
    "${OPC_FINISHED_VIDEO_MANAGER_URL:-http://127.0.0.1:9996/}"
    "${OPC_PRODUCT_SCRIPT_REWRITE_URL:-http://127.0.0.1:9997/}"
    "${OPC_VIDEO_ASSEMBLY_AGENT_URL:-http://127.0.0.1:9998/}"
    "${OPC_HYBRID_SCRIPT_ADAPTATION_AGENT_URL:-http://127.0.0.1:9999/}"
    "${OPC_HYBRID_VIDEO_MIXER_AGENT_URL:-http://127.0.0.1:10000/}"
    "${OPC_HYBRID_VIDEO_COLLECTION_AGENT_URL:-http://127.0.0.1:10001/}"
    "${OPC_HYBRID_SCRIPT_ANALYSIS_AGENT_URL:-http://127.0.0.1:10002/}"
    "${OPC_HYBRID_SCRIPT_GENERATION_AGENT_URL:-http://127.0.0.1:10003/}"
    "${OPC_HYBRID_AUDIO_GENERATION_AGENT_URL:-http://127.0.0.1:10004/}"
    "${OPC_AUTO_PUBLISH_PIPELINE_URL:-http://127.0.0.1:10005/}"
  )
  PATHS+=(
    "api/state"
    "api/status"
    "api/outputs"
    "api/outputs?target_model=veo"
    "health"
    "api/state"
    "api/state"
    "api/state"
    "api/scripts?target_model=omni"
    "api/library"
    "api/state"
    "api/state"
    "api/status"
    "api/outputs"
    "api/library"
  )
fi

FAILED=0
for index in "${!URLS[@]}"; do
  url="${URLS[$index]%/}/${PATHS[$index]}"
  if status="$(curl -L -sS -o /dev/null -w '%{http_code}' --max-time 30 "$url")" && [[ "$status" =~ ^2 ]]; then
    printf 'OK    %-16s %s (%s)\n' "${LABELS[$index]}" "$url" "$status"
  else
    printf 'FAIL  %-16s %s\n' "${LABELS[$index]}" "$url"
    FAILED=1
  fi
done

exit "$FAILED"
