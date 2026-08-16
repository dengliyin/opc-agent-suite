from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ENV_PATH, SETTINGS_PATH, Settings, load_hybrid_omni_settings, load_settings, mask_secrets, update_env_values
from .exporter import (
    deliver_hybrid_scripts,
    export_completed_scripts,
    restore_exported_scripts,
    restore_hybrid_deliveries,
)
from .files import character_image_path, scan_scripts, script_to_dict, storyboard_image_path, summarize_catalog, suppress_script, video_output_path
from .product_lock import storyboard_meta_path
from .tasks import JobManager, VALID_STAGES


omni_settings = load_settings("omni")
grok_settings = load_settings("grok")
hybrid_omni_settings = load_hybrid_omni_settings()
settings = omni_settings
job_managers = {
    "omni": JobManager(omni_settings),
    "grok": JobManager(grok_settings),
    "hybrid_omni": JobManager(hybrid_omni_settings),
}
job_manager = job_managers["omni"]
static_dir = Path(__file__).resolve().parent.parent / "static"
CATALOG_CACHE_TTL_SECONDS = max(0.0, float(os.getenv("CATALOG_CACHE_TTL_SECONDS", "5")))
_catalog_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_catalog_cache_lock = threading.Lock()


IMAGE_SIZE_CHOICES = [
    ("2160x3840", "9:16 · 4K · 2160x3840"),
    ("3840x2160", "16:9 · 4K · 3840x2160"),
    ("3264x2448", "4:3 · 4K · 3264x2448"),
    ("2448x3264", "3:4 · 4K · 2448x3264"),
    ("2880x2880", "1:1 · 4K · 2880x2880"),
]
IMAGE2_1K_SIZE_CHOICES = [
    ("720x1280", "9:16 · 1K · 720x1280"),
    ("1280x720", "16:9 · 1K · 1280x720"),
    ("1152x864", "4:3 · 1K · 1152x864"),
    ("864x1152", "3:4 · 1K · 864x1152"),
    ("1024x1024", "1:1 · 1K · 1024x1024"),
]
OMNI_VIDEO_SIZE_CHOICES = [
    ("720x1280", "9:16 · 720p · 720x1280"),
    ("1280x720", "16:9 · 720p · 1280x720"),
]
GROK_IMAGE_ASPECT_CHOICES = ["9:16", "4:3", "3:4", "1:1", "16:9"]
GROK_IMAGE_RESOLUTION_CHOICES = ["4k", "2k", "1k"]
GROK_VIDEO_ASPECT_CHOICES = ["9:16", "16:9", "2:3", "3:2", "1:1"]
GROK_VIDEO_RESOLUTION_CHOICES = ["720p", "480p"]
GROK_VIDEO_DURATION_CHOICES = ["6", "8", "10", "12", "15", "20", "25", "30"]
SKYREELS_VIDEO_MODEL = "SkyReels V4 Omni Fast"
SKYREELS_VIDEO_ASPECT_CHOICES = ["9:16", "16:9", "1:1", "4:3", "3:4"]
SKYREELS_VIDEO_RESOLUTION_CHOICES = ["1080p", "720p", "480p"]
SKYREELS_VIDEO_DURATION_CHOICES = ["3", "5", "8", "10", "12", "15"]
SCRIPT_CONCURRENCY_CHOICES = [1, 2, 3, 5, 8, 12, 16, 20]
OPTIONAL_API_PAYLOAD_KEYS = {
    "otu_api_key",
    "grok_api_key",
    *[
        f"{provider}_{field}"
        for provider in ("omni", "grok")
        for field in (
            "character_image_size",
            "character_image_aspect_ratio",
            "character_image_resolution",
            "storyboard_image_size",
            "storyboard_image_aspect_ratio",
            "storyboard_image_resolution",
            "function_video_size",
            "function_video_aspect_ratio",
            "function_video_resolution",
            "function_video_duration",
        )
    ],
}

app = FastAPI(title="Fragment Output Agent")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


class RunRequest(BaseModel):
    stage: str = Field("smart", pattern="^(all|characters|storyboards|videos|direct_videos|product_videos|repair|smart)$")
    overwrite: Optional[bool] = False
    script_paths: Optional[List[str]] = None
    script_concurrency: Optional[int] = Field(None, ge=1, le=20)
    reference_images: Optional[Dict[str, str]] = None


class CancelRequest(BaseModel):
    job_id: Optional[str] = None


class ConcurrencyRequest(BaseModel):
    job_id: Optional[str] = None
    script_concurrency: int = Field(..., ge=1, le=20)


class ExportRequest(BaseModel):
    script_paths: Optional[List[str]] = None


class RestoreRequest(BaseModel):
    script_paths: Optional[List[str]] = None
    restore_videos: Optional[bool] = False


class ScriptDeleteRequest(BaseModel):
    script_paths: List[str] = Field(..., min_length=1)


class ArtifactDeleteRequest(BaseModel):
    path: str = Field(..., min_length=1)


class PathSettingsRequest(BaseModel):
    script_root: str = Field(..., min_length=1)
    grok_script_root: str = Field(..., min_length=1)
    hybrid_omni_script_root: str = Field(..., min_length=1)
    reference_root: str = Field(..., min_length=1)
    video_output_root: str = Field(..., min_length=1)
    grok_video_output_root: str = Field(..., min_length=1)
    hybrid_omni_video_output_root: str = Field(..., min_length=1)


