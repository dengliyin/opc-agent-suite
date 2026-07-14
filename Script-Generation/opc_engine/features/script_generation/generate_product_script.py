#!/usr/bin/env python3
import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from opc_engine.features.script_generation.modelmesh_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    endpoint_variants,
    extract_text,
    get_api_key,
    post_json,
)
from opc_engine.core.project_assets import (
    ensure_project_dirs,
    infer_source_id,
    product_profile_path,
    product_project_ready,
    require_product_project,
)


ROOT = Path(__file__).resolve().parents[3]
FEATURE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = FEATURE_DIR / "config"
LOCAL_INPUTS_PATH = CONFIG_DIR / "inputs.json"
SCRIPT_INPUTS_PATH = Path(os.environ.get("SCRIPT_GENERATION_INPUTS_PATH", str(LOCAL_INPUTS_PATH))).expanduser()
LOCAL_MODEL_SETTINGS_PATH = CONFIG_DIR / "model_settings.json"
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault"))
).expanduser()
SCRIPT_OUTPUT_SOURCE_ROOT = VAULT_ROOT / "wiki" / "视频" / "05产品视频脚本"
DEFAULT_PROMPT_PATH = CONFIG_DIR / "script_generation_rewrite_prompt.md"
DEFAULT_PROMPT_CONFIG_PATH = "opc_engine/features/script_generation/config/script_generation_rewrite_prompt.md"
DEFAULT_MUTATION_PROMPT_PATH = CONFIG_DIR / "script_generation_mutation_prompt.md"
DEFAULT_MUTATION_PROMPT_CONFIG_PATH = "opc_engine/features/script_generation/config/script_generation_mutation_prompt.md"
LEGACY_CONTENT_KNOWLEDGE_CONFIG_PATH = "opc_engine/features/script_generation/config/cross_border_ecommerce_knowledge_base.md"
DEFAULT_CONTENT_KNOWLEDGE_PATH = VAULT_ROOT / "wiki" / "视频" / "07错题本"
DEFAULT_CONTENT_KNOWLEDGE_CONFIG_PATH = DEFAULT_CONTENT_KNOWLEDGE_PATH.as_posix()
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_OUTPUT_TOKENS = 24000
DEFAULT_MUTATION_VARIANTS = 3
DEFAULT_MUTATION_BATCH_SIZE = 2
MUTATION_RUN_TS_FORMAT = "%Y%m%d-%H%M%S"
API_CONCURRENCY_STATE_PATH = Path(
    os.environ.get("KESAI_API_CONCURRENCY_STATE_PATH", "/tmp/kesai_script_generation_api_slots.json")
)
API_CONCURRENCY_STALE_SECONDS = 60 * 60 * 2
COUNTRY_DEFAULT_LANGUAGE = {
    "美国": "英语",
    "united states": "英语",
    "usa": "英语",
    "us": "英语",
    "英国": "英语",
    "united kingdom": "英语",
    "uk": "英语",
    "gb": "英语",
    "法国": "法语",
    "france": "法语",
    "fr": "法语",
    "西班牙": "西班牙语",
    "spain": "西班牙语",
    "es": "西班牙语",
    "德国": "德语",
    "germany": "德语",
    "de": "德语",
    "越南": "越南语",
    "vietnam": "越南语",
    "vn": "越南语",
    "菲律宾": "菲律宾语",
    "philippines": "菲律宾语",
    "ph": "菲律宾语",
    "马来西亚": "马来语",
    "malaysia": "马来语",
    "my": "马来语",
    "孟加拉": "孟加拉语",
    "孟加拉国": "孟加拉语",
    "bangladesh": "孟加拉语",
    "bd": "孟加拉语",
    "爱尔兰": "英语",
    "ireland": "英语",
    "ie": "英语",
}
ENGLISH_VARIANT_BY_COUNTRY = {
    "美国": "美式英语 / American English",
    "united states": "美式英语 / American English",
    "usa": "美式英语 / American English",
    "us": "美式英语 / American English",
    "英国": "英式英语 / British English",
    "united kingdom": "英式英语 / British English",
    "uk": "英式英语 / British English",
    "gb": "英式英语 / British English",
    "爱尔兰": "爱尔兰英语 / Irish English（英式拼写倾向）",
    "ireland": "爱尔兰英语 / Irish English（英式拼写倾向）",
    "ie": "爱尔兰英语 / Irish English（英式拼写倾向）",
}
COUNTRY_FILENAME_CODE = {
    "美国": "US",
    "美國": "US",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "英国": "UK",
    "英國": "UK",
    "united kingdom": "UK",
    "uk": "UK",
    "gb": "UK",
    "爱尔兰": "IE",
    "愛爾蘭": "IE",
    "ireland": "IE",
    "ie": "IE",
    "法国": "FR",
    "法國": "FR",
    "france": "FR",
    "fr": "FR",
    "西班牙": "ES",
    "spain": "ES",
    "es": "ES",
    "德国": "DE",
    "德國": "DE",
    "germany": "DE",
    "de": "DE",
    "意大利": "IT",
    "義大利": "IT",
    "italy": "IT",
    "it": "IT",
    "越南": "VN",
    "vietnam": "VN",
    "vn": "VN",
    "菲律宾": "PH",
    "philippines": "PH",
    "ph": "PH",
    "墨西哥": "MX",
    "mexico": "MX",
    "mx": "MX",
    "巴西": "BR",
    "brazil": "BR",
    "br": "BR",
    "泰国": "TH",
    "泰國": "TH",
    "thailand": "TH",
    "th": "TH",
    "马来西亚": "MY",
    "馬來西亞": "MY",
    "malaysia": "MY",
    "my": "MY",
    "孟加拉": "BD",
    "孟加拉国": "BD",
    "孟加拉國": "BD",
    "bangladesh": "BD",
    "bd": "BD",
    "尼泊尔": "NP",
    "尼泊爾": "NP",
    "nepal": "NP",
    "np": "NP",
    "印度尼西亚": "ID",
    "印尼": "ID",
    "indonesia": "ID",
    "id": "ID",
    "加拿大": "CA",
    "canada": "CA",
    "ca": "CA",
    "澳大利亚": "AU",
    "澳洲": "AU",
    "australia": "AU",
    "au": "AU",
}
IGNORED_CONFIG_FIELDS = {"_说明", "_字段说明", "_comment", "_comments", "_note", "_notes"}
PRODUCT_DOCUMENT_PATH_KEYS = (
    "script_product_document_path",
    "product_document_path",
    "product_doc_path",
    "product_profile_path",
)
REFERENCE_PATH_KEYS = (
    "script_reference_analysis_path",
    "script_reference_script_path",
    "reference_script_path",
)

PRODUCT_FIELD_LABELS = {
    "market": "市场 / 地区",
    "collection_date": "收集日期",
    "product_name": "产品名",
    "english_name": "英文名",
    "category": "类目",
    "spec": "规格",
    "colors": "色号",
    "action_time": "作用时间",
    "regular_price": "日常价",
    "promo_price": "活动价",
    "top_selling_points": "TOP 3 核心卖点",
    "audience_pain_matrix": "目标人群 x 痛点矩阵",
    "pain_conversion_talk_tracks": "核心痛点与转化话术",
    "tiktok_marketing_angles": "TikTok 营销推广切入点",
    "market_keywords": "市场关键词参考",
    "material_type_suggestions": "适配素材类型建议",
    "notes": "补充备注",
}


def log(message):
    print(message, flush=True)


def max_api_concurrency(config=None):
    configured = (
        os.environ.get("KESAI_MAX_API_CONCURRENT_REQUESTS")
        or os.environ.get("KESAI_MAX_API_CONCURRENCY")
        or ((config or {}).get("script_generation_api_concurrency") if config else "")
        or "10"
    )
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 10


def _read_api_slot_state(lock_file):
    lock_file.seek(0)
    raw = lock_file.read().strip()
    if not raw:
        return {"queue": [], "active": {}}
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return {"queue": [], "active": {}}
    if not isinstance(state, dict):
        return {"queue": [], "active": {}}
    queue = state.get("queue") if isinstance(state.get("queue"), list) else []
    active = state.get("active") if isinstance(state.get("active"), dict) else {}
    return {"queue": [str(item) for item in queue], "active": {str(k): float(v) for k, v in active.items()}}


def _write_api_slot_state(lock_file, state):
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(json.dumps(state, ensure_ascii=False))
    lock_file.flush()
    os.fsync(lock_file.fileno())


@contextlib.contextmanager
def global_api_slot(task_name, config=None):
    max_slots = max_api_concurrency(config)
    token = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"
    state_path = API_CONCURRENCY_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    wait_started_at = time.time()
    wait_logged = False
    acquired = False
    while not acquired:
        with state_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = _read_api_slot_state(lock_file)
            now = time.time()
            active = {
                key: value
                for key, value in state["active"].items()
                if now - float(value or 0) < API_CONCURRENCY_STALE_SECONDS
            }
            queue = [item for item in state["queue"] if item not in active]
            if token not in queue and token not in active:
                queue.append(token)
            if queue and queue[0] == token and len(active) < max_slots:
                queue.pop(0)
                active[token] = now
                acquired = True
            state = {"queue": queue, "active": active}
            _write_api_slot_state(lock_file, state)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        if not acquired:
            if not wait_logged or time.time() - wait_started_at > 10:
                log(f"{task_name} 等待 API 并发槽位：上限 {max_slots}，按触发顺序排队")
                wait_started_at = time.time()
                wait_logged = True
            time.sleep(0.5)
    try:
        log(f"{task_name} 获取 API 并发槽位：上限 {max_slots}")
        yield
    finally:
        with state_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = _read_api_slot_state(lock_file)
            state["active"].pop(token, None)
            state["queue"] = [item for item in state["queue"] if item != token]
            _write_api_slot_state(lock_file, state)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def resolve_project_path(value, default_path=None):
    raw_value = str(value or "").strip()
    if not raw_value and default_path:
        return default_path.resolve()
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def read_text_file(path):
    return path.read_text(encoding="utf-8").strip()


