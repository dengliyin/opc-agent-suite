#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import html
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opc_shared.global_ai import load_profile, runtime_override_active, set_runtime_overrides
from opc_shared.vault_snapshot import cached_or_empty, refresh_snapshot

from opc_engine.features.script_generation.generate_product_script import (
    CONFIG_DIR,
    DEFAULT_BASE_URL,
    DEFAULT_CONTENT_KNOWLEDGE_PATH,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_MUTATION_PROMPT_PATH,
    DEFAULT_MUTATION_VARIANTS,
    DEFAULT_PROMPT_PATH,
    DEFAULT_TIMEOUT,
    FEATURE_DIR,
    LOCAL_INPUTS_PATH,
    LOCAL_MODEL_SETTINGS_PATH,
    RUNTIME_CONFIG_DIR,
    ROOT,
    SHARED_MODEL_SETTINGS_PATH,
    apply_cli_overrides,
    get_api_key,
    get_reference_path,
    has_direct_file_inputs,
    load_script_generation_config,
    migrate_legacy_local_configs,
    product_project_ready,
    reference_country_author_and_video_id,
    read_json_config,
    run_script_pipeline,
    write_script_outputs,
)
from opc_engine.core.project_assets import infer_source_id, product_project_root


HOST = "127.0.0.1"
DEFAULT_PORT = 9993
IMPORTED_INPUTS_DIR = RUNTIME_CONFIG_DIR / "imported_inputs"
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__"
).expanduser()
PRODUCT_INFO_SOURCE_DIR = VAULT_ROOT / "wiki" / "产品" / "产品信息"
HOT_SCRIPT_SOURCE_ROOT = Path(
    os.environ.get(
        "VIDEO_TEARDOWN_OUTPUT_ROOT",
        str(VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "02参考脚本"),
    )
).expanduser()
SCRIPT_OUTPUT_SOURCE_ROOT = Path(
    os.environ.get(
        "PRODUCT_SCRIPT_ROOT",
        str(VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "03产品脚本"),
    )
).expanduser()
SCRIPT_MISTAKE_BOOK_SOURCE_ROOT = Path(
    os.environ.get(
        "SCRIPT_MISTAKE_BOOK_ROOT",
        str(VAULT_ROOT / "wiki" / "视频" / "共享知识库" / "脚本错题本"),
    )
).expanduser()
INPUT_KEYS = (
    "script_product_document_path",
    "script_reference_script_path",
    "script_reference_analysis_path",
    "script_reference_kind",
    "script_country",
    "script_target_language",
    "script_enable_mutation_rewrite",
    "script_mutation_variants",
    "output_dir",
    "script_generation_prompt_path",
    "script_generation_mutation_prompt_path",
    "script_content_knowledge_base_path",
)
MODEL_KEYS = (
    "modelmesh_api_key",
    "modelmesh_base_url",
    "script_generation_model",
    "script_generation_timeout",
    "script_generation_max_output_tokens",
)


def display_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.expanduser().as_posix()


