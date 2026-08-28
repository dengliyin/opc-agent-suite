#!/usr/bin/env bash
set -euo pipefail

LABELS=("控制台" "脚本解析" "脚本产出" "脚本适配" "片段产出与合成" "成品管理" "产品脚本改写" "钩子与CTA脚本适配" "AI＋实拍混剪" "混剪参考视频解析" "钩子与CTA脚本复刻裂变" "配音" "自动发布流水线" "脚本创作与适配")
PORTS=(8888 9992 9993 9994 9995 9996 9997 9999 10000 10002 10003 10004 10005 10006)
PATHS=("health" "health" "health" "health" "health" "health" "health" "health" "health" "health" "health" "health" "health" "health")

FAILED=0
for index in "${!PORTS[@]}"; do
  url="http://127.0.0.1:${PORTS[$index]}/${PATHS[$index]}"
  if status="$(curl -L -sS -o /dev/null -w '%{http_code}' --max-time 30 "$url")" && [[ "$status" =~ ^2 ]]; then
    printf 'OK    %-20s %s (%s)\n' "${LABELS[$index]}" "$url" "$status"
  else
    printf 'FAIL  %-20s %s\n' "${LABELS[$index]}" "$url"
    FAILED=1
  fi
done

exit "$FAILED"