def is_inside_directory(path, directory):
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def resolve_feature_config_path(value, default_path):
    text = str(value or "").strip()
    if not text:
        return default_path.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not is_inside_directory(path, CONFIG_DIR):
        return default_path.resolve()
    return path


def read_json_config(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if key not in IGNORED_CONFIG_FIELDS and not key.startswith("_")}


def load_script_generation_config():
    config = {}
    config.update(read_json_config(LOCAL_MODEL_SETTINGS_PATH))
    config.update(read_json_config(SCRIPT_INPUTS_PATH))
    return config


def get_prompt_template(config):
    prompt_path = resolve_feature_config_path(config.get("script_generation_prompt_path"), DEFAULT_PROMPT_PATH)
    if not prompt_path.exists():
        raise SystemExit(f"复刻提示词文件不存在: {prompt_path}")
    return read_text_file(prompt_path)


def mutation_mode(config):
    return "standard"


def mutation_prompt_path_for_mode(config):
    return DEFAULT_MUTATION_PROMPT_PATH


def get_mutation_prompt_template(config):
    configured_path = str(config.get("script_generation_mutation_prompt_path") or "").strip()
    builtin_paths = {
        "",
        DEFAULT_MUTATION_PROMPT_CONFIG_PATH,
        str(DEFAULT_MUTATION_PROMPT_PATH),
    }
    legacy_mutation_prompt_name = "script_generation_mutation_" + "adv" + "anced_prompt.md"
    if Path(configured_path).name == legacy_mutation_prompt_name:
        configured_path = DEFAULT_MUTATION_PROMPT_CONFIG_PATH
    default_path = mutation_prompt_path_for_mode(config)
    prompt_path = (
        default_path.resolve()
        if configured_path in builtin_paths
        else resolve_feature_config_path(configured_path, default_path)
    )
    if not prompt_path.exists():
        raise SystemExit(f"裂变提示词文件不存在: {prompt_path}")
    return read_text_file(prompt_path)


def resolve_content_knowledge_path(configured):
    text = str(configured or "").strip()
    if not text or text == LEGACY_CONTENT_KNOWLEDGE_CONFIG_PATH:
        return DEFAULT_CONTENT_KNOWLEDGE_PATH.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve() if path.exists() else DEFAULT_CONTENT_KNOWLEDGE_PATH.resolve()


def product_mistake_book_file(config, directory):
    product_name = product_output_name(config)
    candidates = [product_name]
    profile = (config or {}).get("product_profile", {}) or {}
    candidates.extend([profile.get("product_name", ""), profile.get("english_name", "")])
    product_doc = str((config or {}).get("script_product_document_path", "") or "").strip()
    if product_doc:
        candidates.append(Path(product_doc).expanduser().stem.replace("-产品信息", "").strip())
    normalized = {safe_output_name(strip_import_timestamp_prefix(value)).lower() for value in candidates if value}
    for value in candidates:
        if not value:
            continue
        direct = directory / f"{strip_import_timestamp_prefix(value).replace('-产品信息', '').strip()}.md"
        if direct.is_file():
            return direct
    for path in sorted(directory.glob("*.md"), key=lambda p: p.name.lower()):
        if safe_output_name(strip_import_timestamp_prefix(path.stem).replace("-产品信息", "")).lower() in normalized:
            return path
    return None


def get_content_knowledge_base(config):
    configured = (
        config.get("script_content_knowledge_base_path")
        or config.get("content_knowledge_base_path")
        or config.get("video_teardown_knowledge_base_path")
    )
    knowledge_path = resolve_content_knowledge_path(configured)
    if knowledge_path.is_dir():
        matched_path = product_mistake_book_file(config, knowledge_path)
        if not matched_path:
            return ""
        text = read_text_file(matched_path).strip()
        if not text:
            return ""
        return f"# 错题本\n\n来源文件：{matched_path.as_posix()}\n\n---\n\n## {matched_path.name}\n\n{text}"
    if knowledge_path.exists():
        return read_text_file(knowledge_path)
    return ""


def product_profile_to_markdown(profile):
    lines = []
    for key, label in PRODUCT_FIELD_LABELS.items():
        value = str((profile or {}).get(key, "") or "").strip()
        if value:
            lines.append(f"## {label}\n{value}")
    return "\n\n".join(lines).strip() or "未填写产品信息。"


def get_product_manual(config):
    candidates = []
    for key in PRODUCT_DOCUMENT_PATH_KEYS:
        configured = str(config.get(key, "") or "").strip()
        if configured:
            candidates.append(resolve_project_path(configured))
    candidates.append(product_profile_path(config))
    for product_path in candidates:
        if product_path.exists():
            text = read_text_file(product_path)
            if text:
                return text
    return product_profile_to_markdown(config.get("product_profile", {}))


def get_reference_path(config):
    preferred_keys = REFERENCE_PATH_KEYS
    if "脚本" in str(config.get("script_reference_kind", "") or ""):
        preferred_keys = (
            "script_reference_script_path",
            "reference_script_path",
            "script_reference_analysis_path",
        )
    for key in preferred_keys:
        value = str(config.get(key, "") or "").strip()
        if value:
            return resolve_project_path(value)
    raise SystemExit("请先选择有效的爆款参考文件：竞品爆款脚本或竞品视频拆解 Markdown")


def get_reference_label(config):
    configured = str(config.get("script_reference_kind", "") or "").strip()
    if configured:
        return configured
    if str(config.get("script_reference_script_path", "") or config.get("reference_script_path", "") or "").strip():
        return "竞品爆款脚本"
    return "竞品视频拆解结果"


def safe_output_name(value):
    text = str(value or "").strip() or "product_script"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text).strip("_") or "product_script"


def strip_import_timestamp_prefix(value):
    parts = str(value or "").strip().split("_", 2)
    if len(parts) == 3 and len(parts[0]) == 8 and parts[0].isdigit() and len(parts[1]) == 6 and parts[1].isdigit():
        return parts[2]
    return str(value or "").strip()


def parse_bool(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "启用", "是"}


def preserves_original_script(value):
    return str(value or "").strip() in {"", "不改变原脚本", "跟随原脚本", "保持原脚本", "不变"}


def parse_duration_seconds(value):
    text = str(value or "").strip()
    if preserves_original_script(text):
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:秒|s|sec|secs|second|seconds)?", text, re.I)
    if match:
        return float(match.group(1))
    match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", text)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        millis = int((match.group(4) or "0").ljust(3, "0")[:3])
        return hours * 3600 + minutes * 60 + seconds + millis / 1000
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", text)
    if match:
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2) or 0)
        millis = int((match.group(3) or "0").ljust(3, "0")[:3])
        return minutes * 60 + seconds + millis / 1000
    return None


def target_total_duration_seconds(config):
    return parse_duration_seconds((config or {}).get("script_total_duration", ""))


def format_timecode(seconds):
    total_millis = max(0, int(round(float(seconds or 0) * 1000)))
    minutes, remainder = divmod(total_millis, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def parse_timestamp_seconds(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", text)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        millis = int((match.group(4) or "0").ljust(3, "0")[:3])
        return hours * 3600 + minutes * 60 + seconds + millis / 1000
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", text)
    if match:
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2) or 0)
        millis = int((match.group(3) or "0").ljust(3, "0")[:3])
        return minutes * 60 + seconds + millis / 1000
    return None


TIMECODE_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?:\.\d{1,3})?)\s*(?P<sep>[-~—至到]+)\s*(?P<end>\d{1,2}:\d{2}(?:\.\d{1,3})?)"
)


def extract_timecode_ranges(text):
    ranges = []
    for match in TIMECODE_RANGE_PATTERN.finditer(str(text or "")):
        start = parse_timestamp_seconds(match.group("start"))
        end = parse_timestamp_seconds(match.group("end"))
        if start is None or end is None:
            continue
        ranges.append((start, end, match.group(0)))
    return ranges


def enforce_configured_total_duration(config, text):
    target_seconds = target_total_duration_seconds(config)
    content = str(text or "")
    if target_seconds is None or not content.strip():
        return content, []

    ranges = extract_timecode_ranges(content)
    if not ranges:
        return content, [f"时间码警告: 已指定视频总时长 {target_seconds:g} 秒，但输出中未识别到镜头时间码。"]

    final_end = max(end for _start, end, _raw in ranges)
    if final_end <= 0:
        return content, [f"时间码警告: 已指定视频总时长 {target_seconds:g} 秒，但输出时间码结束时间无效。"]
    if abs(final_end - target_seconds) <= 0.15:
        return content, []

    ratio = target_seconds / final_end

    def replace_range(match):
        start = parse_timestamp_seconds(match.group("start"))
        end = parse_timestamp_seconds(match.group("end"))
        if start is None or end is None:
            return match.group(0)
        return f"{format_timecode(start * ratio)} - {format_timecode(end * ratio)}"

    scaled = TIMECODE_RANGE_PATTERN.sub(replace_range, content)
    return scaled, [
        "时间码已自动缩放: "
        f"结构化变量要求 {target_seconds:g} 秒，但模型输出结束在 {final_end:g} 秒；"
        f"已按比例缩放所有镜头时间码到 {format_timecode(target_seconds)}。"
    ]


def normalized_target_language(config):
    country = str((config or {}).get("script_country", "") or "").strip()
    target_language = str((config or {}).get("script_target_language", "") or "").strip()
    if preserves_original_script(target_language):
        return target_language
    language_key = target_language.lower()
    country_key = country.lower()
    if target_language in {"英语", "英文"} or language_key in {"english", "en"}:
        return ENGLISH_VARIANT_BY_COUNTRY.get(country) or ENGLISH_VARIANT_BY_COUNTRY.get(country_key) or target_language
    if target_language in COUNTRY_DEFAULT_LANGUAGE or language_key in COUNTRY_DEFAULT_LANGUAGE:
        return COUNTRY_DEFAULT_LANGUAGE.get(target_language) or COUNTRY_DEFAULT_LANGUAGE.get(language_key) or target_language
    if country and target_language == country:
        return COUNTRY_DEFAULT_LANGUAGE.get(country) or COUNTRY_DEFAULT_LANGUAGE.get(country_key) or target_language
    return target_language


