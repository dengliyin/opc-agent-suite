#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

from opc_shared.legacy_ai_migration import load_report as load_ai_migration_report
from opc_shared.legacy_ai_migration import resolve_conflicts as resolve_ai_migration_conflicts


ROOT = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("OPC_ENV_FILE", "/config/.env")).expanduser()
HOST = os.environ.get("KESAI_APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KESAI_APP_PORT", "8888"))
UPDATER_URL = os.environ.get("OPC_UPDATER_URL", "http://opc-updater:18888").rstrip("/")
UPDATER_TOKEN_FILE = Path(os.environ.get("OPC_UPDATER_TOKEN_FILE", "/config/updater/updater.token"))


def service_url(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default)


def public_service_url(env_name: str, default: str) -> str:
    return os.environ.get(f"{env_name}_PUBLIC", service_url(env_name, default))


def build_services() -> dict[str, dict]:
    defaults = {
        "collect": ("OPC_HOT_VIDEO_AGENT_URL", "http://127.0.0.1:9991/"),
        "analyze": ("OPC_VIDEO_TEARDOWN_AGENT_URL", "http://127.0.0.1:9992/"),
        "script": ("OPC_SCRIPT_PRODUCTION_AGENT_URL", "http://127.0.0.1:9993/"),
        "adapt": ("OPC_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9994/"),
        "assemble": ("OPC_VIDEO_OUTPUT_AGENT_URL", "http://127.0.0.1:9995/"),
        "finished": ("OPC_FINISHED_VIDEO_MANAGER_URL", "http://127.0.0.1:9996/"),
        "rewrite": ("OPC_PRODUCT_SCRIPT_REWRITE_URL", "http://127.0.0.1:9997/"),
        "compose": ("OPC_VIDEO_ASSEMBLY_AGENT_URL", "http://127.0.0.1:9998/"),
        "hybrid_adapt": ("OPC_HYBRID_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9999/"),
        "hybrid_mix": ("OPC_HYBRID_VIDEO_MIXER_AGENT_URL", "http://127.0.0.1:10000/"),
        "hybrid_collect": ("OPC_HYBRID_VIDEO_COLLECTION_AGENT_URL", "http://127.0.0.1:10001/"),
        "hybrid_analyze": ("OPC_HYBRID_SCRIPT_ANALYSIS_AGENT_URL", "http://127.0.0.1:10002/"),
        "hybrid_script": ("OPC_HYBRID_SCRIPT_GENERATION_AGENT_URL", "http://127.0.0.1:10003/"),
        "hybrid_voice": ("OPC_HYBRID_AUDIO_GENERATION_AGENT_URL", "http://127.0.0.1:10004/"),
        "auto_publish": ("OPC_AUTO_PUBLISH_PIPELINE_URL", "http://127.0.0.1:10005/"),
    }
    urls = {
        key: service_url(env_name, default)
        for key, (env_name, default) in defaults.items()
    }
    public_urls = {
        key: public_service_url(env_name, default)
        for key, (env_name, default) in defaults.items()
    }
    services = {
        "collect": {
            "label": "视频采集",
            "description": "采集 FastMoss 商品关联视频并下载 TikTok 素材",
            "url": urls["collect"],
        },
        "analyze": {
            "label": "脚本解析",
            "description": "把本地短视频拆解成结构化 Markdown",
            "url": urls["analyze"],
        },
        "script": {
            "label": "脚本产出",
            "description": "根据产品资料和爆款参考生成带货脚本",
            "url": urls["script"],
        },
        "adapt": {
            "label": "脚本适配",
            "description": "生成视频模型需要的分镜、图片提示词和任务表",
            "url": urls["adapt"],
        },
        "assemble": {
            "label": "片段产出",
            "description": "生成人物图、故事版和视频片段",
            "url": urls["assemble"],
        },
        "finished": {
            "label": "成品管理",
            "description": "查看成品、维护发布记录并处理 TikTok 发布",
            "url": urls["finished"],
        },
        "rewrite": {
            "label": "产品脚本改写",
            "description": "把爆款脚本改写成目标产品版本",
            "url": urls["rewrite"],
        },
        "compose": {
            "label": "片段合成",
            "description": "离线拼接片段、校验成品并清理已用素材",
            "url": urls["compose"],
        },
        "hybrid_adapt": {
            "label": "钩子与 CTA 脚本适配",
            "description": "把复刻裂变后的钩子与 CTA 脚本适配成视频模型片段指令",
            "url": urls["hybrid_adapt"],
        },
        "hybrid_mix": {
            "label": "AI＋实拍混剪",
            "description": "按产品音频编排 AI 首尾片段与展示、使用实拍素材",
            "url": urls["hybrid_mix"],
        },
        "hybrid_collect": {
            "label": "混剪参考视频采集",
            "description": "按类型和产品下载钩子或 CTA 参考视频",
            "url": urls["hybrid_collect"],
        },
        "hybrid_analyze": {
            "label": "混剪参考视频解析",
            "description": "按类型和产品把参考视频解析成 Markdown",
            "url": urls["hybrid_analyze"],
        },
        "hybrid_script": {
            "label": "钩子与 CTA 脚本复刻裂变",
            "description": "把解析脚本复刻为产品脚本并批量生成可独立使用的变体",
            "url": urls["hybrid_script"],
        },
        "hybrid_voice": {
            "label": "配音",
            "description": "把本地产品音频文案生成为混剪可直接读取的 1.2 倍语速 M4A",
            "url": urls["hybrid_voice"],
        },
        "auto_publish": {
            "label": "自动发布流水线",
            "description": "从已复刻脚本独立完成裂变、适配、片段、合成和串行发布",
            "url": urls["auto_publish"],
        },
    }
    for service_id, service in services.items():
        service["url"] = public_urls[service_id]
        service["health_url"] = urls[service_id]
    health_paths = {
        "collect": "/api/state",
        "analyze": "/api/status",
        "script": "/api/outputs",
        "adapt": "/api/outputs?target_model=veo",
        "assemble": "/health",
        "finished": "/api/state",
        "rewrite": "/api/state",
        "compose": "/api/state",
        "hybrid_adapt": "/api/scripts?target_model=omni",
        "hybrid_mix": "/api/library",
        "hybrid_collect": "/api/state",
        "hybrid_analyze": "/api/status",
        "hybrid_script": "/api/outputs",
        "hybrid_voice": "/api/library",
        "auto_publish": "/api/state",
    }
    for service_id, service in services.items():
        service["health_path"] = health_paths[service_id]
    return services


SERVICES = build_services()

