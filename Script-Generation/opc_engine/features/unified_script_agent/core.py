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
    classify_audio_content,
    classify_subject_type,
    compact_product_fact_card,
    extract_subject_profiles,
    reference_country_author_and_video_id,
    safe_output_name,
    spoken_audio_metrics,
)


PROMPT_FILENAME = "unified_script_generation_adaptation_prompt.md"
PROMPT_BLOCK_RE = re.compile(
    r"<!--\s*OPC_BLOCK:(?P<name>[A-Z_]+):START\s*-->\s*"
    r"(?P<body>.*?)"
    r"\s*<!--\s*OPC_BLOCK:(?P=name):END\s*-->",
    re.DOTALL,
)
OUTER_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*$", re.DOTALL | re.IGNORECASE)
JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(?P<body>.*)\n```\s*$", re.DOTALL | re.IGNORECASE)
MAX_REPAIR_ATTEMPTS = 4
SEGMENT_RE = re.compile(r"(?m)^#\s*Segment\s+(?P<number>\d+)\s*[：:]\s*(?P<range>.+?)\s*$")
SHOT_RE = re.compile(
    r"(?m)^###\s*镜头\s+(?P<number>\d+)\s*\("
    r"(?P<start>\d{2}:\d{2}\.\d{3})\s*-\s*(?P<end>\d{2}:\d{2}\.\d{3})\)\s*$"
)
FIELD_RE = re.compile(r"(?m)^- \[(?P<name>[^\]]+)\]\s+(?P<value>\S.*)$")
SEEDANCE_SHOT_RE = re.compile(r"(?m)^###\s*(?P<number>\d{2})\s*｜\s*(?P<title>\S.*?)\s*$")
SEEDANCE_FIELD_RE = re.compile(r"(?m)^\*\*(?P<name>[^*：:]+)[：:]\*\*\s*$")
SEEDANCE_TIME_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}\.\d{3})\s*[–-]\s*(?P<end>\d{2}:\d{2}\.\d{3})"
    r"\s*｜\s*(?P<duration>\d+(?:\.\d+)?)\s*秒$"
)
SEGMENT_RANGE_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}\.\d{3})\s*[–-]\s*(?P<end>\d{2}:\d{2}\.\d{3})$"
)
SOURCE_SHOT_RE = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?镜头[ \t]*\d+[ \t]*\([ \t]*"
    r"(?P<start>\d{1,2}:\d{2}(?:\.\d{1,3})?)[ \t]*[-~—至到]+[ \t]*"
    r"(?P<end>\d{1,2}:\d{2}(?:\.\d{1,3})?)[ \t]*\)[ \t]*:?[ \t]*$"
)
A_FIELD_RE = re.compile(r"(?m)^(?P<name>角色ID|生成方式|参考来源)[：:]\s*(?P<value>\S.*?)\s*$")
CHARACTER_DESCRIPTION_RE = re.compile(
    r"(?m)^-\s*(?P<role_id>character_\d{2,})[：:]\s*(?P<description>\S.*?)\s*$",
    re.IGNORECASE,
)
CHARACTER_ID_RE = re.compile(r"character_\d{2,}", re.IGNORECASE)
MIN_EXPANDED_CHARACTER_DESCRIPTION_LENGTH = 12
SOURCE_AUDIO_RE = re.compile(r"(?m)^\s*[-*]\s*\[音频文案\]\s*(?P<value>\S.*?)\s*$")
OMNI_GENERATION_MODES = frozenset({"首次生成", "直接复用", "状态更新", "新角色合并", "无人物场景"})
LOCKED_SUBJECT_TYPES = frozenset({"skeleton", "robot", "doll", "animal", "monster", "no_person"})
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
PRODUCT_APPEARANCE_ATTRIBUTE = (
    r"颜色|色号|形状|外形|轮廓|材质|质地|质感|包装|标签|Logo|logo|商标|品牌字样|"
    r"黑色|白色|红色|橙色|黄色|绿色|青色|蓝色|紫色|灰色|棕色|褐色|棕褐色|金色|银色|粉色|米色|"
    r"透明|半透明|不透明|圆柱形|方形|塑料|玻璃|金属|纸盒|软管"
)
PRODUCT_VISUAL_OBJECT = (
    r"\[产品\]|\[手持产品\]|产品|商品|瓶身|瓶体|容器|包装|泵头|喷头|喷嘴|刷头|滴管|滚珠|瓶盖|梳齿"
)
PRODUCT_CONTENT_OBJECT = r"膏体|液体|凝胶|乳液|泡沫|内容物"
PRODUCT_APPEARANCE_RE = re.compile(
    rf"(?:{PRODUCT_VISUAL_OBJECT})(?:的)?(?:颜色|色号|形状|外形|轮廓|材质|质地|质感|为|是|呈|采用|带有)"
    rf".{{0,8}}(?:{PRODUCT_APPEARANCE_ATTRIBUTE})"
    rf"|(?:{PRODUCT_APPEARANCE_ATTRIBUTE})(?:的)?(?:{PRODUCT_VISUAL_OBJECT})"
    rf"|(?:{PRODUCT_APPEARANCE_ATTRIBUTE}).{{0,4}}(?:{PRODUCT_CONTENT_OBJECT})"
    rf"|(?:{PRODUCT_CONTENT_OBJECT})(?:的)?(?:颜色|色号|材质|质地|质感|为|是|呈).{{0,6}}"
    rf"(?:{PRODUCT_APPEARANCE_ATTRIBUTE})",
    re.IGNORECASE,
)
PRODUCT_PACKAGING_RE = re.compile(r"包装|标签|Logo|商标|品牌字样|瓶身文字|瓶体文字", re.IGNORECASE)
PRODUCT_CONTAINER_RE = re.compile(r"瓶身|瓶体|罐身|盒身|外壳")
PRODUCT_CONTEXT_RE = re.compile(
    r"\[产品\]|\[手持产品\]|产品|商品|包装|瓶身|瓶体|膏体|液体|凝胶|乳液|泡沫|内容物|"
    r"泵头|喷头|喷嘴|刷头|滴管|滚珠|瓶盖|梳齿"
)
PRODUCT_STRUCTURE_TERMS = ("泵头", "喷头", "喷嘴", "刷头", "滴管", "滚珠", "瓶盖", "旋盖", "梳齿")
PRODUCT_VISUAL_FIELDS = frozenset(
    {
        "主体",
        "在场景中",
        "做什么动作",
        "镜头语言",
        "光线",
        "细节",
        "画面风格/氛围",
        "画面内容",
        "动作/景别",
        "构图",
        "拍摄方式",
    }
)
PRODUCT_ACTION_FIELDS = frozenset({"做什么动作", "动作/景别"})
PRODUCT_USAGE_ACTION_RULES = (
    ("按压", re.compile(r"按压|压下|压动"), ("按压", "泵头", "压泵")),
    ("喷洒", re.compile(r"喷洒|喷向|喷到|喷在"), ("喷洒", "喷雾", "喷头")),
    ("挤出", re.compile(r"挤出|挤压|挤到|挤在"), ("挤出", "挤压")),
    ("倒出", re.compile(r"倒出|倒入|倾倒"), ("倒出", "倒入", "倾倒")),
    ("滴用", re.compile(r"滴入|滴到|滴在"), ("滴入", "滴到", "滴管")),
    ("开盖或拆封", re.compile(r"拧开|旋开|开盖|撕开|拆封"), ("拧开", "旋开", "开盖", "拆封")),
    ("涂抹", re.compile(r"涂抹|抹到|抹在|涂到|涂在"), ("涂抹", "抹到", "抹在", "涂到", "涂在")),
    ("揉搓", re.compile(r"揉搓"), ("揉搓", "洗头", "涂抹")),
    ("冲洗", re.compile(r"冲洗|洗净"), ("冲洗", "洗净")),
    ("口服或饮用", re.compile(r"吞服|口服|饮用|喝下"), ("吞服", "口服", "饮用", "喝下")),
    ("插接或充电", re.compile(r"插入|接入|连接电源|充电"), ("插入", "接入", "连接", "充电")),
    ("安装或拆卸", re.compile(r"安装|装上|拆卸|取下配件"), ("安装", "装上", "拆卸", "取下")),
)
PRODUCT_FACT_ROW_RE = re.compile(
    r"(?m)^\|\s*\*\*(?:产品名称|品牌|型号-SKU|产品类型)\*\*\s*\|\s*(?P<value>[^|]+)\|"
)
PRODUCT_FACT_ALIASES_RE = re.compile(r"(?m)^aliases:\s*(?P<value>\[[^\n]+\])\s*$")
SEEDANCE_FIELDS = (
    "画面内容",
    "动作/景别",
    "构图",
    "拍摄方式",
    "声音",
    "台词",
    "时间",
)
SEEDANCE_FIELD_NAME_PATTERN = "|".join(re.escape(name) for name in SEEDANCE_FIELDS)
SEEDANCE_LOOSE_FIELD_RE = re.compile(
    rf"(?m)^[ \t]*(?:-\s*)?(?:\*\*(?P<bold_name>{SEEDANCE_FIELD_NAME_PATTERN})(?:[：:]?)\*\*[：:]?"
    rf"|(?P<plain_name>{SEEDANCE_FIELD_NAME_PATTERN})[：:])(?:[ \t]+(?P<value>\S.*))?$"
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
MODEL_LABELS = {"omni": "Omni", "seedance": "Seedance"}
_HISTORY_LOCK = threading.RLock()


@dataclass(frozen=True)
class StoragePaths:
    vault_root: Path
    pure_source_root: Path
    pure_generation_root: Path
    pure_output_root: Path
    pure_seedance_output_root: Path
    hybrid_source_root: Path
    hybrid_generation_root: Path
    hybrid_output_root: Path
    hybrid_seedance_output_root: Path
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
        pure_seedance_output_root=Path(
            os.environ.get("SEEDANCE_SCRIPT_ROOT", vault / "wiki/视频/纯AI视频/04适配脚本/seedance")
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
        hybrid_seedance_output_root=Path(
            os.environ.get(
                "HYBRID_SEEDANCE_SCRIPT_ROOT",
                vault / "wiki/视频/AI实拍混剪/04适配脚本/seedance",
            )
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
            "available": ["omni", "seedance"],
            "pending": ["grok", "veo"],
            "text_model": profile["model"],
            "has_api_key": bool(profile["api_key"]),
        },
        "prompt": {
            "path": current.prompt_path.as_posix(),
            "exists": current.prompt_path.is_file(),
            "production_models": ["omni", "seedance"],
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
    required = {
        "COMMON",
        "CLONE",
        "MUTATION",
        "PRODUCT_REWRITE",
        "MODEL_OMNI",
        "MODEL_SEEDANCE",
        "SEEDANCE_FINAL_CONTRACT",
        "REPAIR",
        "REPAIR_SEEDANCE",
    }
    missing = sorted(required - blocks.keys())
    if missing:
        raise RuntimeError("统一提示词缺少区块: " + "、".join(missing))
    return preamble, blocks


def selected_block_names(route: str, mode: str, model: str = "omni") -> list[str]:
    if route not in ROUTE_LABELS:
        raise ValueError("请选择线路 1、线路 2 或线路 3")
    if mode not in MODE_LABELS:
        raise ValueError("请选择复刻或裂变")
    if model not in MODEL_LABELS:
        raise ValueError("当前只有 Omni 和 Seedance 已开放生产；Grok 和 Veo 暂不可选")
    names = ["COMMON"]
    if route == "route2":
        names.append("PRODUCT_REWRITE")
    names.append("CLONE")
    if mode == "mutation":
        names.append("MUTATION")
    names.append("MODEL_OMNI" if model == "omni" else "MODEL_SEEDANCE")
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
        "MODEL_SEGMENT_SECONDS": "15" if model == "seedance" else "10",
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
    document = f"{preamble}\n\n{selected}\n\n---\n\n{runtime}".strip()
    if model == "seedance":
        document += f"\n\n---\n\n{blocks['SEEDANCE_FINAL_CONTRACT']}"
    elif model == "omni":
        document += f"\n\n---\n\n{blocks['OMNI_FINAL_CONTRACT']}"
    return document.strip() + "\n"


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


def _subject_role_has_description(
    subject_value: str,
    role_match: re.Match[str],
    next_role_start: int,
) -> bool:
    tail = subject_value[role_match.end() : next_role_start]
    description_match = re.match(r"\s*[：:]\s*(?P<description>.+)", tail)
    if not description_match:
        return False
    compact = re.sub(r"[^\w\u3400-\u9fff]+", "", description_match.group("description"))
    return len(compact) >= MIN_EXPANDED_CHARACTER_DESCRIPTION_LENGTH


def _materialize_subject_value(subject_value: str, descriptions: dict[str, str]) -> str:
    result = subject_value
    role_matches = list(CHARACTER_ID_RE.finditer(subject_value))
    for index in range(len(role_matches) - 1, -1, -1):
        role_match = role_matches[index]
        next_role_start = role_matches[index + 1].start() if index + 1 < len(role_matches) else len(subject_value)
        if _subject_role_has_description(subject_value, role_match, next_role_start):
            continue
        role_id = role_match.group(0).lower()
        description = descriptions.get(role_id)
        if not description:
            continue
        tail = result[role_match.end() : next_role_start]
        colon = re.match(r"(?P<space>\s*)[：:]\s*", tail)
        replacement_end = role_match.end()
        separator = ""
        if colon:
            replacement_end += colon.end()
            separator = "；"
        result = (
            result[: role_match.start()]
            + f"{role_id}：{description}{separator}"
            + result[replacement_end:]
        )
    return result


def materialize_omni_character_subjects(text: str) -> str:
    content = clean_model_markdown(text)
    segments = list(SEGMENT_RE.finditer(content))
    descriptions: dict[str, str] = {}
    replacements: list[tuple[int, int, str]] = []
    for index, segment in enumerate(segments):
        block_start = segment.start()
        block_end = segments[index + 1].start() if index + 1 < len(segments) else len(content)
        block = content[block_start:block_end]
        a_heading = block.find("## A. 人物造型参考板提示词")
        b_heading = block.find("## B. 故事板图片提示词")
        if a_heading < 0 or b_heading <= a_heading:
            continue
        for description_match in CHARACTER_DESCRIPTION_RE.finditer(block[a_heading:b_heading]):
            descriptions[description_match.group("role_id").lower()] = description_match.group(
                "description"
            ).strip()

        b_body_start = block_start + b_heading
        b_body = content[b_body_start:block_end]
        shots = list(SHOT_RE.finditer(b_body))
        for shot_index, shot in enumerate(shots):
            shot_body_start = shot.end()
            shot_body_end = shots[shot_index + 1].start() if shot_index + 1 < len(shots) else len(b_body)
            shot_body = b_body[shot_body_start:shot_body_end]
            subject = next(
                (field for field in FIELD_RE.finditer(shot_body) if field.group("name") == "主体"),
                None,
            )
            if subject is None:
                continue
            value = subject.group("value")
            materialized = _materialize_subject_value(value, descriptions)
            if materialized == value:
                continue
            value_start = b_body_start + shot_body_start + subject.start("value")
            replacements.append((value_start, value_start + len(value), materialized))

    for start, end, replacement in reversed(replacements):
        content = content[:start] + replacement + content[end:]
    return content


def _product_identity_terms(fact_card: str) -> tuple[str, ...]:
    terms: set[str] = set()
    for match in PRODUCT_FACT_ROW_RE.finditer(fact_card):
        value = re.sub(r"[*_`]", "", match.group("value")).strip()
        if value:
            terms.add(value)
            terms.update(part.strip() for part in re.split(r"\s*/\s*", value) if len(part.strip()) >= 3)
    aliases = PRODUCT_FACT_ALIASES_RE.search(fact_card)
    if aliases:
        try:
            values = json.loads(aliases.group("value"))
        except (json.JSONDecodeError, TypeError):
            values = []
        terms.update(str(value).strip() for value in values if len(str(value).strip()) >= 3)
    return tuple(sorted(terms, key=len, reverse=True))


