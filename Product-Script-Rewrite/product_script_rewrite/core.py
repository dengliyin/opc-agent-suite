from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "agent_config"
SETTINGS_PATH = CONFIG_DIR / "agent_settings.json"
SECRETS_PATH = CONFIG_DIR / "agent_secrets.local.json"


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是 JSON object: {path}")
    return data


def load_config() -> dict[str, Any]:
    settings = read_json_object(SETTINGS_PATH)
    config: dict[str, Any] = {}
    for section in ("model", "paths", "files"):
        values = settings.get(section, {})
        if isinstance(values, dict):
            config.update({key: value for key, value in values.items() if not key.startswith("_")})
    secrets = read_json_object(SECRETS_PATH)
    config.update({key: value for key, value in secrets.items() if value and not key.startswith("_")})
    return config


def config_path(config: dict[str, Any], key: str) -> Path:
    value = os.path.expandvars(str(config.get(key) or "").strip())
    if not value:
        raise ValueError(f"配置缺少路径: {key}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def hot_scripts_root(config: dict[str, Any]) -> Path:
    return config_path(config, "hot_scripts_root")


def product_info_root(config: dict[str, Any]) -> Path:
    return config_path(config, "product_info_root")


def prompt_path(config: dict[str, Any]) -> Path:
    return config_path(config, "rewrite_prompt_path")


def get_api_key(config: dict[str, Any]) -> str:
    return str(
        config.get("deepseek_api_key")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("MODELMESH_API_KEY")
        or ""
    ).strip()


def product_info_path(config: dict[str, Any], product: str) -> Path:
    name = validate_product_name(config, product)
    return product_info_root(config) / f"{name}-产品信息.md"


def list_products(config: dict[str, Any]) -> list[dict[str, Any]]:
    scripts_root = hot_scripts_root(config)
    info_root = product_info_root(config)
    names: set[str] = set()
    if scripts_root.exists():
        names.update(path.name for path in scripts_root.iterdir() if path.is_dir() and not path.name.startswith("."))
    if info_root.exists():
        for path in info_root.glob("*-产品信息.md"):
            if not path.name.startswith("_"):
                names.add(path.name[: -len("-产品信息.md")])
    products: list[dict[str, Any]] = []
    for name in sorted(names):
        folder = scripts_root / name
        info = info_root / f"{name}-产品信息.md"
        products.append(
            {
                "name": name,
                "script_count": len(list(folder.glob("*.md"))) if folder.is_dir() else 0,
                "has_product_info": info.is_file(),
            }
        )
    return products


def validate_product_name(config: dict[str, Any], product: str) -> str:
    name = str(product or "").strip()
    known = {item["name"] for item in list_products(config)}
    if not name or name not in known:
        raise ValueError(f"未知产品: {name or '未选择'}")
    return name


def script_product(config: dict[str, Any], source_path: str | Path) -> tuple[Path, str]:
    root = hot_scripts_root(config)
    path = Path(source_path).expanduser().resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("来源脚本不在爆款视频脚本目录内") from exc
    if len(relative.parts) != 2 or path.suffix.lower() != ".md" or not path.is_file():
        raise ValueError("来源脚本必须是产品子文件夹内的 Markdown 文件")
    return path, relative.parts[0]


def list_scripts(config: dict[str, Any], product: str) -> list[dict[str, Any]]:
    name = validate_product_name(config, product)
    folder = hot_scripts_root(config) / name
    scripts = []
    if folder.is_dir():
        for path in folder.glob("*.md"):
            stat = path.stat()
            scripts.append(
                {
                    "name": path.name,
                    "path": path.as_posix(),
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    "rewritten": bool(re.search(r"（原[^）]+）", path.stem)),
                }
            )
    scripts.sort(key=lambda item: item["name"].lower())
    return scripts


def rewritten_filename(source_name: str, source_product: str) -> str:
    source = Path(source_name)
    if source.suffix.lower() != ".md":
        raise ValueError("来源脚本必须是 .md 文件")
    match = re.search(r"-(?=\d{10,}(?:-|$))", source.stem)
    if not match:
        raise ValueError("文件名中未找到视频 ID，无法按约定生成改写文件名")
    head = re.sub(r"（原[^）]+）$", "", source.stem[: match.start()])
    tail = source.stem[match.start() :]
    return f"{head}（原{source_product}）{tail}.md"


def rewrite_source_identity(filename: str) -> str:
    normalized = unicodedata.normalize("NFC", Path(filename).name)
    path = Path(normalized)
    stem = re.sub(r"（原[^）]+）(?=-\d{10,}(?:-|$))", "", path.stem)
    return f"{stem}{path.suffix.lower()}"


def rewrite_origin_product(filename: str) -> str:
    normalized = unicodedata.normalize("NFC", Path(filename).name)
    match = re.search(r"（原(?P<product>[^）]+)）(?=-\d{10,}(?:-|$))", Path(normalized).stem)
    return match.group("product").strip() if match else ""


def product_marker_matches(source_product: str, marker: str) -> bool:
    source_key = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", source_product).casefold())
    marker_key = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", marker).casefold())
    if not source_key or not marker_key:
        return False
    if marker_key == source_key:
        return True
    has_meaningful_length = len(marker_key) >= 4 or len(re.findall(r"[\u3400-\u9fff]", marker_key)) >= 2
    return has_meaningful_length and marker_key in source_key


def output_path_for(config: dict[str, Any], source_path: str | Path, target_product: str) -> Path:
    source, source_product = script_product(config, source_path)
    target = validate_product_name(config, target_product)
    if source_product == target:
        raise ValueError("来源产品与目标产品不能相同")
    if not product_info_path(config, target).is_file():
        raise ValueError(f"目标产品缺少产品信息文件: {target}-产品信息.md")
    return hot_scripts_root(config) / target / rewritten_filename(source.name, source_product)


def matching_rewrite_outputs(
    config: dict[str, Any], source_path: str | Path, target_product: str
) -> list[Path]:
    source, source_product = script_product(config, source_path)
    canonical = output_path_for(config, source, target_product)
    identity = rewrite_source_identity(source.name)
    matches = [
        path
        for path in canonical.parent.glob("*.md")
        if rewrite_source_identity(path.name) == identity
        and product_marker_matches(source_product, rewrite_origin_product(path.name))
    ]
    matches.sort(
        key=lambda path: (
            path != canonical,
            -path.stat().st_mtime,
            unicodedata.normalize("NFC", path.name).casefold(),
        )
    )
    return matches


def build_prompt(config: dict[str, Any], source_path: str | Path, target_product: str) -> str:
    source, source_product = script_product(config, source_path)
    target = validate_product_name(config, target_product)
    template = prompt_path(config).read_text(encoding="utf-8")
    source_text = source.read_text(encoding="utf-8", errors="ignore")
    replacements = {
        "{{SOURCE_PRODUCT}}": source_product,
        "{{TARGET_PRODUCT}}": target,
        "{{SOURCE_FILENAME}}": source.name,
        "{{SOURCE_SCRIPT}}": source_text,
        "{{SOURCE_STRUCTURE}}": markdown_structure_checklist(source_text),
        "{{SHOT_AUDIO_BUDGETS}}": speech_budget_checklist(source_text),
        "{{SHOT_DISTRIBUTION_RULE}}": shot_distribution_rule(source_text),
        "{{TARGET_PRODUCT_INFO}}": product_info_path(config, target).read_text(encoding="utf-8", errors="ignore"),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def clean_model_markdown(text: str) -> str:
    content = str(text or "").strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(?P<body>.*)\n```", content, flags=re.S | re.I)
    return fenced.group("body").strip() if fenced else content


def markdown_structure_markers(text: str) -> list[str]:
    first_shot = re.search(r"(?m)^#{1,6}\s+镜头\s*\d+\s*\(", text)
    if first_shot:
        text = text[first_shot.start() :]
    markers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading:
            title = heading.group(2)
            if re.match(r"镜头\s*\d+\s*\(", title):
                markers.append(f"shot:{stripped}")
            else:
                markers.append(f"heading-level:{len(heading.group(1))}")
            continue
        if stripped == "---":
            markers.append("separator:---")
            continue
        field_labels = re.findall(r"\*\*(\[[^\]]+\]|【[^】]+】)\*\*", stripped)
        is_list_item = bool(re.match(r"^[-*+]\s+", stripped))
        for label in field_labels:
            markers.append(f"field:{'list' if is_list_item else 'block'}:{label}")
    return markers


def markdown_structure_checklist(text: str) -> str:
    lines: list[str] = []
    for index, marker in enumerate(markdown_structure_markers(text), start=1):
        if marker.startswith("shot:"):
            value = marker.removeprefix("shot:")
        elif marker.startswith("field:list:"):
            value = f"- **{marker.removeprefix('field:list:')}**"
        elif marker.startswith("field:block:"):
            value = f"**{marker.removeprefix('field:block:')}**"
        elif marker == "separator:---":
            value = "---"
        else:
            value = marker
        lines.append(f"{index}. `{value}`")
    return "\n".join(lines)


def markdown_field_contents(text: str, field_name: str) -> list[str]:
    pattern = re.compile(
        rf"(?ms)^\s*(?:[-*+]\s+)?\*\*\[{re.escape(field_name)}\]\*\*\s*(?P<body>.*?)"
        r"(?=^\s*(?:[-*+]\s+)?\*\*\[[^\]]+\]\*\*|^---\s*$|^#{1,6}\s+|\Z)"
    )
    return [re.sub(r"\s+", " ", match.group("body")).strip() for match in pattern.finditer(text)]


def rewrite_comparison_value(value: str) -> str:
    text = re.sub(r"[（(]\s*中文翻译对照[：:].*?[）)]", "", value)
    return re.sub(r"\s+", " ", text).strip()


def subtitle_is_absent(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", rewrite_comparison_value(value)).casefold()
    normalized = re.sub(r"[\s:：。.!！,，;；'\"“”`*_\[\]【】()（）]+", "", normalized)
    return normalized in {"无", "无字幕", "none", "na", "notapplicable", "sinsubtítulos", "sinsubtitulos"}


def parse_timestamp_seconds(value: str) -> float | None:
    try:
        parts = [float(part) for part in value.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def shot_durations_seconds(text: str) -> list[float]:
    durations: list[float] = []
    for match in re.finditer(
        r"(?m)^#{1,6}\s+镜头\s*\d+\s*\((?P<start>\d+(?::\d+){1,2}(?:\.\d+)?)\s*-\s*(?P<end>\d+(?::\d+){1,2}(?:\.\d+)?)\)",
        text,
    ):
        start = parse_timestamp_seconds(match.group("start"))
        end = parse_timestamp_seconds(match.group("end"))
        if start is not None and end is not None and end > start:
            durations.append(end - start)
    return durations


def speech_budget_checklist(text: str) -> str:
    durations = shot_durations_seconds(text)
    audio_blocks = markdown_field_contents(text, "音频文案")
    if len(durations) != len(audio_blocks):
        return "- 无法解析逐镜头预算；仍须按拉丁语系每秒最多 4 词、中文每秒最多 6 字执行。"
    lines: list[str] = []
    for index, (duration, audio) in enumerate(zip(durations, audio_blocks), start=1):
        spoken = rewrite_comparison_value(audio)
        latin_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*", spoken)
        cjk_chars = re.findall(r"[\u3400-\u9fff]", spoken)
        if len(latin_words) >= 3:
            hard_limit = max(4, math.ceil(duration * 4))
            writing_limit = max(1, min(hard_limit, math.floor(duration * 3.5)))
            lines.append(
                f"- 镜头 {index}：{duration:.1f} 秒；实际生成最多 {writing_limit} 个拉丁语系词，"
                f"校验硬上限 {hard_limit} 个词；来源口播 {len(latin_words)} 个词。"
            )
        elif cjk_chars:
            hard_limit = max(6, math.ceil(duration * 6))
            writing_limit = max(1, min(hard_limit, math.floor(duration * 5)))
            lines.append(
                f"- 镜头 {index}：{duration:.1f} 秒；实际生成最多 {writing_limit} 个汉字，"
                f"校验硬上限 {hard_limit} 个汉字；来源口播 {len(cjk_chars)} 个汉字。"
            )
        else:
            lines.append(f"- 镜头 {index}：来源无可识别口播，输出继续保持无口播。")
    return "\n".join(lines)


def shot_distribution_rule(text: str) -> str:
    shot_count = len(shot_durations_seconds(text))
    if shot_count == 2:
        return "本脚本只有 2 个镜头，因此两个镜头都必须各自包含至少 1 个不同的、由目标产品信息确认的非价格核心卖点。"
    return f"本脚本共有 {shot_count} 个镜头；至少 2 个不同镜头必须各自包含不同的、由目标产品信息确认的非价格核心卖点。"


def speech_duration_issues(text: str) -> list[str]:
    durations = shot_durations_seconds(text)
    audio_blocks = markdown_field_contents(text, "音频文案")
    issues: list[str] = []
    if len(durations) != len(audio_blocks):
        return issues
    for index, (duration, audio) in enumerate(zip(durations, audio_blocks), start=1):
        spoken = rewrite_comparison_value(audio)
        latin_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)*", spoken)
        cjk_chars = re.findall(r"[\u3400-\u9fff]", spoken)
        if len(latin_words) >= 3:
            limit = max(4, math.ceil(duration * 4))
            if len(latin_words) > limit:
                issues.append(f"镜头 {index} 口播超时风险：{duration:.1f} 秒内有 {len(latin_words)} 个词，上限约 {limit} 个")
        elif cjk_chars:
            limit = max(6, math.ceil(duration * 6))
            if len(cjk_chars) > limit:
                issues.append(f"镜头 {index} 口播超时风险：{duration:.1f} 秒内有 {len(cjk_chars)} 个汉字，上限约 {limit} 个")
    return issues


def unsupported_marketing_claim_issues(output_text: str, target_product_info: str) -> list[str]:
    if not target_product_info.strip():
        return []
    urgency_output = re.compile(
        r"(?i)(?:限时|最后\s*\d*\s*(?:小时|天)|即将下架|库存紧张|"
        r"por\s+tiempo\s+limitado|últimas?\s+horas?|antes\s+de\s+que\s+(?:lo|la|los|las)\s+(?:corrijan?|quiten?)|"
        r"a\s+medianoche|limited\s+time|last\s+chance|while\s+stocks?\s+last|"
        r"offre\s+limitée|dernières?\s+heures?|tempo\s+limitato|ultime\s+ore)"
    )
    urgency_evidence = re.compile(
        r"(?i)(?:限时|截止(?:时间|日期)?|倒计时|最后\s*\d*\s*(?:小时|天)|库存(?:仅剩|紧张)|"
        r"por\s+tiempo\s+limitado|últimas?\s+horas?|limited\s+time|last\s+chance|"
        r"offre\s+limitée|dernières?\s+heures?|tempo\s+limitato|ultime\s+ore)"
    )
    if urgency_output.search(output_text) and not urgency_evidence.search(target_product_info):
        return ["目标产品信息未提供限时、下架或库存依据，输出却包含无依据的紧迫性表达"]
    return []


def cross_shot_continuity_issues(text: str) -> list[str]:
    audio_blocks = markdown_field_contents(text, "音频文案")
    issues: list[str] = []
    for index, (current, following) in enumerate(zip(audio_blocks, audio_blocks[1:]), start=1):
        current_text = rewrite_comparison_value(current).strip(' "“”')
        if not re.search(r"(?:\.{3}|…)$", current_text):
            continue
        unfinished = re.sub(r"(?:\.{3}|…)$", "", current_text).strip()
        last_clause = re.split(r"[.!?。！？]\s*", unfinished)[-1].strip().lower()
        hanging = bool(
            re.match(r"^(si|porque|pero|cuando|aunque|que|y|if|because|but|when|although|that|and)\b", last_clause)
            or re.match(r"^(如果|因为|但是|当|虽然|而且|只要|除非)", last_clause)
        )
        if not hanging:
            continue
        next_text = rewrite_comparison_value(following).lstrip(' "“”')
        continuation = bool(
            re.match(r"^(?:\.{3}|…)", next_text)
            or re.match(r"(?i)^(entonces|pues|así que|y|hoy|ahora|then|so|and|today|now)\b", next_text)
            or re.match(r"^(那么|所以|于是|而且|今天|现在)", next_text)
        )
        if not continuation:
            issues.append(f"镜头 {index} 到镜头 {index + 1} 口播衔接不完整：前句以未完成条件/连接句结束，后句没有承接")
    return issues


def validate_rewrite(source_text: str, output_text: str, target_product_info: str = "") -> list[str]:
    issues: list[str] = []
    if not output_text.strip():
        return ["模型返回内容为空"]
    source_shots = len(re.findall(r"(?m)^#{2,4}\s*镜头\s*\d+", source_text))
    output_shots = len(re.findall(r"(?m)^#{2,4}\s*镜头\s*\d+", output_text))
    if source_shots and output_shots != source_shots:
        issues.append(f"镜头数量不一致：来源 {source_shots}，输出 {output_shots}")
    source_markers = markdown_structure_markers(source_text)
    output_markers = markdown_structure_markers(output_text)
    if source_markers != output_markers:
        mismatch = next(
            (
                index
                for index, (source_marker, output_marker) in enumerate(zip(source_markers, output_markers), start=1)
                if source_marker != output_marker
            ),
            min(len(source_markers), len(output_markers)) + 1,
        )
        expected = source_markers[mismatch - 1] if mismatch <= len(source_markers) else "结构结束"
        actual = output_markers[mismatch - 1] if mismatch <= len(output_markers) else "结构结束"
        issues.append(f"Markdown 结构不一致：第 {mismatch} 个结构标记应为 {expected}，实际为 {actual}")
    source_audio = markdown_field_contents(source_text, "音频文案")
    output_audio = markdown_field_contents(output_text, "音频文案")
    if source_audio and len(source_audio) == len(output_audio):
        changed_audio = [
            index
            for index, values in enumerate(zip(source_audio, output_audio))
            if rewrite_comparison_value(values[0]) != rewrite_comparison_value(values[1])
        ]
        minimum_changed = (len(source_audio) + 1) // 2
        if len(changed_audio) < minimum_changed:
            issues.append(
                f"产品改写不足：{len(source_audio)} 个音频文案仅实质改写 {len(changed_audio)} 个，至少需要 {minimum_changed} 个"
            )
        source_subtitles = markdown_field_contents(source_text, "字幕")
        output_subtitles = markdown_field_contents(output_text, "字幕")
        if len(source_subtitles) == len(output_subtitles) == len(source_audio):
            stale_subtitles = [
                index + 1
                for index in changed_audio
                if not subtitle_is_absent(source_subtitles[index])
                if rewrite_comparison_value(source_subtitles[index]) == rewrite_comparison_value(output_subtitles[index])
            ]
            if stale_subtitles:
                issues.append(f"音频已改写但字幕未同步：镜头 {stale_subtitles}")
            missing_subtitles = [
                index + 1
                for index in changed_audio
                if not subtitle_is_absent(source_subtitles[index]) and subtitle_is_absent(output_subtitles[index])
            ]
            if missing_subtitles:
                issues.append(f"音频已改写但字幕缺失：镜头 {missing_subtitles}")
    issues.extend(speech_duration_issues(output_text))
    issues.extend(cross_shot_continuity_issues(output_text))
    issues.extend(unsupported_marketing_claim_issues(output_text, target_product_info))
    if "```" in output_text:
        issues.append("输出仍包含 Markdown 代码围栏")
    return issues


def call_deepseek(prompt: str, config: dict[str, Any]) -> str:
    api_key = get_api_key(config)
    if not api_key:
        raise ValueError("缺少 DeepSeek API Key")
    base_url = str(config.get("deepseek_base_url") or "https://api.deepseek.com").strip().rstrip("/")
    model = str(config.get("deepseek_model") or "deepseek-v4-pro").strip()
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.35,
            "max_tokens": int(config.get("max_output_tokens") or 32768),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        raise RuntimeError(f"DeepSeek 请求失败（HTTP {exc.code}）：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek 请求失败：{exc.reason}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek 响应缺少 choices")
    return str((choices[0].get("message") or {}).get("content") or "")


def run_rewrite(
    source_path: str | Path,
    target_product: str,
    log: Callable[[str], None] | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    config = config or load_config()
    source, source_product = script_product(config, source_path)
    output = output_path_for(config, source, target_product)
    previous_outputs = matching_rewrite_outputs(config, source, target_product)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_text = source.read_text(encoding="utf-8", errors="ignore")
    target_info_text = product_info_path(config, target_product).read_text(encoding="utf-8", errors="ignore")
    if log:
        if previous_outputs:
            log(f"检测到已有改写结果 {len(previous_outputs)} 份；新版校验通过后覆盖并仅保留一份")
        log(f"调用 DeepSeek：{source_product} -> {target_product}")
    result = clean_model_markdown(call_deepseek(build_prompt(config, source, target_product), config))
    issues = validate_rewrite(source_text, result, target_info_text)
    if issues:
        detail = "；".join(issues)
        if log:
            log(f"质量校验未通过，未写入且不自动重试: {detail}")
        raise RuntimeError(f"模型首版输出未通过质量校验（未写入且不自动重试）: {detail}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(result.rstrip() + "\n", encoding="utf-8")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    removed = 0
    for previous in previous_outputs:
        if previous != output and previous.exists():
            previous.unlink()
            removed += 1
    if log:
        action = "已覆盖" if previous_outputs else "已写入"
        log(f"{action}: {output}")
        if removed:
            log(f"已清理同一来源脚本的旧重复文件: {removed} 份")
    return output
