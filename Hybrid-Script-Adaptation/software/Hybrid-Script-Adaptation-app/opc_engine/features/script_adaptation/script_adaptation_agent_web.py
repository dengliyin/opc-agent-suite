#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opc_engine.core.project_assets import (
    ensure_project_dirs,
    product_project_ready,
    product_project_root,
    require_product_project,
    source_stage_dir,
)
from opc_engine.features.script_adaptation import content_workflow_stage as workflow
from opc_engine.features.script_adaptation.script_adaptation_agent import (
    AGENT_CONFIG_DIR,
    AGENT_SECRETS_PATH,
    AGENT_SETTINGS_PATH,
    ROOT,
    ScriptAdaptationAgent,
    load_local_agent_config,
    read_json_object,
    resolve_agent_config_file,
)


class JobCancelled(RuntimeError):
    """Raised when the user requests a task stop."""


HOST = "127.0.0.1"
DEFAULT_PORT = 9999
ADAPTATION_QC_MAX_ATTEMPTS = 3
ADAPTATION_MAX_CONCURRENCY = 5
ADAPTATION_STATUS_LOG_NAME = "_adaptation_status_log.json"
ADAPTATION_STATUS_LOG_LOCK = threading.Lock()
ADAPTATION_TARGET_PROFILES = {
    "veo": {"label": "Veo", "segment_seconds": 8},
    "omni": {"label": "Omni", "segment_seconds": 10},
    "grok": {"label": "Grok", "segment_seconds": 30, "min_segment_seconds": 6, "segment_label": "6-30 秒"},
}
INVALID_ADAPTATION_STATES = {"json_missing", "contract_mismatch", "markdown_invalid"}


def normalize_target_model(value: Any) -> str:
    target = str(value or "veo").strip().lower()
    return target if target in ADAPTATION_TARGET_PROFILES else "veo"


def segment_seconds_for_target(target_model: Any, value: Any = None) -> int:
    target = normalize_target_model(target_model)
    profile = ADAPTATION_TARGET_PROFILES[target]
    default_seconds = int(profile.get("segment_seconds") or 8)
    if target != "grok":
        return default_seconds
    min_seconds = int(profile.get("min_segment_seconds") or 6)
    try:
        seconds = int(value if value not in (None, "") else default_seconds)
    except (TypeError, ValueError):
        seconds = default_seconds
    return max(min_seconds, min(default_seconds, seconds))


