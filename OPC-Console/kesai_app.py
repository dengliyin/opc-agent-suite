#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parent
ENV_FILE = Path(os.environ.get("OPC_ENV_FILE", WORKSPACE_ROOT / ".env")).expanduser()
HOST = os.environ.get("KESAI_APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KESAI_APP_PORT", "8888"))


def service_url(env_name: str, default: str) -> str:
    return os.environ.get(env_name, default)


def service_port(url: str, fallback: int) -> int:
    try:
        return int(urlparse(url).port or fallback)
    except (TypeError, ValueError):
        return fallback


def agent_python(agent_dir: Path) -> str:
    candidate = agent_dir / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else "python3"


VIDEO_COLLECTION_DIR = WORKSPACE_ROOT / "Video-Collection"
SCRIPT_ANALYSIS_DIR = WORKSPACE_ROOT / "Script-Analysis"
HYBRID_VIDEO_COLLECTION_DIR = WORKSPACE_ROOT / "Hybrid-Video-Collection"
HYBRID_SCRIPT_ANALYSIS_DIR = WORKSPACE_ROOT / "Hybrid-Script-Analysis"
HYBRID_SCRIPT_GENERATION_DIR = WORKSPACE_ROOT / "Hybrid-Script-Generation"
SCRIPT_GENERATION_DIR = WORKSPACE_ROOT / "Script-Generation"
SCRIPT_ADAPTATION_DIR = WORKSPACE_ROOT / "Script-Adaptation"
SCRIPT_ADAPTATION_APP_DIR = SCRIPT_ADAPTATION_DIR / "software" / "Script-Adaptation-app"
VIDEO_GENERATION_DIR = WORKSPACE_ROOT / "Video-Generation"
FINISHED_VIDEO_MANAGER_DIR = WORKSPACE_ROOT / "Finished-Video-Manager"
PRODUCT_SCRIPT_REWRITE_DIR = WORKSPACE_ROOT / "Product-Script-Rewrite"
VIDEO_ASSEMBLY_DIR = WORKSPACE_ROOT / "Video-Assembly-hd"
HYBRID_SCRIPT_ADAPTATION_DIR = WORKSPACE_ROOT / "Hybrid-Script-Adaptation"
HYBRID_SCRIPT_ADAPTATION_APP_DIR = HYBRID_SCRIPT_ADAPTATION_DIR / "software" / "Hybrid-Script-Adaptation-app"
HYBRID_VIDEO_MIXER_DIR = WORKSPACE_ROOT / "Hybrid-Video-Mixer"