def _product_visual_issues(
    fields: list[tuple[str, str]],
    fact_card: str,
    location: str,
) -> list[str]:
    issues: list[str] = []
    identity_terms = _product_identity_terms(fact_card)
    combined_text = "\n".join(value for _field_name, value in fields)
    has_product_context = bool(PRODUCT_CONTEXT_RE.search(combined_text)) or any(
        term.casefold() in combined_text.casefold() for term in identity_terms
    )
    for field_name, value in fields:
        if PRODUCT_PACKAGING_RE.search(value) or PRODUCT_CONTAINER_RE.search(value) or PRODUCT_APPEARANCE_RE.search(value):
            issues.append(
                f"{location} [{field_name}] 不得描述产品颜色、形状、包装、标签、膏体颜色或材质，"
                f"只能使用 [产品]/[手持产品]；当前内容：{value}"
            )
        if field_name in PRODUCT_VISUAL_FIELDS:
            without_placeholders = value.replace("[手持产品]", "").replace("[产品]", "")
            if re.search(r"产品|商品", without_placeholders):
                issues.append(
                    f"{location} [{field_name}] 商品视觉引用必须使用 [产品] 或 [手持产品] 占位符；"
                    f"当前内容：{value}"
                )
            identity_term = next(
                (term for term in identity_terms if term.casefold() in value.casefold()),
                "",
            )
            if identity_term:
                issues.append(
                    f"{location} [{field_name}] 不得直接写商品名称、品牌或 SKU：{identity_term}，请改用 [产品]/[手持产品]"
                )
        for term in PRODUCT_STRUCTURE_TERMS:
            if term in value and term not in fact_card:
                issues.append(f"{location} [{field_name}] 包含产品资料未确认的使用结构：{term}")
    if has_product_context:
        action_text = "\n".join(value for field_name, value in fields if field_name in PRODUCT_ACTION_FIELDS)
        for action_name, action_pattern, evidence_terms in PRODUCT_USAGE_ACTION_RULES:
            if action_pattern.search(action_text) and not any(term in fact_card for term in evidence_terms):
                issues.append(f"{location} 使用动作“{action_name}”未在产品资料中确认")
    return issues


