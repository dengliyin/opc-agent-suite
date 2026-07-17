from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .publish_queue import PublishQueue


HOST = "127.0.0.1"
DEFAULT_PORT = 9996
BITBROWSER_API = "http://127.0.0.1:54345"
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video"
TIKTOK_UPLOAD_FALLBACK_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT / "data"
PUBLISH_CONFIG_PATH = DATA_ROOT / "publish_config.json"
PRODUCT_MAPPINGS_PATH = APP_ROOT / "config" / "product_mappings.json"
PUBLISH_RECORDS_PATH = DATA_ROOT / "publish_records.json"
PUBLISH_QUEUE_PATH = DATA_ROOT / "publish_queue.sqlite3"
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault"))
).expanduser()
FINISHED_VIDEO_ROOT = VAULT_ROOT / "wiki" / "视频" / "成品视频"
TITLE_LIBRARY_ROOT = VAULT_ROOT / "wiki" / "视频" / "视频标题库"
PRODUCT_INFO_ROOT = VAULT_ROOT / "wiki" / "产品" / "产品信息"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
PUBLISH_LOCK = threading.Lock()
PUBLISH_QUEUE: PublishQueue | None = None
COUNTRY_NAMES = {
    "US": "美国",
    "UK": "英国",
    "GB": "英国",
    "TH": "泰国",
    "BR": "巴西",
    "VN": "越南",
    "ID": "印度尼西亚",
    "MY": "马来西亚",
    "PH": "菲律宾",
    "SG": "新加坡",
    "JP": "日本",
    "MX": "墨西哥",
    "ES": "西班牙",
    "DE": "德国",
    "FR": "法国",
    "IT": "意大利",
    "IE": "爱尔兰",
}
DEFAULT_PUBLISH_CONFIG = {
    "accounts": {},
    "product_links_by_store": {},
    "product_short_names": {},
    "defaults": {
        "ai_generated": True,
        "visibility": "public",
    },
    "daily_kpis": {
        "target_per_account": 3,
    },
}
DEFAULT_PRODUCT_MAPPINGS = {
    "product_links_by_store": {},
    "product_short_names": {},
    "product_links": {},
}