class DirectoryCreateRequest(BaseModel):
    parent: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class ApiSettingsRequest(BaseModel):
    otu_api_key: Optional[str] = ""
    otu_base_url: str = Field(..., min_length=1)
    image_model: str = Field(..., min_length=1)
    image_fallback_models: str = Field(..., min_length=1)
    image_size: str = Field(..., min_length=1)
    omni_model: str = Field(..., min_length=1)
    video_size: str = Field(..., min_length=1)
    grok_api_key: Optional[str] = ""
    grok_base_url: str = Field(..., min_length=1)
    grok_image_aspect_ratio: str = Field(..., min_length=1)
    grok_image_resolution: str = Field(..., min_length=1)
    grok_video_aspect_ratio: str = Field(..., min_length=1)
    grok_video_resolution: str = Field(..., min_length=1)
    grok_video_duration: int = Field(..., ge=6, le=30)
    omni_character_api_model: str = Field(..., min_length=1)
    omni_storyboard_api_model: str = Field(..., min_length=1)
    omni_video_api_model: str = Field(..., min_length=1)
    grok_character_api_model: str = Field(..., min_length=1)
    grok_storyboard_api_model: str = Field(..., min_length=1)
    grok_video_api_model: str = Field(..., min_length=1)


@app.get("/")
def portal_page() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/settings")
@app.get("/settings/")
def settings_page() -> FileResponse:
    return FileResponse(static_dir / "settings.html")


@app.get("/api-settings")
@app.get("/api-settings/")
def api_settings_page() -> FileResponse:
    return FileResponse(static_dir / "api-settings.html")


@app.get("/omni")
@app.get("/omni/")
def omni_page() -> FileResponse:
    return FileResponse(static_dir / "omni.html")


@app.get("/grok")
@app.get("/grok/")
def grok_page() -> FileResponse:
    return FileResponse(static_dir / "grok.html")


@app.get("/hybrid-omni")
@app.get("/hybrid-omni/")
def hybrid_omni_page() -> FileResponse:
    return FileResponse(static_dir / "hybrid-omni.html")




def _settings_for(provider: str) -> Settings:
    return {
        "omni": omni_settings,
        "grok": grok_settings,
        "hybrid_omni": hybrid_omni_settings,
    }.get(provider, omni_settings)


def _manager_for(provider: str) -> JobManager:
    return job_managers[provider if provider in job_managers else "omni"]


def _config_payload(current: Settings) -> Dict[str, Any]:
    return {
        "provider": current.provider,
        "provider_label": current.provider_label,
        "provider_ready": current.provider_ready,
        "api_base_path": current.api_base_path,
        "otu_ready": current.has_otu_key,
        "otu_base_url": current.otu_base_url,
        "image_model": current.image_model,
        "image_model_candidates": current.image_model_candidates,
        "omni_model": current.omni_model,
        "image_size": current.image_size,
        "video_size": current.video_size,
        "image_display_summary": current.image_display_summary,
        "video_display_summary": current.video_display_summary,
        "video_label": current.video_display_label,
        "script_concurrency": current.script_concurrency,
        "script_concurrency_choices": SCRIPT_CONCURRENCY_CHOICES,
        "script_root": str(current.script_root),
        "reference_root": str(current.reference_root),
        "video_output_root": str(current.video_output_root),
        "preserve_adapted_script_on_delete": True,
        "workflow": current.workflow,
    }


def _path_settings_payload() -> Dict[str, Any]:
    fields = [
        _path_field("script_root", "SCRIPT_ROOT", "Omni 脚本输入路径", omni_settings.script_root, "input"),
        _path_field("grok_script_root", "GROK_SCRIPT_ROOT", "Grok 脚本输入路径", grok_settings.script_root, "input"),
        _path_field(
            "hybrid_omni_script_root",
            "HYBRID_OMNI_SCRIPT_ROOT",
            "混剪 Omni 适配脚本输入路径",
            hybrid_omni_settings.script_root,
            "input",
        ),
        _path_field("reference_root", "REFERENCE_ROOT", "产品参考图路径", omni_settings.reference_root, "input"),
        _path_field("video_output_root", "VIDEO_OUTPUT_ROOT", "Omni 视频输出路径", omni_settings.video_output_root, "output"),
        _path_field("grok_video_output_root", "GROK_VIDEO_OUTPUT_ROOT", "Grok 视频输出路径", grok_settings.video_output_root, "output"),
        _path_field(
            "hybrid_omni_video_output_root",
            "HYBRID_OMNI_VIDEO_OUTPUT_ROOT",
            "混剪钩子与 CTA Omni 视频输出路径",
            hybrid_omni_settings.video_output_root,
            "output",
        ),
    ]
    return {
        "fields": fields,
        "active_jobs": _active_jobs(),
        "providers": {
            "omni": _config_payload(omni_settings),
            "grok": _config_payload(grok_settings),
            "hybrid_omni": _config_payload(hybrid_omni_settings),
        },
    }


def _api_settings_payload() -> Dict[str, Any]:
    groups = [
        {
            "title": "OTU API Key",
            "description": "Omni 与 OTU 图片接口共用；模型与参数在上方 Agent 功能行选择",
            "fields": [
                _api_field("otu_api_key", "OTU_API_KEY", "OTU API Key", "", field_type="password", secret=True, configured=bool(omni_settings.otu_api_key)),
            ],
        },
        {
            "title": "RunningHub API Key",
            "description": "Grok 功能1、功能2、功能3共用；模型与参数在上方 Agent 功能行选择",
            "fields": [
                _api_field("grok_api_key", "GROK_API_KEY", "Grok API Key", "", field_type="password", secret=True, configured=bool(grok_settings.grok_api_key)),
            ],
        },
    ]
    return {
        "summary": _api_summary_payload(),
        "groups": groups,
        "active_jobs": _active_jobs(),
        "providers": {
            "omni": _config_payload(omni_settings),
            "grok": _config_payload(grok_settings),
        },
    }


def _api_field(
    key: str,
    env_key: str,
    label: str,
    value: str,
    *,
    field_type: str = "text",
    secret: bool = False,
    configured: bool = False,
    options: Optional[List[str]] = None,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "env_key": env_key,
        "label": label,
        "value": "" if secret else str(value),
        "type": field_type,
        "secret": secret,
        "configured": configured,
        "options": options or [],
        "min": min_value,
        "max": max_value,
    }


