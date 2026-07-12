#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from urllib.parse import urlparse

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import raw_data_dir, require_product_project, runtime_state_path


ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = ROOT / "browser-profile" / "natural-flow"
STORAGE_STATE = runtime_state_path("natural-flow-state.json")
DEFAULT_EXPORT_TEXT_RE = r"导出|下载|Export|Download"


def log(message: str) -> None:
    print(message, flush=True)


def load_config() -> dict:
    return load_app_config()


def derive_platform_url(management_url: str, path: str) -> str:
    parsed = urlparse(str(management_url or ""))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def natural_flow_management_url(config: dict) -> str:
    return (
        os.environ.get("NATURAL_FLOW_MANAGEMENT_URL")
        or str(config.get("natural_flow_management_url") or "")
    ).strip()


def natural_flow_login_url(config: dict, management_url: str) -> str:
    return (
        os.environ.get("NATURAL_FLOW_LOGIN_URL")
        or str(config.get("natural_flow_login_url") or "")
        or derive_platform_url(management_url, "/login?redirect=%2Fdashboard")
    ).strip()


def resolve_path(value: str | None, default: Path | None = None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return default
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def is_login_page(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return "/login" in page.url or ("用户名/手机号" in text and "验证码" in text)


def is_logged_in(page) -> bool:
    if is_login_page(page):
        return False
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return any(marker in text for marker in ["退出", "退出登录", "账号", "首页", "工作台", "Dashboard", "dashboard"])


def add_saved_cookies(context) -> None:
    if not STORAGE_STATE.exists():
        return
    try:
        saved_state = json.loads(STORAGE_STATE.read_text(encoding="utf-8"))
        cookies = saved_state.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
    except Exception:
        pass


def fill_login_if_possible(page) -> bool:
    username = os.environ.get("NATURAL_FLOW_USERNAME")
    password = os.environ.get("NATURAL_FLOW_PASSWORD")
    if not username or not password:
        return False
    try:
        page.get_by_placeholder("用户名/手机号").fill(username, timeout=5000)
        page.get_by_placeholder("密码").fill(password, timeout=5000)
        log("检测到登录页，已自动填写用户名和密码。若有验证码，请在可见浏览器里手动完成。")
        return True
    except Exception:
        return False


def minimize_browser_windows(show_browser: bool) -> None:
    if show_browser:
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
        pass


def ensure_logged_in(page, context, target_url: str, login_url: str, show_browser: bool) -> None:
    log("检查自然流数据平台登录状态...")
    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    if is_logged_in(page):
        context.storage_state(path=str(STORAGE_STATE))
        log("自然流数据平台登录状态有效")
        return

    page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    filled = fill_login_if_possible(page)
    if not filled:
        raise RuntimeError(
            "自然流数据平台登录态无效。请先运行: "
            "NATURAL_FLOW_USERNAME='你的用户名' NATURAL_FLOW_PASSWORD='你的密码' "
            "python3 -m opc_engine.features.data_attribution.login_natural_flow_assisted"
        )

    if not show_browser:
        log("当前为后台模式，但自然流数据平台登录需要验证码。请先运行辅助登录保存登录态。")
        raise RuntimeError("需要验证码/人工登录，后台模式无法继续。")

    deadline = datetime.now().timestamp() + 180
    while datetime.now().timestamp() < deadline:
        page.wait_for_timeout(2000)
        if is_logged_in(page):
            context.storage_state(path=str(STORAGE_STATE))
            log("自然流数据平台登录成功，状态已更新")
            return
    raise RuntimeError("等待自然流数据平台人工登录超时。")


def save_diagnostic(page, output_dir: Path, name: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / f"{timestamp()}_{name}"
    screenshot = prefix.with_suffix(".png")
    text_file = prefix.with_suffix(".txt")
    html_file = prefix.with_suffix(".html")
    try:
        page.screenshot(path=str(screenshot), full_page=True)
    except Exception:
        pass
    try:
        text_file.write_text(page.locator("body").inner_text(timeout=8000), encoding="utf-8")
    except Exception:
        pass
    try:
        html_file.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    return {
        "screenshot": str(screenshot),
        "text": str(text_file),
        "html": str(html_file),
    }


def click_text(page, text: str, exact: bool = True, timeout: int = 8000) -> None:
    locator = page.get_by_text(text, exact=exact).first
    locator.wait_for(state="visible", timeout=timeout)
    locator.click(timeout=timeout)


def visible_center_for_text_or_placeholder(page, phrase: str) -> dict | None:
    return page.evaluate(
        """(phrase) => {
            const isVisible = (el) => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== 'hidden' && s.display !== 'none'
                    && r.width > 0 && r.height > 0;
            };
            const nodes = Array.from(document.querySelectorAll('input,button,[role="button"],.ant-select,.el-select,div,span'));
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                const placeholder = el.getAttribute('placeholder') || '';
                const title = el.getAttribute('title') || '';
                const aria = el.getAttribute('aria-label') || '';
                if ([text, placeholder, title, aria].some((value) => value.includes(phrase))) {
                    const r = el.getBoundingClientRect();
                    return {x: r.left + r.width / 2, y: r.top + r.height / 2, text, placeholder, title, aria};
                }
            }
            return null;
        }""",
        phrase,
    )


def click_text_or_placeholder(page, phrase: str, timeout: int = 8000) -> bool:
    deadline = datetime.now().timestamp() + timeout / 1000
    while datetime.now().timestamp() < deadline:
        target = visible_center_for_text_or_placeholder(page, phrase)
        if target:
            page.mouse.click(target["x"], target["y"])
            return True
        page.wait_for_timeout(300)
    return False


def wait_for_video_management(page) -> None:
    try:
        page.wait_for_url(re.compile(r".*/data/mytAccountAweme.*"), timeout=12000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1200)
    text = page.locator("body").inner_text(timeout=10000)
    if "视频管理" not in text and "账号分组" not in text:
        raise RuntimeError("未能确认进入自然流数据管理页面。")


def open_video_management(page, target_url: str) -> None:
    log("进入自然流数据管理页面...")
    try:
        dashboard_url = derive_platform_url(target_url, "/dashboard") or target_url
        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        if is_login_page(page):
            raise RuntimeError("当前仍在登录页")
        click_text(page, "数据分析", exact=True, timeout=8000)
        page.wait_for_timeout(600)
        click_text(page, "视频管理", exact=True, timeout=8000)
        wait_for_video_management(page)
        log("已通过侧边栏进入自然流数据管理页")
        return
    except Exception as exc:
        log(f"侧边栏进入自然流数据管理页未成功，改用直达页面: {exc}")

    direct_url = target_url or VIDEO_MANAGEMENT_URL
    page.goto(direct_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_video_management(page)
    log("已进入自然流数据管理页面")


def choose_account_group(page, group_name: str) -> int | None:
    group_name = group_name.strip()
    if not group_name:
        raise RuntimeError("未配置账号分组。请先在数据归因页面填写目标账号分组，再运行下载。")

    log(f"选择账号分组: {group_name}")
    opened = click_text_or_placeholder(page, "请选择账号分组", timeout=8000)
    if not opened:
        raise RuntimeError("未找到账号分组下拉框。")
    page.wait_for_timeout(800)

    exact_pattern = re.compile(rf"^{re.escape(group_name)}(?:\(\d+\))?$")
    contains_pattern = re.compile(re.escape(group_name))
    option = page.get_by_text(exact_pattern).first
    option_text = ""
    try:
        option.wait_for(state="visible", timeout=5000)
        option_text = option.inner_text(timeout=3000).strip()
        option.click(timeout=5000)
    except Exception:
        option = page.get_by_text(contains_pattern).first
        option.wait_for(state="visible", timeout=5000)
        option_text = option.inner_text(timeout=3000).strip()
        option.click(timeout=5000)
    page.wait_for_timeout(1200)
    expected_count = None
    match = re.search(r"\((\d+)\)", option_text)
    if match:
        expected_count = int(match.group(1))
    log(f"账号分组已选择: {option_text or group_name}")
    return expected_count


def get_pagination_total(page) -> int | None:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return None
    matches = re.findall(r"共\s*(\d+)\s*条", text)
    return int(matches[-1]) if matches else None


def wait_for_loading_done(page) -> None:
    try:
        page.locator(".el-loading-mask:visible").first.wait_for(state="hidden", timeout=15000)
    except Exception:
        pass


def click_visible_button_by_text(page, text: str, timeout: int = 8000) -> bool:
    deadline = datetime.now().timestamp() + timeout / 1000
    while datetime.now().timestamp() < deadline:
        target = page.evaluate(
            """(text) => {
                const isVisible = (el) => {
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.visibility !== 'hidden' && s.display !== 'none'
                        && r.width > 0 && r.height > 0;
                };
                const buttons = Array.from(document.querySelectorAll('button,[role="button"]'));
                for (const el of buttons) {
                    if (!isVisible(el)) continue;
                    const label = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (label === text || label.includes(text)) {
                        const r = el.getBoundingClientRect();
                        return {x: r.left + r.width / 2, y: r.top + r.height / 2, label};
                    }
                }
                return null;
            }""",
            text,
        )
        if target:
            page.mouse.click(target["x"], target["y"])
            return True
        page.wait_for_timeout(300)
    return False


def click_search_if_available(page) -> None:
    before_total = get_pagination_total(page)
    try:
        clicked = click_visible_button_by_text(page, "搜索", timeout=6000)
        if not clicked:
            raise RuntimeError("未找到可见的搜索按钮")
        wait_for_loading_done(page)
        page.wait_for_timeout(3000)
        after_total = get_pagination_total(page)
        log(f"已点击搜索，等待分组数据刷新: {before_total or '未知'} -> {after_total or '未知'}")
    except Exception as exc:
        raise RuntimeError(f"选择账号分组后必须点击搜索，但搜索动作未能完成: {exc}") from exc


def find_export_candidates(page, pattern: str) -> list[dict]:
    return page.evaluate(
        """(pattern) => {
            const re = new RegExp(pattern, 'i');
            const isVisible = (el) => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.visibility !== 'hidden' && s.display !== 'none'
                    && r.width > 0 && r.height > 0;
            };
            return Array.from(document.querySelectorAll('button,[role="button"],a,span,div'))
                .filter(isVisible)
                .map((el, index) => {
                    const r = el.getBoundingClientRect();
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    const label = [text, el.title || '', el.getAttribute('aria-label') || ''].join(' ');
                    const exactExport = /^(导出|Export)$/i.test(text);
                    const bulkExport = /导出选中/.test(text);
                    return { index, text, title: el.title || '', aria: el.getAttribute('aria-label') || '', x: r.left + r.width / 2, y: r.top + r.height / 2, exactExport, bulkExport };
                })
                .filter((item) => re.test([item.text, item.title, item.aria].join(' ')))
                .sort((a, b) => Number(b.exactExport) - Number(a.exactExport) || Number(a.bulkExport) - Number(b.bulkExport))
                .slice(0, 30);
        }""",
        pattern,
    )


def get_export_confirm_count(page) -> int | None:
    try:
        message = page.locator(".el-message-box__message").first.inner_text(timeout=3000)
    except Exception:
        return None
    match = re.search(r"导出\s*(\d+)\s*条", message)
    return int(match.group(1)) if match else None


def cancel_export_confirm(page) -> None:
    for label in ["取消", "Close"]:
        try:
            button = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$")).first
            button.wait_for(state="visible", timeout=2000)
            button.click(timeout=2000)
            return
        except Exception:
            pass


def click_export_confirm_if_visible(page) -> bool:
    try:
        page.get_by_text("导出确认", exact=True).first.wait_for(state="visible", timeout=5000)
    except Exception:
        return False

    for label in ["确认导出", "确定", "确认"]:
        try:
            button = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$")).first
            button.wait_for(state="visible", timeout=3000)
            button.click(timeout=3000)
            log(f"已点击二次确认按钮: {label}")
            return True
        except Exception:
            pass

    try:
        button = page.get_by_text("确认导出", exact=True).first
        button.wait_for(state="visible", timeout=3000)
        button.click(timeout=3000)
        log("已点击二次确认按钮: 确认导出")
        return True
    except Exception:
        return False


def try_download_export(page, output_dir: Path, pattern: str) -> list[str]:
    candidates = find_export_candidates(page, pattern)
    if not candidates:
        log("未发现导出/下载按钮，已先保存页面诊断信息。")
        return []

    log(f"发现 {len(candidates)} 个导出/下载候选按钮，优先点击“导出”。")
    first = candidates[0]
    try:
        with page.expect_download(timeout=30000) as info:
            page.mouse.click(first["x"], first["y"])
            page.wait_for_timeout(800)
            click_export_confirm_if_visible(page)
        download = info.value
        suggested = download.suggested_filename or f"natural_flow_{timestamp()}.xlsx"
        target = output_dir / suggested
        if target.exists():
            target = output_dir / f"{target.stem}_{timestamp()}{target.suffix}"
        download.save_as(str(target))
        log(f"自然流数据文件已下载: {target}")
        return [str(target)]
    except PlaywrightTimeoutError:
        log("点击候选按钮后未触发浏览器下载，后续需要继续适配自然流数据页面。")
        return []


def main() -> None:
    config = load_config()
    require_product_project(config, "下载自然流数据")
    global STORAGE_STATE
    STORAGE_STATE = runtime_state_path("natural-flow-state.json", config)
    show_browser = bool(
        config.get("show_browser", False)
        or os.environ.get("NATURAL_FLOW_SHOW_BROWSER") == "1"
    )
    target_url = natural_flow_management_url(config)
    if not target_url:
        raise SystemExit("请先在本地配置自然流数据管理页地址 natural_flow_management_url")
    login_url = natural_flow_login_url(config, target_url)
    if not login_url:
        raise SystemExit("请先在本地配置自然流登录地址 natural_flow_login_url")
    export_text_re = (
        os.environ.get("NATURAL_FLOW_EXPORT_TEXT_RE")
        or config.get("natural_flow_export_button_text_re")
        or DEFAULT_EXPORT_TEXT_RE
    )
    account_group = (
        os.environ.get("NATURAL_FLOW_ACCOUNT_GROUP")
        or os.environ.get("NATURAL_DATA_ACCOUNT_GROUP")
        or config.get("natural_flow_account_group")
        or ""
    ).strip()
    output_dir = resolve_path(
        os.environ.get("DATA_ATTRIBUTION_OUTPUT_DIR"),
        raw_data_dir("natural_flow", config),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)

    log("开始下载自然流数据")
    log(f"使用独立自动化浏览器资料目录: {PROFILE_DIR}")
    log("不会读取或复用你的常用 Chrome 浏览器资料。")
    log("自然流数据管理页: 已配置")
    log(f"账号分组: {account_group or '未配置'}")
    log(f"输出目录: {output_dir}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        add_saved_cookies(context)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000)
        try:
            ensure_logged_in(page, context, target_url, login_url, show_browser)
            minimize_browser_windows(show_browser)
            open_video_management(page, target_url)
            group_account_count = choose_account_group(page, account_group)
            click_search_if_available(page)
            downloaded = try_download_export(page, output_dir, export_text_re)
            diagnostic = save_diagnostic(page, output_dir, "natural_flow_probe")
            payload = {
                "stage": "natural_flow_download",
                "target_url": target_url,
                "account_group": account_group,
                "group_account_count": group_account_count,
                "output_dir": str(output_dir),
                "downloaded_files": downloaded,
                "diagnostic": diagnostic,
                "note": "脚本会进入自然流数据管理页，按账号分组筛选并点击导出；如果没有触发下载，会保留页面诊断用于继续适配。",
            }
            result_path = output_dir / f"{timestamp()}_natural_flow_download.json"
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"自然流下载结果记录: {result_path}")
            context.storage_state(path=str(STORAGE_STATE))
        finally:
            context.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n用户中断。")
        sys.exit(1)
