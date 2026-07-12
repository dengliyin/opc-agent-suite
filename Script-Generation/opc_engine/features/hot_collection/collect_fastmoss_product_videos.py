#!/usr/bin/env python3
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import collection_csv_path, diagnostics_dir, ensure_project_dirs, require_product_project, runtime_state_path


ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE_DIR = ROOT / "browser-profile" / "fastmoss"
LOGIN_URL = "https://www.fastmoss.com/zh/dashboard"
SEARCH_URL = "https://www.fastmoss.com/zh/e-commerce/search"


def safe_profile_part(value):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "").strip()).strip("_") or "default"


def load_config():
    defaults = {
        "phone": os.environ.get("FASTMOSS_PHONE", ""),
        "password": os.environ.get("FASTMOSS_PASSWORD", ""),
        "keyword": "",
        "country": "马来西亚",
        "category_path": ["美妆个护", "头部护理与造型", "染发用品"],
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
        "videos_per_product": 20,
    }
    return load_app_config(defaults)


CONFIG = load_config()
require_product_project(CONFIG, "进行爆款采集")
PROJECT_ROOT = ensure_project_dirs(CONFIG)
STORAGE_STATE = runtime_state_path("fastmoss-state.json", CONFIG)
LOGIN_META = runtime_state_path("fastmoss-login-meta.json", CONFIG)
DIAGNOSTIC_DIR = diagnostics_dir(CONFIG)
KEYWORD = str(CONFIG.get("keyword", "") or "").strip()
CONFIG_PHONE = str(CONFIG.get("phone", "") or "").strip()
COUNTRY = CONFIG["country"]
CATEGORY_PATH = CONFIG["category_path"]
CATEGORY = " > ".join(CATEGORY_PATH)
CATEGORY_FILENAME = "-".join(CATEGORY_PATH)
SHOP_TYPE = str(CONFIG.get("shop_type") or "全部").strip()
PRODUCT_TYPES = CONFIG.get("product_types") or []
if isinstance(PRODUCT_TYPES, str):
    PRODUCT_TYPES = [part.strip() for part in PRODUCT_TYPES.split(",") if part.strip()]
PRODUCT_STATUS = str(CONFIG.get("product_status") or "在售").strip()
SEARCH_FILTERS = {
    "达人出单率": str(CONFIG.get("creator_conversion_rate_filter") or "全部").strip(),
    "总销量": str(CONFIG.get("total_sales_filter") or "全部").strip(),
    "总GMV": str(CONFIG.get("total_gmv_filter") or "全部").strip(),
    "近7天销量": str(CONFIG.get("sales_7d_filter") or "全部").strip(),
    "近7天GMV": str(CONFIG.get("gmv_7d_filter") or "全部").strip(),
    "带货达人数": str(CONFIG.get("creator_count_filter") or "全部").strip(),
    "佣金比例": str(CONFIG.get("commission_rate_filter") or "全部").strip(),
    "带货方式": str(CONFIG.get("shipping_method_filter") or "全部").strip(),
}
PRODUCT_LIMIT = int(CONFIG.get("product_limit", 3))
VIDEOS_PER_PRODUCT = int(CONFIG.get("videos_per_product", 20))
SHOW_BROWSER = bool(CONFIG.get("show_browser", False))
PROFILE_DIR = BASE_PROFILE_DIR / safe_profile_part(CONFIG_PHONE)
if CONFIG.get("phone"):
    os.environ.setdefault("FASTMOSS_PHONE", CONFIG["phone"])
if CONFIG.get("password"):
    os.environ.setdefault("FASTMOSS_PASSWORD", CONFIG["password"])


def log(message):
    print(message, flush=True)


def account_signature():
    phone = str(CONFIG.get("phone", "") or "").strip()
    password = str(CONFIG.get("password", "") or "")
    password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest() if password else ""
    return {"phone": phone, "password_sha256": password_sha256}


