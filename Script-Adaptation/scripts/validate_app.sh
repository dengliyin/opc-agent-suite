#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${SCRIPT_ADAPTATION_APP_ROOT:-${SKILL_ROOT}/software/Script-Adaptation-app}"
PYTHON_BIN="${PYTHON_BIN:-${SKILL_ROOT}/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
cd "$APP_ROOT"

"$PYTHON_BIN" -m py_compile \
  opc_engine/core/config_store.py \
  opc_engine/core/project_assets.py \
  opc_engine/features/video_teardown/analyze_video_teardown.py \
  opc_engine/features/script_adaptation/content_workflow_stage.py \
  opc_engine/features/script_adaptation/script_adaptation_agent.py \
  opc_engine/features/script_adaptation/script_adaptation_agent_web.py

"$PYTHON_BIN" - <<'PY'
from opc_engine.features.script_adaptation.script_adaptation_agent import ScriptAdaptationAgent
from opc_engine.features.script_adaptation.content_workflow_stage import (
    omni_embedded_script_reset_issues,
    reset_omni_output_segment_scripts,
)
from opc_engine.features.script_adaptation.script_adaptation_agent_web import (
    adaptation_output_stem,
    character_reference_issues,
)

config = ScriptAdaptationAgent().load_stage_config("adapt")
print(adaptation_output_stem(config, "7570561984886852882_GlowRoot_Herbal_Hair_Color_Shampoo.md", "veo"))

multi_character_markdown = """# Segment 1：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成一张虚构成年普通用户定妆参考板。
角色设定：两位成年普通用户。
## B. 故事板图片提示词
下面是本段镜头脚本（已过滤字段）:
镜头 1 (00:00.000 - 00:05.000)
[主体] character_01 和 character_02

# Segment 2：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
本段复用 character_01 和 character_02 人物图，不需要重新生成人物造型参考板。
## B. 故事板图片提示词
下面是本段镜头脚本（已过滤字段）:
镜头 1 (00:00.000 - 00:05.000)
[主体] character_01 和 character_02
"""
normalized = reset_omni_output_segment_scripts(multi_character_markdown)
assert normalized.count("### 镜头 1 (00:00.000 - 00:05.000)") == 2
assert character_reference_issues(normalized) == []
assert omni_embedded_script_reset_issues(normalized) == []
print("multi-character validation: ok")

heading_variants = """# Segment 1：00:00.000 - 00:02.000
## A. 人物造型参考板提示词
本段为产品特写段落，无人物主体，不需要生成人物造型参考板。
## B. 故事板图片提示词
下面是本段镜头脚本（已过滤字段）:
**镜头 4-part1 (00:09.500 - 00:10.000)**
[主体] 图1中的该产品
**镜头 4-part2** (00:10.000 - 00:11.500；对应原镜头4部分)
[主体] 图1中的该产品
"""
normalized_headings = reset_omni_output_segment_scripts(heading_variants)
assert "### 镜头 1 (00:00.000 - 00:00.500)" in normalized_headings
assert "### 镜头 2 (00:00.500 - 00:02.000)" in normalized_headings
assert omni_embedded_script_reset_issues(normalized_headings) == []
print("segment heading normalization: ok")

mixed_character_markdown = """# Segment 1：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成一张人物造型参考板。
角色设定：两位成年普通用户。
## B. 故事板图片提示词
故事板提示词

# Segment 2：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
本段复用 character_01、character_02 人物图。
角色ID：character_03
生成一张人物造型参考板。
角色设定：新增成年普通用户。
## B. 故事板图片提示词
故事板提示词
"""
mixed_issues = character_reference_issues(mixed_character_markdown)
assert any("同时复用旧人物图并生成新人物参考板" in issue for issue in mixed_issues)

composite_character_markdown = mixed_character_markdown.replace(
    "本段复用 character_01、character_02 人物图。\n角色ID：character_03",
    "本段重新生成一张包含全部人物的合成人物参考板。\n角色ID：character_01、character_02、character_03",
)
assert character_reference_issues(composite_character_markdown) == []
print("mixed character board validation: ok")
PY