def mutation_variant_count(config, args=None):
    configured = getattr(args, "mutation_variants", 0) if args is not None else 0
    if not configured:
        configured = config.get("script_mutation_variants") or DEFAULT_MUTATION_VARIANTS
    try:
        count = int(configured)
    except (TypeError, ValueError):
        count = DEFAULT_MUTATION_VARIANTS
    return max(1, count)


def mutation_batch_size(config, args=None):
    configured = getattr(args, "mutation_batch_size", 0) if args is not None else 0
    if not configured:
        configured = config.get("script_mutation_batch_size") or DEFAULT_MUTATION_BATCH_SIZE
    try:
        size = int(configured)
    except (TypeError, ValueError):
        size = DEFAULT_MUTATION_BATCH_SIZE
    return max(1, min(5, size))


def mutation_request_concurrency(config, args=None):
    configured = os.environ.get("KESAI_SCRIPT_MUTATION_CONCURRENCY") or config.get("script_mutation_request_concurrency")
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = max_api_concurrency(config)
    return max(1, min(max_api_concurrency(config), value))


def should_run_mutation(config, args=None):
    if args is not None and parse_bool(getattr(args, "enable_mutation", "")):
        return True
    return parse_bool(config.get("script_enable_mutation_rewrite"))


def script_generation_backend(config, args=None):
    configured = str(getattr(args, "backend", "") if args is not None else "").strip()
    if not configured:
        configured = str(config.get("script_generation_backend", "") or "").strip()
    return (configured or "api").lower().replace("-", "_")


def build_generation_prompt(config):
    reference_path = get_reference_path(config)
    reference_label = get_reference_label(config)
    if not reference_path.exists():
        raise SystemExit(f"请先选择有效的爆款参考文件: {reference_path}")
    if reference_path.suffix.lower() != ".md":
        raise SystemExit(f"爆款参考文件必须是 Markdown 文件: {reference_path.name}")

    use_generation_prompt = parse_bool(config.get("script_use_generation_prompt", True))
    prompt_template = get_prompt_template(config) if use_generation_prompt else ""
    content_knowledge = get_content_knowledge_base(config)
    product_manual = get_product_manual(config)
    competitor_reference = read_text_file(reference_path)

    total_duration = str(config.get("script_total_duration", "") or "").strip()
    target_duration_seconds = target_total_duration_seconds(config)
    country = str(config.get("script_country", "") or "").strip()
    target_language = normalized_target_language(config)
    duration_instruction = (
        f"请将新脚本严格控制为 {total_duration}。这是硬性结构化变量，优先级高于参考爆款内容。"
        f"如果参考爆款原视频不是 {total_duration}，不得沿用原时间码，必须按原镜头节奏比例重新压缩/拉伸每个镜头时间码；"
        f"最后一个镜头的结束时间必须是 {format_timecode(target_duration_seconds)}。"
        if not preserves_original_script(total_duration)
        else f"未单独指定；请跟随{reference_label}中的原视频总时长，并保持原视频的镜头时长比例。"
    )
    source_country, _source_author, _source_id = reference_country_author_and_video_id(reference_path)
    source_country_note = source_country or "未从文件名识别"
    country_instruction = (
        f"本次脚本必须面向 {country} 市场/地区；参考爆款来源国家/地区为 {source_country_note}。"
        f"如果两者不同，必须把 [主体] 的人物肤色/族裔气质/发型服装、[在场景中] 的空间陈设/消费语境、"
        f"以及本地化表达调整为 {country} 市场自然可信的版本；但必须保留参考脚本的人物数量、角色功能、年龄段、动作路径、镜头功能、情绪节奏和 CTA 位置。"
        if not preserves_original_script(country)
        else f"未单独指定；请跟随{reference_label}中的国家/地区语境。"
    )
    language_instruction = (
        f"本次脚本的口播、字幕、贴纸文案、屏幕文字和音频交付说明必须使用 {target_language}；中文翻译可作为对照保留。"
        f"如果目标语言包含 American English，必须使用美国市场自然表达和美式拼写；如果包含 British English，必须使用英国市场自然表达和英式拼写；如果包含 Irish English，必须使用爱尔兰市场自然表达并倾向英式拼写。"
        f"如果目标语言是“孟加拉语”，必须使用 Bengali / Bangla（优先孟加拉文字），不得使用 Malay、Bahasa Malaysia、印尼语或英语替代。"
        f"如果目标语言是“法语”，必须使用 French / Français，不得使用 Spanish / Español / 德语或原脚本语言替代。"
        if not preserves_original_script(target_language)
        else f"未单独指定；请跟随{reference_label}中的目标语言。"
    )

    variables = f"""# 系统自动导入变量（由页面结构化参数和本地文件生成）

产品手册信息：
{product_manual}

错题本：
{content_knowledge or "未匹配到当前产品的错题本。请优先参考产品手册和参考爆款内容。"}

素材框架：
请从下方{reference_label}中自动识别主框架；如果参考内容沉淀了新素材类型，则优先沿用该新素材类型。

参考爆款内容：
以下{reference_label}即为本次复刻参考对象，请平移其心理诱因、情绪节奏、转场力度和话术杀伤力。
如果输入是竞品成品脚本而不是拆解报告，请先静默还原它的镜头结构、话术结构、情绪递进、转场逻辑和 CTA 节点，再映射到我方产品。

{reference_label}：
{competitor_reference}

参考爆款情绪和节奏：
不作为独立输入调整。请直接参考{reference_label}中的情绪、语调、节奏和口播强度，并自然迁移到我方产品。

视频总时长：
{duration_instruction}

国家/地区：
{country_instruction}

目标语言：
{language_instruction}
"""
    prompt_template_block = (
        f"""
---

# 复刻规则与输出格式提示词

{prompt_template}
"""
        if prompt_template
        else ""
    )
    prompt_inputs_text = (
        "复刻提示词、参考爆款内容、产品手册信息、错题本"
        if prompt_template
        else "参考爆款内容、产品手册信息、错题本"
    )

    return f"""{variables}
{prompt_template_block}

---

# 本次额外约束

- 你正在做的是“脚本产出”：把竞品爆款视频的底层逻辑、情绪节奏、转场力度和话术杀伤力，复刻成适配我方产品的新带货视频脚本。
- 必须同时参考“{prompt_inputs_text}”；其中参考爆款内容是唯一案例来源，错题本只用于避免重复历史错误、错误卖点、错误表达、合规风险和不适合本产品的转化角度。
- 当参考爆款内容是竞品脚本时，必须先拆出它的镜头节奏、痛点递进、情绪强度、卖点进入顺序和 CTA 位置；人物数量、角色功能、年龄段、动作路径、镜头语言、光线、贴纸位置、特效和 BGM 是锁定项。若“视频总时长”已指定，则只允许按目标总时长重算时间码，不得沿用冲突的原时间码。
- 竞品里的旧产品、旧痛点、旧机制只有在与“产品手册信息”不一致或不合规时才替换；替换范围仅限产品占位、音频文案、字幕和贴纸文案中的产品信息。若“国家/地区”指定了具体市场，还必须把人物外观、服装审美、场景陈设和消费语境本地化到该市场，但不得改变镜头功能、动作路径或重写整条画面结构。
- 必须严格遵守“国家/地区、目标语言、视频总时长”三个结构化变量；这些变量优先级高于参考脚本。国家/地区指定具体市场时，[主体]、[在场景中]、[画面风格/氛围] 和本地化表达必须服务于该市场；目标语言指定具体语言时，所有口播、字幕、贴纸文案和屏幕文字必须使用该语言。尤其是视频总时长：指定了具体秒数时，所有镜头时间码必须落在该总时长内，最后一个镜头结束时间必须等于该总时长。
- 如果目标语言是孟加拉语，台词列必须输出 Bengali / Bangla 文案；字幕列可以放中文翻译对照。不得用 Malay/Bahasa 代替 Bengali。
- 如果目标语言是法语，台词列必须输出 French / Français 文案；字幕列可以放中文翻译对照。不得用 Spanish / Español、德语或原脚本语言代替法语。
- 每个镜头的 **[音频文案]** 必须输出真实目标语言台词，不能只写“目标语言口播（大意：……）”“马来语口播（大意：……）”这类说明；中文翻译对照只能放在该条音频文案最后一个括号里，禁止插在目标语言台词中间，且必须覆盖前面整段目标语言口播。
- 每个镜头的 **[音频文案]** 必须匹配镜头时长，不得比参考脚本同镜头更长，原则上不超过参考同镜头台词长度的 110%；1-2 秒镜头只能用一个短句或半句，3-4 秒镜头最多 1 个完整短句，放不下的信息必须舍弃。
- 贴纸必须最小改动：保留参考脚本里的贴纸数量、位置、颜色、层级、按钮/箭头/CTA 结构和出现镜头；贴纸文案不要重新创作，只允许把旧产品词、冲突卖点或合规风险词替换成我方产品对应表达。目标语言贴纸不得出现中外文混写，中文只能放在括号里的翻译对照。
- 拍摄设备、固定方式、支撑物、垫靠物和摆放位置只用于推导镜头视角；输出脚本时只能写成自拍视角、固定机位、低角度、平视、俯拍、仰拍、轻微手持晃动等抽象镜头语言，不得写入可见场景、动作、道具、细节或倒影。
- 不要输出拆解报告，不要解释你怎么思考，直接输出可拍摄脚本。
- 每个镜头都必须保留完整的画面、动作、光线、音效、音频文案、中文翻译和语速。
"""