def read_login_meta():
    if not LOGIN_META.exists():
        return {}
    try:
        return json.loads(LOGIN_META.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_login_meta():
    LOGIN_META.parent.mkdir(parents=True, exist_ok=True)
    payload = account_signature() | {
        "profile_dir": str(PROFILE_DIR),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    LOGIN_META.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_account_profile():
    signature = account_signature()
    if not signature["phone"]:
        return
    previous = read_login_meta()
    account_changed = (
        previous.get("phone") != signature["phone"]
        or previous.get("password_sha256") != signature["password_sha256"]
    )
    if not account_changed:
        return
    log("检测到 FastMoss 账号或密码已更新，清理旧登录状态并重新登录")
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    if STORAGE_STATE.exists():
        try:
            STORAGE_STATE.unlink()
        except OSError:
            pass


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


def safe_filename_part(value):
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def build_output_csv(rows, product_count):
    today = datetime.now().strftime("%Y%m%d")
    video_url_count = sum(1 for row in rows if row.get("tiktok_video_url"))
    keyword_part = safe_filename_part(KEYWORD) or "无关键词"
    filename = "_".join(
        [
            keyword_part,
            safe_filename_part(COUNTRY),
            safe_filename_part(CATEGORY_FILENAME),
            today,
            str(product_count),
            str(video_url_count),
        ]
    )
    return collection_csv_path(filename, CONFIG)


def close_entry_popup(page):
    page.wait_for_timeout(1000)
    for selector in [
        "[aria-label='Close']",
        "[aria-label='close']",
        ".ant-modal-close",
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


def visible_count(locator, timeout=1000):
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        return locator.count()
    except PlaywrightTimeoutError:
        return 0


def try_click(page, text, exact=True, timeout=4000):
    try:
        locator = page.get_by_text(text, exact=exact)
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.click()
        return True
    except PlaywrightTimeoutError:
        return False


def is_logged_in(page):
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    if re.search(r"\bFM\d+\b", text):
        return True
    if "专业版" in text and "购买续费" in text:
        return True
    if "输入您的手机号" in text or "输入密码" in text:
        return False
    if "登录/注册" in text:
        return False
    return False


def save_login_diagnostic(page, reason):
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
    screenshot = DIAGNOSTIC_DIR / "login_diagnostic.png"
    text_file = DIAGNOSTIC_DIR / "login_diagnostic.txt"
    try:
        page.screenshot(path=str(screenshot), full_page=False)
    except Exception:
        pass
    try:
        text_file.write_text(page.locator("body").inner_text(timeout=5000), encoding="utf-8")
    except Exception:
        pass
    log(f"登录诊断: {reason}")
    log(f"诊断截图: {screenshot}")
    log(f"诊断文本: {text_file}")


def ensure_logged_in(page, context):
    log("检查程序登录状态...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1600)
    close_entry_popup(page)
    if is_logged_in(page):
        log("登录状态有效")
        context.storage_state(path=str(STORAGE_STATE))
        write_login_meta()
        return

    page_text = page.locator("body").inner_text(timeout=5000)
    if "Restricted Access" in page_text or "security policy" in page_text:
        raise RuntimeError("页面访问被安全策略拦截。请勾选“显示浏览器窗口”完成一次验证后再试。")

    phone = os.environ.get("FASTMOSS_PHONE")
    password = os.environ.get("FASTMOSS_PASSWORD")
    if not phone or not password:
        raise RuntimeError("登录态已失效，请设置 FASTMOSS_PHONE 和 FASTMOSS_PASSWORD 后重跑")

    phone_input = page.get_by_placeholder("输入您的手机号")
    if visible_count(phone_input) == 0:
        if visible_count(page.get_by_text("登录/注册", exact=True)) == 0:
            save_login_diagnostic(page, "未检测到已登录账号，也没有找到登录/注册入口")
            raise RuntimeError("未找到登录入口。请勾选「显示浏览器窗口」运行一次，确认页面状态或手动完成登录。")
        click_text(page, "登录/注册")
        page.wait_for_timeout(900)

    try_click(page, "手机号登录/注册")
    page.wait_for_timeout(600)
    try_click(page, "密码登录", exact=True)
    page.wait_for_timeout(600)

    phone_input = page.get_by_placeholder("输入您的手机号")
    phone_input.wait_for(state="visible", timeout=10000)
    phone_input.fill(phone)

    password_input = page.get_by_placeholder("输入密码")
    password_input.wait_for(state="visible", timeout=10000)
    password_input.fill(password)

    click_text(page, "注册/登录")
    log("登录态失效，已自动提交手机号密码。若出现验证码、滑块或短信验证，请在可见浏览器里手动完成。")

    deadline = time.time() + 180
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        close_entry_popup(page)
        if is_logged_in(page):
            context.storage_state(path=str(STORAGE_STATE))
            write_login_meta()
            log("登录成功，状态已更新。")
            return

    context.storage_state(path=str(STORAGE_STATE))
    raise RuntimeError("未能确认登录成功；如果页面停在验证码/滑块，请手动完成后重跑")


def click_text(page, text, exact=True, timeout=12000):
    locator = page.get_by_text(text, exact=exact)
    locator.first.wait_for(state="visible", timeout=timeout)
    locator.first.click()


def try_click_text(page, text, exact=True, timeout=2500):
    try:
        click_text(page, text, exact=exact, timeout=timeout)
        return True
    except Exception:
        return False


def try_click_pattern(page, pattern, timeout=2500):
    try:
        locator = page.get_by_text(re.compile(pattern))
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.click()
        return True
    except Exception:
        return False


def open_filter_dropdown(page, label):
    button = page.get_by_role("button", name=re.compile(rf"{re.escape(label)}[：:]", re.I))
    if button.count() > 0:
        button.first.click(timeout=2500)
        return True

    item = page.locator(".ant-space-item", has_text=re.compile(rf"{re.escape(label)}[：:]"))
    if item.count() > 0:
        item.first.click(timeout=2500)
        return True

    label_locator = page.get_by_text(label, exact=False)
    label_locator.first.wait_for(state="visible", timeout=2500)
    box = label_locator.first.bounding_box()
    if box:
        page.mouse.click(box["x"] + box["width"] + 90, box["y"] + box["height"] / 2)
        return True
    label_locator.first.click(timeout=1500)
    return True


def select_optional_filter_value(page, label, value):
    value = str(value or "全部").strip()
    if not value or value == "全部":
        return
    log(f"设置筛选条件: {label} = {value}")
    try:
        open_filter_dropdown(page, label)
        page.wait_for_timeout(500)
        if (
            try_click_text(page, value, exact=True, timeout=2500)
            or try_click_text(page, f"{label}：{value}", exact=True, timeout=2500)
            or try_click_pattern(page, rf"{re.escape(label)}[：:]\s*{re.escape(value)}", timeout=2500)
        ):
            page.wait_for_timeout(400)
            try_click_pattern(page, r"确\s*认", timeout=1200)
            page.wait_for_timeout(700)
            return
    except Exception:
        pass
    log(f"未能自动设置筛选条件，已跳过: {label} = {value}")


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


def normalize_fastmoss_url(href):
    if not href:
        return None
    if href.startswith("/"):
        return "https://www.fastmoss.com" + href
    return href


def visible_category_menus(page):
    return page.locator("ul.ant-cascader-menu").evaluate_all(
        """
        (menus) => menus.flatMap((menu, index) => {
          const rect = menu.getBoundingClientRect();
          const style = getComputedStyle(menu);
          const text = (menu.innerText || "").trim();
          if (!text || style.display === "none" || style.visibility === "hidden") return [];
          if (rect.width < 20 || rect.height < 20) return [];
          return [{index, left: rect.left, top: rect.top, right: rect.right, text}];
        })
        """
    )


def hover_cascader_item(page, menu_index, title):
    point = page.locator("ul.ant-cascader-menu").nth(menu_index).evaluate(
        """
        (menu, title) => {
          const item = [...menu.querySelectorAll("li[title]")].find((node) => node.getAttribute("title") === title);
          if (!item) throw new Error(`menu item not found: ${title}`);
          item.scrollIntoView({block: "center", inline: "nearest"});
          const rect = item.getBoundingClientRect();
          return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
        }
        """,
        title,
    )
    page.mouse.move(point["x"], point["y"])
    page.wait_for_timeout(350)
    return point


def click_cascader_item(page, menu_index, title):
    point = hover_cascader_item(page, menu_index, title)
    page.mouse.click(point["x"], point["y"])
    page.wait_for_timeout(1500)


def expand_category_area(page):
    try:
        expand_button = page.get_by_text("展开", exact=True).first
        if expand_button.is_visible(timeout=1200):
            expand_button.click(timeout=1200)
            page.wait_for_timeout(600)
    except Exception:
        pass


def select_category_path(page):
    if not CATEGORY_PATH or CATEGORY_PATH[0] == "全部":
        log("商品分类: 全部")
        return

    expand_category_area(page)
    log(f"定位一级类目: {CATEGORY_PATH[0]}")
    first_x, first_y = point_to_visible_text(page, CATEGORY_PATH[0], min_x=390)
    page.mouse.move(first_x, first_y)
    page.wait_for_timeout(900)

    if len(CATEGORY_PATH) == 1:
        page.mouse.click(first_x, first_y)
        page.wait_for_timeout(1500)
        log(f"已选择一级类目: {CATEGORY_PATH[0]}")
        return

    menus = visible_category_menus(page)
    if not menus:
        raise RuntimeError(f"未展开二级类目菜单: {CATEGORY_PATH[0]}")
    first_menu = sorted(menus, key=lambda item: abs(item["left"] - first_x))[0]

    log(f"展开二级类目: {CATEGORY_PATH[1]}")
    hover_cascader_item(page, first_menu["index"], CATEGORY_PATH[1])

    if len(CATEGORY_PATH) == 2:
        click_cascader_item(page, first_menu["index"], CATEGORY_PATH[1])
        log(f"已选择二级类目: {' - '.join(CATEGORY_PATH)}")
        return

    menus_after_second = visible_category_menus(page)
    third_candidates = [
        menu
        for menu in menus_after_second
        if menu["left"] >= first_menu["right"] - 2 and menu["text"] != first_menu["text"]
    ]
    if not third_candidates:
        raise RuntimeError(f"未展开三级类目菜单: {CATEGORY_PATH[1]}")
    third_menu = sorted(third_candidates, key=lambda item: item["left"])[0]

    log(f"点击三级类目: {CATEGORY_PATH[2]}")
    click_cascader_item(page, third_menu["index"], CATEGORY_PATH[2])

    selected_text = page.locator("body").inner_text(timeout=5000)
    selected_category = " - ".join(CATEGORY_PATH)
    if selected_category not in selected_text and "l3_cid=" not in page.url:
        raise RuntimeError(f"未确认第三级类目已选中: {CATEGORY_PATH[2]}")
    log(f"已确认类目: {selected_category}")


def apply_search_filters(page):
    if SHOP_TYPE and SHOP_TYPE != "全部":
        log(f"选择店铺类型: {SHOP_TYPE}")
        if not try_click_text(page, SHOP_TYPE, exact=True, timeout=3000):
            log(f"未找到店铺类型选项，已跳过: {SHOP_TYPE}")

    for product_type in PRODUCT_TYPES:
        if product_type and product_type != "全部":
            log(f"选择商品类型: {product_type}")
            if not try_click_text(page, product_type, exact=True, timeout=3000):
                log(f"未找到商品类型选项，已跳过: {product_type}")

    if PRODUCT_STATUS and PRODUCT_STATUS not in {"全部", "在售"}:
        log(f"选择商品状态: {PRODUCT_STATUS}")
        if not try_click_text(page, PRODUCT_STATUS, exact=True, timeout=3000):
            log(f"未找到商品状态选项，已跳过: {PRODUCT_STATUS}")

    for label, value in SEARCH_FILTERS.items():
        select_optional_filter_value(page, label, value)


def wait_for_products(page):
    detail_links = page.locator("a[href*='/zh/e-commerce/detail/'], a[href*='/e-commerce/detail/']")
    try:
        detail_links.first.wait_for(state="attached", timeout=20000)
    except PlaywrightTimeoutError:
        page.wait_for_timeout(5000)


def collect_top_products(page, limit=PRODUCT_LIMIT):
    rows = page.locator("tr")
    products = []

    for i in range(rows.count()):
        row = rows.nth(i)
        links = row.locator("a[href*='/e-commerce/detail/']")
        if links.count() == 0:
            continue
        href = normalize_fastmoss_url(links.first.get_attribute("href"))
        if not href:
            continue
        text = " ".join(row.inner_text(timeout=2000).split())
        if href not in {item["url"] for item in products}:
            products.append({"rank": len(products) + 1, "name": text[:160], "url": href})
        if len(products) >= limit:
            return products

    anchors = page.locator("a[href*='/e-commerce/detail/']")
    for i in range(anchors.count()):
        link = anchors.nth(i)
        href = normalize_fastmoss_url(link.get_attribute("href"))
        if not href:
            continue
        name = " ".join(link.inner_text(timeout=2000).split())
        if href not in {item["url"] for item in products}:
            products.append({"rank": len(products) + 1, "name": name[:160], "url": href})
        if len(products) >= limit:
            return products

    return products


def search_products(page, context):
    log("打开商品搜索页...")
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    close_entry_popup(page)
    if not is_logged_in(page):
        ensure_logged_in(page, context)
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        close_entry_popup(page)

    search_input = page.get_by_placeholder("商品搜索")
    search_input.wait_for(state="visible", timeout=15000)
    if KEYWORD:
        log(f"输入关键词: {KEYWORD}")
        search_input.fill(KEYWORD)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1800)
    else:
        log("关键词为空，跳过关键词搜索，仅按国家/地区、商品分类和筛选条件采集")

    if COUNTRY and COUNTRY != "全部":
        log(f"选择国家/地区: {COUNTRY}")
        click_text(page, COUNTRY)
        page.wait_for_timeout(1200)
    else:
        log("国家/地区: 全部")

    select_category_path(page)
    apply_search_filters(page)
    wait_for_products(page)
    page.wait_for_timeout(2500)

    products = collect_top_products(page, limit=PRODUCT_LIMIT)
    if not products:
        raise RuntimeError("没有找到商品结果，请检查国家/地区、商品分类或筛选条件")
    log(f"已获取商品链接: {len(products)} 个")
    return products


def open_related_videos(page, product_url):
    log(f"打开商品详情页: {product_url}")
    page.goto(product_url, wait_until="domcontentloaded")
    close_entry_popup(page)
    if not is_logged_in(page):
        raise RuntimeError("打开商品页时检测到登录态失效")
    related_anchor = page.locator("a[href='#related_videos']")
    if related_anchor.count() > 0:
        related_anchor.first.click()
    else:
        click_text(page, "商品关联视频")
    log("进入商品关联视频")
    page.wait_for_timeout(2200)
    page.locator("#related_videos").scroll_into_view_if_needed(timeout=10000)
    page.wait_for_timeout(1200)

    try:
        section = page.locator("#related_videos")
        section.get_by_text("近28天", exact=True).first.click(timeout=5000)
        log("已选择近28天")
        page.wait_for_timeout(1500)
    except PlaywrightTimeoutError:
        pass


def parse_video_page(page):
    return page.eval_on_selector_all(
        "#related_videos tr",
        """
        (rows) => rows.flatMap((row) => {
          const cells = [...row.querySelectorAll('td')];
          if (cells.length < 10) return [];
          const videoLink = cells[0].querySelector("a[href*='/media-source/video/']");
          if (!videoLink) return [];

          const lines = videoLink.innerText.split('\\n').map((x) => x.trim()).filter(Boolean);
          const durationIndex = lines.findIndex((x) => x.includes('视频时长'));
          const title = (durationIndex >= 0 ? lines.slice(0, durationIndex) : lines.slice(0, -1)).join(' ');
          const creatorLines = durationIndex >= 0 ? lines.slice(durationIndex + 2) : lines.slice(-1);
          const creator = creatorLines.join(' ').trim();

          return [{
            video_title: title,
            creator_name: creator,
            fastmoss_video_url: videoLink.href,
            sales_28d: cells[1]?.innerText.trim() || '',
            sales_amount_28d: cells[2]?.innerText.trim() || '',
            ad_spend_28d: cells[3]?.innerText.trim() || '',
            roas_28d: cells[4]?.innerText.trim() || '',
            views: cells[5]?.innerText.trim() || '',
            likes: cells[6]?.innerText.trim() || '',
            comments: cells[7]?.innerText.trim() || '',
            engagement_rate: cells[8]?.innerText.trim() || '',
            published_at: cells[9]?.innerText.trim() || ''
          }];
        })
        """,
    )


def go_next_video_page(page, page_number):
    next_li = page.locator("#related_videos .ant-pagination-next")
    if next_li.count() == 0:
        return False
    class_name = next_li.first.get_attribute("class") or ""
    if "disabled" in class_name:
        return False
    next_button = next_li.first.locator("button")
    if next_button.count() == 0:
        return False
    log(f"翻到商品关联视频第 {page_number + 1} 页")
    next_button.first.click()
    page.wait_for_timeout(1800)
    page.locator("#related_videos").scroll_into_view_if_needed(timeout=10000)
    page.wait_for_timeout(500)
    return True


def assert_related_videos_unlocked(page):
    try:
        section_text = page.locator("#related_videos").inner_text(timeout=5000)
    except Exception:
        return
    locked_markers = [
        "您当前是普通版用户",
        "开通会员解锁更多权限",
    ]
    if any(marker in section_text for marker in locked_markers):
        raise RuntimeError(
            "当前 FastMoss 账号无法访问商品关联视频真实数据，页面展示的是会员权限锁定后的示例数据。"
            "请切换到已开通对应权限的账号后重跑。"
        )


def collect_top_video_rows(page, limit=VIDEOS_PER_PRODUCT):
    assert_related_videos_unlocked(page)
    video_links = page.locator("#related_videos a[href*='/media-source/video/']")
    try:
        video_links.first.wait_for(state="attached", timeout=20000)
    except PlaywrightTimeoutError:
        return []

    videos = []
    seen = set()
    page_number = 1
    while len(videos) < limit:
        log(f"读取商品关联视频第 {page_number} 页，当前累计 {len(videos)}/{limit}")
        for item in parse_video_page(page):
            href = normalize_fastmoss_url(item.get("fastmoss_video_url"))
            if not href or href in seen:
                continue
            seen.add(href)
            item["fastmoss_video_url"] = href
            item["video_rank"] = len(videos) + 1
            videos.append(item)
            log(f"  已读取视频 {len(videos)}/{limit}: {href}")
            if len(videos) >= limit:
                return videos
        if not go_next_video_page(page, page_number):
            break
        page_number += 1

    return videos


def get_tiktok_url(page, context, fastmoss_video_url):
    log(f"打开视频详情页: {fastmoss_video_url}")
    page.goto(fastmoss_video_url, wait_until="domcontentloaded")
    close_entry_popup(page)
    if not is_logged_in(page):
        ensure_logged_in(page, context)
        page.goto(fastmoss_video_url, wait_until="domcontentloaded")
        close_entry_popup(page)
    page.wait_for_timeout(1600)

    official_link = page.locator("a", has_text="进入TikTok官方视频主页")
    if official_link.count() > 0:
        href = official_link.first.get_attribute("href")
        if href:
            log(f"已获取 TikTok URL: {href}")
            return href

    button = page.get_by_text("进入TikTok官方视频主页", exact=True)
    button.first.wait_for(state="visible", timeout=15000)
    try:
        with page.expect_popup(timeout=10000) as popup_info:
            button.first.click()
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=15000)
        url = popup.url
        popup.close()
        log(f"已获取 TikTok URL: {url}")
        return url
    except PlaywrightTimeoutError:
        before = page.url
        button.first.click()
        page.wait_for_timeout(3500)
        url = page.url if page.url != before else ""
        log(f"已获取 TikTok URL: {url}")
        return url


def main():
    rows = []
    log("开始采集任务")
    log(f"任务参数: 关键词={KEYWORD}, 国家={COUNTRY}, 类目={CATEGORY}, 商品数={PRODUCT_LIMIT}, 每商品视频数={VIDEOS_PER_PRODUCT}")
    log(f"浏览器模式: {'可见窗口' if SHOW_BROWSER else '最小化窗口'}")
    prepare_account_profile()
    with sync_playwright() as p:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
        if not SHOW_BROWSER:
            browser_args.extend(["--start-minimized", "--window-size=1920,1000"])
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=450,
            viewport={"width": 1920, "height": 1000},
            args=browser_args,
        )
        minimize_browser_windows()
        page = context.pages[0] if context.pages else context.new_page()
        ensure_logged_in(page, context)
        products = search_products(page, context)
        log(f"搜索到商品数: {len(products)}")
        for product in products:
            log(f"  商品 {product['rank']}: {product['url']}")

        for product in products:
            log(f"开始处理商品 {product['rank']}/{len(products)}: {product['url']}")
            try:
                open_related_videos(page, product["url"])
            except RuntimeError:
                ensure_logged_in(page, context)
                open_related_videos(page, product["url"])

            videos = collect_top_video_rows(page, limit=VIDEOS_PER_PRODUCT)
            log(f"商品 {product['rank']} 找到视频数: {len(videos)}")

            for video in videos:
                log(f"处理商品 {product['rank']} 视频 {video['video_rank']}/{len(videos)}")
                tiktok_url = get_tiktok_url(page, context, video["fastmoss_video_url"])
                row = {
                    "keyword": KEYWORD,
                    "country": COUNTRY,
                    "category": CATEGORY,
                    "product_rank": product["rank"],
                    "product_name": product["name"],
                    "video_rank": video["video_rank"],
                    "video_title": video["video_title"],
                    "creator_name": video.get("creator_name", ""),
                    "sales_28d": video.get("sales_28d", ""),
                    "sales_amount_28d": video.get("sales_amount_28d", ""),
                    "ad_spend_28d": video.get("ad_spend_28d", ""),
                    "roas_28d": video.get("roas_28d", ""),
                    "views": video.get("views", ""),
                    "likes": video.get("likes", ""),
                    "comments": video.get("comments", ""),
                    "engagement_rate": video.get("engagement_rate", ""),
                    "published_at": video.get("published_at", ""),
                    "fastmoss_video_url": video["fastmoss_video_url"],
                    "tiktok_video_url": tiktok_url,
                }
                rows.append(row)
                log(f"已保存记录数: {len(rows)}")

        output_csv = build_output_csv(rows, len(products))
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "keyword",
                    "country",
                    "category",
                    "product_rank",
                    "product_name",
                    "video_rank",
                    "video_title",
                    "creator_name",
                    "sales_28d",
                    "sales_amount_28d",
                    "ad_spend_28d",
                    "roas_28d",
                    "views",
                    "likes",
                    "comments",
                    "engagement_rate",
                    "published_at",
                    "fastmoss_video_url",
                    "tiktok_video_url",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

        context.storage_state(path=str(STORAGE_STATE))
        log(f"已保存 CSV: {output_csv}")
        try:
            input("测试完成。浏览器保持打开，按回车退出...")
        except EOFError:
            pass
        context.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"任务失败: {exc}")
        sys.exit(1)
