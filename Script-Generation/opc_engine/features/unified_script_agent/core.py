from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from opc_shared.global_ai import load_profile
from opc_shared.vault_snapshot import cached_or_empty, refresh_snapshot

from opc_engine.features.script_generation.generate_product_script import (
    COUNTRY_FILENAME_CODE,
    call_text_model,
    compact_product_fact_card,
    reference_country_author_and_video_id,
    safe_output_name,
)


PROMPT_FILENAME = "unified_script_generation_adaptation_prompt.md"
PROMPT_BLOCK_RE = re.compile(
    r"<!--\s*OPC_BLOCK:(?P<name>[A-Z_]+):START\s*-->\s*"
    r"(?P<body>.*?)"
    r"\s*<!--\s*OPC_BLOCK:(?P=name):END\s*-->",
    re.DOTALL,
)
OUTER_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*$", re.DOTALL | re.IGNORECASE)
SEGMENT_RE = re.compile(r"(?m)^#\s*Segment\s+(?P<number>\d+)\s*[：:]\s*(?P<range>.+?)\s*$")
SHOT_RE = re.compile(
    r"(?m)^###\s*镜头\s+(?P<number>\d+)\s*\("
    r"(?P<start>\d{2}:\d{2}\.\d{3})\s*-\s*(?P<end>\d{2}:\d{2}\.\d{3})\)\s*$"
)
FIELD_RE = re.compile(r"(?m)^- \[(?P<name>[^\]]+)\]\s+(?P<value>\S.*)$")
OMNI_FIELDS = (
    "主体",
    "在场景中",
    "做什么动作",
    "镜头语言",
    "光线",
    "细节",
    "画面风格/氛围",
    "音频文案",
    "背景音乐",
)
COUNTRY_LANGUAGES = {
    "US": "英语（美式）",
    "UK": "英语（英式）",
    "GB": "英语（英式）",
    "IE": "英语（爱尔兰）",
    "FR": "法语",
    "ES": "西班牙语",
    "DE": "德语",
    "IT": "意大利语",
    "BR": "葡萄牙语（巴西）",
    "MX": "西班牙语（墨西哥）",
    "MY": "马来语",
    "ID": "印度尼西亚语",
    "PH": "菲律宾语",
    "VN": "越南语",
    "TH": "泰语",
    "BD": "孟加拉语",
    "NP": "尼泊尔语",
    "CA": "英语",
    "AU": "英语（澳大利亚）",
}
ROUTE_LABELS = {
    "route1": "线路 1 · 爆款复刻",
    "route2": "线路 2 · 产品脚本改写",
    "route3": "线路 3 · AI＋实拍混剪",
}
MODE_LABELS = {"clone": "复刻", "mutation": "裂变"}
MODEL_LABELS = {"omni": "Omni"}
_HISTORY_LOCK = threading.RLock()


@dataclass(frozen=True)
class StoragePaths:
    vault_root: Path
    pure_source_root: Path
    pure_generation_root: Path
    pure_output_root: Path
    hybrid_source_root: Path
    hybrid_generation_root: Path
    hybrid_output_root: Path
    product_info_root: Path
    mistake_book_root: Path
    prompt_path: Path
    data_root: Path