def build_mutation_prompt(config, generated_script, variant_count, batch_start=1, total_variant_count=None, reference_context=""):
    prompt_template = get_mutation_prompt_template(config)
    product_manual = get_product_manual(config)
    content_knowledge = get_content_knowledge_base(config)
    reference_label = get_reference_label(config)
    reference_path = get_reference_path(config)
    country = str(config.get("script_country", "") or "").strip()
    target_language = normalized_target_language(config)
    total_duration = str(config.get("script_total_duration", "") or "").strip()
    target_duration_seconds = target_total_duration_seconds(config)
    if preserves_original_script(total_duration):
        timecode_rule = "必须保持原脚本每个镜头的时间码、镜头编号、景别/机位逻辑、情绪强度、视觉奇观底层逻辑、叙事推进顺序和 CTA 位置。"
    else:
        target_timecode = format_timecode(target_duration_seconds) if target_duration_seconds is not None else total_duration
        timecode_rule = (
            f"必须保持原脚本的镜头编号、景别/机位逻辑、情绪强度、视觉奇观底层逻辑、叙事推进顺序和 CTA 位置，"
            f"但不得沿用原脚本时间码；必须按视频总时长变量 {total_duration} 重新压缩/拉伸每个镜头时间码，"
            f"所有镜头时间码必须落在目标总时长内，最后一个镜头结束时间必须是 {target_timecode}。"
        )

    total_variant_count = total_variant_count or variant_count
    batch_end = batch_start + variant_count - 1

    return f"""# 系统自动导入变量（由程序生成）

本次任务：
你将收到“脚本产出阶段已经生成的我方产品成品脚本”。本次裂变只有一个固定流程：以复刻稿为母稿，严格参考裂变提示词、产品手册和错题本限制来做变体。
裂变不得改掉我方产品、核心卖点、价格/承诺、目标市场语言、中文翻译对照、镜头结构、时间码、情绪推进和 CTA 位置；具体可变范围以裂变提示词和错题本为准。

变体数量：
{variant_count}

本批次编号：
请只输出第 {batch_start} 到第 {batch_end} 个变体；这是总计 {total_variant_count} 个裂变脚本中的一个分批请求。

产品手册信息：
{product_manual}

错题本：
{content_knowledge or "未匹配到当前产品的错题本。裂变时必须优先保持产品手册、复刻稿和裂变提示词的一致性。"}

参考来源类型：
{reference_label}

参考来源文件名：
{reference_path.name}

国家/地区变量：
{country if not preserves_original_script(country) else "不改变原脚本"}

目标语言变量：
{target_language if not preserves_original_script(target_language) else "不改变原脚本"}

视频总时长变量：
{total_duration if not preserves_original_script(total_duration) else "不改变原脚本"}

裂变主输入：
以下内容是本次唯一需要被裂变的脚本母稿。必须围绕它保留镜头结构、台词节奏、情绪推进和 CTA 位置；若视频总时长变量不是“不改变原脚本”，时间码必须按该变量重算。
{generated_script}

{f'''
辅助参考上下文：
以下内容来自同一条视频的完整拆解 md，只用于理解爆点、心理工程、素材骨架、情绪节奏和可复用结构；不得把其中的分析文字、步骤说明、标题说明直接当成脚本正文输出。

{reference_context}
''' if reference_context else ''}

---

# 裂变提示词

{prompt_template}

---

# 本次额外约束

- 输出必须是“改写后的结果”，不要要求用户再提供原脚本，也不要输出和执行无关的说明。
- 只裂变“裂变主输入”；“辅助参考上下文”只能用于理解，不得混入最终脚本正文。
- {timecode_rule}
- 裂变阶段必须以裂变提示词和错题本为边界；只允许改提示词允许改的外观、场景、道具、光线、抽象机位角度和局部表演包装，不得改产品事实、核心卖点、承诺、目标语言和 CTA 位置。
- 如果“目标语言变量”不是“不改变原脚本”，所有裂变脚本的口播、字幕、贴纸文案、屏幕文字和音频交付说明必须使用该目标语言；不得回退到原脚本语言。
- 如果“目标语言变量”为“孟加拉语”，台词列必须输出 Bengali / Bangla 文案；字幕列可以放中文翻译对照。不得使用 Malay、Bahasa Malaysia、印尼语或英语替代。
- 如果“目标语言变量”为“马来语”，台词列必须输出 Malay / Bahasa Malaysia 文案；不得使用 Bengali、Bangla、Nepali、Hindi、天城文或英语替代。
- 如果“目标语言变量”为“尼泊尔语”，台词列必须输出 Nepali 文案（优先天城文）；不得使用 Malay、Bengali、Bangla、印尼语或英语替代。
- 如果“目标语言变量”为“法语”，台词列必须输出 French / Français 文案；不得使用 Spanish / Español、德语或原脚本语言替代。
- 如果“目标语言变量”包含 American English，必须使用美国市场自然表达和美式拼写；如果包含 British English，必须使用英国市场自然表达和英式拼写；如果包含 Irish English，必须使用爱尔兰市场自然表达并倾向英式拼写。
- 如果“国家/地区变量”不是“不改变原脚本”，人物外观、服装审美、场景陈设、道具、消费语境和本地化表达必须服务于该国家/地区；不得回到母版原国家语境。
- 每个镜头的 **[音频文案]** 必须输出真实目标语言台词，不能只写“目标语言口播（大意：……）”“马来语口播（大意：……）”这类说明；中文翻译对照只能放在该条音频文案最后一个括号里，禁止插在目标语言台词中间，且必须覆盖前面整段目标语言口播。
- 每个镜头的 **[音频文案]** 必须匹配镜头时长，不得比母版同镜头更长，原则上不超过母版同镜头台词长度的 110%；1-2 秒镜头只能用一个短句或半句，3-4 秒镜头最多 1 个完整短句，不得为了加入 persona/time_marker/卖点而扩写。
- 贴纸必须最小改动：保留母版脚本里的贴纸数量、位置、颜色、层级、按钮/箭头/CTA 结构和出现镜头；贴纸文案只做必要产品词、合规词或目标语言修正，不得重新创作整句，不得出现中外文混写。
- 拍摄设备、固定方式、支撑物、垫靠物和摆放位置只用于推导镜头视角；输出脚本时只能写成自拍视角、固定机位、低角度、平视、俯拍、仰拍、轻微手持晃动等抽象镜头语言，不得写入可见场景、动作、道具、细节或倒影。
- 每个变体都要视觉差异明显，不能只是把“浴室”换成“卧室”这种轻微改词。
- 阶段三必须输出完整 AI 视频生产级提示词，沿用原脚本的镜头格式。
- 必须输出完整脚本正文，不得写“继续生成”“篇幅限制”“剩余变体遵循相同格式”等占位说明。
- 每个变体必须用独立标题开头，格式为：### 变体 #{batch_start}、### 变体 #{batch_start + 1}，依次到 ### 变体 #{batch_end}。
"""


def build_payload(prompt, max_output_tokens):
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": max_output_tokens,
        },
    }


def build_openai_payload(prompt, max_output_tokens):
    return {
        "model": "",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.65,
        "max_tokens": max_output_tokens,
    }


def extract_openai_text(response):
    choices = response.get("choices") if isinstance(response, dict) else None
    if isinstance(choices, list):
        texts = []
        for choice in choices:
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict) and message.get("content"):
                texts.append(str(message["content"]))
            elif isinstance(choice, dict) and choice.get("text"):
                texts.append(str(choice["text"]))
        if texts:
            return "\n".join(texts)
    return extract_text(response)


def openai_endpoint_variants(base_url):
    base_url = str(base_url or "").rstrip("/")
    if base_url.endswith("/v1"):
        return [(f"{base_url}/chat/completions", "openai-chat")]
    return [
        (f"{base_url}/chat/completions", "openai-chat"),
        (f"{base_url}/v1/chat/completions", "openai-v1-chat"),
        (f"{base_url}/api/v1/chat/completions", "openai-api-v1-chat"),
    ]


def should_use_openai_compatible_api(base_url, model):
    text = f"{base_url} {model}".lower()
    return any(marker in text for marker in ("deepseek", "openai", "chat/completions"))


def obsidian_cli_command(config, args=None):
    configured = str(getattr(args, "obsidian_cli_command", "") if args is not None else "").strip()
    return configured or str(config.get("script_obsidian_cli_command", "") or os.environ.get("OBSIDIAN_SCRIPT_CLI_COMMAND", "")).strip()


def obsidian_vault_path(config):
    configured = str(config.get("script_obsidian_vault_path", "") or os.environ.get("OBSIDIAN_VAULT_PATH", "")).strip()
    if not configured:
        return ""
    return str(Path(configured).expanduser().resolve())


def build_obsidian_cli_env(config, prompt_file, output_file, task_name):
    env = os.environ.copy()
    env["SCRIPT_GENERATION_TASK"] = task_name
    env["SCRIPT_GENERATION_PROMPT_FILE"] = str(prompt_file)
    env["SCRIPT_GENERATION_OUTPUT_FILE"] = str(output_file)
    vault_path = obsidian_vault_path(config)
    if vault_path:
        env["OBSIDIAN_VAULT_PATH"] = vault_path
    product_path = str(config.get("script_product_document_path", "") or "").strip()
    reference_path = ""
    try:
        reference_path = str(get_reference_path(config))
    except Exception:
        reference_path = ""
    if product_path:
        env["SCRIPT_PRODUCT_DOCUMENT_PATH"] = str(resolve_project_path(product_path))
    if reference_path:
        env["SCRIPT_REFERENCE_PATH"] = reference_path
    return env


def format_obsidian_cli_command(command, prompt_file, output_file, task_name, config):
    vault_path = obsidian_vault_path(config)
    replacements = {
        "{prompt_file}": shlex.quote(str(prompt_file)),
        "{output_file}": shlex.quote(str(output_file)),
        "{task}": shlex.quote(task_name),
        "{vault_path}": shlex.quote(vault_path),
        "{product_path}": shlex.quote(str(resolve_project_path(config.get("script_product_document_path", ""))) if config.get("script_product_document_path") else ""),
        "{reference_path}": shlex.quote(str(get_reference_path(config))),
    }
    formatted = command
    for placeholder, value in replacements.items():
        formatted = formatted.replace(placeholder, value)
    return formatted