GLOBAL_PATH_FIELDS = (
    ("OPC_VAULT_ROOT", "资料库根目录", "所有 Agent 共用的内容资料库根目录", "/path/to/Obsidian Vault"),
    ("VIDEO_TEARDOWN_INPUT_ROOT", "来源素材", "9991 写入、9992 扫描的爆款视频目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/01来源素材"),
    ("VIDEO_TEARDOWN_OUTPUT_ROOT", "参考脚本", "9992 与 9997 写入、9993 读取的参考脚本目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/02参考脚本"),
    ("PRODUCT_SCRIPT_ROOT", "产品脚本", "9993 保存、9994 读取的正式产品脚本目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/03产品脚本"),
    ("HYBRID_VIDEO_TEARDOWN_INPUT_ROOT", "混剪参考视频", "10002 扫描10001下载结果的目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/01参考视频"),
    ("HYBRID_VIDEO_TEARDOWN_OUTPUT_ROOT", "混剪解析脚本", "10002 保存分类解析 Markdown 的目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/02解析脚本"),
    ("HYBRID_SCRIPT_GENERATION_INPUT_ROOT", "混剪解析脚本", "10003 扫描10002解析结果的目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/02解析脚本"),
    ("HYBRID_SCRIPT_GENERATION_OUTPUT_ROOT", "复刻裂变脚本", "10003 保存复刻稿与裂变稿的目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/03复刻裂变脚本"),
    ("HYBRID_OMNI_SCRIPT_ROOT", "混剪 Omni 脚本输入", "9995 读取的混剪钩子与 CTA Omni 适配脚本目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/04适配脚本/omni"),
    ("HYBRID_AI_CLIP_ROOT", "混剪 AI 片段", "10000 读取的模型/类型/产品 AI 钩子与 CTA 片段目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/05AI片段"),
    ("HYBRID_OMNI_VIDEO_OUTPUT_ROOT", "混剪 Omni 视频输出", "9995 保存混剪钩子与 CTA Omni 片段的目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/05AI片段/omni"),
    ("HYBRID_AUDIO_COPY_ROOT", "混剪音频文案", "10004 扫描可生成配音的 Markdown 文案目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/06音频文案"),
    ("HYBRID_PRODUCT_AUDIO_ROOT", "产品介绍音频", "10000 读取的产品介绍音频目录，按产品名分组", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/06音频文件"),
    ("HYBRID_REAL_FOOTAGE_ROOT", "产品实拍素材", "10000 读取的产品/展示|使用实拍素材目录", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/07实拍素材"),
    ("HYBRID_MIX_WORK_ROOT", "混剪工作区", "10000 保存编排方案、渲染中间文件和素材使用历史", "${OPC_VAULT_ROOT}/wiki/视频/AI实拍混剪/08混剪工作区"),
    ("SCRIPT_ROOT", "Omni 脚本输入", "9995 读取的 Omni 适配脚本目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/04适配脚本/omni"),
    ("GROK_SCRIPT_ROOT", "Grok 脚本输入", "9995 读取的 Grok 适配脚本目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/04适配脚本/grok"),
    ("REFERENCE_ROOT", "产品参考图", "9995 读取的产品底图目录", "${OPC_VAULT_ROOT}/wiki/产品/产品底图"),
    ("VIDEO_OUTPUT_ROOT", "Omni 视频输出", "9995 保存 Omni 视频片段的目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/05AI片段/omni"),
    ("GROK_VIDEO_OUTPUT_ROOT", "Grok 视频输出", "9995 保存 Grok 视频片段的目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/05AI片段/grok"),
    ("VIDEO_ASSEMBLY_PENDING_ROOT", "合成工作区", "9995 导出、9998 扫描待拼接内容的目录", "${OPC_VAULT_ROOT}/wiki/视频/纯AI视频/06合成工作区"),
    ("VIDEO_ASSEMBLY_OUTPUT_ROOT", "成品视频", "9998 输出、9996 管理的统一产品成品目录", "${OPC_VAULT_ROOT}/wiki/视频/成品视频"),
    ("VIDEO_TITLE_LIBRARY_ROOT", "视频标题库", "9996 读取的全线路共享标题与标签目录", "${OPC_VAULT_ROOT}/wiki/视频/成品视频/视频标题库"),
    ("SCRIPT_MISTAKE_BOOK_ROOT", "脚本错题本", "9993 与 10003 共享的产品级脚本纠错知识库", "${OPC_VAULT_ROOT}/wiki/视频/共享知识库/脚本错题本"),
)

GLOBAL_PATH_GROUPS = (
    {
        "id": "shared",
        "label": "全局共享",
        "description": "所有 Agent 默认继承的资料库根目录",
        "keys": ("OPC_VAULT_ROOT",),
    },
    {
        "id": "9992",
        "label": "9992 · 脚本解析",
        "description": "只管理正式业务输入与业务输出；Agent 内部临时目录自动维护",
        "keys": ("VIDEO_TEARDOWN_INPUT_ROOT", "VIDEO_TEARDOWN_OUTPUT_ROOT"),
    },
    {
        "id": "9993",
        "label": "9993 · 脚本产出",
        "description": "正式产品脚本输出；9994 以此作为业务输入",
        "keys": ("PRODUCT_SCRIPT_ROOT",),
    },
    {
        "id": "script_knowledge",
        "label": "9993 / 10003 · 脚本知识库",
        "description": "两条脚本生产线路共享，按产品名读取同名错题本 Markdown",
        "keys": ("SCRIPT_MISTAKE_BOOK_ROOT",),
    },
    {
        "id": "10002",
        "label": "10002 · 混剪参考视频解析",
        "description": "保持混剪-钩子|混剪-CTA/<产品名>目录层级",
        "keys": ("HYBRID_VIDEO_TEARDOWN_INPUT_ROOT", "HYBRID_VIDEO_TEARDOWN_OUTPUT_ROOT"),
    },
    {
        "id": "10003",
        "label": "10003 · 钩子与 CTA 脚本复刻裂变",
        "description": "按混剪-钩子|混剪-CTA/<产品名>/<来源脚本>保持目录层级",
        "keys": ("HYBRID_SCRIPT_GENERATION_INPUT_ROOT", "HYBRID_SCRIPT_GENERATION_OUTPUT_ROOT"),
    },
    {
        "id": "9995",
        "label": "9995 · 片段产出",
        "description": "纯 AI Omni/Grok 与混剪钩子、CTA Omni 的独立输入输出路径",
        "keys": (
            "SCRIPT_ROOT",
            "GROK_SCRIPT_ROOT",
            "HYBRID_OMNI_SCRIPT_ROOT",
            "REFERENCE_ROOT",
            "VIDEO_OUTPUT_ROOT",
            "GROK_VIDEO_OUTPUT_ROOT",
            "HYBRID_OMNI_VIDEO_OUTPUT_ROOT",
        ),
    },
    {
        "id": "10000",
        "label": "10000 · AI＋实拍混剪",
        "description": "读取 AI 片段、产品音频和展示/使用实拍池；成片复用 9998 的统一输出目录",
        "keys": ("HYBRID_AI_CLIP_ROOT", "HYBRID_PRODUCT_AUDIO_ROOT", "HYBRID_REAL_FOOTAGE_ROOT", "HYBRID_MIX_WORK_ROOT"),
    },
    {
        "id": "10004",
        "label": "10004 · 配音智能体",
        "description": "读取音频文案并把生成结果写入10000共用的产品音频目录",
        "keys": ("HYBRID_AUDIO_COPY_ROOT",),
    },
    {
        "id": "9998",
        "label": "9998 · 片段合成",
        "description": "待拼接视频片段的扫描目录和最终成品输出目录",
        "keys": ("VIDEO_ASSEMBLY_PENDING_ROOT", "VIDEO_ASSEMBLY_OUTPUT_ROOT"),
    },
    {
        "id": "9996",
        "label": "9996 · 成品管理",
        "description": "标题库由所有成品视频线路共享；成品目录复用 9998 的输出路径",
        "keys": ("VIDEO_TITLE_LIBRARY_ROOT",),
    },
)

OTHER_AGENT_PATH_NOTES = (
    {"port": "9991", "label": "视频采集", "note": "输出复用 9992 的“来源素材”路径"},
    {"port": "9994", "label": "脚本适配", "note": "读取 9993 产品脚本，写入 04适配脚本/{veo,omni,grok}"},
    {"port": "9997", "label": "产品脚本改写", "note": "输入输出复用 9992 的“参考脚本”路径"},
    {"port": "9999", "label": "混剪脚本适配", "note": "输入输出路径由独立 Agent 配置管理"},
    {"port": "10001", "label": "混剪参考视频采集", "note": "输出到AI实拍混剪/01参考视频/<类型>/<产品名>"},
    {"port": "10005", "label": "自动发布流水线", "note": "继承9993–9998的业务路径，但使用独立任务数据库和执行进程"},
)

GLOBAL_AI_GROUPS = (
    {
        "id": "video_analysis",
        "label": "视频解析模型",
        "description": "9992、10002 共同继承，用于读取视频并生成解析脚本",
    },
    {
        "id": "text",
        "label": "文本生成模型",
        "description": "9993、9994、9997、9999、10003 共同继承",
    },
    {
        "id": "otu",
        "label": "Omni 图像与视频",
        "description": "9995 的 Omni 人物图、故事版和视频片段生成",
    },
    {
        "id": "grok",
        "label": "Grok 图像与视频",
        "description": "9995 的 Grok 人物图、故事版和视频片段生成",
    },
)

GLOBAL_AI_FIELDS = (
    ("OPC_VIDEO_ANALYSIS_API_BASE_URL", "API 地址", "video_analysis", "url", "https://zexapi.com"),
    ("OPC_VIDEO_ANALYSIS_MODEL", "模型", "video_analysis", "text", "gemini-3.5-flash"),
    ("OPC_VIDEO_ANALYSIS_API_KEY", "API Key", "video_analysis", "password", ""),
    ("OPC_TEXT_API_BASE_URL", "API 地址", "text", "url", "https://api.deepseek.com"),
    ("OPC_TEXT_MODEL", "模型", "text", "text", "deepseek-v4-pro"),
    ("OPC_TEXT_API_KEY", "API Key", "text", "password", ""),
    ("OTU_BASE_URL", "API 地址", "otu", "url", "https://zexapi.com"),
    ("IMAGE_MODEL", "图像模型", "otu", "text", "gpt-image-2-4K"),
    ("OMNI_MODEL", "视频模型", "otu", "text", "omni_flash-10s"),
    ("OTU_API_KEY", "API Key", "otu", "password", ""),
    ("GROK_BASE_URL", "API 地址", "grok", "url", "https://www.runninghub.cn"),
    ("GROK_IMAGE_MODEL", "图像模型", "grok", "text", "G-2.0"),
    ("GROK_VIDEO_MODEL", "视频模型", "grok", "text", "X v1.5"),
    ("GROK_API_KEY", "API Key", "grok", "password", ""),
)

GLOBAL_AI_SECRET_FALLBACKS = {
    "OPC_VIDEO_ANALYSIS_API_KEY": ("VIDEO_TEARDOWN_AGENT_API_KEY", "MODELMESH_API_KEY"),
    "OPC_TEXT_API_KEY": ("DEEPSEEK_API_KEY", "MODELMESH_API_KEY"),
}


def unquote_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def read_global_path_values(env_file: Path = ENV_FILE) -> dict[str, str]:
    defaults = {key: default for key, _label, _description, default in GLOBAL_PATH_FIELDS}
    if not env_file.is_file():
        return defaults
    allowed = set(defaults)
    values = defaults.copy()
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", raw_line)
        if match and match.group(1) in allowed:
            values[match.group(1)] = unquote_env_value(match.group(2))
    return values


def read_env_values(env_file: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_file.is_file():
        return values
    for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", raw_line)
        if match:
            values[match.group(1)] = unquote_env_value(match.group(2))
    return values


def global_ai_payload(env_file: Path = ENV_FILE) -> dict:
    env_values = read_env_values(env_file)
    fields = []
    for key, label, group, field_type, default in GLOBAL_AI_FIELDS:
        value = str(env_values.get(key) or "").strip()
        if field_type == "password" and not value:
            for fallback_key in (key, *GLOBAL_AI_SECRET_FALLBACKS.get(key, ())):
                value = str(env_values.get(fallback_key) or os.environ.get(fallback_key) or "").strip()
                if value:
                    break
        fields.append(
            {
                "key": key,
                "label": label,
                "group": group,
                "type": field_type,
                "value": "" if field_type == "password" else (value or default),
                "configured": bool(value) if field_type == "password" else True,
            }
        )
    return {
        "env_file": str(env_file),
        "groups": list(GLOBAL_AI_GROUPS),
        "fields": fields,
        "note": "Agent 页面修改仅在当前进程有效；重启后重新继承这里的全局值。",
    }


def save_global_ai_settings(updates: dict, env_file: Path = ENV_FILE) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("AI 配置格式错误")
    field_map = {field[0]: field for field in GLOBAL_AI_FIELDS}
    unknown = set(updates) - set(field_map)
    if unknown:
        raise ValueError(f"未知 AI 配置：{sorted(unknown)[0]}")

    clean_updates: dict[str, str] = {}
    for key, raw_value in updates.items():
        _key, _label, _group, field_type, _default = field_map[key]
        value = str(raw_value or "").strip()
        if field_type == "password" and not value:
            continue
        if not value or "\n" in value or "\r" in value or "\0" in value:
            raise ValueError(f"{key} 的值无效")
        if field_type == "url" and not re.match(r"^https?://", value, re.IGNORECASE):
            raise ValueError(f"{key} 必须以 http:// 或 https:// 开头")
        clean_updates[key] = value.rstrip("/") if field_type == "url" else value

    existing_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    remaining = set(clean_updates)
    output_lines = []
    for line in existing_lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else ""
        if key in clean_updates:
            output_lines.append(f"{key}={json.dumps(clean_updates[key], ensure_ascii=False)}")
            remaining.discard(key)
        else:
            output_lines.append(line)
    for key, _label, _group, _field_type, _default in GLOBAL_AI_FIELDS:
        if key in remaining:
            output_lines.append(f"{key}={json.dumps(clean_updates[key], ensure_ascii=False)}")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as handle:
        handle.write("\n".join(output_lines) + "\n")
        temporary_path = Path(handle.name)
    if env_file.exists():
        temporary_path.chmod(env_file.stat().st_mode)
    os.replace(temporary_path, env_file)
    return global_ai_payload(env_file)


def migrate_global_ai_secrets(env_file: Path = ENV_FILE) -> int:
    env_values = read_env_values(env_file)
    updates: dict[str, str] = {}
    for key, _label, _group, field_type, _default in GLOBAL_AI_FIELDS:
        if field_type != "password" or env_values.get(key):
            continue
        for source_key in (key, *GLOBAL_AI_SECRET_FALLBACKS.get(key, ())):
            value = str(env_values.get(source_key) or os.environ.get(source_key) or "").strip()
            if value:
                updates[key] = value
                break
    if updates:
        save_global_ai_settings(updates, env_file)
    return len(updates)


def global_ai_migration_payload(env_file: Path = ENV_FILE) -> dict:
    return load_ai_migration_report(env_file.parent)


def resolve_global_ai_migration(choices: dict, env_file: Path = ENV_FILE) -> dict:
    if not isinstance(choices, dict):
        raise ValueError("迁移选择格式错误")
    return resolve_ai_migration_conflicts(env_file.parent, choices)


def resolve_path_values(values: dict[str, str]) -> dict[str, str]:
    variable_pattern = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
    resolved: dict[str, str] = {}

    def resolve(key: str, stack: set[str]) -> str:
        if key in resolved:
            return resolved[key]
        if key in stack:
            raise ValueError(f"路径变量存在循环引用：{key}")
        stack = stack | {key}

        def replace(match: re.Match[str]) -> str:
            name = match.group(1) or match.group(2)
            if name in values:
                return resolve(name, stack)
            return os.environ.get(name, match.group(0))

        value = variable_pattern.sub(replace, values[key])
        resolved[key] = str(Path(value).expanduser())
        return resolved[key]

    for field_key in values:
        resolve(field_key, set())
    return resolved


def path_writable(path: Path) -> bool:
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)


def global_paths_payload(env_file: Path = ENV_FILE) -> dict:
    values = read_global_path_values(env_file)
    resolved = resolve_path_values(values)
    group_by_key = {
        key: group["id"]
        for group in GLOBAL_PATH_GROUPS
        for key in group["keys"]
    }
    paths = []
    for key, label, description, _default in GLOBAL_PATH_FIELDS:
        path = Path(resolved[key])
        paths.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "group": group_by_key[key],
                "value": values[key],
                "resolved": resolved[key],
                "exists": path.is_dir(),
                "writable": path_writable(path),
            }
        )
    return {
        "env_file": str(env_file),
        "groups": [{key: value for key, value in group.items() if key != "keys"} for group in GLOBAL_PATH_GROUPS],
        "other_agents": list(OTHER_AGENT_PATH_NOTES),
        "paths": paths,
    }


