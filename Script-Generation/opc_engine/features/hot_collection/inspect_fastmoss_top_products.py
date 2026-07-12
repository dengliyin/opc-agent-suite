#!/usr/bin/env python3
import subprocess
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import require_product_project, runtime_state_path


ROOT = Path(__file__).resolve().parents[3]
SEARCH_URL = "https://www.fastmoss.com/zh/e-commerce/search"


def load_config():
    defaults = {
        "keyword": "",
        "country": "马来西亚",
        "category_path": ["美妆个护", "头部护理与造型", "染发用品"],
    }
    return load_app_config(defaults)


CONFIG = load_config()
require_product_project(CONFIG, "检查采集结果")
STORAGE_STATE = runtime_state_path("fastmoss-state.json", CONFIG)
KEYWORD = CONFIG["keyword"]
COUNTRY = CONFIG["country"]
CATEGORY_PATH = CONFIG["category_path"]
SHOW_BROWSER = bool(CONFIG.get("show_browser", False))


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
    except Exception:
        pass


def close_entry_popup(page):
    page.wait_for_timeout(1200)
    for selector in [
        ".fixed.inset-0 button",
        ".fixed.inset-0 [role='button']",
        ".fixed.inset-0 svg",
        ".fixed.inset-0 img",
    ]:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                locator.first.click(timeout=1200)
                page.wait_for_timeout(700)
                return
        except Exception:
            pass


def click_text(page, text, exact=True, timeout=10000):
    locator = page.get_by_text(text, exact=exact)
    locator.first.wait_for(state="visible", timeout=timeout)
    locator.first.click()


def point_to_visible_text(page, text, min_x=None, max_x=None, timeout=10000):
    locator = page.get_by_text(text, exact=True)
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        candidates = []
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                box = item.bounding_box()
                if not box:
                    continue
                center_x = box["x"] + box["width"] / 2
                center_y = box["y"] + box["height"] / 2
                if center_y < 0 or center_y > viewport["height"]:
                    continue
                if min_x is not None and center_x < min_x:
                    continue
                if max_x is not None and center_x > max_x:
                    continue
                candidates.append((center_y, center_x, box))
            except Exception:
                continue
        if candidates:
            _, _, box = sorted(candidates)[0]
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.wait_for_timeout(250)
    raise RuntimeError(f"未找到可点击的可见文本: {text}")


def select_category_path(page):
    click_text(page, CATEGORY_PATH[0])
    page.wait_for_timeout(900)

    second_x, second_y = point_to_visible_text(page, CATEGORY_PATH[1], min_x=450, max_x=650)
    page.mouse.move(second_x, second_y)
    page.wait_for_timeout(900)

    third_x, third_y = point_to_visible_text(page, CATEGORY_PATH[2], min_x=600)
    page.mouse.click(third_x, third_y)
    page.wait_for_timeout(2500)

    selected_text = page.locator("body").inner_text(timeout=5000)
    selected_category = " - ".join(CATEGORY_PATH)
    if selected_category not in selected_text and "l3_cid=" not in page.url:
        raise RuntimeError(f"未确认第三级类目已选中: {CATEGORY_PATH[2]}")


def wait_for_products(page):
    detail_links = page.locator("a[href*='/zh/e-commerce/detail/'], a[href*='/e-commerce/detail/']")
    try:
        detail_links.first.wait_for(state="attached", timeout=20000)
    except PlaywrightTimeoutError:
        page.wait_for_timeout(5000)


def collect_top3(page):
    rows = page.locator("tr")
    products = []

    for i in range(rows.count()):
        row = rows.nth(i)
        links = row.locator("a[href*='/e-commerce/detail/']")
        if links.count() == 0:
            continue
        href = links.first.get_attribute("href")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.fastmoss.com" + href
        text = " ".join(row.inner_text(timeout=2000).split())
        name = text[:160]
        if href not in {item["product_url"] for item in products}:
            products.append({"rank": len(products) + 1, "name": name, "product_url": href})
        if len(products) >= 3:
            return products

    anchors = page.locator("a[href*='/e-commerce/detail/']")
    for i in range(anchors.count()):
        link = anchors.nth(i)
        href = link.get_attribute("href")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.fastmoss.com" + href
        name = " ".join(link.inner_text(timeout=2000).split())
        if href not in {item["product_url"] for item in products}:
            products.append({"rank": len(products) + 1, "name": name, "product_url": href})
        if len(products) >= 3:
            return products

    return products


def main():
    if not STORAGE_STATE.exists():
        raise SystemExit(f"找不到登录态文件: {STORAGE_STATE}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=450,
            args=[
                "--disable-blink-features=AutomationControlled",
                *(["--start-minimized", "--window-size=1440,900"] if not SHOW_BROWSER else []),
            ],
        )
        minimize_browser_windows()
        context = browser.new_context(
            storage_state=str(STORAGE_STATE),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        close_entry_popup(page)

        search_input = page.get_by_placeholder("商品搜索")
        search_input.wait_for(state="visible", timeout=15000)
        search_input.fill(KEYWORD)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1800)

        click_text(page, COUNTRY)
        page.wait_for_timeout(1200)

        select_category_path(page)

        wait_for_products(page)
        page.wait_for_timeout(2500)

        products = collect_top3(page)
        for item in products:
            print(f"{item['rank']}. {item['name']}")
            print(f"   {item['product_url']}")

        try:
            input("已读取前三商品链接。浏览器保持打开，按回车退出...")
        except EOFError:
            pass
        context.storage_state(path=str(STORAGE_STATE))
        browser.close()


if __name__ == "__main__":
    main()