def _select_options(current: str, options: List[str]) -> List[str]:
    unique: List[str] = []
    if current:
        unique.append(str(current))
    for option in options:
        if option and option not in unique:
            unique.append(option)
    return unique


def _control_options(current: str, options: List[Any], *, allow_custom: bool = False) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    for option in options:
        if isinstance(option, (tuple, list)) and len(option) >= 2:
            value, label = str(option[0]), str(option[1])
        else:
            value = label = str(option)
        if value and value not in seen:
            seen.add(value)
            normalized.append({"value": value, "label": label})
    if allow_custom and current and current not in seen:
        normalized.insert(0, {"value": current, "label": current})
    return normalized


def _param_control(key: str, label: str, value: Any, options: List[Any]) -> Dict[str, Any]:
    option_items = _control_options(str(value or ""), options)
    allowed_values = {item["value"] for item in option_items}
    selected = str(value or "")
    if selected not in allowed_values and option_items:
        selected = option_items[0]["value"]
    return {
        "key": key,
        "label": label,
        "value": selected,
        "options": option_items,
    }


def _provider_key(current: Settings) -> str:
    return current.provider.strip().lower()


def _api_summary_payload() -> Dict[str, Any]:
    return {
        "api_provider_count": 2,
        "endpoint_count": 9,
        "model_count": 8,
        "description": "当前有 2 个 API 提供方；下方 Agent 功能行决定每个功能使用哪个模型和参数。",
        "api_inventory": [
            {
                "api": "OTU API",
                "base_url": omni_settings.otu_base_url,
                "key_status": "已配置" if omni_settings.otu_api_key else "未配置",
                "models": [
                    {
                        "name": "gpt-image-2 / gpt-image-2-2K / gpt-image-2-4K",
                        "role": "异步图片生成与图片编辑",
                        "endpoints": ["/v1/videos", "/v1/videos/{task_id}"],
                        "params": ["JSON 提交任务并轮询结果；参数在 Agent 功能行设置"],
                    },
                    {
                        "name": "image2",
                        "role": "同步图片生成与图片编辑（仅1K）",
                        "endpoints": ["/v1/images/generations", "/v1/images/edits"],
                        "params": ["同步返回结果；仅支持1K尺寸"],
                    },
                    {
                        "name": "omni_flash-10s",
                        "role": "Omni 图生视频",
                        "endpoints": ["/v1/videos", "/v1/videos/{task_id}"],
                        "params": ["参数在 Agent 功能行设置"],
                    },
                ],
            },
            {
                "api": "RunningHub API",
                "base_url": grok_settings.grok_base_url,
                "key_status": "已配置" if grok_settings.grok_api_key else "未配置",
                "models": [
                    {
                        "name": "G-2.0",
                        "role": "Grok 文生图与图生图",
                        "endpoints": ["/openapi/v2/rhart-image-g-2/text-to-image", "/openapi/v2/rhart-image-g-2/image-to-image", "/openapi/v2/query"],
                        "params": ["参数在 Agent 功能行设置"],
                    },
                    {
                        "name": "X v1.5",
                        "role": "Grok 图生视频",
                        "endpoints": ["/openapi/v2/rhart-video-g/image-to-video", "/openapi/v2/query"],
                        "params": ["参数在 Agent 功能行设置"],
                    },
                    {
                        "name": SKYREELS_VIDEO_MODEL,
                        "role": "SkyReels V4 Omni 参考视频-fast",
                        "endpoints": ["/openapi/v2/skyreels-v4/omni-reference-fast", "/openapi/v2/query"],
                        "params": ["参数在 Agent 功能行设置；最长 15 秒"],
                    },
                ],
            },
        ],
        "agent_function_map": [
            {
                "agent": "Omni 片段产出 Agent",
                "functions": [
                    _agent_function_row(omni_settings, "omni_character_api_model", "功能1 生成人物图", "characters"),
                    _agent_function_row(omni_settings, "omni_storyboard_api_model", "功能2 生成故事版图", "storyboards"),
                    _agent_function_row(omni_settings, "omni_video_api_model", "功能3 生成Omni视频", "videos"),
                ],
            },
            {
                "agent": "Grok 片段产出 Agent",
                "functions": [
                    _agent_function_row(grok_settings, "grok_character_api_model", "功能1 生成人物图", "characters"),
                    _agent_function_row(grok_settings, "grok_storyboard_api_model", "功能2 生成故事版图", "storyboards"),
                    _agent_function_row(grok_settings, "grok_video_api_model", "功能3 生成Grok视频", "videos"),
                ],
            },
        ],
    }


def _agent_function_row(current: Settings, key: str, function_label: str, stage: str) -> Dict[str, Any]:
    selected = {
        "characters": current.character_api_model,
        "storyboards": current.storyboard_api_model,
        "videos": current.video_api_model,
    }[stage]
    options = _function_api_model_options(stage, selected)
    detail = _function_option_detail(current, stage, selected)
    option_details = {option["value"]: _function_option_detail(current, stage, option["value"]) for option in options}
    return {
        "key": key,
        "function": function_label,
        "selected": selected,
        "options": options,
        "option_details": option_details,
        **detail,
    }


def _function_api_model_options(stage: str, selected: str) -> List[Dict[str, str]]:
    if stage in {"characters", "storyboards"}:
        values = _select_options(
            selected,
            [
                "otu:gpt-image-2-4K",
                "otu:image2",
                "grok:G-2.0",
            ],
        )
    else:
        values = _select_options(
            selected,
            [
                f"otu:{omni_settings.omni_model}",
                "otu:omni_flash-10s",
                "grok:X v1.5",
                f"grok:{SKYREELS_VIDEO_MODEL}",
            ],
        )
    return [{"value": value, "label": _api_model_label(value)} for value in values]


def _api_model_label(value: str) -> str:
    api, model = _split_api_model(value)
    label = "RunningHub API" if api == "grok" else "OTU API"
    return f"{label} / {model}"