def resolve_root_path(value: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def read_text(path: Path) -> str:
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def write_json_file(path: Path, payload: dict[str, Any], note: str) -> None:
    data = {"_说明": note}
    data.update(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def safe_import_name(filename: str, fallback: str) -> str:
    source = Path(str(filename or "").strip()).name
    if Path(source).suffix.lower() != ".md":
        raise ValueError("请选择 .md 格式的 Markdown 文档")
    stem = Path(source).stem or fallback
    safe_stem = "".join(ch if ch.isascii() and (ch.isalnum() or ch in ("-", "_")) else "_" for ch in stem)
    safe_stem = "_".join(part for part in safe_stem.split("_") if part) or fallback
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{safe_stem}.md"


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str = "text/html; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_request_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"请求 JSON 无效: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON object")
    return data


def file_stat(path: Path) -> dict[str, Any]:
    return {
        "path": display_path(path),
        "exists": path.exists(),
        "chars": len(read_text(path)),
    }


def strip_product_suffix(value: str) -> str:
    text = str(value or "").strip()
    return text.removesuffix("-产品信息").strip() or text


def product_name_from_path(path: str | Path) -> str:
    return strip_product_suffix(Path(path).expanduser().stem)


def output_dir_for_product(product_name: str) -> Path:
    return SCRIPT_OUTPUT_SOURCE_ROOT / (product_name.strip() or "未命名产品")


def mistake_book_for_product(product_name: str) -> Path | None:
    direct = SCRIPT_MISTAKE_BOOK_SOURCE_ROOT / f"{product_name}.md"
    if direct.is_file():
        return direct
    normalized = strip_product_suffix(product_name).lower()
    for path in sorted(SCRIPT_MISTAKE_BOOK_SOURCE_ROOT.glob("*.md"), key=lambda item: item.name.lower()):
        if strip_product_suffix(path.stem).lower() == normalized:
            return path
    return None


def iter_markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted((path for path in root.rglob("*.md") if path.is_file()), key=lambda item: item.name.lower())


def product_output_stems(product_name: str) -> tuple[str, ...]:
    output_root = output_dir_for_product(product_name)
    if not output_root.is_dir():
        return ()
    return tuple(path.stem for path in output_root.glob("*.md") if path.is_file())


def reference_output_status(
    product_name: str,
    reference_path: Path,
    output_stems: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    status = {"cloned": False, "mutation_count": 0}
    if output_stems is None:
        output_stems = product_output_stems(product_name)

    _country, author, source_id = reference_country_author_and_video_id(reference_path)
    identity = f"-{author}-{source_id}"
    for stem in output_stems:
        if identity not in stem:
            continue
        if stem.startswith("裂变-"):
            status["mutation_count"] += 1
        elif stem.startswith("复刻-"):
            status["cloned"] = True

    return status


def library_payload(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_script_generation_config()
    selected_product = str(config.get("script_product_document_path") or "")
    selected_reference = str(config.get("script_reference_script_path") or config.get("script_reference_analysis_path") or "")
    products: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    output_stems_by_product: dict[str, tuple[str, ...]] = {}

    for path in iter_markdown_files(PRODUCT_INFO_SOURCE_DIR):
        product_name = product_name_from_path(path)
        products.append(
            {
                "name": product_name,
                "path": path.as_posix(),
                "selected": bool(selected_product and resolve_root_path(selected_product) == path.resolve()),
            }
        )

    for path in iter_markdown_files(HOT_SCRIPT_SOURCE_ROOT):
        try:
            product_group = path.relative_to(HOT_SCRIPT_SOURCE_ROOT).parts[0]
        except (ValueError, IndexError):
            product_group = ""
        if product_group not in output_stems_by_product:
            output_stems_by_product[product_group] = product_output_stems(product_group)
        references.append(
            {
                "name": path.name,
                "path": path.as_posix(),
                "product": product_group,
                "selected": bool(selected_reference and resolve_root_path(selected_reference) == path.resolve()),
                "status": reference_output_status(product_group, path, output_stems_by_product[product_group]),
            }
        )

    return {
        "roots": {
            "product_info": PRODUCT_INFO_SOURCE_DIR.as_posix(),
            "hot_scripts": HOT_SCRIPT_SOURCE_ROOT.as_posix(),
            "script_outputs": SCRIPT_OUTPUT_SOURCE_ROOT.as_posix(),
            "mistake_books": SCRIPT_MISTAKE_BOOK_SOURCE_ROOT.as_posix(),
        },
        "products": products,
        "references": references,
    }


def cached_library_payload(config: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return refresh_snapshot("script-generation", "library", lambda: library_payload(config))
    return cached_or_empty(
        "script-generation",
        "library",
        lambda: {"paths": {}, "products": [], "references": []},
    )


def state_payload(refresh_library: bool = False) -> dict[str, Any]:
    config = load_script_generation_config()
    inputs = read_json_config(LOCAL_INPUTS_PATH)
    model = read_json_config(SHARED_MODEL_SETTINGS_PATH)
    model.update(read_json_config(LOCAL_MODEL_SETTINGS_PATH))
    profile = load_profile("text")
    model["modelmesh_base_url"] = profile["base_url"]
    model["script_generation_model"] = profile["model"]
    model["modelmesh_api_key"] = profile["api_key"]
    prompt_path = resolve_root_path(config.get("script_generation_prompt_path") or DEFAULT_PROMPT_PATH)
    mutation_prompt_path = resolve_root_path(config.get("script_generation_mutation_prompt_path") or DEFAULT_MUTATION_PROMPT_PATH)
    knowledge_path = resolve_root_path(config.get("script_content_knowledge_base_path") or SCRIPT_MISTAKE_BOOK_SOURCE_ROOT)
    if not str(prompt_path).startswith(str(CONFIG_DIR.resolve())):
        prompt_path = DEFAULT_PROMPT_PATH
    if not str(mutation_prompt_path).startswith(str(CONFIG_DIR.resolve())):
        mutation_prompt_path = DEFAULT_MUTATION_PROMPT_PATH
    if not knowledge_path.exists():
        knowledge_path = SCRIPT_MISTAKE_BOOK_SOURCE_ROOT
    product_path = resolve_root_path(config.get("script_product_document_path", "")) if config.get("script_product_document_path") else None
    reference_path = None
    try:
        reference_path = get_reference_path(config)
    except SystemExit:
        reference_path = None

    safe_model = dict(model)
    if safe_model.get("modelmesh_api_key"):
        safe_model["modelmesh_api_key"] = ""
    safe_inputs = {
        key: inputs.get(key, "")
        for key in (
            *INPUT_KEYS,
            "product_project_slug",
            "product_profile_path",
            "product_project_root",
        )
        if key in inputs
    }
    safe_inputs["script_generation_prompt_path"] = display_path(prompt_path)
    safe_inputs["script_generation_mutation_prompt_path"] = display_path(mutation_prompt_path)
    safe_inputs["script_content_knowledge_base_path"] = knowledge_path.as_posix()
    if product_path and not safe_inputs.get("output_dir"):
        safe_inputs["output_dir"] = output_dir_for_product(product_name_from_path(product_path)).as_posix()

    product_name = product_name_from_path(product_path) if product_path else ""
    mistake_path = mistake_book_for_product(product_name) if product_name else None

    return {
        "inputs": safe_inputs,
        "model": safe_model,
        "paths": {
            "feature_dir": display_path(FEATURE_DIR),
            "config_dir": display_path(RUNTIME_CONFIG_DIR),
            "bundled_config_dir": display_path(CONFIG_DIR),
            "inputs": display_path(LOCAL_INPUTS_PATH),
            "model_defaults": display_path(SHARED_MODEL_SETTINGS_PATH),
            "model_settings": display_path(LOCAL_MODEL_SETTINGS_PATH),
        },
        "files": {
            "prompt": file_stat(prompt_path),
            "mutation_prompt": file_stat(mutation_prompt_path),
            "knowledge": file_stat(knowledge_path),
            "mistake_book": file_stat(mistake_path) if mistake_path else {"path": "", "exists": False, "chars": 0},
            "product": file_stat(product_path) if product_path else {"path": "", "exists": False, "chars": 0},
            "reference": file_stat(reference_path) if reference_path else {"path": "", "exists": False, "chars": 0},
        },
        "texts": {
            "prompt": read_text(prompt_path),
            "mutation_prompt": read_text(mutation_prompt_path),
            "knowledge": read_text(mistake_path) if mistake_path else "",
        },
        "library": cached_library_payload(config, refresh_library),
        "status": {
            "has_api_key": bool(get_api_key(config) or os.environ.get("MODELMESH_API_KEY") or os.environ.get("GEMINI_API_KEY")),
            "product_project_ready": product_project_ready(config),
            "direct_file_ready": has_direct_file_inputs(config),
            "ai_settings_source": "本 Agent 临时覆盖" if runtime_override_active("text") else "8888 全局设置",
        },
    }


def save_state(payload: dict[str, Any]) -> dict[str, Any]:
    migrate_legacy_local_configs()
    inputs: dict[str, Any] = {}
    for key in INPUT_KEYS:
        if key in payload:
            inputs[key] = str(payload.get(key) or "").strip()

    reference_mode = str(payload.get("reference_mode") or "").strip()
    reference_path = str(payload.get("reference_path") or "").strip()
    if reference_mode == "script":
        inputs["script_reference_kind"] = "竞品爆款脚本"
        inputs["script_reference_script_path"] = reference_path
        inputs["script_reference_analysis_path"] = ""
    elif reference_mode == "analysis":
        inputs["script_reference_kind"] = "竞品视频拆解结果"
        inputs["script_reference_analysis_path"] = reference_path
        inputs["script_reference_script_path"] = ""

    local_model = read_json_config(LOCAL_MODEL_SETTINGS_PATH)
    for key in ("modelmesh_api_key", "modelmesh_base_url", "script_generation_model"):
        local_model.pop(key, None)
    for key in MODEL_KEYS:
        if key in payload:
            value = payload.get(key)
            if key in {"modelmesh_api_key", "modelmesh_base_url", "script_generation_model"}:
                continue
            if key in {"script_generation_timeout", "script_generation_max_output_tokens"}:
                local_model[key] = int(value or (DEFAULT_TIMEOUT if key.endswith("timeout") else DEFAULT_MAX_OUTPUT_TOKENS))
            else:
                local_model[key] = str(value or "").strip()
    set_runtime_overrides(
        "text",
        {
            "base_url": payload.get("modelmesh_base_url"),
            "model": payload.get("script_generation_model"),
            "api_key": payload.get("modelmesh_api_key"),
        },
    )

    if "prompt_text" in payload:
        DEFAULT_PROMPT_PATH.write_text(str(payload.get("prompt_text") or "").rstrip() + "\n", encoding="utf-8")
        inputs["script_generation_prompt_path"] = display_path(DEFAULT_PROMPT_PATH)
    if "mutation_prompt_text" in payload:
        DEFAULT_MUTATION_PROMPT_PATH.write_text(str(payload.get("mutation_prompt_text") or "").rstrip() + "\n", encoding="utf-8")
        inputs["script_generation_mutation_prompt_path"] = display_path(DEFAULT_MUTATION_PROMPT_PATH)
    if "knowledge_text" in payload:
        knowledge_text = str(payload.get("knowledge_text") or "")
        selected_product = str(payload.get("script_product_document_path") or "").strip()
        if selected_product:
            product_name = product_name_from_path(selected_product)
            target_path = mistake_book_for_product(product_name)
            if target_path and target_path.is_file():
                target_path.write_text(knowledge_text.rstrip() + "\n", encoding="utf-8")
        inputs["script_content_knowledge_base_path"] = SCRIPT_MISTAKE_BOOK_SOURCE_ROOT.as_posix()

    selected_product_doc = str(inputs.get("script_product_document_path") or payload.get("script_product_document_path") or "").strip()
    if selected_product_doc:
        product_name = product_name_from_path(selected_product_doc)
        inputs["output_dir"] = str(payload.get("output_dir") or output_dir_for_product(product_name).as_posix())
        inputs["product_project_slug"] = product_name
    inputs.setdefault("script_country", "不改变原脚本")
    inputs.setdefault("script_target_language", "不改变原脚本")
    inputs.setdefault("script_mutation_source", "复刻稿")
    inputs.setdefault("script_mutation_mode", "standard")
    inputs["script_content_knowledge_base_path"] = SCRIPT_MISTAKE_BOOK_SOURCE_ROOT.as_posix()

    preserved_input_keys = {
        *INPUT_KEYS,
        "product_project_slug",
        "product_profile",
        "product_profile_path",
        "product_project_root",
    }
    merged_inputs = {
        key: value
        for key, value in read_json_config(LOCAL_INPUTS_PATH).items()
        if key in preserved_input_keys
    }
    merged_inputs.update({key: value for key, value in inputs.items() if value != "" or key in inputs})
    write_json_file(LOCAL_INPUTS_PATH, merged_inputs, "脚本生成智能体本地输入配置。由可视化界面保存。")
    write_json_file(LOCAL_MODEL_SETTINGS_PATH, local_model, "脚本生成智能体本地模型配置与 API Key。请勿提交。")
    return state_payload()


def import_markdown_file(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "").strip()
    if kind not in {"product_doc", "reference"}:
        raise ValueError("当前只支持导入产品文档或竞品参考")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("Markdown 文档内容为空")
    if len(text) > 3_000_000:
        raise ValueError("产品文档过大，请控制在 300 万字符以内")
    filename = safe_import_name(str(payload.get("filename") or ""), "product_document" if kind == "product_doc" else "reference")
    target_dir = IMPORTED_INPUTS_DIR / ("product_documents" if kind == "product_doc" else "references")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    display = display_path(target_path)
    if kind == "product_doc":
        state = save_state({"script_product_document_path": display})
    else:
        state = save_state(
            {
                "reference_mode": "script",
                "reference_path": display,
                "script_reference_kind": "竞品爆款脚本/拆解稿",
                "script_reference_script_path": display,
                "script_reference_analysis_path": "",
            }
        )
    return {"path": display, "chars": len(text), "state": state}


def open_local_path(value: str) -> dict[str, str]:
    path = resolve_root_path(value)
    if not path.exists():
        raise ValueError(f"文件或目录不存在: {display_path(path)}")
    if path.is_file() and path.suffix.lower() == ".md":
        query = urllib.parse.urlencode({"path": str(path)})
        target = f"obsidian://open?{query}"
    else:
        target = str(path)
    subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"path": display_path(path)}


def add_unique_path(paths: list[Path], path: str | Path) -> None:
    resolved = resolve_root_path(str(path))
    if resolved not in paths:
        paths.append(resolved)


def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def output_file_type(path: Path) -> tuple[str, str]:
    if path.name.endswith(".raw.json"):
        return "raw", "原始响应"
    if path.suffix.lower() == ".md":
        return "script", "成品脚本"
    return "file", "文件"


def script_output_roots(config: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    configured_output = str(config.get("output_dir") or "").strip()
    if configured_output:
        add_unique_path(roots, configured_output)

    product_doc = str(config.get("script_product_document_path") or "").strip()
    if product_doc:
        add_unique_path(roots, output_dir_for_product(product_name_from_path(product_doc)))

    if product_project_ready(config):
        project_root = product_project_root(config)
        try:
            reference_path = get_reference_path(config)
            source_id = infer_source_id(reference_path)
            add_unique_path(roots, project_root / "hot_sources" / source_id / "scripts")
        except SystemExit:
            pass

        hot_sources_root = project_root / "hot_sources"
        if hot_sources_root.exists():
            for scripts_dir in sorted(hot_sources_root.glob("*/scripts")):
                source_name = scripts_dir.parent.name
                if scripts_dir.is_dir() and source_name.isdigit():
                    add_unique_path(roots, scripts_dir)

    add_unique_path(roots, FEATURE_DIR / "outputs")
    return roots


def list_script_outputs() -> dict[str, Any]:
    config = load_script_generation_config()
    roots = script_output_roots(config)
    outputs: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in root.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() != ".md":
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            stat = path.stat()
            file_type, kind = output_file_type(path)
            outputs.append(
                {
                    "name": path.name,
                    "path": display_path(path),
                    "type": file_type,
                    "kind": kind,
                    "mtime": stat.st_mtime,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                    "size": stat.st_size,
                    "size_label": format_file_size(stat.st_size),
                }
            )

    outputs.sort(key=lambda item: float(item.get("mtime") or 0), reverse=True)
    active_root = Path(outputs[0]["path"]).parent if outputs else (roots[0] if roots else FEATURE_DIR / "outputs")
    if outputs:
        active_root = resolve_root_path(str(active_root))
    return {
        "root": display_path(active_root),
        "roots": [display_path(root) for root in roots],
        "outputs": outputs[:120],
    }


def cached_script_outputs(refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return refresh_snapshot("script-generation", "outputs", list_script_outputs)
    return cached_or_empty("script-generation", "outputs", lambda: {"root": "", "roots": [], "outputs": []})


class ThreadWriter(io.TextIOBase):
    def __init__(self, job: "GenerationJob") -> None:
        self.job = job

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if text:
            self.job.append_log(text)
        return len(text)

    def flush(self) -> None:
        return None


class GenerationJob:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.max_workers = self._max_workers()
        self.next_id = 1
        self.active_count = 0
        self.queue: list[int] = []
        self.tasks: dict[int, dict[str, Any]] = {}
        self.logs = ""
        self.error = ""
        self.outputs: list[dict[str, str]] = []
        self.prompt_preview = ""

    def _max_workers(self) -> int:
        configured = os.environ.get("KESAI_MAX_CONCURRENT_TASK_GROUPS") or os.environ.get("KESAI_MAX_CONCURRENT_JOBS") or "3"
        try:
            return max(1, int(configured))
        except (TypeError, ValueError):
            return 3

    def append_log(self, text: str) -> None:
        with self.lock:
            self.logs += text
            if len(self.logs) > 160000:
                self.logs = self.logs[-160000:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            running = self.active_count > 0 or bool(self.queue)
            latest_task = max(self.tasks.values(), key=lambda item: int(item.get("id") or 0), default=None)
            if self.active_count > 0:
                status = "running"
            elif self.queue:
                status = "queued"
            elif latest_task:
                status = str(latest_task.get("status") or "idle")
            else:
                status = "idle"
            return {
                "running": running,
                "status": status,
                "active_count": self.active_count,
                "queued_count": len(self.queue),
                "max_workers": self.max_workers,
                "tasks": [
                    {
                        key: task.get(key)
                        for key in ("id", "status", "title", "dry_run", "created_at", "started_at", "finished_at", "error")
                    }
                    for task in sorted(self.tasks.values(), key=lambda item: int(item.get("id") or 0), reverse=True)[:30]
                ],
                "logs": self.logs,
                "error": self.error,
                "outputs": self.outputs,
                "prompt_preview": self.prompt_preview,
            }

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        reference_value = str(
            payload.get("script_reference_script_path")
            or payload.get("script_reference_analysis_path")
            or ""
        ).strip()
        if not reference_value:
            raise ValueError("请先选择有效的爆款参考文件：竞品爆款脚本或竞品视频拆解 Markdown")
        reference_path = resolve_root_path(reference_value)
        if reference_path.suffix.lower() != ".md" or not reference_path.is_file():
            raise ValueError("爆款参考文件无效或不存在，请重新选择 Markdown 文件")
        save_state(payload)
        with self.lock:
            task_id = self.next_id
            self.next_id += 1
            task = {
                "id": task_id,
                "payload": dict(payload),
                "status": "queued",
                "title": self._task_title(payload),
                "dry_run": bool(payload.get("dry_run")),
                "created_at": time.time(),
                "started_at": 0.0,
                "finished_at": 0.0,
                "error": "",
            }
            self.tasks[task_id] = task
            self.queue.append(task_id)
            self.logs += f"\n[任务 #{task_id}] 已加入队列：{task['title']}\n"
            if len(self.logs) > 160000:
                self.logs = self.logs[-160000:]
        self._schedule()
        return self.snapshot()

    def _task_title(self, payload: dict[str, Any]) -> str:
        reference = Path(str(payload.get("script_reference_script_path") or payload.get("script_reference_analysis_path") or "")).name
        stage = "Dry-run" if payload.get("dry_run") else ("裂变" if str(payload.get("script_enable_mutation_rewrite") or "").lower() in {"1", "true", "yes", "on", "是", "启用"} else "复刻")
        return f"{stage} · {reference or '未选择脚本'}"

    def _schedule(self) -> None:
        while True:
            with self.lock:
                if self.active_count >= self.max_workers or not self.queue:
                    return
                task_id = self.queue.pop(0)
                task = self.tasks.get(task_id)
                if not task:
                    continue
                task["status"] = "running"
                task["started_at"] = time.time()
                self.active_count += 1
                self.logs += f"[任务 #{task_id}] 开始执行（并发 {self.active_count}/{self.max_workers}）：{task['title']}\n"
                if len(self.logs) > 160000:
                    self.logs = self.logs[-160000:]
            threading.Thread(target=self._run, args=(task_id,), daemon=True).start()

    def _run(self, task_id: int) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            payload = dict(task.get("payload") or {}) if task else {}
        try:
            task_outputs = self._run_inner(task_id, payload)
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id]["status"] = "completed"
                self.outputs = task_outputs + self.outputs
                self.outputs = self.outputs[:80]
        except Exception as exc:  # noqa: BLE001 - surface exact local failure in UI.
            self._append_task_log(task_id, traceback.format_exc())
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id]["status"] = "failed"
                    self.tasks[task_id]["error"] = str(exc)
                self.error = str(exc)
        finally:
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id]["finished_at"] = time.time()
                self.active_count = max(0, self.active_count - 1)
        self._schedule()

    def _append_task_log(self, task_id: int, text: str) -> None:
        if not text:
            return
        prefix = f"[任务 #{task_id}] "
        lines = text.splitlines() or [text]
        self.append_log("".join(f"{prefix}{line}\n" for line in lines))

    def _run_inner(self, task_id: int, payload: dict[str, Any]) -> list[dict[str, str]]:
        temp_inputs = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        temp_inputs_path = Path(temp_inputs.name)
        temp_inputs.close()
        inputs_payload = {
            key: value
            for key, value in payload.items()
            if key in INPUT_KEYS or key in {"product_project_slug", "product_profile_path", "product_project_root"}
        }
        write_json_file(temp_inputs_path, inputs_payload, "脚本生成队列任务临时输入配置。")
        command = self._subprocess_command(payload)
        env = os.environ.copy()
        env["SCRIPT_GENERATION_INPUTS_PATH"] = str(temp_inputs_path)
        env["PYTHONUNBUFFERED"] = "1"
        self._append_task_log(task_id, "执行命令: " + " ".join(command))
        outputs: list[dict[str, str]] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                self._append_task_log(task_id, line.rstrip("\n"))
                stripped = line.strip()
                if stripped.startswith("脚本结果:"):
                    path = stripped.split("脚本结果:", 1)[1].strip()
                    outputs.append({"name": Path(path).name, "path": display_path(path), "type": "script"})
                elif stripped.startswith("原始响应:"):
                    path = stripped.split("原始响应:", 1)[1].strip()
                    outputs.append({"name": Path(path).name, "path": display_path(path), "type": "raw"})
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(f"任务子进程退出码: {return_code}")
            self._append_task_log(task_id, "任务完成")
            return outputs
        finally:
            with contextlib.suppress(OSError):
                temp_inputs_path.unlink()

    def _subprocess_command(self, payload: dict[str, Any]) -> list[str]:
        command = [sys.executable, "-u", "-m", "opc_engine.features.script_generation.generate_product_script"]
        option_pairs = [
            ("--model", payload.get("script_generation_model")),
            ("--base-url", payload.get("modelmesh_base_url")),
            ("--output-dir", payload.get("output_dir")),
            ("--product-doc", payload.get("script_product_document_path")),
            ("--reference-script", payload.get("script_reference_script_path")),
            ("--reference-analysis", payload.get("script_reference_analysis_path")),
            ("--country", payload.get("script_country")),
            ("--target-language", payload.get("script_target_language")),
            ("--timeout", payload.get("script_generation_timeout")),
            ("--max-output-tokens", payload.get("script_generation_max_output_tokens")),
        ]
        for option, value in option_pairs:
            text = str(value or "").strip()
            if text:
                command.extend([option, text])
        if str(payload.get("script_enable_mutation_rewrite") or "").lower() in {"1", "true", "yes", "on", "是", "启用"}:
            command.append("--enable-mutation")
        mutation_variants = str(payload.get("script_mutation_variants") or "").strip()
        if mutation_variants:
            command.extend(["--mutation-variants", mutation_variants])
        if payload.get("dry_run"):
            command.append("--dry-run")
        return command


JOB = GenerationJob()


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>脚本产出智能体</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f5f7;
      --panel: rgba(255, 255, 255, .82);
      --panel-solid: #ffffff;
      --ink: #1d1d1f;
      --muted: #6e6e73;
      --subtle: #8a8a8e;
      --line: rgba(0, 0, 0, .11);
      --line-soft: rgba(0, 0, 0, .065);
      --line-strong: rgba(0, 0, 0, .18);
      --control: rgba(255, 255, 255, .82);
      --control-hover: #ffffff;
      --blue: #007aff;
      --blue-dark: #0068d6;
      --red: #ff3b30;
      --yellow: #ffcc00;
      --green: #34c759;
      --code: #1c1c1e;
      --shadow: 0 18px 45px rgba(0, 0, 0, .08);
    }
    * { box-sizing: border-box; }
    html { height: 100%; overflow: hidden; }
    ::selection { background: rgba(0, 122, 255, .18); }
    body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      line-height: 1.5;
      letter-spacing: 0;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid rgba(0,0,0,.08);
      background: rgba(245, 245, 247, .78);
      backdrop-filter: saturate(180%) blur(18px);
      -webkit-backdrop-filter: saturate(180%) blur(18px);
    }
    .window-title { display: flex; align-items: center; min-width: 0; }
    h1 { margin: 0; font-size: 17px; font-weight: 700; letter-spacing: 0; }
    h2 { margin: 0 0 8px; font-size: 13px; font-weight: 700; color: #2c2c2e; }
    label { display: block; margin: 8px 0 4px; color: var(--muted); font-size: 11px; font-weight: 650; }
    input, select, textarea {
      width: 100%;
      min-width: 0;
      border: 1px solid rgba(0,0,0,.11);
      border-radius: 6px;
      background: var(--control);
      color: var(--ink);
      padding: 6px 9px;
      font: inherit;
      font-size: 13px;
      outline: none;
      box-shadow: 0 1px 0 rgba(255,255,255,.72) inset;
      transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    input, select { min-height: 32px; text-overflow: ellipsis; }
    textarea { resize: vertical; min-height: 120px; }
    input:hover, select:hover, textarea:hover { background: var(--control-hover); }
    input:focus, select:focus, textarea:focus {
      background: var(--panel-solid);
      border-color: rgba(0, 122, 255, .55);
      box-shadow: 0 0 0 4px rgba(0, 122, 255, .12);
    }
    input::placeholder { color: var(--subtle); }
    button {
      min-height: 32px;
      border: 1px solid rgba(0,0,0,.10);
      border-radius: 6px;
      background: rgba(255, 255, 255, .78);
      color: var(--ink);
      padding: 7px 11px;
      font-size: 12px;
      line-height: 1.2;
      font-weight: 650;
      cursor: pointer;
      white-space: nowrap;
      box-shadow: 0 1px 0 rgba(255,255,255,.76) inset, 0 1px 2px rgba(0,0,0,.045);
      transition: background .16s ease, border-color .16s ease, color .16s ease, transform .12s ease, box-shadow .16s ease;
    }
    button:hover { background: var(--panel-solid); border-color: var(--line-strong); }
    button:active { transform: scale(.98); }
    button.primary { background: var(--blue); border-color: rgba(0,99,210,.4); color: #fff; box-shadow: 0 1px 0 rgba(255,255,255,.24) inset, 0 1px 2px rgba(0,0,0,.08); }
    button.primary:hover { background: var(--blue-dark); border-color: var(--blue-dark); }
    button.warn { background: rgba(0, 122, 255, .08); border-color: rgba(0, 122, 255, .18); color: var(--blue-dark); }
    #saveBtn.primary {
      background: rgba(255,255,255,.78);
      border-color: var(--line);
      color: var(--ink);
      box-shadow: none;
    }
    #saveBtn.primary:hover { background: var(--panel-solid); border-color: var(--line-strong); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .app {
      position: relative;
      width: 100%;
      display: grid;
      grid-template-columns: 310px minmax(0, 1fr);
      gap: 12px;
      padding: 12px;
      max-width: none;
      height: calc(100vh - 58px);
      margin: 0 auto;
      overflow: hidden;
    }
    .panel {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      max-width: 100%;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 12px;
      backdrop-filter: saturate(180%) blur(20px);
      -webkit-backdrop-filter: saturate(180%) blur(20px);
      overflow: auto;
    }
    .panel > h2 {
      flex: 0 0 auto;
      min-height: 30px;
      display: flex;
      align-items: center;
      margin: -2px -12px 8px;
      padding: 0 12px 8px;
      border-bottom: 1px solid var(--line-soft);
      background: rgba(255,255,255,.32);
    }
    .panel > .bar:first-child {
      flex: 0 0 auto;
      min-height: 30px;
      margin: -2px -12px 8px;
      padding: 0 12px 8px;
      border-bottom: 1px solid var(--line-soft);
      background: rgba(255,255,255,.32);
    }
    .panel > .bar:first-child h2 { margin: 0; }
    .stack { display: grid; gap: 12px; align-content: stretch; min-width: 0; min-height: 0; }
    .app > aside.stack {
      height: 100%;
      grid-template-rows: minmax(0, 1.5fr) minmax(0, .7fr);
    }
    .app > section.stack {
      height: 100%;
      grid-template-rows: minmax(0, 1.05fr) minmax(0, .95fr);
    }
    .app > section.stack > .panel:first-child {
      overflow: auto;
    }
    aside, section, main { min-width: 0; }
    .grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
    .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .check-row {
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      margin-top: 10px;
      padding: 9px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: rgba(255,255,255,.48);
    }
    .check-row input[type="checkbox"] {
      width: 16px;
      min-height: 16px;
      height: 16px;
      margin: 2px 0 0;
      padding: 0;
      box-shadow: none;
      accent-color: var(--blue);
    }
    .check-row strong { display: block; font-size: 12px; color: var(--ink); line-height: 1.25; }
    .check-row small { display: block; color: var(--muted); font-size: 11px; line-height: 1.35; margin-top: 2px; }
    .result-grid {
      display: grid;
      grid-template-columns: minmax(260px, .8fr) minmax(360px, 1.2fr);
      gap: 12px;
      min-height: 0;
    }
    .pathline { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: end; }
    .file-picker { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; }
    .hidden-file { display: none; }
    .drop-zone {
      min-height: 96px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      padding: 10px;
      border: 1px dashed rgba(0,0,0,.22);
      border-radius: 8px;
      background: rgba(255,255,255,.55);
      color: var(--muted);
      text-align: center;
      cursor: pointer;
      user-select: none;
      transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;
    }
    .drop-zone:hover,
    .drop-zone.dragover {
      border-color: rgba(0,122,255,.55);
      background: rgba(0,122,255,.08);
      box-shadow: 0 0 0 4px rgba(0,122,255,.08);
    }
    .drop-zone.ready {
      border-style: solid;
      border-color: rgba(0,122,255,.38);
      background: rgba(0,122,255,.07);
    }
    .drop-zone strong {
      display: block;
      width: 100%;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.25;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .drop-zone span { font-size: 11px; }
    .drop-zone small {
      width: 100%;
      color: var(--subtle);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .task-panel label { margin: 6px 0 3px; }
    .task-panel .drop-zone {
      min-height: 56px;
      padding: 7px 8px;
      gap: 2px;
    }
    .task-panel .drop-zone span {
      display: none;
    }
    .selected-file {
      min-height: 56px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 8px;
      padding: 7px 8px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: rgba(255,255,255,.55);
      overflow: hidden;
    }
    .selected-file-text {
      min-width: 0;
      overflow: hidden;
    }
    .selected-file strong {
      display: block;
      width: 100%;
      max-width: 100%;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.25;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .selected-file small {
      width: 100%;
      max-width: 100%;
      color: var(--subtle);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .selected-file button {
      min-height: 28px;
      height: 28px;
      padding: 0 8px;
    }
    .mutation-row {
      align-items: end;
      margin-top: 8px;
    }
    .mutation-row .check-row {
      height: 32px;
      min-height: 32px;
      margin-top: 0;
      padding: 0 8px;
      align-items: center;
      background: #ffffff;
      border-color: rgba(0, 122, 255, .22);
    }
    .mutation-row .check-row input[type="checkbox"] {
      width: 16px;
      min-height: 16px;
      height: 16px;
      margin: 0;
    }
    .mutation-row .check-row strong {
      line-height: 1;
    }
    .mutation-row .check-row small {
      display: none;
    }
    .mutation-row label {
      margin-top: 0;
    }
    .variable-row {
      margin-top: 6px;
      align-items: end;
    }
    .variable-row label {
      margin-top: 0;
    }
    .variable-row input,
    .variable-row select {
      height: 32px;
      min-height: 32px;
    }
    .mutation-row input {
      height: 32px;
      min-height: 32px;
    }
    .mutation-source-hint {
      margin-top: 6px;
      min-height: 30px;
      padding: 6px 8px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.58);
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow: hidden;
    }
    .mutation-source-hint strong {
      color: var(--ink);
      font-size: 11px;
    }
    .mutation-source-hint .path {
      display: block;
      margin-top: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--subtle);
    }
    .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
    .chip {
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: rgba(255, 255, 255, .70);
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.65);
    }
    .chip.ok { color: #1f7a3a; border-color: rgba(52,199,89,.24); background: rgba(52,199,89,.10); }
    .chip.bad { color: #b42318; border-color: rgba(255,59,48,.24); background: rgba(255,59,48,.09); }
    .flow {
      display: grid;
      grid-template-columns: repeat(5, minmax(108px, 1fr));
      gap: 8px;
      min-height: 0;
    }
    .step {
      min-height: 56px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 9px;
      background: rgba(255, 255, 255, .62);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.72);
    }
    .step strong { display: block; font-size: 12px; margin-bottom: 4px; color: #2c2c2e; }
    .step span { color: var(--muted); font-size: 12px; }
    .script-list {
      display: grid;
      gap: 8px;
      align-content: start;
      grid-auto-rows: minmax(30px, max-content);
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding-right: 2px;
    }
    .script-card {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 8px;
      align-items: center;
      min-height: 30px;
      height: 30px;
      max-height: 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 3px 7px;
      background: rgba(255,255,255,.66);
      cursor: pointer;
      overflow: hidden;
    }
    .script-card:hover {
      border-color: rgba(0,122,255,.34);
      background: rgba(0,122,255,.06);
    }
    .script-card.selected {
      border-color: rgba(0,122,255,.55);
      background: rgba(0,122,255,.10);
      box-shadow: 0 0 0 3px rgba(0,122,255,.08);
    }
    .script-card strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      line-height: 1.2;
    }
    .script-card small {
      display: none;
      margin-top: 3px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 11px;
    }
    .script-pill {
      border: 1px solid rgba(0,122,255,.18);
      border-radius: 999px;
      padding: 2px 6px;
      color: var(--blue-dark);
      background: rgba(0,122,255,.08);
      font-size: 11px;
      font-weight: 700;
      line-height: 1.25;
    }
    .script-status {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-width: max-content;
      overflow: hidden;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      height: 20px;
      border: 1px solid var(--line);
      padding: 0 6px;
      background: #fff;
      color: var(--ink);
      font-size: 11px;
      font-weight: 780;
      line-height: 1;
      white-space: nowrap;
    }
    .status-pill.done {
      background: var(--accent);
    }
    .status-pill.todo {
      background: #fff3c7;
      color: #8b5e00;
    }
    .status-pill.mutation {
      background: var(--surface-soft);
    }
    .tabs { display: flex; gap: 4px; padding: 3px; border-radius: 6px; background: rgba(118,118,128,.10); }
    button.tab { min-height: 28px; border: 0; background: transparent; box-shadow: none; }
    button.tab:hover { background: rgba(255,255,255,.48); }
    button.tab.active { color: var(--ink); background: var(--panel-solid); box-shadow: 0 1px 2px rgba(0,0,0,.10); }
    .editor {
      flex: 1 1 auto;
      min-height: 0;
      background: rgba(255,255,255,.72);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      line-height: 1.58;
      padding: 12px;
    }
    pre {
      margin: 0;
      flex: 1 1 auto;
      min-height: 0;
      max-height: none;
      overflow: auto;
      background: var(--code);
      color: #e8edf2;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-thumb { background: rgba(0,0,0,.18); border: 3px solid transparent; border-radius: 999px; background-clip: content-box; }
    ::-webkit-scrollbar-track { background: transparent; }
    .output-list { display: grid; gap: 8px; }
    .output-root { margin: -2px 0 8px; }
    .output {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: rgba(255, 255, 255, .62);
    }
    .output small, .meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .output-actions { display: flex; gap: 6px; align-items: center; }
    /* Match the tkfastmoss agent workbench style: hard borders, warm grid background, dense controls. */
    :root {
      --bg:#f7f4ec;
      --surface:#fffdf7;
      --surface-soft:#f1eee5;
      --ink:#101010;
      --muted:#5f5b52;
      --subtle:#8b867a;
      --line:#151515;
      --line-soft:rgba(16,16,16,.16);
      --control:#ffffff;
      --control-hover:#ffffff;
      --blue:#101010;
      --blue-dark:#000000;
      --accent:#d9ff63;
      --green:#1f7a42;
      --red:#b32125;
      --code:#111111;
      --shadow:0 14px 0 rgba(16,16,16,.08);
    }
    body {
      background:
        linear-gradient(rgba(16,16,16,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(16,16,16,.035) 1px, transparent 1px),
        var(--bg) !important;
      background-size:28px 28px !important;
      color:var(--ink) !important;
    }
    header {
      height:72px !important;
      padding:0 22px !important;
      background:rgba(255,253,247,.82) !important;
      border-bottom:1px solid var(--line) !important;
      box-shadow:none !important;
      backdrop-filter:blur(14px) !important;
      -webkit-backdrop-filter:blur(14px) !important;
    }
    h1 {
      font-size:24px !important;
      font-weight:820 !important;
      line-height:1 !important;
    }
    .sub {
      color:var(--muted) !important;
      font-size:12px !important;
      margin-top:7px !important;
      text-transform:uppercase !important;
    }
    .app {
      height:calc(100vh - 72px) !important;
      padding:14px !important;
      gap:14px !important;
    }
    .panel {
      background:var(--surface) !important;
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      box-shadow:var(--shadow) !important;
      backdrop-filter:none !important;
      -webkit-backdrop-filter:none !important;
      padding:12px !important;
    }
    .panel > h2,
    .panel > .bar:first-child {
      min-height:50px !important;
      margin:-12px -12px 12px !important;
      padding:10px 12px !important;
      background:var(--surface-soft) !important;
      border-bottom:1px solid var(--line) !important;
    }
    .panel > .bar:first-child h2,
    h2 {
      font-size:12px !important;
      font-weight:820 !important;
      color:var(--ink) !important;
      text-transform:uppercase !important;
    }
    label {
      color:var(--muted) !important;
      font-size:11px !important;
      font-weight:780 !important;
      text-transform:uppercase !important;
    }
    input, select, textarea {
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      background:#fff !important;
      color:var(--ink) !important;
      box-shadow:none !important;
    }
    input:focus, select:focus, textarea:focus {
      border-color:var(--line) !important;
      box-shadow:4px 4px 0 var(--accent) !important;
    }
    .drop-zone,
    .selected-file,
    .check-row,
    .script-card,
    .output {
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      background:#fff !important;
      box-shadow:none !important;
    }
    .drop-zone:hover,
    .drop-zone.dragover,
    .drop-zone.ready,
    .script-card:hover {
      border-color:var(--line) !important;
      background:#fffef4 !important;
      box-shadow:4px 4px 0 rgba(16,16,16,.13) !important;
    }
    .script-card.selected {
      background:var(--accent) !important;
      border-color:var(--line) !important;
      box-shadow:4px 4px 0 rgba(16,16,16,.20) !important;
    }
    .chip,
    .script-pill,
    .status-pill {
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      background:var(--surface) !important;
      color:var(--ink) !important;
      box-shadow:3px 3px 0 rgba(16,16,16,.12) !important;
      font-weight:780 !important;
    }
    .chip.ok,
    .script-card.selected .script-pill {
      background:var(--accent) !important;
      color:#0b0b0b !important;
    }
    .chip.bad {
      background:#fff3c7 !important;
      color:#8b5e00 !important;
    }
    button {
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      background:#fff !important;
      color:var(--ink) !important;
      box-shadow:3px 3px 0 rgba(16,16,16,.13) !important;
      font-weight:820 !important;
    }
    button:hover {
      background:var(--accent) !important;
      box-shadow:4px 4px 0 rgba(16,16,16,.2) !important;
      transform:none !important;
    }
    button:active {
      transform:translate(2px,2px) !important;
      box-shadow:1px 1px 0 rgba(16,16,16,.2) !important;
    }
    button.primary {
      background:var(--ink) !important;
      color:#fff !important;
      box-shadow:4px 4px 0 var(--accent) !important;
    }
    button.primary:hover {
      background:#000 !important;
      color:#fff !important;
    }
    button.warn {
      color:var(--ink) !important;
      background:#fff !important;
    }
    pre {
      background:var(--code) !important;
      color:#f7f4ec !important;
      border:1px solid var(--line) !important;
      border-radius:0 !important;
      box-shadow:inset 0 0 0 1px rgba(255,255,255,.05) !important;
    }
    @media (max-width: 980px) {
      html, body { overflow: auto; height: auto; }
      .app { grid-template-columns: 1fr; height: auto; overflow: visible; }
      .app > aside.stack, .app > section.stack { height: auto; grid-template-rows: none; }
      .flow, .grid3, .result-grid { grid-template-columns: 1fr; }
      header { height: auto; padding: 14px; align-items: flex-start; gap: 10px; flex-direction: column; }
    }
    @media (max-width: 560px) {
      .app { padding: 16px 14px; }
      .grid2 { grid-template-columns: 1fr; }
      button { padding-inline: 10px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="window-title">
      <div>
        <h1>脚本产出智能体</h1>
        <div class="sub">Product MD · Hot Script · Clone / Mutation · Obsidian Output</div>
      </div>
    </div>
    <div class="bar">
      <span id="apiChip" class="chip">API Key</span>
      <button id="openPromptBtn">复刻提示词</button>
      <button id="openMutationPromptBtn">裂变提示词</button>
      <button id="openMistakeBookBtn">错题本</button>
      <span id="jobChip" class="chip">空闲</span>
    </div>
  </header>
  <main class="app">
    <aside class="stack">
      <section class="panel task-panel">
        <h2>任务输入</h2>
        <label>产品信息库</label>
        <select id="productSelect"></select>
        <input id="productDoc" type="hidden" />
        <label>当前爆款脚本</label>
        <div id="referenceDrop" class="selected-file">
          <div class="selected-file-text">
            <strong id="referenceDropTitle">未选择爆款脚本</strong>
            <small id="referenceDropPath">未选择</small>
          </div>
          <button id="openReferenceBtn" disabled>打开脚本</button>
        </div>
        <input id="referencePath" type="hidden" />
        <div class="grid2 variable-row">
          <div>
            <label>国家/地区</label>
            <select id="scriptCountry"></select>
          </div>
          <div>
            <label>目标语言</label>
            <select id="targetLanguage"></select>
          </div>
        </div>
        <div class="grid2 mutation-row">
          <div class="check-row">
            <input id="enableMutation" type="checkbox" />
            <div>
              <strong>是否裂变</strong>
              <small>只基于已复刻脚本裂变</small>
            </div>
          </div>
          <div>
            <label>裂变数量</label>
            <input id="mutationVariants" type="number" min="1" step="1" placeholder="默认 3" />
          </div>
        </div>
        <div id="mutationSourceHint" class="mutation-source-hint"></div>
        <input id="outputDir" type="hidden" />
      </section>
      <section class="panel">
        <h2>模型设置</h2>
        <label>API Key</label>
        <input id="apiKey" type="password" placeholder="留空则保留本地已保存密钥或使用环境变量" />
        <label>Base URL</label>
        <input id="baseUrl" placeholder="https://api.deepseek.com" />
        <label>模型</label>
        <input id="modelName" placeholder="deepseek-v4-pro" />
        <div class="grid2">
          <div>
            <label>超时秒数</label>
            <input id="timeout" type="number" min="1" step="1" />
          </div>
          <div>
            <label>最大输出 token</label>
            <input id="maxTokens" type="number" min="1" step="1" />
          </div>
        </div>
      </section>
    </aside>
    <section class="stack">
      <section class="panel">
        <div class="bar" style="justify-content:space-between;">
          <h2>爆款脚本列表</h2>
          <div class="bar">
            <span class="chip" id="scriptCountChip">0 个脚本</span>
            <button id="refreshScriptsBtn">扫描资料库</button>
          </div>
        </div>
        <div id="selectedScriptMeta" class="meta" style="margin-bottom:8px;">请先选择产品，再选择该产品目录下的爆款脚本。</div>
        <div id="referenceList" class="script-list"></div>
        <div class="bar" style="margin-top:10px;">
          <button class="primary" id="saveBtn">保存配置</button>
          <button class="warn" id="dryRunBtn">Dry-run</button>
          <button class="primary" id="runBtn">生成脚本</button>
          <span class="meta" id="configMeta"></span>
        </div>
      </section>
      <section class="result-grid">
        <div class="panel">
          <h2>运行日志</h2>
          <pre id="logs"></pre>
        </div>
        <div class="panel">
          <div class="bar" style="justify-content:space-between;">
            <h2>输出文件</h2>
            <div class="bar">
              <button id="refreshOutputsBtn">扫描输出目录</button>
              <button id="openOutputRootBtn">打开输出区</button>
            </div>
          </div>
          <div id="outputRoot" class="meta output-root">输出区加载中</div>
          <div id="outputs" class="output-list"></div>
        </div>
      </section>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let currentTab = 'prompt';
    let pollTimer = null;
    let outputRoot = '';
    let library = {products: [], references: [], roots: {}};
    let currentFiles = {};
    const COUNTRY_OPTIONS = [
      ['不改变原脚本', '不改变原脚本'],
      ['美国', '美国 (US)'],
      ['英国', '英国 (UK)'],
      ['爱尔兰', '爱尔兰 (IE)'],
      ['法国', '法国 (FR)'],
      ['德国', '德国 (DE)'],
      ['西班牙', '西班牙 (ES)'],
      ['意大利', '意大利 (IT)'],
      ['越南', '越南 (VN)'],
      ['菲律宾', '菲律宾 (PH)'],
      ['墨西哥', '墨西哥 (MX)'],
      ['巴西', '巴西 (BR)'],
      ['泰国', '泰国 (TH)'],
      ['马来西亚', '马来西亚 (MY)'],
      ['孟加拉国', '孟加拉国 (BD)'],
      ['印度尼西亚', '印度尼西亚 (ID)'],
      ['加拿大', '加拿大 (CA)']
    ];
    const COUNTRY_ALIASES = {
      'US': '美国', 'USA': '美国', 'UNITED STATES': '美国',
      'UK': '英国', 'GB': '英国', 'UNITED KINGDOM': '英国',
      'IE': '爱尔兰', 'IRELAND': '爱尔兰',
      'FR': '法国', 'FRANCE': '法国',
      'DE': '德国', 'GERMANY': '德国',
      'ES': '西班牙', 'SPAIN': '西班牙',
      'IT': '意大利', 'ITALY': '意大利',
      'VN': '越南', 'VIETNAM': '越南',
      'PH': '菲律宾', 'PHILIPPINES': '菲律宾',
      'MX': '墨西哥', 'MEXICO': '墨西哥',
      'BR': '巴西', 'BRAZIL': '巴西',
      'TH': '泰国', 'THAILAND': '泰国',
      'MY': '马来西亚', 'MALAYSIA': '马来西亚',
      'BD': '孟加拉国', 'BANGLADESH': '孟加拉国',
      'ID': '印度尼西亚', 'INDONESIA': '印度尼西亚', '印尼': '印度尼西亚',
      'CA': '加拿大', 'CANADA': '加拿大'
    };
    const COUNTRY_CODES = {
      '美国': 'US',
      '英国': 'UK',
      '爱尔兰': 'IE',
      '法国': 'FR',
      '德国': 'DE',
      '西班牙': 'ES',
      '意大利': 'IT',
      '越南': 'VN',
      '菲律宾': 'PH',
      '墨西哥': 'MX',
      '巴西': 'BR',
      '泰国': 'TH',
      '马来西亚': 'MY',
      '孟加拉国': 'BD',
      '印度尼西亚': 'ID',
      '加拿大': 'CA'
    };
    const LANGUAGE_OPTIONS = [
      ['不改变原脚本', '不改变原脚本'],
      ['英语', '英语'],
      ['法语', '法语'],
      ['德语', '德语'],
      ['西班牙语', '西班牙语'],
      ['意大利语', '意大利语'],
      ['葡萄牙语', '葡萄牙语'],
      ['越南语', '越南语'],
      ['菲律宾语', '菲律宾语'],
      ['泰语', '泰语'],
      ['马来语', '马来语'],
      ['孟加拉语', '孟加拉语'],
      ['印尼语', '印尼语']
    ];
    const LANGUAGE_ALIASES = {
      'EN': '英语', 'ENGLISH': '英语',
      'FR': '法语', 'FRENCH': '法语', 'FRANCAIS': '法语', 'FRANÇAIS': '法语',
      'DE': '德语', 'GERMAN': '德语',
      'ES': '西班牙语', 'SPANISH': '西班牙语',
      'IT': '意大利语', 'ITALIAN': '意大利语',
      'PT': '葡萄牙语', 'PORTUGUESE': '葡萄牙语',
      'VI': '越南语', 'VIETNAMESE': '越南语',
      'FIL': '菲律宾语', 'TL': '菲律宾语', 'FILIPINO': '菲律宾语', 'TAGALOG': '菲律宾语',
      'TH': '泰语', 'THAI': '泰语',
      'MY': '马来语', 'MS': '马来语', 'MALAY': '马来语', 'BAHASA': '马来语', 'BAHASA MALAYSIA': '马来语',
      'BD': '孟加拉语', 'BN': '孟加拉语', 'BENGALI': '孟加拉语', 'BANGLA': '孟加拉语',
      'ID': '印尼语', 'INDONESIAN': '印尼语', 'BAHASA INDONESIA': '印尼语'
    };

    async function api(path, opts = {}) {
      const headers = {'Content-Type': 'application/json', ...(opts.headers || {})};
      const res = await fetch(path, {...opts, headers});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '请求失败');
      return data;
    }

    function fileLabel(path) {
      const value = String(path || '').trim();
      return value ? value.split('/').filter(Boolean).pop() || value : '未选择';
    }

    function isTruthy(value) {
      return ['1', 'true', 'yes', 'y', 'on', '启用', '是'].includes(String(value || '').trim().toLowerCase());
    }

    function populateSelect(select, options) {
      select.innerHTML = '';
      for (const [value, label] of options) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      }
    }

    function normalizeOptionValue(value, aliases, options) {
      const raw = String(value || '').trim();
      if (!raw) return '不改变原脚本';
      const optionValues = new Set(options.map(item => item[0]));
      if (optionValues.has(raw)) return raw;
      const normalized = aliases[raw.toUpperCase()] || aliases[raw.toLowerCase()] || aliases[raw];
      return normalized || '不改变原脚本';
    }

    function populateFixedSelects() {
      populateSelect($('scriptCountry'), COUNTRY_OPTIONS);
      populateSelect($('targetLanguage'), LANGUAGE_OPTIONS);
    }

    function productNameFromPath(path) {
      const name = fileLabel(path).replace(/\.md$/i, '');
      return name.replace(/-产品信息$/u, '');
    }

    function outputDirForProduct(path) {
      const product = productNameFromPath(path);
      const root = (library.roots && library.roots.script_outputs) || '__SCRIPT_OUTPUT_SOURCE_ROOT__';
      return product ? `${root}/${product}` : '';
    }

    function safeName(value) {
      return String(value || '').trim().replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, '_') || 'unknown';
    }

    function referenceParts(path) {
      const stem = fileLabel(path).replace(/\.md$/i, '');
      let sourceCountry = '';
      let core = stem;
      const countryMatch = stem.match(/^([A-Za-z]{2,6})-(.+)$/);
      if (countryMatch) {
        sourceCountry = countryMatch[1].toUpperCase();
        core = countryMatch[2];
      }
      const match = core.match(/(.+?)[-_ ]*(\d{10,24})(?:[-_ ].*)?$/);
      if (match) return {sourceCountry, author: safeName(match[1].replace(/[-_ ]+$/g, '')), sourceId: match[2]};
      return {sourceCountry, author: 'unknown_user', sourceId: safeName(core)};
    }

    function selectedCountryCode(referencePath) {
      const country = $('scriptCountry').value.trim();
      if (country && country !== '不改变原脚本') return COUNTRY_CODES[country] || safeName(country).toUpperCase();
      return referenceParts(referencePath).sourceCountry;
    }

    function expectedClonePath() {
      const productDoc = $('productDoc').value.trim();
      const referencePath = $('referencePath').value.trim();
      const product = safeName(productNameFromPath(productDoc));
      const root = $('outputDir').value.trim() || outputDirForProduct(productDoc);
      if (!productDoc || !referencePath || !root) return '';
      const parts = referenceParts(referencePath);
      const country = selectedCountryCode(referencePath);
      const source = country ? `${country}-${parts.author}-${parts.sourceId}` : `${parts.author}-${parts.sourceId}`;
      return `${root}/复刻-${product}-${source}.md`;
    }

    function updateMutationSourceHint() {
      const hint = $('mutationSourceHint');
      const path = expectedClonePath();
      if (!$('enableMutation').checked) {
        hint.innerHTML = '未勾选裂变：重新复刻并覆盖当前脚本、当前国家/地区对应的原复刻稿；勾选后则基于复刻稿生成独立裂变文件。';
        return;
      }
      if (!path) {
        hint.innerHTML = '<strong>裂变母稿：</strong>请先选择产品和爆款脚本。';
        return;
      }
      hint.innerHTML = `<strong>裂变母稿：</strong>${fileLabel(path)}<span class="path">${path}</span><span class="path">如果这个文件不存在，生成时会先自动复刻该国家版本，再继续裂变。</span>`;
    }

    function renderLibrary() {
      const productSelect = $('productSelect');
      const selectedProductPath = $('productDoc').value.trim();
      productSelect.innerHTML = '<option value="">选择产品信息...</option>';
      for (const item of library.products || []) {
        const option = document.createElement('option');
        option.value = item.path || '';
        option.textContent = item.name || fileLabel(item.path);
        option.selected = !!selectedProductPath && option.value === selectedProductPath;
        productSelect.appendChild(option);
      }
      renderReferenceList();
    }

    function currentProductReferences() {
      const selectedProductPath = $('productDoc').value.trim();
      const productName = productNameFromPath(selectedProductPath);
      return (library.references || []).filter(item => {
        if (!productName) return false;
        return item.product === productName;
      });
    }

    function selectReference(path) {
      $('referencePath').value = path || '';
      updateDropState('reference', $('referencePath').value, 0);
      renderReferenceList();
      updateMutationSourceHint();
    }

    function renderReferenceList() {
      const list = $('referenceList');
      const selectedReferencePath = $('referencePath').value.trim();
      const refs = currentProductReferences();
      $('scriptCountChip').textContent = `${refs.length} 个脚本`;
      list.innerHTML = '';
      if (!refs.length) {
        list.innerHTML = '<div class="meta">当前产品名下没有匹配到爆款脚本。</div>';
        $('selectedScriptMeta').textContent = '请确认产品名和 02参考脚本 下的产品文件夹名称一致。';
        return;
      }
      $('selectedScriptMeta').textContent = selectedReferencePath
        ? `当前选择：${fileLabel(selectedReferencePath)}`
        : '点击下方脚本进行复刻或裂变。';
      for (const item of refs) {
        const row = document.createElement('div');
        row.className = 'script-card' + (item.path === selectedReferencePath ? ' selected' : '');
        row.onclick = () => selectReference(item.path);
        const info = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = item.name || fileLabel(item.path);
        const path = document.createElement('small');
        path.textContent = item.path || '';
        info.append(title, path);
        const status = item.status || {};
        const statusWrap = document.createElement('div');
        statusWrap.className = 'script-status';
        const cloneStatus = document.createElement('span');
        cloneStatus.className = 'status-pill ' + (status.cloned ? 'done' : 'todo');
        cloneStatus.textContent = status.cloned ? '已复刻' : '未复刻';
        const mutationStatus = document.createElement('span');
        mutationStatus.className = 'status-pill mutation';
        mutationStatus.textContent = `裂变 ${Number(status.mutation_count || 0)} 次`;
        statusWrap.append(cloneStatus, mutationStatus);
        const pill = document.createElement('span');
        pill.className = 'script-pill';
        pill.textContent = item.path === selectedReferencePath ? '已选' : '选择';
        row.append(info, statusWrap, pill);
        list.appendChild(row);
      }
    }

    function updateDropState(kind, path, chars) {
      const isProduct = kind === 'product_doc';
      const drop = $(isProduct ? 'productDocDrop' : 'referenceDrop');
      const title = $(isProduct ? 'productDocDropTitle' : 'referenceDropTitle');
      const sub = isProduct ? $('productDocDropSub') : null;
      const pathEl = $(isProduct ? 'productDocDropPath' : 'referenceDropPath');
      if (!drop || !title || !pathEl) return;
      const hasPath = !!String(path || '').trim();
      drop.classList.toggle('ready', hasPath);
      title.textContent = hasPath ? fileLabel(path) : (isProduct ? '选择或拖入产品信息 .md' : '未选择爆款脚本');
      if (sub) sub.textContent = hasPath && chars ? `${chars} 字符` : '点击选择，也可以直接拖入文件';
      pathEl.textContent = hasPath ? path : '未选择';
      if (!isProduct && $('openReferenceBtn')) $('openReferenceBtn').disabled = !hasPath;
    }

    function setupDropZone(dropId, fileInputId, kind) {
      const drop = $(dropId);
      const input = $(fileInputId);
      drop.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          input.click();
        }
      });
      for (const name of ['dragenter', 'dragover']) {
        drop.addEventListener(name, event => {
          event.preventDefault();
          drop.classList.add('dragover');
        });
      }
      for (const name of ['dragleave', 'drop']) {
        drop.addEventListener(name, event => {
          event.preventDefault();
          drop.classList.remove('dragover');
        });
      }
      drop.addEventListener('drop', event => {
        const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
        importMarkdownFile(file, kind);
      });
    }

    async function importMarkdownFile(file, kind) {
      if (!file) return;
      try {
        if (!file.name.toLowerCase().endsWith('.md')) {
          throw new Error('请选择 .md 格式的 Markdown 文档');
        }
        const text = await file.text();
        const data = await api('/api/import', {
          method: 'POST',
          body: JSON.stringify({kind, filename: file.name, text})
        });
        if (data.state) renderState(data.state);
        await refreshOutputs();
        const label = kind === 'product_doc' ? '产品信息文件' : '竞品参考文件';
        $('logs').textContent = `${label}已导入：${data.path}\n字符数：${data.chars}`;
      } catch (err) {
        $('logs').textContent = err.message || String(err);
      }
    }

    async function importProductDocFile(file) {
      await importMarkdownFile(file, 'product_doc');
    }

    async function importReferenceFile(file) {
      await importMarkdownFile(file, 'reference');
    }

    function payload() {
      const referencePath = $('referencePath').value.trim();
      const productDoc = $('productDoc').value.trim();
      return {
        script_product_document_path: productDoc,
        reference_mode: 'script',
        reference_path: referencePath,
        script_reference_kind: '竞品爆款脚本/拆解稿',
        script_reference_script_path: referencePath,
        script_reference_analysis_path: '',
        script_country: $('scriptCountry').value.trim() || '不改变原脚本',
        script_target_language: $('targetLanguage').value.trim() || '不改变原脚本',
        script_enable_mutation_rewrite: $('enableMutation').checked ? 'true' : '',
        script_mutation_variants: Number($('mutationVariants').value || 3),
        script_mutation_source: '复刻稿',
        script_mutation_mode: 'standard',
        output_dir: $('outputDir').value.trim() || outputDirForProduct(productDoc),
        modelmesh_api_key: $('apiKey').value.trim(),
        modelmesh_base_url: $('baseUrl').value.trim(),
        script_generation_model: $('modelName').value.trim(),
        script_generation_timeout: Number($('timeout').value || 240),
        script_generation_max_output_tokens: Number($('maxTokens').value || 32768)
      };
    }

    function setChip(el, ok, text) {
      el.className = 'chip ' + (ok ? 'ok' : 'bad');
      el.textContent = text;
    }

    function renderState(data) {
      const inputs = data.inputs || {};
      const model = data.model || {};
      library = data.library || library;
      $('productDoc').value = inputs.script_product_document_path || '';
      $('referencePath').value = inputs.script_reference_script_path || inputs.script_reference_analysis_path || '';
      $('scriptCountry').value = normalizeOptionValue(inputs.script_country, COUNTRY_ALIASES, COUNTRY_OPTIONS);
      $('targetLanguage').value = normalizeOptionValue(inputs.script_target_language, LANGUAGE_ALIASES, LANGUAGE_OPTIONS);
      $('enableMutation').checked = isTruthy(inputs.script_enable_mutation_rewrite);
      $('mutationVariants').value = inputs.script_mutation_variants || 3;
      $('outputDir').value = inputs.output_dir || outputDirForProduct($('productDoc').value);
      $('baseUrl').value = model.modelmesh_base_url || 'https://api.deepseek.com';
      $('modelName').value = model.script_generation_model || 'deepseek-v4-pro';
      $('timeout').value = model.script_generation_timeout || 240;
      $('maxTokens').value = model.script_generation_max_output_tokens || 32768;
      const files = data.files || {};
      currentFiles = files;
      setChip($('apiChip'), data.status && data.status.has_api_key, `${data.status && data.status.has_api_key ? 'API Key 已就绪' : 'API Key 未配置'} · ${(data.status && data.status.ai_settings_source) || '8888 全局设置'}`);
      updateDropState('reference', $('referencePath').value, files.reference && files.reference.exists ? files.reference.chars : 0);
      $('configMeta').textContent = (data.paths && data.paths.config_dir) || '';
      renderLibrary();
      updateMutationSourceHint();
    }

    async function loadState() {
      const data = await api('/api/config');
      renderState(data);
      await refreshJob();
      await refreshOutputs();
    }

    async function saveConfig() {
      await api('/api/config', {method: 'POST', body: JSON.stringify(payload())});
      $('apiKey').value = '';
      await loadState();
    }

    async function startRun(dryRun) {
      const body = payload();
      const referencePath = body.script_reference_script_path || body.script_reference_analysis_path;
      if (!referencePath) {
        $('logs').textContent = '请先从爆款脚本列表选择一个参考脚本，再生成或裂变。';
        return;
      }
      body.dry_run = dryRun;
      await api('/api/run', {method: 'POST', body: JSON.stringify(body)});
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1200);
      await refreshJob();
    }

    function renderJobLogs(logText) {
      const logElement = $('logs');
      const text = String(logText || '').trimEnd();
      logElement.textContent = text ? text.split('\n').reverse().join('\n') : '';
      logElement.scrollTop = 0;
    }

    async function refreshJob() {
      const job = await api('/api/job');
      renderJobLogs(job.logs);
      $('jobChip').className = 'chip ' + (job.status === 'completed' ? 'ok' : job.status === 'failed' ? 'bad' : '');
      if (job.running) {
        $('jobChip').textContent = `运行 ${job.active_count || 0}/${job.max_workers || 1} · 排队 ${job.queued_count || 0}`;
      } else {
        $('jobChip').textContent = job.status || 'idle';
      }
      $('runBtn').disabled = false;
      $('dryRunBtn').disabled = false;
      $('saveBtn').disabled = false;
      if (!job.running && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        await refreshOutputs();
      }
    }

    async function refreshOutputs(scan=false) {
      try {
        const data = await api(scan ? '/api/outputs?refresh=1' : '/api/outputs');
        outputRoot = data.root || '';
        $('outputRoot').textContent = outputRoot ? `输出区：${outputRoot}` : '输出区未确定';
        renderOutputs(data.outputs || []);
      } catch (err) {
        $('outputRoot').textContent = err.message || String(err);
      }
    }

    function renderOutputs(items) {
      $('outputs').innerHTML = '';
      if (!items.length) {
        $('outputs').innerHTML = '<div class="meta">暂无输出文件</div>';
        return;
      }
      for (const item of items) {
        const row = document.createElement('div');
        row.className = 'output';
        const label = document.createElement('div');
        const name = document.createElement('strong');
        name.textContent = item.name || '未命名文件';
        const details = document.createElement('small');
        details.textContent = `${item.kind || '文件'} · ${item.size_label || ''} · ${item.modified || ''} · ${item.path || ''}`;
        label.append(name, document.createElement('br'), details);
        const actions = document.createElement('div');
        actions.className = 'output-actions';
        const fileBtn = document.createElement('button');
        fileBtn.textContent = '打开文件';
        fileBtn.onclick = () => openLocalPath(item.path);
        const dirBtn = document.createElement('button');
        dirBtn.textContent = '打开目录';
        dirBtn.onclick = () => openLocalPath(parentPath(item.path));
        actions.append(fileBtn, dirBtn);
        row.append(label, actions);
        $('outputs').appendChild(row);
      }
    }

    function parentPath(path) {
      const parts = String(path || '').split('/');
      parts.pop();
      return parts.join('/') || '.';
    }

    async function openLocalPath(path) {
      try {
        const data = await api('/api/open', {method: 'POST', body: JSON.stringify({path})});
        $('logs').textContent = `已打开：${data.path}`;
        return data;
      } catch (err) {
        $('logs').textContent = err.message || String(err);
      }
    }

    async function openOutputRoot() {
      if (!outputRoot) {
        await refreshOutputs();
      }
      if (outputRoot) {
        await openLocalPath(outputRoot);
      }
    }

    async function openSelectedReference() {
      const path = $('referencePath').value.trim();
      if (!path) {
        $('logs').textContent = '请先选择一个爆款脚本。';
        return;
      }
      await openLocalPath(path);
    }

    async function openConfiguredFile(kind) {
      const file = currentFiles && currentFiles[kind];
      if (!file || !file.path || !file.exists) {
        $('logs').textContent = kind === 'mistake_book' ? '当前产品没有可打开的错题本。' : '当前配置文件不存在。';
        return;
      }
      await openLocalPath(file.path);
    }

    $('saveBtn').onclick = saveConfig;
    $('dryRunBtn').onclick = () => startRun(true);
    $('runBtn').onclick = () => startRun(false);
    $('refreshOutputsBtn').onclick = () => refreshOutputs(true);
    $('openOutputRootBtn').onclick = openOutputRoot;
    $('openReferenceBtn').onclick = openSelectedReference;
    $('refreshScriptsBtn').onclick = async () => renderState(await api('/api/config?refresh=1'));
    $('openPromptBtn').onclick = () => openConfiguredFile('prompt');
    $('openMutationPromptBtn').onclick = () => openConfiguredFile('mutation_prompt');
    $('openMistakeBookBtn').onclick = () => openConfiguredFile('mistake_book');
    $('productSelect').addEventListener('change', () => {
      $('productDoc').value = $('productSelect').value;
      $('outputDir').value = outputDirForProduct($('productDoc').value);
      $('referencePath').value = '';
      updateDropState('reference', '', 0);
      renderLibrary();
      updateMutationSourceHint();
    });
    $('scriptCountry').addEventListener('change', updateMutationSourceHint);
    $('enableMutation').addEventListener('change', updateMutationSourceHint);
    document.addEventListener('dragover', event => event.preventDefault());
    document.addEventListener('drop', event => event.preventDefault());
    populateFixedSelects();
    loadState().catch(err => { $('logs').textContent = err.message; });
  </script>
</body>
</html>
"""


class ScriptGenerationWebHandler(BaseHTTPRequestHandler):
    server_version = "ScriptGenerationAgentWeb/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path in {"/", "/script"}:
                text_response(self, 200, HTML_PAGE.replace("__SCRIPT_OUTPUT_SOURCE_ROOT__", SCRIPT_OUTPUT_SOURCE_ROOT.as_posix()))
            elif parsed.path == "/health":
                json_response(self, 200, {"status": "ok"})
            elif parsed.path == "/api/config":
                query = urllib.parse.parse_qs(parsed.query)
                json_response(self, 200, state_payload(query.get("refresh", [""])[0] == "1"))
            elif parsed.path == "/api/job":
                json_response(self, 200, JOB.snapshot())
            elif parsed.path == "/api/outputs":
                query = urllib.parse.parse_qs(parsed.query)
                json_response(self, 200, cached_script_outputs(query.get("refresh", [""])[0] == "1"))
            else:
                json_response(self, 404, {"error": "Not found"})
        except Exception as exc:  # noqa: BLE001
            json_response(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = read_request_json(self)
            if parsed.path == "/api/config":
                json_response(self, 200, save_state(payload))
            elif parsed.path == "/api/run":
                json_response(self, 200, JOB.start(payload))
            elif parsed.path == "/api/import":
                json_response(self, 200, import_markdown_file(payload))
            elif parsed.path == "/api/open":
                json_response(self, 200, open_local_path(str(payload.get("path") or "")))
            else:
                json_response(self, 404, {"error": "Not found"})
        except Exception as exc:  # noqa: BLE001
            json_response(self, 400, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the script generation agent web UI.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ScriptGenerationWebHandler)
    print(f"脚本生成智能体 Web UI: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