def storage_paths() -> StoragePaths:
    vault = Path(os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__").expanduser()
    prompt_default = Path(__file__).resolve().parents[4] / "opc_shared" / "prompts" / PROMPT_FILENAME
    return StoragePaths(
        vault_root=vault,
        pure_source_root=Path(
            os.environ.get("VIDEO_TEARDOWN_OUTPUT_ROOT", vault / "wiki/视频/纯AI视频/02参考脚本")
        ).expanduser(),
        pure_generation_root=Path(
            os.environ.get("PRODUCT_SCRIPT_ROOT", vault / "wiki/视频/纯AI视频/03产品脚本")
        ).expanduser(),
        pure_output_root=Path(
            os.environ.get("SCRIPT_ROOT", vault / "wiki/视频/纯AI视频/04适配脚本/omni")
        ).expanduser(),
        hybrid_source_root=Path(
            os.environ.get("HYBRID_SCRIPT_GENERATION_INPUT_ROOT", vault / "wiki/视频/AI实拍混剪/02解析脚本")
        ).expanduser(),
        hybrid_generation_root=Path(
            os.environ.get(
                "HYBRID_SCRIPT_GENERATION_OUTPUT_ROOT",
                vault / "wiki/视频/AI实拍混剪/03复刻裂变脚本",
            )
        ).expanduser(),
        hybrid_output_root=Path(
            os.environ.get("HYBRID_OMNI_SCRIPT_ROOT", vault / "wiki/视频/AI实拍混剪/04适配脚本/omni")
        ).expanduser(),
        product_info_root=Path(
            os.environ.get("PRODUCT_INFO_ROOT", vault / "wiki/产品/产品信息")
        ).expanduser(),
        mistake_book_root=Path(
            os.environ.get("SCRIPT_MISTAKE_BOOK_ROOT", vault / "wiki/视频/共享知识库/脚本错题本")
        ).expanduser(),
        prompt_path=Path(os.environ.get("UNIFIED_SCRIPT_PROMPT_PATH", prompt_default)).expanduser(),
        data_root=Path(os.environ.get("UNIFIED_SCRIPT_AGENT_DATA_ROOT", "/config/unified-script-agent")).expanduser(),
    )


def _walk_markdown(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith((".", "_")))
        for filename in sorted(filenames):
            if filename.lower().endswith(".md") and not filename.startswith((".", "_")):
                result.append(Path(directory) / filename)
    return result


def _market_from_filename(filename: str) -> str:
    first = Path(filename).stem.split("-", 1)[0].upper()
    return first if re.fullmatch(r"[A-Z]{2,3}", first) else ""


def _output_status_index(roots: tuple[Path, ...], route: str) -> dict[str, dict[str, set[str]]]:
    stems: set[tuple[str, str]] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith((".", "_")))
            for filename in filenames:
                if filename.startswith((".", "_")):
                    continue
                if filename.lower().endswith(".raw.json"):
                    stem = filename[: -len(".raw.json")]
                elif filename.lower().endswith(".md"):
                    stem = filename[:-3]
                else:
                    continue
                relative = Path(directory).relative_to(root)
                if route == "route3":
                    product = relative.parts[1] if len(relative.parts) >= 2 else ""
                else:
                    product = relative.parts[0] if relative.parts else ""
                stems.add((product, re.sub(r"^omni-", "", stem, flags=re.IGNORECASE)))

    status: dict[str, dict[str, set[str]]] = {}
    for product, stem in stems:
        if stem.startswith("复刻-"):
            stage = "clone"
        elif stem.startswith("裂变-"):
            stage = "mutation"
        else:
            continue
        current = status.setdefault(product, {"clones": set(), "mutations": set()})
        current["clones" if stage == "clone" else "mutations"].add(stem)
    return status


def _source_record(
    route: str,
    root: Path,
    path: Path,
    output_status: dict[str, dict[str, set[str]]],
) -> dict[str, Any]:
    relative = path.relative_to(root)
    if route == "route3":
        content_type = relative.parts[0] if len(relative.parts) >= 3 else ""
        product = relative.parts[1] if len(relative.parts) >= 3 else ""
        source_folder = path.stem
    else:
        content_type = "纯AI"
        product = relative.parts[0] if len(relative.parts) >= 2 else ""
        source_folder = ""
    market = _market_from_filename(path.name)
    _country, author, source_id = reference_country_author_and_video_id(path)
    identity = f"-{author}-{source_id}"
    saved_status = output_status.get(product, {})
    return {
        "route": route,
        "name": path.name,
        "path": path.as_posix(),
        "product": product,
        "content_type": content_type,
        "source_folder": source_folder,
        "market": market,
        "language": COUNTRY_LANGUAGES.get(market, ""),
        "status": {
            "cloned": any(identity in stem for stem in saved_status.get("clones") or ()),
            "mutation_count": sum(identity in stem for stem in saved_status.get("mutations") or ()),
        },
    }


