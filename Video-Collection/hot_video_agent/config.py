from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(
    os.environ.get(
        "OPC_VIDEO_COLLECTION_CONFIG_PATH",
        str(Path.home() / "Library" / "Application Support" / "OPC-Agent-Suite" / "Video-Collection" / "config.json"),
    )
).expanduser()
LEGACY_CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"


DEFAULT_CONFIG: Dict[str, Any] = {
    "product": {
        "slug": "",
        "name": "",
        "path": "",
    },
    "fastmoss": {
        "phone": "",
        "password": "",
        "keyword": "",
        "country": "马来西亚",
        "category_path": ["全部"],
        "shop_type": "全部",
        "product_types": [],
        "product_status": "在售",
        "creator_conversion_rate_filter": "全部",
        "total_sales_filter": "全部",
        "total_gmv_filter": "全部",
        "sales_7d_filter": "全部",
        "gmv_7d_filter": "全部",
        "creator_count_filter": "全部",
        "commission_rate_filter": "全部",
        "shipping_method_filter": "全部",
        "product_limit": 3,
        "videos_per_product": 5,
        "show_browser": False,
    },
    "download": {
        "enabled": True,
        "source_csv": "",
        "limit": 0,
    },
    "output": {
        "result_folder_name": "results",
    },
}


class ConfigError(RuntimeError):
    pass


def migrate_legacy_config(config_path: Path = CONFIG_PATH) -> bool:
    config_path = Path(config_path)
    if config_path != CONFIG_PATH or config_path.exists() or not LEGACY_CONFIG_PATH.is_file():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LEGACY_CONFIG_PATH, config_path)
    config_path.chmod(0o600)
    return True


def safe_name(value: str, default: str = "untitled", max_length: int = 120) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    return (text[:max_length].strip(" ._") or default)


VIDEO_FILENAME_STEM_MAX = 96
VIDEO_USERNAME_MAX = 24


def video_filename_stem(username: str, video_id: str, title: str) -> str:
    safe_username = safe_name(username, "unknown_user", VIDEO_USERNAME_MAX)
    title_budget = max(16, VIDEO_FILENAME_STEM_MAX - len(safe_username) - len(video_id) - 2)
    safe_title = safe_name(title, "untitled", title_budget)
    return safe_name(
        f"{safe_username}-{video_id}-{safe_title}",
        video_id,
        VIDEO_FILENAME_STEM_MAX,
    )


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = deep_merge(value, {})
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value

    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config_path = Path(config_path)
    migrate_legacy_config(config_path)
    if not config_path.exists():
        data: Dict[str, Any] = {}
    else:
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"配置文件不是合法 JSON: {config_path} ({exc})")
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件顶层必须是 JSON object: {config_path}")

    config = deep_merge(DEFAULT_CONFIG, data)
    fastmoss = config.setdefault("fastmoss", {})
    fastmoss["phone"] = os.environ.get("FASTMOSS_PHONE") or fastmoss.get("phone", "")
    fastmoss["password"] = os.environ.get("FASTMOSS_PASSWORD") or fastmoss.get("password", "")
    return config


def read_config_file(config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config_path = Path(config_path)
    migrate_legacy_config(config_path)
    if not config_path.exists():
        return deep_merge(DEFAULT_CONFIG, {})
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON: {config_path} ({exc})")
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是 JSON object: {config_path}")
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(config: Dict[str, Any], config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config_path = Path(config_path)
    payload = deep_merge(DEFAULT_CONFIG, config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    return payload


def init_config(config_path: Path = CONFIG_PATH, overwrite: bool = False) -> Path:
    config_path = Path(config_path)
    if not overwrite:
        migrate_legacy_config(config_path)
    if config_path.exists() and not overwrite:
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    source = EXAMPLE_CONFIG_PATH
    if source.exists():
        shutil.copyfile(str(source), str(config_path))
    else:
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    config_path.chmod(0o600)
    return config_path


def product_slug(config: Dict[str, Any]) -> str:
    product = config.get("product") or {}
    configured = str(product.get("slug") or "").strip()
    if configured:
        return safe_name(configured, "product", 100)
    configured_path = str(product.get("path") or "").strip()
    if configured_path:
        return safe_name(Path(configured_path).expanduser().name, "product", 100)
    return safe_name(str(product.get("name") or "").strip(), "product", 100)


def validate_config(config: Dict[str, Any], require_credentials: bool = True) -> None:
    fastmoss = config.get("fastmoss") or {}
    if require_credentials and (not fastmoss.get("phone") or not fastmoss.get("password")):
        raise ConfigError("请在 config.json 或环境变量 FASTMOSS_PHONE / FASTMOSS_PASSWORD 里提供 FastMoss 账号密码")

    category_path = fastmoss.get("category_path") or []
    if isinstance(category_path, str):
        category_path = [part.strip() for part in category_path.split(">") if part.strip()]
        fastmoss["category_path"] = category_path
    if not isinstance(category_path, list) or not category_path:
        raise ConfigError("fastmoss.category_path 必须是非空数组，例如 [\"宠物用品\", \"猫狗食品\"] 或 [\"全部\"]")

    for field in ("product_limit", "videos_per_product"):
        try:
            value = int(fastmoss.get(field, 0))
        except (TypeError, ValueError):
            raise ConfigError(f"fastmoss.{field} 必须是整数")
        if value <= 0:
            raise ConfigError(f"fastmoss.{field} 必须大于 0")


def mask_value(value: str, keep: int = 3) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep * 2) + text[-keep:]


def compact_params(config: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    fastmoss = config.get("fastmoss") or {}
    output: Dict[str, Any] = {}
    for key in keys:
        value = fastmoss.get(key)
        output[key] = mask_value(value) if key in {"phone", "password"} else value
    return output
