from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from .agent import HotVideoAgent
from .config import CONFIG_PATH, ROOT, ConfigError, init_config, read_config_file, save_config, validate_config
from .kolsprite import KolspriteDownloader
from .paths import HOT_VIDEO_LIBRARY_ROOT, VAULT_ROOT, ProjectPaths
from .reporting import RunReport


HOST = "127.0.0.1"
DEFAULT_PORT = 9991
CATEGORY_TREE_RUNTIME_PATH = CONFIG_PATH.parent / "fastmoss_category_tree.json"
LEGACY_CATEGORY_TREE_PATH = ROOT / "data" / "fastmoss_category_tree.json"
CATEGORY_TREE_PATHS = [
    CATEGORY_TREE_RUNTIME_PATH,
    LEGACY_CATEGORY_TREE_PATH,
]
PRODUCT_INFO_DIR = VAULT_ROOT / "wiki" / "产品" / "产品信息"
PRODUCT_INFO_INDEX_PATH = CONFIG_PATH.parent / "product_info_options.json"
LEGACY_PRODUCT_INFO_INDEX_PATH = ROOT / "data" / "product_info_options.json"
FORM_OPTIONS = {
    "country": ["全部", "美国", "印度尼西亚", "英国", "越南", "泰国", "马来西亚", "菲律宾", "西班牙", "墨西哥", "德国", "法国", "意大利", "巴西", "日本", "新加坡"],
    "shop_type": ["全部", "跨境店", "本土店"],
    "product_types": ["全部", "上新商品", "包邮商品", "本地仓商品", "爆款商品"],
    "product_status": ["全部", "在售", "下架"],
    "creator_conversion_rate_filter": ["全部", "<25%", "25%-50%", "50%-75%", "75%-100%"],
    "total_sales_filter": ["全部", "<1万", "1万-10万", "10万-20万", "20万-30万", "30万-40万", "50万-100万", ">100万"],
    "total_gmv_filter": ["全部", "<$500", "$500-$1000", "$1000-$5000", "$5000-$1.00万", "$1.00万-$5.00万", "$5.00万-$10.00万", "$10.00万-$50.00万", "$50.00万-$100.00万", ">$100.00万"],
    "sales_7d_filter": ["全部", "<500", "500-1000", "1000-5000", "5000-1万", "1万-5万", ">5万"],
    "gmv_7d_filter": ["全部", "<$500", "$500-$1000", "$1000-$5000", "$5000-$1.00万", "$1.00万-$5.00万", "$5.00万-$10.00万", "$10.00万-$50.00万", "$50.00万-$100.00万", ">$100.00万"],
    "creator_count_filter": ["全部", "100-499", "500-999", "1000-5000", "5000-1万", ">1万"],
    "commission_rate_filter": ["全部", "<15%", "15%-30%", "30%-50%", "50%-70%", ">70%"],
    "shipping_method_filter": ["全部", "视频带货", "直播带货"],
}


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


def extract_tiktok_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://(?:www\.)?tiktok\.com/[^\s,，)）]+", text or "")
    normalized: list[str] = []
    for url in urls:
        url = url.strip().rstrip("。.;；")
        if url and url not in normalized:
            normalized.append(url)
    return normalized


def display_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def migrate_runtime_support_files() -> None:
    for source, target in (
        (LEGACY_CATEGORY_TREE_PATH, CATEGORY_TREE_RUNTIME_PATH),
        (LEGACY_PRODUCT_INFO_INDEX_PATH, PRODUCT_INFO_INDEX_PATH),
    ):
        if target.exists():
            continue
        try:
            if not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o600)
        except OSError:
            continue


def safe_read_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    allowed_roots = [ROOT.resolve(), ProjectPaths(ROOT, read_config_file(CONFIG_PATH)).project_root.resolve()]
    for allowed_root in allowed_roots:
        try:
            path.relative_to(allowed_root)
            return path
        except ValueError:
            continue
    raise ValueError("路径不在项目目录或当前产品路径内")
    return path


def mask_secret(value: str, keep: int = 3) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "*" * len(text)
    return text[:keep] + "*" * (len(text) - keep * 2) + text[-keep:]


def split_category_path(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()] or ["全部"]
    return [part.strip() for part in str(value or "").split(">") if part.strip()] or ["全部"]