def build_catalog() -> dict[str, Any]:
    current = storage_paths()
    pure_status = _output_status_index((current.pure_generation_root, current.pure_output_root), "route1")
    hybrid_status = _output_status_index((current.hybrid_generation_root, current.hybrid_output_root), "route3")
    sources: list[dict[str, Any]] = []
    for path in _walk_markdown(current.pure_source_root):
        sources.append(_source_record("route1", current.pure_source_root, path, pure_status))
    for path in _walk_markdown(current.hybrid_source_root):
        sources.append(_source_record("route3", current.hybrid_source_root, path, hybrid_status))

    products: list[dict[str, str]] = []
    if current.product_info_root.is_dir():
        for path in sorted(current.product_info_root.glob("*-产品信息.md"), key=lambda item: item.name.casefold()):
            if path.name.startswith((".", "_")):
                continue
            products.append({"name": path.name[: -len("-产品信息.md")], "path": path.as_posix()})

    sources.sort(key=lambda item: (item["route"], item["product"].casefold(), item["name"].casefold()))
    return {
        "sources": sources,
        "products": products,
        "counts": {
            "pure": sum(1 for item in sources if item["route"] == "route1"),
            "hybrid": sum(1 for item in sources if item["route"] == "route3"),
            "products": len(products),
        },
    }


