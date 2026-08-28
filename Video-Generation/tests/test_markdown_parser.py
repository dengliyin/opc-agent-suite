import re

import pytest

from agent.markdown_parser import (
    build_direct_video_prompt,
    build_product_video_prompt,
    build_storyboard_image_prompt,
    build_video_prompt,
    character_source_segment_index,
    parse_segments,
)


SAMPLE = """#
## 每段生成提示词

# Segment 1：00:00.000 - 00:07.600

## A. 人物造型参考板提示词

人物提示词 1

## B. 故事板图片提示词

故事提示词 1
### 镜头 1
内容

# Segment 2：00:07.600 - 00:12.600

## A. 人物造型参考板提示词

本段复用 character_01 人物图，不需要重新生成人物造型参考板。

## B. 故事板图片提示词

故事提示词 2
"""


def test_parse_segments_extracts_prompts_and_reuse() -> None:
    segments = parse_segments(SAMPLE)

    assert len(segments) == 2
    assert segments[0].index == 1
    assert segments[0].time_range == "00:00.000 - 00:07.600"
    assert segments[0].character_prompt == "人物提示词 1"
    assert "故事提示词 1" in segments[0].storyboard_prompt
    assert segments[1].reuses_character is True
    assert segments[1].referenced_character_index == 1


def test_parse_segments_accepts_grok_video_prompt_heading() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:30.000

## A. 人物造型参考板提示词

人物提示词

## B. Grok 视频片段提示词

Grok 片段提示词
"""
    )

    assert len(segments) == 1
    assert segments[0].storyboard_prompt == "Grok 片段提示词"


def test_parse_segments_accepts_heading_level_variants() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:10.000

### A. 人物造型参考板提示词

人物提示词

### B. 故事板图片提示词

故事提示词
"""
    )

    assert len(segments) == 1
    assert segments[0].character_prompt == "人物提示词"
    assert segments[0].storyboard_prompt == "故事提示词"


def test_future_reuse_note_is_not_current_segment_reuse() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:10.000

## A. 人物造型参考板提示词

本段首次出现该人物，生成人物造型参考板，后续段落将复用为 character_01。

## B. 故事板图片提示词

故事提示词
"""
    )

    assert segments[0].reuses_character is False
    assert segments[0].referenced_character_index == 1


def test_current_segment_reuse_allows_detailed_source_description() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:10.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成方式：首次生成
参考来源：无
本段首次生成 character_01 与 character_02 人物造型参考板。
## B. 故事板图片提示词
故事提示词

# Segment 2：00:00.000 - 00:10.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成方式：直接复用
参考来源：Segment 1
本段复用 Segment 1 中已生成的同一张人物造型参考板（包含 character_01 与 character_02），不需要重新生成人物造型参考板。
## B. 故事板图片提示词
故事提示词
"""
    )

    assert segments[1].reuses_character is True
    assert segments[1].character_generation_mode == "直接复用"
    assert segments[1].character_reference_segment_indices == (1,)
    assert segments[1].referenced_character_indices == (1, 2)
    assert character_source_segment_index(segments, segments[1]) == 1


def test_parse_character_state_update_and_merge_reference_sources() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01
生成方式：首次生成
参考来源：无
本段首次生成 character_01 的人物造型参考板。
## B. 故事板图片提示词
故事提示词

# Segment 2：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_02
生成方式：首次生成
参考来源：无
本段首次生成 character_02 的人物造型参考板。
## B. 故事板图片提示词
故事提示词

# Segment 3：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01
生成方式：状态更新
参考来源：Segment 1
保持 character_01 身份不变，重新生成当前外观状态参考板。
## B. 故事板图片提示词
故事提示词

# Segment 4：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02、character_03
生成方式：新角色合并
参考来源：Segment 3、Segment 2
保持旧角色身份不变，并加入 character_03，生成同一张合成参考板。
## B. 故事板图片提示词
故事提示词
"""
    )

    assert segments[2].reuses_character is False
    assert segments[2].character_generation_mode == "状态更新"
    assert segments[2].character_reference_segment_indices == (1,)
    assert segments[2].defined_character_indices == (1,)
    assert segments[3].character_generation_mode == "新角色合并"
    assert segments[3].character_reference_segment_indices == (3, 2)
    assert segments[3].defined_character_indices == (1, 2, 3)


def test_parse_segments_accepts_combined_multi_character_board_and_reuse() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:05.000

## A. 人物造型参考板提示词

角色ID：character_01、character_02
生成一张同时包含两位成年普通用户的人物造型参考板。

## B. 故事板图片提示词

故事提示词
### 镜头 1 (00:00.000 - 00:05.000)
[主体] character_01 和 character_02

# Segment 2：00:00.000 - 00:05.000

## A. 人物造型参考板提示词

本段复用 character_01 和 character_02 人物图，不需要重新生成人物造型参考板。

## B. 故事板图片提示词

故事提示词
### 镜头 1 (00:00.000 - 00:05.000)
[主体] character_01 和 character_02
"""
    )

    assert len(segments) == 2
    assert "character_01、character_02" in segments[0].character_prompt
    assert segments[1].reuses_character is True
    assert segments[1].referenced_character_index == 1
    assert segments[1].referenced_character_indices == (1, 2)
    assert segments[0].defined_character_indices == (1, 2)
    assert character_source_segment_index(segments, segments[1]) == 1
    assert "character_01 和 character_02" in segments[1].raw_text