def _source_duration_seconds(source_text: str) -> float | None:
    ranges = [
        (_seconds(match.group("start")), _seconds(match.group("end")))
        for match in SOURCE_SHOT_RE.finditer(str(source_text or ""))
    ]
    ranges = [(start, end) for start, end in ranges if end > start]
    if not ranges:
        return None
    start = min(item[0] for item in ranges)
    end = max(item[1] for item in ranges)
    return end - start if end > start else None


def _source_content_issues(source_text: str, output_text: str, output_has_spoken_audio: bool) -> list[str]:
    if not source_text:
        return []
    issues: list[str] = []
    source_subject_types = {
        classify_subject_type(subject)
        for subject in extract_subject_profiles(source_text).values()
    } & LOCKED_SUBJECT_TYPES
    output_subject_types = {classify_subject_type(line) for line in output_text.splitlines()}
    for subject_type in sorted(source_subject_types):
        if subject_type not in output_subject_types:
            issues.append(f"来源脚本锁定的特殊主体类型 {subject_type} 未在最终稿中保留")

    source_audio_values = [match.group("value") for match in SOURCE_AUDIO_RE.finditer(source_text)]
    if source_audio_values:
        source_has_spoken_audio = any(classify_audio_content(value) == "spoken" for value in source_audio_values)
        if source_has_spoken_audio and not output_has_spoken_audio:
            issues.append("来源脚本包含真实口播，但最终稿丢失了全部口播")
        elif not source_has_spoken_audio and output_has_spoken_audio:
            issues.append("来源脚本全程无真实口播，最终稿不得新增人物口播、旁白或对白")
    return issues


