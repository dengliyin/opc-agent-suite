from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, List, Mapping
import re

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
SETTINGS_PATH = PROJECT_ROOT / "agent_settings.env"


load_dotenv(ENV_PATH)
load_dotenv(SETTINGS_PATH, override=True)


DEFAULT_VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__"
).expanduser()
DEFAULT_SCRIPT_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "04适配脚本" / "omni"
DEFAULT_GROK_SCRIPT_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "04适配脚本" / "grok"
DEFAULT_REFERENCE_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "产品" / "产品底图"
DEFAULT_VIDEO_OUTPUT_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "05AI片段" / "omni"
DEFAULT_GROK_VIDEO_OUTPUT_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "05AI片段" / "grok"
DEFAULT_COMPLETED_SCRIPT_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "纯AI视频" / "06合成工作区"
DEFAULT_HYBRID_ROOT = DEFAULT_VAULT_ROOT / "wiki" / "视频" / "AI实拍混剪"
DEFAULT_HYBRID_OMNI_SCRIPT_ROOT = DEFAULT_HYBRID_ROOT / "04适配脚本" / "omni"
DEFAULT_HYBRID_AI_CLIP_ROOT = DEFAULT_HYBRID_ROOT / "05AI片段"
DEFAULT_HYBRID_MIX_WORK_ROOT = DEFAULT_HYBRID_ROOT / "08混剪工作区"
ENV_ASSIGNMENT_RE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=)(.*?)(\r?\n)?$")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 12) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _env_list(name: str, default: List[str]) -> List[str]:
    value = os.getenv(name)
    if value is None:
        return default
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or default


@dataclass(frozen=True)
class Settings:
    provider: str
    provider_label: str
    api_base_path: str
    otu_api_key: str
    otu_base_url: str
    image_model: str
    image_fallback_models: List[str]
    omni_model: str
    grok_api_key: str
    grok_base_url: str
    grok_image_aspect_ratio: str
    grok_image_resolution: str
    grok_video_aspect_ratio: str
    grok_video_resolution: str
    grok_video_duration: int
    image_size: str
    video_size: str
    overwrite: bool
    script_root: Path
    reference_root: Path
    video_output_root: Path
    completed_root: Path | None = None
    script_concurrency: int = 3
    character_api_model: str = ""
    storyboard_api_model: str = ""
    video_api_model: str = ""
    character_image_size: str = ""
    character_image_aspect_ratio: str = ""
    character_image_resolution: str = ""
    storyboard_image_size: str = ""
    storyboard_image_aspect_ratio: str = ""
    storyboard_image_resolution: str = ""
    function_video_size: str = ""
    function_video_aspect_ratio: str = ""
    function_video_resolution: str = ""
    function_video_duration: int = 10
    omni_poll_interval_seconds: float = 5.0
    omni_timeout_seconds: float = 1200.0
    omni_retry_attempts: int = 3
    omni_upstream_retry_attempts: int = 3
    omni_retry_base_seconds: float = 10.0
    image_poll_interval_seconds: float = 5.0
    image_timeout_seconds: float = 1200.0
    image_retry_attempts: int = 3
    image_retry_base_seconds: float = 10.0
    image_reference_max_side: int = 2048
    image_reference_jpeg_quality: int = 88
    grok_poll_interval_seconds: float = 5.0
    grok_timeout_seconds: float = 1200.0
    grok_retry_attempts: int = 3
    grok_retry_base_seconds: float = 10.0
    workflow: str = "standard"

    @property
    def image_generations_url(self) -> str:
        return f"{self.otu_base_url.rstrip('/')}/v1/images/generations"

    @property
    def image_edits_url(self) -> str:
        return f"{self.otu_base_url.rstrip('/')}/v1/images/edits"

    @property
    def video_url(self) -> str:
        return f"{self.otu_base_url.rstrip('/')}/v1/videos"

    @property
    def image_model_candidates(self) -> List[str]:
        candidates = [self.image_model, *self.image_fallback_models]
        unique: List[str] = []
        for model in candidates:
            if model and model not in unique:
                unique.append(model)
        return unique

    @property
    def artifact_prefix(self) -> str:
        return ""

    @property
    def character_display_label(self) -> str:
        return "人物图" if not self.artifact_prefix else f"{self.provider_label}人物图"

    @property
    def storyboard_display_label(self) -> str:
        return "故事版" if not self.artifact_prefix else f"{self.provider_label}故事版"

    @property
    def video_display_label(self) -> str:
        return "Omni 视频" if self.provider == "omni" else f"{self.provider_label} 视频"

    @property
    def provider_ready(self) -> bool:
        return bool(self.grok_api_key) if self.provider == "grok" else bool(self.otu_api_key)

    @property
    def image_display_summary(self) -> str:
        if self.provider == "grok":
            return f"G-2.0 {self.grok_image_resolution} {self.grok_image_aspect_ratio}"
        return f"{' -> '.join(self.image_model_candidates)} {self.image_size}"

    @property
    def video_display_summary(self) -> str:
        selected_video = self.video_api_model or ""
        if selected_video.startswith("grok:"):
            model = selected_video.split(":", 1)[1]
            return f"{model} {self.function_video_resolution or self.grok_video_resolution} {self.function_video_aspect_ratio or self.grok_video_aspect_ratio}"
        if self.provider == "grok":
            return f"X v1.5 {self.grok_video_resolution} {self.grok_video_aspect_ratio}"
        return f"{self.omni_model} {self.video_size}"

    @property
    def has_otu_key(self) -> bool:
        return bool(self.otu_api_key)

    @property
    def allowed_artifact_roots(self) -> List[Path]:
        return [
            self.script_root.resolve(),
            self.reference_root.resolve(),
            self.video_output_root.resolve(),
            self.completed_script_root.resolve(),
            (self.video_output_root.parent / f"11{self.provider}完成脚本导出").resolve(),
        ]

    @property
    def completed_script_root(self) -> Path:
        if self.completed_root is not None:
            pending_root = self.completed_root
        else:
            pending_root = self.video_output_root.parent / "视频片段 （待拼接）"
        return pending_root / self.provider

    def secret_values(self) -> List[str]:
        return [value for value in [self.otu_api_key, self.grok_api_key] if value]


