#!/usr/bin/env python3
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import ensure_project_dirs, latest_collection_csv, require_product_project, source_id_from_row, source_stage_dir


ROOT = Path(__file__).resolve().parents[3]
DOWNLOADER_URL = "https://dl.kolsprite.com/tools/video-download"


def load_config():
    return load_app_config()


CONFIG = load_config()
require_product_project(CONFIG, "下载爆款视频")
PROJECT_ROOT = ensure_project_dirs(CONFIG)
SHOW_BROWSER = bool(CONFIG.get("show_browser", False))


def log(message):
    print(message, flush=True)


def minimize_browser_windows():
    if SHOW_BROWSER:
        return
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Google Chrome for Testing" to set miniaturized of every window to true',
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log("已最小化浏览器窗口")
    except Exception:
        log("浏览器窗口最小化失败，继续执行任务")


def safe_filename(value, max_length=120):
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length].strip(" ._") or "video"


def find_latest_csv():
    candidate = latest_collection_csv(CONFIG)
    if not candidate:
        raise SystemExit("当前产品项目里没有找到包含 tiktok_video_url 字段的采集 CSV")
    with candidate.open(encoding="utf-8-sig") as f:
        fieldnames = csv.DictReader(f).fieldnames or []
    if "tiktok_video_url" not in fieldnames:
        raise SystemExit(f"最新采集 CSV 不包含 tiktok_video_url 字段: {candidate}")
    return candidate


def load_rows(csv_path):
    with csv_path.open(encoding="utf-8-sig") as f:
        rows = [row for row in csv.DictReader(f) if row.get("tiktok_video_url")]
    if not rows:
        raise SystemExit(f"CSV 没有可下载的 tiktok_video_url: {csv_path}")
    return rows


def click_first_visible_text(page, text, timeout=20000):
    locator = page.get_by_text(text, exact=False)
    locator.first.wait_for(state="visible", timeout=timeout)
    locator.first.click()


def normalize_tiktok_download_url(url):
    url = (url or "").strip()
    if "?" in url:
        url = url.split("?", 1)[0]
    return url


def download_one(page, row):
    url = normalize_tiktok_download_url(row["tiktok_video_url"])
    video_id_match = re.search(r"/video/(\d+)", url)
    if not video_id_match:
        raise RuntimeError(f"无法从 TikTok URL 提取 video id: {url}")
    video_id = video_id_match.group(1)
    source_id = source_id_from_row(row) or video_id
    output_dir = source_stage_dir(source_id, "source", CONFIG)
    target = output_dir / f"{video_id}.mp4"
    if target.exists():
        log(f"  已存在，跳过: {target.name}")
        return target

    log(f"  打开下载页并提交 URL: {video_id}")
    page.goto(DOWNLOADER_URL, wait_until="networkidle")

    input_box = page.locator("input[placeholder*='TikTok'], input[placeholder*='链接'], input").first
    input_box.wait_for(state="visible", timeout=20000)
    input_box.fill(url)

    click_first_visible_text(page, "立即下载", timeout=10000)
    log("  等待解析完成...")

    high_quality = page.get_by_text(re.compile(r"下载无水印\s*Mp4.*高清", re.I))
    try:
        high_quality.first.wait_for(state="visible", timeout=60000)
    except PlaywrightTimeoutError:
        raise RuntimeError(f"解析超时: {url}")

    log("  点击高清无水印下载...")
    with page.expect_download(timeout=60000) as download_info:
        high_quality.first.click()
    download = download_info.value

    suggested = download.suggested_filename
    suffix = Path(suggested).suffix or ".mp4"
    target = output_dir / f"{video_id}{suffix}"
    download.save_as(str(target))
    metadata_path = output_dir / "source_metrics.json"
    metadata_path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"  保存完成: {target.name}")
    return target


def main():
    csv_path = find_latest_csv()
    rows = load_rows(csv_path)

    log("开始下载任务")
    log(f"读取 CSV: {csv_path}")
    log(f"视频数量: {len(rows)}")
    log(f"项目目录: {PROJECT_ROOT}")
    log("下载目录: 当前产品项目 / hot_sources / 视频ID / source")
    log(f"浏览器模式: {'可见窗口' if SHOW_BROWSER else '最小化窗口'}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=350,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
                *(["--start-minimized", "--window-size=1440,900"] if not SHOW_BROWSER else []),
            ],
        )
        minimize_browser_windows()
        context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 900})
        page = context.new_page()

        failures = []
        for index, row in enumerate(rows, start=1):
            log(f"[{index}/{len(rows)}] {row['tiktok_video_url']}")
            try:
                target = download_one(page, row)
                log(f"  当前完成: {target}")
            except Exception as exc:
                log(f"  下载失败: {exc}")
                failures.append((index, str(exc)))

        try:
            input("下载任务完成。浏览器保持打开，按回车退出...")
        except EOFError:
            pass
        context.close()
        if failures:
            raise RuntimeError(f"下载失败 {len(failures)}/{len(rows)} 条")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"任务失败: {exc}")
        sys.exit(1)
