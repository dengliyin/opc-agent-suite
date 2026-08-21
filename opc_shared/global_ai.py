from __future__ import annotations

import os
import re
from pathlib import Path


GLOBAL_ENV_PATH = Path(os.environ.get("OPC_ENV_FILE", "/config/.env")).expanduser()
_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$"
)


PROFILE_FIELDS = {
    "video_analysis": {
        "base_url": ("OPC_VIDEO_ANALYSIS_API_BASE_URL", "https://zexapi.com"),
        "model": ("OPC_VIDEO_ANALYSIS_MODEL", "gemini-3.5-flash"),
        "api_key": ("OPC_VIDEO_ANALYSIS_API_KEY", ""),
    },
    "text": {
        "base_url": ("OPC_TEXT_API_BASE_URL", "https://api.deepseek.com"),
        "model": ("OPC_TEXT_MODEL", "deepseek-v4-pro"),
        "api_key": ("OPC_TEXT_API_KEY", ""),
    },
    "otu": {
        "base_url": ("OTU_BASE_URL", "https://zexapi.com"),
        "image_model": ("IMAGE_MODEL", "gpt-image-2-4K"),
        "video_model": ("OMNI_MODEL", "omni_flash-10s"),
        "api_key": ("OTU_API_KEY", ""),
    },
    "grok": {
        "base_url": ("GROK_BASE_URL", "https://www.runninghub.cn"),
        "image_model": ("GROK_IMAGE_MODEL", "G-2.0"),
        "video_model": ("GROK_VIDEO_MODEL", "X v1.5"),
        "api_key": ("GROK_API_KEY", ""),
    },
}

_LEGACY_KEY_FALLBACKS = {
    ("video_analysis", "api_key"): (
        "VIDEO_TEARDOWN_AGENT_API_KEY",
        "MODELMESH_API_KEY",
        "GEMINI_API_KEY",
    ),
    ("text", "api_key"): ("DEEPSEEK_API_KEY", "MODELMESH_API_KEY", "GEMINI_API_KEY"),
}


def read_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or Path(os.environ.get("OPC_ENV_FILE", str(GLOBAL_ENV_PATH))).expanduser()
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _first_value(*names: str, file_values: dict[str, str]) -> str:
    for name in names:
        value = str(file_values.get(name) or os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def load_profile(name: str, path: Path | None = None) -> dict[str, str]:
    if name not in PROFILE_FIELDS:
        raise ValueError(f"未知全局 AI 配置组: {name}")
    file_values = read_env_file(path)
    result: dict[str, str] = {}
    runtime_prefix = f"OPC_RUNTIME_{name.upper()}_"
    for field, (env_name, default) in PROFILE_FIELDS[name].items():
        runtime_name = f"{runtime_prefix}{field.upper()}"
        value = str(os.environ.get(runtime_name) or "").strip()
        if not value:
            value = _first_value(env_name, file_values=file_values)
        if not value:
            value = _first_value(
                *_LEGACY_KEY_FALLBACKS.get((name, field), ()),
                file_values=file_values,
            )
        result[field] = value or default
    return result


def set_runtime_overrides(name: str, values: dict[str, object]) -> None:
    if name not in PROFILE_FIELDS:
        raise ValueError(f"未知全局 AI 配置组: {name}")
    allowed = set(PROFILE_FIELDS[name])
    for field, raw_value in values.items():
        if field not in allowed:
            continue
        value = str(raw_value or "").strip()
        env_name = f"OPC_RUNTIME_{name.upper()}_{field.upper()}"
        if value:
            os.environ[env_name] = value
        else:
            os.environ.pop(env_name, None)


def runtime_override_active(name: str) -> bool:
    prefix = f"OPC_RUNTIME_{name.upper()}_"
    return any(key.startswith(prefix) and value for key, value in os.environ.items())