def validate_omni_markdown(text: str, fact_card: str = "", source_text: str = "") -> list[str]:
    content = clean_model_markdown(text)
    content_issues: list[str] = []
    omni_issues: list[str] = []
    if not re.match(r"^#\s*\n## 每段生成提示词\s*$", "\n".join(content.splitlines()[:2])):
        omni_issues.append("文件必须以 # 和 ## 每段生成提示词 两行开头")
    segments = list(SEGMENT_RE.finditer(content))
    if not segments:
        omni_issues.append("没有找到任何 # Segment 段落")
        return [f"[9994 Omni 适配] {issue}" for issue in dict.fromkeys(omni_issues)]
    numbers = [int(match.group("number")) for match in segments]
    if numbers != list(range(1, len(numbers) + 1)):
        omni_issues.append("Segment 编号必须从 1 开始连续递增")

    source_duration = _source_duration_seconds(source_text)
    expected_segment_count = math.ceil(source_duration / 10 - 1e-9) if source_duration else None
    if expected_segment_count is not None and len(segments) != expected_segment_count:
        omni_issues.append(
            f"Segment 数量必须遵循原 9994 的固定 10 秒分段：来源有效时长 {source_duration:.3f} 秒，"
            f"应为 {expected_segment_count} 段，当前为 {len(segments)} 段"
        )

    defined_characters: list[str] = []
    character_descriptions: dict[str, str] = {}
    segment_durations: list[float] = []
    output_has_spoken_audio = False
    for index, match in enumerate(segments):
        number = int(match.group("number"))
        block = content[match.start() : segments[index + 1].start() if index + 1 < len(segments) else len(content)]
        segment_range = SEGMENT_RANGE_RE.fullmatch(match.group("range").strip())
        segment_end: float | None = None
        if segment_range is None:
            omni_issues.append(f"Segment {number} 标题时间格式不正确")
        else:
            segment_start = _seconds(segment_range.group("start"))
            segment_end = _seconds(segment_range.group("end"))
            segment_duration = segment_end - segment_start
            segment_durations.append(segment_duration)
            if abs(segment_start) > 0.001:
                omni_issues.append(f"Segment {number} 标题必须从 00:00.000 开始")
            if segment_duration <= 0 or segment_duration > 10.002:
                omni_issues.append(f"Segment {number} 有效内容时长必须大于 0 且不超过 10 秒")
            if index < len(segments) - 1 and abs(segment_duration - 10) > 0.002:
                omni_issues.append(f"Segment {number} 不是最后一段，必须承载完整 10 秒有效内容")
            if expected_segment_count == len(segments) and source_duration is not None:
                expected_duration = 10.0 if index < len(segments) - 1 else source_duration - 10 * index
                if abs(segment_duration - expected_duration) > 0.002:
                    omni_issues.append(
                        f"Segment {number} 时长应为 {expected_duration:.3f} 秒，当前为 {segment_duration:.3f} 秒"
                    )
        a_heading = block.find("## A. 人物造型参考板提示词")
        b_heading = block.find("## B. 故事板图片提示词")
        if a_heading < 0 or b_heading < 0 or b_heading <= a_heading:
            omni_issues.append(f"Segment {number} 缺少按顺序排列的 A 区和 B 区")
            continue
        a_body = block[a_heading:b_heading]
        a_fields = list(A_FIELD_RE.finditer(a_body))
        a_names = [field.group("name") for field in a_fields[:3]]
        if a_names != ["角色ID", "生成方式", "参考来源"]:
            omni_issues.append(f"Segment {number} A 区必须依次包含角色ID、生成方式和参考来源")
        else:
            a_values = {field.group("name"): field.group("value").strip() for field in a_fields[:3]}
            role_value = a_values["角色ID"]
            mode = a_values["生成方式"]
            reference_value = a_values["参考来源"]
            role_ids = [value.lower() for value in re.findall(r"character_\d{2,}", role_value, re.I)]
            if mode not in OMNI_GENERATION_MODES:
                omni_issues.append(f"Segment {number} A 区生成方式无效：{mode}")
            if mode in {"首次生成", "无人物场景"} and reference_value != "无":
                omni_issues.append(f"Segment {number} 使用{mode}时参考来源必须为“无”")
            reference_segments = [int(value) for value in re.findall(r"Segment\s*(\d+)", reference_value, re.I)]
            if mode in {"直接复用", "状态更新", "新角色合并"}:
                if not reference_segments:
                    omni_issues.append(f"Segment {number} 使用{mode}时必须引用更早的真实参考板 Segment")
                elif any(value >= number for value in reference_segments):
                    omni_issues.append(f"Segment {number} 参考来源只能指向当前段之前的 Segment")
            if mode == "无人物场景":
                if role_value != "无" or role_ids:
                    omni_issues.append(f"Segment {number} 无人物场景的角色ID必须为“无”")
            elif not role_ids:
                omni_issues.append(f"Segment {number} A 区缺少 character_XX 角色ID")

            new_ids = [role_id for role_id in role_ids if role_id not in defined_characters]
            if mode in {"直接复用", "状态更新"} and new_ids:
                omni_issues.append(f"Segment {number} 使用{mode}时不得定义新角色：{new_ids}")
            if mode == "首次生成" and any(role_id in defined_characters for role_id in role_ids):
                omni_issues.append(f"Segment {number} 首次生成不得重复定义已有角色")
            if mode == "新角色合并" and not new_ids:
                omni_issues.append(f"Segment {number} 使用新角色合并时必须至少定义一个新角色")
            for role_id in new_ids:
                expected_id = f"character_{len(defined_characters) + 1:02d}"
                if role_id != expected_id:
                    omni_issues.append(
                        f"Segment {number} 角色ID不连续：写成 {role_id}，应为 {expected_id}"
                    )
                if role_id not in defined_characters:
                    defined_characters.append(role_id)
            for description_match in CHARACTER_DESCRIPTION_RE.finditer(a_body):
                character_descriptions[description_match.group("role_id").lower()] = (
                    description_match.group("description").strip()
                )
        b_body = block[b_heading:]
        if re.search(r"图\s*3\s*是人物造型参考板|严格参考图\s*2\s*[、,，和及与]\s*图\s*3", b_body):
            omni_issues.append(f"Segment {number} 声明了额外人物参考图；Omni 每段只能使用图1和图2")
        if "[TECHNICAL_PADDING: BLACK_SILENT]" in block:
            omni_issues.append(f"Segment {number} 未收到技术补位要求，不得输出 BLACK_SILENT 标记")
        shots = list(SHOT_RE.finditer(b_body))
        if not shots:
            omni_issues.append(f"Segment {number} B 区没有可识别镜头")
            continue
        shot_numbers = [int(shot.group("number")) for shot in shots]
        if shot_numbers != list(range(1, len(shots) + 1)):
            omni_issues.append(f"Segment {number} 镜头编号必须从 1 开始连续递增")
        previous_end = 0.0
        for shot_index, shot in enumerate(shots):
            shot_number = int(shot.group("number"))
            start = _seconds(shot.group("start"))
            end = _seconds(shot.group("end"))
            if shot_index == 0 and abs(start) > 0.001:
                omni_issues.append(f"Segment {number} 镜头 1 必须从 00:00.000 开始")
            if abs(start - previous_end) > 0.002 or end <= start:
                omni_issues.append(f"Segment {number} 镜头 {shot_number} 时间必须连续且结束晚于开始")
            previous_end = end
            shot_block = b_body[shot.end() : shots[shot_index + 1].start() if shot_index + 1 < len(shots) else len(b_body)]
            field_matches = list(FIELD_RE.finditer(shot_block))
            fields = [field.group("name") for field in field_matches]
            if fields != list(OMNI_FIELDS):
                omni_issues.append(
                    f"Segment {number} 镜头 {shot_number} 必须恰好按顺序包含 9 个字段"
                )
            else:
                field_values = {field.group("name"): field.group("value") for field in field_matches}
                subject_value = field_values["主体"]
                subject_role_matches = list(CHARACTER_ID_RE.finditer(subject_value))
                for role_index, role_match in enumerate(subject_role_matches):
                    role_id = role_match.group(0).lower()
                    if role_id not in character_descriptions:
                        omni_issues.append(
                            f"Segment {number} 镜头 {shot_number} [主体] 中 {role_id} "
                            "在 A 区没有可用于自动填入的角色描述"
                        )
                        continue
                    next_role_start = (
                        subject_role_matches[role_index + 1].start()
                        if role_index + 1 < len(subject_role_matches)
                        else len(subject_value)
                    )
                    if not _subject_role_has_description(subject_value, role_match, next_role_start):
                        omni_issues.append(
                            f"Segment {number} 镜头 {shot_number} [主体] 中 {role_id} "
                            "缺少展开后的人物描述；不能只写角色ID、代词或身体局部"
                        )
                content_issues.extend(
                    _product_visual_issues(
                        list(field_values.items()), fact_card, f"Segment {number} 镜头 {shot_number}"
                    )
                )
                audio_value = field_values["音频文案"]
                if "中文翻译" in audio_value:
                    omni_issues.append(f"Segment {number} 镜头 {shot_number} 音频文案不得保留中文翻译对照")
                if classify_audio_content(audio_value) == "spoken":
                    output_has_spoken_audio = True
                    metrics = spoken_audio_metrics(audio_value)
                    duration = end - start
                    uses_cjk_budget = metrics["cjk_count"] >= 2 and metrics["word_count"] <= 2
                    actual = metrics["cjk_count"] if uses_cjk_budget else metrics["word_count"]
                    maximum = math.ceil(duration * (6.5 if uses_cjk_budget else 3.8))
                    if actual > maximum:
                        unit = "字" if uses_cjk_budget else "词"
                        content_issues.append(
                            f"Segment {number} 镜头 {shot_number} 真实口播超过镜头容量："
                            f"{duration:.3f} 秒内 {actual} {unit}，硬上限 {maximum} {unit}"
                        )
                for role_id in re.findall(r"character_\d{2,}", "\n".join(field_values.values()), re.I):
                    normalized = role_id.lower()
                    if normalized not in defined_characters:
                        omni_issues.append(
                            f"Segment {number} 镜头 {shot_number} 引用了未定义角色 {normalized}"
                        )
        if segment_end is not None and shots and abs(previous_end - segment_end) > 0.002:
            omni_issues.append(f"Segment {number} 最后一个镜头结束时间必须与 Segment 标题一致")
        if re.search(r"(?m)^-\s*\[(?:字幕|贴纸|特效|声音/语气|音频交付模式|环境音/音效)\]", b_body):
            omni_issues.append(f"Segment {number} B 区泄漏了 9993 内部字段，必须按 9994 规则过滤")

    if source_duration is not None and len(segment_durations) == len(segments):
        total_duration = sum(segment_durations)
        if abs(total_duration - source_duration) > 0.002:
            omni_issues.append(
                f"全部 Segment 有效内容总时长必须与来源一致：来源 {source_duration:.3f} 秒，"
                f"当前 {total_duration:.3f} 秒"
            )
    content_issues.extend(_source_content_issues(source_text, content, output_has_spoken_audio))
    layered = [f"[9993 内容创作] {issue}" for issue in dict.fromkeys(content_issues)]
    layered.extend(f"[9994 Omni 适配] {issue}" for issue in dict.fromkeys(omni_issues))
    return layered