def _call_obsidian_cli_unlimited(config, args, prompt, task_name, extra_log=""):
    command = obsidian_cli_command(config, args)
    if not command:
        raise RuntimeError(
            "已选择 Obsidian CLI 生产脚本，但没有配置 CLI 命令。"
            "请在页面填写 Obsidian CLI 命令，或设置环境变量 OBSIDIAN_SCRIPT_CLI_COMMAND。"
        )

    timeout = args.timeout or int(config.get("script_generation_timeout") or DEFAULT_TIMEOUT)
    with tempfile.TemporaryDirectory(prefix="script-obsidian-cli-") as temp_dir:
        temp_root = Path(temp_dir)
        prompt_file = temp_root / "prompt.md"
        output_file = temp_root / "output.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        formatted_command = format_obsidian_cli_command(command, prompt_file, output_file, task_name, config)
        uses_prompt_placeholder = "{prompt_file}" in command
        uses_output_placeholder = "{output_file}" in command

        log(f"开始{task_name}请求")
        log("生产后端: Obsidian CLI")
        log(f"CLI 命令: {command}")
        if extra_log:
            log(extra_log)

        result = subprocess.run(
            formatted_command,
            input=None if uses_prompt_placeholder else prompt,
            text=True,
            shell=True,
            capture_output=True,
            timeout=timeout,
            env=build_obsidian_cli_env(config, prompt_file, output_file, task_name),
            cwd=str(ROOT),
        )
        if result.stderr.strip():
            log(result.stderr.strip()[-2000:])
        if result.returncode != 0:
            raise RuntimeError(f"Obsidian CLI 执行失败，退出码 {result.returncode}: {result.stderr.strip()[-1200:]}")

        output_text = ""
        if uses_output_placeholder and output_file.exists():
            output_text = output_file.read_text(encoding="utf-8").strip()
        if not output_text:
            output_text = result.stdout.strip()
        if not output_text:
            raise RuntimeError("Obsidian CLI 已执行完成，但没有从 stdout 或 output_file 读取到脚本结果。")

        raw_response = {
            "backend": "obsidian_cli",
            "task": task_name,
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        return output_text, raw_response, "obsidian-cli", "stdout"


def call_obsidian_cli(config, args, prompt, task_name, extra_log=""):
    with global_api_slot(task_name, config):
        return _call_obsidian_cli_unlimited(config, args, prompt, task_name, extra_log)


def _call_text_model_unlimited(config, args, prompt, task_name, extra_log=""):
    api_key = get_api_key(config)
    if not api_key:
        raise SystemExit(
            "缺少 API Key：请设置 MODELMESH_API_KEY，或在 opc_engine/features/script_generation/config/model_settings.json 写入 modelmesh_api_key"
        )

    model = args.model or config.get("script_generation_model") or config.get("video_analysis_model") or DEFAULT_MODEL
    base_url = args.base_url or config.get("modelmesh_base_url") or DEFAULT_BASE_URL
    timeout = args.timeout or int(config.get("script_generation_timeout") or DEFAULT_TIMEOUT)
    max_output_tokens = args.max_output_tokens or int(
        config.get("script_generation_max_output_tokens") or DEFAULT_MAX_OUTPUT_TOKENS
    )

    if should_use_openai_compatible_api(base_url, model):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        log(f"开始{task_name}请求")
        log(f"模型: {model}")
        log(f"接口: {str(base_url).rstrip('/')}/chat/completions")
        if extra_log:
            log(extra_log)

        last_error = None
        for url, endpoint_style in openai_endpoint_variants(base_url):
            log(f"尝试接口格式: {endpoint_style}")
            payload = build_openai_payload(prompt, max_output_tokens)
            payload["model"] = model
            status, response = post_json(url, headers, payload, timeout)
            if 200 <= status < 300:
                return extract_openai_text(response), response, endpoint_style, "content"
            last_error = {"status": status, "response": response, "endpoint_style": endpoint_style}
            message = response.get("error") if isinstance(response, dict) else response
            log(f"  未成功，HTTP {status}: {str(message)[:220]}")
            time.sleep(0.5)

        raise RuntimeError(f"所有 OpenAI 兼容接口尝试均失败: {json.dumps(last_error, ensure_ascii=False)[:1200]}")

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    log(f"开始{task_name}请求")
    log(f"模型: {model}")
    log(f"接口: {base_url.rstrip('/')}/v1beta/models/...:generateContent")
    if extra_log:
        log(extra_log)

    last_error = None
    for url, endpoint_style in endpoint_variants(base_url, model):
        log(f"尝试接口格式: {endpoint_style}")
        payload = build_payload(prompt, max_output_tokens)
        status, response = post_json(url, headers, payload, timeout)
        if 200 <= status < 300:
            return extract_text(response), response, endpoint_style, "text"
        last_error = {"status": status, "response": response, "endpoint_style": endpoint_style}
        message = response.get("error") if isinstance(response, dict) else response
        log(f"  未成功，HTTP {status}: {str(message)[:220]}")
        time.sleep(0.5)

    raise RuntimeError(f"所有 Gemini 原生接口尝试均失败: {json.dumps(last_error, ensure_ascii=False)[:1200]}")


def call_text_model(config, args, prompt, task_name, extra_log=""):
    with global_api_slot(task_name, config):
        return _call_text_model_unlimited(config, args, prompt, task_name, extra_log)


def generate_script(config, args):
    prompt = build_generation_prompt(config)
    if args.dry_run:
        log(f"脚本产出完整上下文长度: {len(prompt)} 字符")
        log("dry-run 完成，未调用模型")
        return prompt, {}, "dry-run", "text"

    if script_generation_backend(config, args) in {"obsidian", "obsidian_cli"}:
        return call_obsidian_cli(config, args, prompt, "脚本产出", f"参考内容: {get_reference_path(config).name}")

    return call_text_model(config, args, prompt, "脚本产出", f"参考内容: {get_reference_path(config).name}")


def strip_translation_parentheses(text):
    content = str(text or "")
    patterns = (
        r"（\s*中文翻译对照[:：].*?）",
        r"\(\s*中文翻译对照[:：].*?\)",
        r"（\s*中文翻译[:：].*?）",
        r"\(\s*中文翻译[:：].*?\)",
        r"（\s*大意[:：].*?）",
        r"\(\s*大意[:：].*?\)",
    )
    for pattern in patterns:
        content = re.sub(pattern, "", content)
    return content.strip()


def normalize_audio_translation_line(line):
    if "音频文案" not in str(line or ""):
        return line

    translation_pattern = r"[（(]\s*(?:中文翻译对照|中文翻译|大意)\s*[:：].*?[）)]"
    translations = re.findall(translation_pattern, line)
    if not translations:
        return line

    line_without_translations = re.sub(translation_pattern, " ", line)
    line_without_translations = re.sub(r"\s{2,}", " ", line_without_translations).rstrip()
    translation = translations[-1]
    return f"{line_without_translations}{translation}"


def normalize_audio_translation_positions(text):
    return "\n".join(normalize_audio_translation_line(line) for line in str(text or "").splitlines())


CAMERA_DEVICE_PATTERN = r"(?:手机|相机|拍摄设备|摄影设备|摄像设备|摄像机|支架|脚架|三脚架|固定架|自拍杆)"
CAMERA_PLACEMENT_PATTERN = r"(?:靠在|架在|放在|摆在|固定在|支在|夹在|立在|垫在|贴在)"


def split_markdown_field_line(line):
    match = re.match(r"^(\s*\*\s+\*\*\[[^]]+\]\*\*\s*[:：]\s*)(.*)$", str(line or ""))
    if match:
        return match.group(1), match.group(2)
    match = re.match(r"^(\s*\*\s+\*\*【[^】]+】\*\*\s*[:：]\s*)(.*)$", str(line or ""))
    if match:
        return match.group(1), match.group(2)
    return "", str(line or "")


def normalize_camera_visibility_line(line):
    content = str(line or "")
    if not content.strip():
        return content

    prefix, body = split_markdown_field_line(content)
    target = body if prefix else content

    if re.search(CAMERA_DEVICE_PATTERN, target):
        target = re.sub(r"看向[^，。；]*?(?:手机|相机|摄像机)?镜头", "看向镜头", target)
        target = re.sub(r"对着[^，。；]*?(?:手机|相机|摄像机)?镜头", "对着镜头", target)

    if "镜头语言" in content:
        replacements = (
            (r"(?:手机|相机|摄像机)前置(?:摄像头)?自拍视角", "自拍视角"),
            (r"(?:手机|相机|摄像机)后置(?:摄像头)?", "拍摄视角"),
            (r"(?:手机|相机|摄像机)?\s*以?低角度[^，。；]*?(?:仰拍|拍摄)?", "低角度固定机位"),
            (r"(?:手机|相机|摄像机)?\s*以?高角度[^，。；]*?(?:俯拍|拍摄)?", "高角度固定机位"),
            (r"(?:手机|相机|摄像机)[^，。；]*?" + CAMERA_PLACEMENT_PATTERN + r"[^，。；]*", "固定机位"),
            (CAMERA_PLACEMENT_PATTERN + r"[^，。；]*?(?:手机|相机|摄像机|支架|脚架|三脚架|固定架)[^，。；]*", "固定机位"),
            (r"放在[^，。；]*?(?:支架|脚架|三脚架|固定架)上?", "固定机位"),
            (r"(?:手机|相机|摄像机)", ""),
        )
        for pattern, replacement in replacements:
            target = re.sub(pattern, replacement, target)
        target = re.sub(r"(固定机位)[^，。；]*(?:" + CAMERA_PLACEMENT_PATTERN + r")[^，。；]*", r"\1", target)
        target = re.sub(r"(固定机位[，,、\s]*){2,}", "固定机位，", target)
        target = re.sub(r"\s{2,}", " ", target)
        target = re.sub(r"^[，,、\s]+", "", target)
        return f"{prefix}{target}" if prefix else target

    if any(field in content for field in ("[在场景中]", "[做什么动作]", "[细节]", "【在场景中】", "【做什么动作】", "【细节】")):
        if re.search(CAMERA_DEVICE_PATTERN, target) and (
            re.search(CAMERA_PLACEMENT_PATTERN, target) or re.search(r"(?:镜头|倒影|画面中|旁边|边上)", target)
        ):
            target = re.sub(r"看向[^，。；]*?(?:手机|相机|摄像机)?镜头", "看向镜头", target)
            target = re.sub(r"对着[^，。；]*?(?:手机|相机|摄像机)?镜头", "对着镜头", target)
            target = re.sub(r"[^，。；]*?" + CAMERA_DEVICE_PATTERN + r"[^，。；]*?(?:，|。|；|$)", "", target)
            target = re.sub(r"^[，,、\s]+", "", target).strip()
            if not target:
                target = "保持原镜头对应的可见画面内容。"
            return f"{prefix}{target}" if prefix else target
    return f"{prefix}{target}" if prefix else target


def normalize_camera_visibility(text):
    return "\n".join(normalize_camera_visibility_line(line) for line in str(text or "").splitlines())


def compact_audio_text(text):
    content = strip_translation_parentheses(text)
    content = re.sub(r"^[^：:]{0,20}[:：]\s*", "", content)
    content = re.sub(r"\s+", "", content)
    return content


def extract_shot_key(line, fallback_index):
    text = str(line or "")
    match = re.search(r"(?:镜头|Shot|SHOT)\s*#?\s*(\d{1,3})", text)
    if match:
        return match.group(1).zfill(3)
    match = re.match(r"^\s*(?:#{1,6}\s*)?(\d{1,3})[\.、\s-]", text)
    if match:
        return match.group(1).zfill(3)
    return str(fallback_index).zfill(3)


def extract_timecode(line):
    text = str(line or "")
    patterns = (
        r"\d{1,2}:\d{2}(?:\.\d{1,3})?\s*[-~—至到]+\s*\d{1,2}:\d{2}(?:\.\d{1,3})?",
        r"\d+(?:\.\d+)?\s*s\s*[-~—至到]+\s*\d+(?:\.\d+)?\s*s",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(0)
    return ""


def extract_audio_profiles(text):
    profiles = {}
    current_key = None
    current_timecode = ""
    shot_index = 0

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"(?:镜头|Shot|SHOT)\s*#?\s*\d{1,3}", stripped) or re.match(r"^\s*(?:#{1,6}\s*)?\d{1,3}[\.、\s-]", stripped):
            shot_index += 1
            current_key = extract_shot_key(stripped, shot_index)
            current_timecode = extract_timecode(stripped)
            profiles.setdefault(current_key, {"timecode": current_timecode, "audio": "", "audio_length": 0})
            if current_timecode and not profiles[current_key].get("timecode"):
                profiles[current_key]["timecode"] = current_timecode
        elif current_key:
            timecode = extract_timecode(stripped)
            if timecode and not profiles[current_key].get("timecode"):
                profiles[current_key]["timecode"] = timecode

        if "[音频文案]" in stripped or "音频文案" in stripped:
            audio = re.sub(r"^.*?音频文案\]?\*{0,2}\s*[:：]\s*", "", stripped)
            audio = audio.strip()
            if current_key and audio:
                normalized = compact_audio_text(audio)
                profiles.setdefault(current_key, {"timecode": current_timecode, "audio": "", "audio_length": 0})
                profiles[current_key]["audio"] = audio
                profiles[current_key]["audio_length"] = len(normalized)

    return {key: value for key, value in profiles.items() if value.get("audio_length", 0) > 0}


def validate_audio_length_against_source(source_profiles, variant_profiles, variant_number):
    warnings = []
    for shot_key, variant_profile in variant_profiles.items():
        source_profile = source_profiles.get(shot_key)
        if not source_profile:
            continue
        source_length = int(source_profile.get("audio_length") or 0)
        variant_length = int(variant_profile.get("audio_length") or 0)
        if source_length <= 0 or variant_length <= 0:
            continue
        allowed_length = max(int(source_length * 1.1), source_length + 6)
        if variant_length > allowed_length:
            timecode = variant_profile.get("timecode") or source_profile.get("timecode") or "未知时间码"
            warnings.append(
                "音频长度警告: "
                f"变体 #{variant_number} 镜头 {shot_key}（{timecode}）"
                f"口播 {variant_length} 字，母版 {source_length} 字，超过允许 {allowed_length} 字；"
                "建议缩短该镜头 [音频文案]。"
            )
    return warnings


def mutate_generated_script(config, args, generated_script):
    return mutate_script_source(config, args, generated_script, "")


def mutate_script_source(config, args, generated_script, reference_context=""):
    variant_count = mutation_variant_count(config, args)
    backend = script_generation_backend(config, args)
    request_concurrency = mutation_request_concurrency(config, args)
    source_audio_profiles = extract_audio_profiles(generated_script)
    collected_variants = {}
    raw_batches = []
    validation_warnings = []
    endpoint_styles = []
    field_styles = []
    max_attempts_per_variant = max(1, int(config.get("script_mutation_attempts_per_variant") or 2))
    log(
        f"裂变并发模式: 目标 {variant_count} 条，"
        f"每条脚本 1 个 API 请求，本组并发 {request_concurrency}，全局 API 并发上限 {max_api_concurrency(config)}"
    )

    def request_one_variant(variant_number, attempt_number):
        prompt = build_mutation_prompt(
            config,
            generated_script,
            1,
            batch_start=variant_number,
            total_variant_count=variant_count,
            reference_context=reference_context,
        )
        log(f"裂变第 {variant_number} 条上下文长度: {len(prompt)} 字符")
        extra_log = f"裂变变体数: 1（总数 {variant_count}，已完成 {len(collected_variants)}）"
        batch_started_at = time.time()
        if backend in {"obsidian", "obsidian_cli"}:
            batch_text, batch_raw, endpoint_style, field_style = call_obsidian_cli(
                config, args, prompt, f"脚本裂变第 {variant_number} 条", extra_log
            )
        else:
            batch_text, batch_raw, endpoint_style, field_style = call_text_model(
                config, args, prompt, f"脚本裂变第 {variant_number} 条", extra_log
            )
        batch_elapsed = time.time() - batch_started_at

        variants = [
            normalize_audio_translation_positions(variant)
            for variant in split_mutation_variants(batch_text)
            if not is_placeholder_mutation_variant(variant)
            and variant_matches_target_language(config, variant)
        ]
        variant = variants[0] if variants else ""
        batch_validation_warnings = []
        if variant:
            variant, duration_warnings = enforce_configured_total_duration(config, variant)
            batch_validation_warnings.extend(duration_warnings)
            warnings = validate_audio_length_against_source(
                source_audio_profiles,
                extract_audio_profiles(variant),
                variant_number,
            )
            batch_validation_warnings.extend(warnings)
        return {
            "variant_number": variant_number,
            "attempt": attempt_number,
            "variant": variant,
            "requested_variant_count": 1,
            "received_variant_count": 1 if variant else 0,
            "validation_warnings": batch_validation_warnings,
            "raw": batch_raw,
            "endpoint_style": endpoint_style,
            "field_style": field_style,
            "elapsed": batch_elapsed,
        }

    attempts = {number: 0 for number in range(1, variant_count + 1)}
    futures = {}
    completed_count = 0
    with ThreadPoolExecutor(max_workers=request_concurrency) as executor:
        for variant_number in range(1, variant_count + 1):
            attempts[variant_number] += 1
            future = executor.submit(request_one_variant, variant_number, attempts[variant_number])
            futures[future] = variant_number

        while futures:
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                variant_number = futures.pop(future)
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "variant_number": variant_number,
                        "attempt": attempts[variant_number],
                        "variant": "",
                        "requested_variant_count": 1,
                        "received_variant_count": 0,
                        "validation_warnings": [],
                        "raw": {"error": str(error)},
                        "endpoint_style": backend,
                        "field_style": "error",
                        "elapsed": 0,
                    }
                    log(f"裂变第 {variant_number} 条失败: {error}")

                if result["variant"]:
                    collected_variants[variant_number] = result["variant"]
                    completed_count = len(collected_variants)
                    validation_warnings.extend(result["validation_warnings"])
                    for warning in result["validation_warnings"]:
                        log(warning)
                    endpoint_styles.append(result["endpoint_style"])
                    field_styles.append(result["field_style"])
                    raw_batches.append(
                        {
                            "attempt": result["attempt"],
                            "variant_number": variant_number,
                            "requested_variant_count": 1,
                            "received_variant_count": 1,
                            "validation_warnings": result["validation_warnings"],
                            "raw": result["raw"],
                        }
                    )
                    log(
                        f"裂变第 {variant_number} 条完成: 收到 1 个，"
                        f"累计 {completed_count}/{variant_count}，耗时 {result['elapsed']:.1f}s"
                    )
                elif attempts[variant_number] < max_attempts_per_variant:
                    attempts[variant_number] += 1
                    log(f"裂变第 {variant_number} 条未收到有效结果，重新排队第 {attempts[variant_number]} 次")
                    futures[executor.submit(request_one_variant, variant_number, attempts[variant_number])] = variant_number
                else:
                    raw_batches.append(
                        {
                            "attempt": result["attempt"],
                            "variant_number": variant_number,
                            "requested_variant_count": 1,
                            "received_variant_count": 0,
                            "validation_warnings": [],
                            "raw": result["raw"],
                        }
                    )

    missing_variant_numbers = [number for number in range(1, variant_count + 1) if number not in collected_variants]
    if not collected_variants:
        raise RuntimeError(f"裂变结果不足：目标 {variant_count} 个，实际 0 个。请检查模型输出或重新运行失败条目。")
    if missing_variant_numbers:
        warning = (
            f"裂变结果不足警告: 目标 {variant_count} 个，实际 {len(collected_variants)} 个，"
            f"缺失编号: {', '.join(str(number) for number in missing_variant_numbers)}。"
            "已保存成功生成的脚本，失败编号可后续补跑。"
        )
        validation_warnings.append(warning)
        log(warning)

    ordered_variant_numbers = [number for number in range(1, variant_count + 1) if number in collected_variants]
    ordered_variants = [collected_variants[number] for number in ordered_variant_numbers]
    raw_batches = sorted(raw_batches, key=lambda item: (int(item.get("variant_number") or 0), int(item.get("attempt") or 0)))
    combined_text = "\n\n".join(ordered_variants)
    raw_response = {
        "backend": backend,
        "target_language": normalized_target_language(config),
        "requested_variant_count": variant_count,
        "received_variant_count": len(ordered_variants),
        "partial_success": bool(missing_variant_numbers),
        "missing_variant_numbers": missing_variant_numbers,
        "mutation_variant_numbers": ordered_variant_numbers,
        "mutation_variants": ordered_variants,
        "mutation_batches": raw_batches,
        "validation_warnings": validation_warnings,
    }
    return combined_text, raw_response, "+".join(endpoint_styles) or backend, field_styles[-1] if field_styles else "text"