def build_services() -> dict[str, dict]:
    urls = {
        "collect": service_url("OPC_HOT_VIDEO_AGENT_URL", "http://127.0.0.1:9991/"),
        "analyze": service_url("OPC_VIDEO_TEARDOWN_AGENT_URL", "http://127.0.0.1:9992/"),
        "script": service_url("OPC_SCRIPT_PRODUCTION_AGENT_URL", "http://127.0.0.1:9993/"),
        "adapt": service_url("OPC_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9994/"),
        "assemble": service_url("OPC_VIDEO_OUTPUT_AGENT_URL", "http://127.0.0.1:9995/"),
        "finished": service_url("OPC_FINISHED_VIDEO_MANAGER_URL", "http://127.0.0.1:9996/"),
        "rewrite": service_url("OPC_PRODUCT_SCRIPT_REWRITE_URL", "http://127.0.0.1:9997/"),
        "compose": service_url("OPC_VIDEO_ASSEMBLY_AGENT_URL", "http://127.0.0.1:9998/"),
        "hybrid_adapt": service_url("OPC_HYBRID_SCRIPT_ADAPTATION_AGENT_URL", "http://127.0.0.1:9999/"),
        "hybrid_mix": service_url("OPC_HYBRID_VIDEO_MIXER_AGENT_URL", "http://127.0.0.1:10000/"),
        "hybrid_collect": service_url("OPC_HYBRID_VIDEO_COLLECTION_AGENT_URL", "http://127.0.0.1:10001/"),
        "hybrid_analyze": service_url("OPC_HYBRID_SCRIPT_ANALYSIS_AGENT_URL", "http://127.0.0.1:10002/"),
        "hybrid_script": service_url("OPC_HYBRID_SCRIPT_GENERATION_AGENT_URL", "http://127.0.0.1:10003/"),
    }
    services = {
        "collect": {
            "label": "视频采集",
            "description": "采集 FastMoss 商品关联视频并下载 TikTok 素材",
            "url": urls["collect"],
            "cwd": VIDEO_COLLECTION_DIR,
            "command": [agent_python(VIDEO_COLLECTION_DIR), "-m", "hot_video_agent", "web", "--host", "127.0.0.1", "--port", str(service_port(urls["collect"], 9991))],
        },
        "analyze": {
            "label": "脚本解析",
            "description": "把本地短视频拆解成结构化 Markdown",
            "url": urls["analyze"],
            "cwd": SCRIPT_ANALYSIS_DIR,
            "command": [agent_python(SCRIPT_ANALYSIS_DIR), str(SCRIPT_ANALYSIS_DIR / "scripts" / "web_app.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["analyze"], 9992))],
        },
        "script": {
            "label": "脚本产出",
            "description": "根据产品资料和爆款参考生成带货脚本",
            "url": urls["script"],
            "cwd": SCRIPT_GENERATION_DIR,
            "command": [agent_python(SCRIPT_GENERATION_DIR), "-m", "opc_engine.features.script_generation.script_generation_agent_web", "--port", str(service_port(urls["script"], 9993))],
        },
        "adapt": {
            "label": "脚本适配",
            "description": "生成视频模型需要的分镜、图片提示词和任务表",
            "url": urls["adapt"],
            "cwd": SCRIPT_ADAPTATION_DIR,
            "launch_cwd": SCRIPT_ADAPTATION_APP_DIR,
            "command": [agent_python(SCRIPT_ADAPTATION_DIR), "-m", "opc_engine.features.script_adaptation.script_adaptation_agent_web", "--port", str(service_port(urls["adapt"], 9994))],
        },
        "assemble": {
            "label": "片段产出",
            "description": "生成人物图、故事版和视频片段",
            "url": urls["assemble"],
            "cwd": VIDEO_GENERATION_DIR,
            "command": [agent_python(VIDEO_GENERATION_DIR), "-m", "uvicorn", "agent.app:app", "--host", "127.0.0.1", "--port", str(service_port(urls["assemble"], 9995))],
        },
        "finished": {
            "label": "成品管理",
            "description": "查看成品、维护发布记录并处理 TikTok 发布",
            "url": urls["finished"],
            "cwd": FINISHED_VIDEO_MANAGER_DIR,
            "command": [agent_python(FINISHED_VIDEO_MANAGER_DIR), "-m", "finished_video_manager.web", "web", "--host", "127.0.0.1", "--port", str(service_port(urls["finished"], 9996))],
        },
        "rewrite": {
            "label": "产品脚本改写",
            "description": "把爆款脚本改写成目标产品版本",
            "url": urls["rewrite"],
            "cwd": PRODUCT_SCRIPT_REWRITE_DIR,
            "command": [agent_python(PRODUCT_SCRIPT_REWRITE_DIR), "-m", "product_script_rewrite.web", "--port", str(service_port(urls["rewrite"], 9997))],
        },
        "compose": {
            "label": "片段合成",
            "description": "离线拼接片段、校验成品并清理已用素材",
            "url": urls["compose"],
            "cwd": VIDEO_ASSEMBLY_DIR,
            "command": [agent_python(VIDEO_ASSEMBLY_DIR), str(VIDEO_ASSEMBLY_DIR / "app" / "server.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["compose"], 9998))],
        },
        "hybrid_adapt": {
            "label": "钩子与 CTA 脚本适配",
            "description": "把复刻裂变后的钩子与 CTA 脚本适配成视频模型片段指令",
            "url": urls["hybrid_adapt"],
            "cwd": HYBRID_SCRIPT_ADAPTATION_DIR,
            "launch_cwd": HYBRID_SCRIPT_ADAPTATION_APP_DIR,
            "command": [agent_python(HYBRID_SCRIPT_ADAPTATION_DIR), "-m", "opc_engine.features.script_adaptation.script_adaptation_agent_web", "--port", str(service_port(urls["hybrid_adapt"], 9999))],
        },
        "hybrid_mix": {
            "label": "AI＋实拍混剪",
            "description": "按产品音频编排 AI 首尾片段与展示、使用实拍素材",
            "url": urls["hybrid_mix"],
            "cwd": HYBRID_VIDEO_MIXER_DIR,
            "command": [agent_python(HYBRID_VIDEO_MIXER_DIR), str(HYBRID_VIDEO_MIXER_DIR / "app" / "server.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["hybrid_mix"], 10000))],
        },
        "hybrid_collect": {
            "label": "混剪参考视频采集",
            "description": "按类型和产品下载钩子或 CTA 参考视频",
            "url": urls["hybrid_collect"],
            "cwd": HYBRID_VIDEO_COLLECTION_DIR,
            "command": [agent_python(HYBRID_VIDEO_COLLECTION_DIR), "-m", "hot_video_agent", "web", "--host", "127.0.0.1", "--port", str(service_port(urls["hybrid_collect"], 10001))],
        },
        "hybrid_analyze": {
            "label": "混剪参考视频解析",
            "description": "按类型和产品把参考视频解析成 Markdown",
            "url": urls["hybrid_analyze"],
            "cwd": HYBRID_SCRIPT_ANALYSIS_DIR,
            "command": [agent_python(HYBRID_SCRIPT_ANALYSIS_DIR), str(HYBRID_SCRIPT_ANALYSIS_DIR / "scripts" / "web_app.py"), "--host", "127.0.0.1", "--port", str(service_port(urls["hybrid_analyze"], 10002))],
        },
        "hybrid_script": {
            "label": "钩子与 CTA 脚本复刻裂变",
            "description": "把解析脚本复刻为产品脚本并批量生成可独立使用的变体",
            "url": urls["hybrid_script"],
            "cwd": HYBRID_SCRIPT_GENERATION_DIR,
            "command": [agent_python(HYBRID_SCRIPT_GENERATION_DIR), "-m", "opc_engine.features.script_generation.script_generation_agent_web", "--port", str(service_port(urls["hybrid_script"], 10003))],
        },
    }
    for service_id, service in services.items():
        service["launch_agent_label"] = f"com.kesai.opc-agent.{service_id}"
    return services


SERVICES = build_services()

GLOBAL_PATH_FIELDS = (
    ("OPC_VAULT_ROOT", "资料库根目录", "所有 Agent 共用的内容资料库根目录", "$HOME/Documents/Obsidian Vault"),
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
)


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
        request = urllib.request.Request(service["url"], method="GET")
        with urllib.request.urlopen(request, timeout=1.2) as response:
            return 200 <= response.status < 500
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


def start_service(service_id: str) -> dict:
    if service_id not in SERVICES:
        raise ValueError("未知 Agent 服务")
    service = SERVICES[service_id]
    if service_running(service):
        return service_status(service_id) | {"started": False, "message": "服务已运行"}

    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{service['launch_agent_label']}"
    registration = subprocess.run(
        ["launchctl", "print", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if registration.returncode:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{service['launch_agent_label']}.plist"
        if not plist_path.is_file():
            raise RuntimeError(f"Agent LaunchAgent 配置不存在：{plist_path}")
        bootstrap = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode:
            detail = bootstrap.stderr.strip() or bootstrap.stdout.strip() or "launchctl bootstrap 失败"
            raise RuntimeError(f"Agent LaunchAgent 注册失败：{detail}")

    result = subprocess.run(
        ["launchctl", "kickstart", "-k", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "launchctl kickstart 失败"
        raise RuntimeError(f"Agent LaunchAgent 未安装或无法启动：{detail}")
    return service_status(service_id) | {"started": True, "message": "已发送启动命令"}


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
@media(max-width:1000px){.flow{grid-template-columns:repeat(3,minmax(0,1fr))}.destination .card{width:calc((100% - 20px)/3)}}
@media(max-width:700px){main{padding-top:38px}header{align-items:start;flex-direction:column}.summary{white-space:normal}.workflowHead{align-items:start;flex-direction:column}.workflowDescription{text-align:left}.flow{grid-template-columns:1fr}.destination .card{width:100%}}
</style>
</head>
<body><main><header><div><h1>OPC 内容量化增长引擎</h1><p>按三条视频生产线路组织现有 Agent。相同 Agent 在不同线路中共用同一个运行服务，业务参数和产物仍由对应 Agent 管理。</p></div><div class="headerTools"><a class="button" href="/settings/paths">全局路径设置</a><div class="summary" id="summary">正在检测服务…</div></div></header><section class="workflows" id="workflows"></section><section class="destination"><div class="destinationHead"><div class="destinationTitle">统一归口 · 成品管理与发布</div><div class="destinationDescription">三条线路的最终成片统一进入成品目录，由同一个 Agent 扫描、管理和发布。</div></div><div class="flow" id="destination"></div></section><p class="note">控制台端口 8888 · 已接入 13 个 Agent</p></main>
<script>
const workflowsHost=document.querySelector('#workflows'),destination=document.querySelector('#destination'),summary=document.querySelector('#summary');
const workflowLines=[
  {title:'线路 1 · 爆款复刻',description:'从爆款视频采集开始，完成纯 AI 脚本、片段与成片生产。',steps:['collect','analyze','script','adapt','assemble','compose']},
  {title:'线路 2 · 产品脚本改写',description:'从产品脚本改写开始，继续进入纯 AI 片段生产与合成。',steps:['rewrite','script','adapt','assemble','compose']},
  {title:'线路 3 · AI＋实拍混剪',description:'独立采集、解析、复刻裂变钩子/CTA参考视频，混合 AI 首尾片段与产品实拍素材。',steps:['hybrid_collect','hybrid_analyze','hybrid_script','hybrid_adapt',{id:'assemble',label:'钩子与 CTA 片段产出'},'hybrid_mix']}
];
let services=[];
const startingServices=new Set();
function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function cardHtml(step,index){const reference=typeof step==='string'?{id:step}:step;if(!reference.id){return `<article class="card planned"><div class="top"><span class="step">STEP ${String(index+1).padStart(2,'0')} · ${esc(reference.port)}</span><span class="status planned">待开发</span></div><h2>${esc(reference.label)}</h2><div class="actions"><button disabled>暂未接入</button></div></article>`}const service=services.find(item=>item.id===reference.id);if(!service)return '';const starting=startingServices.has(service.id)&&!service.running;return `<article class="card"><div class="top"><span class="step">STEP ${String(index+1).padStart(2,'0')} · ${esc(new URL(service.url).port)}</span><span class="status ${service.running?'on':''}">${service.running?'运行中':starting?'启动中…':'未启动'}</span></div><h2>${esc(reference.label||service.label)}</h2><div class="actions"><button class="primary" onclick="startService('${esc(service.id)}')" ${service.running||starting?'disabled':''}>${service.running?'已启动':starting?'启动中…':'启动'}</button><a class="button" href="${esc(service.url)}" target="_blank" rel="noreferrer">打开</a></div></article>`}
function render(){workflowsHost.innerHTML=workflowLines.map(line=>`<section class="workflow"><div class="workflowHead"><div class="workflowTitle">${esc(line.title)}</div><div class="workflowDescription">${esc(line.description)}</div></div><div class="flow">${line.steps.map(cardHtml).join('')}</div></section>`).join('');destination.innerHTML=cardHtml({id:'finished'},0);const count=services.filter(s=>s.running).length;summary.textContent=`${count} / ${services.length} 个 Agent 运行中`;}
async function refresh(){try{const r=await fetch('/api/agent-services');const data=await r.json();services=data.services;render()}catch(e){summary.textContent='服务状态读取失败'}}
async function waitForService(id){const deadline=Date.now()+30000;while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,1000));await refresh();if(services.some(s=>s.id===id&&s.running))return true}return false}
async function startService(id){startingServices.add(id);render();try{const r=await fetch('/api/agent-services/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});const data=await r.json();if(!r.ok)throw new Error(data.error||'启动失败');if(!await waitForService(id))throw new Error('Agent 启动超时，请检查对应运行日志')}catch(e){alert(e.message)}finally{startingServices.delete(id);await refresh()}}
refresh();setInterval(refresh,4000);
</script></body></html>"""

PATH_SETTINGS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全局路径设置 · OPC</title>
<style>
:root{color-scheme:dark;--bg:#0b0d10;--panel:#15191f;--line:#29313b;--text:#f3f5f7;--muted:#98a2ad;--green:#66d19e;--red:#ff8b8b;--blue:#70a7ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#18202b 0,#0b0d10 42%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:980px;margin:auto;padding:48px 24px 80px}header{display:flex;justify-content:space-between;gap:24px;align-items:start;margin-bottom:26px}h1{font-size:clamp(30px,5vw,48px);margin:0 0 12px;letter-spacing:-.035em}p{color:var(--muted);line-height:1.6;margin:0}.groups{display:grid;gap:16px}.panel{padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#181d24,#11151a);box-shadow:0 16px 48px #0005}.groupHead{padding-bottom:17px;border-bottom:1px solid var(--line)}.groupTitle{font-size:20px;font-weight:720;margin-bottom:5px}.groupDescription{font-size:13px;color:var(--muted)}.field{padding:18px 0;border-bottom:1px solid var(--line)}.field:last-child{border-bottom:0;padding-bottom:0}.fieldHead{display:flex;justify-content:space-between;gap:16px;margin-bottom:8px}.label{font-weight:650}.key{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--blue)}.description,.resolved{font-size:13px;color:var(--muted)}input{width:100%;margin:9px 0 7px;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#0d1116;color:var(--text);font:14px ui-monospace,SFMono-Regular,Menlo,monospace}.status{font-size:12px;margin-left:8px}.status.ok{color:var(--green)}.status.warn{color:var(--red)}.agentNotes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}.agentNote{padding:13px;border:1px solid var(--line);border-radius:12px;background:#0d1116}.agentName{font-weight:650;margin-bottom:5px}.agentDetail{font-size:12px;color:var(--muted);line-height:1.5}.actions{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:20px;flex-wrap:wrap}button,a.button{appearance:none;border:1px solid var(--line);background:#202733;color:var(--text);padding:10px 14px;border-radius:10px;font:inherit;text-decoration:none;cursor:pointer}button.primary{background:#e7edf5;color:#11161d;border-color:#e7edf5}button:disabled{opacity:.5;cursor:wait}.message{font-size:13px;color:var(--muted)}.message.error{color:var(--red)}.envFile{margin:0 0 14px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
@media(max-width:700px){main{padding-top:32px}header{flex-direction:column}.fieldHead{flex-direction:column;gap:4px}.agentNotes{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<header><div><h1>全局路径设置</h1><p>这些值直接来自项目根目录的 <code>.env</code>，并作为已接入 Agent 的全局默认路径。变量写法会原样保留。</p></div><a class="button" href="/">返回控制台</a></header>
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
        elif path in ROUTE_TO_SERVICE:
            self.send_response(302)
            self.send_header("Location", SERVICES[ROUTE_TO_SERVICE[path]]["url"])
            self.end_headers()
        elif path in {"/api/agent-services", "/api/status"}:
            self.send_json(200, services_payload())
        elif path == "/api/global-paths":
            self.send_json(200, global_paths_payload())
        elif path == "/health":
            self.send_json(200, {"ok": True, "service": "OPC-Console"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/agent-services/start":
                payload = self.read_json()
                self.send_json(200, start_service(str(payload.get("id", ""))))
            elif path == "/api/global-paths":
                payload = self.read_json()
                self.send_json(200, save_global_paths(payload.get("paths")))
            else:
                self.send_json(404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})

    def log_message(self, *_args) -> None:
        return


def main() -> None:
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