def _function_param_controls(current: Settings, stage: str, value: str) -> List[Dict[str, Any]]:
    api, model = _split_api_model(value)
    provider = _provider_key(current)
    if stage in {"characters", "storyboards"}:
        role = "character" if stage == "characters" else "storyboard"
        if api == "grok":
            return [
                _param_control(
                    f"{provider}_{role}_image_aspect_ratio",
                    "图片比例",
                    getattr(current, f"{role}_image_aspect_ratio"),
                    GROK_IMAGE_ASPECT_CHOICES,
                ),
                _param_control(
                    f"{provider}_{role}_image_resolution",
                    "图片分辨率",
                    getattr(current, f"{role}_image_resolution"),
                    GROK_IMAGE_RESOLUTION_CHOICES,
                ),
            ]
        return [
            _param_control(
                f"{provider}_{role}_image_size",
                "图片比例/尺寸",
                getattr(current, f"{role}_image_size"),
                IMAGE2_1K_SIZE_CHOICES if model.lower() == "image2" else IMAGE_SIZE_CHOICES,
            )
        ]

    if api == "grok":
        if _is_skyreels_video_model(model):
            return [
                _param_control(f"{provider}_function_video_aspect_ratio", "视频比例", current.function_video_aspect_ratio, SKYREELS_VIDEO_ASPECT_CHOICES),
                _param_control(f"{provider}_function_video_resolution", "视频分辨率", current.function_video_resolution, SKYREELS_VIDEO_RESOLUTION_CHOICES),
                _param_control(f"{provider}_function_video_duration", "片段秒数", current.function_video_duration, SKYREELS_VIDEO_DURATION_CHOICES),
            ]
        return [
            _param_control(f"{provider}_function_video_aspect_ratio", "视频比例", current.function_video_aspect_ratio, GROK_VIDEO_ASPECT_CHOICES),
            _param_control(f"{provider}_function_video_resolution", "视频分辨率", current.function_video_resolution, GROK_VIDEO_RESOLUTION_CHOICES),
            _param_control(f"{provider}_function_video_duration", "片段秒数", current.function_video_duration, GROK_VIDEO_DURATION_CHOICES),
        ]
    return [
        _param_control(f"{provider}_function_video_size", "视频比例/分辨率", current.function_video_size or current.video_size, OMNI_VIDEO_SIZE_CHOICES),
        _param_control(f"{provider}_function_video_duration", "片段秒数", "10", [("10", "10秒")]),
    ]


def _control_value(controls: List[Dict[str, Any]], key_suffix: str, fallback: str = "") -> str:
    for control in controls:
        if control.get("key", "").endswith(key_suffix):
            return str(control.get("value") or fallback)
    return fallback


def _function_option_detail(current: Settings, stage: str, value: str) -> Dict[str, Any]:
    api, model = _split_api_model(value)
    api_label = "RunningHub API" if api == "grok" else "OTU API"
    controls = _function_param_controls(current, stage, value)
    if stage == "characters":
        if api == "grok":
            endpoint = "/openapi/v2/rhart-image-g-2/text-to-image"
        elif _is_async_gpt_image_model(model):
            endpoint = "/v1/videos → /v1/videos/{task_id}"
        else:
            endpoint = "/v1/images/generations"
        params = (
            f"aspectRatio={_control_value(controls, 'image_aspect_ratio')}；resolution={_control_value(controls, 'image_resolution')}"
            if api == "grok"
            else f"size={_control_value(controls, 'image_size')}"
            + ("；异步任务轮询" if _is_async_gpt_image_model(model) else "")
        )
    elif stage == "storyboards":
        if api == "grok":
            endpoint = "/openapi/v2/rhart-image-g-2/image-to-image"
        elif _is_async_gpt_image_model(model):
            endpoint = "/v1/videos → /v1/videos/{task_id}"
        else:
            endpoint = "/v1/images/edits"
        params = (
            f"aspectRatio={_control_value(controls, 'image_aspect_ratio')}；resolution={_control_value(controls, 'image_resolution')}；参考图=产品参考图+当前片段人物图"
            if api == "grok"
            else f"size={_control_value(controls, 'image_size')}；参考图=产品参考图+当前片段人物图"
            + ("；异步任务轮询" if _is_async_gpt_image_model(model) else "")
        )
    else:
        if api == "grok":
            endpoint = "/openapi/v2/skyreels-v4/omni-reference-fast" if _is_skyreels_video_model(model) else "/openapi/v2/rhart-video-g/image-to-video"
            duration_note = (
                f"按片段时长动态计算，最大15s，默认{_control_value(controls, 'video_duration')}s"
                if _is_skyreels_video_model(model)
                else f"按片段时长动态计算，默认{_control_value(controls, 'video_duration')}s"
            )
            params = (
                f"aspectRatio={_control_value(controls, 'video_aspect_ratio')}；"
                f"resolution={_control_value(controls, 'video_resolution')}；"
                f"duration={duration_note}"
            )
        else:
            endpoint = "/v1/videos"
            params = f"size={_control_value(controls, 'video_size')}；duration=10s；参考图=故事版图；prompt=当前片段完整脚本"
    return {"api": api_label, "model": model, "endpoint": endpoint, "params": params, "controls": controls}


def _split_api_model(value: str) -> tuple[str, str]:
    if ":" not in value:
        return "otu", value
    api, model = value.split(":", 1)
    return api.strip() or "otu", model.strip()


def _is_skyreels_video_model(model: str) -> bool:
    return "skyreels" in str(model).lower()


def _is_async_gpt_image_model(model: str) -> bool:
    return str(model).lower() in {"gpt-image-2", "gpt-image-2-2k", "gpt-image-2-4k"}


