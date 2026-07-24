#!/usr/bin/env python3
import re
from pathlib import Path

from opc_engine.core.config_store import CONFIG_PATH, LEGACY_CONFIG_PATH, load_app_config


ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "projects"
PRODUCT_IDENTITY_FIELDS = ("product_name", "english_name")


def load_config():
    return load_app_config()


def safe_name(value, default="untitled", max_length=120):
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    return (text[:max_length].strip(" ._") or default)


def product_project_slug(config=None):
    config = config or load_config()
    configured = str(config.get("product_project_slug", "") or "").strip()
    if configured:
        return safe_name(configured, "product_project", 100)

    profile = config.get("product_profile", {}) or {}
    label = (
        profile.get("english_name")
        or profile.get("product_name")
        or profile.get("market")
        or "current_product"
    )
    return safe_name(label, "current_product", 100)


def product_project_root(config=None):
    return PROJECTS_DIR / product_project_slug(config)


def has_product_identity(config=None):
    config = config or load_config()
    profile = config.get("product_profile", {}) or {}
    return any(str(profile.get(field, "") or "").strip() for field in PRODUCT_IDENTITY_FIELDS)


def product_project_ready(config=None):
    config = config or load_config()
    configured = str(config.get("product_project_slug", "") or "").strip()
    if configured == "current_product":
        return False
    if configured:
        return has_product_identity(config) or product_profile_path(config).exists()
    return has_product_identity(config)


def require_product_project(config=None, action="继续操作"):
    if not product_project_ready(config):
        raise SystemExit(f"请先在「产品信息」页面创建并保存产品项目，再{action}")
    return config or load_config()


def ensure_project_dirs(config=None):
    project_root = product_project_root(config)
    for path in [
        project_root,
        project_root / "product_profile",
        project_root / "collection_runs",
        project_root / "hot_sources",
        project_root / "raw_data" / "natural_flow",
        project_root / "raw_data" / "ad_performance",
        project_root / "product_level_reports" / "data_attribution",
        project_root / "product_level_reports" / "script_optimizations",
        project_root / "runtime_state",
        project_root / "diagnostics",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    return project_root


def project_relative(path):
    path = Path(path)
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_project_path(value, default_path=None):
    raw_value = str(value or "").strip()
    if not raw_value and default_path:
        return Path(default_path).expanduser().resolve()
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def product_profile_path(config=None):
    return product_project_root(config) / "product_profile" / "current_product_profile.md"


def runtime_state_path(name, config=None):
    return product_project_root(config) / "runtime_state" / name


def diagnostics_dir(config=None):
    return product_project_root(config) / "diagnostics"


def collection_run_dir(run_stem, config=None):
    return product_project_root(config) / "collection_runs" / safe_name(run_stem, "collection_run")


def collection_csv_path(run_stem, config=None):
    run_dir = collection_run_dir(run_stem, config)
    return run_dir / f"{safe_name(run_stem, 'collection_run')}.csv"


def latest_collection_csv(config=None):
    project_root = product_project_root(config)
    candidates = [path for path in (project_root / "collection_runs").rglob("*.csv") if path.is_file()]
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None


def infer_source_id(value, default="unknown_source"):
    text = str(value or "").strip()
    if not text:
        return default

    path = Path(text)
    parts = list(path.parts)
    if "hot_sources" in parts:
        index = parts.index("hot_sources")
        if index + 1 < len(parts):
            return safe_name(parts[index + 1], default, 120)

    for pattern in [
        r"/video/(\d{10,24})",
        r"(?:video_id|作品ID|Video ID)[^\d]{0,12}(\d{10,24})",
        r"(\d{16,24})",
        r"(\d{10,15})",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    if path.name:
        return safe_name(path.stem, default, 120)
    return default


def source_dir(source_id, config=None):
    return product_project_root(config) / "hot_sources" / safe_name(source_id, "unknown_source", 120)


def source_stage_dir(source_id, stage, config=None):
    path = source_dir(source_id, config) / stage
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_stage_path(source_id, stage, filename, config=None):
    return source_stage_dir(source_id, stage, config) / filename


def product_report_dir(stage, config=None):
    path = product_project_root(config) / "product_level_reports" / stage
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_data_dir(kind, config=None):
    path = product_project_root(config) / "raw_data" / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_id_from_row(row):
    for key in [
        "tiktok_video_url",
        "fastmoss_video_url",
        "video_id",
        "视频ID",
        "作品ID",
        "Video ID",
        "vidoe id",
    ]:
        value = row.get(key) if isinstance(row, dict) else ""
        if value:
            source_id = infer_source_id(value, "")
            if source_id:
                return source_id
    return "unknown_source"


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find unique path for {path}")