def test_character_source_segment_uses_definition_segment_not_character_number() -> None:
    segments = parse_segments(
        """# Segment 1：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01
生成 character_01 人物造型参考板。
## B. 故事板图片提示词
故事提示词

# Segment 2：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02、character_03
重新生成同时包含 character_01、character_02 和 character_03 的一张合成人物造型参考板。
## B. 故事板图片提示词
故事提示词

# Segment 3：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
本段复用 character_01、character_02、character_03 人物图，不需要重新生成人物造型参考板。
## B. 故事板图片提示词
故事提示词
"""
    )

    assert segments[1].defined_character_indices == (1, 2, 3)
    assert character_source_segment_index(segments, segments[2]) == 2


def test_parse_segments_accepts_unified_omni_downstream_contract() -> None:
    segments = parse_segments(
        """#
## 每段生成提示词

# Segment 1：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成方式：首次生成
参考来源：无
本段首次生成 character_01 与 character_02 的同一张人物造型参考板。
## B. 故事板图片提示词
图1是当前产品参考图，图2是当前 Segment 的人物或特殊主体一致性参考板。
下面是本段镜头脚本（已过滤字段）:
### 镜头 1 (00:00.000 - 00:05.000)
- [主体] character_01 与 character_02
- [在场景中] 普通客厅
- [做什么动作] 展示图1中的该产品
- [镜头语言] 中景
- [光线] 自然光
- [细节] 生活化细节
- [画面风格/氛围] 真实手机实拍
- [音频文案] Hello.

# Segment 2：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：character_01、character_02
生成方式：直接复用
参考来源：Segment 1
本段复用 Segment 1 中已生成的同一张人物造型参考板（包含 character_01 与 character_02），不需要重新生成人物造型参考板。
## B. 故事板图片提示词
图1是当前产品参考图，图2是当前 Segment 复用的人物或特殊主体一致性参考板。
下面是本段镜头脚本（已过滤字段）:
### 镜头 1 (00:00.000 - 00:05.000)
- [主体] character_01 与 character_02
- [在场景中] 相同客厅
- [做什么动作] 继续展示
- [镜头语言] 近景
- [光线] 自然光
- [细节] 外观一致
- [画面风格/氛围] 真实手机实拍
- [音频文案] No voiceover.

# Segment 3：00:00.000 - 00:05.000
## A. 人物造型参考板提示词
角色ID：无
生成方式：无人物场景
参考来源：无
本段无需要保持一致的人物或特殊主体，不分配 character。
生成一张竖版 9:16 的无人物场景一致性参考板。
## B. 故事板图片提示词
图1是当前产品参考图，图2是当前 Segment 的无人物场景一致性参考板。
下面是本段镜头脚本（已过滤字段）:
### 镜头 1 (00:00.000 - 00:05.000)
- [主体] 图1中的该产品
- [在场景中] 无人空镜
- [做什么动作] 产品静置
- [镜头语言] 特写
- [光线] 柔和光
- [细节] 产品外观由图1决定
- [画面风格/氛围] 真实商业带货
- [音频文案] 无人物口播、无旁白、无对白、无歌词。
"""
    )

    assert len(segments) == 3
    assert segments[0].defined_character_indices == (1, 2)
    assert segments[0].character_generation_mode == "首次生成"
    assert segments[1].reuses_character is True
    assert segments[1].character_generation_mode == "直接复用"
    assert segments[1].character_reference_segment_indices == (1,)
    assert segments[1].referenced_character_indices == (1, 2)
    assert character_source_segment_index(segments, segments[1]) == 1
    assert segments[2].character_generation_mode == "无人物场景"
    assert segments[2].defined_character_indices == ()
    expected_fields = [
        "主体",
        "在场景中",
        "做什么动作",
        "镜头语言",
        "光线",
        "细节",
        "画面风格/氛围",
        "音频文案",
    ]
    for segment in segments:
        actual_fields = re.findall(
            r"^- \[([^\]]+)\] ",
            segment.storyboard_prompt,
            flags=re.MULTILINE,
        )
        assert actual_fields == expected_fields
        assert "### 镜头 1" in build_direct_video_prompt(segment)