def _path_field(key: str, env_key: str, label: str, value: Path, kind: str) -> Dict[str, Any]:
    path = Path(str(value)).expanduser()
    exists = path.exists()
    is_dir = path.is_dir()
    parent_exists = path.parent.exists()
    return {
        "key": key,
        "env_key": env_key,
        "label": label,
        "value": str(value),
        "kind": kind,
        "exists": exists,
        "is_dir": is_dir,
        "parent_exists": parent_exists,
        "ok": is_dir if kind == "input" else (is_dir or parent_exists),
    }


def _directory_payload(path: Optional[str] = None) -> Dict[str, Any]:
    target = Path(path).expanduser() if path else Path.home()
    if not target.exists():
        target = _nearest_existing_parent(target)
    if target.is_file():
        target = target.parent
    try:
        current = target.resolve()
    except Exception:
        current = Path.home()

    entries: List[Dict[str, str]] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.lower())
    except Exception:
        children = []
    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            entries.append({"name": child.name, "path": str(child.resolve())})
        except Exception:
            continue

    roots = []
    for root in [Path.home(), Path.home() / "Documents", Path("/Users"), Path("/")]:
        try:
            if root.exists() and root.is_dir():
                value = str(root.resolve())
                if value not in [item["path"] for item in roots]:
                    roots.append({"label": root.name or value, "path": value})
        except Exception:
            continue

    parent = None if current.parent == current else str(current.parent)
    return {
        "current": str(current),
        "parent": parent,
        "entries": entries,
        "roots": roots,
        "can_write": os.access(current, os.W_OK),
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current if current.exists() else Path.home()


def _create_directory(parent: str, name: str) -> Dict[str, Any]:
    clean_name = name.strip()
    if not clean_name or clean_name in {".", ".."} or "/" in clean_name or "\\" in clean_name:
        raise HTTPException(status_code=400, detail="文件夹名称不合法")
    parent_path = Path(parent).expanduser()
    if not parent_path.exists() or not parent_path.is_dir():
        raise HTTPException(status_code=400, detail="上级目录不存在")
    target = parent_path / clean_name
    try:
        target.mkdir(parents=False, exist_ok=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(f"新建文件夹失败：{exc}"))
    return _directory_payload(str(target))


def _active_jobs() -> List[Dict[str, Any]]:
    active = []
    for provider, manager in job_managers.items():
        for job in manager.list_jobs():
            if job.get("status") in {"queued", "running"}:
                active.append({"provider": provider, "id": job.get("id"), "stage": job.get("stage"), "status": job.get("status")})
    return active


def _provider_has_active_job(provider: str) -> bool:
    return any(job["provider"] == provider for job in _active_jobs())


def _job_locked_script_paths(job: Dict[str, Any]) -> tuple[bool, set[Path]]:
    statuses = job.get("script_statuses") or {}
    if statuses:
        locked = {
            Path(str(path)).expanduser().resolve()
            for path, status in statuses.items()
            if str((status or {}).get("status") or "").lower() in {"pending", "queued", "running"}
        }
        return False, locked
    raw_job_paths = job.get("script_paths")
    if raw_job_paths is None:
        return True, set()
    return False, {Path(path).expanduser().resolve() for path in raw_job_paths if path}


def _reload_runtime_settings() -> None:
    global omni_settings, grok_settings, hybrid_omni_settings, settings, job_managers, job_manager
    omni_settings = load_settings("omni")
    grok_settings = load_settings("grok")
    hybrid_omni_settings = load_hybrid_omni_settings()
    settings = omni_settings
    job_managers = {
        "omni": JobManager(omni_settings),
        "grok": JobManager(grok_settings),
        "hybrid_omni": JobManager(hybrid_omni_settings),
    }
    job_manager = job_managers["omni"]
    _clear_catalog_cache()


def _catalog_payload(current: Settings) -> Dict[str, Any]:
    cache_key = current.api_base_path
    with _catalog_cache_lock:
        now = time.monotonic()
        cached = _catalog_cache.get(cache_key)
        if cached is not None and now - cached[0] < CATALOG_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            scripts = scan_scripts(current, include_archived=current.workflow == "standard")
            payload = {
                "summary": summarize_catalog(current, scripts),
                "scripts": [script_to_dict(current, script) for script in scripts],
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_safe(str(exc)))
        _catalog_cache[cache_key] = (time.monotonic(), payload)
        return payload


def _clear_catalog_cache() -> None:
    with _catalog_cache_lock:
        _catalog_cache.clear()


def _run_pipeline(provider: str, request: RunRequest) -> Dict[str, Any]:
    if request.stage not in VALID_STAGES:
        raise HTTPException(status_code=400, detail="未知任务阶段")
    try:
        return _manager_for(provider).start(
            stage=request.stage,
            overwrite=request.overwrite,
            script_paths=request.script_paths,
            script_concurrency=request.script_concurrency,
            reference_images=request.reference_images,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(str(exc)))


def _export_completed(provider: str, request: ExportRequest) -> Dict[str, Any]:
    selected_paths = {Path(path).expanduser().resolve() for path in request.script_paths if path}
    for job in _manager_for(provider).list_jobs():
        if job.get("status") not in {"queued", "running"}:
            continue
        locks_all, active_paths = _job_locked_script_paths(job)
        if locks_all:
            raise HTTPException(status_code=409, detail="当前任务会处理全部脚本，暂不能导出")
        if selected_paths & active_paths:
            raise HTTPException(status_code=409, detail="所选脚本正在运行或排队，请等待任务完成或先取消任务")
    current = _settings_for(provider)
    try:
        scripts = scan_scripts(current)
        if current.workflow == "hybrid_omni":
            return deliver_hybrid_scripts(current, scripts, request.script_paths)
        return export_completed_scripts(current, scripts, request.script_paths)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(str(exc)))


def _restore_exported(provider: str, request: RestoreRequest) -> Dict[str, Any]:
    if _provider_has_active_job(provider):
        raise HTTPException(status_code=409, detail="当前 Agent 有任务正在运行，请先停止或等待完成后再恢复归档")
    current = _settings_for(provider)
    try:
        scripts = scan_scripts(current, include_archived=True)
        if current.workflow == "hybrid_omni":
            return restore_hybrid_deliveries(current, scripts, request.script_paths)
        return restore_exported_scripts(current, scripts, request.script_paths, bool(request.restore_videos))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(str(exc)))