def validate_seedance_markdown(text: str, fact_card: str = "") -> list[str]:
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
        segment_range = SEGMENT_RANGE_RE.fullmatch(match.group("range").strip())
        segment_end: float | None = None
        if segment_range is None:
            issues.append(f"Segment {number} 标题时间格式不正确")
        else:
            segment_start = _seconds(segment_range.group("start"))
            segment_end = _seconds(segment_range.group("end"))
            if abs(segment_start) > 0.001:
                issues.append(f"Segment {number} 标题必须从 00:00.000 开始")
            if segment_end <= segment_start or segment_end > 15.002:
                issues.append(f"Segment {number} 有效内容时长必须大于 0 且不超过 15 秒")

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
        shots = list(SEEDANCE_SHOT_RE.finditer(b_body))
        if not shots:
            issues.append(f"Segment {number} B 区没有可识别的 Seedance 镜头")
            continue
        shot_numbers = [int(shot.group("number")) for shot in shots]
        if shot_numbers != list(range(1, len(shots) + 1)):
            issues.append(f"Segment {number} Seedance 镜头编号必须从 01 开始连续递增")

        previous_end = 0.0
        for shot_index, shot in enumerate(shots):
            shot_number = int(shot.group("number"))
            shot_block = b_body[
                shot.end() : shots[shot_index + 1].start() if shot_index + 1 < len(shots) else len(b_body)
            ]
            fields = list(SEEDANCE_FIELD_RE.finditer(shot_block))
            field_names = [field.group("name").strip() for field in fields]
            if field_names != list(SEEDANCE_FIELDS):
                issues.append(f"Segment {number} 镜头 {shot_number:02d} 必须恰好按顺序包含 7 个字段")
                continue

            values: list[str] = []
            for field_index, field in enumerate(fields):
                value_end = fields[field_index + 1].start() if field_index + 1 < len(fields) else len(shot_block)
                value = shot_block[field.end() : value_end].strip()
                value = re.sub(r"\n?---\s*$", "", value).strip()
                values.append(value)
            if any(not value for value in values):
                issues.append(f"Segment {number} 镜头 {shot_number:02d} 的 7 个字段内容均不能为空")
                continue
            issues.extend(
                _product_visual_issues(
                    list(zip(field_names, values)),
                    fact_card,
                    f"Segment {number} 镜头 {shot_number:02d}",
                )
            )

            action_value = values[1]
            dialogue_value = values[5]
            if dialogue_value != "无口播。":
                voiceover = re.search(r"发声方式[：:]\s*画外旁白", action_value)
                onscreen_speakers = re.findall(
                    r"发声方式[：:]\s*(character_\d{2})\s*画内说出台词",
                    action_value,
                )
                if bool(voiceover) == bool(onscreen_speakers) or len(onscreen_speakers) > 1:
                    issues.append(
                        f"Segment {number} 镜头 {shot_number:02d} 有台词时必须在动作/景别明确唯一发声方式"
                    )
                elif voiceover and ("画面内人物不说话" not in action_value or "不做口型" not in action_value):
                    issues.append(
                        f"Segment {number} 镜头 {shot_number:02d} 使用画外旁白时必须注明画面内人物不说话、不做口型"
                    )

            time_value = values[-1].splitlines()[0].strip()
            time_match = SEEDANCE_TIME_RE.fullmatch(time_value)
            if time_match is None:
                issues.append(f"Segment {number} 镜头 {shot_number:02d} 时间格式不正确")
                continue
            start = _seconds(time_match.group("start"))
            end = _seconds(time_match.group("end"))
            duration = float(time_match.group("duration"))
            if shot_index == 0 and abs(start) > 0.001:
                issues.append(f"Segment {number} 镜头 01 必须从 00:00.000 开始")
            if abs(start - previous_end) > 0.002 or end <= start:
                issues.append(f"Segment {number} 镜头 {shot_number:02d} 时间必须连续且结束晚于开始")
            if abs(duration - (end - start)) > 0.002:
                issues.append(f"Segment {number} 镜头 {shot_number:02d} 标注时长与起止时间不一致")
            previous_end = end

        if segment_end is not None and shots and abs(previous_end - segment_end) > 0.002:
            issues.append(f"Segment {number} 最后一个镜头结束时间必须与 Segment 标题一致")
        if re.search(r"(?m)^\*\*(?:字幕|贴纸|屏幕文字|特效)[：:]\*\*\s*$", b_body):
            issues.append(f"Segment {number} Seedance 分镜不得输出字幕、贴纸、屏幕文字或特效字段")
    return list(dict.fromkeys(issues))


