from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


SEGMENT_RE = re.compile(r"^#\s*Segment\s+(\d+)\s*[：:]\s*(.*)$", re.MULTILINE)
A_HEADING = "## A. 人物造型参考板提示词"
B_HEADING = "## B. 故事板图片提示词"
A_HEADING_RE = re.compile(r"^#{1,6}\s*A[.．、]\s*人物造型参考板提示词\s*$")
B_HEADING_RE = re.compile(r"^#{1,6}\s*B[.．、]\s*(?:故事板图片提示词|Grok 视频片段提示词)\s*$")

VIDEO_AUDIO_LANGUAGE_GUARD = (
    "音频与语言控制规则：只允许使用脚本中[音频文案]字段明确给出的原文语言和原文内容；"
    "不得翻译、改写、补写、扩写或新增任何未在[音频文案]中出现的人声内容。"
    "当[音频文案]标记为无口播、仅音乐或仅环境声时，必须保持无人物口播、无旁白、无对白、无歌词；"
    "只允许与镜头动作一致的自然环境声。"
    "背景音乐只服从[背景音乐]字段；标记为无时不得生成背景音乐，"
    "标记了音乐氛围时只能生成与描述一致的无版权纯背景音乐，不得使用具体歌曲、歌手或受保护音乐。"
)

CAMERA_VISIBILITY_GUARD = (
    "拍摄设备可见性规则：脚本中的拍摄设备、固定方式和机位摆放只用于定义视角、景别和运动感；"
    "不得把拍摄设备、支撑物、固定物或其倒影作为画面内容生成。"
    "除非[做什么动作]明确要求角色操作拍摄设备，否则所有拍摄设备和支撑物必须保持在画面外。"
)

DIRECT_VIDEO_LAYOUT_GUARD = (
    "画面布局规则：始终使用单一全屏画面。"
    "禁止分屏、拼贴、网格、画中画、故事板版式或同时展示多个镜头。"
    "镜头只能按脚本时间顺序依次切换，任何时刻只能显示当前时间段对应的一个镜头。"
)


@dataclass(frozen=True)
class Segment:
    index: int
    title: str
    time_range: str
    raw_text: str
    character_prompt: str
    storyboard_prompt: str

    @property
    def reuses_character(self) -> bool:
        prompt = self.character_prompt.strip()
        lowered = prompt.lower()
        if "复用" not in prompt or ("character" not in lowered and "人物图" not in prompt):
            return False
        if re.search(r"后续(?:段落|片段|镜头)?[^。；;\n]{0,24}复用", prompt):
            return False
        if "本段首次" in prompt or "首次出现" in prompt:
            return False
        if re.search(
            r"(?:^|[。；;\n])\s*(?:本段|当前片段|此段|本片段)\s*(?:将|继续|直接)?\s*复用",
            prompt,
            re.IGNORECASE,
        ):
            return True
        return bool(
            re.search(
                r"(?:本段|当前片段|此段|本片段)?[^。；;\n]{0,12}复用[^。；;\n]{0,24}(?:character[_-]?0*\d+|人物图)",
                prompt,
                re.IGNORECASE,
            )
        )

    @property
    def referenced_character_index(self) -> Optional[int]:
        indices = _character_indices(self.character_prompt)
        return indices[0] if indices else None

    @property
    def referenced_character_indices(self) -> Tuple[int, ...]:
        if not self.reuses_character:
            return ()
        return _character_indices(self.character_prompt)

    @property
    def character_generation_mode(self) -> str:
        match = re.search(r"^\s*生成方式\s*[：:]\s*(?P<mode>[^\n]+)$", self.character_prompt, re.MULTILINE)
        return match.group("mode").strip() if match else ""

    @property
    def character_reference_segment_indices(self) -> Tuple[int, ...]:
        match = re.search(r"^\s*参考来源\s*[：:]\s*(?P<sources>[^\n]+)$", self.character_prompt, re.MULTILINE)
        if match is None or match.group("sources").strip() == "无":
            return ()
        return tuple(
            dict.fromkeys(
                int(source.group(1))
                for source in re.finditer(r"Segment\s*0*(\d+)", match.group("sources"), re.IGNORECASE)
            )
        )

    @property
    def defined_character_indices(self) -> Tuple[int, ...]:
        prompt = self.character_prompt
        explicit: List[int] = []
        for match in re.finditer(r"角色\s*ID\s*[：:]\s*(?P<ids>[^\n]+)", prompt, re.IGNORECASE):
            explicit.extend(_character_indices(match.group("ids")))
        if explicit:
            return tuple(dict.fromkeys(explicit))
        if not self.reuses_character and re.search(r"本段首次|首次出现|本段生成|标记为", prompt):
            return _character_indices(prompt)
        return ()


