from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent.markdown_parser import build_direct_video_prompt, parse_segments
from assembly import video_assembly as assembly


ROOT = Path(__file__).resolve().parents[2]
UNIFIED_PROMPT = ROOT / "opc_shared" / "prompts" / "unified_script_generation_adaptation_prompt.md"
EXPECTED_FIELDS = [
    "主体",
    "在场景中",
    "做什么动作",
    "镜头语言",
    "光线",
    "细节",
    "画面风格/氛围",
    "音频文案",
    "背景音乐",
]


def _segment(
    index: int,
    end_seconds: float,
    action: str,
    audio: str,
    *,
    padding: str = "",
) -> str:
    if index == 1:
        character_block = """角色ID：character_01
生成方式：首次生成
参考来源：无
本段首次生成 character_01 的人物造型参考板。"""
    else:
        character_block = """角色ID：character_01
生成方式：直接复用
参考来源：Segment 1
本段复用 Segment 1 中已生成的 character_01 人物造型参考板。"""
    end = f"00:{end_seconds:06.3f}"
    padding_block = f"\n{padding.strip()}\n" if padding.strip() else "\n"
    return f"""# Segment {index}：00:00.000 - {end}{padding_block}
## A. 人物造型参考板提示词
{character_block}

## B. 故事板图片提示词
图1是当前产品参考图，图2是当前 Segment 的人物一致性参考板。
下面是本段镜头脚本（已过滤字段）:

### 镜头 1 (00:00.000 - {end})

- [主体] character_01
- [在场景中] 同一普通客厅
- [做什么动作] {action}
- [镜头语言] 中景，保持连续运动方向
- [光线] 同一自然光
- [细节] 人物、产品状态和持物手保持一致
- [画面风格/氛围] 真实手机实拍
- [音频文案] {audio}
- [背景音乐] 无
"""


def _document(segments: list[str]) -> str:
    return "#\n## 每段生成提示词\n\n---\n\n" + "\n---\n\n".join(segments)


def _field_names(storyboard_prompt: str) -> list[str]:
    return re.findall(r"^- \[([^\]]+)\] ", storyboard_prompt, flags=re.MULTILINE)


def test_omni_prompt_locks_sealed_duration_and_audio_rules() -> None:
    prompt = UNIFIED_PROMPT.read_text(encoding="utf-8")
    omni = prompt.split("<!-- OPC_BLOCK:MODEL_OMNI:START -->", 1)[1].split(
        "<!-- OPC_BLOCK:MODEL_OMNI:END -->",
        1,
    )[0]

    assert "30 秒必须是 3 段" in omni
    assert "超过 30 秒且不超过 40 秒为 4 段" in omni
    assert "有效内容总时长必须与原脚本有效内容总时长精确一致" in omni
    assert "原始生成素材时长可以包含系统注入的技术补位" in omni
    assert "必须在前面的内部规范脚本阶段完成" in omni
    assert "不得绕过 `[音频文案]`" in omni
    assert "可提取字幕引号内原文作为口播" not in omni


def test_omni_storyboard_is_a_labeled_shot_sheet_using_nine_fields() -> None:
    prompt = UNIFIED_PROMPT.read_text(encoding="utf-8")
    omni = prompt.split("<!-- OPC_BLOCK:MODEL_OMNI:START -->", 1)[1].split(
        "<!-- OPC_BLOCK:MODEL_OMNI:END -->",
        1,
    )[0]

    assert "逐镜头分镜故事板执行单" in omni
    assert "不得在最终故事板中单独做成产品陈列区" in omni
    assert "代表画面、九字段信息区、镜头编号、起止时间和准确时长" in omni
    assert "不得改成示例图中的“画面内容、动作/景别、构图、拍摄方式、声音、台词”等另一套字段" in omni
    assert "无标注照片拼贴" in omni


