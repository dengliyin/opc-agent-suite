# Teardown Output Contract

Use this contract when writing, reviewing, or refining short-video teardown Markdown.

## Required Structure

```markdown
# 视频拆解结果

## 1. Source Summary

- Source:
- Product project:
- Market / language:
- Duration:
- Analysis confidence:

## 2. Full Transcript And Translation

| Timecode | Audio / On-screen text | 中文翻译 | Notes |
| --- | --- | --- | --- |

## 3. Shot-By-Shot Teardown

| Shot ID | 时间码(MM:SS.mmm) | 画面全息描述(景别/运镜/场景/人物动作/贴图) | 原音逐字脚本 | 中文翻译 | 情绪与语调(Tone) |
| --- | --- | --- | --- | --- | --- |

## 4. Conversion Logic

### Audience

### Hook

### Pain / Desire

### Native Look & Trust

### Product Proof

### Offer / Price Anchor

### CTA & End

### Core Truth

## 5. Material Framework

- Matched framework:
- Evidence:
- If new, proposed material type name:

## 6. Reusable SOP

**新素材类型名称：**

### Hook

- Visual:
- Audio:

### Body

- Visual:
- Audio:

### End

- Visual:
- Audio:

### Core

## 7. Downstream Script Notes

- Reuse:
- Localize:
- Avoid:
- Open questions:
```

## Quality Rules

- Cut by real shot transitions or clear scene/action changes, not fixed intervals.
- Use concrete visual language: shot size, camera movement, setting, actor action, props, overlay text, product moment, and editing rhythm.
- Preserve original words when audible. If audio is unclear, mark `听不清` and explain the uncertainty.
- Translate meaning and emotion, not only literal words.
- Keep analysis tied to observed evidence; label inference as inference.
- Use `[product]` for generic product mentions to keep outputs reusable.
- Separate visual structure from copy structure in the SOP section.
- Do not fabricate price, discount, performance data, or claims that are not visible/audible.

## Acceptance Checklist

- The transcript covers audio and important on-screen text.
- The shot table covers the whole video timeline.
- Each shot has a timecode and specific visual description.
- The conversion logic explains why the video might hold attention and convert.
- The framework decision is supported by evidence.
- A new material type includes a reusable Hook, Body, End, and Core.
- The result can be used directly by the script generation workflow.