def _delete_scripts(provider: str, request: ScriptDeleteRequest) -> Dict[str, Any]:
    current = _settings_for(provider)
    selected_paths = {Path(path).expanduser().resolve() for path in request.script_paths if path}
    if not selected_paths:
        raise HTTPException(status_code=400, detail="请至少选择一个脚本")

    for job in _manager_for(provider).list_jobs():
        if job.get("status") not in {"queued", "running"}:
            continue
        locks_all, active_paths = _job_locked_script_paths(job)
        if locks_all:
            raise HTTPException(status_code=409, detail="当前任务会处理全部脚本，暂不能删除脚本")
        if selected_paths & active_paths:
            raise HTTPException(status_code=409, detail="所选脚本正在运行或排队，请等待任务完成或先取消任务")

    try:
        scripts = scan_scripts(current)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(f"读取脚本失败：{exc}"))
    scripts_by_path = {script.md_path.resolve(): script for script in scripts}
    missing = selected_paths - scripts_by_path.keys()
    if missing:
        raise HTTPException(status_code=404, detail=f"脚本不存在、已归档或不属于当前 Agent：{next(iter(sorted(missing)))}")

    deletion_plan: List[Path] = []
    for script_path in sorted(selected_paths):
        script = scripts_by_path[script_path]
        for segment in script.segments:
            character_path = character_image_path(script.md_path, segment.index, current.artifact_prefix).resolve()
            storyboard_path = storyboard_image_path(script.md_path, segment.index, current.artifact_prefix).resolve()
            video_path = video_output_path(current, script.product_name, script.md_path, segment.index).resolve()
            deletion_plan.extend(
                [
                    character_path,
                    storyboard_path,
                    storyboard_meta_path(storyboard_path),
                    video_path,
                    storyboard_meta_path(video_path),
                ]
            )

    deleted: List[str] = []
    try:
        for target in dict.fromkeys(deletion_plan):
            if target.exists() and target.is_file():
                target.unlink()
                deleted.append(str(target))
        suppressed = [str(suppress_script(scripts_by_path[path].md_path)) for path in sorted(selected_paths)]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(f"删除脚本及附属文件失败：{exc}"))
    return {
        "scripts_deleted": len(selected_paths),
        "files_deleted": len(deleted),
        "deleted": deleted,
        "suppressed": suppressed,
    }


def _list_jobs(provider: str) -> Dict[str, Any]:
    return {"jobs": _manager_for(provider).list_jobs()}


def _cancel_jobs(provider: str, request: CancelRequest) -> Dict[str, Any]:
    canceled = _manager_for(provider).cancel(request.job_id)
    if request.job_id and not canceled:
        raise HTTPException(status_code=404, detail="没有可停止的运行中任务")
    return {"jobs": canceled}


def _update_job_concurrency(provider: str, request: ConcurrencyRequest) -> Dict[str, Any]:
    try:
        return _manager_for(provider).update_concurrency(request.script_concurrency, request.job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_safe(str(exc)))


def _get_job(provider: str, job_id: str) -> Dict[str, Any]:
    try:
        return _manager_for(provider).get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")