def run_script_pipeline(config, args):
    if should_run_mutation(config, args):
        if args.dry_run:
            source_label = mutation_source_choice(config)
            source_path = clone_output_path_for_reference(config, get_reference_path(config), getattr(args, "output_dir", ""))
            mutation_prompt = build_mutation_prompt(
                config,
                f"<裂变阶段会读取{source_label}作为输入源：{source_path}>",
                mutation_variant_count(config, args),
            )
            log(f"裂变已启用；裂变提示词模板检查完成，上下文长度: {len(mutation_prompt)} 字符")
            return mutation_prompt, {}, "dry-run", "text"

        source_label, source_path, source_text, source_context = mutation_input_source(config, args)
        log(f"已启用裂变，输入源为{source_label}: {source_path}")
        if source_context:
            log(f"已从复刻稿中提取裂变主输入: {len(source_text)} 字符；完整参考上下文: {len(source_context)} 字符")
        mutation_text, mutation_raw, mutation_endpoint, mutation_field = mutate_script_source(config, args, source_text, source_context)
        raw_bundle = {
            "final_stage": "mutation_rewrite",
            "mutation_mode": mutation_mode(config),
            "mutation_source_stage": source_label,
            "mutation_source_path": str(source_path),
            "mutation_primary_input_chars": len(source_text),
            "mutation_reference_context_chars": len(source_context or ""),
            "mutation_run_id": time.strftime(MUTATION_RUN_TS_FORMAT),
            "mutation_rewrite_raw": mutation_raw,
        }
        return mutation_text, raw_bundle, f"mutation:{mutation_endpoint}", mutation_field

    generated_text, generated_raw, endpoint_style, field_style = generate_script(config, args)
    if args.dry_run:
        return generated_text, generated_raw, endpoint_style, field_style
    return generated_text, generated_raw, endpoint_style, field_style


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a product TikTok script from product info and a competitor reference.")
    parser.add_argument("--model", default="", help=f"模型名，默认复用配置或 {DEFAULT_MODEL}")
    parser.add_argument("--base-url", default="", help=f"中转 API base，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--backend", choices=["api", "obsidian_cli"], default="", help="脚本生产后端：api 或 obsidian_cli")
    parser.add_argument("--obsidian-cli-command", default="", help="Obsidian CLI 命令；支持 {prompt_file}、{output_file}、{vault_path} 占位符")
    parser.add_argument("--output-dir", default="", help=f"脚本产出结果输出目录；留空时写入 {SCRIPT_OUTPUT_SOURCE_ROOT}/产品名")
    parser.add_argument("--product-doc", default="", help="本次直接使用的产品文档 Markdown 路径")
    parser.add_argument("--reference-script", default="", help="本次直接使用的竞品爆款脚本 Markdown 路径")
    parser.add_argument("--reference-analysis", default="", help="本次直接使用的竞品视频拆解 Markdown 路径")
    parser.add_argument("--country", default="", help="已弃用：脚本生产会从产品信息和参考脚本中自动识别市场语境")
    parser.add_argument("--target-language", default="", help="已弃用：脚本生产会从产品信息和参考脚本中自动识别目标语言")
    parser.add_argument("--total-duration", default="", help="目标视频总时长；留空时跟随参考爆款原视频时长")
    parser.add_argument("--hook-duration", default="", help="已弃用：黄金钩子不再作为独立输入")
    parser.add_argument("--audio-emotion", default="", help="已弃用：情绪强度不再作为独立输入，直接参考竞品爆款")
    parser.add_argument("--enable-mutation", action="store_true", help="生成脚本后继续进行场景/人物/服饰道具裂变，并只保存裂变后的结果")
    parser.add_argument("--mutation-variants", type=int, default=0, help=f"裂变变体数，默认 {DEFAULT_MUTATION_VARIANTS}")
    parser.add_argument("--mutation-batch-size", type=int, default=0, help=f"每批裂变条数，默认 {DEFAULT_MUTATION_BATCH_SIZE}，最大 5")
    parser.add_argument("--timeout", type=int, default=0, help=f"单次请求超时时间，秒，默认 {DEFAULT_TIMEOUT}")
    parser.add_argument("--max-output-tokens", type=int, default=0, help=f"最大输出 token，默认 {DEFAULT_MAX_OUTPUT_TOKENS}")
    parser.add_argument("--dry-run", action="store_true", help="只组装提示词并检查参数，不调用模型")
    return parser.parse_args()