def _validator_for_model(
    model: str,
    fact_card: str = "",
    source_text: str = "",
) -> Callable[[str], list[str]]:
    if model == "seedance":
        return lambda text: validate_seedance_markdown(text, fact_card)
    return lambda text: validate_omni_markdown(text, fact_card, source_text)


def normalize_seedance_markdown(markdown: str) -> str:
    def replace_field(match: re.Match[str]) -> str:
        header = f"**{match.group('bold_name') or match.group('plain_name')}：**"
        value = (match.group("value") or "").strip()
        return f"{header}\n{value}" if value else header

    return SEEDANCE_LOOSE_FIELD_RE.sub(replace_field, markdown)


def _repair_prompt(
    candidate: str,
    issues: list[str],
    model: str = "omni",
    source_text: str = "",
) -> str:
    _preamble, blocks = load_prompt_blocks()
    if model == "seedance":
        return f"""{blocks['REPAIR_SEEDANCE']}

# 本次 Seedance 修复输入

错误：
{chr(10).join(f'- {issue}' for issue in issues)}

<REPAIR_CONTEXT>
{candidate}
</REPAIR_CONTEXT>
"""
    source_context = f"""
<SOURCE_SCRIPT>
{source_text.strip()}
</SOURCE_SCRIPT>
""" if source_text.strip() else ""
    return f"""{blocks['REPAIR']}

# 本次局部修复输入

错误：
{chr(10).join(f'- {issue}' for issue in issues)}

请只修正导致上述错误的局部内容，严格按上方规则返回 JSON 替换列表，不要返回完整 Markdown 或解释。
标记为 `[9993 内容创作]` 的错误必须以来源脚本为准恢复主体类型、剧情、音频结构或口播容量，同时保持既有 Omni 分段结构不变。
标记为 `[9994 Omni 适配]` 的错误只修正分段、时间、角色参考板或九字段格式，不得改写 9993 已确定的内容。
若错误涉及产品视觉描述，请把对应字段的完整内容作为 old 并重写该字段：保留人物动作与手机、水管、塑料桶、手套等剧情道具；真正带货商品只能写成 [产品] 或 [手持产品]，不得改写成裸写“产品”“商品”，也不得保留任何产品颜色、形状、包装、标签、膏体颜色、质地或材质。
{source_context}

<REPAIR_CONTEXT>
{candidate}
</REPAIR_CONTEXT>
"""