def _artifact(current: Settings, path: str) -> FileResponse:
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not _is_allowed_artifact(current, target):
        raise HTTPException(status_code=403, detail="不允许访问该文件")
    return FileResponse(
        target,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _delete_artifact(current: Settings, request: ArtifactDeleteRequest) -> Dict[str, Any]:
    target = Path(request.path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not _is_deletable_artifact(current, target):
        raise HTTPException(status_code=403, detail="只允许删除人物图、故事版图和视频产物")

    deleted = [str(target)]
    try:
        target.unlink()
        meta_path = storyboard_meta_path(target)
        if meta_path.exists() and meta_path.is_file() and _is_deletable_storyboard_meta(current, meta_path):
            meta_path.unlink()
            deleted.append(str(meta_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(f"删除文件失败：{exc}"))
    return {"deleted": deleted}


def _payload_text(payload: Dict[str, Any], key: str, *, required: bool = True) -> str:
    required = required and key not in OPTIONAL_API_PAYLOAD_KEYS
    value = payload.get(key)
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail=f"{key} 不能为空")
        return ""
    text = str(value).strip()
    if not text and required:
        raise HTTPException(status_code=400, detail=f"{key} 不能为空")
    return text


@app.get("/settings/api/paths")
def get_path_settings() -> Dict[str, Any]:
    return _path_settings_payload()


@app.get("/settings/api/directories")
def browse_directories(path: Optional[str] = Query(None)) -> Dict[str, Any]:
    return _directory_payload(path)


@app.post("/settings/api/directories")
def create_directory(request: DirectoryCreateRequest) -> Dict[str, Any]:
    return _create_directory(request.parent, request.name)


@app.get("/settings/api/apis")
def get_api_settings() -> Dict[str, Any]:
    return _api_settings_payload()


@app.post("/settings/api/paths")
def save_path_settings(request: PathSettingsRequest) -> Dict[str, Any]:
    if _active_jobs():
        raise HTTPException(status_code=409, detail="有任务正在运行，请等待任务结束后再保存路径")
    updates = {
        "SCRIPT_ROOT": request.script_root.strip(),
        "GROK_SCRIPT_ROOT": request.grok_script_root.strip(),
        "HYBRID_OMNI_SCRIPT_ROOT": request.hybrid_omni_script_root.strip(),
        "REFERENCE_ROOT": request.reference_root.strip(),
        "VIDEO_OUTPUT_ROOT": request.video_output_root.strip(),
        "GROK_VIDEO_OUTPUT_ROOT": request.grok_video_output_root.strip(),
        "HYBRID_OMNI_VIDEO_OUTPUT_ROOT": request.hybrid_omni_video_output_root.strip(),
    }
    if any(not value for value in updates.values()):
        raise HTTPException(status_code=400, detail="路径不能为空")
    try:
        update_env_values(updates)
        _reload_runtime_settings()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(str(exc)))
    return _path_settings_payload()


@app.post("/settings/api/apis")
def save_api_settings(request: Dict[str, Any]) -> Dict[str, Any]:
    if _active_jobs():
        raise HTTPException(status_code=409, detail="有任务正在运行，请等待任务结束后再保存 API 设置")
    shared_updates: Dict[str, str] = {}
    secret_updates: Dict[str, str] = {}
    payload_env_map = {
        "omni_character_api_model": "OMNI_CHARACTER_API_MODEL",
        "omni_storyboard_api_model": "OMNI_STORYBOARD_API_MODEL",
        "omni_video_api_model": "OMNI_VIDEO_API_MODEL",
        "grok_character_api_model": "GROK_CHARACTER_API_MODEL",
        "grok_storyboard_api_model": "GROK_STORYBOARD_API_MODEL",
        "grok_video_api_model": "GROK_VIDEO_API_MODEL",
        "omni_character_image_size": "OMNI_CHARACTER_IMAGE_SIZE",
        "omni_character_image_aspect_ratio": "OMNI_CHARACTER_IMAGE_ASPECT_RATIO",
        "omni_character_image_resolution": "OMNI_CHARACTER_IMAGE_RESOLUTION",
        "omni_storyboard_image_size": "OMNI_STORYBOARD_IMAGE_SIZE",
        "omni_storyboard_image_aspect_ratio": "OMNI_STORYBOARD_IMAGE_ASPECT_RATIO",
        "omni_storyboard_image_resolution": "OMNI_STORYBOARD_IMAGE_RESOLUTION",
        "omni_function_video_size": "OMNI_FUNCTION_VIDEO_SIZE",
        "omni_function_video_aspect_ratio": "OMNI_FUNCTION_VIDEO_ASPECT_RATIO",
        "omni_function_video_resolution": "OMNI_FUNCTION_VIDEO_RESOLUTION",
        "omni_function_video_duration": "OMNI_FUNCTION_VIDEO_DURATION",
        "grok_character_image_size": "GROK_CHARACTER_IMAGE_SIZE",
        "grok_character_image_aspect_ratio": "GROK_CHARACTER_IMAGE_ASPECT_RATIO",
        "grok_character_image_resolution": "GROK_CHARACTER_IMAGE_RESOLUTION",
        "grok_storyboard_image_size": "GROK_STORYBOARD_IMAGE_SIZE",
        "grok_storyboard_image_aspect_ratio": "GROK_STORYBOARD_IMAGE_ASPECT_RATIO",
        "grok_storyboard_image_resolution": "GROK_STORYBOARD_IMAGE_RESOLUTION",
        "grok_function_video_size": "GROK_FUNCTION_VIDEO_SIZE",
        "grok_function_video_aspect_ratio": "GROK_FUNCTION_VIDEO_ASPECT_RATIO",
        "grok_function_video_resolution": "GROK_FUNCTION_VIDEO_RESOLUTION",
        "grok_function_video_duration": "GROK_FUNCTION_VIDEO_DURATION",
    }
    for payload_key, env_key in payload_env_map.items():
        value = _payload_text(request, payload_key, required=False)
        if value:
            shared_updates[env_key] = value
    if _payload_text(request, "otu_api_key", required=False):
        secret_updates["OTU_API_KEY"] = _payload_text(request, "otu_api_key", required=False)
    if _payload_text(request, "grok_api_key", required=False):
        secret_updates["GROK_API_KEY"] = _payload_text(request, "grok_api_key", required=False)
    try:
        if shared_updates:
            update_env_values(shared_updates, SETTINGS_PATH)
        if secret_updates:
            update_env_values(secret_updates, ENV_PATH)
        if shared_updates or secret_updates:
            _reload_runtime_settings()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_safe(str(exc)))
    return _api_settings_payload()


@app.get("/api/config")
@app.get("/omni/api/config")
def get_omni_config() -> Dict[str, Any]:
    return _config_payload(omni_settings)


@app.get("/grok/api/config")
def get_grok_config() -> Dict[str, Any]:
    return _config_payload(grok_settings)


@app.get("/hybrid-omni/api/config")
def get_hybrid_omni_config() -> Dict[str, Any]:
    return _config_payload(hybrid_omni_settings)




@app.get("/api/catalog")
@app.get("/omni/api/catalog")
def get_omni_catalog() -> Dict[str, Any]:
    return _catalog_payload(omni_settings)


@app.get("/grok/api/catalog")
def get_grok_catalog() -> Dict[str, Any]:
    return _catalog_payload(grok_settings)


@app.get("/hybrid-omni/api/catalog")
def get_hybrid_omni_catalog() -> Dict[str, Any]:
    return _catalog_payload(hybrid_omni_settings)




@app.post("/api/run")
@app.post("/omni/api/run")
def run_omni_pipeline(request: RunRequest) -> Dict[str, Any]:
    return _run_pipeline("omni", request)


@app.post("/grok/api/run")
def run_grok_pipeline(request: RunRequest) -> Dict[str, Any]:
    return _run_pipeline("grok", request)


@app.post("/hybrid-omni/api/run")
def run_hybrid_omni_pipeline(request: RunRequest) -> Dict[str, Any]:
    return _run_pipeline("hybrid_omni", request)




@app.post("/api/export-completed")
@app.post("/omni/api/export-completed")
def export_omni_completed(request: ExportRequest) -> Dict[str, Any]:
    return _export_completed("omni", request)


@app.post("/grok/api/export-completed")
def export_grok_completed(request: ExportRequest) -> Dict[str, Any]:
    return _export_completed("grok", request)