def split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def int_value(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def local_project_options() -> list[dict[str, str]]:
    options = [{"name": "默认 product", "path": display_path(ROOT / "product")}]
    projects_dir = ROOT / "projects"
    if not projects_dir.exists():
        return options
    for path in sorted(projects_dir.iterdir(), key=lambda item: item.name.lower()):
        if path.is_dir():
            options.append({"name": path.name, "path": display_path(path)})
    return options


def product_info_options() -> list[dict[str, str]]:
    return product_info_options_from_index()


def scan_product_info_options() -> list[dict[str, str]]:
    if not PRODUCT_INFO_DIR.exists():
        raise FileNotFoundError(f"产品信息目录不存在: {PRODUCT_INFO_DIR}")
    options: list[dict[str, str]] = []
    paths = sorted(PRODUCT_INFO_DIR.glob("*.md"), key=lambda item: item.name.lower())
    for path in paths:
        option = product_info_option_from_path(path)
        if option:
            options.append(option)
    return options


def product_info_option_from_path(path: Path) -> dict[str, str]:
    if path.stem.startswith("_"):
        return {}
    name = path.stem
    for suffix in ("-产品信息", "产品信息"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip(" -_")
            break
    return {"name": name or path.stem, "path": path.as_posix()}


def product_info_options_from_index() -> list[dict[str, str]]:
    if not PRODUCT_INFO_INDEX_PATH.exists():
        return []
    try:
        data = json.loads(PRODUCT_INFO_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    options: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        path = str(item.get("path") or "").strip()
        if name and path:
            options.append({"name": name, "path": path})
    return options


def refresh_product_info_index() -> dict[str, Any]:
    options = scan_product_info_options()
    if not options:
        indexed_options = product_info_options_from_index()
        if not indexed_options:
            raise ValueError(f"未在产品信息目录找到 Markdown: {PRODUCT_INFO_DIR}")
        return {
            "count": len(indexed_options),
            "source_dir": PRODUCT_INFO_DIR.as_posix(),
            "index_path": display_path(PRODUCT_INFO_INDEX_PATH),
            "source": "index",
            "warning": "常驻服务未读取到产品目录 Markdown，已使用本地产品索引。",
        }
    PRODUCT_INFO_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRODUCT_INFO_INDEX_PATH.write_text(
        json.dumps(options, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "count": len(options),
        "source_dir": PRODUCT_INFO_DIR.as_posix(),
        "index_path": display_path(PRODUCT_INFO_INDEX_PATH),
        "source": "directory",
    }


def load_category_tree() -> dict[str, Any]:
    for path in CATEGORY_TREE_PATHS:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("category_tree"), dict):
            top_categories = data.get("top_categories")
            if not isinstance(top_categories, list):
                top_categories = ["全部"] + sorted(data["category_tree"].keys())
            return {
                "source": display_path(path),
                "top_categories": [str(item) for item in top_categories if str(item).strip()],
                "category_tree": data["category_tree"],
            }
    return {"source": "", "top_categories": ["全部"], "category_tree": {}}


def config_for_client() -> dict[str, Any]:
    init_config(CONFIG_PATH)
    config = read_config_file(CONFIG_PATH)
    runtime = read_config_file(CONFIG_PATH)
    fastmoss = runtime.get("fastmoss") or {}
    env_phone = os.environ.get("FASTMOSS_PHONE", "")
    env_password = os.environ.get("FASTMOSS_PASSWORD", "")
    paths = ProjectPaths(ROOT, config)
    latest_csv = paths.latest_collection_csv()
    reports_dir = paths.run_logs_dir()
    latest_report = None
    if reports_dir.exists():
        reports = sorted(reports_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        latest_report = reports[0] if reports else None

    client_config = json.loads(json.dumps(config, ensure_ascii=False))
    client_fastmoss = client_config.setdefault("fastmoss", {})
    if client_fastmoss.get("password"):
        client_fastmoss["password"] = mask_secret(str(client_fastmoss.get("password")))

    return {
        "config": client_config,
        "paths": {
            "root": display_path(ROOT),
            "config": display_path(CONFIG_PATH),
            "project_root": display_path(paths.project_root),
            "result_dir": display_path(paths.result_dir()),
            "hot_video_root": display_path(HOT_VIDEO_LIBRARY_ROOT),
            "hot_video_dir": display_path(paths.hot_video_dir(create=False)),
            "latest_csv": display_path(latest_csv) if latest_csv else "",
            "latest_report": display_path(latest_report) if latest_report else "",
        },
        "project_options": local_project_options(),
        "product_options": product_info_options(),
        "category_data": load_category_tree(),
        "form_options": FORM_OPTIONS,
        "environment": {
            "playwright": bool(importlib.util.find_spec("playwright")),
            "browser_viewer_port": int(os.environ.get("OPC_BROWSER_VIEWER_PORT") or 0),
            "phone_from_env": bool(env_phone),
            "password_from_env": bool(env_password),
            "has_phone": bool(env_phone or fastmoss.get("phone")),
            "has_password": bool(env_password or fastmoss.get("password")),
        },
    }


def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = read_config_file(CONFIG_PATH)
    product = config.setdefault("product", {})
    fastmoss = config.setdefault("fastmoss", {})
    download = config.setdefault("download", {})
    output = config.setdefault("output", {})

    if "name" in payload:
        product["name"] = str(payload.get("name") or "").strip()
        product["slug"] = ""
        product["path"] = ""

    for key in (
        "phone",
        "keyword",
        "country",
        "shop_type",
        "product_status",
        "creator_conversion_rate_filter",
        "total_sales_filter",
        "total_gmv_filter",
        "sales_7d_filter",
        "gmv_7d_filter",
        "creator_count_filter",
        "commission_rate_filter",
        "shipping_method_filter",
    ):
        if key in payload:
            fastmoss[key] = str(payload.get(key) or "").strip()

    if "password" in payload:
        password = str(payload.get("password") or "")
        if password and "*" not in password:
            fastmoss["password"] = password

    if "category_path" in payload:
        fastmoss["category_path"] = split_category_path(payload.get("category_path"))
    if "product_types" in payload:
        selected_product_type = str(payload.get("product_types") or "").strip()
        fastmoss["product_types"] = [] if selected_product_type in {"", "全部"} else [selected_product_type]

    for key, default in (("product_limit", 3), ("videos_per_product", 5)):
        if key in payload:
            fastmoss[key] = int_value(payload.get(key), default, 1)

    if "show_browser" in payload:
        fastmoss["show_browser"] = bool(payload.get("show_browser"))

    if "download_enabled" in payload:
        download["enabled"] = bool(payload.get("download_enabled"))
    if "source_csv" in payload:
        download["source_csv"] = str(payload.get("source_csv") or "").strip()
    if "download_limit" in payload:
        download["limit"] = int_value(payload.get("download_limit"), 0, 0)
    output["result_folder_name"] = "results"

    save_config(config, CONFIG_PATH)
    return config_for_client()


def inspect_config() -> dict[str, Any]:
    init_config(CONFIG_PATH)
    config = read_config_file(CONFIG_PATH)
    paths = ProjectPaths(ROOT, config)
    checks: list[dict[str, str]] = []

    try:
        validate_config(config, require_credentials=False)
        checks.append({"level": "ok", "message": "基础配置可用", "detail": f"产品目录: {display_path(paths.project_root)}"})
    except ConfigError as exc:
        checks.append({"level": "error", "message": "基础配置未完成", "detail": str(exc)})

    fastmoss = config.get("fastmoss") or {}
    if os.environ.get("FASTMOSS_PHONE") or fastmoss.get("phone"):
        checks.append({"level": "ok", "message": "FastMoss 手机号已配置", "detail": "可来自环境变量或本地配置。"})
    else:
        checks.append({"level": "warn", "message": "FastMoss 手机号未配置", "detail": "运行采集或刷新登录前需要补充。"})

    if os.environ.get("FASTMOSS_PASSWORD") or fastmoss.get("password"):
        checks.append({"level": "ok", "message": "FastMoss 密码已配置", "detail": "页面不会回显真实密码。"})
    else:
        checks.append({"level": "warn", "message": "FastMoss 密码未配置", "detail": "运行采集或刷新登录前需要补充。"})

    latest_csv = paths.latest_collection_csv()
    checks.append({"level": "ok", "message": "结果文件夹", "detail": display_path(paths.result_dir())})
    if latest_csv:
        checks.append({"level": "ok", "message": "找到可下载 CSV", "detail": display_path(latest_csv)})
    else:
        checks.append({"level": "warn", "message": "暂未找到采集 CSV", "detail": "先运行采集，或填写下载 CSV 路径。"})

    category_data = load_category_tree()
    category_count = len(category_data.get("category_tree", {}))
    checks.append(
        {
            "level": "ok" if category_count else "warn",
            "message": "FastMoss 类目树",
            "detail": f"已加载 {category_count} 个一级类目" if category_count else "未找到类目树文件，仅可选择全部。",
        }
    )

    checks.append(
        {
            "level": "ok" if importlib.util.find_spec("playwright") else "error",
            "message": "Playwright 环境",
            "detail": "已安装" if importlib.util.find_spec("playwright") else "未安装，请运行 python3 -m pip install -r requirements.txt",
        }
    )

    ready = not any(item["level"] == "error" for item in checks)
    return {"checks": checks, "ready": ready}


class ThreadWriter(io.TextIOBase):
    def __init__(self, job: "WebJob") -> None:
        self.job = job

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if text:
            self.job.append_log(text)
        return len(text)

    def flush(self) -> None:
        return None


class WebJob:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.status = "idle"
        self.mode = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self.logs = ""
        self.error = ""
        self.report_path = ""
        self.outputs: list[dict[str, str]] = []

    def append_log(self, text: str) -> None:
        with self.lock:
            self.logs += text
            if len(self.logs) > 160000:
                self.logs = self.logs[-160000:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "mode": self.mode,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": self.logs,
                "error": self.error,
                "report_path": self.report_path,
                "outputs": self.outputs,
            }

    def start(self, mode: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.running:
                raise RuntimeError("已有任务正在运行")
            self.running = True
            self.status = "running"
            self.mode = mode
            self.started_at = time.time()
            self.finished_at = 0.0
            self.logs = ""
            self.error = ""
            self.report_path = ""
            self.outputs = []

        update_config(payload)
        thread = threading.Thread(target=self._run, args=(mode, payload), daemon=True)
        thread.start()
        return self.snapshot()

    def _run_direct_url_download(self, payload: dict[str, Any]) -> tuple[Path, RunReport]:
        config = read_config_file(CONFIG_PATH)
        paths = ProjectPaths(ROOT, config)
        paths.ensure()
        urls = extract_tiktok_urls(str(payload.get("direct_urls") or ""))
        if not urls:
            raise ValueError("请先粘贴 TikTok 视频 URL，每行一个或用空格分隔")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = paths.result_dir(create=True) / f"direct_urls_{stamp}.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["tiktok_video_url"])
            writer.writeheader()
            for url in urls:
                writer.writerow({"tiktok_video_url": url})

        report = RunReport(mode="url_download", started_at=datetime.now(), csv_path=csv_path)
        self.append_log(f"开始 URL 下载任务\n")
        self.append_log(f"产品: {paths.product_name()}\n")
        self.append_log(f"URL 数量: {len(urls)}\n")
        self.append_log(f"临时 CSV: {csv_path}\n")
        downloader = KolspriteDownloader(config, paths, self.append_log)
        csv_path, downloaded, skipped, failures = downloader.run(csv_path)
        report.csv_path = csv_path
        report.downloaded.extend(downloaded)
        report.skipped.extend(skipped)
        report.failures.extend(failures)
        report_path = report.write(paths)
        self.append_log(f"运行报告: {report_path}\n")
        return report_path, report

    def _run(self, mode: str, payload: dict[str, Any]) -> None:
        writer = ThreadWriter(self)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                if mode == "url_download":
                    report_path, report = self._run_direct_url_download(payload)
                elif mode == "login":
                    HotVideoAgent(CONFIG_PATH).refresh_login()
                    report_path = ""
                    report = None
                else:
                    report_path, report = HotVideoAgent(CONFIG_PATH).run(mode)
                with self.lock:
                    self.status = "completed"
                    self.report_path = display_path(report_path) if report_path else ""
                    if report:
                        self.outputs = [
                            {"name": "运行报告", "path": display_path(report_path), "kind": "report"},
                        ]
                        if report.csv_path:
                            self.outputs.append({"name": "结果文件夹", "path": display_path(Path(report.csv_path).parent), "kind": "folder"})
                            self.outputs.append({"name": "采集 CSV", "path": display_path(report.csv_path), "kind": "csv"})
                        for path in report.downloaded[:8]:
                            self.outputs.append({"name": Path(path).name, "path": display_path(path), "kind": "video"})
        except Exception as exc:  # noqa: BLE001 - surface local automation failure in UI.
            self.append_log(traceback.format_exc())
            with self.lock:
                self.status = "failed"
                self.error = str(exc)
        finally:
            with self.lock:
                self.running = False
                self.finished_at = time.time()


JOB = WebJob()


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>爆款视频收集智能体</title>
  <style>
    :root {
      color-scheme: light;
      --bg:#f7f4ec;
      --surface:#fffdf7;
      --surface-soft:#f1eee5;
      --ink:#101010;
      --muted:#5f5b52;
      --soft:#8b867a;
      --line:#151515;
      --line-soft:rgba(16,16,16,.16);
      --accent:#d9ff63;
      --accent-ink:#0b0b0b;
      --green:#1f7a42;
      --amber:#8b5e00;
      --red:#b32125;
      --code:#111;
      --shadow:0 14px 0 rgba(16,16,16,.08);
    }
    * { box-sizing:border-box; }
    html, body { height:100%; overflow:hidden; }
    body {
      margin:0;
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
      height:72px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:0 22px;
      background:rgba(255,253,247,.82);
      border-bottom:1px solid var(--line);
      backdrop-filter:blur(14px);
      -webkit-backdrop-filter:blur(14px);
    }
    h1 { margin:0; font-size:24px; font-weight:820; letter-spacing:0; line-height:1; }
    .sub { color:var(--muted); font-size:12px; margin-top:7px; text-transform:uppercase; }
    .topBadges { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
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
    .badge.ok { color:var(--accent-ink); background:var(--accent); border-color:var(--line); }
    .badge.warn { color:var(--amber); background:#fff3c7; border-color:var(--line); }
    .badge.error { color:#fff; background:var(--red); border-color:var(--line); }
    main {
      height:calc(100vh - 72px);
      padding:14px;
      display:grid;
      grid-template-columns:320px minmax(430px, 1fr) 420px;
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
      border-radius:0;
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
    .panelBody { flex:1; min-height:0; overflow:hidden; padding:12px; }
    .scrollBody { overflow:auto; padding-right:6px; }
    label {
      display:block;
      margin:8px 0 4px;
      color:var(--muted);
      font-size:11px;
      font-weight:780;
      text-transform:uppercase;
    }
    .hint {
      color:var(--muted);
      font-size:11px;
      line-height:1.35;
      margin:3px 0 6px;
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
      box-shadow:4px 4px 0 var(--accent);
    }
    textarea { resize:vertical; min-height:52px; line-height:1.48; }
    .row2 { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .row3 { display:grid; grid-template-columns:1fr 92px 92px; gap:8px; }
    .row3equal { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    .filterGrid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    .categoryGrid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    .selectGrid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    .productPick { display:grid; grid-template-columns:minmax(0, 1fr) 82px; gap:8px; align-items:end; }
    .productPick button { height:36px; }
    .pathPick { display:grid; grid-template-columns:1fr 86px; gap:8px; align-items:end; }
    .switchRow {
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      align-items:center;
      padding:9px 0;
      border-bottom:1px solid var(--line-soft);
      font-size:12px;
    }
    .switchRow:last-child { border-bottom:0; }
    .switchRow span { color:var(--muted); font-size:11px; display:block; margin-top:2px; }
    input[type="checkbox"] { width:18px; height:18px; box-shadow:none; accent-color:var(--ink); }
    .segmented {
      display:grid;
      grid-template-columns:repeat(5, 1fr);
      gap:0;
      padding:0;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
    }
    .segmented button {
      padding:9px 6px;
      border:0;
      border-right:1px solid var(--line);
      box-shadow:none;
      background:transparent;
      color:var(--muted);
    }
    .segmented button:last-child { border-right:0; }
    .segmented button.active {
      background:var(--ink);
      color:var(--ink);
      color:#fff;
      box-shadow:none;
    }
    .actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; }
    .actions .wide { grid-column:1 / -1; }
    button {
      border:1px solid var(--line);
      background:#fff;
      color:var(--ink);
      border-radius:0;
      padding:8px 12px;
      font-size:12px;
      font-weight:820;
      line-height:1.2;
      cursor:pointer;
      box-shadow:3px 3px 0 rgba(16,16,16,.13);
      transition:transform .12s ease, background .15s ease, box-shadow .15s ease;
    }
    button:hover { background:var(--accent); box-shadow:4px 4px 0 rgba(16,16,16,.2); }
    button:active { transform:translate(2px,2px); box-shadow:1px 1px 0 rgba(16,16,16,.2); }
    button.primary { background:var(--ink); color:#fff; border-color:var(--line); box-shadow:4px 4px 0 var(--accent); }
    button.primary:hover { background:#000; }
    button.blue { color:var(--ink); border-color:var(--line); background:#fff; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .kv {
      display:grid;
      grid-template-columns:70px 1fr;
      gap:8px;
      padding:6px 0;
      border-bottom:1px solid var(--line-soft);
      font-size:11px;
    }
    .kv:last-child { border-bottom:0; }
    .k { color:var(--muted); }
    .v { color:var(--ink); overflow-wrap:anywhere; }
    .checks { display:flex; flex-direction:column; gap:6px; min-height:0; overflow:auto; }
    .check {
      border:1px solid var(--line);
      border-radius:0;
      padding:8px 9px;
      background:#fff;
      font-size:11px;
    }
    .check strong {
      display:inline-flex;
      min-width:32px;
      justify-content:center;
      margin-right:5px;
      padding:2px 5px;
      border-radius:0;
      font-size:10px;
    }
    .check.ok strong { color:var(--accent-ink); background:var(--accent); }
    .check.warn strong { color:var(--amber); background:rgba(255,159,10,.14); }
    .check.error strong { color:var(--red); background:rgba(255,59,48,.13); }
    .detail {
      margin-top:2px;
      color:var(--muted);
      overflow-wrap:anywhere;
      display:-webkit-box;
      -webkit-line-clamp:2;
      -webkit-box-orient:vertical;
      overflow:hidden;
    }
    .runBody {
      display:grid;
      grid-template-rows:auto minmax(120px, 1fr) minmax(150px, 1.1fr) auto;
      gap:8px;
      height:100%;
      overflow:hidden;
    }
    pre {
      margin:0;
      white-space:pre-wrap;
      word-break:break-word;
      background:var(--code);
      color:#f7f4ec;
      padding:12px;
      border-radius:0;
      border:1px solid var(--line);
      min-height:0;
      overflow:auto;
      font-size:11px;
      line-height:1.48;
      box-shadow:inset 0 0 0 1px rgba(255,255,255,.05);
    }
    .outputs { display:flex; flex-direction:column; gap:6px; overflow:auto; max-height:110px; }
    .outputItem {
      display:grid;
      grid-template-columns:1fr auto;
      gap:8px;
      align-items:center;
      padding:7px 8px;
      border:1px solid var(--line);
      border-radius:0;
      background:#fff;
      font-size:12px;
    }
    .path { margin-top:2px; color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
    .tiny { color:var(--soft); font-size:11px; }
    .muted { color:var(--muted); }
    @media (max-width: 1180px) {
      html, body { overflow:auto; }
      main { grid-template-columns:320px 1fr; height:auto; min-height:calc(100vh - 72px); overflow:auto; }
      section.run { grid-column:1 / -1; min-height:420px; }
    }
    @media (max-width: 760px) {
      header { height:auto; min-height:58px; flex-direction:column; align-items:flex-start; padding:12px; }
      .topBadges { justify-content:flex-start; }
      main { grid-template-columns:1fr; padding:10px; }
      section.run { grid-column:auto; }
      .row2, .row3 { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>爆款视频收集智能体</h1>
      <div class="sub">FastMoss 采集 · TikTok URL · Kolsprite 下载 · 本地归档</div>
    </div>
    <div class="topBadges">
      <span id="configBadge" class="badge">配置</span>
      <span id="credentialBadge" class="badge">账号</span>
      <span id="jobBadge" class="badge">空闲</span>
    </div>
  </header>
  <main>
    <section>
      <div class="panelHead">
        <h2>项目与账号</h2>
        <button onclick="saveSettings()">保存</button>
      </div>
        <div class="panelBody scrollBody">
          <label>产品名称</label>
        <div class="productPick">
          <select id="name"></select>
          <button id="refreshProductsBtn" onclick="refreshProducts()">刷新产品</button>
        </div>
        <div class="hint">来自 Obsidian 产品信息 Markdown 文件名，自动去掉 “-产品信息.md”。</div>
        <label>FastMoss 手机号</label>
        <input id="phone" autocomplete="off" />
        <label>FastMoss 密码</label>
        <input id="password" type="password" autocomplete="new-password" placeholder="留空则保持不变" />
        <div class="switchRow">
          <div>显示浏览器<span>勾选后运行时自动打开，可处理验证码或滑块</span></div>
          <input id="show_browser" type="checkbox" />
        </div>
        <div class="switchRow">
          <div>采集后下载视频<span>完整流程结束后调用 Kolsprite</span></div>
          <input id="download_enabled" type="checkbox" />
        </div>
        <div class="kv"><div class="k">配置</div><div class="v" id="configPath"></div></div>
        <div class="kv"><div class="k">项目目录</div><div class="v" id="projectPath"></div></div>
        <div class="hint">项目目录由产品名称自动生成，用于存放该产品的采集 CSV 和运行状态。</div>
        <div class="kv"><div class="k">采集 CSV 目录</div><div class="v" id="resultPath"></div></div>
        <div class="hint">采集得到的表格会输出到这里。</div>
        <div class="kv"><div class="k">爆款视频目录</div><div class="v" id="hotVideoPath"></div></div>
        <div class="hint">下载好的 MP4 和同名 JSON 会输出到这里。</div>
        <div class="kv"><div class="k">最新 CSV</div><div class="v" id="latestCsv"></div></div>
      </div>
    </section>

    <section>
      <div class="panelHead">
        <h2>采集条件</h2>
        <button class="blue" onclick="inspectAgent()">巡检</button>
      </div>
      <div class="panelBody scrollBody">
        <label>关键词</label>
        <input id="keyword" placeholder="可为空，仅使用国家、类目和筛选条件" />
        <div class="row3equal">
          <div>
            <label>国家/地区</label>
            <select id="country"></select>
          </div>
          <div>
            <label>商品状态</label>
            <select id="product_status"></select>
          </div>
          <div>
            <label>店铺类型</label>
            <select id="shop_type"></select>
          </div>
        </div>
        <div class="categoryGrid">
          <div>
            <label>一级类目</label>
            <select id="category_l1" onchange="onCategoryLevel1Change()"></select>
          </div>
          <div>
            <label>二级类目</label>
            <select id="category_l2" onchange="onCategoryLevel2Change()"></select>
          </div>
          <div>
            <label>三级类目</label>
            <select id="category_l3" onchange="updateCategoryPreview()"></select>
          </div>
        </div>
        <div class="row2">
          <div>
            <label>商品类型</label>
            <select id="product_types"></select>
          </div>
          <div>
            <label>当前类目路径</label>
            <input id="category_path_preview" readonly />
          </div>
        </div>
        <div class="row3">
          <div>
            <label>下载 CSV</label>
            <input id="source_csv" placeholder="留空使用最新采集 CSV" />
          </div>
          <div>
            <label>商品数</label>
            <input id="product_limit" type="number" min="1" />
          </div>
          <div>
            <label>视频/商品</label>
            <input id="videos_per_product" type="number" min="1" />
          </div>
        </div>
        <label>直接下载 URL</label>
        <textarea id="direct_urls" placeholder="每行一个 TikTok 视频链接；选择 URL下载 时只使用这里的链接"></textarea>
        <div class="hint">只下载你粘贴的视频，不运行 FastMoss 采集；保存到当前产品的爆款视频目录。</div>
        <div class="filterGrid">
          <div>
            <label>总销量</label>
            <select id="total_sales_filter"></select>
          </div>
          <div>
            <label>总 GMV</label>
            <select id="total_gmv_filter"></select>
          </div>
          <div>
            <label>近 7 天销量</label>
            <select id="sales_7d_filter"></select>
          </div>
          <div>
            <label>近 7 天 GMV</label>
            <select id="gmv_7d_filter"></select>
          </div>
          <div>
            <label>达人出单率</label>
            <select id="creator_conversion_rate_filter"></select>
          </div>
          <div>
            <label>带货达人数</label>
            <select id="creator_count_filter"></select>
          </div>
          <div>
            <label>佣金比例</label>
            <select id="commission_rate_filter"></select>
          </div>
          <div>
            <label>带货方式</label>
            <select id="shipping_method_filter"></select>
          </div>
          <div>
            <label>下载上限</label>
            <input id="download_limit" type="number" min="0" />
          </div>
        </div>
      </div>
    </section>

    <section class="run">
      <div class="panelHead">
        <h2>运行</h2>
        <button class="blue" onclick="refreshJob()">刷新</button>
      </div>
      <div class="panelBody runBody">
        <div>
          <div class="segmented" id="modeTabs">
            <button data-mode="pipeline" class="active" onclick="selectMode('pipeline')">完整</button>
            <button data-mode="collect" onclick="selectMode('collect')">采集</button>
            <button data-mode="download" onclick="selectMode('download')">下载</button>
            <button data-mode="url_download" onclick="selectMode('url_download')">URL下载</button>
            <button data-mode="login" onclick="selectMode('login')">登录</button>
          </div>
          <div class="actions">
            <button onclick="saveSettings()">保存配置</button>
            <button onclick="inspectAgent()">运行前巡检</button>
            <button class="primary wide" id="runBtn" onclick="runAgent()">开始运行</button>
          </div>
        </div>
        <div class="checks" id="checks"></div>
        <pre id="logs"></pre>
        <div class="outputs" id="outputs"></div>
      </div>
    </section>
  </main>
  <script>
    let selectedMode = 'pipeline';
    let pollTimer = null;
    let categoryData = {top_categories:['全部'], category_tree:{}};
    let formOptions = {};
    let hotVideoRoot = '';
    let browserViewerPort = 0;
    const $ = (id) => document.getElementById(id);

    async function api(path, options={}) {
      const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = {error:text}; }
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }

    function payload() {
      return {
        name: $('name').value,
        phone: $('phone').value,
        password: $('password').value,
        show_browser: $('show_browser').checked,
        download_enabled: $('download_enabled').checked,
        keyword: $('keyword').value,
        country: $('country').value,
        category_path: selectedCategoryPath().join(' > '),
        shop_type: $('shop_type').value,
        product_types: $('product_types').value === '全部' ? '' : $('product_types').value,
        product_status: $('product_status').value,
        product_limit: $('product_limit').value,
        videos_per_product: $('videos_per_product').value,
        creator_conversion_rate_filter: $('creator_conversion_rate_filter').value,
        total_sales_filter: $('total_sales_filter').value,
        total_gmv_filter: $('total_gmv_filter').value,
        sales_7d_filter: $('sales_7d_filter').value,
        gmv_7d_filter: $('gmv_7d_filter').value,
        creator_count_filter: $('creator_count_filter').value,
        commission_rate_filter: $('commission_rate_filter').value,
        shipping_method_filter: $('shipping_method_filter').value,
        source_csv: $('source_csv').value,
        download_limit: $('download_limit').value,
        direct_urls: $('direct_urls').value
      };
    }

    function setValue(id, value) {
      const el = $(id);
      if (el) el.value = value ?? '';
    }

    function fillState(data) {
      const c = data.config || {};
      const product = c.product || {};
      const f = c.fastmoss || {};
      const d = c.download || {};
      browserViewerPort = Number((data.environment || {}).browser_viewer_port || 0);
      formOptions = data.form_options || {};
      renderFixedSelects(f);
      renderProductNameOptions(data.product_options || [], product.name || '');
      setValue('phone', f.phone || '');
      setValue('password', f.password || '');
      $('show_browser').checked = !!f.show_browser;
      $('download_enabled').checked = d.enabled !== false;
      setValue('keyword', f.keyword || '');
      categoryData = data.category_data || categoryData;
      renderCategorySelectors(Array.isArray(f.category_path) ? f.category_path : String(f.category_path || '全部').split('>').map(x => x.trim()).filter(Boolean));
      setValue('product_limit', f.product_limit || 3);
      setValue('videos_per_product', f.videos_per_product || 5);
      setValue('source_csv', d.source_csv || '');
      setValue('download_limit', d.limit || 0);
      $('configPath').textContent = data.paths.config || '';
      $('projectPath').textContent = data.paths.project_root || '';
      $('resultPath').textContent = data.paths.result_dir || '';
      hotVideoRoot = data.paths.hot_video_root || '';
      $('hotVideoPath').textContent = data.paths.hot_video_dir || '';
      updateProductPathPreview();
      $('latestCsv').textContent = data.paths.latest_csv || '暂无';
      renderBadges(data);
    }

    function renderFixedSelects(f) {
      fillFixedSelect('country', f.country || '马来西亚');
      fillFixedSelect('shop_type', f.shop_type || '全部');
      fillFixedSelect('product_status', f.product_status || '在售');
      const productType = Array.isArray(f.product_types) ? (f.product_types[0] || '全部') : (f.product_types || '全部');
      fillFixedSelect('product_types', productType || '全部');
      [
        'creator_conversion_rate_filter',
        'total_sales_filter',
        'total_gmv_filter',
        'sales_7d_filter',
        'gmv_7d_filter',
        'creator_count_filter',
        'commission_rate_filter',
        'shipping_method_filter'
      ].forEach(id => fillFixedSelect(id, f[id] || '全部'));
    }

    function fillFixedSelect(id, selected) {
      const select = $(id);
      const options = (formOptions && formOptions[id]) ? formOptions[id].slice() : ['全部'];
      if (selected && !options.includes(selected)) options.push(selected);
      select.innerHTML = options.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
      select.value = selected && options.includes(selected) ? selected : options[0];
    }

    function setSelectOptions(select, values, placeholder) {
      const list = values && values.length ? values : [];
      select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` + list.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
    }

    function renderCategorySelectors(path) {
      const normalized = path && path.length ? path : ['全部'];
      const top = categoryData.top_categories || ['全部'];
      setSelectOptions($('category_l1'), top, '全部');
      $('category_l1').value = top.includes(normalized[0]) ? normalized[0] : '全部';
      onCategoryLevel1Change(normalized[1], normalized[2]);
    }

    function onCategoryLevel1Change(nextSecond='', nextThird='') {
      const first = $('category_l1').value || '全部';
      const secondMap = (categoryData.category_tree || {})[first] || {};
      const seconds = first === '全部' ? [] : Object.keys(secondMap);
      setSelectOptions($('category_l2'), seconds, first === '全部' ? '无需选择' : '请选择二级');
      $('category_l2').disabled = seconds.length === 0;
      if (nextSecond && seconds.includes(nextSecond)) $('category_l2').value = nextSecond;
      onCategoryLevel2Change(nextThird);
    }

    function onCategoryLevel2Change(nextThird='') {
      const first = $('category_l1').value || '全部';
      const second = $('category_l2').value || '';
      const secondMap = (categoryData.category_tree || {})[first] || {};
      const thirds = second && Array.isArray(secondMap[second]) ? secondMap[second] : [];
      setSelectOptions($('category_l3'), thirds, thirds.length ? '请选择三级' : '无需选择');
      $('category_l3').disabled = thirds.length === 0;
      if (nextThird && thirds.includes(nextThird)) $('category_l3').value = nextThird;
      updateCategoryPreview();
    }

    function selectedCategoryPath() {
      const first = $('category_l1').value || '全部';
      if (!first || first === '全部') return ['全部'];
      const second = $('category_l2').value || '';
      const third = $('category_l3').value || '';
      return [first, second, third].filter(Boolean);
    }

    function updateCategoryPreview() {
      $('category_path_preview').value = selectedCategoryPath().join(' > ');
    }

    function renderBadges(data) {
      $('configBadge').textContent = '产品目录已就绪';
      $('configBadge').className = 'badge ok';
      const env = data.environment || {};
      const ready = !!(env.has_phone && env.has_password);
      $('credentialBadge').textContent = ready ? '账号已就绪' : '缺少账号';
      $('credentialBadge').className = 'badge ' + (ready ? 'ok' : 'warn');
    }

    function renderProductNameOptions(options, selectedName) {
      const select = $('name');
      if (!options.length) {
        select.innerHTML = '<option value="">未找到产品信息 Markdown</option>';
        select.value = '';
        updateProductPathPreview();
        return;
      }
      select.innerHTML = options.map(item => {
        const selected = item.name === selectedName ? ' selected' : '';
        return `<option value="${escapeHtml(item.name)}"${selected}>${escapeHtml(item.name)}</option>`;
      }).join('');
      if (selectedName && [...select.options].some(option => option.value === selectedName)) {
        select.value = selectedName;
      } else {
        select.value = options[0].name;
      }
      select.onchange = updateProductPathPreview;
      updateProductPathPreview();
    }

    function safePathName(value) {
      const text = String(value || '').trim()
        .replace(/[\\/:*?"<>|]+/g, '_')
        .replace(/\s+/g, '_')
        .replace(/_+/g, '_')
        .replace(/^[ ._]+|[ ._]+$/g, '');
      return text || 'product';
    }

    function updateProductPathPreview() {
      const productName = $('name') ? $('name').value : '';
      const safeName = safePathName(productName);
      if ($('projectPath')) {
        $('projectPath').textContent = productName ? `projects/${safeName}` : '';
      }
      if ($('resultPath')) {
        $('resultPath').textContent = productName ? `projects/${safeName}/collection_runs/results` : '';
      }
      if ($('hotVideoPath')) {
        $('hotVideoPath').textContent = productName && hotVideoRoot ? `${hotVideoRoot}/${safeName}` : '';
      }
    }

    function selectMode(mode) {
      selectedMode = mode;
      document.querySelectorAll('#modeTabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.mode === mode));
      const text = {pipeline:'开始完整流程', collect:'开始采集', download:'开始下载', url_download:'开始 URL 下载', login:'刷新登录'}[mode] || '开始运行';
      $('runBtn').textContent = text;
    }

    async function saveSettings() {
      const data = await api('/api/settings', {method:'POST', body:JSON.stringify(payload())});
      fillState(data);
      await inspectAgent();
    }

    async function refreshProducts() {
      const btn = $('refreshProductsBtn');
      const selectedBefore = $('name').value;
      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = '刷新中';
      try {
        const data = await api('/api/products/refresh', {method:'POST', body:JSON.stringify({})});
        fillState(data);
        if (selectedBefore && [...$('name').options].some(option => option.value === selectedBefore)) {
          $('name').value = selectedBefore;
          updateProductPathPreview();
        }
        const refresh = data.product_refresh || {};
        renderChecks([{
          level: refresh.warning ? 'warn' : 'ok',
          message: refresh.warning ? '已使用本地产品索引' : '产品名称已刷新',
          detail: `${refresh.warning || ''} 已加载 ${refresh.count || (data.product_options || []).length} 个产品；索引: ${refresh.index_path || ''}`
        }]);
      } catch (err) {
        renderChecks([{level:'error', message:'产品名称刷新失败', detail:err.message}]);
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    }

    async function inspectAgent() {
      await api('/api/settings', {method:'POST', body:JSON.stringify(payload())});
      const data = await api('/api/inspect');
      renderChecks(data.checks || []);
    }

    async function runAgent() {
      $('logs').textContent = '';
      if ($('show_browser').checked && browserViewerPort) {
        const viewerUrl = `${window.location.protocol}//${window.location.hostname}:${browserViewerPort}/vnc.html?autoconnect=1&resize=scale&reconnect=1`;
        window.open(viewerUrl, `opc-browser-${browserViewerPort}`);
      }
      await api('/api/settings', {method:'POST', body:JSON.stringify(payload())});
      const data = await api('/api/run', {method:'POST', body:JSON.stringify({mode:selectedMode, direct_urls:$('direct_urls').value})});
      renderJob(data);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1200);
    }

    async function refreshJob() {
      const data = await api('/api/job');
      renderJob(data);
      if (!data.running && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
        const state = await api('/api/state');
        fillState(state);
      }
    }

    function renderChecks(checks=[]) {
      const labels = {ok:'通过', warn:'注意', error:'错误'};
      $('checks').innerHTML = checks.map(item => `
        <div class="check ${escapeHtml(item.level || '')}">
          <div><strong>${escapeHtml(labels[item.level] || '信息')}</strong>${escapeHtml(item.message || '')}</div>
          ${item.detail ? `<div class="detail">${escapeHtml(item.detail)}</div>` : ''}
        </div>
      `).join('') || '<div class="muted tiny">暂无巡检结果</div>';
    }

    function renderJob(job) {
      const statusText = {idle:'空闲', running:'运行中', completed:'已完成', failed:'失败'};
      $('jobBadge').textContent = job.running ? '运行中' : (statusText[job.status] || job.status || '空闲');
      $('jobBadge').className = 'badge ' + (job.status === 'failed' ? 'error' : job.status === 'completed' ? 'ok' : '');
      $('runBtn').disabled = !!job.running;
      $('logs').textContent = job.logs || '';
      $('logs').scrollTop = $('logs').scrollHeight;
      if (job.error) renderChecks([{level:'error', message:'任务失败', detail:job.error}]);
      renderOutputs(job.outputs || []);
    }

    function renderOutputs(outputs=[]) {
      $('outputs').innerHTML = outputs.map(item => `
        <div class="outputItem">
          <div>
            <strong>${escapeHtml(item.name || '')}</strong>
            <div class="path">${escapeHtml(item.path || '')}</div>
          </div>
          ${item.kind === 'folder' ? '<span class="tiny">目录</span>' : `<button onclick="previewFile('${encodeURIComponent(item.path || '')}')">预览</button>`}
        </div>
      `).join('') || '<div class="muted tiny">运行完成后显示报告、CSV 和视频路径</div>';
    }

    async function previewFile(encodedPath) {
      const data = await api(`/api/file?path=${encodedPath}`);
      $('logs').textContent = data.text || '';
      $('logs').scrollTop = 0;
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({
        '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
      }[ch]));
    }

    async function boot() {
      const state = await api('/api/state');
      fillState(state);
      selectMode('pipeline');
      await inspectAgent();
      await refreshJob();
    }

    boot().catch(err => renderChecks([{level:'error', message:'页面初始化失败', detail:err.message}]));
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path in {"/", "/collect"}:
                text_response(self, 200, HTML, "text/html; charset=utf-8")
            elif parsed.path == "/health":
                json_response(self, 200, {"status": "ok"})
            elif parsed.path == "/api/state":
                json_response(self, 200, config_for_client())
            elif parsed.path == "/api/inspect":
                json_response(self, 200, inspect_config())
            elif parsed.path == "/api/job":
                json_response(self, 200, JOB.snapshot())
            elif parsed.path == "/api/file":
                query = urllib.parse.parse_qs(parsed.query)
                raw_path = query.get("path", [""])[0]
                path = safe_read_path(raw_path)
                if not path.exists() or not path.is_file():
                    raise ValueError("文件不存在")
                text = path.read_text(encoding="utf-8", errors="ignore")
                json_response(self, 200, {"path": display_path(path), "text": text[:300000]})
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert UI errors to API errors.
            json_response(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = read_request_json(self)
            if parsed.path == "/api/settings":
                json_response(self, 200, update_config(payload))
            elif parsed.path == "/api/products/refresh":
                refresh = refresh_product_info_index()
                state = config_for_client()
                state["product_refresh"] = refresh
                json_response(self, 200, state)
            elif parsed.path == "/api/run":
                mode = str(payload.get("mode") or "pipeline")
                if mode not in {"pipeline", "collect", "download", "url_download", "login"}:
                    raise ValueError("未知运行模式")
                json_response(self, 200, JOB.start(mode, payload))
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - convert UI errors to API errors.
            json_response(self, 400, {"error": str(exc)})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hot video collection agent web UI.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    init_config(CONFIG_PATH)
    migrate_runtime_support_files()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"爆款视频收集智能体 Web 界面: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