def apply_cli_overrides(config, args):
    config = dict(config)
    if args.product_doc:
        config["script_product_document_path"] = args.product_doc
    if args.reference_script:
        config["script_reference_analysis_path"] = args.reference_script
        config["script_reference_script_path"] = args.reference_script
        config["script_reference_kind"] = "竞品爆款脚本"
    if args.reference_analysis:
        config["script_reference_analysis_path"] = args.reference_analysis
        config["script_reference_kind"] = "竞品视频拆解结果"
    if getattr(args, "country", ""):
        config["script_country"] = args.country
    if getattr(args, "target_language", ""):
        config["script_target_language"] = args.target_language
    if args.total_duration:
        config["script_total_duration"] = args.total_duration
    if getattr(args, "enable_mutation", False):
        config["script_enable_mutation_rewrite"] = "true"
    config["script_mutation_mode"] = "standard"
    if getattr(args, "mutation_variants", 0):
        config["script_mutation_variants"] = str(args.mutation_variants)
    if getattr(args, "mutation_batch_size", 0):
        config["script_mutation_batch_size"] = str(args.mutation_batch_size)
    if getattr(args, "backend", ""):
        config["script_generation_backend"] = args.backend
    if getattr(args, "obsidian_cli_command", ""):
        config["script_obsidian_cli_command"] = args.obsidian_cli_command
    return config


def product_output_name(config):
    product_doc = str(config.get("script_product_document_path", "") or "").strip()
    if product_doc:
        return strip_import_timestamp_prefix(Path(product_doc).expanduser().stem).replace("-产品信息", "").strip()
    profile = config.get("product_profile", {}) or {}
    configured = profile.get("english_name") or profile.get("product_name")
    if configured:
        return strip_import_timestamp_prefix(configured).replace("-产品信息", "").strip()
    return "product_script"


def split_country_prefix_from_reference_stem(stem):
    parts = str(stem or "").split("-", 2)
    if len(parts) >= 3 and re.fullmatch(r"[A-Za-z]{2,6}", parts[0] or "") and parts[2]:
        return parts[0].upper(), f"{parts[1]}-{parts[2]}"
    return "", str(stem or "")


def reference_country_author_and_video_id(reference_path):
    stem = Path(reference_path).expanduser().stem
    country, core_stem = split_country_prefix_from_reference_stem(stem)
    match = re.search(r"(.+?)[-_ ]*(\d{10,24})(?:[-_ ].*)?$", core_stem)
    if match:
        author = safe_output_name(match.group(1).rstrip("-_ "))
        return country, author or "unknown_user", match.group(2)
    source_id = infer_source_id(core_stem or reference_path)
    return country, "unknown_user", source_id


def source_key_for_reference(reference_path):
    country, author, source_id = reference_country_author_and_video_id(reference_path)
    return f"{country}-{author}-{source_id}" if country else f"{author}-{source_id}"


def output_country_for_filename(config, source_country):
    configured = str((config or {}).get("script_country", "") or "").strip()
    if preserves_original_script(configured):
        value = str(source_country or "").strip()
    else:
        value = configured
    if not value:
        return ""
    return COUNTRY_FILENAME_CODE.get(value.lower(), safe_output_name(value).upper() if value.isascii() else safe_output_name(value))


def reference_author_and_video_id(reference_path):
    _country, author, source_id = reference_country_author_and_video_id(reference_path)
    return author, source_id


def clone_stem_for_reference(config, reference_path):
    country, author, source_id = reference_country_author_and_video_id(reference_path)
    product_name = safe_output_name(product_output_name(config))
    filename_country = output_country_for_filename(config, country)
    filename_part = f"{filename_country}-{author}-{source_id}" if filename_country else f"{author}-{source_id}"
    return f"复刻-{product_name}-{filename_part}"


def clone_output_path_for_reference(config, reference_path, output_dir=""):
    output_root = resolve_output_root(config, output_dir)
    return output_root / f"{clone_stem_for_reference(config, reference_path)}.md"


def require_clone_source_for_mutation(config, args):
    reference_path = get_reference_path(config)
    clone_path = clone_output_path_for_reference(config, reference_path, getattr(args, "output_dir", ""))
    if not clone_path.exists():
        raise RuntimeError(
            "裂变必须以已复刻脚本为输入源。请先取消勾选“是否裂变”生成一次复刻稿，再勾选裂变。"
            f"\n缺少复刻稿: {clone_path}"
        )
    text = clone_path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"复刻稿为空，不能作为裂变母稿: {clone_path}")
    return clone_path, text


def ensure_clone_source_for_mutation(config, args):
    reference_path = get_reference_path(config)
    expected_clone_path = clone_output_path_for_reference(config, reference_path, getattr(args, "output_dir", ""))
    if expected_clone_path.exists():
        return require_clone_source_for_mutation(config, args)

    log(f"未找到对应国家的复刻稿，先自动复刻: {expected_clone_path}")
    generated_text, generated_raw, clone_endpoint, clone_field = generate_script(config, args)
    output_paths, _raw_paths = write_script_outputs(config, getattr(args, "output_dir", ""), generated_text, generated_raw)
    if not output_paths:
        raise RuntimeError("自动复刻未生成可用脚本，不能继续裂变。")
    clone_path = output_paths[0]
    clone_text = clone_path.read_text(encoding="utf-8").strip()
    if not clone_text:
        raise RuntimeError(f"自动复刻稿为空，不能作为裂变母稿: {clone_path}")
    log(f"自动复刻完成: endpoint={clone_endpoint}, field={clone_field}")
    log(f"自动复刻稿: {clone_path}")
    return clone_path, clone_text