def test_omni_30_second_output_is_three_complete_segments() -> None:
    markdown = _document(
        [
            _segment(1, 10.0, "开始连续展示", "First line."),
            _segment(2, 10.0, "继续展示第二部分", "Second line."),
            _segment(3, 10.0, "完成展示", "Third line."),
        ]
    )

    segments = parse_segments(markdown)

    assert len(segments) == 3
    assert [segment.index for segment in segments] == [1, 2, 3]
    assert [segment.time_range for segment in segments] == ["00:00.000 - 00:10.000"] * 3
    assert "[TECHNICAL_PADDING: BLACK_SILENT]" not in markdown
    for segment in segments:
        assert _field_names(segment.storyboard_prompt) == EXPECTED_FIELDS
        assert "### 镜头 1" in build_direct_video_prompt(segment)


def test_omni_31_second_output_keeps_continuity_and_assembles_to_31_seconds() -> None:
    padding = """- 原脚本总时长：31.000秒
- 本段有效内容时长：1.000秒
- 有效内容结束：1.000秒
- 技术占位开始：1.000秒
- 技术占位时长：9.000秒
- 模型片段时长：10.000秒
[TECHNICAL_PADDING: BLACK_SILENT]
技术占位为纯黑画面、完全静音、无人物、无产品、无字幕、无贴纸、无动作、无转场内容。"""
    markdown = _document(
        [
            _segment(1, 10.0, "完成第一段动作", "First line."),
            _segment(2, 10.0, "完成第二段动作", "Second line."),
            _segment(3, 10.0, "开始同一个连续动作，至片段结束时尚未完成", "The action starts."),
            _segment(4, 1.0, "从上一段结束状态继续同一动作并完成", "It ends.", padding=padding),
        ]
    )

    segments = parse_segments(markdown)

    assert len(segments) == 4
    assert [segment.time_range for segment in segments] == [
        "00:00.000 - 00:10.000",
        "00:00.000 - 00:10.000",
        "00:00.000 - 00:10.000",
        "00:00.000 - 00:01.000",
    ]
    assert markdown.count("[TECHNICAL_PADDING: BLACK_SILENT]") == 1
    assert "开始同一个连续动作" in segments[2].storyboard_prompt
    assert "从上一段结束状态继续同一动作" in segments[3].storyboard_prompt
    assert _field_names(segments[3].storyboard_prompt) == EXPECTED_FIELDS
    final_video_prompt = build_direct_video_prompt(segments[3])
    assert "本段有效内容时长：1.000秒" in final_video_prompt
    assert "技术占位时长：9.000秒" in final_video_prompt

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        script_dir = root / "script"
        script_dir.mkdir()
        md_path = script_dir / "script.md"
        md_path.write_text(markdown, encoding="utf-8")
        videos = []
        for index in range(1, 5):
            video = script_dir / f"片段{index}.mp4"
            video.touch()
            videos.append(str(video))
        vendor_root = root / "vendor"
        vendor_root.mkdir()
        (vendor_root / "gsap.min.js").write_text("", encoding="utf-8")
        item = assembly.ScriptItem(
            model="omni",
            date="2026-08-27",
            product="测试产品",
            script_dir=str(script_dir),
            md_path=str(md_path),
            video_paths=videos,
            output_path=str(root / "output.mp4"),
            status="missing",
        )
        with (
            patch.object(assembly, "WORK_ROOT", root / "work"),
            patch.object(assembly, "VENDOR_ROOT", vendor_root),
            patch.object(assembly, "media_duration", return_value=10.0),
            patch.object(assembly, "tail_audio_is_active", return_value=False),
        ):
            _project_dir, clips = assembly.prepare_project(item)

    assert [clip["target_duration"] for clip in clips] == [10.0, 10.0, 10.0, 1.0]
    assert [clip["duration"] for clip in clips] == [10.0, 10.0, 10.0, 1.0]
    assert clips[-1]["action"] == "trim_tail"
    assert sum(clip["duration"] for clip in clips) == 31.0