def _apply_omni_repair(candidate: str, response: str) -> str:
    content = str(response or "").strip()
    fence = JSON_FENCE_RE.fullmatch(content)
    if fence:
        content = fence.group("body").strip()
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("未返回合法 JSON 替换列表") from exc
    replacements = payload.get("replacements") if isinstance(payload, dict) else None
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("JSON 中缺少非空 replacements 列表")
    repaired = candidate
    for replacement in replacements:
        if not isinstance(replacement, dict):
            raise ValueError("replacements 每一项都必须是 object")
        old = replacement.get("old")
        new = replacement.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("每项 replacement 必须包含非空 old 和字符串 new")
        if old not in repaired:
            raise ValueError("replacement.old 必须存在于当前稿中")
        repaired = repaired.replace(old, new)
    return repaired


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
        if payload["model"] == "seedance":
            return current.pure_seedance_output_root / product
        return current.pure_output_root / product
    source = Path(payload["source_path"])
    if payload["model"] == "seedance":
        return current.hybrid_seedance_output_root / payload["content_type"] / product / source.stem
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
    validator = _validator_for_model(payload["model"], fact_card, source_text)
    if not variant_number and output_path.is_file():
        existing = output_path.read_text(encoding="utf-8", errors="ignore")
        materialized_existing = False
        if payload["model"] == "omni":
            materialized = materialize_omni_character_subjects(existing)
            if materialized != existing:
                existing = materialized
                materialized_existing = True
        if not validator(existing):
            if materialized_existing:
                _write_output(output_path, existing)
                progress(f"已从 A 区自动补全 B 区人物描述：{output_path.name}")
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
    if payload["model"] == "seedance":
        candidate = normalize_seedance_markdown(candidate)
    else:
        candidate = materialize_omni_character_subjects(candidate)
    issues = validator(candidate)
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        if not issues:
            break
        progress(f"{label} 第 {attempt} 次校验未通过，只修复失败内容：{'；'.join(issues[:3])}")
        repair_response = _call_model(
            _repair_prompt(candidate, issues, payload["model"], source_text),
            "repair",
            f"{label} 局部修复",
        )
        if payload["model"] == "seedance":
            candidate = normalize_seedance_markdown(repair_response)
        else:
            try:
                candidate = _apply_omni_repair(candidate, repair_response)
                candidate = materialize_omni_character_subjects(candidate)
            except ValueError as exc:
                progress(f"{label} 第 {attempt} 次局部修复响应不可用：{exc}")
                continue
        issues = validator(candidate)
    if issues:
        raise RuntimeError(f"{MODEL_LABELS[payload['model']]} 输出校验失败：" + "；".join(issues))
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
        f"任务已确认：{ROUTE_LABELS[task['route']]} / {MODE_LABELS[task['mode']]} / "
        f"{MODEL_LABELS[task['model']]} / "
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