def mutation_source_choice(config):
    return "复刻稿"


def mutation_input_source(config, args):
    clone_path, clone_text = ensure_clone_source_for_mutation(config, args)
    return "复刻稿", clone_path, clone_text.strip(), ""


def script_output_stage_name(raw_response):
    if isinstance(raw_response, dict) and raw_response.get("final_stage") == "mutation_rewrite":
        return "裂变"
    return "复刻"


def unique_script_output_paths(output_root, stem):
    for index in range(1, 10000):
        candidate_stem = stem if index == 1 else f"{stem}_{index:03d}"
        output_path = output_root / f"{candidate_stem}.md"
        raw_path = output_root / f"{candidate_stem}.raw.json"
        try:
            with output_path.open("x", encoding="utf-8"):
                pass
            try:
                with raw_path.open("x", encoding="utf-8"):
                    pass
            except FileExistsError:
                output_path.unlink(missing_ok=True)
                continue
            return output_path, raw_path
        except FileExistsError:
            continue

    raise RuntimeError(f"输出目录同名脚本过多，无法生成唯一文件名: {output_root / stem}")


def single_clone_output_paths(output_root, stem):
    output_path = output_root / f"{stem}.md"
    raw_path = output_root / f"{stem}.raw.json"
    created_output = False
    try:
        with output_path.open("x", encoding="utf-8"):
            pass
        created_output = True
        with raw_path.open("x", encoding="utf-8"):
            pass
    except FileExistsError:
        if created_output:
            output_path.unlink(missing_ok=True)
        raise RuntimeError(
            "当前参考爆款脚本已经复刻过一次，不能重复复刻；如需更多版本，请勾选“是否裂变”生成裂变脚本。"
            f"\n已存在: {output_path}"
        )
    return output_path, raw_path


def is_placeholder_mutation_variant(text):
    content = str(text or "").strip()
    if not content:
        return True
    markers = (
        "篇幅限制",
        "继续生成",
        "续生成",
        "剩下的",
        "剩余的",
        "遵循相同",
        "实际输出中",
        "此处仅展示",
    )
    if len(content) < 2000 and any(marker in content for marker in markers):
        return True
    return len(content) < 800


def text_has_range(text, start, end):
    return any(start <= ch <= end for ch in str(text or ""))


def variant_matches_target_language(config, text):
    target_language = normalized_target_language(config).lower()
    if not target_language or preserves_original_script(target_language):
        return True
    has_bengali = text_has_range(text, "\u0980", "\u09ff")
    has_devanagari = text_has_range(text, "\u0900", "\u097f")
    if "孟加拉" in target_language or "bengali" in target_language or "bangla" in target_language:
        return has_bengali
    if "尼泊尔" in target_language or "nepali" in target_language:
        return has_devanagari and not has_bengali
    if "马来" in target_language or "malay" in target_language or "bahasa" in target_language:
        return not has_bengali and not has_devanagari
    if "法语" in target_language or "french" in target_language or "français" in target_language or "francais" in target_language:
        content = str(text or "").lower()
        french_markers = re.findall(
            r"\\b(le|la|les|un|une|des|de|du|ce|cet|cette|ces|est|sont|avec|pour|vous|votre|notre|sans|très|tres|maintenant|aujourd'hui|ça|ca|je|nous|plus)\\b",
            content,
        )
        spanish_markers = re.findall(
            r"\\b(el|los|las|una|unos|este|esta|estos|estas|ahora|mismo|env[ií]o|gratis|todo|mundo|habla|para|muy|reseñas|geniales|rápido|rapido|cápsulas|capsulas)\\b",
            content,
        )
        has_french_accents = bool(re.search(r"[àâçéèêëîïôûùüÿœ]", content))
        return (len(french_markers) >= 3 or has_french_accents) and len(spanish_markers) <= max(1, len(french_markers) // 2)
    return True


def split_mutation_variants(text):
    content = str(text or "").strip()
    if not content:
        return []

    lines = content.splitlines()
    starts = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        heading_text = stripped.lstrip("#").strip()
        if stripped.startswith("#") and heading_text.startswith("变体"):
            starts.append(index)

    if not starts:
        return [content]

    variants = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        variant = "\n".join(lines[start:end]).strip()
        if variant:
            variants.append(variant)
    return variants or [content]


def has_direct_file_inputs(config):
    product_doc = str(config.get("script_product_document_path", "") or "").strip()
    reference = str(
        config.get("script_reference_script_path", "")
        or config.get("reference_script_path", "")
        or config.get("script_reference_analysis_path", "")
        or ""
    ).strip()
    return bool(product_doc and reference)


def product_output_dir_name(config):
    product_doc = str(config.get("script_product_document_path", "") or "").strip()
    if product_doc:
        name = Path(product_doc).expanduser().stem.replace("-产品信息", "").strip()
        if name:
            return safe_output_name(strip_import_timestamp_prefix(name))
    profile = config.get("product_profile", {}) or {}
    configured = profile.get("product_name") or profile.get("english_name")
    if configured:
        return safe_output_name(strip_import_timestamp_prefix(configured))
    slug = str(config.get("product_project_slug", "") or "").replace("-产品信息", "").strip()
    return safe_output_name(slug or "未命名产品")


def resolve_output_root(config, output_dir=""):
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    if product_project_ready(config):
        return SCRIPT_OUTPUT_SOURCE_ROOT / product_output_dir_name(config)
    return FEATURE_DIR / "outputs"


def write_script_outputs(config, output_dir, text, raw_response):
    text = normalize_camera_visibility(normalize_audio_translation_positions(text))
    text, duration_warnings = enforce_configured_total_duration(config, text)
    output_root = resolve_output_root(config, output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    reference_path = get_reference_path(config)
    country, author, source_id = reference_country_author_and_video_id(reference_path)
    product_name = safe_output_name(product_output_name(config))
    stage_name = script_output_stage_name(raw_response)
    source_part = f"{country}-{author}-{source_id}" if country else f"{author}-{source_id}"
    filename_country = output_country_for_filename(config, country)
    filename_part = f"{filename_country}-{author}-{source_id}" if filename_country else f"{author}-{source_id}"
    stem = f"{stage_name}-{product_name}-{filename_part}"
    base_metadata = {
        "output_stage": stage_name,
        "mutation_mode": mutation_mode(config) if stage_name == "裂变" else "",
        "target_language": normalized_target_language(config),
        "script_country": str(config.get("script_country", "") or "").strip(),
        "filename_country": filename_country,
        "source_country": country,
        "source_author": author,
        "source_video_id": source_id,
        "source_key": source_part,
        "source_reference_path": str(reference_path),
        "expected_clone_path": str(clone_output_path_for_reference(config, reference_path, output_dir)),
    }
    if stage_name == "复刻":
        output_path, raw_path = single_clone_output_paths(output_root, stem)
        output_path.write_text(text.strip() + "\n", encoding="utf-8")
        raw_payload = dict(raw_response) if isinstance(raw_response, dict) else {"raw_response": raw_response}
        raw_payload.update(base_metadata)
        raw_payload["duration_validation_warnings"] = duration_warnings
        raw_payload["clone_source_path"] = str(output_path)
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return [output_path], [raw_path]

    output_paths = []
    raw_paths = []
    nested_raw = raw_response.get("mutation_rewrite_raw") if isinstance(raw_response, dict) else {}
    variants = nested_raw.get("mutation_variants") if isinstance(nested_raw, dict) else None
    variant_numbers = nested_raw.get("mutation_variant_numbers") if isinstance(nested_raw, dict) else None
    if not variants:
        variants = split_mutation_variants(text)
    if not isinstance(variant_numbers, list) or len(variant_numbers) != len(variants):
        variant_numbers = list(range(1, len(variants) + 1))
    variant_count = len(variants)
    for sequence_index, variant_text in enumerate(variants, start=1):
        variant_number = variant_numbers[sequence_index - 1]
        variant_text = normalize_camera_visibility(normalize_audio_translation_positions(variant_text))
        variant_text, variant_duration_warnings = enforce_configured_total_duration(config, variant_text)
        output_path, raw_path = unique_script_output_paths(output_root, stem)
        output_path.write_text(variant_text.strip() + "\n", encoding="utf-8")
        raw_payload = dict(raw_response) if isinstance(raw_response, dict) else {"raw_response": raw_response}
        raw_payload.update(base_metadata)
        raw_payload["saved_sequence_index"] = sequence_index
        raw_payload["saved_variant_index"] = variant_number
        raw_payload["saved_variant_count"] = variant_count
        raw_payload["duration_validation_warnings"] = variant_duration_warnings
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_paths.append(output_path)
        raw_paths.append(raw_path)
    return output_paths, raw_paths


def main():
    args = parse_args()
    config = apply_cli_overrides(load_script_generation_config(), args)
    direct_file_mode = has_direct_file_inputs(config)
    has_project_context = product_project_ready(config)
    unified_direct_mode = bool(os.environ.get("OPC_APP_CONFIG_PATH") and direct_file_mode)
    explicit_product_output_mode = bool(args.product_doc and args.output_dir)
    if explicit_product_output_mode:
        Path(args.output_dir).expanduser().resolve().mkdir(parents=True, exist_ok=True)
    if not (unified_direct_mode or explicit_product_output_mode) and (
        not direct_file_mode or (not args.output_dir and has_project_context)
    ):
        require_product_project(config, "生成脚本")
        ensure_project_dirs(config)
    text, raw_response, endpoint_style, field_style = run_script_pipeline(config, args)

    if args.dry_run:
        return

    output_paths, raw_paths = write_script_outputs(config, args.output_dir, text, raw_response)

    log(f"脚本产出成功: endpoint={endpoint_style}, field={field_style}")
    for output_path in output_paths:
        log(f"脚本结果: {output_path}")
    for raw_path in raw_paths:
        log(f"原始响应: {raw_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"脚本产出失败: {exc}")
        sys.exit(1)