def configured_local_roots() -> list[Path]:
    roots = [ROOT.resolve()]
    try:
        config = load_local_agent_config()
    except Exception:
        config = {}
    for key in ("script_adaptation_input_dir", "script_adaptation_output_root"):
        value = str(config.get(key) or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        roots.append(path.resolve())
    input_roots = config.get("script_adaptation_input_dirs")
    if isinstance(input_roots, list):
        for value in input_roots:
            text = str(value or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            roots.append(path.resolve())
    output_roots = config.get("script_adaptation_output_roots")
    if isinstance(output_roots, dict):
        for value in output_roots.values():
            text = str(value or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            roots.append(path.resolve())
    return roots


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def safe_root_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    for root in configured_local_roots():
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    raise ValueError("路径不在允许的项目/脚本目录内")


def display_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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


def target_model_from_query(parsed: urllib.parse.ParseResult, fallback: str = "veo") -> str:
    query = urllib.parse.parse_qs(parsed.query)
    return normalize_target_model(query.get("target_model", [fallback])[0])


def target_prompt_path(settings: dict[str, Any], target_model: str) -> Path:
    files = settings.get("files", {}) if isinstance(settings.get("files", {}), dict) else {}
    prompt_paths = files.get("script_adaptation_prompt_paths")
    prompt_value = ""
    if isinstance(prompt_paths, dict):
        prompt_value = str(prompt_paths.get(target_model) or "").strip()
    if not prompt_value:
        prompt_value = str(files.get("script_adaptation_prompt_path") or "").strip()
    return resolve_agent_config_file(prompt_value)


def target_output_root(config: dict[str, Any], target_model: str) -> Path | None:
    scoped_config = {**config, "script_adaptation_target_model": target_model}
    return workflow.script_adaptation_output_root(scoped_config)


def target_profiles_for_client(settings: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for key, profile in ADAPTATION_TARGET_PROFILES.items():
        prompt_path = target_prompt_path(settings, key)
        output_root = target_output_root(config, key)
        profiles[key] = {
            "label": profile["label"],
            "segment_seconds": profile["segment_seconds"],
            "min_segment_seconds": profile.get("min_segment_seconds"),
            "segment_label": profile.get("segment_label") or f"{profile['segment_seconds']} 秒",
            "prompt_path": display_path(prompt_path),
            "prompt_open_path": prompt_path.as_posix(),
            "prompt_chars": len(prompt_path.read_text(encoding="utf-8", errors="ignore")) if prompt_path.exists() else 0,
            "output_root": output_root.as_posix() if output_root else "",
        }
    return profiles


def settings_for_client() -> dict[str, Any]:
    settings = read_json_object(AGENT_SETTINGS_PATH)
    config = load_local_agent_config()
    target_model = normalize_target_model(config.get("script_adaptation_target_model"))
    prompt_path = target_prompt_path(settings, target_model)
    target_profiles = target_profiles_for_client(settings, config)
    return {
        "settings": settings,
        "target_profiles": target_profiles,
        "paths": {
            "agent_config_dir": display_path(AGENT_CONFIG_DIR),
            "settings": display_path(AGENT_SETTINGS_PATH),
            "prompt": display_path(prompt_path),
        },
        "open_paths": {
            "agent_config_dir": AGENT_CONFIG_DIR.as_posix(),
            "settings": AGENT_SETTINGS_PATH.as_posix(),
            "prompt": prompt_path.as_posix(),
        },
        "file_stats": {
            "prompt_chars": len(prompt_path.read_text(encoding="utf-8", errors="ignore")) if prompt_path.exists() else 0,
        },
        "runtime": {
            "adaptation_max_concurrency": ADAPTATION_MAX_CONCURRENCY,
            "adaptation_qc_max_attempts": ADAPTATION_QC_MAX_ATTEMPTS,
        },
        "has_api_key": bool(config.get("modelmesh_api_key") or config.get("gemini_api_key") or os.environ.get("MODELMESH_API_KEY") or os.environ.get("GEMINI_API_KEY")),
    }


def script_library_roots(config: dict[str, Any] | None = None) -> list[Path]:
    config = config or load_local_agent_config()
    values = config.get("script_adaptation_input_dirs")
    if not isinstance(values, list):
        values = [config.get("script_adaptation_input_dir")]
    roots: list[Path] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        roots.append(path.resolve())
    return roots


def hybrid_script_classification(path: Path, config: dict[str, Any]) -> dict[str, str]:
    resolved = path.resolve()
    for root in script_library_roots(config):
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        product_name = relative.parts[0] if len(relative.parts) > 1 else ""
        if product_name:
            relative_parent = relative.parent
            return {
                "material_type": root.name,
                "product_name": product_name,
                "relative_dir": (Path(root.name) / relative_parent).as_posix(),
                "group_label": f"{root.name} / {product_name}",
            }
    return {
        "material_type": "",
        "product_name": "",
        "relative_dir": "",
        "group_label": "未分类",
    }


def parse_time_value(value: str) -> float | None:
    text = str(value or "").strip()
    text = re.sub(r"[秒sS]\s*$", "", text).strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return None
        if len(numbers) == 2:
            return numbers[0] * 60 + numbers[1]
        if len(numbers) == 3:
            return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_time_range_seconds(value: str) -> tuple[float, float] | None:
    text = str(value or "").strip()
    match = re.search(
        r"(?P<start>\d+(?::\d{1,2}){0,2}(?:\.\d+)?)\s*(?:-|–|—|~|至|到)\s*(?P<end>\d+(?::\d{1,2}){0,2}(?:\.\d+)?)",
        text,
    )
    if not match:
        return None
    start = parse_time_value(match.group("start"))
    end = parse_time_value(match.group("end"))
    if start is None or end is None or end < start:
        return None
    return start, end


def omni_segment_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^#\s*Segment\s+(.+?)\s*$", text or ""))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1).strip(), text[start:end]))
    return blocks


def character_reference_issues(text: str) -> list[str]:
    issues: list[str] = []
    defined: list[str] = []
    for index, (_title, body) in enumerate(omni_segment_blocks(text), start=1):
        label = f"Segment {index}"
        section_match = re.search(
            r"##\s*A\.\s*人物造型参考板提示词(?P<section>.*?)(?=^##\s*B\.|\Z)",
            body,
            re.S | re.M,
        )
        section = section_match.group("section") if section_match else ""
        if not section:
            continue
        has_full_board = bool(re.search(r"生成一张商业带货短视频用的|角色设定[：:]|人物必须为成年人", section))
        no_person = (not has_full_board) and bool(re.search(r"无人物|产品特写段落|纯产品展示|不需要生成人物造型参考板", section))
        reuse_ids: list[str] = []
        for match in re.finditer(
            r"(?:本段|该段)\s*(?:直接)?复用\s*(?P<ids>[^。；;\n]+)",
            section,
            flags=re.I,
        ):
            for role_id in re.findall(r"character_\d{2,}", match.group("ids"), flags=re.I):
                normalized = role_id.lower()
                if normalized not in reuse_ids:
                    reuse_ids.append(normalized)
        for role_id in reuse_ids:
            normalized = role_id.lower()
            if index == 1:
                issues.append(f"{label} 是首个片段，不能复用人物图 {normalized}")
            if normalized not in defined:
                issues.append(f"{label} 复用了未定义人物图 {normalized}")

        if has_full_board and reuse_ids:
            issues.append(f"{label} 同时复用旧人物图并生成新人物参考板；含新人物时必须重新生成一张全员合成人物图")

        if has_full_board:
            explicit_ids: list[str] = []
            for match in re.finditer(r"角色\s*ID\s*[：:]\s*(?P<ids>[^\n]+)", section, flags=re.I):
                for role_id in re.findall(r"character_\d{2,}", match.group("ids"), flags=re.I):
                    normalized = role_id.lower()
                    if normalized not in explicit_ids:
                        explicit_ids.append(normalized)
            for match in re.finditer(
                r"(?m)^\\s*(?:#{2,5}\\s*|\\*\\*)?(character_\\d{2,})\\b",
                section,
                flags=re.I,
            ):
                role_id = match.group(1).lower()
                if role_id not in explicit_ids:
                    explicit_ids.append(role_id)
            for match in re.finditer(
                r"(?:首次出现|本段生成|标记为|复用为)[^。\n]{0,40}?(character_\d{2,})",
                section,
                flags=re.I,
            ):
                role_id = match.group(1).lower()
                if role_id not in explicit_ids:
                    explicit_ids.append(role_id)
            if not explicit_ids:
                expected = f"character_{len(defined) + 1:02d}"
                issues.append(f"{label} 新人物造型参考板缺少角色ID，应为 {expected}")
            for role_id in explicit_ids:
                if role_id in defined:
                    continue
                expected = f"character_{len(defined) + 1:02d}"
                if role_id != expected:
                    issues.append(f"{label} 角色ID不连续：写成 {role_id}，应为 {expected}")
                defined.append(role_id)
        elif no_person and not reuse_ids:
            continue

        known = set(defined)
        for ref_id in re.findall(r"character_\d{2,}", body, flags=re.I):
            normalized = ref_id.lower()
            if normalized not in known:
                issues.append(f"{label} 引用了未定义人物图 {normalized}")
                break
    return issues


def read_optional_text(path: Path | None) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def fixed_duration_padding_issues(
    text: str,
    source_text: str,
    target_model: str,
    segment_seconds: Any = None,
) -> list[str]:
    target_model = normalize_target_model(target_model)
    if target_model not in {"omni", "veo"}:
        return []
    seconds = segment_seconds_for_target(target_model, segment_seconds)
    plan = workflow.fixed_duration_padding_plan(source_text, seconds)
    if not plan:
        return []
    marker = "[TECHNICAL_PADDING: BLACK_SILENT]"
    if plan["padding_duration"] < 0.001:
        return ["原脚本恰好填满固定时长，不应出现技术占位"] if marker in text else []
    issues: list[str] = []
    if text.count(marker) != 1:
        issues.append("最后一个片段必须且只能包含一个黑屏静音技术占位标记")

    expected_fields = {
        "原脚本总时长": plan["source_duration"],
        "本段有效内容时长": plan["last_content_duration"],
        "有效内容结束": plan["last_content_duration"],
        "技术占位开始": plan["last_content_duration"],
        "技术占位时长": plan["padding_duration"],
        "模型片段时长": plan["segment_seconds"],
    }
    for label, expected in expected_fields.items():
        match = re.search(rf"{re.escape(label)}[：:]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)", text, flags=re.I)
        if not match:
            issues.append(f"缺少技术占位字段：{label}")
            continue
        actual = float(match.group(1))
        if abs(actual - expected) > 0.01:
            issues.append(f"{label}应为 {expected:.3f}秒，当前为 {actual:.3f}秒")
    if "纯黑" not in text:
        issues.append("技术占位必须明确为纯黑画面")
    if not any(token in text for token in ("完全静音", "静音", "无音频", "无声音")):
        issues.append("技术占位必须明确为完全静音")
    return issues


def segmented_markdown_output_validation_text(
    text: str,
    source_text: str = "",
    target_model: str = "omni",
    segment_seconds: Any = None,
) -> dict[str, Any]:
    target_model = normalize_target_model(target_model)
    profile = ADAPTATION_TARGET_PROFILES.get(target_model, ADAPTATION_TARGET_PROFILES["omni"])
    label_text = str(profile.get("label") or target_model)
    max_seconds = float(segment_seconds_for_target(target_model, segment_seconds))
    min_seconds = float(profile.get("min_segment_seconds") or 0)
    content = (text or "").strip()
    if not content:
        return {"valid": False, "state": "markdown_invalid", "message": "Markdown 为空"}
    forbidden_wrappers = [
        "## 模块一：宫格分镜 JSON",
        "## 模块二：Veo 线性实操手册",
    ]
    for token in forbidden_wrappers:
        if token in content:
            return {
                "valid": False,
                "state": "markdown_invalid",
                "message": f"{label_text} 输出不应包含 Veo 模块包装",
            }
    forbidden_source_patterns = {
        "背景音乐": r"\[\s*背景音乐[^\]]*\]",
        "字幕": r"\[\s*字幕[^\]]*\]",
        "贴纸": r"\[\s*贴纸[^\]】]*(?:\]|】)",
        "特效": r"\[\s*特效[^\]]*\]",
        "中文翻译": r"中文翻译(?:对照)?",
    }
    leaked_tokens = [label for label, pattern in forbidden_source_patterns.items() if re.search(pattern, content)]
    if leaked_tokens:
        return {
            "valid": False,
            "state": "markdown_invalid",
            "message": f"{label_text} 输出包含不应进入下游的源脚本字段：{leaked_tokens}",
        }
    forbidden_overlay_patterns = {
        "产品贴纸": r"画面左下角有一个常驻|常驻的方形贴纸|展示着(?:图1)?(?:中)?(?:的)?该?产品(?:的)?渲染图",
        "购物贴纸": r"画面(?:右下角|中下方)出现.*(?:购物车|点击手势|贴纸)|购物车图标贴纸|点击手势动画贴纸|CTA贴纸",
    }
    leaked_overlays = [label for label, pattern in forbidden_overlay_patterns.items() if re.search(pattern, content)]
    if leaked_overlays:
        return {
            "valid": False,
            "state": "markdown_invalid",
            "message": f"{label_text} 输出包含贴纸式产品叠图，应删除后重试：{leaked_overlays}",
        }
    product_detail_tokens = [
        "使用产品手势参考",
        "手持该产品状产品",
        "染发梳",
        "染发棒",
        "梳状产品",
        "黑色梳状产品",
        "梳子",
        "刷头",
        "包装盒",
        "瓶身",
        "梳齿",
        "染发膏",
        "黑色膏体",
        "黑色产品",
        "产品内容物",
        "产品使用部位",
        "产品操作部位",
        "Stylo Hair Color",
        "SIMC",
    ]
    leaked_product_tokens = [token for token in product_detail_tokens if token in content]
    if leaked_product_tokens:
        return {
            "valid": False,
            "state": "markdown_invalid",
            "message": f"{label_text} 输出包含产品外观/品类描述，应只保留该产品：{leaked_product_tokens}",
        }
    full_required = [
        "AI视频生成分段提示词包",
        "## 1. 分段总览",
        "## 2. 人物设定总览",
        "## 3. 每段生成提示词",
    ]
    segments = omni_segment_blocks(content)
    has_full_structure = all(item in content for item in full_required)
    has_simple_structure = "## 每段生成提示词" in content or (target_model == "grok" and bool(segments))
    if not has_full_structure and not has_simple_structure:
        return {
            "valid": False,
            "state": "markdown_invalid",
            "message": f"缺少 {label_text} 主结构：需要完整结构或简化结构 ## 每段生成提示词",
        }
    if not segments:
        return {"valid": False, "state": "markdown_invalid", "message": "缺少 # Segment 段落"}

    issues: list[str] = []
    full_segment_sections = ["## A. 片段信息", "## B. 人物造型参考板提示词", "## C. 故事板图片提示词", "## D. 文件命名建议"]
    simple_segment_sections = (
        ["## A. 人物造型参考板提示词", "## B. 故事板图片提示词"]
        if target_model == "grok"
        else ["## A. 人物造型参考板提示词", "## B. 故事板图片提示词"]
    )
    placeholders = ["【粘贴该段对应的原始镜头脚本】", "【粘贴该段对应的过滤后镜头脚本】", "【把完整脚本粘贴在这里】"]
    source_duration = workflow.omni_source_duration_seconds(source_text)
    parsed_durations: list[float] = []
    for index, (title, body) in enumerate(segments, start=1):
        label = f"Segment {index}"
        required_sections = full_segment_sections if has_full_structure else simple_segment_sections
        for section in required_sections:
            if section not in body:
                issues.append(f"{label} 缺少 {section}")
        time_text = title
        info_time = re.search(r"(?m)^-\s*时间范围[：:]\s*(.+)$", body)
        if info_time:
            time_text = info_time.group(1).strip()
        parsed_range = parse_time_range_seconds(time_text)
        if not parsed_range:
            issues.append(f"{label} 时间范围不可解析")
        else:
            duration = parsed_range[1] - parsed_range[0]
            parsed_durations.append(duration)
            if abs(parsed_range[0]) > 0.01:
                issues.append(f"{label} 标题时间必须从 00:00.000 开始")
            if duration > max_seconds + 0.05:
                issues.append(f"{label} 时长 {duration:.1f}s 超过 {max_seconds:g}s")
            if min_seconds and source_duration and source_duration >= min_seconds and duration < min_seconds - 0.05:
                issues.append(f"{label} 时长 {duration:.1f}s 低于 {min_seconds:g}s")
        if not re.search(r"下面是(?:我的完整脚本|本段镜头脚本(?:（已过滤字段）)?)\s*[：:]", body):
            issues.append(f"{label} 故事板提示词缺少本段镜头脚本标记")
        if any(placeholder in body for placeholder in placeholders):
            issues.append(f"{label} 保留了脚本占位文本")
        if target_model == "omni" and re.search(
            r"图\s*3\s*是人物造型参考板|严格参考图\s*2\s*[、,，和及与]\s*图\s*3",
            body,
        ):
            issues.append(f"{label} 声明了多张人物参考板；Omni 每段只能使用图2这一张人物图")
    issues.extend(character_reference_issues(content))
    issues.extend(workflow.omni_embedded_script_reset_issues(content))
    if target_model == "omni":
        issues.extend(workflow.omni_segment_count_issues(content, source_text, segment_seconds_for_target(target_model, segment_seconds)))
        issues.extend(fixed_duration_padding_issues(content, source_text, target_model, segment_seconds))
    elif target_model == "grok" and source_duration and parsed_durations:
        total_duration = sum(parsed_durations)
        tolerance = max(0.1, source_duration * 0.01)
        if total_duration > source_duration + tolerance:
            issues.append(f"Grok Segment 总时长 {total_duration:.1f}s 明显超过原脚本总时长 {source_duration:.1f}s")
        if total_duration < source_duration - tolerance:
            issues.append(f"Grok Segment 总时长 {total_duration:.1f}s 明显少于原脚本总时长 {source_duration:.1f}s")
    if issues:
        return {"valid": False, "state": "markdown_invalid", "message": "；".join(issues)}
    return {"valid": True, "state": "done", "message": "已适配"}


def omni_output_validation_text(text: str, source_text: str = "") -> dict[str, Any]:
    return segmented_markdown_output_validation_text(text, source_text, "omni")


def adaptation_output_validation(
    path: Path | None,
    target_model: str = "veo",
    source_path: Path | None = None,
    segment_seconds: Any = None,
) -> dict[str, Any]:
    if not path or not path.exists() or not path.is_file():
        return {"valid": False, "state": "todo", "message": "未适配"}
    text = path.read_text(encoding="utf-8", errors="ignore")
    normalized_target = normalize_target_model(target_model)
    if normalized_target in {"omni", "grok"}:
        return segmented_markdown_output_validation_text(
            text,
            read_optional_text(source_path),
            normalized_target,
            segment_seconds,
        )
    if "未能提取可校正的宫格 JSON" in text:
        return {"valid": False, "state": "json_missing", "message": "缺 JSON"}
    image_data, image_error = workflow.extract_image_prompt_json(text)
    shots = image_data.get("shots") if isinstance(image_data, dict) else None
    if not image_data or not isinstance(shots, list) or not shots:
        return {"valid": False, "state": "json_missing", "message": image_error or "缺 JSON"}

    issues = adaptation_contract_issues(text, image_data)
    issues.extend(fixed_duration_padding_issues(text, read_optional_text(source_path), normalized_target, segment_seconds))
    if issues:
        return {"valid": False, "state": "contract_mismatch", "message": "；".join(issues)}
    return {"valid": True, "state": "done", "message": "已适配"}


def status_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def adaptation_status_label(status: str) -> str:
    return {
        "waiting": "等待",
        "running": "适配中",
        "retrying": "重试中",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已终止",
    }.get(status, status)


def is_non_retryable_model_error(message: str) -> bool:
    text = str(message or "").lower()
    fatal_tokens = [
        "insufficient balance",
        "http 402",
        '"status": 402',
        "'status': 402",
        "invalid_api_key",
        "invalid api key",
        "unauthorized",
        "permission denied",
        "http 401",
        "http 403",
        '"status": 401',
        '"status": 403',
    ]
    return any(token in text for token in fatal_tokens)


def validation_retry_feedback(message: str) -> str:
    marker = "输出质检未通过："
    if marker not in message:
        return ""
    feedback = message.split(marker, 1)[1]
    feedback = feedback.split("；失败产物已隔离:", 1)[0]
    return feedback.strip()


def read_adaptation_status_log(output_dir: Path) -> dict[str, Any]:
    log_path = output_dir / ADAPTATION_STATUS_LOG_NAME
    if not log_path.exists():
        return {"version": 1, "updated_at": "", "files": {}}
    try:
        raw_text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"version": 1, "updated_at": "", "files": {}}
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            data, _ = json.JSONDecoder().raw_decode(raw_text.lstrip())
        except json.JSONDecodeError:
            return {"version": 1, "updated_at": "", "files": {}}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": "", "files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        data["files"] = {}
    data.setdefault("version", 1)
    data.setdefault("updated_at", "")
    return data


def write_adaptation_status(output_dir: Path, output_filename: str, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with ADAPTATION_STATUS_LOG_LOCK:
        log = read_adaptation_status_log(output_dir)
        files = log.setdefault("files", {})
        now = status_timestamp()
        previous = files.get(output_filename) if isinstance(files, dict) else {}
        if not isinstance(previous, dict):
            previous = {}
        status = str(record.get("status") or previous.get("status") or "")
        merged = {
            **previous,
            **record,
            "status": status,
            "status_label": adaptation_status_label(status),
            "updated_at": now,
        }
        if status == "completed":
            merged["completed_at"] = now
            merged.pop("failed_at", None)
            merged.pop("quarantine_path", None)
        if status == "failed":
            merged["failed_at"] = now
            merged.pop("completed_at", None)
            merged.pop("cancelled_at", None)
        if status == "cancelled":
            merged["cancelled_at"] = now
            merged.pop("completed_at", None)
            merged.pop("failed_at", None)
        if status in {"running", "retrying"}:
            merged.pop("completed_at", None)
            merged.pop("failed_at", None)
            merged.pop("cancelled_at", None)
            merged.pop("quarantine_path", None)
        files[output_filename] = merged
        log["updated_at"] = now
        tmp_path = output_dir / f".{ADAPTATION_STATUS_LOG_NAME}.tmp"
        tmp_path.write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(output_dir / ADAPTATION_STATUS_LOG_NAME)


def quarantine_failed_output(path: Path, attempt: int, message: str) -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    quarantine_dir = path.parent / "_质检失败"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = quarantine_dir / f"{path.stem}__attempt-{attempt}.md.txt"
    if target.exists():
        target = quarantine_dir / f"{path.stem}__attempt-{attempt}-{int(time.time())}.md.txt"
    content = path.read_text(encoding="utf-8", errors="ignore")
    header = (
        "# 质检失败隔离\n\n"
        f"- 原文件: {path.name}\n"
        f"- 尝试次数: {attempt}/{ADAPTATION_QC_MAX_ATTEMPTS}\n"
        f"- 失败原因: {message}\n\n"
        "---\n\n"
    )
    target.write_text(header + content, encoding="utf-8")
    path.unlink()
    return target


def positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    numbers: list[int] = []
    for item in value:
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    return numbers


def duplicate_numbers(values: list[int]) -> list[int]:
    seen: set[int] = set()
    duplicated: set[int] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    return sorted(duplicated)


def content_after_module_two(content: str) -> str:
    match = re.search(r"^##\s*模块二.*$", content, re.M)
    if not match:
        match = re.search(r"^#{2,4}\s*.*Veo\s*实操指导书.*$", content, re.M | re.I)
    if not match:
        return content
    tail = content[match.end() :]
    end_match = re.search(r"^##\s*本次模型调用上下文.*$", tail, re.M)
    if end_match:
        tail = tail[: end_match.start()]
    return tail


def vomd_segment_matches(content: str) -> list[re.Match[str]]:
    module_two = content_after_module_two(content)
    pattern = re.compile(
        r"\*\*【片段\s*(?P<num>\d+)[：:].*?】\*\*\s*(?:→|->)\s*分镜\s*(?P<shot>\d+)",
        re.S,
    )
    return list(pattern.finditer(module_two))


def adaptation_contract_issues(content: str, image_data: dict[str, Any]) -> list[str]:
    meta = image_data.get("meta") if isinstance(image_data.get("meta"), dict) else {}
    export_rules = image_data.get("export_rules") if isinstance(image_data.get("export_rules"), dict) else {}
    shots = image_data.get("shots") if isinstance(image_data.get("shots"), list) else []
    shot_count = len(shots)
    grid_layout = str(image_data.get("grid_layout") or image_data.get("gridLayout") or "").strip().lower()
    expected_layout = str(workflow.expected_grid_layout(shot_count)).strip().lower()
    valid_shots = positive_int(meta.get("valid_shots") or meta.get("validShots"))
    expected_export_count = positive_int(
        export_rules.get("expected_export_count")
        or image_data.get("expected_export_count")
        or image_data.get("real_shot_count")
        or image_data.get("shot_count")
    )
    crop_order = int_list(meta.get("crop_order") or meta.get("cropOrder"))
    module_two_matches = vomd_segment_matches(content)
    module_two_count = len(module_two_matches)
    module_two_segment_numbers = [int(match.group("num")) for match in module_two_matches]
    module_two_shot_numbers = [int(match.group("shot")) for match in module_two_matches]
    contract_count = valid_shots or expected_export_count or shot_count
    issues: list[str] = []

    if grid_layout and expected_layout and grid_layout != expected_layout:
        issues.append(f"grid_layout={grid_layout}，按 {shot_count} 个分镜应为 {expected_layout}")
    if valid_shots is not None and valid_shots != shot_count:
        issues.append(f"meta.valid_shots={valid_shots}，shots={shot_count}")
    if expected_export_count is not None and expected_export_count != shot_count:
        issues.append(f"expected_export_count={expected_export_count}，shots={shot_count}")
    if crop_order and len(crop_order) != shot_count:
        issues.append(f"crop_order={len(crop_order)}，shots={shot_count}")
    if crop_order and len(set(crop_order)) != len(crop_order):
        issues.append("crop_order 有重复")
    if module_two_count != contract_count:
        issues.append(f"模块一 {contract_count} 个分镜，VOMD 可识别模块二 {module_two_count} 条")
    if module_two_count and contract_count:
        expected_numbers = list(range(1, contract_count + 1))
        duplicated_shots = duplicate_numbers(module_two_shot_numbers)
        if duplicated_shots:
            issues.append(f"模块二存在重复分镜ID：{[f'分镜{value:02d}' for value in duplicated_shots]}")
        if module_two_segment_numbers != expected_numbers:
            issues.append(
                "模块二片段编号不连续："
                f"{[f'片段{value:02d}' for value in module_two_segment_numbers]}，应为 {[f'片段{value:02d}' for value in expected_numbers]}"
            )
        if sorted(module_two_shot_numbers) != expected_numbers:
            missing = [value for value in expected_numbers if value not in module_two_shot_numbers]
            extra = [value for value in module_two_shot_numbers if value not in expected_numbers]
            details = []
            if missing:
                details.append(f"缺少 {[f'分镜{value:02d}' for value in missing]}")
            if extra:
                details.append(f"多出 {[f'分镜{value:02d}' for value in extra]}")
            issues.append("模块二分镜ID未唯一覆盖模块一：" + "，".join(details))
        mismatches = [
            f"片段{segment:02d}->分镜{shot:02d}"
            for segment, shot in zip(module_two_segment_numbers, module_two_shot_numbers)
            if segment != shot
        ]
        if mismatches:
            issues.append(f"模块二片段与分镜未一一对应：{mismatches[:6]}")
    return issues


def script_file_payload(
    path: Path,
    root: Path,
    config: dict[str, Any],
    status_logs: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stat = path.stat()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    parsed_name = workflow.parse_script_filename(path.name)
    target_model = normalize_target_model(config.get("script_adaptation_target_model"))
    output_root = workflow.script_adaptation_output_root(config)
    classification = hybrid_script_classification(path, config)
    product_folder = classification["product_name"] or workflow.product_folder_from_script(config, path)
    output_stem = adaptation_output_stem(config, path.name, target_model)
    output_path = (
        output_root / classification["relative_dir"] / f"{output_stem}.md"
        if output_root and classification["relative_dir"]
        else output_root / product_folder / f"{output_stem}.md"
        if output_root
        else None
    )
    output_validation = adaptation_output_validation(
        output_path,
        target_model,
        path,
        config.get("script_adaptation_segment_seconds"),
    )
    status_log = None
    if output_path and status_logs is not None:
        output_dir = output_path.parent
        if output_dir not in status_logs:
            status_logs[output_dir] = read_adaptation_status_log(output_dir)
        status_log = status_logs[output_dir]
    status_record = adaptation_status_record_for_script(
        output_path,
        path.name,
        path.as_posix(),
        status_log=status_log,
    )
    batch_meta = script_batch_metadata(path, product_folder, status_record, stat.st_mtime)
    adapted = bool(output_validation["valid"])
    return {
        "name": path.name,
        "path": path.as_posix(),
        "relative_path": relative,
        "product": product_folder,
        **classification,
        "adaptation_type": parsed_name.get("adaptation_type", ""),
        "country": parsed_name.get("country", ""),
        "username": parsed_name.get("username", ""),
        "video_id": parsed_name.get("video_id", ""),
        "variant_index": parsed_name.get("variant_index", ""),
        "has_country_format": bool(parsed_name.get("has_country_format")),
        "adapted": adapted,
        "adaptation_state": output_validation["state"],
        "adaptation_message": output_validation["message"],
        "adapted_output_path": output_path.as_posix() if output_path and adapted else "",
        "expected_output_name": f"{output_stem}.md",
        "batch_id": batch_meta["batch_id"],
        "batch_label": batch_meta["batch_label"],
        "batch_source": batch_meta["batch_source"],
        "source_script": batch_meta["source_script"],
        "created_at": batch_meta["created_at"],
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "size_label": format_file_size(stat.st_size),
    }


def adaptation_status_record_for_script(
    output_path: Path | None,
    source_filename: str,
    source_path: str,
    status_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not output_path:
        return {}
    log = status_log if status_log is not None else read_adaptation_status_log(output_path.parent)
    files = log.get("files") if isinstance(log.get("files"), dict) else {}
    candidates = [
        output_path.name,
        source_filename,
        Path(source_filename).name,
        source_path,
    ]
    for key in candidates:
        record = files.get(key) if isinstance(files, dict) else None
        if isinstance(record, dict):
            return record
    for record in files.values() if isinstance(files, dict) else []:
        if not isinstance(record, dict):
            continue
        if source_filename and source_filename in {
            str(record.get("md_file") or ""),
            str(record.get("source_filename") or ""),
            Path(str(record.get("source_path") or "")).name,
        }:
            return record
        if source_path and source_path == str(record.get("source_path") or ""):
            return record
    return {}


def base_source_script_name(filename: str) -> str:
    path = Path(filename)
    stem = re.sub(r"_\d{3,}$", "", path.stem)
    return f"{stem}{path.suffix or '.md'}"


def source_batch_identity(filename: str) -> str:
    parsed_name = workflow.parse_script_filename(Path(filename).name)
    country = str(parsed_name.get("country") or "").strip()
    username = str(parsed_name.get("username") or "").strip()
    video_id = str(parsed_name.get("video_id") or "").strip()
    if video_id:
        parts = [part for part in (country, username, video_id) if part]
        return workflow.safe_name("-".join(parts))
    return workflow.safe_name(Path(base_source_script_name(filename)).stem or Path(filename).stem or "source")


def batch_source_key_for_scripts(scripts: list[dict[str, str]]) -> str:
    source_keys: set[str] = set()
    for script in scripts:
        source_name = Path(str(script.get("source_path") or script.get("filename") or "")).name
        if source_name:
            source_keys.add(source_batch_identity(source_name))
    if len(source_keys) == 1:
        return next(iter(source_keys))
    return "mixedsource" if source_keys else "source"


def compact_batch_label(batch_id: str, source_script: str, created_at: str) -> str:
    if batch_id and not batch_id.startswith("tmp-"):
        return batch_id
    source_stem = Path(source_script).stem if source_script else "未命名母脚本"
    time_text = created_at[:16] if created_at else "未知时间"
    return f"{source_stem} · {time_text}"


def script_batch_metadata(path: Path, product_name: str, status_record: dict[str, Any], mtime: float) -> dict[str, str]:
    explicit_batch_id = next(
        (
            str(status_record.get(key) or "").strip()
            for key in ("adaptation_batch_key", "batch_id", "run_id")
            if str(status_record.get(key) or "").strip()
        ),
        "",
    )
    source_script = str(status_record.get("source_script") or status_record.get("source_filename") or "").strip()
    if not source_script:
        source_script = base_source_script_name(path.name)
    created_at = str(
        status_record.get("created_at")
        or status_record.get("completed_at")
        or status_record.get("updated_at")
        or ""
    ).strip()
    if not created_at:
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
    if explicit_batch_id:
        batch_id = explicit_batch_id
        batch_source = "explicit"
    else:
        source_script = base_source_script_name(source_script)
        date_key = re.sub(r"[^0-9]", "", created_at)[:12] or time.strftime("%Y%m%d%H%M", time.localtime(mtime))
        source_key = workflow.safe_name(Path(source_script).stem or path.stem)
        product_key = workflow.safe_name(product_name or "product")
        batch_id = f"tmp-{date_key}-{product_key}-{source_key}"
        batch_source = "fallback"
    return {
        "batch_id": batch_id,
        "batch_label": compact_batch_label(batch_id, source_script, created_at),
        "batch_source": batch_source,
        "source_script": source_script,
        "created_at": created_at,
    }


def batch_payload(batch_id: str, scripts: list[dict[str, Any]]) -> dict[str, Any]:
    scripts = sorted(scripts, key=lambda item: (str(item.get("created_at") or ""), str(item.get("name") or "")))
    adapted_count = sum(1 for script in scripts if script.get("adapted"))
    invalid_count = sum(1 for script in scripts if script.get("adaptation_state") in INVALID_ADAPTATION_STATES)
    selected_source_scripts = sorted({str(script.get("source_script") or "").strip() for script in scripts if str(script.get("source_script") or "").strip()})
    created_values = [str(script.get("created_at") or "").strip() for script in scripts if str(script.get("created_at") or "").strip()]
    label = str(scripts[0].get("batch_label") or batch_id) if scripts else batch_id
    return {
        "batch_id": batch_id,
        "batch_label": label,
        "batch_source": str(scripts[0].get("batch_source") or "") if scripts else "",
        "source_script": selected_source_scripts[0] if len(selected_source_scripts) == 1 else "多个母脚本",
        "created_at": min(created_values) if created_values else "",
        "count": len(scripts),
        "adapted_count": adapted_count,
        "invalid_count": invalid_count,
        "unused_count": len(scripts) - adapted_count,
        "scripts": scripts,
    }


def product_script_payload(
    product_name: str,
    product_path: Path,
    files: list[Path],
    root: Path,
    config: dict[str, Any],
    material_type: str = "",
) -> dict[str, Any]:
    status_logs: dict[Path, dict[str, Any]] = {}
    scripts = [script_file_payload(path, root, config, status_logs) for path in files]
    adapted_count = sum(1 for script in scripts if script.get("adapted"))
    invalid_count = sum(1 for script in scripts if script.get("adaptation_state") in INVALID_ADAPTATION_STATES)
    countries = sorted({str(script.get("country") or "").strip() for script in scripts if str(script.get("country") or "").strip()})
    grouped_batches: dict[str, list[dict[str, Any]]] = {}
    for script in scripts:
        grouped_batches.setdefault(str(script.get("batch_id") or "未分批"), []).append(script)
    batches = sorted(
        (batch_payload(batch_id, batch_scripts) for batch_id, batch_scripts in grouped_batches.items()),
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("batch_label") or "")),
        reverse=True,
    )
    total_count = len(scripts)
    return {
        "name": product_name,
        "material_type": material_type,
        "product_name": product_path.name,
        "path": product_path.as_posix(),
        "countries": countries,
        "count": total_count,
        "adapted_count": adapted_count,
        "invalid_count": invalid_count,
        "unused_count": total_count - adapted_count,
        "batches": batches,
        "scripts": scripts,
    }


def list_product_scripts(target_model: str | None = None) -> dict[str, Any]:
    config = load_local_agent_config()
    if target_model:
        config["script_adaptation_target_model"] = normalize_target_model(target_model)
        config["script_adaptation_segment_seconds"] = segment_seconds_for_target(
            config["script_adaptation_target_model"],
            config.get("script_adaptation_segment_seconds"),
        )
    roots = script_library_roots(config)
    available_roots = [root for root in roots if root.exists() and root.is_dir()]
    if not available_roots:
        return {
            "root": "\n".join(root.as_posix() for root in roots),
            "roots": [root.as_posix() for root in roots],
            "total_count": 0,
            "products": [],
        }

    products: list[dict[str, Any]] = []
    for root in available_roots:
        for product_dir in sorted(root.iterdir(), key=lambda item: item.name):
            if not product_dir.is_dir():
                continue
            files = sorted(product_dir.rglob("*.md"), key=lambda item: item.relative_to(product_dir).as_posix())
            files = [path for path in files if path.is_file()]
            if files:
                group_label = f"{root.name} / {product_dir.name}"
                products.append(
                    product_script_payload(
                        group_label,
                        product_dir,
                        files,
                        root,
                        config,
                        material_type=root.name,
                    )
                )

    total_count = sum(product["count"] for product in products)
    adapted_count = sum(product.get("adapted_count", 0) for product in products)
    invalid_count = sum(product.get("invalid_count", 0) for product in products)
    return {
        "root": "\n".join(root.as_posix() for root in roots),
        "roots": [root.as_posix() for root in roots],
        "target_model": normalize_target_model(config.get("script_adaptation_target_model")),
        "total_count": total_count,
        "adapted_count": adapted_count,
        "invalid_count": invalid_count,
        "unused_count": total_count - adapted_count,
        "products": products,
    }


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = read_json_object(AGENT_SETTINGS_PATH)
    model = settings.setdefault("model", {})
    adaptation = settings.setdefault("adaptation", {})

    for key in ("modelmesh_base_url", "video_analysis_model", "script_adaptation_text_model"):
        if key in payload:
            model[key] = str(payload.get(key) or "").strip()

    if "video_analysis_max_output_tokens" in payload:
        model["video_analysis_max_output_tokens"] = int(payload.get("video_analysis_max_output_tokens") or 32768)

    for key in ("script_adaptation_target_model",):
        if key in payload:
            adaptation[key] = normalize_target_model(payload.get(key))

    if "script_adaptation_segment_seconds" in payload:
        target_model = normalize_target_model(adaptation.get("script_adaptation_target_model"))
        adaptation["script_adaptation_segment_seconds"] = segment_seconds_for_target(
            target_model,
            payload.get("script_adaptation_segment_seconds"),
        )

    AGENT_SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_secrets(payload)
    return settings_for_client()


def update_secrets(payload: dict[str, Any]) -> None:
    api_key = str(payload.get("modelmesh_api_key") or "").strip()
    if not api_key:
        return

    secrets = read_json_object(AGENT_SECRETS_PATH)
    if not secrets:
        secrets = {
            "_说明": "复制为 agent_secrets.local.json 后填写本地 API Key。agent_secrets.local.json 已被 .gitignore 忽略。",
            "modelmesh_api_key": "",
            "gemini_api_key": "",
        }
    secrets["modelmesh_api_key"] = api_key
    AGENT_SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_SECRETS_PATH.write_text(json.dumps(secrets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key in (
        "script_adaptation_target_model",
        "script_adaptation_text_model",
        "modelmesh_base_url",
        "video_analysis_model",
    ):
        value = payload.get(key)
        if value is not None:
            overrides[key] = normalize_target_model(value) if key == "script_adaptation_target_model" else str(value).strip()
    if payload.get("script_adaptation_segment_seconds") not in (None, ""):
        target_model = normalize_target_model(overrides.get("script_adaptation_target_model"))
        overrides["script_adaptation_segment_seconds"] = segment_seconds_for_target(
            target_model,
            payload.get("script_adaptation_segment_seconds"),
        )
    overrides["script_adaptation_notes"] = ""
    return overrides


def validate_markdown_filename(filename: str) -> str:
    name = Path(str(filename or "").strip()).name
    if not name:
        raise RuntimeError("请先选择一个 .md 格式的脚本文档")
    if Path(name).suffix.lower() != ".md":
        raise RuntimeError("混剪参考脚本输入必须是 .md 格式的文档")
    return name


def next_daily_adaptation_sequence(config: dict[str, Any], date_text: str) -> int:
    project_root = product_project_root(config)
    pattern = re.compile(rf"^{re.escape(date_text)}_(\d{{3}})(?:_|$)")
    sequences: list[int] = []
    candidates: list[Path] = []

    hot_sources_root = project_root / "hot_sources"
    if hot_sources_root.exists():
        candidates.extend(path for path in hot_sources_root.iterdir() if path.is_dir())
        for adaptations_dir in hot_sources_root.glob("*/adaptations"):
            if adaptations_dir.is_dir():
                candidates.extend(path for path in adaptations_dir.iterdir() if path.is_file())

    report_dir = project_root / "product_level_reports" / "script_adaptations"
    if report_dir.exists():
        candidates.extend(path for path in report_dir.iterdir() if path.is_file())

    for path in candidates:
        name = path.stem if path.is_file() else path.name
        match = pattern.match(name)
        if match:
            sequences.append(int(match.group(1)))

    return (max(sequences) if sequences else 0) + 1


def adaptation_output_stem(config: dict[str, Any], script_filename: str, target_model: str) -> str:
    script_stem = workflow.safe_name(Path(script_filename).stem)
    model_stem = workflow.safe_name(target_model or "veo")
    return f"{model_stem}-{script_stem}"


def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def adaptation_output_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "适配结果 Markdown"
    if suffix == ".json":
        return "文生图 JSON"
    if suffix == ".csv":
        return "视频片段 CSV"
    return "文件"


def output_payload(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": display_path(path),
        "suffix": path.suffix.lower(),
        "kind": adaptation_output_kind(path),
        "mtime": stat.st_mtime,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "size": stat.st_size,
        "size_label": format_file_size(stat.st_size),
    }


def output_file_snapshot(output_dir: Path) -> dict[Path, tuple[float, int]]:
    return {
        path.resolve(): (path.stat().st_mtime, path.stat().st_size)
        for path in output_dir.glob("*")
        if path.is_file()
    }


def changed_output_files(before: dict[Path, tuple[float, int]], output_dir: Path) -> list[Path]:
    after = output_file_snapshot(output_dir)
    changed = [
        path
        for path, signature in after.items()
        if path not in before or before[path] != signature
    ]
    return sorted(changed, key=lambda path: path.stat().st_mtime)


def adaptation_output_roots(target_model: str | None = None) -> list[Path]:
    agent = ScriptAdaptationAgent()
    config = agent.load_stage_config("adapt")
    if target_model:
        config["script_adaptation_target_model"] = normalize_target_model(target_model)
    roots: list[Path] = []
    external_root = workflow.script_adaptation_output_root(config)
    if external_root:
        roots.append(external_root)
    if external_root and external_root.exists():
        roots.extend(path for path in sorted(external_root.iterdir()) if path.is_dir())
    if product_project_ready(config):
        project_root = product_project_root(config)
        report_dir = project_root / "product_level_reports" / "script_adaptations"
        if report_dir.exists():
            roots.append(report_dir)
        hot_sources_root = project_root / "hot_sources"
        if hot_sources_root.exists():
            for path in sorted(hot_sources_root.glob("*/adaptations")):
                if path.is_dir():
                    roots.append(path)
    return roots


def list_adaptation_outputs(target_model: str | None = None) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in adaptation_output_roots(target_model):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".csv"}:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            outputs.append(output_payload(path))
    suffix_priority = {".md": 3, ".json": 2, ".csv": 1}
    outputs.sort(
        key=lambda item: (
            int(float(item.get("mtime") or 0)),
            suffix_priority.get(str(item.get("suffix") or ""), 0),
            float(item.get("mtime") or 0),
        ),
        reverse=True,
    )
    roots = adaptation_output_roots(target_model)
    active_root = Path(outputs[0]["path"]).parent if outputs else (roots[0] if roots else AGENT_CONFIG_DIR)
    if outputs:
        active_root = safe_root_path(str(active_root))
    return {
        "root": display_path(active_root),
        "outputs": outputs[:120],
    }


def open_local_path(value: str) -> dict[str, str]:
    path = safe_root_path(value)
    if not path.exists():
        raise ValueError(f"文件或目录不存在: {display_path(path)}")
    subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"path": display_path(path)}


class ThreadWriter(io.TextIOBase):
    def __init__(self, job: "AgentWebJob") -> None:
        self.job = job

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if text:
            self.job.append_log(text)
        return len(text)

    def flush(self) -> None:
        return None


class ThreadLogRouter(io.TextIOBase):
    def __init__(self, fallback: io.TextIOBase) -> None:
        self.fallback = fallback
        self.lock = threading.Lock()
        self.routes: dict[int, ThreadWriter] = {}

    def writable(self) -> bool:
        return True

    def register(self, job: "AgentWebJob") -> None:
        with self.lock:
            self.routes[threading.get_ident()] = ThreadWriter(job)

    def unregister(self) -> None:
        with self.lock:
            self.routes.pop(threading.get_ident(), None)

    def write(self, text: str) -> int:
        with self.lock:
            writer = self.routes.get(threading.get_ident())
        if writer:
            return writer.write(text)
        return self.fallback.write(text)

    def flush(self) -> None:
        with self.lock:
            writer = self.routes.get(threading.get_ident())
        if writer:
            writer.flush()
            return None
        self.fallback.flush()
        return None


STDOUT_ROUTER = ThreadLogRouter(sys.stdout)
STDERR_ROUTER = ThreadLogRouter(sys.stderr)


def ensure_thread_log_router() -> None:
    if sys.stdout is not STDOUT_ROUTER:
        sys.stdout = STDOUT_ROUTER
    if sys.stderr is not STDERR_ROUTER:
        sys.stderr = STDERR_ROUTER


class AgentWebJob:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.status = "idle"
        self.started_at = 0.0
        self.finished_at = 0.0
        self.logs = ""
        self.error = ""
        self.outputs: list[dict[str, str]] = []
        self.script_path = ""
        self.progress: dict[str, Any] = {}
        self.tasks: list[dict[str, Any]] = []
        self.active_runs = 0
        self.batch_counter = 0
        self.next_task_index = 1
        self.pending_batches: list[dict[str, Any]] = []
        self.cancel_event = threading.Event()
        self.cancel_requested_at = 0.0

    def append_log(self, text: str) -> None:
        with self.lock:
            self.logs += text
            if len(self.logs) > 120000:
                self.logs = self.logs[-120000:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": self.logs,
                "error": self.error,
                "outputs": self.outputs,
                "script_path": self.script_path,
                "progress": self.progress,
                "tasks": self.tasks,
                "active_runs": self.active_runs,
                "pending_batches": [
                    {
                        "batch_id": item.get("batch_id", 0),
                        "count": len(item.get("indexed_scripts") or []),
                    }
                    for item in self.pending_batches
                ],
                "cancel_requested": self.cancel_event.is_set(),
                "cancel_requested_at": self.cancel_requested_at,
            }

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        scripts = self.expand_target_scripts(self.selected_scripts(payload), self.selected_target_models(payload))
        with self.lock:
            was_idle = self.active_runs == 0 and not self.running
            if was_idle:
                self.started_at = time.time()
                self.finished_at = 0.0
                self.logs = ""
                self.error = ""
                self.outputs = []
                self.script_path = ""
                self.progress = {}
                self.tasks = []
                self.pending_batches = []
                self.next_task_index = 1
                self.cancel_event.clear()
                self.cancel_requested_at = 0.0
            elif self.cancel_event.is_set():
                self.append_log("\n[队列] 当前任务正在终止中，未加入新任务；请等待终止完成后再重新提交。\n")
                self.recalculate_progress_locked()
                return self.snapshot()
            else:
                self.append_log("\n[任务] 当前已有适配任务正在运行，未加入新任务；请等待完成或先终止当前任务。\n")
                self.recalculate_progress_locked()
                return self.snapshot()

            original_count = len(scripts)
            scripts = self.filter_duplicate_scripts_locked(scripts)
            skipped_count = original_count - len(scripts)
            if not scripts:
                skipped_note = f"已跳过 {skipped_count} 个重复脚本；" if skipped_count else ""
                self.append_log(f"\n[队列] 未加入新任务：{skipped_note}所选脚本已在当前队列、适配中或已完成。\n")
                self.recalculate_progress_locked()
                return self.snapshot()

            self.batch_counter += 1
            batch_id = self.batch_counter
            adaptation_batch_key = self.create_adaptation_batch_key(payload, scripts, batch_id)
            for script in scripts:
                script["adaptation_batch_key"] = adaptation_batch_key
                script["batch_created_at"] = status_timestamp()
            if was_idle:
                self.active_runs = 1
                self.running = True
                self.status = "running"
            indexed_scripts = self.append_progress_tasks(scripts, batch_id)
            skipped_note = f"；跳过重复 {skipped_count} 个" if skipped_count else ""
            self.finished_at = 0.0
            self.append_log(f"\n[任务] 已创建，等待调度：共 {len(indexed_scripts)} 个任务{skipped_note}\n")

        ensure_thread_log_router()
        thread = threading.Thread(target=self._run, args=(payload, batch_id, indexed_scripts), daemon=True)
        thread.start()
        return self.snapshot()

    def create_adaptation_batch_key(self, payload: dict[str, Any], scripts: list[dict[str, str]], batch_id: int) -> str:
        explicit = str(payload.get("adaptation_batch_key") or payload.get("batch_id") or payload.get("run_id") or "").strip()
        if explicit:
            return explicit
        config = load_local_agent_config()
        product_names = sorted(
            {
                workflow.product_folder_from_script(config, script.get("source_path") or script.get("filename") or "")
                for script in scripts
            }
        )
        product_name = product_names[0] if len(product_names) == 1 else "mixed"
        timestamp_text = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        source_text = batch_source_key_for_scripts(scripts)
        target_names = sorted({normalize_target_model(script.get("target_model")) for script in scripts})
        target_text = "+".join(target_names) if target_names else "veo"
        return f"{timestamp_text}-{workflow.safe_name(product_name)}-{source_text}-{target_text}-{batch_id:03d}"

    def script_identity(self, script: dict[str, str]) -> str:
        target_model = normalize_target_model(script.get("target_model"))
        script_key = str(script.get("source_path") or script.get("filename") or "").strip()
        return f"{target_model}::{script_key}" if script_key else ""

    def active_task_keys_locked(self) -> set[str]:
        active_statuses = {"waiting", "running", "retrying", "completed"}
        keys: set[str] = set()
        for task in self.tasks:
            if task.get("status") not in active_statuses:
                continue
            key = self.script_identity(task)
            if key:
                keys.add(key)
        return keys

    def filter_duplicate_scripts_locked(self, scripts: list[dict[str, str]]) -> list[dict[str, str]]:
        active_keys = self.active_task_keys_locked()
        seen: set[str] = set()
        filtered: list[dict[str, str]] = []
        for script in scripts:
            key = self.script_identity(script)
            if key and (key in active_keys or key in seen):
                continue
            if key:
                seen.add(key)
            filtered.append(script)
        return filtered

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            if not self.running and self.active_runs <= 0:
                self.append_log("\n[终止] 当前没有正在运行的适配任务。\n")
                return self.snapshot()
            if not self.cancel_event.is_set():
                self.cancel_event.set()
                self.cancel_requested_at = time.time()
                self.status = "cancelling"
                self.append_log("\n[终止] 已收到终止请求：不再启动新脚本，不再重试；正在调用模型的脚本会在当前请求返回后停止收尾。\n")
            self.pending_batches = []
            for task in self.tasks:
                if task.get("status") == "waiting":
                    task["status"] = "cancelled"
                    task["error"] = "用户终止任务，尚未开始适配"
            self.recalculate_progress_locked()
            return self.snapshot()

    def cancel_waiting_tasks(self, batch_id: int, reason: str) -> None:
        with self.lock:
            if not self.cancel_event.is_set():
                self.cancel_event.set()
                self.cancel_requested_at = time.time()
            self.status = "cancelling"
            self.pending_batches = []
            for task in self.tasks:
                if task.get("status") == "waiting":
                    task["status"] = "cancelled"
                    task["error"] = reason
            self.recalculate_progress_locked()

    def _run(self, payload: dict[str, Any], batch_id: int, indexed_scripts: list[tuple[int, dict[str, str]]]) -> None:
        STDOUT_ROUTER.register(self)
        STDERR_ROUTER.register(self)
        try:
            self._run_inner(payload, batch_id, indexed_scripts)
        except JobCancelled as exc:
            self.append_log(f"\n[任务] 已终止：{exc}\n")
            with self.lock:
                self.status = "cancelled"
                self.error = ""
                for task in self.tasks:
                    if task.get("batch_id") == batch_id and task.get("status") in {"waiting", "running", "retrying"}:
                        task["status"] = "cancelled"
                        task["error"] = str(exc)
                self.recalculate_progress_locked()
        except BaseException as exc:  # noqa: BLE001 - show web user the exact failure.
            trace = traceback.format_exc()
            self.append_log(trace)
            with self.lock:
                self.status = "failed"
                self.error = str(exc)
                if self.tasks:
                    for task in self.tasks:
                        if task.get("batch_id") == batch_id and task.get("status") in {"waiting", "running", "retrying"}:
                            task["status"] = "failed"
                            task["error"] = str(exc)
                self.recalculate_progress_locked()
        finally:
            next_batch: dict[str, Any] | None = None
            with self.lock:
                self.active_runs = max(self.active_runs - 1, 0)
                if self.cancel_event.is_set() or self.status == "failed":
                    self.pending_batches = []
                elif self.pending_batches:
                    next_batch = self.pending_batches.pop(0)
                    self.active_runs += 1
                    self.running = True
                    self.status = "running"
                    self.finished_at = 0.0
                    self.append_log(
                        f"\n[队列] 开始执行排队任务：共 {len(next_batch.get('indexed_scripts') or [])} 个任务\n"
                    )
                    self.recalculate_progress_locked()

                if not next_batch:
                    self.running = self.active_runs > 0
                if not self.running:
                    self.finished_at = time.time()
                    if self.cancel_event.is_set():
                        self.status = "cancelled"
                    elif self.status != "failed":
                        self.status = "completed"
                    self.recalculate_progress_locked()
            STDOUT_ROUTER.unregister()
            STDERR_ROUTER.unregister()
            if next_batch:
                ensure_thread_log_router()
                thread = threading.Thread(
                    target=self._run,
                    args=(next_batch["payload"], next_batch["batch_id"], next_batch["indexed_scripts"]),
                    daemon=True,
                )
                thread.start()

    def append_progress_tasks(self, scripts: list[dict[str, str]], batch_id: int) -> list[tuple[int, dict[str, str]]]:
        with self.lock:
            indexed_scripts: list[tuple[int, dict[str, str]]] = []
            for batch_index, script in enumerate(scripts, start=1):
                task_index = self.next_task_index
                self.next_task_index += 1
                indexed_scripts.append((task_index, script))
                self.tasks.append(
                    {
                        "index": task_index,
                        "batch_id": batch_id,
                        "batch_index": batch_index,
                        "filename": script["filename"],
                        "source_path": script.get("source_path", ""),
                        "target_model": normalize_target_model(script.get("target_model")),
                        "adaptation_batch_key": script.get("adaptation_batch_key", ""),
                        "status": "waiting",
                        "attempt": 0,
                        "max_attempts": ADAPTATION_QC_MAX_ATTEMPTS,
                        "output_paths": [],
                        "error": "",
                    }
                )
            self.recalculate_progress_locked()
            return indexed_scripts

    def recalculate_progress_locked(self) -> None:
        done = sum(1 for task in self.tasks if task.get("status") == "completed")
        failed = sum(1 for task in self.tasks if task.get("status") == "failed")
        cancelled = sum(1 for task in self.tasks if task.get("status") == "cancelled")
        running_tasks = [task for task in self.tasks if task.get("status") in {"running", "retrying"}]
        running = running_tasks[0] if running_tasks else None
        total = len(self.tasks)
        self.progress = {
            "total": total,
            "done": done,
            "failed": failed,
            "cancelled": cancelled,
            "remaining": max(total - done - failed - cancelled, 0),
            "current_index": running.get("index", 0) if running else 0,
            "current_script": running.get("filename", "") if running else "",
            "current_status": running.get("status", "") if running else "",
            "current_attempt": running.get("attempt", 0) if running else 0,
            "current_max_attempts": running.get("max_attempts", ADAPTATION_QC_MAX_ATTEMPTS) if running else ADAPTATION_QC_MAX_ATTEMPTS,
            "running_count": len(running_tasks),
            "running_scripts": [
                {
                    "index": task.get("index", 0),
                    "batch_id": task.get("batch_id", 0),
                    "filename": task.get("filename", ""),
                    "target_model": task.get("target_model", ""),
                    "status": task.get("status", ""),
                    "attempt": task.get("attempt", 0),
                }
                for task in running_tasks
            ],
            "concurrency": ADAPTATION_MAX_CONCURRENCY,
            "active_runs": self.active_runs,
            "pending_batches": len(self.pending_batches),
            "queued_batches": [
                {
                    "batch_id": item.get("batch_id", 0),
                    "count": len(item.get("indexed_scripts") or []),
                }
                for item in self.pending_batches
            ],
            "cancel_requested": self.cancel_event.is_set(),
        }

    def update_task(
        self,
        index: int,
        status: str,
        *,
        output_paths: list[str] | None = None,
        error: str | None = None,
        attempt: int | None = None,
    ) -> None:
        with self.lock:
            for task in self.tasks:
                if task.get("index") != index:
                    continue
                task["status"] = status
                task["max_attempts"] = ADAPTATION_QC_MAX_ATTEMPTS
                if attempt is not None:
                    task["attempt"] = attempt
                if output_paths is not None:
                    task["output_paths"] = output_paths
                if error is not None:
                    task["error"] = error
                break
            self.recalculate_progress_locked()

    def selected_target_models(self, payload: dict[str, Any]) -> list[str]:
        raw_targets = payload.get("script_adaptation_target_models")
        targets: list[str] = []
        if isinstance(raw_targets, list):
            for raw_target in raw_targets:
                target = normalize_target_model(raw_target)
                if target not in targets:
                    targets.append(target)
        if not targets:
            targets.append(normalize_target_model(payload.get("script_adaptation_target_model")))
        return targets

    def expand_target_scripts(self, scripts: list[dict[str, str]], target_models: list[str]) -> list[dict[str, str]]:
        expanded: list[dict[str, str]] = []
        for target_model in target_models:
            for script in scripts:
                expanded.append({**script, "target_model": target_model})
        return expanded

    def selected_scripts(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        scripts: list[dict[str, str]] = []
        raw_paths = payload.get("script_paths")
        if isinstance(raw_paths, list):
            for raw_path in raw_paths:
                path = safe_root_path(str(raw_path or ""))
                if not path.exists() or not path.is_file():
                    raise RuntimeError(f"脚本文档不存在: {display_path(path)}")
                script_filename = validate_markdown_filename(path.name)
                script_text = path.read_text(encoding="utf-8", errors="ignore").strip()
                if not script_text:
                    raise RuntimeError(f"脚本文档为空: {script_filename}")
                scripts.append(
                    {
                        "text": script_text,
                        "filename": script_filename,
                        "source_path": path.as_posix(),
                    }
                )

        if scripts:
            return scripts

        script_text = str(payload.get("script_text") or "").strip()
        script_filename = validate_markdown_filename(str(payload.get("script_filename") or ""))
        if not script_text:
            raise RuntimeError("请先选择并读取一个 .md 格式的混剪参考脚本文档")
        return [
            {
                "text": script_text,
                "filename": script_filename,
                "source_path": str(payload.get("script_source_path") or script_filename),
            }
        ]

    def run_single_adaptation_attempt(
        self,
        agent: ScriptAdaptationAgent,
        payload: dict[str, Any],
        script: dict[str, str],
        index: int,
        total: int,
        attempt: int,
        retry_feedback: str = "",
    ) -> tuple[Path, list[dict[str, Any]]]:
        script_filename = script["filename"]
        config = agent.load_stage_config("adapt")
        effective_payload = dict(payload)
        script_target_model = normalize_target_model(script.get("target_model") or effective_payload.get("script_adaptation_target_model"))
        effective_payload["script_adaptation_target_model"] = script_target_model
        segment_seconds_by_model = effective_payload.get("script_adaptation_segment_seconds_by_model")
        if isinstance(segment_seconds_by_model, dict) and script_target_model in segment_seconds_by_model:
            effective_payload["script_adaptation_segment_seconds"] = segment_seconds_by_model.get(script_target_model)
        overrides = build_overrides(effective_payload)
        if retry_feedback:
            overrides["script_adaptation_notes"] = (
                "上一次输出未通过本地质检。请只修正以下问题，其他脚本内容保持不变："
                f"{retry_feedback}"
            )
        config.update(overrides)

        ensure_project_dirs(config)
        script_text = script["text"]
        target_model = normalize_target_model(config.get("script_adaptation_target_model"))
        config["script_adaptation_target_model"] = target_model
        config["script_adaptation_segment_seconds"] = segment_seconds_for_target(
            target_model,
            config.get("script_adaptation_segment_seconds"),
        )
        parsed_name = workflow.parse_script_filename(script_filename)
        source_id = adaptation_output_stem(config, script_filename, target_model)
        source_anchor = script["source_path"] or script_filename
        product_folder = workflow.product_folder_from_script(config, source_anchor)
        classification = hybrid_script_classification(Path(source_anchor), config)
        if classification["product_name"]:
            product_folder = classification["product_name"]
        script_dir = source_stage_dir(source_id, "scripts", config)
        script_path = script_dir / f"{source_id}.md"
        script_path.write_text(script_text.rstrip() + "\n", encoding="utf-8")
        overrides["script_adaptation_input_path"] = str(script_path)
        overrides["script_adaptation_output_stem"] = source_id
        overrides["script_adaptation_product_folder"] = product_folder
        if classification["relative_dir"]:
            overrides["script_adaptation_output_relative_dir"] = classification["relative_dir"]

        output_config = {**config, **overrides}
        output_dir = workflow.output_dir_for_stage("adapt", output_config, script_path)
        expected_md = output_dir / f"{source_id}.md"
        task_status = "running" if attempt == 1 else "retrying"
        base_status_record = {
            "status": task_status,
            "md_file": expected_md.name,
            "batch_id": script.get("adaptation_batch_key", ""),
            "adaptation_batch_key": script.get("adaptation_batch_key", ""),
            "run_id": script.get("adaptation_batch_key", ""),
            "source_script": script_filename,
            "created_at": script.get("batch_created_at") or status_timestamp(),
            "source_filename": script_filename,
            "source_path": script.get("source_path", ""),
            "runtime_script_path": display_path(script_path),
            "output_filename": expected_md.name,
            "output_path": expected_md.as_posix(),
            "product": product_folder,
            "adaptation_type": parsed_name.get("adaptation_type", ""),
            "country": parsed_name.get("country", ""),
            "username": parsed_name.get("username", ""),
            "video_id": parsed_name.get("video_id", ""),
            "variant_index": parsed_name.get("variant_index", ""),
            "has_country_format": bool(parsed_name.get("has_country_format")),
            "target_model": target_model,
            "attempt": attempt,
            "max_attempts": ADAPTATION_QC_MAX_ATTEMPTS,
            "message": adaptation_status_label(task_status),
        }
        write_adaptation_status(output_dir, expected_md.name, base_status_record)

        print("")
        print(f"[{index}/{total}] 第 {attempt}/{ADAPTATION_QC_MAX_ATTEMPTS} 次尝试：{script_filename}")
        print(f"[{index}/{total}] 已导入 Markdown: {script_filename}")
        print(f"[{index}/{total}] 脚本已保存: {display_path(script_path)}")
        print(f"[{index}/{total}] 输出目录: {display_path(output_dir)}")
        print(f"[{index}/{total}] 开始调用钩子与 CTA 脚本适配智能体...")
        if self.is_cancelled():
            write_adaptation_status(
                output_dir,
                expected_md.name,
                {
                    **base_status_record,
                    "status": "cancelled",
                    "message": "用户终止任务，未调用模型",
                },
            )
            raise JobCancelled("用户终止任务")
        try:
            workflow.run_adapt(output_config)
        except BaseException as exc:
            cancelled = self.is_cancelled()
            write_adaptation_status(
                output_dir,
                expected_md.name,
                {
                    **base_status_record,
                    "status": "cancelled" if cancelled else "failed",
                    "message": "用户终止任务" if cancelled else str(exc),
                },
            )
            if cancelled:
                raise JobCancelled("用户终止任务") from exc
            raise
        if self.is_cancelled():
            write_adaptation_status(
                output_dir,
                expected_md.name,
                {
                    **base_status_record,
                    "status": "cancelled",
                    "message": "用户终止任务，模型调用返回后停止收尾",
                },
            )
            raise JobCancelled("用户终止任务")
        print(f"[{index}/{total}] 钩子与 CTA 脚本适配智能体执行完成，开始质检")

        output_validation = adaptation_output_validation(
            expected_md,
            target_model,
            script_path,
            output_config.get("script_adaptation_segment_seconds"),
        )
        if not output_validation["valid"]:
            validation_message = str(output_validation["message"])
            quarantined = quarantine_failed_output(expected_md, attempt, validation_message)
            quarantine_note = f"；失败产物已隔离: {display_path(quarantined)}" if quarantined else ""
            write_adaptation_status(
                output_dir,
                expected_md.name,
                {
                    **base_status_record,
                    "status": "failed",
                    "message": f"输出质检未通过：{validation_message}",
                    "validation_state": output_validation["state"],
                    "validation_message": validation_message,
                    "quarantine_path": quarantined.as_posix() if quarantined else "",
                },
            )
            raise RuntimeError(f"输出质检未通过：{validation_message}{quarantine_note}")

        if self.is_cancelled():
            write_adaptation_status(
                output_dir,
                expected_md.name,
                {
                    **base_status_record,
                    "status": "cancelled",
                    "message": "用户终止任务，质检完成前停止收尾",
                    "validation_state": output_validation["state"],
                    "validation_message": output_validation["message"],
                },
            )
            raise JobCancelled("用户终止任务")

        write_adaptation_status(
            output_dir,
            expected_md.name,
            {
                **base_status_record,
                "status": "completed",
                "message": "输出质检通过",
                "validation_state": output_validation["state"],
                "validation_message": output_validation["message"],
            },
        )
        print(f"[{index}/{total}] 输出质检通过: {expected_md.name}")
        return script_path, [output_payload(expected_md)]

    def _run_inner(self, payload: dict[str, Any], batch_id: int, indexed_scripts: list[tuple[int, dict[str, str]]]) -> None:
        outputs: list[dict[str, Any]] = []
        script_paths: list[str] = []
        max_attempts = ADAPTATION_QC_MAX_ATTEMPTS
        task_count = len(indexed_scripts)
        if task_count <= 0:
            print("[任务] 没有可执行脚本，已跳过")
            return
        concurrency = max(1, min(ADAPTATION_MAX_CONCURRENCY, task_count))
        print(f"[任务] 开始适配：共 {task_count} 个任务；并发 {concurrency} 路；质检不通过将自动重试，最多 {max_attempts} 次")

        def run_script_with_retry(index: int, script: dict[str, str]) -> dict[str, Any]:
            STDOUT_ROUTER.register(self)
            STDERR_ROUTER.register(self)
            agent = ScriptAdaptationAgent()
            success = False
            retry_feedback = ""
            try:
                for attempt in range(1, max_attempts + 1):
                    if self.is_cancelled():
                        self.update_task(index, "cancelled", attempt=attempt - 1, error="用户终止任务")
                        return {"success": False, "cancelled": True, "outputs": [], "script_path": ""}
                    task_status = "running" if attempt == 1 else "retrying"
                    self.update_task(index, task_status, attempt=attempt, error="")
                    try:
                        script_path, changed_payloads = self.run_single_adaptation_attempt(
                            agent,
                            payload,
                            script,
                            index,
                            len(self.tasks),
                            attempt,
                            retry_feedback,
                        )
                        if self.is_cancelled():
                            self.update_task(index, "cancelled", output_paths=[], error="用户终止任务", attempt=attempt)
                            return {"success": False, "cancelled": True, "outputs": [], "script_path": ""}
                        self.update_task(
                            index,
                            "completed",
                            output_paths=[item["path"] for item in changed_payloads],
                            error="",
                            attempt=attempt,
                        )
                        success = True
                        return {
                            "success": True,
                            "script_path": display_path(script_path),
                            "outputs": changed_payloads,
                        }
                    except JobCancelled as exc:
                        message = str(exc) or "用户终止任务"
                        print(f"[任务 {index}] 已终止: {message}")
                        self.update_task(index, "cancelled", error=message, attempt=attempt)
                        return {"success": False, "cancelled": True, "error": message, "outputs": [], "script_path": ""}
                    except BaseException as exc:  # noqa: BLE001 - keep batch progress visible.
                        message = str(exc)
                        if self.is_cancelled():
                            print(f"[任务 {index}] 已终止: 用户终止任务")
                            self.update_task(index, "cancelled", error="用户终止任务", attempt=attempt)
                            return {"success": False, "cancelled": True, "error": "用户终止任务", "outputs": [], "script_path": ""}
                        print(f"[任务 {index}] 第 {attempt}/{max_attempts} 次适配失败: {message}")
                        if is_non_retryable_model_error(message):
                            reason = "模型接口返回不可重试错误，已终止剩余批量任务"
                            print(f"[任务 {index}] {reason}: {message}")
                            self.cancel_waiting_tasks(batch_id, reason)
                            self.update_task(index, "failed", error=message, attempt=attempt)
                            return {"success": False, "fatal": True, "error": message, "outputs": [], "script_path": ""}
                        if attempt < max_attempts:
                            print(f"[任务 {index}] 自动重新触发该脚本适配")
                            retry_feedback = validation_retry_feedback(message)
                            self.update_task(index, "retrying", attempt=attempt, error=message)
                            continue
                        print(f"[任务 {index}] 适配失败，已达到最大重试次数: {message}")
                        self.update_task(index, "failed", error=message, attempt=attempt)
                        return {"success": False, "error": message, "outputs": [], "script_path": ""}
                return {"success": success, "outputs": [], "script_path": ""}
            finally:
                STDOUT_ROUTER.unregister()
                STDERR_ROUTER.unregister()

        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(run_script_with_retry, index, script)
                for index, script in indexed_scripts
            ]
            for future in as_completed(futures):
                results.append(future.result())

        for result in results:
            if result.get("success"):
                outputs.extend(result.get("outputs") or [])
                if result.get("script_path"):
                    script_paths.append(str(result["script_path"]))

        failed_count = sum(1 for task in self.tasks if task.get("batch_id") == batch_id and task.get("status") == "failed")
        cancelled_count = sum(1 for task in self.tasks if task.get("batch_id") == batch_id and task.get("status") == "cancelled")
        success_count = sum(1 for task in self.tasks if task.get("batch_id") == batch_id and task.get("status") == "completed")

        print("")
        if self.is_cancelled() or cancelled_count:
            print(f"[任务] 已终止：成功适配 {success_count} 个脚本，失败 {failed_count} 个，终止 {cancelled_count} 个")
        else:
            print(f"[任务] 完成：成功适配 {success_count} 个脚本，失败 {failed_count} 个")
        with self.lock:
            existing_paths = [path for path in self.script_path.splitlines() if path]
            self.script_path = "\n".join(existing_paths + script_paths)
            self.outputs.extend(outputs)


JOB = AgentWebJob()


def inspect_payload(payload: dict[str, Any]) -> dict[str, Any]:
    agent = ScriptAdaptationAgent()
    overrides = build_overrides(payload)
    target_model = normalize_target_model(overrides.get("script_adaptation_target_model"))
    overrides["script_adaptation_prompt_path"] = str(target_prompt_path(read_json_object(AGENT_SETTINGS_PATH), target_model))
    report = agent.inspect("adapt", overrides)
    report["checks"] = [
        item for item in report.get("checks", [])
        if not str(item.get("message", "")).startswith("当前产品项目")
        and str(item.get("message", "")) != "路径未填写: script_adaptation_input_path"
    ]
    report.get("inputs", {}).pop("script_adaptation_notes", None)
    raw_paths = payload.get("script_paths")
    selected_count = len(raw_paths) if isinstance(raw_paths, list) else 0
    raw_targets = payload.get("script_adaptation_target_models")
    target_count = len(raw_targets) if isinstance(raw_targets, list) and raw_targets else 1
    script_text = str(payload.get("script_text") or "").strip()
    script_filename = str(payload.get("script_filename") or "").strip()
    report["web_script_chars"] = len(script_text)
    if selected_count:
        report["checks"].append(
            {
                "level": "ok",
                "message": "Markdown 脚本文档已选择",
                "detail": f"已勾选 {selected_count} 个脚本 × {target_count} 个目标模型，将生成 {selected_count * target_count} 个任务，最多 {ADAPTATION_MAX_CONCURRENCY} 路并发适配。",
            }
        )
    elif script_filename and Path(script_filename).suffix.lower() == ".md" and script_text:
        report["checks"].append(
            {
                "level": "ok",
                "message": "Markdown 脚本文档已导入",
                "detail": f"{script_filename} / {len(script_text)} 字符",
            }
        )
    elif script_filename and Path(script_filename).suffix.lower() != ".md":
        report["checks"].append(
            {
                "level": "error",
                "message": "脚本文档格式不正确",
                "detail": "混剪参考脚本必须是 .md 文件。",
            }
        )
    else:
        report["checks"].append(
            {
                "level": "warn",
                "message": "尚未选择 Markdown 脚本文档",
                "detail": "运行前需要选择一个 .md 格式的混剪参考脚本。",
            }
        )
    report["ready_to_run"] = not any(item["level"] == "error" for item in report["checks"])
    return report


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>钩子与 CTA 脚本适配智能体</title>
  <style>
    :root {
      color-scheme:light;
      --bg:#f7f4ec;
      --surface:#fffdf7;
      --surface-soft:#f1eee5;
      --panel:var(--surface);
      --panel-solid:var(--surface);
      --panel-raised:var(--surface-soft);
      --ink:#101010;
      --muted:#5f5b52;
      --subtle:#8b867a;
      --line:#151515;
      --line-soft:rgba(16,16,16,.16);
      --blue:#d9ff63;
      --blue-pressed:#c9f04f;
      --green:#1f7a42;
      --amber:#8b5e00;
      --red:#b32125;
      --code:#111;
      --shadow:0 14px 0 rgba(16,16,16,.08);
      --glow:4px 4px 0 var(--blue);
    }
    * { box-sizing:border-box; }
    html { height:100%; overflow:hidden; }
    body {
      margin:0;
      height:100%;
      overflow:hidden;
      background:
        linear-gradient(rgba(16,16,16,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(16,16,16,.035) 1px, transparent 1px),
        var(--bg);
      background-size:28px 28px;
      color:var(--ink);
      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Arial,"PingFang SC","Microsoft YaHei",sans-serif;
      letter-spacing:0;
      -webkit-font-smoothing:antialiased;
    }
    header {
      position:sticky;
      top:0;
      z-index:5;
      height:72px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      padding:0 22px;
      background:rgba(255,253,247,.82);
      border-bottom:1px solid var(--line);
      backdrop-filter:blur(14px);
      -webkit-backdrop-filter:blur(14px);
    }
    h1 { margin:0; font-size:24px; font-weight:820; letter-spacing:0; line-height:1; }
    .sub { color:var(--muted); font-size:12px; margin-top:7px; text-transform:uppercase; }
    .statusBar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .badge {
      border:1px solid var(--line);
      border-radius:0;
      padding:6px 10px;
      font-size:11px;
      font-weight:780;
      background:var(--surface);
      color:var(--ink);
      white-space:nowrap;
      box-shadow:3px 3px 0 rgba(16,16,16,.12);
    }
    .badge.ok { color:var(--ink); background:var(--blue); border-color:var(--line); }
    .badge.warn { color:var(--amber); background:#fff3c7; border-color:var(--line); }
    main {
      display:grid;
      grid-template-columns:300px minmax(330px, 1fr) 360px;
      gap:14px;
      padding:14px;
      height:calc(100vh - 72px);
      overflow:hidden;
    }
    section {
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:0;
      min-width:0;
      box-shadow:var(--shadow);
      position:relative;
      overflow:hidden;
      display:flex;
      flex-direction:column;
      min-height:0;
    }
    .panelHead {
      min-height:50px;
      padding:10px 12px;
      border-bottom:1px solid var(--line);
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      background:var(--surface-soft);
    }
    h2 { margin:0; font-size:12px; font-weight:820; color:var(--ink); text-transform:uppercase; }
    .panelBody {
      padding:10px;
      min-height:0;
      flex:1;
      overflow:hidden;
    }
    .configBody { overflow:auto; }
    .scriptBody {
      display:flex;
      flex-direction:column;
      gap:8px;
    }
    .resultBody {
      display:flex;
      flex-direction:column;
      gap:8px;
      overflow:hidden;
    }
    label {
      display:block;
      color:var(--muted);
      font-size:11px;
      font-weight:780;
      margin:8px 0 4px;
      text-transform:uppercase;
    }
    input, textarea, select {
      width:100%;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      color:var(--ink);
      font:inherit;
      font-size:13px;
      padding:8px 9px;
      outline:none;
      box-shadow:none;
      transition:box-shadow .15s ease, background .15s ease, transform .12s ease;
    }
    input:focus, textarea:focus, select:focus {
      background:#fff;
      box-shadow:4px 4px 0 var(--blue);
    }
    .readonlyValue {
      width:100%;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      color:var(--ink);
      font-size:13px;
      padding:7px 8px;
      min-height:32px;
      display:flex;
      align-items:center;
    }
    .segmentSecondsPicker {
      display:none;
      align-items:center;
      gap:6px;
    }
    .segmentSecondsPicker input {
      flex:1;
      min-width:0;
      text-align:center;
    }
    .segmentSecondsPicker span {
      flex:0 0 auto;
      color:var(--muted);
      font-size:12px;
    }
    .radioGroup {
      display:flex;
      gap:6px;
      align-items:center;
      flex-wrap:wrap;
      min-height:32px;
    }
    .radioOption {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:6px;
      flex:1 1 64px;
      min-width:0;
      min-height:32px;
      padding:6px 8px;
      margin:0;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      color:var(--ink);
      font-size:13px;
      font-weight:700;
      cursor:default;
    }
    .radioOption input {
      width:auto;
      margin:0;
      accent-color:var(--ink);
    }
    .scriptLibrary {
      flex:1 1 auto;
      min-height:0;
      display:flex;
      flex-direction:column;
      border:1px solid var(--line);
      border-radius:0;
      overflow:hidden;
      background:#fff;
    }
    .libraryHead {
      min-height:34px;
      padding:7px 9px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      border-bottom:1px solid var(--line);
      font-size:12px;
      font-weight:700;
      color:var(--ink);
    }
    .libraryRoot {
      color:var(--muted);
      font-size:10px;
      font-weight:500;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      max-width:62%;
    }
    .products {
      flex:1 1 auto;
      min-height:0;
      overflow:hidden;
      padding:0;
      display:flex;
      flex-direction:column;
      gap:6px;
    }
    .productPicker {
      flex:0 0 80px;
      min-height:80px;
      max-height:80px;
      display:grid;
      grid-template-columns:minmax(0, 1fr) auto;
      gap:8px;
      align-items:end;
      padding:8px 10px;
      border:1px solid var(--line);
      border-radius:0;
      background:var(--surface-soft);
    }
    .productPicker label {
      margin:0 0 4px;
    }
    .productPicker select {
      min-height:34px;
      font-weight:650;
    }
    .currentProductSelect {
      min-height:34px;
      display:inline-flex;
      align-items:center;
      gap:7px;
      padding:7px 10px;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      color:var(--ink);
      font-size:12px;
      font-weight:750;
      white-space:nowrap;
    }
    .currentProductSelect input {
      width:auto;
      margin:0;
      accent-color:var(--ink);
    }
    .productGroup {
      flex:1 1 auto;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      overflow:hidden;
      min-height:0;
      display:flex;
      flex-direction:column;
    }
    .productSummary {
      list-style:none;
      padding:8px 10px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      font-size:12px;
      font-weight:700;
      border-bottom:1px solid var(--line);
      background:var(--surface-soft);
    }
    .productMain {
      min-width:0;
      display:flex;
      align-items:center;
      gap:7px;
      overflow:hidden;
    }
    .productName {
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .productStats {
      flex:0 0 auto;
      display:flex;
      align-items:center;
      gap:5px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }
    .hideAdaptedToggle {
      flex:0 0 auto;
      display:flex;
      align-items:center;
      gap:4px;
      border:1px solid var(--line);
      background:#fff;
      padding:2px 6px;
      font-size:10px;
      font-weight:700;
      white-space:nowrap;
      cursor:pointer;
    }
    .hideAdaptedToggle.active { background:#f4ffd1; }
    .hideAdaptedToggle input {
      width:auto;
      margin:0;
      accent-color:var(--ink);
    }
    .productCount {
      flex:0 0 auto;
      color:var(--ink);
      background:var(--blue);
      border-radius:999px;
      padding:2px 7px;
      font-size:10px;
      font-weight:750;
    }
    .productCount.done { color:var(--green); background:#e9f7e7; }
    .productCount.todo { color:var(--amber); background:#fff3c7; }
    .productCount.invalid { color:var(--red); background:#ffe2df; }
    .countryBadge {
      color:var(--ink);
      background:var(--blue);
      border-radius:999px;
      padding:1px 6px;
      font-size:10px;
      font-weight:800;
      white-space:nowrap;
    }
    .scriptList {
      flex:1 1 auto;
      display:flex;
      flex-direction:column;
      gap:6px;
      padding:4px;
      overflow:auto;
      min-height:0;
    }
    .scriptItem {
      width:100%;
      text-align:left;
      border:1px solid var(--line-soft);
      background:#fff;
      box-shadow:none;
      border-radius:0;
      padding:6px 8px;
      color:var(--ink);
      display:grid;
      grid-template-columns:minmax(0, 1fr) auto;
      gap:8px;
      align-items:start;
      font-size:11px;
      font-weight:550;
      cursor:pointer;
      min-height:34px;
    }
    .scriptItem:hover { background:#fbffe8; border-color:var(--line); }
    .scriptItem.active {
      background:#f4ffd1;
      color:var(--ink);
      font-weight:750;
    }
    .scriptItem.running,
    .scriptItem.retrying {
      background:#f4ffd1;
      border-color:var(--line);
    }
    .scriptItem.completed {
      background:#eff9ec;
      border-color:var(--line-soft);
    }
    .scriptItem.failed {
      background:#ffecea;
      border-color:var(--line-soft);
    }
    .scriptItem.cancelled {
      background:#f5f2ea;
      border-color:var(--line-soft);
    }
    .scriptItem.used {
      color:var(--subtle);
    }
    .scriptItem input {
      width:auto;
      margin:0;
      accent-color:var(--ink);
    }
    .scriptItemMain {
      min-width:0;
      display:flex;
      align-items:flex-start;
      gap:6px;
    }
    .scriptName {
      overflow:visible;
      text-overflow:clip;
      white-space:normal;
      min-width:0;
      direction:ltr;
      text-align:left;
      overflow-wrap:anywhere;
      word-break:break-word;
      line-height:1.35;
    }
    .scriptMeta {
      color:var(--muted);
      font-size:10px;
      font-weight:500;
      display:flex;
      align-items:center;
      gap:4px;
      justify-content:flex-end;
      min-width:0;
      padding-top:1px;
    }
    .scriptStatus {
      border-radius:999px;
      padding:1px 6px;
      font-size:10px;
      font-weight:750;
      white-space:nowrap;
    }
    .scriptStatus.done { color:var(--green); background:#e9f7e7; }
    .scriptStatus.todo { color:var(--amber); background:#fff3c7; }
    .scriptStatus.running { color:var(--ink); background:var(--blue); }
    .scriptStatus.retrying { color:var(--ink); background:var(--blue); }
    .scriptStatus.failed { color:var(--red); background:#ffe2df; }
    .scriptStatus.cancelled { color:var(--muted); background:#efede5; }
    .scriptStatus.json_missing { color:var(--red); background:#ffe2df; }
    .scriptStatus.contract_mismatch { color:var(--red); background:#ffe2df; }
    .scriptStatus.markdown_invalid { color:var(--red); background:#ffe2df; }
    .scriptStatus.waiting { color:var(--muted); background:#efede5; }
    .selectedScriptInfo {
      flex:0 0 auto;
      border:1px solid var(--line);
      border-radius:0;
      padding:8px 10px;
      background:#fbffe8;
      display:grid;
      gap:3px;
      min-height:58px;
    }
    .selectedScriptInfo strong {
      font-size:12px;
      color:var(--ink);
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .selectedScriptInfo span {
      font-size:11px;
      color:var(--muted);
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .row2 { display:grid; grid-template-columns:1fr 110px; gap:8px; }
    .configBody .row2 { grid-template-columns:1fr; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    button {
      border:1px solid var(--line);
      background:#fff;
      color:var(--ink);
      border-radius:0;
      padding:8px 12px;
      font-weight:820;
      cursor:pointer;
      font-size:12px;
      line-height:1.2;
      white-space:nowrap;
      box-shadow:3px 3px 0 rgba(16,16,16,.13);
      transition:transform .12s ease, background .15s ease, box-shadow .15s ease;
    }
    button:hover { background:var(--blue); box-shadow:4px 4px 0 rgba(16,16,16,.2); }
    button:active { transform:translate(2px,2px); box-shadow:1px 1px 0 rgba(16,16,16,.2); }
    button.primary { background:var(--ink); color:#fff; border-color:var(--line); box-shadow:4px 4px 0 var(--blue); }
    button.primary:hover { background:#000; }
    button.blue { color:var(--ink); border-color:var(--line); background:#fff; }
    button.danger { background:#fff; color:var(--red); border-color:var(--line); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .kv {
      display:block;
      padding:5px 0;
      border-bottom:1px solid var(--line-soft);
      font-size:11px;
    }
    .kv:last-child { border-bottom:0; }
    .k { color:var(--muted); }
    .v { color:var(--ink); overflow-wrap:anywhere; }
    .checks {
      display:grid;
      grid-template-columns:1fr;
      gap:4px;
      overflow:visible;
      min-height:0;
      flex:0 0 auto;
    }
    .check {
      border:1px solid var(--line);
      border-radius:0;
      padding:8px 9px;
      font-size:11px;
      background:#fff;
      box-shadow:none;
      display:grid;
      grid-template-columns:auto minmax(0, 1fr);
      gap:5px;
      align-items:start;
    }
    .check strong {
      display:inline-flex;
      min-width:28px;
      justify-content:center;
      margin-right:0;
      padding:1px 4px;
      border-radius:0;
      font-size:10px;
      line-height:1.45;
    }
    .checkText { min-width:0; line-height:1.35; }
    .check.ok strong { color:var(--ink); background:var(--blue); }
    .check.warn strong { color:var(--amber); background:#fff3c7; }
    .check.error strong { color:var(--red); background:#ffe2df; }
    .check .detail {
      color:var(--muted);
      margin-top:1px;
      overflow-wrap:anywhere;
      display:-webkit-box;
      -webkit-line-clamp:1;
      -webkit-box-orient:vertical;
      overflow:hidden;
    }
    .progressPanel {
      flex:0 0 auto;
      border:1px solid var(--line);
      border-radius:0;
      padding:8px 10px;
      background:#fbffe8;
      display:grid;
      gap:7px;
    }
    .progressPanel.idle { display:none; }
    .progressTop {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      font-size:12px;
      font-weight:750;
      color:var(--ink);
    }
    .progressCurrent {
      color:var(--muted);
      font-size:11px;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .progressBar {
      height:7px;
      border-radius:999px;
      background:#e0ded5;
      overflow:hidden;
    }
    .progressFill {
      height:100%;
      width:0%;
      background:var(--ink);
      border-radius:999px;
      transition:width .2s ease;
    }
    .progressTasks {
      display:grid;
      gap:3px;
      max-height:92px;
      overflow:auto;
    }
    .progressTask {
      display:grid;
      grid-template-columns:72px minmax(0, 1fr);
      gap:6px;
      align-items:center;
      font-size:11px;
      color:var(--muted);
    }
    .progressTask strong {
      font-size:10px;
      border-radius:999px;
      padding:1px 5px;
      text-align:center;
      background:#efede5;
      color:var(--muted);
      white-space:nowrap;
    }
    .progressTask.running strong { color:var(--ink); background:var(--blue); }
    .progressTask.retrying strong { color:var(--ink); background:var(--blue); }
    .progressTask.completed strong { color:var(--green); background:#e9f7e7; }
    .progressTask.failed strong { color:var(--red); background:#ffe2df; }
    .progressTask.cancelled strong { color:var(--muted); background:#efede5; }
    .progressTask span {
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    pre {
      margin:0;
      white-space:pre-wrap;
      word-break:break-word;
      background:var(--code);
      color:#f7f4ec;
      border:1px solid var(--line);
      padding:12px;
      border-radius:0;
      min-height:0;
      max-height:none;
      overflow:auto;
      font-size:11px;
      line-height:1.5;
      box-shadow:inset 0 0 0 1px rgba(255,255,255,.05);
    }
    .logPane {
      flex:0 0 180px;
      min-height:150px;
      max-height:240px;
      overflow:auto;
      background:var(--code);
      color:#e8edf2;
      font:11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
    }
    .logPane.empty {
      background:#fff;
      color:var(--muted);
      font-family:inherit;
    }
    .outputHeader {
      display:grid;
      gap:6px;
      flex:0 0 auto;
      padding-top:2px;
    }
    .outputHeaderTop {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:8px;
    }
    .outputTitle { font-size:12px; font-weight:700; color:var(--ink); }
    .outputRoot { color:var(--muted); font-size:11px; overflow-wrap:anywhere; margin-top:2px; }
    .outputActions { display:flex; gap:6px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .outputActions { flex:0 0 auto; }
    .outputs {
      display:grid;
      gap:6px;
      overflow:auto;
      max-height:none;
      min-height:0;
      flex:1 1 auto;
    }
    .outputItem {
      border:1px solid var(--line);
      border-radius:0;
      padding:8px 9px;
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      align-items:center;
      font-size:12px;
      background:#fff;
    }
    .outputItem small {
      display:block;
      color:var(--muted);
      font-size:11px;
      line-height:1.4;
      overflow-wrap:anywhere;
      margin-top:2px;
    }
    .outputButtons { display:flex; gap:6px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .path { color:var(--muted); font-size:12px; overflow-wrap:anywhere; margin-top:2px; }
    .preview {
      margin-top:0;
      border:1px solid var(--line);
      border-radius:0;
      overflow:hidden;
      flex:1 1 auto;
      min-height:0;
    }
    .previewHead { padding:8px 10px; border-bottom:1px solid var(--line); font-size:12px; color:var(--muted); background:var(--surface-soft); }
    .preview pre { border-radius:0; max-height:none; height:100%; }
    .modalOverlay {
      position:fixed;
      inset:0;
      z-index:50;
      display:none;
      align-items:center;
      justify-content:center;
      padding:22px;
      background:rgba(16,16,16,.45);
      backdrop-filter:blur(10px);
      -webkit-backdrop-filter:blur(10px);
    }
    .modalOverlay.open { display:flex; }
    .modalWindow {
      width:min(980px, 100%);
      height:min(760px, calc(100vh - 44px));
      border:1px solid var(--line);
      border-radius:0;
      background:var(--surface);
      box-shadow:var(--shadow);
      display:flex;
      flex-direction:column;
      overflow:hidden;
    }
    .modalHead {
      min-height:44px;
      padding:8px 10px;
      border-bottom:1px solid var(--line);
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      background:var(--surface-soft);
    }
    .modalTitle {
      min-width:0;
      display:grid;
      gap:2px;
    }
    .modalTitle strong { font-size:13px; color:var(--ink); }
    .modalTitle span {
      color:var(--muted);
      font-size:11px;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      max-width:70vw;
    }
    .modalBody {
      flex:1;
      min-height:0;
      padding:10px;
      background:var(--surface);
    }
    .modalBody pre {
      height:100%;
      max-height:none;
      background:#fff;
      font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;
    }
    .modalBody textarea {
      height:100%;
      resize:none;
      background:#fff;
      font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;
      padding:12px;
    }
    .modalStatus {
      color:var(--muted);
      font-size:11px;
      min-width:80px;
      text-align:right;
    }
    .muted { color:var(--muted); }
    @media (max-width: 980px) {
      main { grid-template-columns:300px 1fr; }
      section.result { grid-column:1 / -1; }
      main { overflow:auto; height:auto; min-height:calc(100vh - 72px); }
      html, body { overflow:auto; }
    }
    @media (max-width: 760px) {
      main { grid-template-columns:1fr; }
      section.result { grid-column:auto; }
      .scriptList { max-height:min(58vh, 560px); }
    }
    @media (max-width: 760px) {
      header { height:auto; padding:13px; align-items:flex-start; flex-direction:column; gap:10px; }
      .statusBar { justify-content:flex-start; }
      main { grid-template-columns:1fr; padding:10px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>钩子与 CTA 脚本适配智能体</h1>
      <div class="sub">钩子与 CTA 参考脚本 · 多模型适配 · 本地归档</div>
    </div>
    <div class="statusBar">
      <span id="apiBadge" class="badge">API Key</span>
      <span id="jobBadge" class="badge">空闲</span>
      <span id="configBadge" class="badge">agent_config</span>
    </div>
  </header>
  <main>
    <section>
      <div class="panelHead">
        <h2>模型与提示词</h2>
        <button onclick="saveSettings()">保存</button>
      </div>
      <div class="panelBody configBody">
        <label>模型 Base URL</label>
        <input id="modelmesh_base_url" />
        <label>API 密钥</label>
        <input id="modelmesh_api_key" type="password" autocomplete="off" placeholder="已配置；输入新密钥后保存" />
        <label>AI 文本模型</label>
        <input id="script_adaptation_text_model" />
        <div class="row2">
          <div>
            <label>目标视频模型</label>
            <div class="radioGroup" id="script_adaptation_target_model">
              <label class="radioOption">
                <input type="checkbox" name="script_adaptation_target_model" value="veo" checked />
                <span>Veo</span>
              </label>
              <label class="radioOption">
                <input type="checkbox" name="script_adaptation_target_model" value="omni" />
                <span>Omni</span>
              </label>
              <label class="radioOption">
                <input type="checkbox" name="script_adaptation_target_model" value="grok" />
                <span>Grok</span>
              </label>
            </div>
          </div>
          <div>
            <label>片段秒数</label>
            <div id="script_adaptation_segment_seconds" class="readonlyValue">8 秒</div>
            <div id="grokSegmentSecondsPicker" class="segmentSecondsPicker">
              <input id="grokSegmentSeconds" type="number" min="6" max="30" step="1" value="30" />
              <span>秒</span>
            </div>
          </div>
        </div>
        <div style="height:12px"></div>
        <div class="kv"><button class="blue" id="promptPathBtn">提示词</button></div>
      </div>
    </section>

    <section>
      <div class="panelHead">
        <h2>脚本库</h2>
        <div class="actions">
          <button class="blue" id="runUnusedBtn" onclick="runUnusedAgent()">适配未适配</button>
          <button class="primary" id="runBtn" onclick="runAgent()">调用 AI 适配</button>
          <button class="danger" id="cancelBtn" onclick="cancelJob()" disabled>终止任务</button>
        </div>
      </div>
      <div class="panelBody scriptBody">
        <div class="scriptLibrary">
          <div class="libraryHead">
            <span id="libraryTitle">钩子与 CTA 脚本库</span>
            <span id="libraryRoot" class="libraryRoot">加载中</span>
            <button class="blue" id="selectAllScriptsBtn">选当前产品</button>
            <button class="blue" id="clearScriptsBtn">清空</button>
            <button class="blue" id="refreshScriptsBtn">刷新</button>
          </div>
          <div id="products" class="products">
            <div class="muted">正在扫描脚本目录</div>
          </div>
        </div>
        <div class="selectedScriptInfo">
          <strong id="selectedScriptName">未选择脚本</strong>
          <span id="selectedScriptMeta">请从上方钩子与 CTA 脚本库勾选脚本后运行适配</span>
          <span id="selectedScriptPath"></span>
        </div>
      </div>
    </section>

    <section class="result">
      <div class="panelHead">
        <h2>运行</h2>
        <button class="blue" onclick="refreshJob()">刷新</button>
      </div>
      <div class="panelBody resultBody">
        <div class="checks" id="checks"></div>
        <div id="progressPanel" class="progressPanel idle">
          <div class="progressTop">
            <span id="progressSummary">暂无任务</span>
            <span id="progressPercent">0%</span>
          </div>
          <div class="progressBar"><div id="progressFill" class="progressFill"></div></div>
          <div id="progressCurrent" class="progressCurrent"></div>
          <div id="progressTasks" class="progressTasks"></div>
        </div>
        <div class="outputTitle">运行日志</div>
        <pre id="logs" class="logPane empty">暂无运行日志</pre>
        <div class="outputHeader">
          <div>
            <div class="outputHeaderTop">
              <div class="outputTitle">输出文件</div>
              <div class="outputActions">
                <button onclick="refreshOutputs()">刷新</button>
                <button onclick="openOutputRoot()">打开输出区</button>
              </div>
            </div>
            <div id="outputRoot" class="outputRoot">输出区加载中</div>
          </div>
        </div>
        <div class="outputs" id="outputs"></div>
        <div id="preview" class="preview" style="display:none">
          <div class="previewHead" id="previewTitle"></div>
          <pre id="previewText"></pre>
        </div>
      </div>
    </section>
  </main>
  <div id="fileModal" class="modalOverlay" role="dialog" aria-modal="true" aria-labelledby="fileModalTitle">
    <div class="modalWindow">
      <div class="modalHead">
        <div class="modalTitle">
          <strong id="fileModalTitle">文件内容</strong>
          <span id="fileModalPath"></span>
        </div>
        <div class="actions">
          <span id="fileModalStatus" class="modalStatus"></span>
          <button class="primary" id="fileModalSaveBtn">保存</button>
          <button id="fileModalOpenBtn">打开文件</button>
          <button class="blue" id="fileModalCloseBtn">关闭</button>
        </div>
      </div>
      <div class="modalBody">
        <textarea id="fileModalText" spellcheck="false" placeholder="把新的提示词内容粘贴到这里，然后保存"></textarea>
      </div>
    </div>
  </div>
  <script>
    let pollTimer = null;
    let selectedScriptFilename = '';
    let selectedScriptText = '';
    let selectedScriptPath = '';
    let selectedScripts = new Map();
    let knownScripts = new Map();
    let knownProducts = [];
    let currentProductName = '';
    let hideAdaptedScripts = false;
    let targetProfiles = {};
    let taskStatusMap = new Map();
    let unusedScriptCount = 0;
    let outputRoot = '';
    let currentJobRunning = false;
    let modalFilePath = '';
    const $ = (id) => document.getElementById(id);

    async function api(path, options={}) {
      const res = await fetch(path, {
        headers: {'Content-Type':'application/json'},
        ...options
      });
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = {error:text}; }
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }

    function collectPayload() {
      const targetModels = selectedTargetModels();
      return {
        script_text: selectedScriptText,
        script_filename: selectedScriptFilename,
        script_source_path: selectedScriptPath,
        script_paths: Array.from(selectedScripts.keys()),
        modelmesh_base_url: $('modelmesh_base_url').value,
        modelmesh_api_key: $('modelmesh_api_key').value,
        script_adaptation_text_model: $('script_adaptation_text_model').value,
        script_adaptation_target_model: targetModels[0] || 'veo',
        script_adaptation_target_models: targetModels,
        script_adaptation_segment_seconds: segmentSecondsForTargetModel(targetModels[0] || 'veo'),
        script_adaptation_segment_seconds_by_model: Object.fromEntries(targetModels.map(target => [target, segmentSecondsForTargetModel(target)]))
      };
    }

    function selectedTargetModels() {
      const selected = Array.from(document.querySelectorAll('input[name="script_adaptation_target_model"]:checked')).map(input => input.value);
      return selected.length ? selected : ['veo'];
    }

    function currentTargetModel() {
      return selectedTargetModels()[0] || 'veo';
    }

    function clampNumber(value, minValue, maxValue, fallback) {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return fallback;
      return Math.max(minValue, Math.min(maxValue, Math.round(parsed)));
    }

    function grokSegmentBounds() {
      const profile = targetProfiles.grok || {};
      const maxValue = Number(profile.segment_seconds || 30);
      const minValue = Number(profile.min_segment_seconds || 6);
      return { minValue, maxValue };
    }

    function grokSegmentSeconds() {
      const input = $('grokSegmentSeconds');
      const { minValue, maxValue } = grokSegmentBounds();
      return clampNumber(input?.value, minValue, maxValue, maxValue);
    }

    function setGrokSegmentSeconds(value) {
      const input = $('grokSegmentSeconds');
      if (!input) return;
      const { minValue, maxValue } = grokSegmentBounds();
      input.min = String(minValue);
      input.max = String(maxValue);
      input.value = String(clampNumber(value, minValue, maxValue, maxValue));
    }

    function invalidAdaptationState(state) {
      return ['json_missing', 'contract_mismatch', 'markdown_invalid'].includes(state || '');
    }

    function targetModelLabel(targetModel = currentTargetModel()) {
      const profile = targetProfiles[targetModel] || {};
      const fallback = { veo:'Veo', omni:'Omni', grok:'Grok' };
      return profile.label || fallback[targetModel] || targetModel;
    }

    function adaptationStateLabel(script) {
      const modelLabel = targetModelLabel();
      if (script.adaptation_state === 'json_missing') return `${modelLabel} 缺 JSON`;
      if (script.adaptation_state === 'contract_mismatch') return `${modelLabel} 结构不一致`;
      if (script.adaptation_state === 'markdown_invalid') return `${modelLabel} 结构异常`;
      return script.adapted ? `${modelLabel} 已适配` : `${modelLabel} 未适配`;
    }

    function segmentSecondsForTargetModel(targetModel = currentTargetModel()) {
      if (targetModel === 'grok') return grokSegmentSeconds();
      return Number((targetProfiles[targetModel] || {}).segment_seconds || (targetModel === 'grok' ? 30 : targetModel === 'omni' ? 10 : 8));
    }

    function syncSegmentSecondsDisplay() {
      const targetModel = currentTargetModel();
      const profile = targetProfiles[targetModel] || {};
      const readonly = $('script_adaptation_segment_seconds');
      const picker = $('grokSegmentSecondsPicker');
      if (targetModel === 'grok') {
        setGrokSegmentSeconds(grokSegmentSeconds());
        readonly.style.display = 'none';
        picker.style.display = 'flex';
      } else {
        readonly.style.display = 'flex';
        picker.style.display = 'none';
        readonly.textContent = `${segmentSecondsForTargetModel()} 秒`;
      }
      if (profile.prompt_open_path) {
        setOpenButton('promptPathBtn', `${profile.label || targetModel} 提示词`, profile.prompt_open_path);
      }
    }

    function setOpenButton(id, label, path) {
      const button = $(id);
      button.textContent = label;
      button.dataset.openPath = path || '';
      button.disabled = !path;
    }

    function applyStatePaths(data) {
      targetProfiles = data.target_profiles || {};
      const adaptation = (data.settings || {}).adaptation || {};
      if (currentTargetModel() === 'grok') {
        setGrokSegmentSeconds(adaptation.script_adaptation_segment_seconds);
      }
      syncSegmentSecondsDisplay();
    }

    function renderProducts(data) {
      const products = data.products || [];
      knownScripts = new Map();
      knownProducts = products;
      unusedScriptCount = Number(data.unused_count || 0);
      for (const product of products) {
        for (const script of (product.scripts || [])) {
          knownScripts.set(script.path, script);
        }
      }
      $('runUnusedBtn').textContent = unusedScriptCount ? `适配未适配（${unusedScriptCount}）` : '无未适配';
      $('runUnusedBtn').disabled = !unusedScriptCount;
      $('libraryTitle').textContent = `钩子与 CTA 脚本库 · 共 ${data.total_count || 0} · 已适配 ${data.adapted_count || 0} · 待处理 ${data.unused_count || 0} · 异常 ${data.invalid_count || 0}`;
      $('libraryRoot').textContent = data.roots?.length ? `已配置 ${data.roots.length} 个扫描目录` : '未配置输入目录';
      if (!products.length) {
        $('products').innerHTML = '<div class="muted">未找到 .md 脚本</div>';
        $('runUnusedBtn').textContent = '无未适配';
        $('runUnusedBtn').disabled = true;
        return;
      }
      if (!currentProductName || !products.some(product => product.name === currentProductName)) {
        currentProductName = products[0].name || '';
      }
      renderCurrentProduct();
    }

    function currentProduct() {
      return knownProducts.find(product => product.name === currentProductName) || knownProducts[0] || null;
    }

    function visibleProductScripts(product) {
      const scripts = product?.scripts || [];
      return hideAdaptedScripts ? scripts.filter(script => !script.adapted) : scripts;
    }

    function renderCurrentProduct() {
      const product = currentProduct();
      if (!product) {
        $('products').innerHTML = '<div class="muted">未找到 .md 脚本</div>';
        return;
      }
      currentProductName = product.name || '';
      const visibleScripts = visibleProductScripts(product);
      $('products').innerHTML = `
        <div class="productPicker">
          <div>
            <label for="productSelect">产品</label>
            <select id="productSelect">
                  ${knownProducts.map(item => `
                <option value="${escapeHtml(item.name || '')}" ${item.name === currentProductName ? 'selected' : ''}>
                  ${escapeHtml(item.name || '未命名产品')}${(item.countries || []).length ? ` · ${escapeHtml((item.countries || []).join('/'))}` : ''} · ${Number(item.count || 0)} 个 · 已 ${Number(item.adapted_count || 0)} · 待 ${Number(item.unused_count || 0)} · 异常 ${Number(item.invalid_count || 0)}
                </option>
              `).join('')}
            </select>
          </div>
          <label class="currentProductSelect">
            <input type="checkbox" id="currentProductCheck" title="选择当前产品下的全部脚本" />
            <span>${hideAdaptedScripts ? '选择当前产品可见脚本' : '选择当前产品全部脚本'}</span>
          </label>
        </div>
        <div class="productGroup">
          <div class="productSummary">
            <span class="productMain">
              <span class="productName">${escapeHtml(product.name || '未命名产品')}</span>
              ${(product.countries || []).length ? `<span class="countryBadge">${escapeHtml((product.countries || []).join('/'))}</span>` : ''}
            </span>
            <span class="productStats">
              <label class="hideAdaptedToggle ${hideAdaptedScripts ? 'active' : ''}" title="隐藏当前模型已经适配完成的脚本">
                <input type="checkbox" id="hideAdaptedCheck" ${hideAdaptedScripts ? 'checked' : ''} />
                <span>隐藏已适配</span>
              </label>
              <span class="productCount">${Number(product.count || 0)} 个</span>
              <span class="productCount done">已 ${Number(product.adapted_count || 0)}</span>
              <span class="productCount todo">待 ${Number(product.unused_count || 0)}</span>
              <span class="productCount invalid">异常 ${Number(product.invalid_count || 0)}</span>
            </span>
          </div>
          <div class="scriptList">
            ${visibleScripts.map(script => renderScriptItem(script)).join('') || `<div class="muted">${hideAdaptedScripts ? '已隐藏当前产品的全部已适配脚本' : '暂无脚本'}</div>`}
          </div>
        </div>
      `;
      document.querySelectorAll('#products .scriptItem').forEach(item => {
        item.classList.toggle('active', selectedScripts.has(item.dataset.scriptPath || ''));
      });
      applyTaskStatusesToVisibleScripts();
      syncSelectionChecks();
      updateSelectedScriptInfo();
    }

    function renderScriptItem(script) {
      return `
        <label class="scriptItem ${script.adapted ? 'used' : invalidAdaptationState(script.adaptation_state) ? 'failed' : ''}" data-script-path="${escapeHtml(script.path)}" data-script-name="${escapeHtml(script.name)}">
          <span class="scriptItemMain">
            <input type="checkbox" class="scriptCheck" data-script-path="${escapeHtml(script.path)}" ${selectedScripts.has(script.path) ? 'checked' : ''} />
            <span class="scriptName" title="${escapeHtml(script.name)}">${escapeHtml(script.name || '')}</span>
          </span>
          <span class="scriptMeta">
            ${script.country ? `<span class="countryBadge" title="国家">${escapeHtml(script.country)}</span>` : ''}
            <span class="scriptStatus ${escapeHtml(invalidAdaptationState(script.adaptation_state) ? script.adaptation_state : script.adapted ? 'done' : 'todo')}" title="${escapeHtml(script.adaptation_message || '')}">${escapeHtml(adaptationStateLabel(script))}</span>
            <span>${escapeHtml(script.size_label || '')}</span>
          </span>
        </label>
      `;
    }

    async function refreshScripts() {
      const data = await api(`/api/scripts?target_model=${encodeURIComponent(currentTargetModel())}`);
      renderProducts(data);
    }

    async function importServerScript(encodedPath) {
      const data = await api(`/api/file?path=${encodeURIComponent(encodedPath)}`);
      selectedScriptFilename = data.name || parentPath(data.path || '').split('/').pop() || 'script.md';
      selectedScriptPath = data.path || '';
      selectedScriptText = data.text || '';
      $('selectedScriptName').textContent = selectedScriptFilename;
      $('selectedScriptMeta').textContent = `${selectedScriptText.length} 字符`;
      $('selectedScriptPath').textContent = selectedScriptPath;
      document.querySelectorAll('#products .scriptItem').forEach(button => {
        button.classList.toggle('active', selectedScripts.has(button.dataset.scriptPath || ''));
      });
      await inspectAgent();
    }

    function updateSelectedScriptInfo() {
      const scripts = Array.from(selectedScripts.values());
      if (!scripts.length) {
        selectedScriptFilename = '';
        selectedScriptText = '';
        selectedScriptPath = '';
        $('selectedScriptName').textContent = '未选择脚本';
        $('selectedScriptMeta').textContent = '请从上方钩子与 CTA 脚本库勾选脚本后运行适配';
        $('selectedScriptPath').textContent = '';
        $('runBtn').textContent = currentJobRunning ? '任务运行中' : '调用 AI 适配';
        return;
      }
      const targetCount = selectedTargetModels().length;
      const taskCount = scripts.length * targetCount;
      selectedScriptFilename = scripts[0].name || '';
      selectedScriptText = '';
      selectedScriptPath = scripts[0].path || '';
      $('selectedScriptName').textContent = `已选择 ${scripts.length} 个脚本 × ${targetCount} 个模型`;
      $('selectedScriptMeta').textContent = scripts.slice(0, 3).map(item => item.name).join('、') + (scripts.length > 3 ? ` 等 ${scripts.length} 个` : '');
      $('selectedScriptPath').textContent = scripts.length === 1 ? (scripts[0].relative_path || scripts[0].name || '') : `将创建 ${taskCount} 个适配任务`;
      if (currentJobRunning) {
        $('runBtn').textContent = '任务运行中';
      } else {
        $('runBtn').textContent = taskCount > 1 ? `批量调用 AI 适配（${taskCount}）` : '调用 AI 适配';
      }
    }

    function syncSelectionChecks() {
      const productCheck = $('currentProductCheck');
      const scriptChecks = Array.from(document.querySelectorAll('#products .scriptCheck'));
      if (!productCheck || !scriptChecks.length) return;
      const checkedCount = scriptChecks.filter(input => input.checked).length;
      productCheck.checked = checkedCount === scriptChecks.length;
      productCheck.indeterminate = checkedCount > 0 && checkedCount < scriptChecks.length;
    }

    function setScriptSelected(scriptPath, selected) {
      const script = knownScripts.get(scriptPath);
      if (!script) return;
      if (selected) {
        selectedScripts.set(scriptPath, script);
      } else {
        selectedScripts.delete(scriptPath);
      }
      document.querySelectorAll('#products .scriptItem').forEach(item => {
        item.classList.toggle('active', selectedScripts.has(item.dataset.scriptPath || ''));
      });
      syncSelectionChecks();
      updateSelectedScriptInfo();
      inspectAgent().catch(err => {
        renderChecks([{level:'error', message:'脚本选择检查失败', detail:err.message}]);
      });
    }

    function selectScriptsByFilter(filterFn) {
      selectedScripts.clear();
      document.querySelectorAll('#products .scriptCheck').forEach(input => { input.checked = false; });
      for (const [path, script] of knownScripts.entries()) {
        if (!filterFn(script)) continue;
        selectedScripts.set(path, script);
        const selector = `.scriptCheck[data-script-path="${cssEscape(path)}"]`;
        const input = document.querySelector(selector);
        if (input) input.checked = true;
      }
      document.querySelectorAll('#products .scriptItem').forEach(item => {
        item.classList.toggle('active', selectedScripts.has(item.dataset.scriptPath || ''));
      });
      syncSelectionChecks();
      updateSelectedScriptInfo();
    }

    function setupProductScriptList() {
      $('refreshScriptsBtn').addEventListener('click', () => {
        refreshScripts().catch(err => {
          renderChecks([{level:'error', message:'脚本库刷新失败', detail:err.message}]);
        });
      });
      $('selectAllScriptsBtn').addEventListener('click', () => {
        const product = currentProduct();
        selectedScripts.clear();
        if (product) {
          for (const script of visibleProductScripts(product)) {
            selectedScripts.set(script.path, script);
          }
        }
        document.querySelectorAll('#products .scriptCheck').forEach(input => { input.checked = true; });
        document.querySelectorAll('#products .scriptItem').forEach(item => item.classList.add('active'));
        syncSelectionChecks();
        updateSelectedScriptInfo();
        inspectAgent().catch(err => {
          renderChecks([{level:'error', message:'脚本选择检查失败', detail:err.message}]);
        });
      });
      $('clearScriptsBtn').addEventListener('click', () => {
        selectedScripts.clear();
        document.querySelectorAll('#products .scriptCheck').forEach(input => { input.checked = false; });
        document.querySelectorAll('#products .scriptItem').forEach(item => item.classList.remove('active'));
        syncSelectionChecks();
        updateSelectedScriptInfo();
        inspectAgent().catch(err => {
          renderChecks([{level:'error', message:'脚本选择检查失败', detail:err.message}]);
        });
      });
      $('products').addEventListener('click', event => {
        const productCheck = event.target.closest('#currentProductCheck');
        if (productCheck) {
          const product = currentProduct();
          selectedScripts.clear();
          document.querySelectorAll('#products .scriptCheck').forEach(input => {
            input.checked = productCheck.checked;
          });
          if (productCheck.checked && product) {
            for (const script of visibleProductScripts(product)) {
              selectedScripts.set(script.path, script);
            }
          }
          document.querySelectorAll('#products .scriptItem').forEach(item => {
            item.classList.toggle('active', selectedScripts.has(item.dataset.scriptPath || ''));
          });
          syncSelectionChecks();
          updateSelectedScriptInfo();
          inspectAgent().catch(err => {
            renderChecks([{level:'error', message:'脚本选择检查失败', detail:err.message}]);
          });
          event.stopPropagation();
          return;
        }
        const item = event.target.closest('.scriptItem');
        if (!item) return;
        const input = item.querySelector('.scriptCheck');
        if (!input) return;
        if (event.target !== input) {
          input.checked = !input.checked;
          event.preventDefault();
        }
        setScriptSelected(item.dataset.scriptPath || '', input.checked);
      });
      $('products').addEventListener('change', event => {
        const hideAdaptedCheck = event.target.closest('#hideAdaptedCheck');
        if (hideAdaptedCheck) {
          hideAdaptedScripts = hideAdaptedCheck.checked;
          renderCurrentProduct();
          return;
        }
        const productSelect = event.target.closest('#productSelect');
        if (!productSelect) return;
        currentProductName = productSelect.value || '';
        selectedScripts.clear();
        renderCurrentProduct();
        inspectAgent().catch(err => {
          renderChecks([{level:'error', message:'脚本选择检查失败', detail:err.message}]);
        });
      });
    }

    function setupConfigOpenButtons() {
      const labels = {promptPathBtn:'提示词'};
      for (const id of ['promptPathBtn']) {
        $(id).addEventListener('click', event => {
          const path = event.currentTarget.dataset.openPath || '';
          if (!path) return;
          showFileModal(labels[id] || '文件内容', path).catch(err => {
            renderChecks([{level:'error', message:'文件读取失败', detail:err.message}]);
          });
        });
      }
    }

    function setupFileModal() {
      $('fileModalCloseBtn').addEventListener('click', closeFileModal);
      $('fileModal').addEventListener('click', event => {
        if (event.target === $('fileModal')) closeFileModal();
      });
      $('fileModalOpenBtn').addEventListener('click', () => {
        if (modalFilePath) openLocalPath(encodeURIComponent(modalFilePath));
      });
      $('fileModalSaveBtn').addEventListener('click', saveFileModal);
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && $('fileModal').classList.contains('open')) closeFileModal();
      });
    }

    async function showFileModal(title, path) {
      $('fileModalStatus').textContent = '';
      const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
      modalFilePath = data.path || path || '';
      $('fileModalTitle').textContent = `${title}内容`;
      $('fileModalPath').textContent = modalFilePath;
      $('fileModalText').value = data.text || '';
      $('fileModal').classList.add('open');
      setTimeout(() => $('fileModalText').focus(), 0);
    }

    async function saveFileModal() {
      if (!modalFilePath) return;
      const button = $('fileModalSaveBtn');
      const status = $('fileModalStatus');
      button.disabled = true;
      status.textContent = '保存中';
      try {
        const data = await api('/api/file', {
          method:'POST',
          body:JSON.stringify({path: modalFilePath, text: $('fileModalText').value})
        });
        status.textContent = `已保存 ${data.chars || 0} 字`;
        await loadState();
      } catch (err) {
        status.textContent = '保存失败';
        renderChecks([{level:'error', message:'提示词保存失败', detail:err.message}]);
      } finally {
        button.disabled = false;
      }
    }

    function closeFileModal() {
      $('fileModal').classList.remove('open');
    }

    function setupTargetModelControls() {
      document.querySelectorAll('input[name="script_adaptation_target_model"]').forEach(input => {
        input.addEventListener('change', event => {
          if (!document.querySelector('input[name="script_adaptation_target_model"]:checked')) {
            event.currentTarget.checked = true;
          }
          syncSegmentSecondsDisplay();
          updateSelectedScriptInfo();
          refreshScripts().catch(err => {
            renderChecks([{level:'error', message:'脚本库刷新失败', detail:err.message}]);
          });
          refreshOutputs().catch(err => {
            renderChecks([{level:'error', message:'输出列表刷新失败', detail:err.message}]);
          });
          inspectAgent().catch(err => {
            renderChecks([{level:'error', message:'配置检查失败', detail:err.message}]);
          });
        });
      });
      $('grokSegmentSeconds').addEventListener('change', () => {
        setGrokSegmentSeconds($('grokSegmentSeconds').value);
        refreshScripts().catch(err => {
          renderChecks([{level:'error', message:'脚本库刷新失败', detail:err.message}]);
        });
        inspectAgent().catch(err => {
          renderChecks([{level:'error', message:'配置检查失败', detail:err.message}]);
        });
      });
      syncSegmentSecondsDisplay();
    }

    function renderChecks(checks=[]) {
      const labels = {ok:'通过', warn:'注意', error:'错误'};
      $('checks').innerHTML = checks.map(item => `
        <div class="check ${item.level}">
          <strong>${escapeHtml(labels[item.level] || (item.level || '').toUpperCase())}</strong>
          <div class="checkText">
            <div>${escapeHtml(item.message || '')}</div>
            ${item.detail ? `<div class="detail">${escapeHtml(item.detail)}</div>` : ''}
          </div>
        </div>
      `).join('') || '<div class="muted">暂无巡检结果</div>';
    }

    function renderOutputs(outputs=[]) {
      $('outputs').innerHTML = outputs.length ? outputs.map(item => `
        <div class="outputItem">
          <div>
            <strong>${escapeHtml(item.name)}</strong>
            <small>${escapeHtml(item.kind || '文件')} · ${escapeHtml(item.size_label || '')} · ${escapeHtml(item.modified || '')}</small>
            <div class="path">${escapeHtml(item.path)}</div>
          </div>
          <div class="outputButtons">
            <button onclick="previewFile('${encodeURIComponent(item.path)}')">预览</button>
            <button onclick="openLocalPath('${encodeURIComponent(item.path)}')">打开文件</button>
            <button onclick="openLocalPath('${encodeURIComponent(parentPath(item.path))}')">打开目录</button>
          </div>
        </div>
      `).join('') : '<div class="muted">暂无输出文件</div>';
      $('outputs').scrollTop = 0;
    }

    function taskLabel(status) {
      return {
        waiting: '等待',
        running: '适配中',
        retrying: '重试中',
        completed: '已完成',
        failed: '失败',
        cancelled: '已终止'
      }[status] || '等待';
    }

    function updateTaskStatusMap(tasks=[]) {
      taskStatusMap = new Map();
      for (const task of tasks) {
        if (task.source_path) taskStatusMap.set(task.source_path, task);
        if (task.filename) taskStatusMap.set(task.filename, task);
      }
    }

    function taskForScriptElement(item) {
      return taskStatusMap.get(item.dataset.scriptPath || '') || taskStatusMap.get(item.dataset.scriptName || '');
    }

    function applyTaskStatusesToVisibleScripts() {
      document.querySelectorAll('#products .scriptItem').forEach(item => {
        const task = taskForScriptElement(item);
        item.classList.remove('running', 'retrying', 'completed', 'failed', 'cancelled');
        const status = task?.status || '';
        if (['running', 'retrying', 'completed', 'failed', 'cancelled'].includes(status)) {
          item.classList.add(status);
        }
        const badge = item.querySelector('.scriptStatus');
        if (badge && task) {
          badge.className = `scriptStatus ${status || 'waiting'}`;
          badge.textContent = taskLabel(status);
          if (task.error) badge.title = task.error;
        }
      });
    }

    function renderProgress(job) {
      const progress = job.progress || {};
      const tasks = job.tasks || [];
      updateTaskStatusMap(tasks);
      applyTaskStatusesToVisibleScripts();
      const total = Number(progress.total || tasks.length || 0);
      const done = Number(progress.done || 0);
      const failed = Number(progress.failed || 0);
      const cancelled = Number(progress.cancelled || 0);
      const finished = done + failed + cancelled;
      const percent = total ? Math.round((finished / total) * 100) : 0;
      $('progressPanel').classList.toggle('idle', !total);
      $('progressSummary').textContent = total
        ? `任务进度：已完成 ${done} / 失败 ${failed} / 已终止 ${cancelled} / 剩余 ${Math.max(total - finished, 0)}`
        : '暂无任务';
      $('progressPercent').textContent = total ? `${percent}%` : '0%';
      $('progressFill').style.width = `${percent}%`;
      const runningTasks = tasks.filter(task => ['running', 'retrying'].includes(task.status || ''));
      const runningTask = runningTasks[0];
      const attempt = Number(progress.current_attempt || runningTask?.attempt || 0);
      const maxAttempts = Number(progress.current_max_attempts || runningTask?.max_attempts || 0);
      const attemptText = attempt && maxAttempts ? `（第 ${attempt}/${maxAttempts} 次）` : '';
      const runningNames = runningTasks.slice(0, 3).map(task => `${task.index || ''}/${total} ${compactScriptName(task.filename || '')}`).join('；');
      $('progressCurrent').textContent = runningTasks.length
        ? `并发适配中：${runningTasks.length}/${Number(progress.concurrency || 3)} 条 ${runningNames}${runningTasks.length > 3 ? ' ...' : ''} ${attemptText}`
        : (total ? '当前没有正在适配的脚本' : '');
      $('progressTasks').innerHTML = tasks.length ? tasks.map(task => `
        <div class="progressTask ${escapeHtml(task.status || 'waiting')}">
          <strong>${escapeHtml(taskLabel(task.status))}${task.attempt ? ` ${escapeHtml(String(task.attempt))}/${escapeHtml(String(task.max_attempts || 3))}` : ''}</strong>
          <span title="${escapeHtml(task.filename || '')}">${escapeHtml(compactScriptName(task.filename || ''))}</span>
        </div>
      `).join('') : '';
    }

    function renderJob(job) {
      const statusText = {idle:'空闲', running:'运行中', cancelling:'终止中', completed:'已完成', failed:'失败', cancelled:'已终止'};
      const activeRuns = Number(job.active_runs || (job.running ? 1 : 0));
      currentJobRunning = !!job.running;
      $('jobBadge').textContent = job.running
        ? `${job.cancel_requested ? '终止中' : '运行中'}${activeRuns > 1 ? ` x${activeRuns}` : ''}`
        : (statusText[job.status] || job.status || '空闲');
      const failedCount = Number((job.progress || {}).failed || 0);
      $('jobBadge').className = 'badge ' + (job.status === 'failed' || failedCount ? 'warn' : job.status === 'completed' ? 'ok' : job.status === 'cancelled' || job.status === 'cancelling' ? 'warn' : '');
      $('runBtn').disabled = !!job.running;
      $('runUnusedBtn').disabled = !!job.running || !unusedScriptCount;
      $('cancelBtn').disabled = !job.running;
      updateSelectedScriptInfo();
      renderProgress(job);
      const visibleLogs = (job.logs || '').trim();
      $('logs').textContent = visibleLogs || '暂无运行日志';
      $('logs').className = 'logPane' + (visibleLogs ? '' : ' empty');
      $('logs').scrollTop = $('logs').scrollHeight;
      if (job.outputs && job.outputs.length) {
        renderOutputs(job.outputs);
        outputRoot = parentPath(job.outputs[0].path || '');
        $('outputRoot').textContent = outputRoot ? `输出区：${outputRoot}` : '输出区未确定';
      }
      if (job.error) {
        renderChecks([{level:'error', message:'任务失败', detail:job.error}]);
      }
    }

    async function loadState() {
      const data = await api('/api/state');
      const s = data.settings || {};
      const model = s.model || {};
      const adaptation = s.adaptation || {};
      $('modelmesh_base_url').value = model.modelmesh_base_url || '';
      $('modelmesh_api_key').value = '';
      $('modelmesh_api_key').placeholder = data.has_api_key ? '已配置；输入新密钥后保存' : '请输入 API 密钥';
      $('script_adaptation_text_model').value = model.script_adaptation_text_model || model.video_analysis_model || '';
      const targetModel = adaptation.script_adaptation_target_model || 'veo';
      document.querySelectorAll('input[name="script_adaptation_target_model"]').forEach(input => { input.checked = false; });
      const targetInput = document.querySelector(`input[name="script_adaptation_target_model"][value="${targetModel}"]`);
      if (targetInput) targetInput.checked = true;
      else document.querySelector('input[name="script_adaptation_target_model"][value="veo"]').checked = true;
      syncSegmentSecondsDisplay();
      applyStatePaths(data);
      $('apiBadge').textContent = data.has_api_key ? 'API Key 已就绪' : '缺少 API Key';
      $('apiBadge').className = 'badge ' + (data.has_api_key ? 'ok' : 'warn');
      await refreshScripts();
      await inspectAgent();
      await refreshJob();
      await refreshOutputs();
    }

    async function saveSettings() {
      const payload = collectPayload();
      const data = await api('/api/settings', {method:'POST', body:JSON.stringify(payload)});
      $('modelmesh_api_key').value = '';
      $('modelmesh_api_key').placeholder = data.has_api_key ? '已配置；输入新密钥后保存' : '请输入 API 密钥';
      applyStatePaths(data);
      $('apiBadge').textContent = data.has_api_key ? 'API Key 已就绪' : '缺少 API Key';
      $('apiBadge').className = 'badge ' + (data.has_api_key ? 'ok' : 'warn');
      await inspectAgent();
      await refreshScripts();
      await refreshOutputs();
    }

    async function inspectAgent() {
      const data = await api('/api/inspect', {method:'POST', body:JSON.stringify(collectPayload())});
      renderChecks(data.checks || []);
    }

    async function runAgent() {
      if (!selectedScripts.size) {
        renderChecks([{level:'warn', message:'尚未选择 Markdown 脚本文档', detail:'请先勾选脚本，或点击“适配未适配”自动提交待处理脚本。'}]);
        return;
      }
      if (currentJobRunning) {
        renderChecks([{level:'warn', message:'任务正在运行', detail:'请等待当前任务完成，或先终止当前任务后再提交。'}]);
        return;
      }
      $('preview').style.display = 'none';
      $('outputRoot').textContent = '等待本次输出...';
      renderOutputs([]);
      const data = await api('/api/run', {method:'POST', body:JSON.stringify(collectPayload())});
      renderJob(data);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1200);
    }

    async function runUnusedAgent() {
      selectScriptsByFilter(script => !script.adapted);
      if (!selectedScripts.size) {
        renderChecks([{level:'ok', message:'暂无未适配脚本', detail:'当前扫描到的 Markdown 都已经生成过对应适配结果。'}]);
        return;
      }
      await runAgent();
    }

    async function cancelJob() {
      const data = await api('/api/cancel', {method:'POST', body:JSON.stringify({})});
      renderJob(data);
      renderChecks([{level:'warn', message:'已请求终止任务', detail:'未开始的脚本会立即标记为已终止；正在调用模型的脚本会在当前请求返回后停止。'}]);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1000);
    }

    async function refreshJob() {
      const data = await api('/api/job');
      renderJob(data);
      if (!data.running && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        await refreshScripts();
        await refreshOutputs();
      }
    }

    async function refreshOutputs() {
      const data = await api(`/api/outputs?target_model=${encodeURIComponent(currentTargetModel())}`);
      outputRoot = data.root || '';
      $('outputRoot').textContent = outputRoot ? `输出区：${outputRoot}` : '输出区未确定';
      renderOutputs(data.outputs || []);
    }

    async function previewFile(encodedPath) {
      const data = await api(`/api/file?path=${encodedPath}`);
      $('preview').style.display = 'block';
      $('previewTitle').textContent = data.path;
      $('previewText').textContent = data.text;
    }

    function parentPath(path) {
      const parts = String(path || '').split('/');
      parts.pop();
      return parts.join('/') || '.';
    }

    async function openLocalPath(encodedPath) {
      const path = decodeURIComponent(encodedPath || '');
      try {
        await api('/api/open', {method:'POST', body:JSON.stringify({path})});
      } catch (err) {
        $('logs').textContent = err.message || String(err);
        $('logs').className = 'logPane';
      }
    }

    async function openOutputRoot() {
      if (!outputRoot) {
        await refreshOutputs();
      }
      if (outputRoot) {
        await openLocalPath(encodeURIComponent(outputRoot));
      }
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({
        '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
      }[ch]));
    }

    function compactScriptName(value) {
      const text = String(value || '').replace(/\.md$/i, '');
      if (text.length <= 34) return text;
      const parts = text.split('-').filter(Boolean);
      const prefix = parts.slice(0, 2).join('-') || text.slice(0, 12);
      const suffix = parts.slice(-2).join('-') || text.slice(-18);
      const compact = `${prefix}…${suffix}`;
      return compact.length <= 42 ? compact : `${text.slice(0, 14)}…${text.slice(-22)}`;
    }

    function cssEscape(value) {
      if (window.CSS && CSS.escape) return CSS.escape(String(value || ''));
      return String(value || '').replace(/["\\]/g, '\\$&');
    }

    setupProductScriptList();
    setupConfigOpenButtons();
    setupFileModal();
    setupTargetModelControls();
    loadState().catch(err => {
      renderChecks([{level:'error', message:'页面初始化失败', detail:err.message}]);
    });
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                text_response(self, 200, HTML, "text/html; charset=utf-8")
            elif parsed.path == "/api/state":
                json_response(self, 200, settings_for_client())
            elif parsed.path == "/api/job":
                json_response(self, 200, JOB.snapshot())
            elif parsed.path == "/api/outputs":
                json_response(self, 200, list_adaptation_outputs(target_model_from_query(parsed)))
            elif parsed.path == "/api/scripts":
                json_response(self, 200, list_product_scripts(target_model_from_query(parsed)))
            elif parsed.path == "/api/file":
                query = urllib.parse.parse_qs(parsed.query)
                raw_path = query.get("path", [""])[0]
                path = safe_root_path(raw_path)
                if not path.exists() or not path.is_file():
                    raise ValueError("文件不存在")
                text = path.read_text(encoding="utf-8", errors="ignore")
                json_response(self, 200, {"name": path.name, "path": display_path(path), "text": text[:300000]})
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert to API error.
            json_response(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = read_request_json(self)
            if parsed.path == "/api/settings":
                json_response(self, 200, update_settings(payload))
            elif parsed.path == "/api/inspect":
                json_response(self, 200, inspect_payload(payload))
            elif parsed.path == "/api/run":
                update_settings(payload)
                json_response(self, 200, JOB.start(payload))
            elif parsed.path == "/api/cancel":
                json_response(self, 200, JOB.cancel())
            elif parsed.path == "/api/open":
                json_response(self, 200, open_local_path(str(payload.get("path") or "")))
            elif parsed.path == "/api/file":
                path = safe_root_path(str(payload.get("path") or ""))
                if not path.exists() or not path.is_file():
                    raise ValueError("文件不存在")
                text = str(payload.get("text") or "")
                path.write_text(text, encoding="utf-8")
                json_response(self, 200, {"name": path.name, "path": display_path(path), "chars": len(text)})
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert to API error.
            json_response(self, 400, {"error": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the script adaptation agent web UI.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"钩子与 CTA 脚本适配智能体 Web 界面: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
