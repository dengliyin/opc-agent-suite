#!/usr/bin/env python3
import os
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from opc_engine.core.project_assets import load_config, require_product_project, runtime_state_path


ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = ROOT / "browser-profile" / "fastmoss"
CONFIG = load_config()
require_product_project(CONFIG, "刷新登录状态")
STORAGE_STATE = runtime_state_path("fastmoss-state.json", CONFIG)
LOGIN_URL = "https://www.fastmoss.com/zh/dashboard"


def click_unique(page, text, timeout=8000):
    locator = page.get_by_text(text, exact=True)
    locator.wait_for(state="visible", timeout=timeout)
    locator.click()


def try_click(page, text, exact=True, timeout=4000):
    try:
        locator = page.get_by_text(text, exact=exact)
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.click()
        return True
    except PlaywrightTimeoutError:
        return False


def is_logged_in(page):
    header = page.locator("header, .header, body")
    text = header.inner_text(timeout=5000)
    return "登录/注册" not in text and ("FM" in text or "专业版" in text or "账号中心" in text)


def visible_count(locator, timeout=1000):
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return locator.count()
    except PlaywrightTimeoutError:
        return 0


def close_entry_popup(page):
    selectors = [
        ".fixed.inset-0 button",
        ".fixed.inset-0 [role='button']",
        ".fixed.inset-0 svg",
        ".fixed.inset-0 img",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                locator.first.click(timeout=1500)
                page.wait_for_timeout(600)
                return True
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def main():
    phone = os.environ.get("FASTMOSS_PHONE")
    password = os.environ.get("FASTMOSS_PASSWORD")
    if not phone or not password:
        raise SystemExit("请先设置 FASTMOSS_PHONE 和 FASTMOSS_PASSWORD 环境变量")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=350,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
        close_entry_popup(page)

        if is_logged_in(page):
            context.storage_state(path=str(STORAGE_STATE))
            print(f"已检测到登录态，保存到: {STORAGE_STATE}")
            input("浏览器会保持打开。确认无误后按回车退出...")
            context.close()
            return

        phone_input = page.get_by_placeholder("输入您的手机号")
        if visible_count(phone_input) == 0:
            click_unique(page, "登录/注册")
            page.wait_for_timeout(1000)

        try_click(page, "手机号登录/注册")
        page.wait_for_timeout(700)

        if try_click(page, "密码登录", exact=True):
            page.wait_for_timeout(700)

        phone_input = page.get_by_placeholder("输入您的手机号")
        phone_input.wait_for(state="visible", timeout=10000)
        phone_input.fill(phone)

        password_input = page.get_by_placeholder("输入密码")
        password_input.wait_for(state="visible", timeout=10000)
        password_input.fill(password)

        click_unique(page, "注册/登录")
        print("已提交手机号密码。若出现验证码、滑块或短信验证，请在可见浏览器里手动完成。")

        deadline = time.time() + 180
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            try:
                if is_logged_in(page):
                    context.storage_state(path=str(STORAGE_STATE))
                    print(f"登录成功，状态已保存到: {STORAGE_STATE}")
                    input("浏览器会保持打开。确认无误后按回车退出...")
                    context.close()
                    return
            except Exception:
                pass

        context.storage_state(path=str(STORAGE_STATE))
        print(f"未能自动确认登录成功，但已保存当前浏览器状态到: {STORAGE_STATE}")
        input("请检查浏览器当前状态。按回车退出...")
        context.close()


if __name__ == "__main__":
    main()