def test_build_video_prompt_treats_storyboard_as_director_reference_only() -> None:
    segment = parse_segments(SAMPLE)[0]
    prompt = build_video_prompt(segment)

    assert "不是视频首帧，也不是成片画面" in prompt
    assert "严禁在成片中出现、保留或动画化整张故事板" in prompt
    assert "不得从故事板整页开始后再放大、裁切或转场进入镜头" in prompt
    assert "不得省略、合并、重排或新增镜头" in prompt
    assert "### 镜头 1" in prompt
    assert "当前片段完整脚本" in prompt


def test_build_storyboard_image_prompt_replaces_legacy_layout_with_eight_field_sheet() -> None:
    segment = parse_segments(
        """# Segment 1：00:00.000 - 00:02.500

## A. 人物造型参考板提示词

人物提示词

## B. 故事板图片提示词

上方产品参考区占约25%，下方使用纯视觉照片拼贴。

### 镜头 1 (00:00.000 - 00:02.500)

- [主体] character_01
- [在场景中] 普通客厅
- [做什么动作] 拿起产品
- [镜头语言] 中景固定机位
- [光线] 自然光
- [细节] 右手持物
- [画面风格/氛围] 真实手机实拍
- [音频文案] Hello.
"""
    )[0]

    prompt = build_storyboard_image_prompt(segment)

    assert "逐镜头执行单" in prompt
    assert "主体、在场景中、做什么动作、镜头语言、光线、细节、画面风格/氛围、音频文案" in prompt
    assert "### 镜头 1 (00:00.000 - 00:02.500)" in prompt
    assert "- [音频文案] Hello." in prompt
    assert "上方产品参考区占约25%" not in prompt
    assert "纯视觉照片拼贴" not in prompt


def test_build_direct_video_prompt_locks_order_and_references() -> None:
    segment = parse_segments(SAMPLE)[0]
    prompt = build_direct_video_prompt(segment)

    assert "第一张人物参考图" in prompt
    assert "第二张产品参考图" in prompt
    assert "不得省略任何镜头" in prompt
    assert "不得重排镜头顺序" in prompt
    assert "音频与语言控制规则" in prompt
    assert "拍摄设备可见性规则" in prompt
    assert "### 镜头 1" in prompt
    assert "故事提示词 1" not in prompt
    assert "始终使用单一全屏画面" in prompt
    assert "禁止分屏、拼贴、网格、画中画" in prompt
    assert "镜头只能按脚本时间顺序依次切换" in prompt


def test_build_direct_video_prompt_requires_shot_script() -> None:
    segment = parse_segments(SAMPLE)[1]

    with pytest.raises(ValueError, match="未找到镜头脚本"):
        build_direct_video_prompt(segment)


def test_build_product_video_prompt_uses_only_product_reference_and_shot_script() -> None:
    segment = parse_segments(SAMPLE)[0]
    prompt = build_product_video_prompt(segment)

    assert "唯一一张产品参考图" in prompt
    assert "人物、场景和动作只按镜头脚本生成" in prompt
    assert "### 镜头 1" in prompt
    assert "人物提示词 1" not in prompt
    assert "故事提示词 1" not in prompt
    assert "第一张人物参考图" not in prompt
    assert "始终使用单一全屏画面" in prompt
    assert "禁止分屏、拼贴、网格、画中画" in prompt
    assert "镜头只能按脚本时间顺序依次切换" in prompt


def test_build_product_video_prompt_requires_shot_script() -> None:
    segment = parse_segments(SAMPLE)[1]

    with pytest.raises(ValueError, match="未找到镜头脚本"):
        build_product_video_prompt(segment)


def test_build_direct_video_prompt_includes_technical_padding_control() -> None:
    segment = parse_segments(
        """# Segment 1：00:00.000 - 00:07.500
- 原脚本总时长：7.500秒
- 本段有效内容时长：7.500秒
- 有效内容结束：7.500秒
- 技术占位开始：7.500秒
- 技术占位时长：2.500秒
- 模型片段时长：10.000秒
[TECHNICAL_PADDING: BLACK_SILENT]
技术占位为纯黑画面、完全静音、无人物、无产品、无字幕、无贴纸、无动作、无转场内容。

## A. 人物造型参考板提示词
人物提示词

## B. 故事板图片提示词
故事提示词
### 镜头 1 (00:00.000 - 00:07.500)
镜头内容
"""
    )[0]

    prompt = build_direct_video_prompt(segment)

    assert "固定时长技术占位要求（最高优先级）" in prompt
    assert "- 本段有效内容时长：7.500秒" in prompt
    assert "- 技术占位时长：2.500秒" in prompt
    assert "[TECHNICAL_PADDING: BLACK_SILENT]" in prompt
    assert "从“技术占位开始”到“模型片段时长”必须切换为纯黑画面并保持完全静音" in prompt
    assert "禁止通过慢动作、延长停留、重复动作" in prompt
    assert prompt.index("[TECHNICAL_PADDING: BLACK_SILENT]") < prompt.index("### 镜头 1")
