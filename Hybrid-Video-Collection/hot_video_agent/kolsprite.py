from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import VIDEO_USERNAME_MAX, safe_name, video_filename_stem
from .paths import ProjectPaths


DOWNLOADER_URL = "https://dl.kolsprite.com/tools/video-download"
DOWNLOADER_SUBMIT_TEXT = re.compile(r"^(立即下载|开始解析|解析|下载)$")
SNAPTIK_URL = "https://snaptik.app/en2"


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
        self.limit = int(self.download.get("limit") or 0)
        self.retry_count = max(1, int(self.download.get("retry_count") or 3))
        self.parse_timeout_ms = max(60000, int(self.download.get("parse_timeout_ms") or 90000))
        self.current_result_dir: Optional[Path] = None

    def browser_profile_dir(self) -> Path:
        phone = str(self.fastmoss.get("phone") or "").strip()
        return self.paths.root / "browser-profile" / "fastmoss" / safe_name(phone, "default", 80)

    def minimize_browser_windows(self) -> None:
        if self.show_browser:
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

    def extract_kolsprite_title(self, page) -> str:
        selectors = [
            ".style_video_details_text__TMXot",
            "p[class*='video_details_text']",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=5000)
                title = (locator.inner_text(timeout=2000) or "").strip()
                if title:
                    self.log(f"  解析页标题: {title[:80]}")
                    return title
            except Exception:
                continue
        return ""

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

    @staticmethod
    def click_first_visible_text(page, text: str, timeout: int = 20000) -> None:
        locator = page.get_by_text(text, exact=False)
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.click()

    def confirm_kolsprite_download_quota(self, page, timeout: int = 12000) -> bool:
        confirm = page.get_by_text("确认下载", exact=True)
        try:
            confirm.first.wait_for(state="visible", timeout=timeout)
            confirm.first.click()
            self.log("  已确认 Kolsprite 下载额度弹窗")
            page.wait_for_timeout(1200)
            return True
        except PlaywrightTimeoutError:
            return False

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

        submit = page.get_by_role("button", name=DOWNLOADER_SUBMIT_TEXT).or_(page.get_by_text(DOWNLOADER_SUBMIT_TEXT))
        submit.first.wait_for(state="visible", timeout=10000)
        submit.first.click()
        self.confirm_kolsprite_download_quota(page)
        self.log("  等待解析完成...")

        high_quality = page.get_by_text("下载无水印Mp4", exact=True).or_(
            page.locator("a:has-text('下载无水印Mp4'), button:has-text('下载无水印Mp4')")
        )
        try:
            high_quality.first.wait_for(state="visible", timeout=self.parse_timeout_ms)
        except PlaywrightTimeoutError:
            raise RuntimeError(f"解析超时: {url}")

        page_title = self.extract_kolsprite_title(page)
        self.log("  点击下载无水印Mp4...")
        with page.expect_download(timeout=60000) as download_info:
            high_quality.first.click()
        download = download_info.value

        suggested = download.suggested_filename
        suffix = Path(suggested).suffix or ".mp4"
        target = self.target_for_row(row, video_id, url, suffix=suffix, page_title=page_title)
        metadata_path = target.with_suffix(".json")
        self.write_metadata(metadata_path, row, video_id, url, page_title=page_title)
        download.save_as(str(target))
        self.log(f"  保存完成: {target.name}")
        return "downloaded", target

    @staticmethod
    def click_first_visible(locator, timeout_ms: int = 500) -> bool:
        try:
            count = min(locator.count(), 5)
        except Exception:
            return False
        for index in range(count):
            item = locator.nth(index)
            try:
                if item.is_visible(timeout=timeout_ms):
                    item.click(force=True, timeout=3000)
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def is_browser_closed_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message or "browser has been closed" in message

    def close_snaptik_ad_pages(self, page) -> bool:
        closed = False
        try:
            pages = list(page.context.pages)
        except Exception:
            return False
        for extra_page in pages:
            if extra_page == page:
                continue
            try:
                if not extra_page.is_closed():
                    extra_page.close()
                    closed = True
            except Exception:
                continue
        if closed:
            self.log("  已关闭 SnapTik 弹出的广告页")
        return closed

    def close_snaptik_popup(self, page, timeout_ms: int = 2500) -> bool:
        """Close SnapTik/Google vignette popups before retrying the download click."""
        close_text = re.compile(r"^\s*(close|关闭|×|x)\s*$", re.I)
        selectors = [
            "#modal-vignette .modal-close",
            "#modal-vignette .continue-web",
            ".modal.is-active .modal-close",
            ".modal.is-active .continue-web",
            "[aria-label='Close']",
            "[aria-label='close']",
            "[aria-label*='close' i]",
            "[data-testid*='close' i]",
            "[id*='close' i]",
            "[id*='dismiss' i]",
            "[class*='close' i]",
            "button:has-text('Close')",
            "a:has-text('Close')",
            "div:text-is('Close')",
            "span:text-is('Close')",
            "text=/^\\s*Close\\s*$/i",
        ]
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.close_snaptik_ad_pages(page)
            frames = []
            try:
                frames = list(page.frames)
            except Exception:
                frames = []
            for frame in frames:
                locators = [
                    frame.get_by_role("button", name=close_text),
                    frame.get_by_text(close_text),
                    *(frame.locator(selector) for selector in selectors),
                ]
                for locator in locators:
                    if self.click_first_visible(locator):
                        page.wait_for_timeout(900)
                        self.log("  已点击 SnapTik 弹窗右上角 Close")
                        return True
            page.wait_for_timeout(250)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        return False

    def find_snaptik_download_button(self, page):
        candidates = [
            "#download a.download-file:has-text('Download Video')",
            "#download a:has-text('Download Video')",
            "a.download-file:has-text('Download Video')",
        ]
        for selector in candidates:
            locator = page.locator(selector)
            try:
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return page.locator("#download a.download-file, #download a[href]").first

    def wait_for_snaptik_download_button(self, page, timeout_ms: int = 60000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            self.close_snaptik_popup(page, timeout_ms=900)
            button = self.find_snaptik_download_button(page)
            try:
                if button.count() > 0 and button.is_visible(timeout=700):
                    return button
            except Exception:
                pass
            page.wait_for_timeout(1000)
        body_text = page.locator("body").inner_text(timeout=5000)
        raise RuntimeError(f"SnapTik 未返回下载按钮: {body_text[:300]}")

    def save_snaptik_href(self, page, button, output_dir: Path, video_id: str) -> Optional[Path]:
        href = button.get_attribute("href") or ""
        if not href or href.startswith("javascript:"):
            return None
        if href.startswith("/"):
            href = "https://snaptik.app" + href
        self.log("  尝试直接读取 SnapTik 下载链接")
        response = page.request.get(href, timeout=90000)
        body = response.body()
        content_type = (response.headers.get("content-type") or "").lower()
        if response.status < 400 and len(body) > 100000 and ("video" in content_type or "octet" in content_type):
            target = output_dir / f"{video_id}.mp4"
            target.write_bytes(body)
            self.log(f"  SnapTik 保存完成: {target.name}")
            return target
        return None

    def download_one_snaptik(self, page, row: Dict[str, str]) -> Tuple[str, Path]:
        url = self.normalize_tiktok_download_url(row.get("tiktok_video_url") or "")
        username, video_id = self.parse_tiktok_identity(url)
        output_dir = self.output_dir_for_source()
        target = self.target_for_row(row, video_id, url)
        metadata_path = target.with_suffix(".json")

        existing = self.existing_video_for_identity(username, video_id)
        if existing:
            self.write_metadata(existing.with_suffix(".json"), row, video_id, url)
            self.log(f"  已存在，已更新 JSON，跳过视频下载: {existing.name}")
            return "skipped", existing

        self.write_metadata(metadata_path, row, video_id, url)

        self.log(f"  切换 SnapTik 备用下载源: {video_id}")
        page.goto(SNAPTIK_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        self.close_snaptik_popup(page, timeout_ms=4000)

        input_box = page.locator('form[name="formurl"] input#url, input[name="url"]').first
        input_box.wait_for(state="visible", timeout=20000)
        input_box.fill(url)
        page.locator('form[name="formurl"] button[type="submit"], button.button-go').first.click(force=True, timeout=10000)
        self.close_snaptik_popup(page, timeout_ms=1500)

        button = self.wait_for_snaptik_download_button(page, timeout_ms=60000)

        for attempt in range(1, 4):
            self.log(f"  点击 SnapTik Download Video（第 {attempt} 次）")
            try:
                self.close_snaptik_popup(page, timeout_ms=1200)
                button.scroll_into_view_if_needed(timeout=5000)
                with page.expect_download(timeout=12000) as download_info:
                    button.click(timeout=7000)
                download = download_info.value
                suffix = Path(download.suggested_filename).suffix or ".mp4"
                final_target = output_dir / f"{video_id}{suffix}"
                download.save_as(str(final_target))
                self.log(f"  SnapTik 保存完成: {final_target.name}")
                return "downloaded", final_target
            except Exception as exc:
                self.log(f"  SnapTik 点击后未直接下载: {exc}")
                self.close_snaptik_popup(page, timeout_ms=5000)
                direct_target = self.save_snaptik_href(page, button, output_dir, video_id)
                if direct_target:
                    return "downloaded", direct_target
                if attempt == 3:
                    raise RuntimeError(f"SnapTik 下载按钮点击失败: {exc}")
                button = self.wait_for_snaptik_download_button(page, timeout_ms=15000)
        raise RuntimeError("SnapTik 下载失败")

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
        self.log(f"  Kolsprite 多次失败，改用 SnapTik: {last_error}")
        if last_error and reset_page and self.is_browser_closed_error(last_error):
            page = reset_page()
        return self.download_one_snaptik(page, row)

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
        self.log(f"浏览器模式: {'可见窗口' if self.show_browser else '最小化窗口'}")

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
            if not self.show_browser:
                browser_args.extend(["--start-minimized", "--window-size=1440,900"])
            context = None
            page = None

            def open_page():
                nonlocal context, page
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=False,
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
