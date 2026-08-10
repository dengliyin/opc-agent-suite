#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${OPC_SERVICE_RUNTIME_ROOT:-$HOME/Library/Application Support/OPC-Agent-Suite/Service-Runtime}"
COMPONENTS=(
  OPC-Console
  Video-Collection
  Script-Analysis
  Script-Generation
  Script-Adaptation
  Video-Generation
  Finished-Video-Manager
  Product-Script-Rewrite
  Video-Assembly-hd
  Hybrid-Script-Adaptation
  Hybrid-Video-Mixer
  Hybrid-Video-Collection
  Hybrid-Script-Analysis
  Hybrid-Script-Generation
  Hybrid-Audio-Generation
  Auto-Publish-Pipeline
)

mkdir -p "$RUNTIME_ROOT"

sync_component() {
  local component="$1"
  local source="$SOURCE_ROOT/$component/"
  local destination="$RUNTIME_ROOT/$component"
  local excludes=(
    --exclude=.DS_Store
    --exclude=__pycache__/
    --exclude=.pytest_cache/
    --exclude=runs/
  )

  if [ -d "$destination" ]; then
    excludes+=(
      --exclude=agent_config/
      --exclude=browser-profile/
      --exclude=config/
      --exclude=data/
      --exclude=projects/
      --exclude=run_logs/
    )
  fi

  mkdir -p "$destination"
  rsync -a --delete "${excludes[@]}" "$source" "$destination/"
}

for component in "${COMPONENTS[@]}"; do
  sync_component "$component"
done

rsync -a --delete \
  --exclude=.DS_Store \
  --exclude=__pycache__/ \
  "$SOURCE_ROOT/scripts/" "$RUNTIME_ROOT/scripts/"
rsync -a --delete "$SOURCE_ROOT/storage-template/" "$RUNTIME_ROOT/storage-template/"

echo "$RUNTIME_ROOT"