@app.post("/hybrid-omni/api/export-completed")
def export_hybrid_omni_completed(request: ExportRequest) -> Dict[str, Any]:
    return _export_completed("hybrid_omni", request)




@app.post("/api/restore-exported")
@app.post("/omni/api/restore-exported")
def restore_omni_exported(request: RestoreRequest) -> Dict[str, Any]:
    return _restore_exported("omni", request)


@app.post("/grok/api/restore-exported")
def restore_grok_exported(request: RestoreRequest) -> Dict[str, Any]:
    return _restore_exported("grok", request)


@app.post("/hybrid-omni/api/restore-exported")
def restore_hybrid_omni_exported(request: RestoreRequest) -> Dict[str, Any]:
    return _restore_exported("hybrid_omni", request)


@app.delete("/api/scripts")
@app.delete("/omni/api/scripts")
def delete_omni_scripts(request: ScriptDeleteRequest) -> Dict[str, Any]:
    return _delete_scripts("omni", request)


@app.delete("/grok/api/scripts")
def delete_grok_scripts(request: ScriptDeleteRequest) -> Dict[str, Any]:
    return _delete_scripts("grok", request)


@app.delete("/hybrid-omni/api/scripts")
def delete_hybrid_omni_scripts(request: ScriptDeleteRequest) -> Dict[str, Any]:
    return _delete_scripts("hybrid_omni", request)




@app.post("/api/cancel")
@app.post("/omni/api/cancel")
def cancel_omni_jobs(request: CancelRequest = CancelRequest()) -> Dict[str, Any]:
    return _cancel_jobs("omni", request)


@app.post("/grok/api/cancel")
def cancel_grok_jobs(request: CancelRequest = CancelRequest()) -> Dict[str, Any]:
    return _cancel_jobs("grok", request)


@app.post("/hybrid-omni/api/cancel")
def cancel_hybrid_omni_jobs(request: CancelRequest = CancelRequest()) -> Dict[str, Any]:
    return _cancel_jobs("hybrid_omni", request)




@app.post("/api/jobs/concurrency")
@app.post("/omni/api/jobs/concurrency")
def update_omni_job_concurrency(request: ConcurrencyRequest) -> Dict[str, Any]:
    return _update_job_concurrency("omni", request)


@app.post("/grok/api/jobs/concurrency")
def update_grok_job_concurrency(request: ConcurrencyRequest) -> Dict[str, Any]:
    return _update_job_concurrency("grok", request)


@app.post("/hybrid-omni/api/jobs/concurrency")
def update_hybrid_omni_job_concurrency(request: ConcurrencyRequest) -> Dict[str, Any]:
    return _update_job_concurrency("hybrid_omni", request)




@app.get("/api/jobs")
@app.get("/omni/api/jobs")
def list_omni_jobs() -> Dict[str, Any]:
    return _list_jobs("omni")


@app.get("/grok/api/jobs")
def list_grok_jobs() -> Dict[str, Any]:
    return _list_jobs("grok")


@app.get("/hybrid-omni/api/jobs")
def list_hybrid_omni_jobs() -> Dict[str, Any]:
    return _list_jobs("hybrid_omni")




@app.get("/api/jobs/{job_id}")
@app.get("/omni/api/jobs/{job_id}")
def get_omni_job(job_id: str) -> Dict[str, Any]:
    return _get_job("omni", job_id)


@app.get("/grok/api/jobs/{job_id}")
def get_grok_job(job_id: str) -> Dict[str, Any]:
    return _get_job("grok", job_id)


@app.get("/hybrid-omni/api/jobs/{job_id}")
def get_hybrid_omni_job(job_id: str) -> Dict[str, Any]:
    return _get_job("hybrid_omni", job_id)




@app.get("/api/artifact")
@app.get("/omni/api/artifact")
def omni_artifact(path: str = Query(...)) -> FileResponse:
    return _artifact(omni_settings, path)


@app.get("/grok/api/artifact")
def grok_artifact(path: str = Query(...)) -> FileResponse:
    return _artifact(grok_settings, path)


@app.get("/hybrid-omni/api/artifact")
def hybrid_omni_artifact(path: str = Query(...)) -> FileResponse:
    return _artifact(hybrid_omni_settings, path)




@app.delete("/api/artifact")
@app.delete("/omni/api/artifact")
def delete_omni_artifact(request: ArtifactDeleteRequest) -> Dict[str, Any]:
    return _delete_artifact(omni_settings, request)


@app.delete("/grok/api/artifact")
def delete_grok_artifact(request: ArtifactDeleteRequest) -> Dict[str, Any]:
    return _delete_artifact(grok_settings, request)


@app.delete("/hybrid-omni/api/artifact")
def delete_hybrid_omni_artifact(request: ArtifactDeleteRequest) -> Dict[str, Any]:
    return _delete_artifact(hybrid_omni_settings, request)




def _is_allowed_artifact(current: Settings, target: Path) -> bool:
    for root in current.allowed_artifact_roots:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _is_deletable_artifact(current: Settings, target: Path) -> bool:
    if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"}:
        return False
    name = target.name
    if "-片段" not in name:
        return False
    if not any(token in name for token in ("人物图", "故事版", "omni", "grok")):
        return False
    roots = [
        current.script_root.resolve(),
        current.video_output_root.resolve(),
        current.completed_script_root.resolve(),
        (current.video_output_root.parent / f"11{current.provider}完成脚本导出").resolve(),
    ]
    for root in roots:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _is_deletable_storyboard_meta(current: Settings, target: Path) -> bool:
    if target.suffix.lower() != ".json" or not target.name.endswith(".product-lock.json"):
        return False
    roots = [
        current.script_root.resolve(),
        current.completed_script_root.resolve(),
        (current.video_output_root.parent / f"11{current.provider}完成脚本导出").resolve(),
    ]
    for root in roots:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _safe(text: str) -> str:
    return mask_secrets(text, [*omni_settings.secret_values(), *grok_settings.secret_values()])


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