def _character_indices(value: str) -> Tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            int(match.group(1))
            for match in re.finditer(r"character[_-]?0*(\d+)", value or "", re.IGNORECASE)
        )
    )


def character_source_segment_index(segments: List[Segment], segment: Segment) -> int:
    if not segment.reuses_character:
        return segment.index
    explicit_sources = segment.character_reference_segment_indices
    if explicit_sources:
        if len(explicit_sources) > 1:
            joined = "、".join(f"片段{index}" for index in explicit_sources)
            raise ValueError(f"直接复用只能读取一张人物参考板，当前指定了 {joined}")
        if explicit_sources[0] >= segment.index:
            raise ValueError(f"人物参考来源必须早于当前片段：Segment {explicit_sources[0]}")
        return explicit_sources[0]
    referenced = segment.referenced_character_indices
    if not referenced:
        return 1

    prior_segments = [candidate for candidate in segments if candidate.index < segment.index]
    source_indices: List[int] = []
    for character_index in referenced:
        source_index = next(
            (
                candidate.index
                for candidate in reversed(prior_segments)
                if character_index in candidate.defined_character_indices
            ),
            None,
        )
        if source_index is None and any(candidate.index == character_index for candidate in prior_segments):
            source_index = character_index
        if source_index is None:
            raise ValueError(f"未找到 character_{character_index:02d} 对应的人物参考板")
        if source_index not in source_indices:
            source_indices.append(source_index)

    if len(source_indices) > 1:
        joined = "、".join(f"片段{index}" for index in source_indices)
        raise ValueError(f"复用角色来自不同人物参考板（{joined}），无法作为一张人物图读取")
    return source_indices[0]


def parse_segments(markdown: str) -> List[Segment]:
    matches = list(SEGMENT_RE.finditer(markdown))
    segments: List[Segment] = []
    for position, match in enumerate(matches):
        block_start = match.start()
        block_end = matches[position + 1].start() if position + 1 < len(matches) else len(markdown)
        block = markdown[block_start:block_end].strip()
        character_prompt, storyboard_prompt = _extract_prompts(block)
        segments.append(
            Segment(
                index=int(match.group(1)),
                title=match.group(0).strip(),
                time_range=match.group(2).strip(),
                raw_text=block,
                character_prompt=character_prompt,
                storyboard_prompt=storyboard_prompt,
            )
        )
    return segments


def _extract_prompts(block: str) -> Tuple[str, str]:
    lines = block.splitlines()
    a_idx: Optional[int] = None
    b_idx: Optional[int] = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if A_HEADING_RE.match(stripped):
            a_idx = idx
        elif B_HEADING_RE.match(stripped):
            b_idx = idx

    if a_idx is None:
        raise ValueError("未找到 A. 人物造型参考板提示词")
    if b_idx is None:
        raise ValueError("未找到 B. 故事板图片提示词 或 B. Grok 视频片段提示词")
    if b_idx <= a_idx:
        raise ValueError("B 提示词标题出现在 A 提示词标题之前")

    character_prompt = "\n".join(lines[a_idx + 1 : b_idx]).strip()
    storyboard_prompt = "\n".join(lines[b_idx + 1 :]).strip()
    return character_prompt, storyboard_prompt


def _ensure_background_music_field(value: str) -> str:
    """Keep existing eight-field adaptations usable by treating missing BGM as none."""
    blocks = re.split(r"(?=^#{1,6}\s*镜头\s*\d+\b)", str(value or ""), flags=re.MULTILINE)
    normalized: List[str] = []
    for block in blocks:
        if not re.match(r"^#{1,6}\s*镜头\s*\d+\b", block) or re.search(r"\[背景音乐\]", block):
            normalized.append(block)
            continue
        def add_background_music(match: re.Match[str]) -> str:
            audio = match.group("audio")
            background_music = "无版权音乐氛围" if re.search(r"仅音乐|仅保留背景音乐|背景音乐|\bBGM\b", audio, re.IGNORECASE) else "无"
            return f"{audio}\n- [背景音乐] {background_music}"

        block = re.sub(
            r"(?m)^(?P<audio>\s*[-*]\s*(?:\*\*)?\[音频文案\](?:\*\*)?\s*[：:]?.*)$",
            add_background_music,
            block,
            count=1,
        )
        normalized.append(block)
    return "".join(normalized)