def read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def ensure_local_data_files() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if not PUBLISH_CONFIG_PATH.exists():
        PUBLISH_CONFIG_PATH.write_text(json.dumps(DEFAULT_PUBLISH_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not PUBLISH_RECORDS_PATH.exists():
        PUBLISH_RECORDS_PATH.write_text("[]\n", encoding="utf-8")


def load_publish_config() -> dict[str, Any]:
    ensure_local_data_files()
    config = read_json_file(PUBLISH_CONFIG_PATH, DEFAULT_PUBLISH_CONFIG)
    if not isinstance(config, dict):
        config = dict(DEFAULT_PUBLISH_CONFIG)
    mappings = read_json_file(PRODUCT_MAPPINGS_PATH, DEFAULT_PRODUCT_MAPPINGS)
    if isinstance(mappings, dict):
        for key in DEFAULT_PRODUCT_MAPPINGS:
            if key in mappings:
                config[key] = mappings[key]
    return config


def load_publish_records() -> list[dict[str, Any]]:
    ensure_local_data_files()
    records = read_json_file(PUBLISH_RECORDS_PATH, [])
    return records if isinstance(records, list) else []


def write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_publish_config(config: dict[str, Any]) -> None:
    mappings = {key: config.get(key) or {} for key in DEFAULT_PRODUCT_MAPPINGS}
    local_config = {key: value for key, value in config.items() if key not in DEFAULT_PRODUCT_MAPPINGS}
    write_json_file(PRODUCT_MAPPINGS_PATH, mappings)
    write_json_file(PUBLISH_CONFIG_PATH, local_config)


def save_publish_records(records: list[dict[str, Any]]) -> None:
    write_json_file(PUBLISH_RECORDS_PATH, records)


def parse_bitbrowser_profile_name(name: str) -> dict[str, str]:
    parts = [part.strip() for part in str(name or "").split("-", 4)]
    country = parts[0].upper() if len(parts) > 0 else ""
    shop_name = parts[1] if len(parts) > 1 else ""
    shop_type = parts[2] if len(parts) > 2 else ""
    account_type = parts[3] if len(parts) > 3 else ""
    account_name = parts[4] if len(parts) > 4 else ""
    store_name = "-".join(part for part in [shop_name, shop_type] if part)
    return {
        "country": country,
        "shop_name": shop_name,
        "shop_type": shop_type,
        "store_name": store_name,
        "account_type": account_type,
        "account_name": account_name,
    }


def flatten_product_id_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    short_names = config.get("product_short_names") or {}
    for product_code, countries in sorted((config.get("product_links_by_store") or {}).items()):
        if not isinstance(countries, dict):
            continue
        for country, stores in sorted(countries.items()):
            if not isinstance(stores, dict):
                continue
            for store_name, account_types in sorted(stores.items()):
                if not isinstance(account_types, dict):
                    continue
                for account_type, product_id in sorted(account_types.items()):
                    label = "全部账号类型" if account_type == "*" else account_type
                    rows.append(
                        {
                            "product_code": product_code,
                            "country": country,
                            "store_name": store_name,
                            "account_type": account_type,
                            "account_type_label": label,
                            "product_id": str(product_id),
                            "product_short_name": str(((short_names.get(product_code) or {}).get(country)) or ""),
                        }
                    )
    for product_code, countries in sorted((config.get("product_links") or {}).items()):
        if not isinstance(countries, dict):
            continue
        for country, profiles in sorted(countries.items()):
            if not isinstance(profiles, dict):
                continue
            for profile_id, product_id in sorted(profiles.items()):
                rows.append(
                    {
                        "product_code": product_code,
                        "country": country,
                        "store_name": "",
                        "account_type": "",
                        "account_type_label": "旧窗口映射",
                        "profile_id": profile_id,
                        "product_id": str(product_id),
                        "product_short_name": str(((short_names.get(product_code) or {}).get(country)) or ""),
                    }
                )
    return rows


def load_product_info_catalog() -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    if not PRODUCT_INFO_ROOT.exists():
        return products
    for path in PRODUCT_INFO_ROOT.glob("*.md"):
        if path.name.startswith("_"):
            continue
        stem = re.sub(r"-产品信息$", "", path.stem).strip()
        code, separator, name = stem.partition("-")
        if not separator or not code.strip() or not name.strip():
            continue
        products.append({"code": code.strip().upper(), "name": name.strip()})
    products.sort(key=lambda product: (product["code"], product["name"].casefold()))
    return products


def product_ids_payload() -> dict[str, Any]:
    config = load_publish_config()
    return {
        "config_path": PRODUCT_MAPPINGS_PATH.as_posix(),
        "product_info_root": PRODUCT_INFO_ROOT.as_posix(),
        "products": load_product_info_catalog(),
        "accounts": config.get("accounts") or {},
        "defaults": config.get("defaults") or {},
        "rows": flatten_product_id_rows(config),
    }


def upsert_product_id(payload: dict[str, Any]) -> dict[str, Any]:
    product_code = str(payload.get("product_code", "")).strip().upper()
    country = str(payload.get("country", "")).strip().upper()
    store_name = str(payload.get("store_name", "")).strip()
    account_type = str(payload.get("account_type", "")).strip() or "*"
    product_id = str(payload.get("product_id", "")).strip()
    product_short_name = str(payload.get("product_short_name", "")).strip()
    if not product_code or not country or not store_name or not product_id:
        raise ValueError("产品代码、国家、店铺名称和商品 ID 都必须填写")
    if len(product_short_name) > 30:
        raise ValueError("商品简称不能超过 30 个字符")
    config = load_publish_config()
    product_links = config.setdefault("product_links_by_store", {})
    product_links.setdefault(product_code, {}).setdefault(country, {}).setdefault(store_name, {})[account_type] = product_id
    short_names = config.setdefault("product_short_names", {})
    if product_short_name:
        short_names.setdefault(product_code, {})[country] = product_short_name
    save_publish_config(config)
    return {
        "ok": True,
        "row": {
            "product_code": product_code,
            "country": country,
            "store_name": store_name,
            "account_type": account_type,
            "product_id": product_id,
            "product_short_name": product_short_name,
        },
    }


def delete_product_id(payload: dict[str, Any]) -> dict[str, Any]:
    product_code = str(payload.get("product_code", "")).strip().upper()
    country = str(payload.get("country", "")).strip().upper()
    store_name = str(payload.get("store_name", "")).strip()
    account_type = str(payload.get("account_type", "")).strip() or "*"
    config = load_publish_config()
    product_links = config.get("product_links_by_store") or {}
    try:
        del product_links[product_code][country][store_name][account_type]
        if not product_links[product_code][country][store_name]:
            del product_links[product_code][country][store_name]
        if not product_links[product_code][country]:
            del product_links[product_code][country]
        if not product_links[product_code]:
            del product_links[product_code]
    except KeyError as exc:
        raise ValueError("这条商品 ID 映射不存在") from exc
    save_publish_config(config)
    return {"ok": True}


def records_payload() -> dict[str, Any]:
    return {
        "records_path": PUBLISH_RECORDS_PATH.as_posix(),
        "records": load_publish_records(),
    }


def delete_publish_record(payload: dict[str, Any]) -> dict[str, Any]:
    index = int(payload.get("index", -1))
    records = load_publish_records()
    if index < 0 or index >= len(records):
        raise ValueError("发布记录序号无效")
    removed = records.pop(index)
    save_publish_records(records)
    return {"ok": True, "removed": removed}


def normalize_daily_kpi_date(value: str = "") -> str:
    selected = value.strip() or datetime.now().astimezone().strftime("%Y-%m-%d")
    try:
        return datetime.strptime(selected, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期格式必须是 YYYY-MM-DD") from exc


def daily_kpi_target(config: dict[str, Any]) -> int:
    value = (config.get("daily_kpis") or {}).get("target_per_account", 3)
    try:
        target = int(value)
    except (TypeError, ValueError):
        target = 3
    return max(1, min(target, 100))


def build_daily_kpi_rows(
    profiles: list[dict[str, Any]],
    records: list[dict[str, Any]],
    selected_date: str,
    target: int,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "published":
            continue
        if str(record.get("published_at", ""))[:10] != selected_date:
            continue
        profile_id = str(record.get("profile_id", "")).strip()
        if profile_id:
            counts[profile_id] = counts.get(profile_id, 0) + 1

    rows: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = str(profile.get("id", "")).strip()
        if not profile_id:
            continue
        published = counts.get(profile_id, 0)
        remaining = max(0, target - published)
        rows.append(
            {
                **profile,
                "id": profile_id,
                "published": published,
                "target": target,
                "remaining": remaining,
                "completion_rate": round((published / target) * 100, 1),
                "met": published >= target,
            }
        )
    rows.sort(
        key=lambda row: (
            bool(row["met"]),
            str(row.get("country", "")),
            str(row.get("store_name", "")),
            str(row.get("account_type", "")),
            str(row.get("name", "")),
        )
    )
    account_count = len(rows)
    met_count = sum(1 for row in rows if row["met"])
    total_published = sum(int(row["published"]) for row in rows)
    total_target = account_count * target
    return {
        "rows": rows,
        "summary": {
            "account_count": account_count,
            "met_count": met_count,
            "unmet_count": account_count - met_count,
            "total_published": total_published,
            "total_target": total_target,
            "completion_rate": round((total_published / total_target) * 100, 1) if total_target else 0,
        },
    }


def daily_kpis_payload(date_value: str = "") -> dict[str, Any]:
    selected_date = normalize_daily_kpi_date(date_value)
    config = load_publish_config()
    records = load_publish_records()
    warning = ""
    try:
        live_profiles = list_bitbrowser_profiles().get("profiles", [])
    except Exception as exc:
        live_profiles = None
        warning = f"读取比特浏览器窗口失败，当前显示已保存账号和历史账号：{exc}"

    profiles_by_id: dict[str, dict[str, Any]] = {}

    def add_profile(profile_id: str, data: dict[str, Any], live: bool) -> None:
        profile_id = profile_id.strip()
        if not profile_id:
            return
        name = str(data.get("name") or data.get("account_name") or profile_id)
        parsed = parse_bitbrowser_profile_name(name)
        row = {
            "id": profile_id,
            "seq": data.get("seq"),
            "name": name,
            "country": str(data.get("country") or parsed["country"]),
            "store_name": str(data.get("store_name") or parsed["store_name"]),
            "account_type": str(data.get("account_type") or parsed["account_type"]),
            "account_name": str(data.get("account_name") or parsed["account_name"]),
            "live": live,
        }
        if profile_id not in profiles_by_id or live:
            profiles_by_id[profile_id] = row

    for profile in live_profiles or []:
        add_profile(str(profile.get("id", "")), profile, True)
    if live_profiles is None:
        for profile_id, account in (config.get("accounts") or {}).items():
            if isinstance(account, dict):
                add_profile(str(profile_id), account, False)
        for record in records:
            if not isinstance(record, dict):
                continue
            add_profile(
                str(record.get("profile_id", "")),
                {
                    "name": record.get("account_name", ""),
                    "country": record.get("country", ""),
                    "store_name": record.get("store_name", ""),
                    "account_type": record.get("account_type", ""),
                },
                False,
            )

    target = daily_kpi_target(config)
    result = build_daily_kpi_rows(list(profiles_by_id.values()), records, selected_date, target)
    daily_records = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or str(record.get("published_at", ""))[:10] != selected_date:
            continue
        video_name = str(record.get("video_name", "")).strip()
        if not video_name:
            video_name = Path(str(record.get("video_path", ""))).name
        daily_records.append({**record, "record_index": index, "video_name": video_name})
    daily_records.sort(key=lambda record: str(record.get("published_at", "")), reverse=True)
    return {
        "date": selected_date,
        "target_per_account": target,
        "countries": sorted({str(row.get("country", "")) for row in result["rows"] if row.get("country")}),
        "warning": warning,
        "records": daily_records,
        **result,
    }


def save_daily_kpi_settings(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        target = int(payload.get("target_per_account", 3))
    except (TypeError, ValueError) as exc:
        raise ValueError("日发布目标必须是整数") from exc
    if target < 1 or target > 100:
        raise ValueError("日发布目标必须在 1 到 100 之间")
    config = load_publish_config()
    config.setdefault("daily_kpis", {})["target_per_account"] = target
    save_publish_config(config)
    return {"ok": True, "target_per_account": target}


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


def safe_video_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = FINISHED_VIDEO_ROOT / path
    path = path.resolve()
    root = FINISHED_VIDEO_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("视频路径不在成品视频目录内") from exc
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("不支持的视频文件类型")
    return path


def video_identity(path: Path) -> tuple[str, str]:
    return path.parent.name.casefold(), path.name.casefold()


def resolve_finished_video_path(value: str) -> str:
    path = safe_video_path(value)
    identity = video_identity(path)
    flat_path = FINISHED_VIDEO_ROOT / path.parent.name / path.name
    if flat_path.is_file():
        return flat_path.resolve().as_posix()
    if path.is_file():
        return path.as_posix()
    match = next(
        (
            candidate
            for candidate in FINISHED_VIDEO_ROOT.rglob(path.name)
            if candidate.is_file() and video_identity(candidate) == identity
        ),
        None,
    )
    return (match.resolve() if match else path).as_posix()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    body = handler.rfile.read(length)
    return json.loads(body.decode("utf-8"))


def bitbrowser_post(path: str, payload: dict[str, Any], timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(
        BITBROWSER_API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def bitbrowser_open_payload(profile_id: str, execution_mode: str = "visible") -> dict[str, Any]:
    if execution_mode == "visible":
        return {"id": profile_id}
    if execution_mode == "headless":
        return {
            "id": profile_id,
            "args": ["--headless"],
            "queue": True,
            "ignoreDefaultUrls": True,
        }
    raise ValueError("不支持的执行方式")


def list_bitbrowser_profiles() -> dict[str, Any]:
    result = bitbrowser_post("/browser/list", {"page": 0, "pageSize": 100})
    if not result.get("success"):
        raise RuntimeError(result.get("msg") or "读取比特浏览器窗口失败")
    data = result.get("data") or {}
    profiles = []
    for item in data.get("list") or []:
        name = item.get("name", "") or item.get("code", "") or item.get("id", "")
        parsed_name = parse_bitbrowser_profile_name(name)
        profiles.append(
            {
                "id": item.get("id", ""),
                "seq": item.get("seq"),
                "code": item.get("code", ""),
                "name": name,
                "platform": item.get("platform", ""),
                "url": item.get("url", ""),
                **parsed_name,
            }
        )
    profiles.sort(
        key=lambda profile: (
            re.fullmatch(r"[A-Z]{2}", str(profile.get("country", ""))) is None,
            str(profile.get("country", ""))
            if re.fullmatch(r"[A-Z]{2}", str(profile.get("country", "")))
            else "",
            -int(profile["seq"]) if str(profile.get("seq", "")).isdigit() else 0,
            str(profile.get("name", "")).casefold(),
        )
    )
    return {"profiles": profiles, "total": data.get("totalNum", len(profiles))}


def published_record_by_path(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    published: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("status") != "published":
            continue
        video_path = str(record.get("video_path", ""))
        if video_path:
            published[video_path] = record
    return published


def product_id_for_account(config: dict[str, Any], product_code: str, country: str, account: dict[str, Any]) -> str:
    store_name = str(account.get("store_name", ""))
    account_type = str(account.get("account_type", ""))
    product_links_by_store = config.get("product_links_by_store") or {}
    store_links = ((product_links_by_store.get(product_code) or {}).get(country) or {}).get(store_name) or {}
    if account_type and store_links.get(account_type):
        return str(store_links.get(account_type) or "")
    if store_links.get("*"):
        return str(store_links.get("*") or "")
    return ""


def product_id_for(config: dict[str, Any], product_code: str, country: str, profile_id: str) -> str:
    account = (config.get("accounts") or {}).get(profile_id) or {}
    product_id = product_id_for_account(config, product_code, country, account)
    if product_id:
        return product_id
    product_links = config.get("product_links") or {}
    return str(((product_links.get(product_code) or {}).get(country) or {}).get(profile_id) or "")


def normalize_cdp_endpoint(value: str) -> str:
    if not value:
        return ""
    if value.startswith(("http://", "https://", "ws://", "wss://")):
        return value
    return "http://" + value


def find_tiktok_upload_page(context: Any) -> Any | None:
    pages = [
        page
        for page in context.pages
        if "tiktok" in page.url.lower() and "upload" in page.url.lower()
    ]
    for page in reversed(pages):
        try:
            if (
                page.locator('[data-e2e="caption_container"]').count() > 0
                or page.locator('[data-e2e="upload_status_container"]').count() > 0
            ):
                return page
        except Exception:
            continue
    return pages[-1] if pages else None


def visible_tiktok_caption_input(page: Any) -> Any | None:
    selectors = [
        '[data-e2e="caption_container"] [contenteditable="true"][role="combobox"]',
        '[data-e2e="caption-input"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="caption"]',
        'textarea',
    ]
    for selector in selectors:
        try:
            candidates = page.locator(selector)
            if candidates.count() > 0 and candidates.first.is_visible():
                return candidates.first
        except Exception:
            continue
    return None


def fill_tiktok_caption(page: Any, caption: str) -> bool:
    if not caption:
        return False
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        locator = visible_tiktok_caption_input(page)
        if locator:
            break
        page.wait_for_timeout(500)
    else:
        return False

    hashtags = re.findall(r"(?<!\S)#[^\s#]+", caption)
    plain_text = re.sub(r"(?<!\S)#[^\s#]+", "", caption)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    if not replace_caption_text(page, locator, plain_text):
        return False

    for hashtag in hashtags:
        locator = visible_tiktok_caption_input(page)
        if not locator:
            return False
        focus_tiktok_caption_end(locator)
        if caption_text(locator):
            page.keyboard.press("Space")
        page.keyboard.type(hashtag, delay=40)
        if not select_tiktok_hashtag_suggestion(page, locator, hashtag):
            return False

    expected = re.sub(r"\s+", " ", caption).strip()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        locator = visible_tiktok_caption_input(page)
        if locator and captions_match(caption_text(locator), expected) and tiktok_hashtags_are_mentions(locator, hashtags):
            return True
        page.wait_for_timeout(250)
    return False


def focus_tiktok_caption_end(locator: Any) -> None:
    locator.evaluate(
        """el => {
            el.focus();
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            range.collapse(false);
            selection.removeAllRanges();
            selection.addRange(range);
        }"""
    )


def select_tiktok_hashtag_suggestion(page: Any, locator: Any, hashtag: str) -> bool:
    existing_count = locator.locator('[data-testid="mentionText"]').count()
    candidates = [hashtag]
    if hashtag.casefold() != hashtag:
        candidates.append(hashtag.casefold())

    for candidate_index, candidate in enumerate(candidates):
        if candidate_index:
            focus_tiktok_caption_end(locator)
            for _ in hashtag:
                page.keyboard.press("Backspace")
            page.keyboard.type(candidate, delay=40)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            options = page.locator('[role="option"].hashtag-suggestion-item')
            for index in range(options.count()):
                option = options.nth(index)
                if not option.is_visible():
                    continue
                topic = option.locator('.hash-tag-topic')
                if topic.count() != 1 or topic.first.inner_text().strip().casefold() != candidate.casefold():
                    continue
                option.click(force=True, timeout=5000)
                page.wait_for_timeout(300)
                if locator.locator('[data-testid="mentionText"]').count() > existing_count:
                    return True
            page.wait_for_timeout(250)
    return False


def tiktok_hashtags_are_mentions(locator: Any, hashtags: list[str]) -> bool:
    if not hashtags:
        return True
    mentions = [
        re.sub(r"\s+", " ", value).strip().casefold()
        for value in locator.locator('[data-testid="mentionText"]').all_inner_texts()
    ]
    return all(hashtag.casefold() in mentions for hashtag in hashtags)


def caption_text(locator: Any) -> str:
    return locator.evaluate(
        """el => {
            const value = 'value' in el ? el.value : el.innerText;
            return (value || '').replace(/\\s+/g, ' ').trim();
        }"""
    )


def captions_match(actual: str, expected: str) -> bool:
    def normalize(value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        return re.sub(r"(?<!\S)#[^\s#]+", lambda match: match.group(0).casefold(), value)

    return normalize(actual) == normalize(expected)


def replace_caption_text(page: Any, locator: Any, caption: str) -> bool:
    expected = re.sub(r"\s+", " ", caption).strip()

    def normalize_selection(value: str) -> str:
        value = re.sub(r"[\u200b-\u200d\ufeff]", "", value)
        return re.sub(r"\s+", " ", value).strip()

    try:
        is_contenteditable = bool(locator.evaluate("el => el.isContentEditable"))
    except Exception:
        return False

    if not is_contenteditable:
        try:
            locator.fill(caption, timeout=5000)
            return caption_text(locator) == expected
        except Exception:
            return False

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if locator.locator('[data-contents="true"]').count() > 0:
                break
        except Exception:
            pass
        page.wait_for_timeout(250)
    else:
        return False

    for _ in range(2):
        try:
            locator.click(timeout=5000)
            current = caption_text(locator)
            platform = str(locator.evaluate("el => navigator.platform || ''"))
            shortcut = "Meta+A" if platform.casefold().startswith("mac") else "Control+A"
            page.keyboard.press(shortcut)
            selected_text = locator.evaluate(
                "el => el.contains(window.getSelection().anchorNode) ? window.getSelection().toString() : ''"
            )
            selected_all = normalize_selection(selected_text) == normalize_selection(current)
            if not selected_all:
                selected_text = locator.evaluate(
                    """el => {
                        const selection = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(el);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        return selection.toString();
                    }"""
                )
                selected_all = normalize_selection(selected_text) == normalize_selection(current)
            if not selected_all:
                return False
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(caption)
            page.wait_for_timeout(300)
            if caption_text(locator) == expected:
                return True
        except Exception:
            pass
        page.wait_for_timeout(300)
    return False


def select_tiktok_video(page: Any, video_path: Path) -> str:
    direct_selectors = [
        'input[type="file"][accept*="video"]',
        'input[type="file"][accept*=".mp4"]',
        'input[type="file"]',
    ]
    for selector in direct_selectors:
        try:
            inputs = page.locator(selector)
            count = inputs.count()
        except Exception:
            continue
        for index in range(count):
            try:
                inputs.nth(index).set_input_files(video_path.as_posix(), timeout=8000)
                return f"input:{selector}:{index}"
            except Exception:
                continue

    button_selectors = [
        '[data-e2e="select_video_button"]',
        'button:has-text("选择视频")',
        'button:has-text("เลือกวิดีโอ")',
        'button:has-text("Select video")',
        'text=选择视频',
        'text=เลือกวิดีโอ',
        'text=Select video',
    ]
    for selector in button_selectors:
        try:
            button = page.locator(selector).first
            button.wait_for(state="visible", timeout=5000)
            with page.expect_file_chooser(timeout=10000) as chooser_info:
                button.click(timeout=5000)
            chooser_info.value.set_files(video_path.as_posix())
            return f"chooser:{selector}"
        except Exception:
            continue

    raise RuntimeError("没有找到 TikTok 上传页的视频选择控件")


def wait_for_tiktok_upload_state(page: Any) -> bool:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if visible_tiktok_caption_input(page):
            return True
        page.wait_for_timeout(500)
    return False


def wait_for_tiktok_upload_ready(page: Any, timeout_ms: int = 180000) -> str:
    """Wait for the actual upload UI instead of TikTok's transient loading page."""
    selectors = [
        ('input[type="file"]', "视频文件选择控件"),
        ('[data-e2e="select_video_button"]', "选择视频按钮"),
        ('button:has-text("选择视频")', "选择视频按钮"),
        ('button:has-text("เลือกวิดีโอ")', "选择视频按钮"),
        ('button:has-text("Select video")', "选择视频按钮"),
    ]
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for selector, description in selectors:
            try:
                if page.locator(selector).count() > 0:
                    return description
            except Exception:
                continue
        page.wait_for_timeout(1000)
    raise RuntimeError(
        f"TikTok 上传页在 {timeout_ms // 1000} 秒内没有加载出视频选择控件，当前页面：{page.url}"
    )


def set_tiktok_ai_label(page: Any, enabled: bool) -> bool:
    if not enabled:
        return False
    try:
        advanced = page.locator('[data-e2e="advanced_settings_container"]')
        if advanced.count() > 0 and "collapsed" in str(advanced.first.get_attribute("class") or ""):
            advanced.first.evaluate("el => (el.querySelector('.more-btn') || el).click()")
        deadline = time.monotonic() + 5
        state = None
        while time.monotonic() < deadline and not state:
            state = page.evaluate(
                """() => {
                    const container = document.querySelector('[data-e2e="aigc_container"]');
                    const input = container && container.querySelector('input[role="switch"]');
                    if (!container || !input) return null;
                    container.scrollIntoView({ block: 'center', inline: 'nearest' });
                    return { checked: Boolean(input.checked), disabled: Boolean(input.disabled) };
                }"""
            )
            if not state:
                page.wait_for_timeout(250)
        if not state or state.get("disabled"):
            return False
        if state.get("checked"):
            return True
        clicked = page.evaluate(
            """() => {
                const input = document.querySelector('[data-e2e="aigc_container"] input[role="switch"]');
                const control = input && input.closest('.Switch__content');
                if (!input || !control) return false;
                control.click();
                return true;
            }"""
        )
        if not clicked:
            return False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if page.locator('[data-e2e="aigc_container"] input[role="switch"]').is_checked():
                return True
            page.wait_for_timeout(200)
        return False
    except Exception:
        return False


def tiktok_body_text(page: Any) -> str:
    return page.locator("body").inner_text(timeout=5000)


def visible_tiktok_buttons(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('button')).map((button, index) => {
            const rect = button.getBoundingClientRect();
            const style = getComputedStyle(button);
            return {
                index,
                text: (button.innerText || button.textContent || '').trim(),
                x: rect.x,
                y: rect.y,
                w: rect.width,
                h: rect.height,
                disabled: Boolean(button.disabled),
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'
            };
        }).filter(item => item.visible)"""
    )


def click_tiktok_button_index(page: Any, index: int) -> bool:
    return bool(
        page.evaluate(
            """index => {
                const button = document.querySelectorAll('button')[index];
                if (!button) return false;
                button.scrollIntoView({ block: 'center', inline: 'center' });
                button.click();
                return true;
            }""",
            index,
        )
    )


def click_visible_tiktok_button(page: Any, text: str, *, rightmost: bool = True) -> dict[str, Any] | None:
    candidates = [
        item
        for item in visible_tiktok_buttons(page)
        if item["text"] == text and not item["disabled"] and item["x"] > 80
    ]
    if not candidates:
        return None
    if rightmost:
        target = sorted(candidates, key=lambda item: (item["y"], item["x"]))[-1]
    else:
        target = sorted(candidates, key=lambda item: (item["y"], item["x"]))[0]
    click_tiktok_button_index(page, int(target["index"]))
    page.wait_for_timeout(1200)
    return target


def click_tiktok_dialog_primary_button(page: Any) -> bool:
    clicked = page.evaluate(
        """() => {
            const candidates = Array.from(document.querySelectorAll('button.TUXButton--primary')).map(button => {
                const rect = button.getBoundingClientRect();
                const style = getComputedStyle(button);
                const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
                return {
                    button,
                    rect,
                    visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
                    topmost: Boolean(hit && (hit === button || button.contains(hit))),
                    disabled: Boolean(button.disabled) || button.getAttribute('aria-disabled') === 'true'
                };
            }).filter(item => item.visible && item.topmost && !item.disabled)
              .sort((a, b) => b.rect.y - a.rect.y || b.rect.x - a.rect.x);
            const chosen = candidates[0];
            if (!chosen) return false;
            chosen.button.click();
            return true;
        }"""
    )
    if clicked:
        page.wait_for_timeout(800)
    return bool(clicked)


def visible_tiktok_product_name_input(page: Any) -> Any | None:
    candidates = page.locator('input.TUXTextInputCore-input:not([placeholder])')
    for index in range(candidates.count() - 1, -1, -1):
        candidate = candidates.nth(index)
        if candidate.is_visible() and candidate.is_enabled():
            return candidate
    return None


def click_main_add_link_button(page: Any) -> bool:
    container = page.locator('[data-e2e="anchor_container"]')
    if container.count() != 1:
        return False
    container.first.evaluate("el => el.scrollIntoView({ block: 'center', inline: 'nearest' })")
    button = container.first.locator('button:has([data-testid="Plus"])')
    if button.count() != 1 or not button.first.is_enabled():
        return False
    button.first.evaluate("el => el.click()")
    page.wait_for_timeout(1500)
    return True


def fill_tiktok_product_search(page: Any, product_id: str) -> None:
    deadline = time.monotonic() + 15
    search = None
    while time.monotonic() < deadline:
        candidates = page.locator('.TUXInputBox:has(.product-search-icon) input.TUXTextInputCore-input')
        if candidates.count() == 1 and candidates.first.is_visible() and candidates.first.is_enabled():
            search = candidates.first
            break
        page.wait_for_timeout(250)
    if not search:
        raise RuntimeError("商品选择页没有找到搜索框")
    search.fill(product_id)
    if str(search.input_value()).strip() != product_id:
        raise RuntimeError("商品 ID 没有完整写入搜索框")
    search.evaluate("input => input.closest('.TUXInputBox').querySelector('.product-search-icon').click()")
    page.wait_for_timeout(800)


def select_tiktok_product_row(page: Any, product_id: str) -> str:
    deadline = time.monotonic() + 15
    result = None
    while time.monotonic() < deadline:
        result = page.evaluate(
            """productId => {
                const textNodes = Array.from(document.querySelectorAll('body *'));
                const idNode = textNodes.find(el => (el.innerText || el.textContent || '').trim() === productId);
                if (!idNode) return null;
                let root = idNode;
                let radio = null;
                while (root && root !== document.body) {
                    radio = root.querySelector && root.querySelector('input[type="radio"]');
                    if (radio) break;
                    root = root.parentElement;
                }
                if (!radio) return null;
                radio.click();
                return { selected: Boolean(radio.checked), name: radio.name || radio.value || '' };
            }""",
            product_id,
        )
        if result and result.get("selected"):
            break
        page.wait_for_timeout(300)
    if not result or not result.get("selected"):
        raise RuntimeError(f"没有在 TikTok 商品列表里找到商品 ID：{product_id}")
    return str(result.get("name") or product_id)


def add_tiktok_product_link(page: Any, product_id: str, product_short_name: str) -> dict[str, Any]:
    if not product_id:
        raise ValueError("商品 ID 不能为空")
    product_short_name = product_short_name.strip()
    if not product_short_name:
        raise ValueError("没有配置当前产品和国家的商品简称")
    if len(product_short_name) > 30:
        raise ValueError("商品简称不能超过 30 个字符")
    if not click_main_add_link_button(page):
        raise RuntimeError("没有找到商品链接区域的添加按钮")
    if not click_tiktok_dialog_primary_button(page):
        raise RuntimeError("链接类型弹窗没有找到主操作按钮")

    fill_tiktok_product_search(page, product_id)
    product_name = select_tiktok_product_row(page, product_id)
    if not click_tiktok_dialog_primary_button(page):
        raise RuntimeError("商品选择页没有找到主操作按钮")

    deadline = time.monotonic() + 15
    name_input = None
    while time.monotonic() < deadline:
        name_input = visible_tiktok_product_name_input(page)
        if name_input:
            break
        page.wait_for_timeout(250)
    if not name_input:
        raise RuntimeError("商品名称确认弹窗没有找到输入框")
    name_input.fill(product_short_name)
    if str(name_input.input_value()).strip() != product_short_name:
        raise RuntimeError("商品简称没有完整写入")
    if not click_tiktok_dialog_primary_button(page):
        raise RuntimeError("商品名称确认弹窗没有找到添加按钮")

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        anchor = page.locator('[data-e2e="anchor_container"]')
        if anchor.count() == 1 and product_short_name in anchor.first.inner_text(timeout=3000):
            return {
                "product_linked": True,
                "product_name": product_short_name,
                "source_product_name": product_name,
            }
        page.wait_for_timeout(300)
    raise RuntimeError("商品链接流程完成后没有在页面确认到商品简称")


def ensure_tiktok_public_visibility(page: Any) -> bool:
    try:
        trigger = page.locator('[data-e2e="video_visibility_container"] button[role="combobox"]')
        if trigger.count() != 1:
            return False
        trigger.first.evaluate("el => el.click()")
        page.wait_for_timeout(300)
        state = page.evaluate(
            """() => {
                const options = Array.from(document.querySelectorAll('[role="option"]'));
                const publicOption = options.find(option =>
                    (option.getAttribute('data-value') || '').replaceAll('"', '') === '0'
                );
                if (!publicOption) return null;
                const selected = publicOption.getAttribute('aria-selected') === 'true';
                if (!selected) publicOption.click();
                return { selected };
            }"""
        )
        if not state:
            return False
        if state.get("selected"):
            trigger.first.evaluate("el => el.click()")
        page.wait_for_timeout(300)
        trigger.first.evaluate("el => el.click()")
        page.wait_for_timeout(300)
        verified = bool(
            page.evaluate(
                """() => Array.from(document.querySelectorAll('[role="option"]')).some(option =>
                    (option.getAttribute('data-value') || '').replaceAll('"', '') === '0' &&
                    option.getAttribute('aria-selected') === 'true'
                )"""
            )
        )
        trigger.first.evaluate("el => el.click()")
        return verified
    except Exception:
        return False


def wait_for_tiktok_upload_complete(page: Any, timeout_seconds: int = 180) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        complete = page.evaluate(
            """() => {
                const container = document.querySelector('[data-e2e="upload_status_container"]');
                return Boolean(container && (
                    container.querySelector('.info-status.success') ||
                    container.querySelector('.info-progress.success') ||
                    container.querySelector('[data-testid="CheckCircleFill"]')
                ));
            }"""
        )
        if complete:
            return True
        page.wait_for_timeout(500)
    return False


def click_tiktok_publish_button(page: Any) -> dict[str, Any]:
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)
    button = page.locator('[data-e2e="post_video_button"]')
    if button.count() != 1:
        raise RuntimeError("没有找到 TikTok 底部发布按钮")
    if not button.first.is_enabled() or button.first.get_attribute("aria-disabled") == "true":
        raise RuntimeError("TikTok 发布按钮当前不可用")
    button.first.evaluate("el => el.click()")
    deadline = datetime.now().timestamp() + 90
    last_url = page.url
    confirmation_clicked = False
    while datetime.now().timestamp() < deadline:
        page.wait_for_timeout(500)
        if not confirmation_clicked and click_tiktok_dialog_primary_button(page):
            confirmation_clicked = True
        text = tiktok_body_text(page)
        last_url = page.url
        if "เผยแพร่วิดีโอแล้ว" in text or "/tiktokstudio/content" in last_url:
            return {
                "published": True,
                "url": last_url,
                "confirmation_clicked": confirmation_clicked,
            }
        if "คุณแน่ใจหรือไม่ว่าต้องการออก" in text:
            click_visible_tiktok_button(page, "ยกเลิก")
            raise RuntimeError("误触离开确认弹窗，已取消，没有发布")
    raise RuntimeError(f"TikTok 发布后没有返回成功状态，当前页面：{last_url}")


def close_confirmed_tiktok_publish_page(page: Any, timeout_seconds: int = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_url = ""
    while True:
        try:
            last_url = str(page.url or "")
            if "/tiktokstudio/content" in last_url:
                page.close()
                return {"publish_page_closed": True, "publish_page_url": last_url}
        except Exception:
            break
        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(250)
    return {"publish_page_closed": False, "publish_page_url": last_url}


def append_publish_record(
    video_path: Path,
    profile_id: str,
    product_id: str,
    ai_generated: bool,
    visibility: str,
    publish_mode: str = "auto",
) -> dict[str, Any]:
    records = load_publish_records()
    config = load_publish_config()
    libraries = load_title_library()
    videos = scan_finished_videos(libraries, records)
    video = next((item for item in videos if item["path"] == video_path.as_posix()), None)
    account = (config.get("accounts") or {}).get(profile_id) or {}
    if not account:
        try:
            account = next(
                (
                    profile
                    for profile in list_bitbrowser_profiles().get("profiles", [])
                    if profile.get("id") == profile_id
                ),
                {},
            )
        except Exception:
            account = {}
    country = ((video or {}).get("countries") or [account.get("country", "")])[0] or ""
    record = {
        "status": "published",
        "video_path": video_path.as_posix(),
        "video_name": video_path.name,
        "product_code": (video or {}).get("product_code", ""),
        "country": country,
        "profile_id": profile_id,
        "account_name": account.get("name", ""),
        "store_name": account.get("store_name", ""),
        "account_type": account.get("account_type", ""),
        "product_id": product_id,
        "publish_mode": publish_mode,
        "ai_generated": ai_generated,
        "visibility": visibility,
        "published_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
    }
    records.append(record)
    save_publish_records(records)
    return record


def publish_tiktok_video(
    profile_id: str,
    video_value: str,
    caption: str,
    product_id: str,
    product_short_name: str,
    ai_generated: bool = True,
    visibility: str = "public",
    execution_mode: str = "visible",
) -> dict[str, Any]:
    if visibility != "public":
        raise ValueError("当前脚本只允许发布为所有人可见")
    result = prepare_tiktok_upload(profile_id, video_value, caption, ai_generated, execution_mode)
    if caption and not result.get("caption_filled"):
        raise RuntimeError("视频已选择，但文案没有被完整替换，停止发布")

    open_result = bitbrowser_post(
        "/browser/open",
        bitbrowser_open_payload(profile_id, execution_mode),
        timeout=30,
    )
    open_data = open_result.get("data") or {}
    cdp_endpoint = normalize_cdp_endpoint(open_data.get("http") or open_data.get("ws") or "")
    if not cdp_endpoint:
        raise RuntimeError("比特浏览器没有返回可连接的调试地址")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境缺少 playwright，无法接管浏览器窗口") from exc

    video_path = safe_video_path(video_value)
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = find_tiktok_upload_page(context) or context.new_page()
        page.bring_to_front()
        caption_input = visible_tiktok_caption_input(page)
        current_caption = caption_text(caption_input) if caption_input else ""
        if caption and not captions_match(current_caption, caption):
            raise RuntimeError(f"发布文案不匹配，停止发布。当前文案：{current_caption}")
        hashtags = re.findall(r"(?<!\S)#[^\s#]+", caption)
        if caption_input and not tiktok_hashtags_are_mentions(caption_input, hashtags):
            raise RuntimeError("发布文案中的标签没有全部选择为 TikTok hashtag，停止发布")
        product_result = add_tiktok_product_link(page, product_id, product_short_name)
        if ai_generated and not set_tiktok_ai_label(page, True):
            raise RuntimeError("AI 标识未确认开启，停止发布")
        if not ensure_tiktok_public_visibility(page):
            raise RuntimeError("可见性不是所有人，停止发布")
        if not wait_for_tiktok_upload_complete(page):
            raise RuntimeError("视频在 180 秒内没有确认上传完成，停止发布")
        publish_result = click_tiktok_publish_button(page)
        record = append_publish_record(video_path, profile_id, product_id, ai_generated, visibility, "auto")
        close_result = close_confirmed_tiktok_publish_page(page)
        return {
            **result,
            **product_result,
            **publish_result,
            **close_result,
            "record": record,
            "message": "已完成 TikTok 发布、写入本地发布记录，并关闭本次发布页面。"
            if close_result["publish_page_closed"]
            else "已完成 TikTok 发布并写入本地发布记录，但发布页面未自动关闭，请人工检查。",
        }
    finally:
        playwright.stop()


def prepare_tiktok_upload(
    profile_id: str,
    video_value: str,
    caption: str,
    ai_generated: bool = True,
    execution_mode: str = "visible",
) -> dict[str, Any]:
    if not profile_id:
        raise ValueError("请选择一个比特浏览器窗口")
    video_path = safe_video_path(video_value)
    if not video_path.exists() or not video_path.is_file():
        raise ValueError("视频文件不存在")

    open_result = bitbrowser_post(
        "/browser/open",
        bitbrowser_open_payload(profile_id, execution_mode),
        timeout=30,
    )
    if not open_result.get("success"):
        raise RuntimeError(open_result.get("msg") or "打开比特浏览器窗口失败")
    open_data = open_result.get("data") or {}
    cdp_endpoint = normalize_cdp_endpoint(open_data.get("http") or open_data.get("ws") or "")
    if not cdp_endpoint:
        raise RuntimeError("比特浏览器没有返回可连接的调试地址")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境缺少 playwright，无法接管浏览器窗口") from exc

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        page.bring_to_front()
        try:
            upload_page_ready = wait_for_tiktok_upload_ready(page, timeout_ms=30000)
        except RuntimeError:
            page.goto(TIKTOK_UPLOAD_FALLBACK_URL, wait_until="domcontentloaded", timeout=60000)
        upload_page_ready = wait_for_tiktok_upload_ready(page)
        upload_method = select_tiktok_video(page, video_path)
        upload_started = wait_for_tiktok_upload_state(page)
        caption_pre_filled = False
        caption_input = visible_tiktok_caption_input(page)
        if caption and caption_input:
            caption_plain_text = re.sub(r"(?<!\S)#[^\s#]+", "", caption)
            caption_plain_text = re.sub(r"\s+", " ", caption_plain_text).strip()
            caption_pre_filled = replace_caption_text(page, caption_input, caption_plain_text)
        upload_complete = wait_for_tiktok_upload_complete(page) if caption else False
        if upload_complete:
            page.wait_for_timeout(1500)
        caption_filled = fill_tiktok_caption(page, caption) if upload_complete else False
        if caption and upload_complete and not caption_filled:
            page.wait_for_timeout(1000)
            caption_filled = fill_tiktok_caption(page, caption)
        if caption and not caption_filled:
            raise RuntimeError("视频已选择，但文案没有被完整替换。请不要发布，先检查描述框内容。")
        ai_label_set = False
        page.bring_to_front()
        return {
            "ok": True,
            "message": "已打开 TikTok 上传页并选择视频。请人工确认页面状态后点击发布。"
            if upload_started
            else "已尝试选择视频，但没有检测到 TikTok 上传状态变化。请检查页面是否弹出文件选择或权限提示。",
            "profile_id": profile_id,
            "video_path": video_path.as_posix(),
            "upload_method": upload_method,
            "upload_page_ready": upload_page_ready,
            "upload_started": upload_started,
            "upload_complete": upload_complete,
            "caption_pre_filled": caption_pre_filled,
            "caption_filled": caption_filled,
            "ai_generated": ai_generated,
            "execution_mode": execution_mode,
            "ai_label_set": ai_label_set,
            "tiktok_upload_url": TIKTOK_UPLOAD_URL,
        }
    finally:
        playwright.stop()


def serve_video(handler: BaseHTTPRequestHandler, path: Path) -> None:
    file_size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = handler.headers.get("Range", "")
    start = 0
    end = file_size - 1
    status = 200
    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if match:
        status = 206
        if match.group(1):
            start = int(match.group(1))
        if match.group(2):
            end = min(int(match.group(2)), file_size - 1)
    length = max(0, end - start + 1)
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(length))
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    handler.end_headers()
    try:
        with path.open("rb") as file:
            file.seek(start)
            remaining = length
            while remaining > 0:
                chunk = file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        return


def delete_finished_video(video_value: str) -> dict[str, Any]:
    path = safe_video_path(video_value)
    if not path.exists() or not path.is_file():
        raise ValueError("视频文件不存在")
    path.unlink()
    return {"ok": True, "deleted_path": path.as_posix()}


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def parse_title_tag_range(lines: list[str], start: int, end: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in lines[start:end]:
        line = raw_line.strip()
        match = re.match(r"^(\d+)[\.、]\s*(.+)$", line)
        if match:
            content = match.group(2).strip()
            tags = re.findall(r"#[^\s#]+", content)
            text = re.sub(r"\s*#[^\s#]+", "", content).strip()
            current = {
                "index": match.group(1),
                "text": text,
                "language": "",
                "tags": tags[:5],
                "translation": "",
                "tag_translation": "",
                "full_text": content,
            }
            rows.append(current)
            continue
        if current and (line.startswith("中文翻译：") or line.startswith("中文翻译:")):
            current["translation"] = re.split(r"[:：]", line, maxsplit=1)[-1].strip()
            continue
        if current and (line.startswith("标签翻译：") or line.startswith("标签翻译:")):
            current["tag_translation"] = re.split(r"[:：]", line, maxsplit=1)[-1].strip()
            continue
        if current and line and not line.startswith("#") and not line.startswith("|"):
            current["translation"] = line
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] in {"#", "---"} or set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) >= 8:
            tags = cells[3:8]
            rows.append(
                {
                    "index": cells[0],
                    "text": cells[1],
                    "language": cells[2],
                    "tags": tags,
                    "translation": cells[8] if len(cells) > 8 else "",
                    "tag_translation": "",
                    "full_text": " ".join([cells[1], *[tag for tag in tags if tag]]).strip(),
                }
            )
    return rows


def parse_country_heading(text: str) -> tuple[str, str] | None:
    normalized = re.sub(r"^国家\s*[:：]\s*", "", text.strip())
    match = re.match(r"(.+?)\s*\(([A-Za-z]{2})\)\s*$", normalized)
    if match:
        code = match.group(2).upper()
        return code, match.group(1).strip()
    match = re.match(r"([A-Za-z]{2})\s*[｜|/\-]\s*(.+)$", normalized)
    if match:
        code = match.group(1).upper()
        return code, match.group(2).strip()
    code = normalized.upper()
    if code in COUNTRY_NAMES:
        return code, COUNTRY_NAMES[code]
    return None


def parse_country_libraries(lines: list[str]) -> list[dict[str, Any]]:
    country_libraries: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        parsed_heading = heading(lines[index])
        if not parsed_heading or parsed_heading[0] != 2:
            index += 1
            continue
        country = parse_country_heading(parsed_heading[1])
        if not country:
            index += 1
            continue
        code, name = country
        section_end = index + 1
        while section_end < len(lines):
            next_heading = heading(lines[section_end])
            if next_heading and next_heading[0] <= 2:
                break
            section_end += 1
        items: list[dict[str, Any]] = []
        child_index = index + 1
        while child_index < section_end:
            child_heading = heading(lines[child_index])
            if child_heading and child_heading[1] == "标题标签池":
                table_end = child_index + 1
                while table_end < section_end:
                    next_heading = heading(lines[table_end])
                    if next_heading and next_heading[0] <= child_heading[0]:
                        break
                    table_end += 1
                items = parse_title_tag_range(lines, child_index + 1, table_end)
                child_index = table_end
                continue
            child_index += 1
        country_libraries.append({"code": code, "name": name, "items": items})
        index = section_end
    return country_libraries


def parse_title_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    product = ""
    title = ""
    code = path.stem.split("-", 1)[0]
    in_frontmatter = False
    if lines and lines[0].strip() == "---":
        in_frontmatter = True
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip().strip('"')
            if key.strip() == "product":
                product = value
            elif key.strip() == "title":
                title = value
    match = re.search(r"项目代码\*\*:\s*([A-Za-z0-9_-]+)", text)
    if match:
        code = match.group(1).strip()
    if not product and "-" in path.stem:
        product = path.stem.split("-", 1)[1]
    country_libraries = parse_country_libraries(lines)
    return {
        "key": path.stem,
        "code": code,
        "name": product or path.stem,
        "title": title or path.stem,
        "path": path.as_posix(),
        "display_path": display_path(path),
        "country_libraries": country_libraries,
        "by_country": {item["code"]: item for item in country_libraries},
    }


def load_title_library() -> dict[str, dict[str, Any]]:
    libraries: dict[str, dict[str, Any]] = {}
    if not TITLE_LIBRARY_ROOT.exists():
        return libraries
    for path in sorted(TITLE_LIBRARY_ROOT.glob("*.md"), key=lambda item: item.name.lower()):
        if path.name.startswith("_"):
            continue
        try:
            library = parse_title_file(path)
        except OSError:
            continue
        libraries[library["key"]] = library
    return libraries


def extract_countries(filename: str, product_key: str) -> list[str]:
    stem = Path(filename).stem
    prefix_match = re.search(re.escape(product_key) + r"-(.+)$", stem)
    if not prefix_match:
        return []
    for token in prefix_match.group(1).split("-"):
        code = token.strip().upper()
        if code in COUNTRY_NAMES:
            return [code]
        break
    return []


def scan_finished_videos(libraries: dict[str, dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    if not FINISHED_VIDEO_ROOT.exists():
        return videos
    published_records = published_record_by_path(records)
    paths = sorted(
        (
            path
            for path in FINISHED_VIDEO_ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=lambda item: item.as_posix().lower(),
    )
    flat_identities = {
        video_identity(path)
        for path in paths
        if len(path.relative_to(FINISHED_VIDEO_ROOT).parts) == 2
    }
    published_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "published" or not record.get("video_path"):
            continue
        published_by_identity.setdefault(video_identity(Path(str(record["video_path"]))), record)

    for path in paths:
        product_key = path.parent.name
        identity = video_identity(path)
        relative_parts = path.relative_to(FINISHED_VIDEO_ROOT).parts
        is_flat_layout = len(relative_parts) == 2
        if not is_flat_layout and identity in flat_identities:
            continue
        library = libraries.get(product_key)
        if library is None and "-" in product_key:
            code = product_key.split("-", 1)[0]
            library = next((item for item in libraries.values() if item.get("code") == code), None)
        countries = extract_countries(path.name, product_key)
        stat = path.stat()
        published_record = published_records.get(path.as_posix()) or published_by_identity.get(identity)
        workflow = relative_parts[0] if len(relative_parts) > 3 else ""
        date = (
            datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
            if is_flat_layout
            else relative_parts[1] if len(relative_parts) > 3 else ""
        )
        stem_parts = path.stem.split("-")
        videos.append(
            {
                "id": path.as_posix(),
                "name": path.name,
                "path": path.as_posix(),
                "display_path": display_path(path),
                "product_key": product_key,
                "product_code": product_key.split("-", 1)[0] if "-" in product_key else product_key,
                "product_name": library["name"] if library else product_key.split("-", 1)[-1],
                "workflow": workflow,
                "date": date,
                "mode": stem_parts[1] if len(stem_parts) > 1 else "",
                "countries": countries,
                "country_names": [COUNTRY_NAMES.get(code, code) for code in countries],
                "size_mb": round(stat.st_size / 1024 / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "video_url": "/api/video?path=" + urllib.parse.quote(path.as_posix()),
                "has_title_library": library is not None,
                "published": published_record is not None,
                "published_record": published_record,
            }
        )
    return videos


def build_products(videos: list[dict[str, Any]], libraries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    for key, library in libraries.items():
        products[key] = {
            "key": key,
            "code": library["code"],
            "name": library["name"],
            "video_count": 0,
            "countries": [],
            "title_count": max([len(item["items"]) for item in library["country_libraries"]] or [0]),
            "tag_count": 5,
            "library": library,
        }
    for video in videos:
        key = video["product_key"]
        product = products.setdefault(
            key,
            {
                "key": key,
                "code": video["product_code"],
                "name": video["product_name"],
                "video_count": 0,
                "countries": [],
                "title_count": 0,
                "tag_count": 0,
                "library": None,
            },
        )
        product["video_count"] += 1
        for code in video["countries"]:
            if code not in product["countries"]:
                product["countries"].append(code)
    return sorted(products.values(), key=lambda item: (-item["video_count"], item["key"].lower()))


def state_for_client() -> dict[str, Any]:
    libraries = load_title_library()
    publish_config = load_publish_config()
    publish_records = load_publish_records()
    videos = scan_finished_videos(libraries, publish_records)
    products = build_products(videos, libraries)
    countries = sorted({code for video in videos for code in video["countries"]})
    return {
        "finished_video_root": FINISHED_VIDEO_ROOT.as_posix(),
        "title_library_root": TITLE_LIBRARY_ROOT.as_posix(),
        "video_count": len(videos),
        "product_count": len(products),
        "library_count": len(libraries),
        "countries": [{"code": code, "name": COUNTRY_NAMES.get(code, code)} for code in countries],
        "products": products,
        "videos": videos,
        "publish_config": publish_config,
        "publish_records": publish_records,
        "warnings": [
            {"level": "warn", "message": f"成品视频目录不存在: {FINISHED_VIDEO_ROOT}"}
            if not FINISHED_VIDEO_ROOT.exists()
            else None,
            {"level": "warn", "message": f"视频标题库目录不存在: {TITLE_LIBRARY_ROOT}"}
            if not TITLE_LIBRARY_ROOT.exists()
            else None,
        ],
    }


def get_publish_queue() -> PublishQueue:
    if PUBLISH_QUEUE is None:
        raise RuntimeError("发布队列尚未启动")
    return PUBLISH_QUEUE


def build_queue_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    profile_id = str(payload.get("profile_id", "")).strip()
    raw_tasks = payload.get("tasks") or []
    if not profile_id:
        raise ValueError("请选择一个比特浏览器窗口")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("请至少选择一个视频")

    profiles = list_bitbrowser_profiles().get("profiles", [])
    profile = next((item for item in profiles if item.get("id") == profile_id), None)
    if not profile:
        raise ValueError("选中的比特浏览器窗口不存在")

    config = load_publish_config()
    records = load_publish_records()
    libraries = load_title_library()
    videos = scan_finished_videos(libraries, records)
    videos_by_path = {item["path"]: item for item in videos}
    tasks: list[dict[str, Any]] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise ValueError("队列任务格式无效")
        video_path = safe_video_path(str(raw_task.get("video_path", ""))).as_posix()
        video = videos_by_path.get(video_path)
        if not video:
            raise ValueError(f"成品视频不存在：{Path(video_path).name}")
        if video.get("published"):
            raise ValueError(f"已发布视频不能重复入队：{video['name']}")
        country = str((video.get("countries") or [""])[0])
        if profile.get("country") != country:
            raise ValueError(
                f"账号国家与视频不匹配：{profile.get('country') or '未识别'} / {country or '未识别'} / {video['name']}"
            )
        product_code = str(video.get("product_code", ""))
        product_id = product_id_for_account(config, product_code, country, profile)
        if not product_id:
            product_id = str(((config.get("product_links") or {}).get(product_code) or {}).get(country, {}).get(profile_id, ""))
        if not product_id:
            raise ValueError(f"商品 ID 未配置：{product_code} / {country} / {profile.get('store_name', '')}")
        product_short_name = str(((config.get("product_short_names") or {}).get(product_code) or {}).get(country) or "")
        if not product_short_name:
            raise ValueError(f"商品简称未配置：{product_code} / {country}")
        caption = str(raw_task.get("caption", "")).strip()
        if not caption:
            raise ValueError(f"发布文案为空：{video['name']}")
        if len(re.findall(r"(?<!\S)#[^\s#]+", caption)) != 5:
            raise ValueError(f"发布文案必须包含 5 个标签：{video['name']}")
        tasks.append(
            {
                "video_path": video_path,
                "video_name": video["name"],
                "product_code": product_code,
                "country": country,
                "profile_id": profile_id,
                "profile_name": profile.get("name", ""),
                "caption": caption,
                "product_id": product_id,
                "product_short_name": product_short_name,
                "ai_generated": bool(payload.get("ai_generated", True)),
                "visibility": "public",
            }
        )
    return tasks


def run_tiktok_publish_locked(task: dict[str, Any]) -> dict[str, Any]:
    if not PUBLISH_LOCK.acquire(blocking=False):
        raise RuntimeError("另一个发布任务正在执行")
    try:
        return publish_tiktok_video(
            str(task.get("profile_id", "")),
            str(task.get("video_path", "")),
            str(task.get("caption", "")),
            str(task.get("product_id", "")),
            str(task.get("product_short_name", "")),
            bool(task.get("ai_generated", True)),
            str(task.get("visibility", "public")),
            str(task.get("execution_mode", "visible")),
        )
    finally:
        PUBLISH_LOCK.release()


def close_bitbrowser_profile(task: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(task.get("profile_id", "")).strip()
    if not profile_id:
        raise ValueError("缺少需要关闭的比特浏览器窗口 ID")
    result = bitbrowser_post("/browser/close", {"id": profile_id}, timeout=30)
    if not result.get("success"):
        raise RuntimeError(result.get("msg") or "关闭比特浏览器窗口失败")
    return {"browser_closed": True, "profile_id": profile_id}


def prepare_tiktok_upload_locked(
    profile_id: str,
    video_path: str,
    caption: str,
    ai_generated: bool,
) -> dict[str, Any]:
    if not PUBLISH_LOCK.acquire(blocking=False):
        raise RuntimeError("另一个发布任务正在执行")
    try:
        return prepare_tiktok_upload(profile_id, video_path, caption, ai_generated)
    finally:
        PUBLISH_LOCK.release()


APP_HEADER_MARKER = "<!-- APP_HEADER_ACTIONS -->"

APP_HEADER_HTML = r"""<div class="appHeaderActions">
      <a id="videoBadge" class="appHeaderControl appHeaderBadge" href="/" title="成品管理">视频 0</a>
      <span id="productBadge" class="appHeaderControl appHeaderBadge">产品 0</span>
      <span id="libraryBadge" class="appHeaderControl appHeaderBadge">标题库 0</span>
      <a class="appHeaderControl" href="/product-id">商品映射库</a>
      <a class="appHeaderControl" href="/Daily-KPIs">每日 KPI</a>
      <a id="queueBadge" class="appHeaderControl" href="/queue">发布队列 0</a>
      <button class="appHeaderControl" type="button" onclick="refreshCurrentPage()">刷新</button>
    </div>"""

APP_HEADER_STYLE = r"""<style>
    .appHeaderActions {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:8px;
      flex-wrap:wrap;
    }
    .appHeaderActions .appHeaderControl {
      display:inline-flex;
      align-items:center;
      box-sizing:border-box;
      height:32px;
      margin:0;
      border:1px solid var(--line, #151515);
      background:var(--surface, #fffdf7);
      color:var(--ink, #101010);
      padding:7px 10px;
      font:inherit;
      font-size:12px;
      font-weight:800;
      line-height:1.2;
      text-decoration:none;
      white-space:nowrap;
      cursor:pointer;
      box-shadow:3px 3px 0 rgba(16,16,16,.12);
    }
    .appHeaderActions .appHeaderControl:hover { background:var(--accent, #d9ff63); }
    .appHeaderActions .appHeaderBadge { font-size:11px; cursor:default; }
    .appHeaderActions a.appHeaderBadge { cursor:pointer; }
    @media (max-width:760px) {
      header { align-items:flex-start; flex-direction:column; padding:12px; }
      .appHeaderActions { width:100%; justify-content:flex-start; }
    }
  </style>"""

APP_HEADER_SCRIPT = r"""<script>
    async function loadAppHeader() {
      const [stateResult, queueResult] = await Promise.all([
        fetch('/api/state').then(async response => response.ok ? response.json() : null).catch(() => null),
        fetch('/api/queue').then(async response => response.ok ? response.json() : null).catch(() => null),
      ]);
      if (stateResult) {
        document.getElementById('videoBadge').textContent = `视频 ${stateResult.video_count || 0}`;
        document.getElementById('productBadge').textContent = `产品 ${stateResult.product_count || 0}`;
        document.getElementById('libraryBadge').textContent = `标题库 ${stateResult.library_count || 0}`;
      }
      if (queueResult) {
        const counts = queueResult.counts || {};
        const activeCount = Number(counts.pending || 0) + Number(counts.running || 0);
        document.getElementById('queueBadge').textContent = `发布队列 ${activeCount}`;
      }
    }

    async function refreshCurrentPage() {
      const loaders = {
        '/': 'loadState',
        '/product-id': 'loadRows',
        '/Daily-KPIs': 'loadKpis',
        '/daily-kpis': 'loadKpis',
        '/queue': 'loadQueue',
      };
      const loader = window[loaders[window.location.pathname] || ''];
      try {
        if (typeof loader === 'function') await loader();
      } finally {
        await loadAppHeader();
      }
    }

    loadAppHeader().catch(() => {});
  </script>"""


def render_app_page(html: str) -> str:
    if APP_HEADER_MARKER not in html:
        raise ValueError("app page is missing the shared header marker")
    return (
        html.replace(APP_HEADER_MARKER, APP_HEADER_HTML)
        .replace("</head>", f"{APP_HEADER_STYLE}\n</head>", 1)
        .replace("</body>", f"{APP_HEADER_SCRIPT}\n</body>", 1)
    )


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>成品管理</title>
  <style>
    :root {
      color-scheme: light;
      --bg:#f6f3ea;
      --surface:#fffdf7;
      --surface-soft:#eee9dd;
      --ink:#101010;
      --muted:#5e5a51;
      --soft:#888276;
      --line:#151515;
      --line-soft:rgba(16,16,16,.16);
      --accent:#d9ff63;
      --teal:#0e766e;
      --blue:#2463eb;
      --red:#b42318;
      --shadow:0 14px 0 rgba(16,16,16,.08);
    }
    * { box-sizing:border-box; }
    html, body { min-height:100%; margin:0; }
    body {
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
      min-height:72px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:0 22px;
      background:rgba(255,253,247,.86);
      border-bottom:1px solid var(--line);
      backdrop-filter:blur(14px);
      position:sticky;
      top:0;
      z-index:5;
    }
    h1 { margin:0; font-size:24px; font-weight:820; line-height:1; }
    .sub { color:var(--muted); font-size:12px; margin-top:7px; text-transform:uppercase; }
    main {
      height:calc(100vh - 72px);
      padding:14px;
      display:grid;
      grid-template-columns:300px minmax(420px,1fr) 420px;
      gap:14px;
      overflow:hidden;
    }
    section {
      min-height:0;
      min-width:0;
      display:flex;
      flex-direction:column;
      overflow:hidden;
      border:1px solid var(--line);
      background:var(--surface);
      box-shadow:var(--shadow);
    }
    .panelHead {
      min-height:50px;
      padding:10px 12px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      border-bottom:1px solid var(--line);
      background:var(--surface-soft);
    }
    h2 { margin:0; font-size:12px; font-weight:820; color:var(--ink); text-transform:uppercase; }
    .panelBody { flex:1; min-height:0; overflow:auto; padding:12px; }
    .panelActions { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
    label {
      display:block;
      margin:8px 0 4px;
      color:var(--muted);
      font-size:11px;
      font-weight:780;
      text-transform:uppercase;
    }
    input, select, textarea {
      width:100%;
      border:1px solid var(--line);
      background:#fff;
      color:var(--ink);
      font:inherit;
      font-size:13px;
      padding:8px 9px;
      outline:none;
    }
    textarea { min-height:92px; resize:vertical; line-height:1.45; }
    input:focus, select:focus, textarea:focus { box-shadow:4px 4px 0 var(--accent); }
    button {
      border:1px solid var(--line);
      background:#fff;
      color:var(--ink);
      padding:8px 11px;
      font-size:12px;
      font-weight:820;
      line-height:1.2;
      cursor:pointer;
      box-shadow:3px 3px 0 rgba(16,16,16,.13);
    }
    button:hover { background:var(--accent); }
    button.primary { background:var(--ink); color:#fff; box-shadow:4px 4px 0 var(--accent); }
    button.danger { color:var(--red); }
    .filters { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
    .filters .wide { grid-column:1 / -1; }
    .statusFilters { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:10px; }
    .statusFilters button { width:100%; }
    .statusFilters button.active { background:var(--ink); color:#fff; box-shadow:4px 4px 0 var(--accent); }
    .productList { display:flex; flex-direction:column; gap:8px; }
    .productItem {
      width:100%;
      text-align:left;
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      box-shadow:3px 3px 0 rgba(16,16,16,.1);
    }
    .productItem.active { background:var(--ink); color:#fff; }
    .productName { font-size:13px; font-weight:820; overflow-wrap:anywhere; }
    .productMeta { margin-top:4px; color:var(--muted); font-size:11px; }
    .productItem.active .productMeta { color:#d9d9d9; }
    .count { font-size:18px; font-weight:860; align-self:start; }
    .videoGrid {
      display:grid;
      grid-template-columns:repeat(auto-fill,minmax(250px,1fr));
      gap:10px;
    }
    .videoCard {
      border:1px solid var(--line);
      background:#fff;
      min-width:0;
      overflow:hidden;
      position:relative;
    }
    .videoCard.active { box-shadow:5px 5px 0 var(--accent); }
    .videoCard.selectedForQueue { outline:3px solid var(--blue); outline-offset:-3px; }
    .videoCard.published { border-color:var(--teal); }
    .publishedFlag {
      position:absolute;
      top:8px;
      left:8px;
      z-index:2;
      border:1px solid var(--line);
      background:var(--accent);
      color:var(--ink);
      padding:4px 7px;
      font-size:11px;
      font-weight:860;
      box-shadow:3px 3px 0 rgba(16,16,16,.16);
    }
    .queueFlag {
      position:absolute;
      top:8px;
      right:8px;
      z-index:2;
      border:1px solid var(--line);
      background:var(--blue);
      color:#fff;
      padding:4px 7px;
      font-size:11px;
      font-weight:860;
      box-shadow:3px 3px 0 rgba(16,16,16,.16);
    }
    .videoSelectControl {
      width:auto;
      height:30px;
      margin:0;
      padding:0 6px;
      display:flex;
      align-items:center;
      gap:5px;
      border:1px solid var(--line);
      background:#fff;
      box-shadow:none;
    }
    .videoSelectControl input { width:16px; height:16px; margin:0; accent-color:var(--blue); }
    .orderFlag {
      min-width:20px;
      height:20px;
      display:grid;
      place-items:center;
      background:var(--blue);
      color:#fff;
      font-size:10px;
      font-weight:860;
    }
    .selectionBar {
      min-height:40px;
      margin-bottom:10px;
      padding:7px 8px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      border:1px solid var(--line);
      background:var(--surface-soft);
      font-size:12px;
      font-weight:760;
    }
    .selectionBar.emptySelection { color:var(--muted); font-weight:600; }
    video { width:100%; aspect-ratio:9/12; display:block; background:#111; object-fit:cover; }
    .videoInfo { padding:9px; }
    .videoTitleRow { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:start; }
    .videoTitle { font-size:13px; font-weight:820; line-height:1.35; overflow-wrap:anywhere; }
    .chips { display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }
    .chip {
      border:1px solid var(--line);
      background:#f8f8f8;
      padding:3px 6px;
      font-size:10px;
      font-weight:760;
      color:var(--ink);
    }
    .chip.teal { color:#fff; background:var(--teal); }
    .chip.blue { color:#fff; background:var(--blue); }
    .muted { color:var(--muted); }
    .empty {
      border:1px dashed var(--line);
      padding:18px;
      background:#fff;
      color:var(--muted);
      font-size:13px;
      line-height:1.5;
    }
    .libraryBlock { margin-bottom:14px; }
    .publishBox {
      padding:12px;
      border-bottom:1px solid var(--line);
      background:#fff;
    }
    .publishActions {
      display:grid;
      grid-template-columns:minmax(0,1fr) auto auto auto auto;
      gap:8px;
      align-items:end;
      margin-top:8px;
    }
    .statusLine {
      min-height:18px;
      margin-top:8px;
      font-size:11px;
      color:var(--muted);
      line-height:1.45;
      overflow-wrap:anywhere;
    }
    .statusLine.error { color:var(--red); }
    .statusLine.ok { color:var(--teal); }
    .publishMeta {
      margin-top:8px;
      padding:8px;
      border:1px solid var(--line-soft);
      background:#fff;
      font-size:11px;
      line-height:1.55;
      color:var(--muted);
      overflow-wrap:anywhere;
    }
    .publishMeta strong { color:var(--ink); }
    .publishMeta.warn { color:var(--red); border-color:rgba(180,35,24,.45); }
    .settingsRow {
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:8px;
      margin-top:8px;
      align-items:stretch;
    }
    .optionRow {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      margin:0;
      padding:8px;
      border:1px solid var(--line-soft);
      background:#fff;
      font-size:12px;
      color:var(--ink);
    }
    .optionRow input {
      width:auto;
      margin:0;
      accent-color:#20c7d8;
    }
    .visibilityInline {
      padding:8px;
      border:1px solid var(--line-soft);
      background:#fff;
      font-size:11px;
      line-height:1.55;
      color:var(--muted);
    }
    .visibilityInline strong { color:var(--ink); }
    .libraryTitle {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      margin-bottom:8px;
    }
    .itemList { display:flex; flex-direction:column; gap:7px; }
    .copyItem {
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      align-items:start;
      border:1px solid var(--line);
      background:#fff;
      padding:8px;
      font-size:12px;
    }
    .copyText { line-height:1.4; overflow-wrap:anywhere; }
    .smallPath {
      color:var(--soft);
      font-size:11px;
      line-height:1.35;
      overflow-wrap:anywhere;
      margin-top:6px;
    }
    .chipButton {
      border:1px solid var(--line);
      background:#fff;
      padding:3px 6px;
      font-size:10px;
      font-weight:760;
      box-shadow:none;
    }
    .chipButton.danger { color:var(--red); }
    .chipButton:hover { background:#fff0f0; }
    .kv {
      display:grid;
      grid-template-columns:72px 1fr;
      gap:8px;
      padding:6px 0;
      border-bottom:1px solid var(--line-soft);
      font-size:11px;
    }
    .k { color:var(--muted); }
    .v { overflow-wrap:anywhere; }
    @media (max-width:1180px) {
      main { grid-template-columns:280px 1fr; height:auto; min-height:calc(100vh - 72px); overflow:auto; }
      section.library { grid-column:1 / -1; min-height:520px; }
    }
    @media (max-width:760px) {
      header { align-items:flex-start; flex-direction:column; padding:12px; }
      main { grid-template-columns:1fr; padding:10px; }
      section.library { grid-column:auto; }
      .filters { grid-template-columns:1fr; }
      .filters .wide { grid-column:auto; }
      .publishActions { grid-template-columns:1fr; }
      .settingsRow { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>成品管理</h1>
      <div class="sub">Finished videos · Titles · Hashtags · Local archive</div>
    </div>
    <!-- APP_HEADER_ACTIONS -->
  </header>
  <main>
    <section>
      <div class="panelHead"><h2>产品与筛选</h2></div>
      <div class="panelBody">
        <div class="filters">
          <div>
            <label>产品名称</label>
            <select id="productSelect" onchange="onProductFilterChange()"></select>
          </div>
          <div>
            <label>国家</label>
            <select id="country" onchange="render()"></select>
          </div>
        </div>
        <div class="statusFilters" aria-label="发布状态筛选">
          <button id="statusAll" class="active" onclick="setPublishStatusFilter('all')">全部</button>
          <button id="statusUnpublished" onclick="setPublishStatusFilter('unpublished')">未发布</button>
          <button id="statusPublished" onclick="setPublishStatusFilter('published')">已发布</button>
        </div>
        <div id="productList" class="productList"></div>
      </div>
    </section>
    <section>
      <div class="panelHead">
        <h2>成品视频</h2>
        <div class="panelActions">
          <button onclick="selectAllVisibleVideos()">全选</button>
          <button class="danger" onclick="deleteSelectedVideos()">批量删除</button>
          <span id="resultCount" class="muted"></span>
        </div>
      </div>
      <div class="panelBody">
        <div id="selectionBar" class="selectionBar emptySelection">勾选视频后可加入队列或批量删除。</div>
        <div id="videoGrid" class="videoGrid"></div>
      </div>
    </section>
    <section class="library">
      <div class="panelHead">
        <h2>标题与标签</h2>
      </div>
      <div class="publishBox">
        <label>比特浏览器窗口</label>
        <select id="bitProfile" onchange="onBitProfileChange()"></select>
        <div id="productIdLine" class="publishMeta">请选择视频和 TikTok 账号窗口后显示商品 ID。</div>
        <div class="settingsRow">
          <label class="optionRow">
            <span>标注为 AI 生成内容</span>
            <input id="aiGenerated" type="checkbox" checked />
          </label>
          <div class="visibilityInline"><strong>可见性</strong>：所有人</div>
        </div>
        <div class="publishActions">
          <button onclick="loadBitProfiles()">刷新窗口</button>
          <button onclick="manualUpload()">手动发布</button>
          <button onclick="autoPublish()">立即自动发布</button>
          <button class="primary" onclick="enqueueSelected()">加入队列</button>
        </div>
        <div id="publishStatus" class="statusLine">手动发布和自动发布都会从当前产品/国家标题库随机选择一条文案。</div>
      </div>
      <div id="libraryPanel" class="panelBody"></div>
    </section>
  </main>
  <script>
    let state = null;
    let selectedProduct = '';
    let selectedVideo = '';
    let selectedVideoOrder = [];
    let bitProfiles = [];
    let captionPool = [];
    let publishStatusFilter = 'all';
    let queuedVideoPaths = new Set();

    async function loadState() {
      const res = await fetch('/api/state');
      state = await res.json();
      if (!res.ok || state.error) throw new Error(state.error || '读取成品管理数据失败');
      document.getElementById('videoBadge').textContent = `视频 ${state.video_count}`;
      document.getElementById('productBadge').textContent = `产品 ${state.product_count}`;
      document.getElementById('libraryBadge').textContent = `标题库 ${state.library_count}`;
      const aiDefault = state.publish_config && state.publish_config.defaults
        ? state.publish_config.defaults.ai_generated !== false
        : true;
      document.getElementById('aiGenerated').checked = aiDefault;
      const availableIds = new Set(state.videos.map(video => video.id));
      selectedVideoOrder = selectedVideoOrder.filter(id => availableIds.has(id));
      renderProductOptions();
      renderCountryOptions();
      render();
      loadQueueSummary().catch(() => {});
      loadBitProfiles().catch(err => setPublishStatus(`比特浏览器窗口读取失败: ${err.message}`, 'error'));
    }

    function renderProductOptions() {
      const select = document.getElementById('productSelect');
      select.innerHTML = '<option value="">全部产品</option>' + state.products.map(product => {
        const meta = `${product.video_count} 视频 / ${product.title_count} 标题`;
        return `<option value="${escapeAttr(product.key)}">${escapeHtml(product.key)} · ${escapeHtml(meta)}</option>`;
      }).join('');
      if (state.products.some(product => product.key === selectedProduct)) {
        select.value = selectedProduct;
      } else {
        selectedProduct = '';
        select.value = '';
      }
    }

    function renderCountryOptions() {
      const select = document.getElementById('country');
      const current = select.value;
      const product = state.products.find(item => item.key === selectedProduct);
      const codes = product && product.countries && product.countries.length
        ? product.countries
        : state.countries.map(item => item.code);
      const options = codes.map(code => ({code, name: countryNameFromState(code)}));
      select.innerHTML = '<option value="">全部</option>' + options
        .map(c => `<option value="${escapeHtml(c.code)}">${escapeHtml(c.name)} (${escapeHtml(c.code)})</option>`)
        .join('');
      select.value = options.some(item => item.code === current) ? current : '';
    }

    async function loadBitProfiles() {
      const select = document.getElementById('bitProfile');
      const current = select.value;
      select.innerHTML = '<option value="">读取中...</option>';
      const res = await fetch('/api/bitbrowser/profiles');
      const payload = await res.json();
      if (!res.ok || payload.error) throw new Error(payload.error || '读取失败');
      bitProfiles = payload.profiles || [];
      select.innerHTML = '<option value="">选择一个 TikTok 账号窗口</option>' + bitProfiles.map(profile => {
        const label = [profile.seq ? `#${profile.seq}` : '', profile.name || profile.code || profile.id].filter(Boolean).join(' ');
        return `<option value="${escapeAttr(profile.id)}">${escapeHtml(label)}</option>`;
      }).join('');
      if (bitProfiles.some(profile => profile.id === current)) select.value = current;
      onBitProfileChange();
      setPublishStatus(`已读取当前比特浏览器子账号可见的 ${bitProfiles.length} 个窗口`, 'ok');
    }

    function onBitProfileChange() {
      renderLibrary();
      renderPublishContext();
    }

    function filteredVideos() {
      const country = document.getElementById('country').value;
      let videos = state.videos.filter(v => {
        if (selectedProduct && v.product_key !== selectedProduct) return false;
        if (country && !v.countries.includes(country)) return false;
        if (publishStatusFilter === 'published' && !v.published) return false;
        if (publishStatusFilter === 'unpublished' && v.published) return false;
        return true;
      });
      videos.sort((a,b) => b.modified.localeCompare(a.modified));
      return videos;
    }

    function render() {
      if (!state) return;
      const videos = filteredVideos();
      document.getElementById('resultCount').textContent = `${videos.length} 个结果`;
      if (!selectedVideo && videos.length) selectedVideo = videos[0].id;
      if (!videos.some(v => v.id === selectedVideo) && videos.length) selectedVideo = videos[0].id;
      renderProductCards();
      renderVideos(videos);
      renderSelectionBar();
      renderLibrary();
      renderPublishContext();
    }

    function setPublishStatusFilter(value) {
      publishStatusFilter = value;
      selectedVideo = '';
      render();
    }

    function renderPublishStatusButtons() {
      const buttons = {
        all: document.getElementById('statusAll'),
        unpublished: document.getElementById('statusUnpublished'),
        published: document.getElementById('statusPublished'),
      };
      Object.entries(buttons).forEach(([key, button]) => {
        if (!button) return;
        button.classList.toggle('active', key === publishStatusFilter);
        button.setAttribute('aria-pressed', key === publishStatusFilter ? 'true' : 'false');
      });
    }

    function videoMatchesProductCardFilter(video, productKey, country) {
      if (video.product_key !== productKey) return false;
      if (country && !video.countries.includes(country)) return false;
      if (publishStatusFilter === 'published' && !video.published) return false;
      if (publishStatusFilter === 'unpublished' && video.published) return false;
      return true;
    }

    function renderProductCards() {
      const host = document.getElementById('productList');
      const country = document.getElementById('country').value;
      renderPublishStatusButtons();
      let products = state.products;
      if (selectedProduct) {
        products = products.filter(product => product.key === selectedProduct);
      }
      if (country) {
        products = products.filter(product => (product.countries || []).includes(country));
      }
      const productRows = products.map(product => ({
        ...product,
        visible_video_count: state.videos.filter(video => videoMatchesProductCardFilter(video, product.key, country)).length,
      })).filter(product => product.visible_video_count > 0 || selectedProduct === product.key);
      host.innerHTML = productRows.map(p => `
        <button class="productItem ${p.key === selectedProduct ? 'active' : ''}" onclick="selectProduct('${escapeAttr(p.key)}')">
          <div>
            <div class="productName">${escapeHtml(p.key)}</div>
            <div class="productMeta">${escapeHtml(p.title_count + ' 标题 / 每条5标签 / ' + countryLabel(p.countries))}</div>
          </div>
          <div class="count">${p.visible_video_count}</div>
        </button>
      `).join('') || '<div class="empty">当前筛选下没有产品。</div>';
    }

    function onProductFilterChange() {
      selectedProduct = document.getElementById('productSelect').value;
      selectedVideo = '';
      renderCountryOptions();
      render();
    }

    function renderVideos(videos) {
      const host = document.getElementById('videoGrid');
      if (!videos.length) {
        host.innerHTML = '<div class="empty">当前筛选下没有成品视频。</div>';
        return;
      }
      host.innerHTML = videos.map(v => `
        <div class="videoCard ${v.id === selectedVideo ? 'active' : ''} ${v.published ? 'published' : ''} ${selectedVideoOrder.includes(v.id) ? 'selectedForQueue' : ''}" onclick="selectVideo('${escapeAttr(v.id)}')">
          ${v.published ? '<div class="publishedFlag">已发布</div>' : ''}
          ${queuedVideoPaths.has(v.path) ? '<div class="queueFlag">队列中</div>' : ''}
          <video src="${escapeAttr(v.video_url)}" preload="metadata" muted controls></video>
            <div class="videoInfo">
              <div class="videoTitleRow">
                <div class="videoTitle">${escapeHtml(v.name)}</div>
              <label class="videoSelectControl" title="勾选视频" onclick="event.stopPropagation()">${selectedVideoOrder.includes(v.id) ? `<span class="orderFlag">${selectedVideoOrder.indexOf(v.id) + 1}</span>` : ''}<input type="checkbox" ${selectedVideoOrder.includes(v.id) ? 'checked' : ''} onchange="toggleQueueVideo(event, '${escapeAttr(v.id)}')" /></label>
            </div>
            <div class="chips">
              ${(v.countries || []).map(c => `<span class="chip teal">${escapeHtml(countryName(c))}</span>`).join('')}
              ${v.mode ? `<span class="chip blue">${escapeHtml(v.mode)}</span>` : ''}
              ${v.date ? `<span class="chip">${escapeHtml(v.date)}</span>` : ''}
              <span class="chip">${escapeHtml(v.size_mb + ' MB')}</span>
              <span class="chip ${v.published ? 'teal' : ''}">${v.published ? '已发布' : '未发布'}</span>
              <button class="chipButton danger" onclick="deleteVideo(event, '${escapeAttr(v.id)}')">删除</button>
            </div>
          </div>
        </div>
      `).join('');
    }

    function selectedQueueVideos() {
      return selectedVideoOrder.map(id => state.videos.find(video => video.id === id)).filter(Boolean);
    }

    function toggleQueueVideo(event, id) {
      event.stopPropagation();
      const video = state.videos.find(item => item.id === id);
      if (!video) return;
      const index = selectedVideoOrder.indexOf(id);
      if (index >= 0) selectedVideoOrder.splice(index, 1);
      else selectedVideoOrder.push(id);
      renderVideos(filteredVideos());
      renderSelectionBar();
      renderPublishContext();
    }

    function clearQueueSelection() {
      selectedVideoOrder = [];
      renderVideos(filteredVideos());
      renderSelectionBar();
      renderPublishContext();
    }

    function selectAllVisibleVideos() {
      const known = new Set(selectedVideoOrder);
      filteredVideos().forEach(video => {
        if (!known.has(video.id)) selectedVideoOrder.push(video.id);
      });
      renderVideos(filteredVideos());
      renderSelectionBar();
      renderPublishContext();
    }

    function renderSelectionBar() {
      const host = document.getElementById('selectionBar');
      const selected = selectedQueueVideos();
      if (!selected.length) {
        host.className = 'selectionBar emptySelection';
        host.innerHTML = '勾选视频后可加入队列或批量删除。';
        return;
      }
      host.className = 'selectionBar';
      host.innerHTML = `<span>已选 ${selected.length} 个。加入队列会按卡片右上角编号执行，批量删除会删除这些视频文件。</span><button onclick="clearQueueSelection()">清空选择</button>`;
    }

    function renderLibrary() {
      const selected = state.videos.find(v => v.id === selectedVideo);
      const productKey = selectedProduct || (selected ? selected.product_key : '');
      const product = state.products.find(p => p.key === productKey);
      const host = document.getElementById('libraryPanel');
      if (!product) {
        captionPool = [];
        host.innerHTML = '<div class="empty">请选择一个产品。</div>';
        return;
      }
      const library = product.library;
      const groups = library ? currentLibraryGroups(product, library, selected) : [];
      let html = '';
      if (!library) {
        captionPool = [];
        host.innerHTML = '<div class="empty">这个产品还没有匹配到标题库 Markdown。</div>';
        return;
      }
      if (!groups.length) {
        captionPool = [];
        host.innerHTML = '<div class="empty">标题库缺少国家分组。请使用 “## 国家：英国 (UK)” 这类格式。</div>';
        return;
      }
      captionPool = groups.flatMap(group => group.items || []).map(copyValue).filter(Boolean);
      html += groups.map(group => `
        <div class="libraryBlock">
          <div class="libraryTitle">
            <h2>${escapeHtml(group.label)}</h2>
            <span class="muted">${group.items.length} 条</span>
          </div>
          ${renderTitleTagList(group.items)}
        </div>
      `).join('');
      host.innerHTML = html;
    }

    function currentLibraryGroups(product, library, selected) {
      const byCountry = library.by_country || {};
      const countryCodes = Object.keys(byCountry);
      if (!countryCodes.length) return [];
      const profile = selectedProfileItem();
      const profileCodes = profile && profile.country && byCountry[profile.country] ? [profile.country] : [];
      const selectedCodes = selected && selected.countries && selected.countries.length
        ? selected.countries.filter(code => byCountry[code])
        : [];
      const productCodes = product.countries.filter(code => byCountry[code]);
      const visibleCodes = profileCodes.length ? profileCodes : (selectedCodes.length ? selectedCodes : productCodes);
      const codes = visibleCodes.length ? visibleCodes : countryCodes;
      return codes.map(code => ({
        label: countryName(code),
        items: byCountry[code].items || [],
      }));
    }

    function renderTitleTagList(items) {
      if (!items.length) return '<div class="empty">暂无标题标签。</div>';
      return `
        <div class="itemList">
          ${items.map(item => `
            <div class="copyItem titleTagItem">
              <div>
                <div class="copyText">${escapeHtml(copyValue(item))}</div>
                ${item.translation ? `<div class="smallPath">${escapeHtml(item.translation)}</div>` : ''}
              </div>
              <button data-copy="${escapeAttr(copyValue(item))}" onclick="copyText(this.dataset.copy)">复制</button>
            </div>
          `).join('')}
        </div>
      `;
    }

    function copyValue(item) {
      return item.full_text || [item.text, ...((item.tags || []).filter(Boolean))].join(' ');
    }

    function selectedVideoItem() {
      return state && state.videos ? state.videos.find(v => v.id === selectedVideo) : null;
    }

    function selectedProfileItem() {
      const profileId = document.getElementById('bitProfile').value;
      return bitProfiles.find(profile => profile.id === profileId) || null;
    }

    function productIdFor(video, profileId) {
      if (!video || !profileId) return '';
      const config = state.publish_config || {};
      const country = (video.countries || [])[0] || '';
      const profile = selectedProfileItem();
      const storeName = profile ? (profile.store_name || '') : '';
      const accountType = profile ? (profile.account_type || '') : '';
      const productLinksByStore = config.product_links_by_store || {};
      const storeLinks = (((productLinksByStore[video.product_code] || {})[country] || {})[storeName] || {});
      if (accountType && storeLinks[accountType]) return storeLinks[accountType];
      if (storeLinks['*']) return storeLinks['*'];
      const productLinks = config.product_links || {};
      return (((productLinks[video.product_code] || {})[country] || {})[profileId]) || '';
    }

    function productShortNameFor(video) {
      if (!video) return '';
      const country = (video.countries || [])[0] || '';
      const shortNames = (state.publish_config || {}).product_short_names || {};
      return ((shortNames[video.product_code] || {})[country]) || '';
    }

    function renderPublishContext() {
      if (!state) return;
      const host = document.getElementById('productIdLine');
      const video = selectedVideoItem();
      const profileId = document.getElementById('bitProfile').value;
      const profile = selectedProfileItem();
      const batchVideos = selectedQueueVideos();
      if (batchVideos.length) {
        if (!profileId || !profile) {
          host.className = 'publishMeta warn';
          host.innerHTML = `已选 <strong>${batchVideos.length}</strong> 个视频。请选择这一批任务使用的 TikTok 账号窗口。`;
          return;
        }
        const invalid = batchVideos.filter(item => {
          const country = (item.countries || [])[0] || '';
          return item.published || country !== profile.country || !productIdFor(item, profileId) || !productShortNameFor(item);
        });
        host.className = `publishMeta ${invalid.length ? 'warn' : ''}`;
        host.innerHTML = `<strong>批量任务</strong>：${batchVideos.length} 个视频<br><strong>窗口</strong>：${escapeHtml(profile.name)}<br><strong>校验</strong>：${invalid.length ? `${invalid.length} 个视频的国家或商品映射不完整` : '可以加入队列'}<br><strong>间隔</strong>：每个任务完成后 10 秒`;
        return;
      }
      if (!video || !profileId) {
        host.className = 'publishMeta';
        host.innerHTML = '请选择视频和 TikTok 账号窗口后显示商品 ID。';
        return;
      }
      const country = (video.countries || [])[0] || '';
      const productId = productIdFor(video, profileId);
      const productShortName = productShortNameFor(video);
      const accountName = profile ? profile.name : profileId;
      const storeName = profile ? (profile.store_name || '未解析店铺') : '';
      const accountType = profile ? (profile.account_type || '未解析账号类型') : '';
      if (!productId) {
        host.className = 'publishMeta warn';
        host.innerHTML = `<strong>商品 ID 未配置</strong>：${escapeHtml(video.product_code)} / ${escapeHtml(country || '未识别国家')} / ${escapeHtml(storeName)} / ${escapeHtml(accountType)}。请先补充商品 ID 映射。`;
        return;
      }
      if (!productShortName) {
        host.className = 'publishMeta warn';
        host.innerHTML = `<strong>商品简称未配置</strong>：${escapeHtml(video.product_code)} / ${escapeHtml(country || '未识别国家')}。请先到商品映射库补充不超过 30 个字符的商品简称。`;
        return;
      }
      host.className = 'publishMeta';
      host.innerHTML = `<strong>商品 ID</strong>：${escapeHtml(productId)}<br><strong>商品简称</strong>：${escapeHtml(productShortName)}<br><strong>店铺</strong>：${escapeHtml(storeName)}<br><strong>账号类型</strong>：${escapeHtml(accountType)}<br><strong>产品/国家</strong>：${escapeHtml(video.product_code)} / ${escapeHtml(country)}<br><strong>窗口</strong>：${escapeHtml(accountName)}`;
    }

    function selectProduct(key) {
      selectedProduct = key;
      selectedVideo = '';
      const productSelect = document.getElementById('productSelect');
      if (productSelect) productSelect.value = selectedProduct;
      renderCountryOptions();
      render();
    }

    function selectVideo(id) {
      selectedVideo = id;
      render();
    }

    async function copyText(text) {
      await navigator.clipboard.writeText(text);
    }

    async function deleteVideo(event, id) {
      event.stopPropagation();
      const video = state.videos.find(v => v.id === id);
      if (!video) return;
      const ok = window.confirm(`确认删除这个成品视频？\n\n${video.name}`);
      if (!ok) return;
      const res = await fetch('/api/video/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({video_path: video.path}),
      });
      const payload = await res.json();
      if (!res.ok || payload.error) {
        setPublishStatus(payload.error || '删除失败', 'error');
        return;
      }
      if (selectedVideo === id) selectedVideo = '';
      setPublishStatus(`已删除: ${video.name}`, 'ok');
      await loadState();
    }

    async function deleteSelectedVideos() {
      const videos = selectedQueueVideos();
      if (!videos.length) return setPublishStatus('请先勾选要删除的视频。', 'error');
      const preview = videos.slice(0, 8).map(video => `- ${video.name}`).join('\n');
      const more = videos.length > 8 ? `\n... 还有 ${videos.length - 8} 个` : '';
      const ok = window.confirm(`确认批量删除 ${videos.length} 个成品视频？\n删除后文件会从本地成品视频目录移除。\n\n${preview}${more}`);
      if (!ok) return;
      setPublishStatus(`正在删除 ${videos.length} 个视频...`, '');
      let deleted = 0;
      for (const video of videos) {
        const res = await fetch('/api/video/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({video_path: video.path}),
        });
        const payload = await res.json();
        if (!res.ok || payload.error) {
          setPublishStatus(`批量删除中断：${video.name}，${payload.error || '删除失败'}`, 'error');
          await loadState();
          return;
        }
        deleted += 1;
      }
      selectedVideo = '';
      selectedVideoOrder = [];
      setPublishStatus(`已批量删除 ${deleted} 个视频。`, 'ok');
      await loadState();
    }

    function randomCaptionForSelected() {
      if (!captionPool.length) {
        throw new Error('当前视频没有可用标题标签。');
      }
      const index = Math.floor(Math.random() * captionPool.length);
      return captionPool[index];
    }

    function captionPoolForVideo(video, profile) {
      const product = state.products.find(item => item.key === video.product_key);
      const byCountry = product && product.library ? (product.library.by_country || {}) : {};
      const videoCountry = (video.countries || [])[0] || '';
      const country = profile && byCountry[profile.country] ? profile.country : videoCountry;
      const group = byCountry[country];
      return group ? (group.items || []).map(copyValue).filter(Boolean) : [];
    }

    function randomCaptionForVideo(video, profile) {
      const pool = captionPoolForVideo(video, profile);
      if (!pool.length) throw new Error(`没有可用文案：${video.name}`);
      return pool[Math.floor(Math.random() * pool.length)];
    }

    async function loadQueueSummary() {
      const res = await fetch('/api/queue');
      const payload = await res.json();
      if (!res.ok || payload.error) throw new Error(payload.error || '读取队列失败');
      const waiting = Number((payload.counts || {}).pending || 0);
      const running = Number((payload.counts || {}).running || 0);
      queuedVideoPaths = new Set((payload.tasks || [])
        .filter(task => task.status === 'pending' || task.status === 'running')
        .map(task => task.video_path)
        .filter(Boolean));
      document.getElementById('queueBadge').textContent = `发布队列 ${waiting + running}`;
      if (state) renderVideos(filteredVideos());
    }

    async function enqueueSelected() {
      const videos = selectedQueueVideos();
      const profileId = document.getElementById('bitProfile').value;
      const profile = selectedProfileItem();
      if (!videos.length) return setPublishStatus('请勾选至少一个未发布视频。', 'error');
      if (!profileId || !profile) return setPublishStatus('请选择一个比特浏览器窗口。', 'error');

      const tasks = [];
      for (const video of videos) {
        const country = (video.countries || [])[0] || '';
        if (video.published) return setPublishStatus(`已发布视频不能入队：${video.name}`, 'error');
        if (country !== profile.country) return setPublishStatus(`账号国家与视频不匹配：${profile.country} / ${country}`, 'error');
        if (!productIdFor(video, profileId)) return setPublishStatus(`商品 ID 未配置：${video.product_code} / ${country}`, 'error');
        if (!productShortNameFor(video)) return setPublishStatus(`商品简称未配置：${video.product_code} / ${country}`, 'error');
        let caption = '';
        try { caption = randomCaptionForVideo(video, profile); }
        catch (err) { return setPublishStatus(err.message, 'error'); }
        tasks.push({video_path: video.path, caption});
      }

      if (!window.confirm(`按当前顺序加入 ${tasks.length} 个自动发布任务？\n账号：${profile.name}\n任务间隔：10 秒\n\n加入后处于待执行状态，不会立即发布。`)) return;
      setPublishStatus(`正在加入 ${tasks.length} 个队列任务...`, '');
      const res = await fetch('/api/queue/enqueue', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          profile_id:profileId,
          tasks,
          ai_generated:document.getElementById('aiGenerated').checked,
        }),
      });
      const payload = await res.json();
      if (!res.ok || payload.error) return setPublishStatus(payload.error || '加入队列失败', 'error');
      selectedVideoOrder = [];
      renderVideos(filteredVideos());
      renderSelectionBar();
      renderPublishContext();
      await loadQueueSummary();
      setPublishStatus(`已加入 ${tasks.length} 个待执行任务。请前往发布队列选择“可视执行”或“后台执行”。`, 'ok');
    }

    function setPublishStatus(text, kind = '') {
      const host = document.getElementById('publishStatus');
      host.textContent = text;
      host.className = `statusLine ${kind}`;
    }

    async function manualUpload() {
      const profileId = document.getElementById('bitProfile').value;
      const video = selectedVideoItem();
      if (!video) {
        setPublishStatus('请先选择一个成品视频。', 'error');
        return;
      }
      if (!profileId) {
        setPublishStatus('请先选择一个比特浏览器窗口。', 'error');
        return;
      }
      let caption = '';
      try {
        caption = randomCaptionForSelected();
      } catch (err) {
        setPublishStatus(err.message, 'error');
        return;
      }
      setPublishStatus('正在手动发布：随机选择文案、上传视频并填写文案，后续步骤由你手动处理...', '');
      const res = await fetch('/api/tiktok/manual-upload', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          profile_id: profileId,
          video_path: video.path,
          caption,
        }),
      });
      const payload = await res.json();
      if (!res.ok || payload.error) {
        setPublishStatus(payload.error || '手动发布准备失败', 'error');
        return;
      }
      setPublishStatus('已上传视频并填写文案，AI 标识、商品链接和最终发布请手动完成。', 'ok');
    }

    async function autoPublish() {
      const profileId = document.getElementById('bitProfile').value;
      const video = selectedVideoItem();
      if (!video) {
        setPublishStatus('请先选择一个成品视频。', 'error');
        return;
      }
      if (!profileId) {
        setPublishStatus('请先选择一个比特浏览器窗口。', 'error');
        return;
      }
      const productId = productIdFor(video, profileId);
      if (!productId) {
        setPublishStatus('当前视频和账号没有配置商品 ID，已停止发布。', 'error');
        renderPublishContext();
        return;
      }
      const productShortName = productShortNameFor(video);
      if (!productShortName) {
        setPublishStatus('当前产品和国家没有配置商品简称，已停止发布。', 'error');
        renderPublishContext();
        return;
      }
      let caption = '';
      try {
        caption = randomCaptionForSelected();
      } catch (err) {
        setPublishStatus(err.message, 'error');
        return;
      }
      setPublishStatus('正在执行完整发布：随机选择文案、上传视频、填写文案、挂商品、确认设置并发布...', '');
      const res = await fetch('/api/tiktok/publish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          profile_id: profileId,
          video_path: video.path,
          caption,
          product_id: productId,
          product_short_name: productShortName,
          ai_generated: document.getElementById('aiGenerated').checked,
          visibility: 'public',
        }),
      });
      const payload = await res.json();
      if (!res.ok || payload.error) {
        setPublishStatus(payload.error || '发布失败', 'error');
        return;
      }
      setPublishStatus(`${payload.message} 商品：${payload.product_name || productId}`, 'ok');
      await loadState();
    }

    function countryName(code) {
      const name = countryNameFromState(code);
      return name ? `${name} (${code})` : code;
    }

    function countryNameFromState(code) {
      const item = state.countries.find(c => c.code === code);
      const known = {
        US:'美国', UK:'英国', GB:'英国', TH:'泰国', BR:'巴西',
        VN:'越南', ID:'印度尼西亚', MY:'马来西亚', PH:'菲律宾',
        SG:'新加坡', JP:'日本', MX:'墨西哥', ES:'西班牙',
        DE:'德国', FR:'法国', IT:'意大利', IE:'爱尔兰'
      };
      return item ? item.name : (known[code] || code);
    }

    function countryLabel(codes) {
      if (!codes || !codes.length) return '未识别';
      return codes.map(countryName).join(' / ');
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }

    function escapeAttr(value) {
      return escapeHtml(value).replace(/`/g, '&#96;');
    }

    loadState().catch(err => {
      document.body.innerHTML = `<pre>页面初始化失败: ${escapeHtml(err.message)}</pre>`;
    });
  </script>
</body>
</html>"""


DAILY_KPI_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>每日发布 KPI</title>
  <style>
    :root { --bg:#f6f3ea; --surface:#fffdf7; --soft:#eee9dd; --ink:#101010; --muted:#666157; --line:#151515; --accent:#d9ff63; --teal:#0e766e; --red:#b42318; --blue:#2463eb; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"PingFang SC",sans-serif; font-size:13px; }
    header { min-height:72px; padding:12px 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; border-bottom:1px solid var(--line); background:var(--surface); }
    h1 { margin:0; font-size:24px; }
    .sub { margin-top:5px; color:var(--muted); font-size:12px; }
    nav, .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    button, a.button { border:1px solid var(--line); background:#fff; color:var(--ink); padding:8px 11px; font-weight:800; font-size:12px; text-decoration:none; cursor:pointer; box-shadow:3px 3px 0 rgba(16,16,16,.12); }
    button:hover, a.button:hover { background:var(--accent); }
    button.primary { background:var(--ink); color:#fff; box-shadow:4px 4px 0 var(--accent); }
    button.danger { color:var(--red); }
    main { min-width:0; padding:16px; display:grid; gap:14px; }
    section { min-width:0; border:1px solid var(--line); background:var(--surface); }
    .sectionHead { min-height:42px; padding:9px 12px; display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); background:var(--soft); }
    .sectionHead h2 { margin:0; font-size:14px; }
    .filters { padding:12px; display:grid; grid-template-columns:minmax(150px,1fr) minmax(130px,1fr) minmax(130px,1fr) minmax(130px,1fr) auto auto; gap:10px; align-items:end; }
    label { display:block; margin-bottom:4px; color:var(--muted); font-size:11px; font-weight:800; }
    input, select { width:100%; height:36px; border:1px solid var(--line); background:#fff; color:var(--ink); padding:7px 9px; font:inherit; }
    .statusLine { min-height:20px; padding:0 12px 10px; color:var(--teal); font-size:12px; }
    .statusLine.error { color:var(--red); }
    .summary { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); }
    .metric { min-height:78px; padding:12px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    .metricLabel { color:var(--muted); font-size:11px; font-weight:800; }
    .metricValue { margin-top:7px; font-size:22px; font-weight:900; }
    .tableWrap { min-width:0; max-width:100%; overflow:auto; }
    table { width:100%; min-width:1100px; border-collapse:collapse; }
    th, td { padding:9px 8px; text-align:left; vertical-align:middle; border-bottom:1px solid rgba(16,16,16,.16); }
    th { background:var(--soft); font-size:11px; white-space:nowrap; }
    .kpiTable td { height:54px; }
    .status { display:inline-block; min-width:46px; padding:3px 6px; border:1px solid var(--line); font-size:10px; font-weight:900; text-align:center; white-space:nowrap; }
    .status.met { background:var(--teal); color:#fff; }
    .status.unmet { background:#fff0f0; color:var(--red); }
    .windowName { max-width:330px; font-weight:780; overflow-wrap:anywhere; }
    .muted { color:var(--muted); font-size:11px; }
    .number { font-size:17px; font-weight:900; }
    .progressTrack { width:150px; height:9px; border:1px solid var(--line); background:#fff; overflow:hidden; }
    .progressFill { height:100%; background:var(--blue); }
    .recordVideo { max-width:360px; overflow-wrap:anywhere; }
    .empty { padding:28px; color:var(--muted); text-align:center; }
    @media (max-width:900px) { header { align-items:flex-start; flex-direction:column; } .filters { grid-template-columns:1fr 1fr; } .summary { grid-template-columns:1fr 1fr; } .metric { border-bottom:1px solid var(--line); } .metric:last-child { grid-column:1 / -1; } }
    @media (max-width:560px) { main { padding:10px; } .filters { grid-template-columns:1fr; } .summary { grid-template-columns:1fr 1fr; } }
  </style>
</head>
<body>
  <header>
    <div><h1>每日发布 KPI</h1><div class="sub">按比特浏览器窗口核对日发目标与发布明细</div></div>
    <!-- APP_HEADER_ACTIONS -->
  </header>
  <main>
    <section>
      <div class="filters">
        <div><label>统计日期</label><input id="selectedDate" type="date" onchange="loadKpis()" /></div>
        <div><label>每窗口日目标</label><input id="dailyTarget" type="number" min="1" max="100" step="1" value="3" /></div>
        <div><label>国家</label><select id="countryFilter" onchange="renderKpiRows()"><option value="">全部国家</option></select></div>
        <div><label>达标状态</label><select id="statusFilter" onchange="renderKpiRows()"><option value="">全部状态</option><option value="unmet">未达标</option><option value="met">已达标</option></select></div>
        <button class="primary" onclick="saveTarget()">保存目标</button>
        <button onclick="setToday()">回到今天</button>
      </div>
      <div id="statusLine" class="statusLine"></div>
    </section>

    <section>
      <div class="summary">
        <div class="metric"><div class="metricLabel">窗口总数</div><div id="accountCount" class="metricValue">0</div></div>
        <div class="metric"><div class="metricLabel">已达标</div><div id="metCount" class="metricValue">0</div></div>
        <div class="metric"><div class="metricLabel">未达标</div><div id="unmetCount" class="metricValue">0</div></div>
        <div class="metric"><div class="metricLabel">当日发布</div><div id="publishedCount" class="metricValue">0</div></div>
        <div class="metric"><div class="metricLabel">总体完成率</div><div id="overallRate" class="metricValue">0%</div></div>
      </div>
    </section>

    <section>
      <div class="sectionHead"><h2>窗口达标情况</h2><span id="kpiCount" class="muted"></span></div>
      <div class="tableWrap">
        <table class="kpiTable">
          <thead><tr><th>#</th><th>状态</th><th>比特浏览器窗口</th><th>国家</th><th>店铺</th><th>账号类型</th><th>已发布</th><th>目标</th><th>还差</th><th>完成率</th></tr></thead>
          <tbody id="kpiRows"></tbody>
        </table>
      </div>
    </section>

    <section>
      <div class="sectionHead"><h2>发布明细</h2><span id="recordCount" class="muted"></span></div>
      <div class="tableWrap">
        <table>
          <thead><tr><th>#</th><th>时间</th><th>账号</th><th>方式</th><th>产品/国家</th><th>商品 ID</th><th>视频文件</th><th>操作</th></tr></thead>
          <tbody id="recordRows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    let kpiData = null;

    async function loadKpis() {
      const dateValue = document.getElementById('selectedDate').value;
      const url = '/api/daily-kpis' + (dateValue ? `?date=${encodeURIComponent(dateValue)}` : '');
      const res = await fetch(url);
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '读取每日 KPI 失败', true);
      kpiData = body;
      document.getElementById('selectedDate').value = body.date;
      document.getElementById('dailyTarget').value = body.target_per_account;
      renderCountryOptions();
      renderSummary();
      renderKpiRows();
      renderRecords();
      setStatus(body.warning || `已读取 ${body.summary.account_count} 个窗口。`, Boolean(body.warning));
    }

    function renderCountryOptions() {
      const select = document.getElementById('countryFilter');
      const selected = select.value;
      select.innerHTML = '<option value="">全部国家</option>' + (kpiData.countries || []).map(code => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`).join('');
      if ((kpiData.countries || []).includes(selected)) select.value = selected;
    }

    function renderSummary() {
      const summary = kpiData.summary || {};
      document.getElementById('accountCount').textContent = summary.account_count || 0;
      document.getElementById('metCount').textContent = summary.met_count || 0;
      document.getElementById('unmetCount').textContent = summary.unmet_count || 0;
      document.getElementById('publishedCount').textContent = `${summary.total_published || 0} / ${summary.total_target || 0}`;
      document.getElementById('overallRate').textContent = `${formatRate(summary.completion_rate)}%`;
    }

    function filteredKpiRows() {
      const country = document.getElementById('countryFilter').value;
      const status = document.getElementById('statusFilter').value;
      return (kpiData.rows || []).filter(row => (!country || row.country === country) && (!status || (status === 'met') === Boolean(row.met)));
    }

    function renderKpiRows() {
      if (!kpiData) return;
      const rows = filteredKpiRows();
      document.getElementById('kpiCount').textContent = `${rows.length} 个窗口`;
      document.getElementById('kpiRows').innerHTML = rows.length ? rows.map((row, index) => {
        const rateWidth = Math.min(100, Number(row.completion_rate || 0));
        return `<tr>
          <td>${index + 1}</td>
          <td><span class="status ${row.met ? 'met' : 'unmet'}">${row.met ? '达标' : '未达标'}</span></td>
          <td><div class="windowName">${escapeHtml(row.name)}</div><div class="muted">${escapeHtml(row.account_name || '')}${row.live ? '' : ' · 历史账号'}</div></td>
          <td>${escapeHtml(row.country || '未识别')}</td><td>${escapeHtml(row.store_name || '-')}</td><td>${escapeHtml(row.account_type || '-')}</td>
          <td class="number">${row.published}</td><td>${row.target}</td><td>${row.remaining}</td>
          <td><div>${formatRate(row.completion_rate)}%</div><div class="progressTrack"><div class="progressFill" style="width:${rateWidth}%"></div></div></td>
        </tr>`;
      }).join('') : '<tr><td colspan="10" class="empty">当前筛选下没有窗口。</td></tr>';
    }

    function renderRecords() {
      const rows = kpiData.records || [];
      document.getElementById('recordCount').textContent = `${rows.length} 条`;
      document.getElementById('recordRows').innerHTML = rows.length ? rows.map((row, index) => `<tr>
        <td>${index + 1}</td><td>${escapeHtml(row.published_at || '')}</td><td>${escapeHtml(row.account_name || row.profile_id || '')}</td>
        <td>${row.publish_mode === 'manual' ? '手动' : '自动'}</td><td>${escapeHtml(row.product_code || '')} / ${escapeHtml(row.country || '')}</td>
        <td>${escapeHtml(row.product_id || '')}</td><td class="recordVideo">${escapeHtml(row.video_name || '')}</td>
        <td><button class="danger" onclick="deleteRecord(${row.record_index})">删除记录</button></td>
      </tr>`).join('') : '<tr><td colspan="8" class="empty">所选日期没有发布记录。</td></tr>';
    }

    async function saveTarget() {
      const target = Number(document.getElementById('dailyTarget').value);
      const res = await fetch('/api/daily-kpis/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target_per_account:target})});
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '保存失败', true);
      setStatus(`已将每窗口日目标设置为 ${body.target_per_account} 条。`);
      await loadKpis();
    }

    async function deleteRecord(recordIndex) {
      if (!confirm('确认删除这条发布记录？这不会删除视频文件。')) return;
      const res = await fetch('/api/records/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({index:recordIndex})});
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '删除失败', true);
      await loadKpis();
    }

    function setToday() { document.getElementById('selectedDate').value = ''; loadKpis(); }
    function setStatus(text, error=false) { const el=document.getElementById('statusLine'); el.textContent=text; el.className=`statusLine ${error ? 'error' : ''}`; }
    function formatRate(value) { return Number(value || 0).toFixed(1).replace(/\.0$/, ''); }
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
    loadKpis().catch(err => setStatus(err.message, true));
  </script>
</body>
</html>"""


PRODUCT_ID_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>商品 ID 映射表</title>
  <style>
    body { margin:0; background:#f6f3ea; color:#101010; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 22px; border-bottom:1px solid #111; background:#fffdf7; }
    h1 { margin:0; font-size:22px; }
    main { padding:16px; }
    a, button { color:#101010; }
    .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    button { border:1px solid #111; background:#fff; padding:8px 12px; font-weight:800; cursor:pointer; box-shadow:3px 3px 0 rgba(16,16,16,.13); }
    button.primary { background:#101010; color:#fff; box-shadow:4px 4px 0 #d9ff63; }
    button.danger { color:#b42318; }
    section { border:1px solid #111; background:#fffdf7; margin-bottom:14px; }
    .head { padding:10px 12px; border-bottom:1px solid #111; background:#eee9dd; font-weight:850; }
    .body { padding:12px; overflow:auto; }
    label { display:block; font-size:11px; font-weight:800; color:#5e5a51; margin-bottom:4px; }
    input, select { width:100%; border:1px solid #111; padding:8px; font:inherit; box-sizing:border-box; }
    .grid { display:grid; grid-template-columns:repeat(7,minmax(120px,1fr)) auto; gap:10px; align-items:end; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { border-bottom:1px solid rgba(16,16,16,.16); padding:8px; text-align:left; vertical-align:top; }
    th { background:#eee9dd; font-size:11px; text-transform:uppercase; }
    .muted { color:#5e5a51; font-size:12px; overflow-wrap:anywhere; }
    .status { min-height:18px; margin-top:8px; font-size:12px; color:#0e766e; }
    .status.error { color:#b42318; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>商品 ID 映射表</h1>
      <div class="muted" id="configPath"></div>
    </div>
    <!-- APP_HEADER_ACTIONS -->
  </header>
  <main>
    <section>
      <div class="head">新增 / 更新映射</div>
      <div class="body">
        <div class="grid">
          <div><label>产品</label><select id="productCode" onchange="fillShortNameFromExisting()"></select></div>
          <div><label>比特窗口</label><select id="profileSelect" onchange="fillFromProfile()"></select></div>
          <div><label>国家</label><input id="country" readonly placeholder="自动填入" /></div>
          <div><label>店铺名称</label><input id="storeName" readonly placeholder="自动填入" /></div>
          <div><label>账号类型</label><input id="accountType" readonly placeholder="自动填入" /></div>
          <div><label>商品 ID</label><input id="productId" placeholder="1735..." /></div>
          <div><label>商品简称（最多 30 字符）</label><input id="productShortName" maxlength="30" placeholder="按产品和国家共用" /></div>
          <button class="primary" onclick="saveRow()">保存</button>
        </div>
        <div id="status" class="status"></div>
      </div>
    </section>
    <section>
      <div class="head">映射列表</div>
      <div class="body">
        <table>
          <thead><tr><th>产品</th><th>国家</th><th>店铺名称</th><th>账号类型</th><th>商品 ID</th><th>商品简称</th><th>操作</th></tr></thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    let rows = [];
    let groupedRows = [];
    let products = [];
    let bitProfiles = [];
    async function loadRows() {
      const res = await fetch('/api/product-ids');
      const payload = await res.json();
      rows = payload.rows || [];
      products = payload.products || [];
      document.getElementById('configPath').textContent = payload.config_path || '';
      renderProductOptions();
      await loadProfiles();
      groupedRows = groupProductIdRows(rows);
      document.getElementById('rows').innerHTML = groupedRows.map((row, index) => `
        <tr>
          <td>${escapeHtml(productLabel(row.product_code))}</td>
          <td>${escapeHtml(row.country)}</td>
          <td>${escapeHtml(row.store_name || '')}</td>
          <td>${escapeHtml(row.account_type_label || row.account_type || '')}</td>
          <td>${escapeHtml(row.product_id)}</td>
          <td>${escapeHtml(row.product_short_name || '')}</td>
          <td>
            <button onclick="editRow(${index})">编辑</button>
            <button class="danger" onclick="deleteRow(${index})">删除</button>
          </td>
        </tr>
      `).join('');
    }
    function groupProductIdRows(sourceRows) {
      const groups = new Map();
      for (const row of sourceRows) {
        const key = [row.product_code, row.country, row.store_name || '', row.product_id || ''].join('||');
        if (!groups.has(key)) {
          groups.set(key, {
            ...row,
            children: [],
            account_types: [],
          });
        }
        const group = groups.get(key);
        group.children.push(row);
        const accountType = row.account_type || '*';
        if (!group.account_types.includes(accountType)) group.account_types.push(accountType);
      }
      return Array.from(groups.values()).map(group => ({
        ...group,
        account_type_label: group.account_types
          .map(value => value === '*' ? '全部账号类型' : value)
          .join('/'),
      }));
    }
    function renderProductOptions() {
      const select = document.getElementById('productCode');
      const current = select.value;
      const productOptions = products.length
        ? products.map(product => {
            const code = product.code || product.key || '';
            const name = product.name || product.key || '';
            return { code, label: `${code} - ${name}` };
          })
        : uniqueRows().map(row => ({ code: row.product_code, label: row.product_code }));
      select.innerHTML = productOptions.map(item => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.label)}</option>`).join('');
      if (productOptions.some(item => item.code === current)) select.value = current;
      else if (productOptions.length) select.value = productOptions[0].code;
    }
    function productLabel(code) {
      const product = products.find(item => (item.code || item.key || '') === code);
      if (!product) return code || '';
      return `${product.code || product.key || ''} - ${product.name || product.key || ''}`;
    }
    function uniqueRows() {
      const seen = new Set();
      return rows.filter(row => {
        if (seen.has(row.product_code)) return false;
        seen.add(row.product_code);
        return true;
      });
    }
    async function loadProfiles() {
      const select = document.getElementById('profileSelect');
      const current = select.value;
      select.innerHTML = '<option value="">读取窗口中...</option>';
      try {
        const res = await fetch('/api/bitbrowser/profiles');
        const payload = await res.json();
        if (!res.ok || payload.error) throw new Error(payload.error || '读取失败');
        bitProfiles = payload.profiles || [];
        select.innerHTML = '<option value="">选择一个比特窗口</option>' + bitProfiles.map(profile => {
          const label = [profile.seq ? `#${profile.seq}` : '', profile.name || profile.id].filter(Boolean).join(' ');
          return `<option value="${escapeHtml(profile.id)}">${escapeHtml(label)}</option>`;
        }).join('');
        if (bitProfiles.some(profile => profile.id === current)) select.value = current;
        else if (bitProfiles.length) select.value = bitProfiles[0].id;
        fillFromProfile();
      } catch (error) {
        bitProfiles = [];
        select.innerHTML = '<option value="">比特窗口读取失败</option>';
        setStatus(`比特窗口读取失败: ${error.message}`, true);
      }
    }
    function fillFromProfile() {
      const profileId = document.getElementById('profileSelect').value;
      const profile = bitProfiles.find(item => item.id === profileId);
      document.getElementById('country').value = profile ? (profile.country || '') : '';
      document.getElementById('storeName').value = profile ? (profile.store_name || '') : '';
      document.getElementById('accountType').value = profile ? (profile.account_type || '') : '';
      fillShortNameFromExisting();
    }
    function fillShortNameFromExisting() {
      const productCode = document.getElementById('productCode').value;
      const country = document.getElementById('country').value;
      const existing = rows.find(row => row.product_code === productCode && row.country === country && row.product_short_name);
      document.getElementById('productShortName').value = existing ? existing.product_short_name : '';
    }
    function editRow(index) {
      const row = (groupedRows[index] && groupedRows[index].children[0]) || groupedRows[index] || rows[index];
      document.getElementById('productCode').value = row.product_code || '';
      const profile = bitProfiles.find(item =>
        item.country === row.country &&
        item.store_name === row.store_name &&
        item.account_type === row.account_type
      );
      document.getElementById('profileSelect').value = profile ? profile.id : '';
      if (profile) fillFromProfile();
      else {
        document.getElementById('country').value = row.country || '';
        document.getElementById('storeName').value = row.store_name || '';
        document.getElementById('accountType').value = row.account_type === '*' ? '' : (row.account_type || '');
      }
      document.getElementById('productId').value = row.product_id || '';
      document.getElementById('productShortName').value = row.product_short_name || '';
      setStatus('已载入，可修改后保存。');
    }
    async function saveRow() {
      const payload = {
        product_code: document.getElementById('productCode').value,
        country: document.getElementById('country').value,
        store_name: document.getElementById('storeName').value,
        account_type: document.getElementById('accountType').value,
        product_id: document.getElementById('productId').value,
        product_short_name: document.getElementById('productShortName').value,
      };
      const res = await fetch('/api/product-ids/upsert', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '保存失败', true);
      setStatus('已保存。');
      await loadRows();
    }
    async function deleteRow(index) {
      const row = groupedRows[index];
      if (!confirm(`确认删除映射？\n${row.product_code} / ${row.country} / ${row.store_name} / ${row.account_type_label || row.account_type} / ${row.product_id}`)) return;
      const targets = row.children && row.children.length ? row.children : [row];
      for (const target of targets) {
        const res = await fetch('/api/product-ids/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(target)});
        const body = await res.json();
        if (!res.ok || body.error) return setStatus(body.error || '删除失败', true);
      }
      setStatus('已删除。');
      await loadRows();
    }
    function setStatus(text, error=false) {
      const el = document.getElementById('status');
      el.textContent = text;
      el.className = `status ${error ? 'error' : ''}`;
    }
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    loadRows().catch(err => setStatus(err.message, true));
  </script>
</body>
</html>"""


RECORDS_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>发布记录表</title>
  <style>
    body { margin:0; background:#f6f3ea; color:#101010; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 22px; border-bottom:1px solid #111; background:#fffdf7; }
    h1 { margin:0; font-size:22px; }
    main { padding:16px; }
    button { border:1px solid #111; background:#fff; padding:8px 12px; font-weight:800; cursor:pointer; box-shadow:3px 3px 0 rgba(16,16,16,.13); }
    button.danger { color:#b42318; }
    section { border:1px solid #111; background:#fffdf7; }
    .head { padding:10px 12px; border-bottom:1px solid #111; background:#eee9dd; font-weight:850; display:flex; justify-content:space-between; gap:10px; }
    .body { padding:12px; overflow:auto; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { border-bottom:1px solid rgba(16,16,16,.16); padding:8px; text-align:left; vertical-align:top; }
    th { background:#eee9dd; font-size:11px; text-transform:uppercase; white-space:nowrap; }
    .muted { color:#5e5a51; font-size:12px; overflow-wrap:anywhere; }
    .status { min-height:18px; margin-top:8px; font-size:12px; color:#0e766e; }
    .status.error { color:#b42318; }
    .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>发布记录表</h1>
      <div class="muted" id="recordsPath"></div>
    </div>
    <div class="actions">
      <a href="/"><button>成品管理</button></a>
      <a href="/product-id"><button>商品 ID 映射</button></a>
      <button onclick="loadRows()">刷新</button>
    </div>
  </header>
  <main>
    <section>
      <div class="head"><span>记录列表</span><span id="count" class="muted"></span></div>
      <div class="body">
        <table>
          <thead><tr><th>#</th><th>状态</th><th>方式</th><th>产品</th><th>国家</th><th>账号</th><th>商品 ID</th><th>AI</th><th>可见性</th><th>时间</th><th>视频文件</th><th>操作</th></tr></thead>
          <tbody id="rows"></tbody>
        </table>
        <div id="status" class="status"></div>
      </div>
    </section>
  </main>
  <script>
    let records = [];
    async function loadRows() {
      const res = await fetch('/api/records');
      const payload = await res.json();
      records = payload.records || [];
      document.getElementById('recordsPath').textContent = payload.records_path || '';
      document.getElementById('count').textContent = `${records.length} 条`;
      document.getElementById('rows').innerHTML = records.map((row, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${escapeHtml(row.status || '')}</td>
          <td>${escapeHtml(publishModeLabel(row.publish_mode))}</td>
          <td>${escapeHtml(row.product_code || '')}</td>
          <td>${escapeHtml(row.country || '')}</td>
          <td>${escapeHtml(row.account_name || row.profile_id || '')}</td>
          <td>${escapeHtml(row.product_id || '')}</td>
          <td>${row.ai_generated ? '是' : '否'}</td>
          <td>${escapeHtml(row.visibility || '')}</td>
          <td>${escapeHtml(row.published_at || '')}</td>
          <td class="muted">${escapeHtml(videoFileName(row))}</td>
          <td><button class="danger" onclick="deleteRow(${index})">删除记录</button></td>
        </tr>
      `).join('');
    }
    async function deleteRow(index) {
      if (!confirm(`确认删除第 ${index + 1} 条发布记录？\\n这不会删除视频文件。`)) return;
      const res = await fetch('/api/records/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({index})});
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '删除失败', true);
      setStatus('已删除记录。');
      await loadRows();
    }
    function setStatus(text, error=false) {
      const el = document.getElementById('status');
      el.textContent = text;
      el.className = `status ${error ? 'error' : ''}`;
    }
    function videoFileName(row) {
      if (row.video_name) return row.video_name;
      const path = row.video_path || '';
      return path.split('/').filter(Boolean).pop() || '';
    }
    function publishModeLabel(value) {
      if (value === 'manual') return '手动';
      if (value === 'auto') return '自动';
      return '自动';
    }
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    loadRows().catch(err => setStatus(err.message, true));
  </script>
</body>
</html>"""


QUEUE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>发布队列</title>
  <style>
    :root { --bg:#f6f3ea; --surface:#fffdf7; --soft:#eee9dd; --ink:#101010; --muted:#666157; --line:#151515; --accent:#d9ff63; --blue:#2463eb; --teal:#0e766e; --red:#b42318; --amber:#9a6700; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"PingFang SC",sans-serif; font-size:13px; }
    header { min-height:72px; padding:0 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; border-bottom:1px solid var(--line); background:var(--surface); }
    h1 { margin:0; font-size:24px; }
    .sub { margin-top:6px; color:var(--muted); font-size:12px; }
    nav { display:flex; gap:8px; flex-wrap:wrap; }
    button, a.button { border:1px solid var(--line); background:#fff; color:var(--ink); padding:8px 11px; font-weight:800; font-size:12px; text-decoration:none; cursor:pointer; box-shadow:3px 3px 0 rgba(16,16,16,.12); }
    button:hover, a.button:hover { background:var(--accent); }
    button.primary { background:var(--ink); color:#fff; box-shadow:4px 4px 0 var(--accent); }
    button:disabled { background:#e3e0d8; color:#777; cursor:not-allowed; opacity:.65; box-shadow:none; }
    button.danger { color:var(--red); }
    main { padding:16px; }
    section { border:1px solid var(--line); background:var(--surface); }
    .summary { display:grid; grid-template-columns:repeat(7,minmax(105px,1fr)); border-bottom:1px solid var(--line); }
    .metric { padding:12px; border-right:1px solid var(--line); }
    .metric:last-child { border-right:0; }
    button.metric { border:0; border-right:1px solid var(--line); border-radius:0; background:transparent; color:inherit; text-align:left; box-shadow:none; }
    button.metric:hover { background:var(--accent); }
    button.metric.active { background:var(--ink); color:#fff; box-shadow:inset 0 -4px 0 var(--accent); }
    button.metric.active .metricLabel { color:#fff; }
    .metricLabel { color:var(--muted); font-size:11px; font-weight:760; }
    .metricValue { margin-top:5px; font-size:19px; font-weight:860; }
    .toolbar { min-height:54px; padding:9px 12px; display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); background:var(--soft); }
    .toolbarActions { display:flex; gap:8px; flex-wrap:wrap; }
    .statusText { color:var(--muted); font-size:12px; }
    .tableWrap { overflow:auto; }
    table { width:100%; border-collapse:collapse; min-width:1380px; }
    th, td { padding:9px 8px; text-align:left; vertical-align:top; border-bottom:1px solid rgba(16,16,16,.16); }
    th { position:sticky; top:0; background:var(--soft); font-size:11px; z-index:1; }
    td { line-height:1.4; }
    .status { display:inline-block; padding:3px 6px; border:1px solid var(--line); font-weight:800; font-size:10px; white-space:nowrap; }
    .status.pending { background:#fff; }
    .status.running { background:var(--blue); color:#fff; }
    .status.published { background:var(--teal); color:#fff; }
    .status.failed, .status.needs_review { background:#fff0f0; color:var(--red); }
    .status.canceled { color:var(--muted); }
    .videoName { max-width:250px; font-weight:760; overflow-wrap:anywhere; }
    .caption { max-width:330px; color:var(--muted); overflow-wrap:anywhere; }
    .error { max-width:260px; color:var(--red); overflow-wrap:anywhere; }
    .actions { display:flex; gap:5px; flex-wrap:wrap; min-width:170px; }
    .actions button { padding:5px 7px; box-shadow:none; }
    .empty { padding:28px; color:var(--muted); text-align:center; }
    .pagination { min-height:48px; padding:9px 12px; display:flex; align-items:center; justify-content:flex-end; gap:8px; border-top:1px solid var(--line); background:var(--soft); }
    .pagination[hidden] { display:none; }
    .pageInfo { min-width:180px; color:var(--muted); text-align:center; font-size:12px; }
    @media (max-width:760px) { header { padding:12px; align-items:flex-start; flex-direction:column; } .summary { grid-template-columns:1fr 1fr; } .metric { border-bottom:1px solid var(--line); } .toolbar { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
  <header>
    <div><h1>发布队列</h1><div class="sub">全局串行执行 · 任务完成后间隔 10 秒</div></div>
    <!-- APP_HEADER_ACTIONS -->
  </header>
  <main>
    <section>
      <div class="summary">
        <div class="metric"><div class="metricLabel">队列状态</div><div id="workerState" class="metricValue">-</div></div>
        <button type="button" class="metric filterMetric" data-filter="running" aria-pressed="false" onclick="selectTaskFilter('running')"><div class="metricLabel">正在发布</div><div id="runningCount" class="metricValue">0</div></button>
        <button type="button" class="metric filterMetric active" data-filter="pending" aria-pressed="true" onclick="selectTaskFilter('pending')"><div class="metricLabel">等待任务</div><div id="pendingCount" class="metricValue">0</div></button>
        <button type="button" class="metric filterMetric" data-filter="problem" aria-pressed="false" onclick="selectTaskFilter('problem')"><div class="metricLabel">异常任务</div><div id="problemCount" class="metricValue">0</div></button>
        <button type="button" class="metric filterMetric" data-filter="published" aria-pressed="false" onclick="selectTaskFilter('published')"><div class="metricLabel">已发布</div><div id="publishedCount" class="metricValue">0</div></button>
        <button type="button" class="metric filterMetric" data-filter="canceled" aria-pressed="false" onclick="selectTaskFilter('canceled')"><div class="metricLabel">已取消</div><div id="canceledCount" class="metricValue">0</div></button>
        <div class="metric"><div class="metricLabel">下一条倒计时</div><div id="countdown" class="metricValue">--</div></div>
      </div>
      <div class="toolbar">
        <div id="queueStatus" class="statusText">正在读取队列...</div>
        <div class="toolbarActions">
          <button id="visibleButton" class="primary" onclick="startQueue('visible')">可视执行</button>
          <button id="headlessButton" onclick="startQueue('headless')">后台执行</button>
          <button id="pauseButton" onclick="controlQueue('pause')">暂停队列</button>
          <button class="danger" onclick="clearPending()">清空等待任务</button>
        </div>
      </div>
      <div class="tableWrap">
        <table>
          <thead><tr><th>#</th><th>状态</th><th>视频</th><th>产品/国家</th><th>账号</th><th>发布文案</th><th>商品 ID</th><th>时间</th><th>错误</th><th>操作</th></tr></thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
      <div id="pagination" class="pagination" hidden>
        <button id="previousPage" type="button" onclick="changePage(-1)">上一页</button>
        <span id="pageInfo" class="pageInfo"></span>
        <button id="nextPage" type="button" onclick="changePage(1)">下一页</button>
      </div>
    </section>
  </main>
  <script>
    let queue = null;
    const PAGE_SIZE = 20;
    let activeStatus = 'pending';
    let currentPage = 1;
    const statusLabels = {pending:'等待中',running:'发布中',published:'已发布',failed:'失败',needs_review:'结果待确认',canceled:'已取消'};
    const filterLabels = {running:'正在发布',pending:'等待任务',problem:'异常任务',published:'已发布',canceled:'已取消'};
    async function loadQueue() {
      const res = await fetch('/api/queue');
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '读取失败', true);
      queue = body;
      render();
    }
    function render() {
      const counts = queue.counts || {};
      const running = Number(counts.running || 0);
      const pending = Number(counts.pending || 0);
      const executionLabel = queue.execution_mode === 'headless' ? '后台执行' : '可视执行';
      const workerState = running || (!queue.paused && pending) ? executionLabel : (queue.paused && pending ? '待执行' : (queue.paused ? '已暂停' : '空闲'));
      document.getElementById('workerState').textContent = workerState;
      document.getElementById('queueBadge').textContent = `发布队列 ${pending + running}`;
      document.getElementById('runningCount').textContent = running;
      document.getElementById('pendingCount').textContent = pending;
      document.getElementById('problemCount').textContent = Number(counts.failed || 0) + Number(counts.needs_review || 0);
      document.getElementById('publishedCount').textContent = counts.published || 0;
      document.getElementById('canceledCount').textContent = counts.canceled || 0;
      const startDisabled = !queue.paused || !pending || Boolean(running);
      document.getElementById('visibleButton').disabled = startDisabled;
      document.getElementById('headlessButton').disabled = startDisabled;
      document.getElementById('pauseButton').disabled = queue.paused || (!pending && !running);
      renderTaskList();
      if (running) setStatus(`正在以${executionLabel}方式发布。`);
      else if (queue.paused && pending) setStatus(`${pending} 个任务待执行，请选择“可视执行”或“后台执行”。`);
      else if (queue.paused) setStatus('队列已暂停，当前没有待执行任务。');
      else if (pending) setStatus(`队列正在以${executionLabel}方式按顺序串行执行。`);
      else setStatus('当前没有待执行任务。');
      updateCountdown();
    }
    function selectTaskFilter(status) {
      activeStatus = status;
      currentPage = 1;
      renderTaskList();
    }
    function filteredTasks() {
      const tasks = queue ? (queue.tasks || []) : [];
      if (activeStatus === 'problem') return tasks.filter(task => task.status === 'failed' || task.status === 'needs_review');
      return tasks.filter(task => task.status === activeStatus);
    }
    function renderTaskList() {
      const tasks = filteredTasks();
      const totalPages = Math.max(1, Math.ceil(tasks.length / PAGE_SIZE));
      currentPage = Math.min(currentPage, totalPages);
      const pageTasks = tasks.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
      document.getElementById('rows').innerHTML = pageTasks.length
        ? pageTasks.map(rowHtml).join('')
        : `<tr><td colspan="10" class="empty">当前没有${escapeHtml(filterLabels[activeStatus])}的任务。</td></tr>`;
      document.querySelectorAll('.filterMetric').forEach(metric => {
        const active = metric.dataset.filter === activeStatus;
        metric.classList.toggle('active', active);
        metric.setAttribute('aria-pressed', String(active));
      });
      const pagination = document.getElementById('pagination');
      pagination.hidden = tasks.length === 0;
      document.getElementById('pageInfo').textContent = `第 ${currentPage} / ${totalPages} 页 · 共 ${tasks.length} 条 · 每页 ${PAGE_SIZE} 条`;
      document.getElementById('previousPage').disabled = currentPage <= 1;
      document.getElementById('nextPage').disabled = currentPage >= totalPages;
    }
    function changePage(offset) {
      currentPage += offset;
      renderTaskList();
      document.querySelector('.tableWrap').scrollTo({top:0, behavior:'smooth'});
    }
    function rowHtml(task) {
      const time = [task.created_at && `入队 ${task.created_at}`, task.started_at && `开始 ${task.started_at}`, task.completed_at && `完成 ${task.completed_at}`].filter(Boolean).join('<br>');
      return `<tr>
        <td>${task.position}</td><td><span class="status ${escapeHtml(task.status)}">${escapeHtml(statusLabels[task.status] || task.status)}</span><br><small>尝试 ${task.attempts}</small></td>
        <td class="videoName">${escapeHtml(task.video_name)}</td><td>${escapeHtml(task.product_code)} / ${escapeHtml(task.country)}</td>
        <td>${escapeHtml(task.profile_name)}</td><td class="caption">${escapeHtml(task.caption)}</td><td>${escapeHtml(task.product_id)}</td>
        <td>${time}</td><td class="error">${escapeHtml(task.error || '')}</td><td><div class="actions">${taskActions(task)}</div></td>
      </tr>`;
    }
    function taskActions(task) {
      if (task.status === 'pending') return `<button onclick="taskAction(${task.id},'move_up')">↑</button><button onclick="taskAction(${task.id},'move_down')">↓</button><button class="danger" onclick="taskAction(${task.id},'cancel')">取消</button>`;
      if (task.status === 'failed' || task.status === 'needs_review') return `<button onclick="retryTask(${task.id},'${task.status}')">重试</button><button class="danger" onclick="taskAction(${task.id},'cancel')">取消</button>`;
      return '';
    }
    async function startQueue(executionMode) {
      await controlQueue('resume', executionMode);
    }
    async function controlQueue(action, executionMode='') {
      await post('/api/queue/control',{action, execution_mode:executionMode});
    }
    async function clearPending() {
      if (!confirm('确认取消所有等待中任务？正在发布的任务不受影响。')) return;
      await controlQueue('clear_pending');
    }
    async function retryTask(id, status) {
      const warning = status === 'needs_review' ? '这个任务的发布结果不明确，重试可能造成重复发布。\n\n' : '';
      if (!confirm(`${warning}确认将任务重新加到队尾并强制使用可视执行？`)) return;
      await taskAction(id,'retry');
    }
    async function taskAction(taskId, action) { await post('/api/queue/task',{task_id:taskId,action}); }
    async function post(url, payload) {
      const res = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const body = await res.json();
      if (!res.ok || body.error) return setStatus(body.error || '操作失败', true);
      queue = body.queue || body;
      render();
    }
    function updateCountdown() {
      if (!queue) return;
      const remaining = Math.max(0, Math.ceil(Number(queue.next_run_at || 0) - Date.now()/1000));
      const pending = Number((queue.counts || {}).pending || 0);
      document.getElementById('countdown').textContent = queue.paused ? (pending ? '待执行' : '--') : (remaining ? `${remaining}s` : '就绪');
    }
    function setStatus(text, error=false) { const el=document.getElementById('queueStatus'); el.textContent=text; el.style.color=error?'var(--red)':'var(--muted)'; }
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
    loadQueue().catch(err => setStatus(err.message,true));
    setInterval(() => { updateCountdown(); loadQueue().catch(() => {}); }, 2000);
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
                text_response(self, 200, render_app_page(HTML), "text/html; charset=utf-8")
            elif parsed.path == "/product-id":
                text_response(self, 200, render_app_page(PRODUCT_ID_HTML), "text/html; charset=utf-8")
            elif parsed.path == "/records":
                self.send_response(302)
                self.send_header("Location", "/Daily-KPIs")
                self.end_headers()
            elif parsed.path in ("/Daily-KPIs", "/daily-kpis"):
                text_response(self, 200, render_app_page(DAILY_KPI_HTML), "text/html; charset=utf-8")
            elif parsed.path == "/queue":
                text_response(self, 200, render_app_page(QUEUE_HTML), "text/html; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            elif parsed.path == "/api/state":
                json_response(self, 200, state_for_client())
            elif parsed.path == "/api/product-ids":
                json_response(self, 200, product_ids_payload())
            elif parsed.path == "/api/records":
                json_response(self, 200, records_payload())
            elif parsed.path == "/api/daily-kpis":
                query = urllib.parse.parse_qs(parsed.query)
                json_response(self, 200, daily_kpis_payload(query.get("date", [""])[0]))
            elif parsed.path == "/api/queue":
                json_response(self, 200, get_publish_queue().payload())
            elif parsed.path == "/api/bitbrowser/profiles":
                json_response(self, 200, list_bitbrowser_profiles())
            elif parsed.path == "/api/video":
                query = urllib.parse.parse_qs(parsed.query)
                path = safe_video_path(query.get("path", [""])[0])
                if not path.exists() or not path.is_file():
                    raise ValueError("视频文件不存在")
                serve_video(self, path)
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - keep UI/API failures readable.
            json_response(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/tiktok/prepare-upload":
                payload = read_json_body(self)
                result = prepare_tiktok_upload_locked(
                    str(payload.get("profile_id", "")),
                    str(payload.get("video_path", "")),
                    str(payload.get("caption", "")),
                    bool(payload.get("ai_generated", True)),
                )
                json_response(self, 200, result)
            elif parsed.path == "/api/tiktok/manual-upload":
                payload = read_json_body(self)
                result = prepare_tiktok_upload_locked(
                    str(payload.get("profile_id", "")),
                    str(payload.get("video_path", "")),
                    str(payload.get("caption", "")),
                    False,
                )
                result["message"] = "已打开 TikTok 上传页、上传视频并填写文案，后续步骤请手动完成。"
                json_response(self, 200, result)
            elif parsed.path == "/api/tiktok/publish":
                payload = read_json_body(self)
                result = run_tiktok_publish_locked(payload)
                json_response(self, 200, result)
            elif parsed.path == "/api/queue/enqueue":
                payload = read_json_body(self)
                tasks = build_queue_tasks(payload)
                task_ids = get_publish_queue().enqueue(tasks)
                json_response(self, 200, {"ok": True, "task_ids": task_ids, "queue": get_publish_queue().payload()})
            elif parsed.path == "/api/queue/control":
                payload = read_json_body(self)
                result = get_publish_queue().control(
                    str(payload.get("action", "")),
                    str(payload.get("execution_mode", "")),
                )
                json_response(self, 200, result)
            elif parsed.path == "/api/queue/task":
                payload = read_json_body(self)
                result = get_publish_queue().task_action(int(payload.get("task_id", 0)), str(payload.get("action", "")))
                json_response(self, 200, result)
            elif parsed.path == "/api/video/delete":
                payload = read_json_body(self)
                result = delete_finished_video(str(payload.get("video_path", "")))
                json_response(self, 200, result)
            elif parsed.path == "/api/product-ids/upsert":
                payload = read_json_body(self)
                json_response(self, 200, upsert_product_id(payload))
            elif parsed.path == "/api/product-ids/delete":
                payload = read_json_body(self)
                json_response(self, 200, delete_product_id(payload))
            elif parsed.path == "/api/records/delete":
                payload = read_json_body(self)
                json_response(self, 200, delete_publish_record(payload))
            elif parsed.path == "/api/daily-kpis/settings":
                payload = read_json_body(self)
                json_response(self, 200, save_daily_kpi_settings(payload))
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - keep UI/API failures readable.
            json_response(self, 400, {"error": str(exc)})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args_list = list(argv if argv is not None else sys.argv[1:])
    if not args_list or args_list[0].startswith("-"):
        args_list.insert(0, "web")
    parser = argparse.ArgumentParser(description="Finished video manager.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    web_parser = subparsers.add_parser("web", help="Run the local web UI.")
    web_parser.add_argument("--host", default=HOST)
    web_parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    publish_parser = subparsers.add_parser("publish", help="Publish one video to TikTok through BitBrowser.")
    publish_parser.add_argument("--profile-id", required=True)
    publish_parser.add_argument("--video-path", required=True)
    publish_parser.add_argument("--caption", required=True)
    publish_parser.add_argument("--product-id", required=True)
    publish_parser.add_argument("--product-short-name", required=True)
    publish_parser.add_argument("--visibility", default="public", choices=["public"])
    publish_parser.add_argument("--no-ai", action="store_true", help="Do not enable the TikTok AI-generated label.")
    return parser.parse_args(args_list)


def main(argv: list[str] | None = None) -> None:
    global PUBLISH_QUEUE
    args = parse_args(argv)
    if args.command == "publish":
        result = publish_tiktok_video(
            args.profile_id,
            args.video_path,
            args.caption,
            args.product_id,
            args.product_short_name,
            not args.no_ai,
            args.visibility,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    PUBLISH_QUEUE = PublishQueue(
        PUBLISH_QUEUE_PATH,
        run_tiktok_publish_locked,
        interval_seconds=10,
        profile_closer=close_bitbrowser_profile,
        video_path_resolver=resolve_finished_video_path,
    )
    PUBLISH_QUEUE.start()
    print(f"成品管理 Web 界面: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        PUBLISH_QUEUE.stop()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