def catalog_payload(refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return refresh_snapshot("unified-script-agent", "catalog", build_catalog)
    payload = cached_or_empty(
        "unified-script-agent",
        "catalog",
        lambda: {"sources": [], "products": [], "counts": {"pure": 0, "hybrid": 0, "products": 0}},
    )
    if payload.get("sources") and any("status" not in item for item in payload["sources"]):
        return refresh_snapshot("unified-script-agent", "catalog", build_catalog)
    return payload


def _source_history_status() -> dict[tuple[str, str, str], dict[str, Any]]:
    current = storage_paths()
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, count in _read_history(current).items():
        parts = key.split("|", 4)
        if len(parts) != 5:
            continue
        source_route = "route3" if parts[0] == "route3" else "route1"
        _country, author, source_id = reference_country_author_and_video_id(Path(parts[4]))
        identity = f"{author}-{source_id}"
        saved = result.setdefault((source_route, parts[2], identity), {"cloned": False, "mutation_count": 0})
        saved["mutation_count"] += max(0, int(count))
    for key in _read_clone_history(current):
        parts = key.split("|", 4)
        if len(parts) != 5:
            continue
        source_route = "route3" if parts[0] == "route3" else "route1"
        _country, author, source_id = reference_country_author_and_video_id(Path(parts[4]))
        identity = f"{author}-{source_id}"
        saved = result.setdefault((source_route, parts[2], identity), {"cloned": False, "mutation_count": 0})
        saved["cloned"] = True
    return result


def _catalog_with_runtime_history(catalog: dict[str, Any]) -> dict[str, Any]:
    history = _source_history_status()
    payload = dict(catalog)
    sources: list[dict[str, Any]] = []
    for item in catalog.get("sources") or []:
        source = dict(item)
        status = dict(source.get("status") or {})
        _country, author, source_id = reference_country_author_and_video_id(Path(str(source.get("name") or "")))
        identity = f"{author}-{source_id}"
        saved = history.get(
            (
                str(source.get("route") or "route1"),
                str(source.get("product") or ""),
                identity,
            ),
            {},
        )
        status["cloned"] = bool(status.get("cloned") or saved.get("cloned"))
        status["mutation_count"] = max(
            int(status.get("mutation_count") or 0),
            int(saved.get("mutation_count") or 0),
        )
        source["status"] = status
        sources.append(source)
    payload["sources"] = sources
    return payload


def state_payload(refresh: bool = False) -> dict[str, Any]:
    current = storage_paths()
    profile = load_profile("text")
    catalog = _catalog_with_runtime_history(catalog_payload(refresh))
    return {
        **catalog,
        "routes": {
            "route1": {
                "label": ROUTE_LABELS["route1"],
                "input": current.pure_source_root.as_posix(),
                "output": current.pure_output_root.as_posix(),
                "product_fact": "自动使用来源产品资料",
            },
            "route2": {
                "label": ROUTE_LABELS["route2"],
                "input": current.pure_source_root.as_posix(),
                "output": current.pure_output_root.as_posix(),
                "product_fact": "必选，且目标产品应与来源产品不同",
            },
            "route3": {
                "label": ROUTE_LABELS["route3"],
                "input": current.hybrid_source_root.as_posix(),
                "output": current.hybrid_output_root.as_posix(),
                "product_fact": "可选",
            },
        },
        "model": {
            "selected": "omni",
            "available": ["omni"],
            "pending": ["grok", "veo"],
            "text_model": profile["model"],
            "has_api_key": bool(profile["api_key"]),
        },
        "prompt": {
            "path": current.prompt_path.as_posix(),
            "exists": current.prompt_path.is_file(),
            "production_models": ["omni"],
        },
        "country_languages": COUNTRY_LANGUAGES,
    }


def load_prompt_blocks(path: Path | None = None) -> tuple[str, dict[str, str]]:
    prompt_path = path or storage_paths().prompt_path
    if not prompt_path.is_file():
        raise RuntimeError(f"统一提示词文件不存在: {prompt_path}")
    text = prompt_path.read_text(encoding="utf-8")
    matches = list(PROMPT_BLOCK_RE.finditer(text))
    blocks = {match.group("name"): match.group("body").strip() for match in matches}
    preamble = text[: matches[0].start()].strip() if matches else ""
    required = {"COMMON", "CLONE", "MUTATION", "PRODUCT_REWRITE", "MODEL_OMNI", "REPAIR"}
    missing = sorted(required - blocks.keys())
    if missing:
        raise RuntimeError("统一提示词缺少区块: " + "、".join(missing))
    return preamble, blocks


def selected_block_names(route: str, mode: str, model: str = "omni") -> list[str]:
    if route not in ROUTE_LABELS:
        raise ValueError("请选择线路 1、线路 2 或线路 3")
    if mode not in MODE_LABELS:
        raise ValueError("请选择复刻或裂变")
    if model != "omni":
        raise ValueError("当前只有 Omni 已完成审核并开放生产；Grok 和 Veo 暂不可选")
    names = ["COMMON"]
    if route == "route2":
        names.append("PRODUCT_REWRITE")
    names.append("CLONE")
    if mode == "mutation":
        names.append("MUTATION")
    names.append("MODEL_OMNI")
    return names


def assemble_prompt(
    payload: dict[str, Any],
    source_text: str,
    fact_card: str,
    lesson_card: str,
    *,
    variant_number: int = 0,
) -> str:
    route = str(payload.get("route") or "")
    mode = str(payload.get("mode") or "")
    model = str(payload.get("model") or "omni").lower()
    preamble, blocks = load_prompt_blocks()
    names = selected_block_names(route, mode, model)
    values = {
        "SOURCE_FILENAME": Path(str(payload["source_path"])).name,
        "TARGET_MARKET": str(payload.get("target_market") or "").strip(),
        "TARGET_LANGUAGE": str(payload.get("target_language") or "").strip(),
        "SOURCE_PRODUCT": str(payload.get("source_product") or "").strip(),
        "TARGET_PRODUCT": str(payload.get("target_product") or payload.get("source_product") or "").strip(),
        "VARIANT_COUNT": str(payload.get("variant_count") or 1),
        "VARIANT_NUMBER": str(variant_number or "不适用"),
        "CONTENT_SUBTYPE": str(payload.get("content_type") or "纯AI").strip(),
        "MODEL_SEGMENT_SECONDS": "10",
        "TECHNICAL_PADDING_REQUIREMENT": "无",
    }
    variable_lines = "\n".join(f"- `{key}`：{value}" for key, value in values.items())
    runtime = f"""# 本次运行变量（值已由 10006 校验）

{variable_lines}

## TARGET_PRODUCT_FACT_CARD

{fact_card or "未注入产品事实卡。"}

## PRODUCT_LESSON_CARD

{lesson_card or "未匹配到当前产品错题本。"}

## SOURCE_SCRIPT

<SOURCE_SCRIPT>
{source_text.strip()}
</SOURCE_SCRIPT>
"""
    selected = "\n\n---\n\n".join(blocks[name] for name in names)
    return f"{preamble}\n\n{selected}\n\n---\n\n{runtime}".strip() + "\n"


def _allowed_source_root(route: str, current: StoragePaths) -> Path:
    return current.hybrid_source_root if route == "route3" else current.pure_source_root


def _validated_file(value: str, root: Path, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label}不在当前线路允许的资料库目录内") from exc
    if not path.is_file() or path.suffix.lower() != ".md":
        raise ValueError(f"{label}不存在或不是 Markdown 文件")
    return path


def source_preview_payload(route: str, source_path: str) -> dict[str, str]:
    if route not in ROUTE_LABELS:
        raise ValueError("请选择线路 1、线路 2 或线路 3")
    current = storage_paths()
    source = _validated_file(source_path, _allowed_source_root(route, current), "来源脚本")
    return {
        "name": source.name,
        "path": source.as_posix(),
        "content": source.read_text(encoding="utf-8", errors="ignore"),
    }


def _product_info_path(product: str, current: StoragePaths) -> Path:
    return current.product_info_root / f"{product}-产品信息.md"


def _lesson_card(product: str, current: StoragePaths) -> str:
    direct = current.mistake_book_root / f"{product}.md"
    if direct.is_file():
        return direct.read_text(encoding="utf-8", errors="ignore").strip()
    key = re.sub(r"[\W_]+", "", product).casefold()
    if current.mistake_book_root.is_dir():
        for path in current.mistake_book_root.glob("*.md"):
            if re.sub(r"[\W_]+", "", path.stem).casefold() == key:
                return path.read_text(encoding="utf-8", errors="ignore").strip()
    return ""


def validate_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = storage_paths()
    result = dict(payload)
    route = str(result.get("route") or "")
    mode = str(result.get("mode") or "")
    model = str(result.get("model") or "omni").lower()
    selected_block_names(route, mode, model)
    source = _validated_file(str(result.get("source_path") or ""), _allowed_source_root(route, current), "来源脚本")
    relative = source.relative_to(_allowed_source_root(route, current).resolve())
    if route == "route3":
        if len(relative.parts) < 3 or relative.parts[0] not in {"混剪-钩子", "混剪-CTA"}:
            raise ValueError("线路 3 来源脚本必须位于 混剪-钩子 或 混剪-CTA 的产品目录内")
        source_product = relative.parts[1]
        content_type = relative.parts[0]
    else:
        if len(relative.parts) < 2:
            raise ValueError("纯 AI 来源脚本必须位于产品子目录内")
        source_product = relative.parts[0]
        content_type = "纯AI"

    target_product = str(result.get("target_product") or "").strip()
    if route == "route1":
        target_product = source_product
        use_product_info = True
    elif route == "route2":
        if not target_product:
            raise ValueError("线路 2 必须选择目标产品资料")
        if target_product == source_product:
            raise ValueError("线路 2 的目标产品必须与来源产品不同")
        use_product_info = True
    elif not target_product:
        target_product = source_product
        use_product_info = False
    else:
        use_product_info = bool(target_product)
    if use_product_info and not _product_info_path(target_product, current).is_file():
        raise ValueError(f"目标产品缺少产品信息文件: {target_product}-产品信息.md")

    market = str(result.get("target_market") or "").strip().upper()
    language = str(result.get("target_language") or "").strip()
    if not market:
        market = _market_from_filename(source.name)
    if not language:
        language = COUNTRY_LANGUAGES.get(market, "")
    if not market or not language:
        raise ValueError("请确认目标国家/地区和目标语言")

    try:
        variant_count = int(result.get("variant_count") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("裂变数量必须是整数") from exc
    if mode == "mutation" and not 1 <= variant_count <= 99:
        raise ValueError("裂变数量必须在 1–99 之间")
    if mode == "clone":
        variant_count = 1

    result.update(
        {
            "route": route,
            "mode": mode,
            "model": model,
            "source_path": source.as_posix(),
            "source_product": source_product,
            "target_product": target_product,
            "content_type": content_type,
            "target_market": market,
            "target_language": language,
            "variant_count": variant_count,
            "use_product_info": use_product_info,
        }
    )
    return result


def _seconds(value: str) -> float:
    minute, second = value.split(":", 1)
    return int(minute) * 60 + float(second)


def clean_model_markdown(text: str) -> str:
    content = str(text or "").strip()
    match = OUTER_FENCE_RE.fullmatch(content)
    return (match.group("body") if match else content).strip()


def validate_omni_markdown(text: str) -> list[str]:
    content = clean_model_markdown(text)
    issues: list[str] = []
    if not re.match(r"^#\s*\n## 每段生成提示词\s*$", "\n".join(content.splitlines()[:2])):
        issues.append("文件必须以 # 和 ## 每段生成提示词 两行开头")
    segments = list(SEGMENT_RE.finditer(content))
    if not segments:
        return issues + ["没有找到任何 # Segment 段落"]
    numbers = [int(match.group("number")) for match in segments]
    if numbers != list(range(1, len(numbers) + 1)):
        issues.append("Segment 编号必须从 1 开始连续递增")

    for index, match in enumerate(segments):
        number = int(match.group("number"))
        block = content[match.start() : segments[index + 1].start() if index + 1 < len(segments) else len(content)]
        if "00:00.000" not in match.group("range"):
            issues.append(f"Segment {number} 标题必须从 00:00.000 开始")
        a_heading = block.find("## A. 人物造型参考板提示词")
        b_heading = block.find("## B. 故事板图片提示词")
        if a_heading < 0 or b_heading < 0 or b_heading <= a_heading:
            issues.append(f"Segment {number} 缺少按顺序排列的 A 区和 B 区")
            continue
        a_body = block[a_heading:b_heading]
        positions = [a_body.find(label) for label in ("角色ID：", "生成方式：", "参考来源：")]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            issues.append(f"Segment {number} A 区必须依次包含角色ID、生成方式和参考来源")
        b_body = block[b_heading:]
        shots = list(SHOT_RE.finditer(b_body))
        if not shots:
            issues.append(f"Segment {number} B 区没有可识别镜头")
            continue
        shot_numbers = [int(shot.group("number")) for shot in shots]
        if shot_numbers != list(range(1, len(shots) + 1)):
            issues.append(f"Segment {number} 镜头编号必须从 1 开始连续递增")
        previous_end = 0.0
        for shot_index, shot in enumerate(shots):
            shot_number = int(shot.group("number"))
            start = _seconds(shot.group("start"))
            end = _seconds(shot.group("end"))
            if shot_index == 0 and abs(start) > 0.001:
                issues.append(f"Segment {number} 镜头 1 必须从 00:00.000 开始")
            if abs(start - previous_end) > 0.002 or end <= start:
                issues.append(f"Segment {number} 镜头 {shot_number} 时间必须连续且结束晚于开始")
            previous_end = end
            shot_block = b_body[shot.end() : shots[shot_index + 1].start() if shot_index + 1 < len(shots) else len(b_body)]
            fields = [field.group("name") for field in FIELD_RE.finditer(shot_block)]
            if fields != list(OMNI_FIELDS):
                issues.append(
                    f"Segment {number} 镜头 {shot_number} 必须恰好按顺序包含 9 个字段"
                )
    return list(dict.fromkeys(issues))


def _repair_prompt(candidate: str, issues: list[str]) -> str:
    _preamble, blocks = load_prompt_blocks()
    return f"""{blocks['REPAIR']}

# 本次局部修复输入

错误：
{chr(10).join(f'- {issue}' for issue in issues)}

请只修正导致上述错误的结构和内容，返回修复后的完整 Omni Markdown，不要解释。

<REPAIR_CONTEXT>
{candidate}
</REPAIR_CONTEXT>
"""


def _call_model(prompt: str, request_kind: str, label: str) -> str:
    profile = load_profile("text")
    if not profile["api_key"]:
        raise RuntimeError("缺少全局文本模型 API Key，请先在 8888 的全局 API / 模型页面配置")
    max_tokens = 96 * 1024 if request_kind == "mutation" else 32 * 1024
    config = {
        "modelmesh_base_url": profile["base_url"],
        "script_generation_model": profile["model"],
        "script_generation_timeout": 360,
        "script_generation_max_output_tokens": 32 * 1024,
        "script_mutation_max_output_tokens": 96 * 1024,
    }
    args = SimpleNamespace(model="", base_url="", timeout=0, max_output_tokens=max_tokens)
    text, _raw, _endpoint, _field = call_text_model(
        config,
        args,
        prompt,
        label,
        request_kind=request_kind,
    )
    return clean_model_markdown(text)


def _output_directory(payload: dict[str, Any], current: StoragePaths) -> Path:
    product = safe_output_name(payload["target_product"])
    if payload["route"] != "route3":
        return current.pure_output_root / product
    source = Path(payload["source_path"])
    return current.hybrid_output_root / payload["content_type"] / product / source.stem


def _country_code(value: str) -> str:
    raw = str(value or "").strip()
    return COUNTRY_FILENAME_CODE.get(raw.casefold(), safe_output_name(raw).upper())


def _output_base_stem(payload: dict[str, Any]) -> str:
    source = Path(payload["source_path"])
    _country, author, source_id = reference_country_author_and_video_id(source)
    stage = MODE_LABELS[payload["mode"]]
    return "-".join(
        (
            payload["model"],
            stage,
            safe_output_name(payload["target_product"]),
            _country_code(payload["target_market"]),
            author,
            source_id,
        )
    )


def _history_path(current: StoragePaths) -> Path:
    return current.data_root / "mutation_history.json"


def _clone_history_path(current: StoragePaths) -> Path:
    return current.data_root / "clone_history.json"


def _read_history(current: StoragePaths) -> dict[str, int]:
    try:
        data = json.loads(_history_path(current).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return {str(key): int(value) for key, value in data.items() if str(value).isdigit() or isinstance(value, int)}


def _write_history(current: StoragePaths, history: dict[str, int]) -> None:
    path = _history_path(current)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_clone_history(current: StoragePaths) -> dict[str, str]:
    try:
        data = json.loads(_clone_history_path(current).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _record_clone(payload: dict[str, Any]) -> None:
    current = storage_paths()
    with _HISTORY_LOCK:
        history = _read_clone_history(current)
        history[_history_key(payload)] = time.strftime("%Y-%m-%d %H:%M:%S")
        path = _clone_history_path(current)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def _history_key(payload: dict[str, Any]) -> str:
    return "|".join(
        (
            payload["route"],
            payload["model"],
            payload["target_product"],
            payload["target_market"],
            Path(payload["source_path"]).name,
        )
    )


def reserve_mutation_numbers(payload: dict[str, Any], count: int) -> list[int]:
    current = storage_paths()
    output_dir = _output_directory(payload, current)
    base = _output_base_stem(payload)
    with _HISTORY_LOCK:
        history = _read_history(current)
        key = _history_key(payload)
        maximum = int(history.get(key, 0))
        if output_dir.is_dir():
            for path in output_dir.glob(f"{base}*.md"):
                suffix = re.search(r"_(\d{3,})$", path.stem)
                maximum = max(maximum, int(suffix.group(1)) if suffix else 1)
        numbers = list(range(maximum + 1, maximum + count + 1))
        history[key] = numbers[-1]
        _write_history(current, history)
        return numbers


def output_path_for(payload: dict[str, Any], variant_number: int = 0) -> Path:
    current = storage_paths()
    stem = _output_base_stem(payload)
    if variant_number:
        stem += f"_{variant_number:03d}"
    return _output_directory(payload, current) / f"{stem}.md"


def _write_output(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def _generate_one(
    payload: dict[str, Any],
    source_text: str,
    fact_card: str,
    lesson_card: str,
    progress: Callable[[str], None],
    variant_number: int = 0,
) -> dict[str, Any]:
    output_path = output_path_for(payload, variant_number)
    if not variant_number and output_path.is_file():
        existing = output_path.read_text(encoding="utf-8", errors="ignore")
        if not validate_omni_markdown(existing):
            progress(f"已有合格适配稿，直接复用：{output_path.name}")
            return {"path": output_path.as_posix(), "name": output_path.name, "reused": True}

    prompt = assemble_prompt(
        payload,
        source_text,
        fact_card,
        lesson_card,
        variant_number=variant_number,
    )
    label = f"统一脚本{MODE_LABELS[payload['mode']]}"
    if variant_number:
        label += f" #{variant_number}"
    progress(f"开始调用文本模型：{label}")
    candidate = _call_model(prompt, payload["mode"], label)
    issues = validate_omni_markdown(candidate)
    for attempt in range(1, 3):
        if not issues:
            break
        progress(f"{label} 第 {attempt} 次校验未通过，只修复失败内容：{'；'.join(issues[:3])}")
        candidate = _call_model(_repair_prompt(candidate, issues), "repair", f"{label} 局部修复")
        issues = validate_omni_markdown(candidate)
    if issues:
        raise RuntimeError("Omni 输出校验失败：" + "；".join(issues))
    _write_output(output_path, candidate)
    progress(f"已写入片段产出目录：{output_path}")
    return {"path": output_path.as_posix(), "name": output_path.name, "reused": False}


def run_task(payload: dict[str, Any], progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    log = progress or (lambda _message: None)
    task = validate_task_payload(payload)
    current = storage_paths()
    source_path = Path(task["source_path"])
    source_text = source_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not source_text:
        raise RuntimeError("来源脚本为空")
    fact_card = ""
    if task["use_product_info"]:
        manual = _product_info_path(task["target_product"], current).read_text(encoding="utf-8", errors="ignore")
        fact_card = compact_product_fact_card(manual, max_chars=5000)
    lesson_card = _lesson_card(task["target_product"], current)
    log(
        f"任务已确认：{ROUTE_LABELS[task['route']]} / {MODE_LABELS[task['mode']]} / Omni / "
        f"{task['target_market']} / {task['target_language']}"
    )
    if task["route"] == "route2":
        log(f"产品改写：{task['source_product']} → {task['target_product']}，不保存中间稿")
    if task["route"] == "route3" and not task["use_product_info"]:
        log("线路 3 本次不注入产品事实卡")

    if task["mode"] == "clone":
        outputs = [_generate_one(task, source_text, fact_card, lesson_card, log)]
        _record_clone(task)
    else:
        numbers = reserve_mutation_numbers(task, task["variant_count"])
        outputs: list[dict[str, Any]] = []
        for offset in range(0, len(numbers), 3):
            batch = numbers[offset : offset + 3]
            log("开始裂变批次：" + "、".join(f"#{number}" for number in batch))
            failures: list[tuple[int, str]] = []
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = {
                    executor.submit(
                        _generate_one,
                        task,
                        source_text,
                        fact_card,
                        lesson_card,
                        log,
                        number,
                    ): number
                    for number in batch
                }
                for future in as_completed(futures):
                    number = futures[future]
                    try:
                        outputs.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - preserve successful variants and report only failures.
                        failures.append((number, str(exc)))
                        log(f"裂变 #{number} 失败：{exc}")
            if failures:
                log("批次存在失败，已缩小为单条补跑")
                for number, _error in failures:
                    try:
                        outputs.append(
                            _generate_one(task, source_text, fact_card, lesson_card, log, number)
                        )
                    except Exception as exc:  # noqa: BLE001 - return partial success with exact failed number.
                        log(f"裂变 #{number} 补跑仍失败：{exc}")
        outputs.sort(key=lambda item: item["name"])
        if not outputs:
            raise RuntimeError("全部裂变脚本均未通过校验，没有写入任何结果")

    return {
        "route": task["route"],
        "mode": task["mode"],
        "model": task["model"],
        "requested": task["variant_count"],
        "completed": len(outputs),
        "partial_success": len(outputs) < task["variant_count"],
        "outputs": outputs,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