def save_global_paths(updates: dict, env_file: Path = ENV_FILE) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("路径配置格式错误")
    allowed = {key for key, _label, _description, _default in GLOBAL_PATH_FIELDS}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"未知路径配置：{sorted(unknown)[0]}")

    values = read_global_path_values(env_file)
    for key, raw_value in updates.items():
        value = str(raw_value).strip()
        if not value or "\n" in value or "\r" in value or "\0" in value:
            raise ValueError(f"{key} 的路径无效")
        values[key] = value

    resolved = resolve_path_values(values)
    for key, value in resolved.items():
        if not Path(value).is_absolute():
            raise ValueError(f"{key} 必须解析为绝对路径")

    existing_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.is_file() else []
    remaining = set(updates)
    output_lines = []
    for line in existing_lines:
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else ""
        if key in updates:
            output_lines.append(f"{key}={json.dumps(values[key], ensure_ascii=False)}")
            remaining.discard(key)
        else:
            output_lines.append(line)
    for key, _label, _description, _default in GLOBAL_PATH_FIELDS:
        if key in remaining:
            output_lines.append(f"{key}={json.dumps(values[key], ensure_ascii=False)}")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=env_file.parent, delete=False) as handle:
        handle.write("\n".join(output_lines) + "\n")
        temporary_path = Path(handle.name)
    if env_file.exists():
        temporary_path.chmod(env_file.stat().st_mode)
    os.replace(temporary_path, env_file)

    if env_file.resolve() == ENV_FILE.resolve():
        os.environ.update(resolved)
    return global_paths_payload(env_file)


