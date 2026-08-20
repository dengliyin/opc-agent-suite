from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright

from .config import VIDEO_USERNAME_MAX, browser_headless, safe_name, video_filename_stem
from .paths import ProjectPaths


DOWNLOADER_URL = "https://dl.kolsprite.com/tools/video-download"
KOLSPRITE_API_URL = "https://www.kolsprite.com/api/v2/video/fetch_video_data_by_url"


def chromium_launch_options() -> Dict[str, str]:
    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
    return {"executable_path": executable_path} if executable_path else {}


class KolspriteDownloader:
    def __init__(self, config: Dict[str, Any], paths: ProjectPaths, logger=print) -> None:
        self.config = config
        self.paths = paths
        self.log = logger
        self.fastmoss = config.get("fastmoss") or {}
        self.download = config.get("download") or {}
        self.show_browser = bool(self.fastmoss.get("show_browser", False))
        self.headless = browser_headless(self.show_browser)
        self.limit = int(self.download.get("limit") or 0)
        self.retry_count = max(1, int(self.download.get("retry_count") or 3))
        self.current_result_dir: Optional[Path] = None

    def browser_profile_dir(self) -> Path:
        phone = str(self.fastmoss.get("phone") or "").strip()
        return self.paths.root / "browser-profile" / "fastmoss" / safe_name(phone, "default", 80)

    def minimize_browser_windows(self) -> None:
        if self.show_browser or self.headless:
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
            self.log("已最小化浏览器窗口")
        except Exception:
            self.log("浏览器窗口最小化失败，继续执行任务")

    @staticmethod
    def normalize_tiktok_download_url(url: str) -> str:
        url = (url or "").strip()
        if "?" in url:
            url = url.split("?", 1)[0]
        return url

    @staticmethod
    def parse_tiktok_identity(url: str) -> Tuple[str, str]:
        normalized = KolspriteDownloader.normalize_tiktok_download_url(url)
        match = re.search(r"tiktok\.com/@([^/?#]+)/video/(\d+)", normalized, flags=re.I)
        if not match:
            raise RuntimeError(f"无法从 TikTok URL 提取用户名和 video id: {url}")
        return match.group(1), match.group(2)

    def find_csv(self, csv_path: Optional[Path] = None) -> Path:
        configured = str(self.download.get("source_csv") or "").strip()
        if csv_path:
            candidate = Path(csv_path)
        elif configured:
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                candidate = self.paths.root / candidate
        else:
            candidate = self.paths.latest_collection_csv()
            if not candidate:
                raise RuntimeError("当前产品项目里没有找到包含 tiktok_video_url 字段的采集 CSV")

        if not candidate.exists():
            raise RuntimeError(f"找不到采集 CSV: {candidate}")
        with candidate.open(encoding="utf-8-sig") as handle:
            fieldnames = csv.DictReader(handle).fieldnames or []
        if "tiktok_video_url" not in fieldnames:
            raise RuntimeError(f"采集 CSV 不包含 tiktok_video_url 字段: {candidate}")
        return candidate

    def load_rows(self, csv_path: Path) -> List[Dict[str, str]]:
        with csv_path.open(encoding="utf-8-sig") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get("tiktok_video_url")]
        if self.limit > 0:
            rows = rows[: self.limit]
        if not rows:
            raise RuntimeError(f"CSV 没有可下载的 tiktok_video_url: {csv_path}")
        return rows

    def output_dir_for_source(self, source_id: str = "") -> Path:
        return self.paths.hot_video_dir()

    def filename_stem_for_row(
        self,
        row: Dict[str, str],
        video_id: str,
        url: str,
        page_title: str = "",
    ) -> str:
        try:
            username, _ = self.parse_tiktok_identity(url)
        except RuntimeError:
            username = str(row.get("creator_name") or row.get("username") or row.get("author") or "").strip()
            if not username:
                username = "unknown_user"
        title = page_title.strip() or str(row.get("video_title") or row.get("title") or "").strip() or "untitled"
        title = re.sub(r"^\s*ads\s*", "", title, flags=re.I).strip() or "untitled"
        return video_filename_stem(username, video_id, title)

    def row_download_info(self, row: Dict[str, str]) -> Tuple[str, str, Path, Path]:
        url = self.normalize_tiktok_download_url(row["tiktok_video_url"])
        _, video_id = self.parse_tiktok_identity(url)
        output_dir = self.output_dir_for_source()
        target = output_dir / f"{self.filename_stem_for_row(row, video_id, url)}.mp4"
        metadata_path = target.with_suffix(".json")
        return url, video_id, target, metadata_path

    def target_for_row(
        self,
        row: Dict[str, str],
        video_id: str,
        url: str,
        suffix: str = ".mp4",
        page_title: str = "",
    ) -> Path:
        output_dir = self.output_dir_for_source()
        return output_dir / f"{self.filename_stem_for_row(row, video_id, url, page_title)}{suffix}"

    def existing_video_for_identity(self, username: str, video_id: str) -> Optional[Path]:
        output_dir = self.output_dir_for_source()
        candidates = sorted(output_dir.glob(f"*-{video_id}-*.mp4"))
        if not candidates:
            candidates = sorted(output_dir.glob(f"{video_id}.mp4"))
        expected_username = username.lower()
        for candidate in candidates:
            if not candidate.exists() or candidate.stat().st_size <= 100000:
                continue
            metadata_path = candidate.with_suffix(".json")
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata_url = str(metadata.get("tiktok_video_url") or "")
                    found_username, found_video_id = self.parse_tiktok_identity(metadata_url)
                    if found_username.lower() == expected_username and found_video_id == video_id:
                        return candidate
                except Exception:
                    pass
            safe_username = safe_name(username, "unknown_user", VIDEO_USERNAME_MAX).lower()
            if candidate.stem.lower().startswith(f"{safe_username}-{video_id}-"):
                return candidate
        return None

    def metadata_for_row(
        self,
        row: Dict[str, str],
        video_id: str,
        url: str,
        page_title: str = "",
    ) -> Dict[str, str]:
        excluded = {"roas_28d", "ad_spend_28d", "fastmoss_video_url"}
        clean_page_title = page_title.strip()
        payload: Dict[str, str] = {
            "collected_at": datetime.now().astimezone().date().isoformat(),
        }
        for key, value in row.items():
            if key in excluded:
                continue
            if key == "video_title":
                title = clean_page_title or re.sub(r"^\s*ads\s*", "", str(value or ""), flags=re.I).strip()
                payload[key] = title
                continue
            payload[key] = value
        payload.setdefault("tiktok_video_url", url)
        if clean_page_title:
            payload["video_title"] = clean_page_title
        payload["video_id"] = video_id
        return payload

    def write_metadata(
        self,
        path: Path,
        row: Dict[str, str],
        video_id: str,
        url: str,
        page_title: str = "",
    ) -> None:
        payload = self.metadata_for_row(row, video_id, url, page_title=page_title)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def fetch_kolsprite_video_data(self, url: str) -> Dict[str, Any]:
        api_url = KOLSPRITE_API_URL + "?" + urllib.parse.urlencode({"url": url})
        request = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not payload.get("success"):
            message = payload.get("message") if isinstance(payload, dict) else "返回格式错误"
            raise RuntimeError(f"Kolsprite 解析失败: {message}")
        if not (data.get("hdUrls") or data.get("urls")):
            raise RuntimeError("Kolsprite 没有返回可下载的视频地址")
        return data

    @staticmethod
    def save_video_url(url: str, target: Path) -> None:
        partial = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as handle:
                shutil.copyfileobj(response, handle, length=1024 * 1024)
            if partial.stat().st_size <= 100000:
                raise RuntimeError("Kolsprite 返回的视频文件过小")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)

    def download_one(self, page, row: Dict[str, str]) -> Tuple[str, Path]:
        url, video_id, target, metadata_path = self.row_download_info(row)
        username, _ = self.parse_tiktok_identity(url)

        existing = self.existing_video_for_identity(username, video_id)
        if existing:
            self.write_metadata(existing.with_suffix(".json"), row, video_id, url)
            self.log(f"  已存在，已更新 JSON，跳过视频下载: {existing.name}")
            return "skipped", existing

        self.log(f"  打开下载页并提交 URL: {video_id}")
        page.goto(DOWNLOADER_URL, wait_until="domcontentloaded", timeout=60000)

        input_box = page.locator("input[placeholder*='TikTok'], input[placeholder*='链接'], input").first
        input_box.wait_for(state="visible", timeout=20000)
        input_box.fill(url)
        self.log("  通过 Kolsprite 解析视频...")
        data = self.fetch_kolsprite_video_data(url)
        video_urls = data.get("hdUrls") or data.get("urls") or []
        page_title = str(data.get("desc") or "").strip()
        target = self.target_for_row(row, video_id, url, page_title=page_title)
        metadata_path = target.with_suffix(".json")
        self.log("  下载高清无水印 MP4...")
        self.save_video_url(str(video_urls[0]), target)
        self.write_metadata(metadata_path, row, video_id, url, page_title=page_title)
        self.log(f"  保存完成: {target.name}")
        return "downloaded", target

    @staticmethod
    def is_browser_closed_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message or "browser has been closed" in message

    def download_one_with_retries(
        self,
        page,
        row: Dict[str, str],
        reset_page: Optional[Callable[[], Any]] = None,
    ) -> Tuple[str, Path]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retry_count + 1):
            try:
                if attempt > 1:
                    self.log(f"  第 {attempt}/{self.retry_count} 次重试解析...")
                return self.download_one(page, row)
            except Exception as exc:
                last_error = exc
                if reset_page and self.is_browser_closed_error(exc):
                    self.log("  浏览器上下文已关闭，重新打开后继续...")
                    page = reset_page()
                if attempt >= self.retry_count:
                    break
                self.log(f"  本次解析失败: {exc}")
                try:
                    page.goto("about:blank")
                    page.wait_for_timeout(2500)
                except Exception:
                    pass
        raise RuntimeError(f"Kolsprite 多次尝试仍然失败: {last_error}")

    def run(self, csv_path: Optional[Path] = None) -> Tuple[Path, List[Path], List[Path], List[str]]:
        source_csv = self.find_csv(csv_path)
        self.current_result_dir = source_csv.parent
        rows = self.load_rows(source_csv)

        self.log("开始下载任务")
        self.log(f"读取 CSV: {source_csv}")
        self.log(f"视频数量: {len(rows)}")
        self.log(f"项目目录: {self.paths.project_root}")
        self.log(f"结果文件夹: {self.current_result_dir}")
        self.log(f"下载目录: {self.paths.hot_video_dir()}")
        browser_mode = "无头模式" if self.headless else ("可见窗口" if self.show_browser else "最小化窗口")
        self.log(f"浏览器模式: {browser_mode}")

        downloaded: List[Path] = []
        skipped: List[Path] = []
        failures: List[str] = []

        with sync_playwright() as p:
            profile_dir = self.browser_profile_dir()
            profile_dir.mkdir(parents=True, exist_ok=True)
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
            ]
            if not self.show_browser and not self.headless:
                browser_args.extend(["--start-minimized", "--window-size=1440,900"])
            context = None
            page = None

            def open_page():
                nonlocal context, page
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=self.headless,
                    slow_mo=350,
                    accept_downloads=True,
                    viewport={"width": 1440, "height": 900},
                    args=browser_args,
                    **chromium_launch_options(),
                )
                self.minimize_browser_windows()
                page = context.pages[0] if context.pages else context.new_page()
                return page

            def reset_page():
                nonlocal context, page
                try:
                    if context:
                        context.close()
                except Exception:
                    pass
                time.sleep(1)
                return open_page()

            page = open_page()
            try:
                for index, row in enumerate(rows, start=1):
                    self.log(f"[{index}/{len(rows)}] {row['tiktok_video_url']}")
                    try:
                        status, target = self.download_one_with_retries(page, row, reset_page)
                        if status == "downloaded":
                            downloaded.append(target)
                        else:
                            skipped.append(target)
                        self.log(f"  当前完成: {target}")
                    except Exception as exc:
                        message = f"第 {index} 条下载失败: {exc}"
                        self.log(f"  {message}")
                        failures.append(message)
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        if failures:
            self.log(f"下载完成，但有失败项: {len(failures)}")
        else:
            self.log("下载任务完成")
        return source_csv, downloaded, skipped, failures


def main() -> int:
    from .config import ROOT, load_config, validate_config

    config = load_config()
    validate_config(config, require_credentials=False)
    paths = ProjectPaths(ROOT, config)
    paths.ensure()
    downloader = KolspriteDownloader(config, paths)
    _, _, _, failures = downloader.run()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