def build_storyboard_image_prompt(segment: Segment) -> str:
    shot_match = re.search(r"^#{1,6}\s*镜头\s*\d+\b.*$", segment.storyboard_prompt, re.MULTILINE)
    if shot_match is None:
        raise ValueError(f"片段{segment.index}未找到镜头脚本，无法生成故事版图")
    shot_script = _ensure_background_music_field(segment.storyboard_prompt[shot_match.start() :].strip())
    return (
        f"生成一张竖版9:16的《Segment {segment.index}｜分镜故事板》逐镜头执行单。"
        f"本段时间为{segment.time_range}。输入图1只用于锁定产品外观；输入图2只用于锁定人物、特殊主体或场景一致性；"
        "两张参考图不得在成品中单独做成产品陈列区、人物陈列区或参考图展示区。"
        "页面顶部使用简洁标题栏；下方按时间顺序从上到下排列镜头行，镜头行数量必须与脚本完全一致。"
        "每个镜头行左侧为该镜头最有代表性的单一画面，右侧为白底信息区，最右侧为时长色条；"
        "左上角显示两位镜头编号，信息区显示完整起止时间，时长色条显示由起止时间计算出的准确时长。"
        "白底信息区必须严格按脚本原文依次显示九个字段：主体、在场景中、做什么动作、镜头语言、光线、细节、画面风格/氛围、音频文案、背景音乐。"
        "不得改名、合并、删减、增加或自行推断字段，也不得改成画面内容、动作/景别、构图、拍摄方式、声音、台词等另一套结构。"
        "九字段允许换行但不得截断；音频文案和背景音乐只显示在白底信息区，不得叠加到镜头画面中成为字幕或贴纸。"
        "每个镜头画面只表现一个代表性瞬间，不得使用无标注照片拼贴、九宫格、分屏、画中画、动作阶段拼贴、产品目录或促销信息图。"
        "保持相邻镜头的人物、产品、场景、持物手、光线、相对位置和运动方向连续。"
        "仅在脚本明确要求产品出镜的镜头中显示产品，产品外观必须与输入图1一致。\n\n"
        "当前片段镜头脚本：\n"
        f"{shot_script}"
    )


def build_video_prompt(segment: Segment) -> str:
    normalized_script = _ensure_background_music_field(segment.raw_text)
    return (
        "输入图片是一张导演使用的分镜故事板执行单，只用于理解镜头画面和镜头顺序，不是视频首帧，也不是成片画面。"
        "成片必须从00:00直接进入镜头1左侧代表画面，并按脚本时间依次切换为单一9:16全屏镜头。"
        "严禁在成片中出现、保留或动画化整张故事板、标题栏、白底信息区、文字、镜头编号、时间、时长色条、边框、多格排版或表格；"
        "不得从故事板整页开始后再放大、裁切或转场进入镜头。"
        "严格按照下面完整脚本中的镜头数量、起止时间、主体、场景、动作、镜头语言、光线、细节、画面风格、音频文案和背景音乐执行；"
        "不得省略、合并、重排或新增镜头。"
        "相邻镜头保持人物、产品、场景状态和动作衔接一致。"
        "音频文案只作为人声内容和节奏依据，背景音乐只作为声音轨要求；两者都不得生成字幕、贴纸或其他画面文字。"
        f"{VIDEO_AUDIO_LANGUAGE_GUARD}"
        f"{CAMERA_VISIBILITY_GUARD}"
        f"{DIRECT_VIDEO_LAYOUT_GUARD}"
        "画面自然真实，适合竖屏短视频带货。\n\n"
        "当前片段完整脚本如下：\n"
        f"{normalized_script}"
    )