def service_running(service: dict) -> bool:
    try:
        request = urllib.request.Request(
            urljoin(service["health_url"], service["health_path"].lstrip("/")),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=1.2) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def service_status(service_id: str) -> dict:
    service = SERVICES[service_id]
    running = service_running(service)
    return {
        "id": service_id,
        "label": service["label"],
        "description": service["description"],
        "url": service["url"],
        "running": running,
        "process_running": running,
    }


def services_payload() -> dict:
    return {"services": [service_status(service_id) for service_id in SERVICES]}


def updater_request(path: str, method: str = "GET") -> tuple[int, dict]:
    try:
        token = UPDATER_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return 503, {"state": "unavailable", "message": f"更新服务尚未就绪：{exc}"}
    request = urllib.request.Request(
        f"{UPDATER_URL}{path}",
        data=b"{}" if method == "POST" else None,
        headers={"X-OPC-Updater-Token": token, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"error": str(exc)}
        return exc.code, payload
    except Exception as exc:
        return 503, {"state": "unavailable", "message": f"无法连接独立更新服务：{exc}"}


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OPC 内容量化增长引擎</title>
<style>
:root{color-scheme:dark;--bg:#0b0d10;--panel:#15191f;--line:#29313b;--text:#f3f5f7;--muted:#98a2ad;--green:#66d19e;--blue:#70a7ff;--amber:#f2bd67}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#18202b 0,#0b0d10 42%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:auto;padding:64px 24px 80px}header{display:flex;justify-content:space-between;gap:32px;align-items:end;margin-bottom:36px}h1{font-size:clamp(32px,5vw,58px);line-height:1.03;margin:0 0 14px;letter-spacing:-.04em}header p{max-width:700px;color:var(--muted);font-size:17px;line-height:1.7;margin:0}.headerTools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.summary{white-space:nowrap;color:var(--muted);padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:#11151a}
.workflows{display:grid;gap:20px}.workflow,.destination{padding:22px;border:1px solid var(--line);border-radius:20px;background:#101419b8;box-shadow:0 16px 48px #0004}.workflowHead{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:16px}.workflowTitle{font-size:24px;font-weight:760}.workflowDescription{color:var(--muted);font-size:13px;line-height:1.5;text-align:right}.flow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.card{display:flex;flex-direction:column;height:160px;padding:17px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,#181d24,#11151a)}.card.planned{border-style:dashed;background:linear-gradient(145deg,#191813,#11151a)}.top{display:flex;justify-content:space-between;gap:12px;align-items:center}.step{font-size:11px;color:var(--blue);letter-spacing:.1em}.status{font-size:11px;color:var(--muted);white-space:nowrap}.status::before{content:"";display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:#59636e}.status.on{color:var(--green)}.status.on::before{background:var(--green);box-shadow:0 0 12px var(--green)}.status.planned{color:var(--amber)}.status.planned::before{background:var(--amber)}h2{min-height:47px;font-size:18px;line-height:1.3;margin:18px 0 7px}.card .actions{display:flex;gap:7px;margin-top:auto}.actions>*{flex:1;text-align:center}button,a.button{appearance:none;border:1px solid var(--line);background:#202733;color:var(--text);padding:8px 7px;border-radius:9px;font:12px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;white-space:nowrap;text-decoration:none;cursor:pointer}button.primary{background:#e7edf5;color:#11161d;border-color:#e7edf5}button:disabled{opacity:.45;cursor:wait}.destination{margin-top:20px}.destination .flow{display:block}.destination .card{width:calc((100% - 50px)/6);margin:auto}.destinationHead{text-align:center;margin-bottom:16px}.destinationTitle{font-size:24px;font-weight:760}.destinationDescription{margin-top:6px;color:var(--muted);font-size:13px}.note{margin-top:30px;color:var(--muted);font-size:13px;text-align:center}
.updateButton{background:#e7edf5;color:#11161d;border-color:#e7edf5;padding:10px 14px}.overlay{display:none;position:fixed;inset:0;z-index:20;background:#05070acc;align-items:center;justify-content:center;padding:22px}.overlay.show{display:flex}.updatePanel{width:min(680px,100%);max-height:82vh;overflow:auto;padding:24px;border:1px solid var(--line);border-radius:18px;background:#15191f;box-shadow:0 28px 100px #000b}.updateHead{display:flex;justify-content:space-between;align-items:start;gap:18px}.updateHead h2{min-height:0;margin:0 0 7px;font-size:24px}.updateMessage{color:var(--muted);line-height:1.6}.updateState{margin:18px 0;padding:14px;border:1px solid var(--line);border-radius:12px;background:#0d1116}.updateState.complete{border-color:#386a55;color:var(--green)}.updateState.blocked,.updateState.failed{border-color:#7b4b38;color:#ffac91}.updateLog{display:none;max-height:240px;overflow:auto;margin:12px 0 0;padding:14px;border-radius:10px;background:#090b0e;color:#aeb8c3;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}.updateLog.show{display:block}.updateActions{display:flex;justify-content:flex-end;gap:9px;margin-top:18px}.updateActions button{padding:10px 14px}.dirtyList{margin:10px 0 0;padding-left:20px;color:#ffb49e;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
@media(max-width:1000px){.flow{grid-template-columns:repeat(3,minmax(0,1fr))}.destination .card{width:calc((100% - 20px)/3)}}
@media(max-width:700px){main{padding-top:38px}header{align-items:start;flex-direction:column}.summary{white-space:normal}.workflowHead{align-items:start;flex-direction:column}.workflowDescription{text-align:left}.flow{grid-template-columns:1fr}.destination .card{width:100%}}
</style>
</head>
<body><main><header><div><h1>OPC 内容量化增长引擎</h1><p>按手动生产线路与自动发布流水线组织现有 Agent。手动 Agent 保持独立，自动流水线复用底层能力。</p></div><div class="headerTools"><button class="updateButton" onclick="openUpdate()">本地更新</button><a class="button" href="/settings/ai">全局 API / 模型</a><a class="button" href="/settings/paths">全局路径设置</a><div class="summary" id="summary">正在检测服务…</div></div></header><section class="workflows" id="workflows"></section><section class="destination"><div class="destinationHead"><div class="destinationTitle">统一归口 · 成品管理与发布</div><div class="destinationDescription">三条线路的最终成片统一进入成品目录，由同一个 Agent 扫描、管理和发布。</div></div><div class="flow" id="destination"></div></section><p class="note">控制台端口 8888 · 已接入 15 个 Agent</p></main><div class="overlay" id="updateOverlay"><section class="updatePanel"><div class="updateHead"><div><h2>应用本地更新</h2><div class="updateMessage" id="updateMessage">请先手动拉取 GitHub 代码。这里会应用当前本地代码、迁移配置、重建 Docker，并等待全部 Agent 恢复正常。</div></div><button onclick="closeUpdate()">关闭</button></div><div class="updateState" id="updateState">准备应用本地更新</div><ul class="dirtyList" id="dirtyList"></ul><pre class="updateLog" id="updateLog"></pre><div class="updateActions"><button id="startUpdateButton" class="primary" onclick="startUpdate()">应用本地更新</button></div></section></div>
<script>
const workflowsHost=document.querySelector('#workflows'),destination=document.querySelector('#destination'),summary=document.querySelector('#summary'),updateOverlay=document.querySelector('#updateOverlay'),updateState=document.querySelector('#updateState'),updateMessage=document.querySelector('#updateMessage'),updateLog=document.querySelector('#updateLog'),dirtyList=document.querySelector('#dirtyList'),startUpdateButton=document.querySelector('#startUpdateButton');
const workflowLines=[
  {title:'线路 1 · 爆款复刻',description:'从爆款视频采集开始，完成纯 AI 脚本、片段与成片生产。',steps:['collect','analyze','script','adapt','assemble','compose']},
  {title:'线路 2 · 产品脚本改写',description:'从产品脚本改写开始，继续进入纯 AI 片段生产与合成。',steps:['rewrite','script','adapt','assemble','compose']},
  {title:'线路 3 · AI＋实拍混剪',description:'独立采集、解析、复刻裂变钩子/CTA参考视频，并生成混剪配音、AI首尾片段与实拍成片。',steps:['hybrid_collect','hybrid_analyze','hybrid_script','hybrid_adapt',{id:'assemble',label:'钩子与 CTA 片段产出'},'hybrid_voice','hybrid_mix']},
  {title:'线路 4 · 自动发布',description:'从已认可的复刻脚本开始，独立完成裂变、适配、片段、合成与串行发布。',steps:['auto_publish']}
];
let services=[];
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function cardHtml(step,index){const reference=typeof step==='string'?{id:step}:step;if(!reference.id){return `<article class="card planned"><div class="top"><span class="step">STEP ${String(index+1).padStart(2,'0')} · ${esc(reference.port)}</span><span class="status planned">待开发</span></div><h2>${esc(reference.label)}</h2><div class="actions"><button disabled>暂未接入</button></div></article>`}const service=services.find(item=>item.id===reference.id);if(!service)return '';return `<article class="card"><div class="top"><span class="step">STEP ${String(index+1).padStart(2,'0')} · ${esc(new URL(service.url).port)}</span><span class="status ${service.running?'on':''}">${service.running?'运行中':'未启动'}</span></div><h2>${esc(reference.label||service.label)}</h2><div class="actions"><a class="button" href="${esc(service.url)}" target="_blank" rel="noreferrer">打开</a></div></article>`}
function render(){workflowsHost.innerHTML=workflowLines.map(line=>`<section class="workflow"><div class="workflowHead"><div class="workflowTitle">${esc(line.title)}</div><div class="workflowDescription">${esc(line.description)}</div></div><div class="flow">${line.steps.map(cardHtml).join('')}</div></section>`).join('');destination.innerHTML=cardHtml({id:'finished'},0);const count=services.filter(s=>s.running).length;summary.textContent=`${count} / ${services.length} 个 Agent 运行中`;}
async function refresh(){try{const r=await fetch('/api/agent-services');const data=await r.json();services=data.services;render()}catch(e){summary.textContent='服务状态读取失败'}}
function openUpdate(){updateOverlay.className='overlay show';loadUpdateStatus()}
function closeUpdate(){updateOverlay.className='overlay'}
function renderUpdate(data){const state=data.state||'unavailable';updateState.className=`updateState ${state}`;updateState.textContent=data.message||'更新服务暂时不可用';dirtyList.innerHTML=(data.dirty_paths||[]).map(path=>`<li>${esc(path)}</li>`).join('');const lines=data.log_tail||[];updateLog.textContent=lines.join('\\n');updateLog.className=lines.length?'updateLog show':'updateLog';const running=state==='running';startUpdateButton.disabled=running;startUpdateButton.textContent=running?'本地更新进行中…':'重新应用本地更新';if(state==='idle')startUpdateButton.textContent='应用本地更新';if(state==='complete'){updateMessage.textContent='本地代码已应用，程序和全部 Agent 已恢复正常。';refresh()}else if(running){updateMessage.textContent='页面可以保持打开；8888 重启期间会自动等待并重新连接。'}else{updateMessage.textContent='请先手动拉取 GitHub 代码。应用前会检查本地改动；发现未提交文件时会停止，不会覆盖。'}}
async function loadUpdateStatus(){try{const r=await fetch('/api/system-update',{cache:'no-store'});const data=await r.json();renderUpdate(data)}catch(error){renderUpdate({state:'unavailable',message:'8888 正在重启，正在等待恢复…'})}}
async function startUpdate(){if(!confirm('确定应用当前本地代码，并重建全部 Agent 吗？'))return;startUpdateButton.disabled=true;renderUpdate({state:'running',message:'正在启动本地更新…'});try{const r=await fetch('/api/system-update',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const data=await r.json();renderUpdate(data)}catch(error){renderUpdate({state:'running',message:'连接暂时中断，正在等待 8888 恢复…'})}}
refresh();loadUpdateStatus();setInterval(refresh,4000);setInterval(()=>{if(updateOverlay.classList.contains('show'))loadUpdateStatus()},2000);
</script></body></html>"""

PATH_SETTINGS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全局路径设置 · OPC</title>
<style>
:root{color-scheme:dark;--bg:#0b0d10;--panel:#15191f;--line:#29313b;--text:#f3f5f7;--muted:#98a2ad;--green:#66d19e;--red:#ff8b8b;--blue:#70a7ff;--amber:#f3be63}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#18202b 0,#0b0d10 42%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:980px;margin:auto;padding:48px 24px 80px}header{display:flex;justify-content:space-between;gap:24px;align-items:start;margin-bottom:26px}h1{font-size:clamp(30px,5vw,48px);margin:0 0 12px;letter-spacing:-.035em}p{color:var(--muted);line-height:1.6;margin:0}.groups{display:grid;gap:16px}.panel{padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#181d24,#11151a);box-shadow:0 16px 48px #0005}.groupHead{padding-bottom:17px;border-bottom:1px solid var(--line)}.groupTitle{font-size:20px;font-weight:720;margin-bottom:5px}.groupDescription{font-size:13px;color:var(--muted)}.field{padding:18px 0;border-bottom:1px solid var(--line)}.field:last-child{border-bottom:0;padding-bottom:0}.fieldHead{display:flex;justify-content:space-between;gap:16px;margin-bottom:8px}.label{font-weight:650}.key{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--blue)}.description,.resolved{font-size:13px;color:var(--muted)}input{width:100%;margin:9px 0 7px;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#0d1116;color:var(--text);font:14px ui-monospace,SFMono-Regular,Menlo,monospace}.status{font-size:12px;margin-left:8px}.status.ok{color:var(--green)}.status.warn{color:var(--red)}.agentNotes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}.agentNote{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0d1116}.agentName{font-weight:650;margin-bottom:5px}.agentDetail{font-size:12px;color:var(--muted);line-height:1.5}.actions{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:20px;flex-wrap:wrap}button,a.button{appearance:none;border:1px solid var(--line);background:#202733;color:var(--text);padding:10px 14px;border-radius:10px;font:inherit;text-decoration:none;cursor:pointer}button.primary{background:#e7edf5;color:#11161d;border-color:#e7edf5}button:disabled{opacity:.5;cursor:wait}.message{font-size:13px;color:var(--muted)}.message.error{color:var(--red)}.envFile{margin:0 0 14px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
@media(max-width:700px){main{padding-top:32px}header{flex-direction:column}.fieldHead{flex-direction:column;gap:4px}.agentNotes{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<header><div><h1>全局路径设置</h1><p>这些值直接来自当前电脑的统一 <code>.env</code> 配置文件，并作为已接入 Agent 的全局默认路径。变量写法会原样保留。</p></div><a class="button" href="/">返回控制台</a></header>
<div class="envFile" id="envFile"></div>
<section class="groups" id="fields">正在读取路径…</section>
<div class="actions"><span class="message" id="message">保存后，新启动的 Agent 会读取新路径；已运行 Agent 需要重启。</span><button class="primary" id="saveButton" onclick="savePaths()">保存全局路径</button></div>
</main>
<script>
const fields=document.querySelector('#fields'),message=document.querySelector('#message'),saveButton=document.querySelector('#saveButton'),envFile=document.querySelector('#envFile');
let paths=[],groups=[],otherAgents=[];
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fieldHtml(item){return `<div class="field"><div class="fieldHead"><span class="label">${esc(item.label)}</span><span class="key">${esc(item.key)}</span></div><div class="description">${esc(item.description)}</div><input data-key="${esc(item.key)}" value="${esc(item.value)}"><div class="resolved">实际路径：${esc(item.resolved)} <span class="status ${item.exists&&item.writable?'ok':'warn'}">${item.exists?(item.writable?'目录存在且可写':'目录不可写'):'目录尚未创建'}</span></div></div>`}
function render(){const configured=groups.map(group=>`<section class="panel"><div class="groupHead"><div class="groupTitle">${esc(group.label)}</div><div class="groupDescription">${esc(group.description)}</div></div>${paths.filter(item=>item.group===group.id).map(fieldHtml).join('')}</section>`).join('');const inherited=`<section class="panel"><div class="groupHead"><div class="groupTitle">其他 Agent</div><div class="groupDescription">当前没有单独的全局路径键，按各自规则继承或使用 Agent 内部目录</div></div><div class="agentNotes">${otherAgents.map(item=>`<div class="agentNote"><div class="agentName">${esc(item.port)} · ${esc(item.label)}</div><div class="agentDetail">${esc(item.note)}</div></div>`).join('')}</div></section>`;fields.innerHTML=configured+inherited}
async function loadPaths(){const r=await fetch('/api/global-paths');const data=await r.json();if(!r.ok)throw new Error(data.error||'读取失败');paths=data.paths;groups=data.groups;otherAgents=data.other_agents;envFile.textContent=`配置文件：${data.env_file}`;render()}
async function savePaths(){saveButton.disabled=true;message.className='message';message.textContent='正在保存…';try{const updates={};document.querySelectorAll('input[data-key]').forEach(input=>updates[input.dataset.key]=input.value);const r=await fetch('/api/global-paths',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paths:updates})});const data=await r.json();if(!r.ok)throw new Error(data.error||'保存失败');paths=data.paths;render();message.textContent='保存成功。新启动的 Agent 将使用这些路径。'}catch(error){message.className='message error';message.textContent=error.message}finally{saveButton.disabled=false}}
loadPaths().catch(error=>{fields.textContent=error.message;message.className='message error';message.textContent='路径读取失败'})
</script>
</body></html>"""

AI_SETTINGS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全局 API / 模型设置 · OPC</title>
<style>
:root{color-scheme:dark;--bg:#0b0d10;--panel:#15191f;--line:#29313b;--text:#f3f5f7;--muted:#98a2ad;--green:#66d19e;--red:#ff8b8b;--blue:#70a7ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#18202b 0,#0b0d10 42%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:980px;margin:auto;padding:48px 24px 80px}header{display:flex;justify-content:space-between;gap:24px;align-items:start;margin-bottom:26px}h1{font-size:clamp(30px,5vw,48px);margin:0 0 12px;letter-spacing:-.035em}p{color:var(--muted);line-height:1.6;margin:0}.groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.panel{padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#181d24,#11151a);box-shadow:0 16px 48px #0005}.groupHead{padding-bottom:16px;border-bottom:1px solid var(--line)}.groupTitle{font-size:20px;font-weight:720;margin-bottom:5px}.groupDescription,.hint{font-size:13px;color:var(--muted);line-height:1.5}.field{padding-top:16px}.fieldHead{display:flex;justify-content:space-between;gap:12px;margin-bottom:7px}.label{font-weight:650}.key{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--blue)}input{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#0d1116;color:var(--text);font:14px ui-monospace,SFMono-Regular,Menlo,monospace}.configured{margin-top:6px;color:var(--green);font-size:12px}.actions{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:20px;flex-wrap:wrap}button,a.button{appearance:none;border:1px solid var(--line);background:#202733;color:var(--text);padding:10px 14px;border-radius:10px;font:inherit;text-decoration:none;cursor:pointer}button.primary{background:#e7edf5;color:#11161d;border-color:#e7edf5}button:disabled{opacity:.5;cursor:wait}.message{font-size:13px;color:var(--muted)}.message.error{color:var(--red)}.envFile{margin:0 0 14px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.notice{padding:14px 16px;margin-bottom:16px;border:1px solid #36506f;border-radius:12px;background:#111a25;color:#b9cbe0;font-size:13px;line-height:1.6}.migration{display:none;margin-bottom:18px;padding:18px;border:1px solid #72582a;border-radius:14px;background:#211b11}.migration.show{display:block}.migration h2{margin:0 0 8px;font-size:19px}.migration p{color:#d6c39f}.conflict{margin-top:14px;padding-top:14px;border-top:1px solid #554528}.choice{display:flex;gap:9px;align-items:flex-start;margin-top:8px;color:#e9edf2;font-size:13px}.choice input{width:auto;margin-top:2px}.choice small{display:block;color:var(--muted);margin-top:3px}.migration button{margin-top:16px;background:var(--amber);border-color:var(--amber);color:#1b1408;font-weight:700}@media(max-width:760px){main{padding-top:32px}header{flex-direction:column}.groups{grid-template-columns:1fr}.fieldHead{flex-direction:column;gap:4px}}
</style>
</head>
<body><main>
<header><div><h1>全局 API / 模型设置</h1><p>所有相关 Agent 默认继承这里的配置。Agent 页面允许临时覆盖，但重启 Agent 后会自动恢复全局设置。</p></div><a class="button" href="/">返回控制台</a></header>
<div class="envFile" id="envFile"></div><div class="notice">API Key 只保存到外置盘的 Docker 私有配置文件，不会写入 GitHub，也不会在页面中回显。保存后请重启相关 Agent，使全部进程重新继承全局值。</div>
<section class="migration" id="migration"></section>
<section class="groups" id="groups">正在读取配置…</section>
<div class="actions"><span class="message" id="message"></span><button class="primary" id="saveButton" onclick="saveSettings()">保存全局配置</button></div>
</main>
<script>
const groupsHost=document.querySelector('#groups'),message=document.querySelector('#message'),saveButton=document.querySelector('#saveButton'),envFile=document.querySelector('#envFile'),migrationHost=document.querySelector('#migration');let fields=[],groups=[];
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fieldHtml(field){const placeholder=field.type==='password'?(field.configured?'已配置；留空保持不变':'请输入 API Key'):'';return `<div class="field"><div class="fieldHead"><span class="label">${esc(field.label)}</span><span class="key">${esc(field.key)}</span></div><input data-key="${esc(field.key)}" type="${field.type==='password'?'password':'text'}" value="${esc(field.value)}" placeholder="${esc(placeholder)}" autocomplete="off">${field.type==='password'&&field.configured?'<div class="configured">已配置</div>':''}</div>`}
function render(){groupsHost.innerHTML=groups.map(group=>`<section class="panel"><div class="groupHead"><div class="groupTitle">${esc(group.label)}</div><div class="groupDescription">${esc(group.description)}</div></div>${fields.filter(field=>field.group===group.id).map(fieldHtml).join('')}</section>`).join('')}
async function loadSettings(){const r=await fetch('/api/global-ai-settings');const data=await r.json();if(!r.ok)throw new Error(data.error||'读取失败');fields=data.fields;groups=data.groups;envFile.textContent=`私有配置文件：${data.env_file}`;message.textContent=data.note;render()}
async function loadMigration(){const r=await fetch('/api/global-ai-migration');const data=await r.json();if(!r.ok)throw new Error(data.error||'迁移状态读取失败');if(data.status!=='pending'){migrationHost.className='migration';return}migrationHost.className='migration show';migrationHost.innerHTML=`<h2>发现旧 Agent 配置冲突</h2><p>${esc(data.message)} 迁移前备份：${esc(data.backup_dir||'')}</p>${data.conflicts.map(item=>`<div class="conflict"><strong>${esc(item.label)}</strong>${item.candidates.map((candidate,index)=>`<label class="choice"><input type="radio" name="migration-${esc(item.field)}" value="${esc(candidate.id)}" ${index===0?'checked':''}><span>${esc(candidate.display_value)}<small>${esc(candidate.source)}</small></span></label>`).join('')}</div>`).join('')}<button onclick="resolveMigration()">应用选择并完成迁移</button>`}
async function resolveMigration(){const choices={};migrationHost.querySelectorAll('input[type=radio]:checked').forEach(input=>choices[input.name.replace('migration-','')]=input.value);const r=await fetch('/api/global-ai-migration',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choices})});const data=await r.json();if(!r.ok)throw new Error(data.error||'迁移失败');await Promise.all([loadMigration(),loadSettings()]);message.textContent='旧配置迁移完成。请重启相关 Agent，使其继承迁移后的全局值。'}
async function saveSettings(){saveButton.disabled=true;message.className='message';message.textContent='正在保存…';try{const updates={};document.querySelectorAll('input[data-key]').forEach(input=>updates[input.dataset.key]=input.value);const r=await fetch('/api/global-ai-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:updates})});const data=await r.json();if(!r.ok)throw new Error(data.error||'保存失败');fields=data.fields;render();message.textContent='保存成功。重启相关 Agent 后，所有临时覆盖会清空并继承这些全局值。'}catch(error){message.className='message error';message.textContent=error.message}finally{saveButton.disabled=false}}
Promise.all([loadSettings(),loadMigration()]).catch(error=>{groupsHost.textContent=error.message;message.className='message error';message.textContent='配置读取失败'})
</script></body></html>"""


ROUTE_TO_SERVICE = {
    "/collect": "collect",
    "/analyze": "analyze",
    "/script": "script",
    "/adapt": "adapt",
    "/assemble": "assemble",
    "/finished": "finished",
    "/rewrite": "rewrite",
    "/compose": "compose",
    "/hybrid-adapt": "hybrid_adapt",
    "/hybrid-mix": "hybrid_mix",
    "/hybrid-collect": "hybrid_collect",
    "/hybrid-analyze": "hybrid_analyze",
    "/hybrid-script": "hybrid_script",
    "/hybrid-voice": "hybrid_voice",
    "/auto-publish": "auto_publish",
}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/settings/paths":
            body = PATH_SETTINGS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/settings/ai":
            body = AI_SETTINGS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ROUTE_TO_SERVICE:
            self.send_response(302)
            self.send_header("Location", SERVICES[ROUTE_TO_SERVICE[path]]["url"])
            self.end_headers()
        elif path in {"/api/agent-services", "/api/status"}:
            self.send_json(200, services_payload())
        elif path == "/api/global-paths":
            self.send_json(200, global_paths_payload())
        elif path == "/api/global-ai-settings":
            self.send_json(200, global_ai_payload())
        elif path == "/api/global-ai-migration":
            self.send_json(200, global_ai_migration_payload())
        elif path == "/api/system-update":
            status, payload = updater_request("/status")
            self.send_json(status, payload)
        elif path == "/health":
            self.send_json(200, {"ok": True, "service": "OPC-Console"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/global-paths":
                payload = self.read_json()
                self.send_json(200, save_global_paths(payload.get("paths")))
            elif path == "/api/global-ai-settings":
                payload = self.read_json()
                self.send_json(200, save_global_ai_settings(payload.get("settings")))
            elif path == "/api/global-ai-migration":
                payload = self.read_json()
                self.send_json(200, resolve_global_ai_migration(payload.get("choices")))
            elif path == "/api/system-update":
                status, payload = updater_request("/update", method="POST")
                self.send_json(status, payload)
            else:
                self.send_json(404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def log_message(self, *_args) -> None:
        return


def main() -> None:
    migration_status = global_ai_migration_payload().get("status")
    migrated_secret_count = 0 if migration_status == "pending" else migrate_global_ai_secrets()
    if migrated_secret_count:
        print(f"已迁移 {migrated_secret_count} 组全局 AI 密钥到 Docker 私有配置", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"OPC 内容量化增长引擎已启动: {url}", flush=True)
    if os.environ.get("KESAI_APP_NO_OPEN") != "1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
