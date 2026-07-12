#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from opc_engine.core.project_assets import load_config, require_product_project, runtime_state_path


ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = ROOT / "browser-profile" / "natural-flow"
CONFIG = load_config()
require_product_project(CONFIG, "刷新自然流登录状态")
STORAGE_STATE = runtime_state_path("natural-flow-state.json", CONFIG)


def derive_platform_url(management_url: str, path: str) -> str:
    parsed = urlparse(str(management_url or ""))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def management_url() -> str:
    return (
        os.environ.get("NATURAL_FLOW_MANAGEMENT_URL")
        or str(CONFIG.get("natural_flow_management_url") or "")
    ).strip()


def login_url(management: str) -> str:
    return (
        os.environ.get("NATURAL_FLOW_LOGIN_URL")
        or str(CONFIG.get("natural_flow_login_url") or "")
        or derive_platform_url(management, "/login?redirect=%2Fdashboard")
    ).strip()


def log(message: str) -> None:
    print(message, flush=True)


def visible(locator, timeout: int = 1000) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False


def is_login_page(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return "用户名/手机号" in text and "密码" in text and "验证码" in text


def is_logged_in(page) -> bool:
    try:
        if "/login" in page.url:
            return False
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    if "用户名/手机号" in text and "验证码" in text:
        return False
    return any(marker in text for marker in ["退出", "账号", "工作台", "Dashboard", "dashboard"])


def fill_login_form(page, username: str, password: str) -> None:
    username_input = page.get_by_placeholder("用户名/手机号")
    username_input.wait_for(state="visible", timeout=15000)
    username_input.fill(username)

    password_input = page.get_by_placeholder("密码")
    password_input.wait_for(state="visible", timeout=15000)
    password_input.fill(password)


def main() -> None:
    username = os.environ.get("NATURAL_FLOW_USERNAME")
    password = os.environ.get("NATURAL_FLOW_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "请先设置 NATURAL_FLOW_USERNAME 和 NATURAL_FLOW_PASSWORD 环境变量，"
            "例如: NATURAL_FLOW_USERNAME='xxx' NATURAL_FLOW_PASSWORD='xxx' "
            "python3 -m opc_engine.features.data_attribution.login_natural_flow_assisted"
        )
    dashboard_url = management_url()
    if not dashboard_url:
        raise SystemExit("请先在本地配置自然流数据管理页地址 natural_flow_management_url")
    target_login_url = login_url(dashboard_url)
    if not target_login_url:
        raise SystemExit("请先在本地配置自然流登录地址 natural_flow_login_url")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)
    log(f"使用独立自动化浏览器资料目录: {PROFILE_DIR}")
    log("不会读取或复用你的常用 Chrome 浏览器资料。")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000)

        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        if is_logged_in(page):
            context.storage_state(path=str(STORAGE_STATE))
            log(f"已检测到自然流数据登录态，保存到: {STORAGE_STATE}")
            input("浏览器会保持打开。确认无误后按回车退出...")
            context.close()
            return

        page.goto(target_login_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        fill_login_form(page, username, password)

        log("=" * 72)
        log("已自动填写自然流数据平台用户名和密码。")
        log("请在可见浏览器里手动输入验证码，并点击「登 录」。")
        log("登录成功进入后台后，回到终端按 Enter 保存登录状态。")
        log("=" * 72)
        input(">>> 完成登录后按 Enter 保存状态...")

        deadline = time.time() + 20
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if is_logged_in(page):
                break

        context.storage_state(path=str(STORAGE_STATE))
        log(f"自然流数据登录状态已保存到: {STORAGE_STATE}")
        context.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n用户中断。")
        sys.exit(1)