def build_direct_video_prompt(segment: Segment) -> str:
    shot_match = re.search(r"^#{1,6}\s*镜头\s*\d+\b.*$", segment.raw_text, re.MULTILINE)
    if shot_match is None:
        raise ValueError(f"片段{segment.index}未找到镜头脚本，无法运行功能4")
    shot_script = _ensure_background_music_field(segment.raw_text[shot_match.start() :].strip())
    technical_padding = _technical_padding_control(segment.raw_text)
    technical_padding_prompt = ""
    if technical_padding:
        technical_padding_prompt = (
            "\n固定时长技术占位要求（最高优先级）：\n"
            f"{technical_padding}\n"
            "只允许在“本段有效内容时长”内执行下面的镜头脚本；"
            "从“技术占位开始”到“模型片段时长”必须切换为纯黑画面并保持完全静音，"
            "不得出现人物、产品、字幕、贴纸、动作或转场内容。"
            "禁止通过慢动作、延长停留、重复动作、补充台词、增加空镜或新增剧情延长有效内容。\n"
        )
    return (
        "请根据第一张人物参考图、第二张产品参考图和当前片段镜头脚本，直接生成一段真实商业带货短视频片段。"
        "第一张参考图用于锁定人物外观、年龄、肤色、发型、脸部特征和整体气质；"
        "第二张参考图用于强制锁定产品外观、颜色、结构、包装、Logo、标签和可见文字。"
        "必须严格按脚本中每个镜头的时间段、画面内容、人物动作、产品露出方式和镜头语言执行；"
        "不得省略任何镜头，不得重排镜头顺序，不得合并镜头，不得新增与脚本冲突的镜头。"
        "音频文案只作为镜头节奏和语境参考，不要生成字幕、贴纸或画面文字。"
        f"{VIDEO_AUDIO_LANGUAGE_GUARD}"
        f"{CAMERA_VISIBILITY_GUARD}"
        f"{DIRECT_VIDEO_LAYOUT_GUARD}"
        "画面自然真实，适合竖屏短视频带货。"
        f"{technical_padding_prompt}\n"
        "当前片段镜头脚本如下：\n"
        f"{shot_script}"
    )


def build_product_video_prompt(segment: Segment) -> str:
    shot_match = re.search(r"^#{1,6}\s*镜头\s*\d+\b.*$", segment.raw_text, re.MULTILINE)
    if shot_match is None:
        raise ValueError(f"片段{segment.index}未找到镜头脚本，无法运行功能5极速模式")
    shot_script = _ensure_background_music_field(segment.raw_text[shot_match.start() :].strip())
    technical_padding = _technical_padding_control(segment.raw_text)
    technical_padding_prompt = ""
    if technical_padding:
        technical_padding_prompt = (
            "\n固定时长技术占位要求（最高优先级）：\n"
            f"{technical_padding}\n"
            "只允许在“本段有效内容时长”内执行下面的镜头脚本；"
            "从“技术占位开始”到“模型片段时长”必须切换为纯黑画面并保持完全静音，"
            "不得出现人物、产品、字幕、贴纸、动作或转场内容。"
            "禁止通过慢动作、延长停留、重复动作、补充台词、增加空镜或新增剧情延长有效内容。\n"
        )
    return (
        "请根据唯一一张产品参考图和当前片段镜头脚本，直接生成一段真实商业带货短视频片段。"
        "参考图仅用于强制锁定产品外观、颜色、结构、包装、Logo、标签和可见文字；"
        "人物、场景和动作只按镜头脚本生成，不要把产品参考图中的背景、构图或展示方式当作首帧。"
        "必须严格按脚本中每个镜头的时间段、画面内容、人物动作、产品露出方式和镜头语言执行；"
        "不得省略任何镜头，不得重排镜头顺序，不得合并镜头，不得新增与脚本冲突的镜头。"
        "音频文案只作为镜头节奏和语境参考，不要生成字幕、贴纸或画面文字。"
        f"{VIDEO_AUDIO_LANGUAGE_GUARD}"
        f"{CAMERA_VISIBILITY_GUARD}"
        f"{DIRECT_VIDEO_LAYOUT_GUARD}"
        "画面自然真实，适合竖屏短视频带货。"
        f"{technical_padding_prompt}\n"
        "当前片段镜头脚本如下：\n"
        f"{shot_script}"
    )


def _technical_padding_control(raw_text: str) -> str:
    lines: List[str] = []
    field_labels = (
        "原脚本总时长",
        "本段有效内容时长",
        "有效内容结束",
        "技术占位开始",
        "技术占位时长",
        "模型片段时长",
    )
    marker_found = False
    for line in str(raw_text or "").splitlines():
        stripped = line.strip()
        if A_HEADING_RE.match(stripped):
            break
        if any(re.match(rf"^-?\s*{re.escape(label)}[：:]", stripped) for label in field_labels):
            lines.append(stripped)
        elif stripped == "[TECHNICAL_PADDING: BLACK_SILENT]":
            lines.append(stripped)
            marker_found = True
        elif stripped.startswith("技术占位为纯黑画面"):
            lines.append(stripped)
    return "\n".join(lines) if marker_found else ""