def load_settings(provider: str = "omni") -> Settings:
    load_dotenv(SETTINGS_PATH, override=True)
    provider = provider.strip().lower()
    if provider not in {"omni", "grok"}:
        raise ValueError(f"未知 provider：{provider}")
    script_root = Path(os.getenv("SCRIPT_ROOT", str(DEFAULT_SCRIPT_ROOT))).expanduser()
    video_output_root = DEFAULT_VIDEO_OUTPUT_ROOT
    if provider == "grok":
        script_root = Path(os.getenv("GROK_SCRIPT_ROOT", str(DEFAULT_GROK_SCRIPT_ROOT))).expanduser()
        video_output_root = Path(os.getenv("GROK_VIDEO_OUTPUT_ROOT", str(DEFAULT_GROK_VIDEO_OUTPUT_ROOT)))
    resolved_video_output_root = (
        Path(os.getenv("VIDEO_OUTPUT_ROOT", str(video_output_root))).expanduser()
        if provider == "omni"
        else video_output_root.expanduser()
    )
    provider_labels = {"omni": "Omni", "grok": "Grok"}
    provider_prefixes = {"omni": "OMNI", "grok": "GROK"}
    prefix = provider_prefixes[provider]
    image_model = os.getenv("IMAGE_MODEL", "gpt-image-2-4K")
    image_fallback_models = _env_list("IMAGE_FALLBACK_MODELS", [])
    omni_model = os.getenv("OMNI_MODEL", "omni_flash-10s")
    default_character_api_model = "grok:G-2.0" if provider == "grok" else f"otu:{image_model}"
    default_storyboard_api_model = default_character_api_model
    if provider == "grok":
        default_video_api_model = "grok:X v1.5"
        default_video_duration = int(os.getenv("GROK_VIDEO_DURATION", "10"))
    else:
        default_video_api_model = f"otu:{omni_model}"
        default_video_duration = 10
    video_size = os.getenv("VIDEO_SIZE", "720x1280")
    image_size = os.getenv("IMAGE_SIZE", "4096x3072")
    grok_image_aspect_ratio = os.getenv("GROK_IMAGE_ASPECT_RATIO", "9:16")
    grok_image_resolution = os.getenv("GROK_IMAGE_RESOLUTION", "4k")
    grok_video_aspect_ratio = os.getenv("GROK_VIDEO_ASPECT_RATIO", "9:16")
    grok_video_resolution = os.getenv("GROK_VIDEO_RESOLUTION", "720p")
    return Settings(
        provider=provider,
        provider_label=provider_labels[provider],
        api_base_path=f"/{provider}/api",
        otu_api_key=os.getenv("OTU_API_KEY", ""),
        otu_base_url=os.getenv("OTU_BASE_URL", "https://zexapi.com"),
        image_model=image_model,
        image_fallback_models=image_fallback_models,
        omni_model=omni_model,
        grok_api_key=os.getenv("GROK_API_KEY", ""),
        grok_base_url=os.getenv("GROK_BASE_URL", "https://www.runninghub.cn"),
        grok_image_aspect_ratio=grok_image_aspect_ratio,
        grok_image_resolution=grok_image_resolution,
        grok_video_aspect_ratio=grok_video_aspect_ratio,
        grok_video_resolution=grok_video_resolution,
        grok_video_duration=int(os.getenv("GROK_VIDEO_DURATION", "10")),
        image_size=image_size,
        video_size=video_size,
        overwrite=_env_bool("OVERWRITE", False),
        script_root=script_root,
        reference_root=Path(os.getenv("REFERENCE_ROOT", str(DEFAULT_REFERENCE_ROOT))).expanduser(),
        video_output_root=resolved_video_output_root,
        completed_root=Path(
            os.getenv(
                "VIDEO_ASSEMBLY_PENDING_ROOT",
                str(resolved_video_output_root.parent.parent / "06合成工作区"),
            )
        ).expanduser(),
        script_concurrency=_env_int(f"{prefix}_SCRIPT_CONCURRENCY", _env_int("SCRIPT_CONCURRENCY", 3)),
        character_api_model=os.getenv(f"{prefix}_CHARACTER_API_MODEL", default_character_api_model),
        storyboard_api_model=os.getenv(f"{prefix}_STORYBOARD_API_MODEL", default_storyboard_api_model),
        video_api_model=os.getenv(f"{prefix}_VIDEO_API_MODEL", default_video_api_model),
        character_image_size=os.getenv(f"{prefix}_CHARACTER_IMAGE_SIZE", image_size),
        character_image_aspect_ratio=os.getenv(f"{prefix}_CHARACTER_IMAGE_ASPECT_RATIO", grok_image_aspect_ratio),
        character_image_resolution=os.getenv(f"{prefix}_CHARACTER_IMAGE_RESOLUTION", grok_image_resolution),
        storyboard_image_size=os.getenv(f"{prefix}_STORYBOARD_IMAGE_SIZE", image_size),
        storyboard_image_aspect_ratio=os.getenv(f"{prefix}_STORYBOARD_IMAGE_ASPECT_RATIO", grok_image_aspect_ratio),
        storyboard_image_resolution=os.getenv(f"{prefix}_STORYBOARD_IMAGE_RESOLUTION", grok_image_resolution),
        function_video_size=os.getenv(f"{prefix}_FUNCTION_VIDEO_SIZE", video_size),
        function_video_aspect_ratio=os.getenv(f"{prefix}_FUNCTION_VIDEO_ASPECT_RATIO", grok_video_aspect_ratio),
        function_video_resolution=os.getenv(f"{prefix}_FUNCTION_VIDEO_RESOLUTION", grok_video_resolution),
        function_video_duration=int(os.getenv(f"{prefix}_FUNCTION_VIDEO_DURATION", str(default_video_duration))),
        omni_poll_interval_seconds=float(os.getenv("OMNI_POLL_INTERVAL_SECONDS", "5")),
        omni_timeout_seconds=float(os.getenv("OMNI_TIMEOUT_SECONDS", "1200")),
        omni_retry_attempts=int(os.getenv("OMNI_RETRY_ATTEMPTS", "3")),
        omni_upstream_retry_attempts=int(os.getenv("OMNI_UPSTREAM_RETRY_ATTEMPTS", "3")),
        omni_retry_base_seconds=float(os.getenv("OMNI_RETRY_BASE_SECONDS", "10")),
        image_poll_interval_seconds=float(os.getenv("IMAGE_POLL_INTERVAL_SECONDS", "5")),
        image_timeout_seconds=float(os.getenv("IMAGE_TIMEOUT_SECONDS", "1200")),
        image_retry_attempts=int(os.getenv("IMAGE_RETRY_ATTEMPTS", "3")),
        image_retry_base_seconds=float(os.getenv("IMAGE_RETRY_BASE_SECONDS", "10")),
        image_reference_max_side=int(os.getenv("IMAGE_REFERENCE_MAX_SIDE", "2048")),
        image_reference_jpeg_quality=int(os.getenv("IMAGE_REFERENCE_JPEG_QUALITY", "88")),
        grok_poll_interval_seconds=float(os.getenv("GROK_POLL_INTERVAL_SECONDS", "5")),
        grok_timeout_seconds=float(os.getenv("GROK_TIMEOUT_SECONDS", "1200")),
        grok_retry_attempts=int(os.getenv("GROK_RETRY_ATTEMPTS", "3")),
        grok_retry_base_seconds=float(os.getenv("GROK_RETRY_BASE_SECONDS", "10")),
    )


def load_hybrid_omni_settings() -> Settings:
    base = load_settings("omni")
    ai_clip_root = Path(
        os.getenv("HYBRID_AI_CLIP_ROOT", str(DEFAULT_HYBRID_AI_CLIP_ROOT))
    ).expanduser()
    video_output_root = Path(
        os.getenv("HYBRID_OMNI_VIDEO_OUTPUT_ROOT", str(ai_clip_root / "omni"))
    ).expanduser()
    hybrid_root = video_output_root.parent.parent
    return replace(
        base,
        provider_label="混剪 Omni",
        api_base_path="/hybrid-omni/api",
        script_root=Path(
            os.getenv("HYBRID_OMNI_SCRIPT_ROOT", str(DEFAULT_HYBRID_OMNI_SCRIPT_ROOT))
        ).expanduser(),
        video_output_root=video_output_root,
        completed_root=hybrid_root / "08混剪工作区" / "片段产出归档",
        workflow="hybrid_omni",
    )


def mask_secrets(text: str, secrets: Iterable[str]) -> str:
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "***")
    return masked


def update_env_values(updates: Mapping[str, str], env_path: Path = ENV_PATH) -> None:
    existing = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []
    seen = set()
    lines = []

    for line in existing:
        match = ENV_ASSIGNMENT_RE.match(line)
        if not match:
            lines.append(line)
            continue
        prefix, key, equals, _value, newline = match.groups()
        if key not in updates:
            lines.append(line)
            continue
        linebreak = newline or "\n"
        lines.append(f"{prefix}{key}{equals}{_format_env_value(updates[key])}{linebreak}")
        seen.add(key)

    missing = [key for key in updates if key not in seen]
    if missing and lines and not lines[-1].endswith(("\n", "\r\n")):
        lines[-1] = f"{lines[-1]}\n"
    for key in missing:
        lines.append(f"{key}={_format_env_value(updates[key])}\n")

    env_path.write_text("".join(lines), encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value
    load_dotenv(env_path, override=True)


def _format_env_value(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
