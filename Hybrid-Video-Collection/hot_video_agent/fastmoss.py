from __future__ import annotations

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
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import browser_headless, safe_name
from .paths import ProjectPaths


LOGIN_URL = "https://www.fastmoss.com/zh/dashboard"
SEARCH_URL = "https://www.fastmoss.com/zh/e-commerce/search"


def chromium_launch_options() -> Dict[str, str]:
    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
    return {"executable_path": executable_path} if executable_path else {}


class FastMossCollector:
    def __init__(self, config: Dict[str, Any], paths: ProjectPaths, logger=print) -> None:
        self.config = config
        self.paths = paths
        self.log = logger
        self.fastmoss = config.get("fastmoss") or {}

        self.keyword = str(self.fastmoss.get("keyword", "") or "").strip()
        self.country = str(self.fastmoss.get("country", "全部") or "全部").strip()
        self.category_path = self._normalize_category_path(self.fastmoss.get("category_path") or ["全部"])
        self.category = " > ".join(self.category_path)
        self.shop_type = str(self.fastmoss.get("shop_type") or "全部").strip()
        self.product_types = self._normalize_list(self.fastmoss.get("product_types") or [])
        self.product_status = str(self.fastmoss.get("product_status") or "在售").strip()
        self.product_limit = int(self.fastmoss.get("product_limit", 3))
        self.videos_per_product = int(self.fastmoss.get("videos_per_product", 5))
        self.show_browser = bool(self.fastmoss.get("show_browser", False))
        self.headless = browser_headless()

        self.search_filters = {
            "达人出单率": str(self.fastmoss.get("creator_conversion_rate_filter") or "全部").strip(),
            "总销量": str(self.fastmoss.get("total_sales_filter") or "全部").strip(),
            "总GMV": str(self.fastmoss.get("total_gmv_filter") or "全部").strip(),
            "近7天销量": str(self.fastmoss.get("sales_7d_filter") or "全部").strip(),
            "近7天GMV": str(self.fastmoss.get("gmv_7d_filter") or "全部").strip(),
            "带货达人数": str(self.fastmoss.get("creator_count_filter") or "全部").strip(),
            "佣金比例": str(self.fastmoss.get("commission_rate_filter") or "全部").strip(),
            "带货方式": str(self.fastmoss.get("shipping_method_filter") or "全部").strip(),
        }

        phone = str(self.fastmoss.get("phone", "") or "").strip()
        self.profile_dir = paths.root / "browser-profile" / "fastmoss" / safe_name(phone, "default", 80)
        self.storage_state = paths.runtime_state_path("fastmoss-state.json")
        self.login_meta = paths.runtime_state_path("fastmoss-login-meta.json")
        self.diagnostics_dir = paths.diagnostics_dir()

        if self.fastmoss.get("phone"):
            os.environ.setdefault("FASTMOSS_PHONE", str(self.fastmoss.get("phone")))
        if self.fastmoss.get("password"):
            os.environ.setdefault("FASTMOSS_PASSWORD", str(self.fastmoss.get("password")))

    @staticmethod
    def _normalize_list(value: Any) -> List[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()]
        return []

    @staticmethod
    def _normalize_category_path(value: Any) -> List[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(">") if part.strip()] or ["全部"]
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()] or ["全部"]
        return ["全部"]

    def account_signature(self) -> Dict[str, str]:
        phone = str(self.fastmoss.get("phone", "") or "").strip()
        password = str(self.fastmoss.get("password", "") or "")
        password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest() if password else ""
        return {"phone": phone, "password_sha256": password_sha256}

    def read_login_meta(self) -> Dict[str, Any]:
        if not self.login_meta.exists():
            return {}
        try:
            return json.loads(self.login_meta.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_login_meta(self) -> None:
        self.login_meta.parent.mkdir(parents=True, exist_ok=True)
        payload = self.account_signature()
        payload.update(
            {
                "profile_dir": str(self.profile_dir),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self.login_meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def prepare_account_profile(self) -> None:
        signature = self.account_signature()
        if not signature["phone"]:
            return
        previous = self.read_login_meta()
        account_changed = (
            previous.get("phone") != signature["phone"]
            or previous.get("password_sha256") != signature["password_sha256"]
        )
        if not account_changed:
            return
        self.log("检测到 FastMoss 账号或密码已更新，清理旧登录状态并重新登录")
        if self.profile_dir.exists():
            shutil.rmtree(str(self.profile_dir), ignore_errors=True)
        if self.storage_state.exists():
            try:
                self.storage_state.unlink()
            except OSError:
                pass

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

    def build_output_csv(self, rows: List[Dict[str, Any]], product_count: int) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        video_url_count = sum(1 for row in rows if row.get("tiktok_video_url"))
        keyword_part = safe_name(self.keyword, "无关键词")
        category_filename = "-".join(self.category_path)
        filename = "_".join(
            [
                keyword_part,
                safe_name(self.country),
                safe_name(category_filename),
                today,
                str(product_count),
                str(video_url_count),
            ]
        )
        return self.paths.collection_csv_path(filename)

    def close_entry_popup(self, page) -> None:
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

    @staticmethod
    def visible_count(locator, timeout: int = 1000) -> int:
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
            return locator.count()
        except PlaywrightTimeoutError:
            return 0

    @staticmethod
    def is_logged_in(page) -> bool:
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

    def save_login_diagnostic(self, page, reason: str) -> None:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        screenshot = self.diagnostics_dir / "login_diagnostic.png"
        text_file = self.diagnostics_dir / "login_diagnostic.txt"
        try:
            page.screenshot(path=str(screenshot), full_page=False)
        except Exception:
            pass
        try:
            text_file.write_text(page.locator("body").inner_text(timeout=5000), encoding="utf-8")
        except Exception:
            pass
        self.log(f"登录诊断: {reason}")
        self.log(f"诊断截图: {screenshot}")
        self.log(f"诊断文本: {text_file}")

    def save_category_diagnostic(self, page, reason: str) -> None:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        screenshot = self.diagnostics_dir / "category_diagnostic.png"
        text_file = self.diagnostics_dir / "category_diagnostic.txt"
        try:
            page.screenshot(path=str(screenshot), full_page=False)
        except Exception:
            pass
        try:
            text_file.write_text(
                f"reason: {reason}\nurl: {page.url}\n\n{page.locator('body').inner_text(timeout=5000)}",
                encoding="utf-8",
            )
        except Exception:
            pass
        self.log(f"类目诊断: {reason}")
        self.log(f"诊断截图: {screenshot}")
        self.log(f"诊断文本: {text_file}")

    @staticmethod
    def click_text(page, text: str, exact: bool = True, timeout: int = 12000) -> None:
        locator = page.get_by_text(text, exact=exact)
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.click()

    @staticmethod
    def try_click_text(page, text: str, exact: bool = True, timeout: int = 2500) -> bool:
        try:
            FastMossCollector.click_text(page, text, exact=exact, timeout=timeout)
            return True
        except Exception:
            return False

    @staticmethod
    def try_click_pattern(page, pattern: str, timeout: int = 2500) -> bool:
        try:
            locator = page.get_by_text(re.compile(pattern))
            locator.first.wait_for(state="visible", timeout=timeout)
            locator.first.click()
            return True
        except Exception:
            return False

    def ensure_logged_in(self, page, context) -> None:
        self.log("检查程序登录状态...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1600)
        self.close_entry_popup(page)
        if self.is_logged_in(page):
            self.log("登录状态有效")
            context.storage_state(path=str(self.storage_state))
            self.write_login_meta()
            return

        page_text = page.locator("body").inner_text(timeout=5000)
        if "Restricted Access" in page_text or "security policy" in page_text:
            raise RuntimeError("页面访问被安全策略拦截。请把 fastmoss.show_browser 改为 true 完成一次验证后再试。")

        phone = os.environ.get("FASTMOSS_PHONE")
        password = os.environ.get("FASTMOSS_PASSWORD")
        if not phone or not password:
            raise RuntimeError("登录态已失效，请设置 FASTMOSS_PHONE 和 FASTMOSS_PASSWORD 后重跑")

        phone_input = page.get_by_placeholder("输入您的手机号")
        if self.visible_count(phone_input) == 0:
            if self.visible_count(page.get_by_text("登录/注册", exact=True)) == 0:
                self.save_login_diagnostic(page, "未检测到已登录账号，也没有找到登录/注册入口")
                raise RuntimeError("未找到登录入口。请开启可见浏览器运行一次，确认页面状态或手动完成登录。")
            self.click_text(page, "登录/注册")
            page.wait_for_timeout(900)

        self.try_click_text(page, "手机号登录/注册")
        page.wait_for_timeout(600)
        self.try_click_text(page, "密码登录", exact=True)
        page.wait_for_timeout(600)

        phone_input = page.get_by_placeholder("输入您的手机号")
        phone_input.wait_for(state="visible", timeout=10000)
        phone_input.fill(phone)

        password_input = page.get_by_placeholder("输入密码")
        password_input.wait_for(state="visible", timeout=10000)
        password_input.fill(password)

        self.click_text(page, "注册/登录")
        self.log("登录态失效，已自动提交手机号密码。若出现验证码、滑块或短信验证，请在可见浏览器里手动完成。")

        deadline = time.time() + 180
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            self.close_entry_popup(page)
            if self.is_logged_in(page):
                context.storage_state(path=str(self.storage_state))
                self.write_login_meta()
                self.log("登录成功，状态已更新。")
                return

        context.storage_state(path=str(self.storage_state))
        raise RuntimeError("未能确认登录成功；如果页面停在验证码/滑块，请手动完成后重跑")

    @staticmethod
    def open_filter_dropdown(page, label: str) -> bool:
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

    def select_optional_filter_value(self, page, label: str, value: str) -> None:
        value = str(value or "全部").strip()
        if not value or value == "全部":
            return
        self.log(f"设置筛选条件: {label} = {value}")
        try:
            self.open_filter_dropdown(page, label)
            page.wait_for_timeout(500)
            if (
                self.try_click_text(page, value, exact=True, timeout=2500)
                or self.try_click_text(page, f"{label}：{value}", exact=True, timeout=2500)
                or self.try_click_pattern(page, rf"{re.escape(label)}[：:]\s*{re.escape(value)}", timeout=2500)
            ):
                page.wait_for_timeout(400)
                self.try_click_pattern(page, r"确\s*认", timeout=1200)
                page.wait_for_timeout(700)
                return
        except Exception:
            pass
        self.log(f"未能自动设置筛选条件，已跳过: {label} = {value}")

    @staticmethod
    def point_to_visible_text(page, text: str, min_x: Optional[int] = None, max_x: Optional[int] = None, timeout: int = 10000):
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

    @staticmethod
    def normalize_fastmoss_url(href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        if href.startswith("/"):
            return "https://www.fastmoss.com" + href
        return href

    @staticmethod
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

    @staticmethod
    def hover_cascader_item(page, menu_index: int, title: str):
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

    def click_cascader_item(self, page, menu_index: int, title: str) -> None:
        point = self.hover_cascader_item(page, menu_index, title)
        page.mouse.click(point["x"], point["y"])
        page.wait_for_timeout(1500)

    @staticmethod
    def compact_category_text(value: str) -> str:
        return re.sub(r"[\s>＞\\/\-–—_]+", "", str(value or ""))

    def category_selection_confirmed(self, page) -> bool:
        selected_category_dash = " - ".join(self.category_path)
        selected_category_arrow = " > ".join(self.category_path)
        compact_selected = self.compact_category_text(selected_category_arrow)

        try:
            body_text = page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        decoded_url = unquote(page.url)
        compact_body = self.compact_category_text(body_text)

        if selected_category_dash in body_text or selected_category_arrow in body_text:
            return True
        if compact_selected and compact_selected in compact_body:
            return True
        if any(token in decoded_url for token in ("l3_cid=", "l3Cid=", "third_category", "thirdCategory")):
            return True
        return False

    def wait_for_category_selection(self, page, timeout_ms: int = 8000) -> bool:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if self.category_selection_confirmed(page):
                return True
            page.wait_for_timeout(500)
        return False

    @staticmethod
    def expand_category_area(page) -> None:
        try:
            expand_button = page.get_by_text("展开", exact=True).first
            if expand_button.is_visible(timeout=1200):
                expand_button.click(timeout=1200)
                page.wait_for_timeout(600)
        except Exception:
            pass

    def select_category_path(self, page) -> None:
        if not self.category_path or self.category_path[0] == "全部":
            self.log("商品分类: 全部")
            return

        self.expand_category_area(page)
        self.log(f"定位一级类目: {self.category_path[0]}")
        first_x, first_y = self.point_to_visible_text(page, self.category_path[0], min_x=390)
        page.mouse.move(first_x, first_y)
        page.wait_for_timeout(900)

        if len(self.category_path) == 1:
            page.mouse.click(first_x, first_y)
            page.wait_for_timeout(1500)
            self.log(f"已选择一级类目: {self.category_path[0]}")
            return

        menus = self.visible_category_menus(page)
        if not menus:
            raise RuntimeError(f"未展开二级类目菜单: {self.category_path[0]}")
        first_menu = sorted(menus, key=lambda item: abs(item["left"] - first_x))[0]

        self.log(f"展开二级类目: {self.category_path[1]}")
        self.hover_cascader_item(page, first_menu["index"], self.category_path[1])

        if len(self.category_path) == 2:
            self.click_cascader_item(page, first_menu["index"], self.category_path[1])
            self.log(f"已选择二级类目: {' - '.join(self.category_path)}")
            return

        menus_after_second = self.visible_category_menus(page)
        third_candidates = [
            menu
            for menu in menus_after_second
            if menu["left"] >= first_menu["right"] - 2 and menu["text"] != first_menu["text"]
        ]
        if not third_candidates:
            raise RuntimeError(f"未展开三级类目菜单: {self.category_path[1]}")
        third_menu = sorted(third_candidates, key=lambda item: item["left"])[0]

        self.log(f"点击三级类目: {self.category_path[2]}")
        self.click_cascader_item(page, third_menu["index"], self.category_path[2])

        selected_category = " - ".join(self.category_path)
        if not self.wait_for_category_selection(page):
            reason = f"第三级类目点击后，FastMoss 未回显选中状态: {' > '.join(self.category_path)}"
            self.save_category_diagnostic(page, reason)
            raise RuntimeError(reason)
        self.log(f"已确认类目: {selected_category}")

    def apply_search_filters(self, page) -> None:
        if self.shop_type and self.shop_type != "全部":
            self.log(f"选择店铺类型: {self.shop_type}")
            if not self.try_click_text(page, self.shop_type, exact=True, timeout=3000):
                self.log(f"未找到店铺类型选项，已跳过: {self.shop_type}")

        for product_type in self.product_types:
            if product_type and product_type != "全部":
                self.log(f"选择商品类型: {product_type}")
                if not self.try_click_text(page, product_type, exact=True, timeout=3000):
                    self.log(f"未找到商品类型选项，已跳过: {product_type}")

        if self.product_status and self.product_status not in {"全部", "在售"}:
            self.log(f"选择商品状态: {self.product_status}")
            if not self.try_click_text(page, self.product_status, exact=True, timeout=3000):
                self.log(f"未找到商品状态选项，已跳过: {self.product_status}")

        for label, value in self.search_filters.items():
            self.select_optional_filter_value(page, label, value)

    @staticmethod
    def wait_for_products(page) -> None:
        detail_links = page.locator("a[href*='/zh/e-commerce/detail/'], a[href*='/e-commerce/detail/']")
        try:
            detail_links.first.wait_for(state="attached", timeout=20000)
        except PlaywrightTimeoutError:
            page.wait_for_timeout(5000)

    def collect_top_products(self, page) -> List[Dict[str, Any]]:
        rows = page.locator("tr")
        products: List[Dict[str, Any]] = []

        for i in range(rows.count()):
            row = rows.nth(i)
            links = row.locator("a[href*='/e-commerce/detail/']")
            if links.count() == 0:
                continue
            href = self.normalize_fastmoss_url(links.first.get_attribute("href"))
            if not href:
                continue
            text = " ".join(row.inner_text(timeout=2000).split())
            if href not in {item["url"] for item in products}:
                products.append({"rank": len(products) + 1, "name": text[:160], "url": href})
            if len(products) >= self.product_limit:
                return products

        anchors = page.locator("a[href*='/e-commerce/detail/']")
        for i in range(anchors.count()):
            link = anchors.nth(i)
            href = self.normalize_fastmoss_url(link.get_attribute("href"))
            if not href:
                continue
            name = " ".join(link.inner_text(timeout=2000).split())
            if href not in {item["url"] for item in products}:
                products.append({"rank": len(products) + 1, "name": name[:160], "url": href})
            if len(products) >= self.product_limit:
                return products

        return products

    def search_products(self, page, context) -> List[Dict[str, Any]]:
        self.log("打开商品搜索页...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        self.close_entry_popup(page)
        if not self.is_logged_in(page):
            self.ensure_logged_in(page, context)
            page.goto(SEARCH_URL, wait_until="domcontentloaded")
            self.close_entry_popup(page)

        search_input = page.get_by_placeholder("商品搜索")
        search_input.wait_for(state="visible", timeout=15000)
        if self.keyword:
            self.log(f"输入关键词: {self.keyword}")
            search_input.fill(self.keyword)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1800)
        else:
            self.log("关键词为空，跳过关键词搜索，仅按国家/地区、商品分类和筛选条件采集")

        if self.country and self.country != "全部":
            self.log(f"选择国家/地区: {self.country}")
            self.click_text(page, self.country)
            page.wait_for_timeout(1200)
        else:
            self.log("国家/地区: 全部")

        self.select_category_path(page)
        self.apply_search_filters(page)
        self.wait_for_products(page)
        page.wait_for_timeout(2500)

        products = self.collect_top_products(page)
        if not products:
            raise RuntimeError("没有找到商品结果，请检查国家/地区、商品分类或筛选条件")
        self.log(f"已获取商品链接: {len(products)} 个")
        return products

    def open_related_videos(self, page, product_url: str) -> None:
        self.log(f"打开商品详情页: {product_url}")
        page.goto(product_url, wait_until="domcontentloaded")
        self.close_entry_popup(page)
        if not self.is_logged_in(page):
            raise RuntimeError("打开商品页时检测到登录态失效")
        related_anchor = page.locator("a[href='#related_videos']")
        if related_anchor.count() > 0:
            related_anchor.first.click()
        else:
            self.click_text(page, "商品关联视频")
        self.log("进入商品关联视频")
        page.wait_for_timeout(2200)
        page.locator("#related_videos").scroll_into_view_if_needed(timeout=10000)
        page.wait_for_timeout(1200)

        try:
            section = page.locator("#related_videos")
            section.get_by_text("近28天", exact=True).first.click(timeout=5000)
            self.log("已选择近28天")
            page.wait_for_timeout(1500)
        except PlaywrightTimeoutError:
            pass

    @staticmethod
    def parse_video_page(page) -> List[Dict[str, Any]]:
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

    def go_next_video_page(self, page, page_number: int) -> bool:
        next_li = page.locator("#related_videos .ant-pagination-next")
        if next_li.count() == 0:
            return False
        class_name = next_li.first.get_attribute("class") or ""
        if "disabled" in class_name:
            return False
        next_button = next_li.first.locator("button")
        if next_button.count() == 0:
            return False
        self.log(f"翻到商品关联视频第 {page_number + 1} 页")
        next_button.first.click()
        page.wait_for_timeout(1800)
        page.locator("#related_videos").scroll_into_view_if_needed(timeout=10000)
        page.wait_for_timeout(500)
        return True

    @staticmethod
    def assert_related_videos_unlocked(page) -> None:
        try:
            section_text = page.locator("#related_videos").inner_text(timeout=5000)
        except Exception:
            return
        locked_markers = [
            "您当前是普通版用户",
            "开通会员解锁更多权限",
        ]
        if any(marker in section_text for marker in locked_markers):
            raise RuntimeError("当前 FastMoss 账号无法访问商品关联视频真实数据，请切换到已开通对应权限的账号后重跑。")

    def collect_top_video_rows(self, page) -> List[Dict[str, Any]]:
        self.assert_related_videos_unlocked(page)
        video_links = page.locator("#related_videos a[href*='/media-source/video/']")
        try:
            video_links.first.wait_for(state="attached", timeout=20000)
        except PlaywrightTimeoutError:
            return []

        videos: List[Dict[str, Any]] = []
        seen = set()
        page_number = 1
        while len(videos) < self.videos_per_product:
            self.log(f"读取商品关联视频第 {page_number} 页，当前累计 {len(videos)}/{self.videos_per_product}")
            for item in self.parse_video_page(page):
                href = self.normalize_fastmoss_url(item.get("fastmoss_video_url"))
                if not href or href in seen:
                    continue
                seen.add(href)
                item["fastmoss_video_url"] = href
                item["video_rank"] = len(videos) + 1
                videos.append(item)
                self.log(f"  已读取视频 {len(videos)}/{self.videos_per_product}: {href}")
                if len(videos) >= self.videos_per_product:
                    return videos
            if not self.go_next_video_page(page, page_number):
                break
            page_number += 1
        return videos

    def get_tiktok_url(self, page, context, fastmoss_video_url: str) -> str:
        self.log(f"打开视频详情页: {fastmoss_video_url}")
        page.goto(fastmoss_video_url, wait_until="domcontentloaded")
        self.close_entry_popup(page)
        if not self.is_logged_in(page):
            self.ensure_logged_in(page, context)
            page.goto(fastmoss_video_url, wait_until="domcontentloaded")
            self.close_entry_popup(page)
        page.wait_for_timeout(1600)

        official_link = page.locator("a", has_text="进入TikTok官方视频主页")
        if official_link.count() > 0:
            href = official_link.first.get_attribute("href")
            if href:
                self.log(f"已获取 TikTok URL: {href}")
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
            self.log(f"已获取 TikTok URL: {url}")
            return url
        except PlaywrightTimeoutError:
            before = page.url
            button.first.click()
            page.wait_for_timeout(3500)
            url = page.url if page.url != before else ""
            self.log(f"已获取 TikTok URL: {url}")
            return url

    def run(self) -> Path:
        rows: List[Dict[str, Any]] = []
        self.log("开始采集任务")
        self.log(
            f"任务参数: 关键词={self.keyword or '空'}, 国家={self.country}, 类目={self.category}, "
            f"商品数={self.product_limit}, 每商品视频数={self.videos_per_product}"
        )
        browser_mode = "无头模式" if self.headless else ("可见窗口" if self.show_browser else "最小化窗口")
        self.log(f"浏览器模式: {browser_mode}")
        self.prepare_account_profile()

        with sync_playwright() as p:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
            ]
            if not self.show_browser and not self.headless:
                browser_args.extend(["--start-minimized", "--window-size=1920,1000"])
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                slow_mo=450,
                viewport={"width": 1920, "height": 1000},
                args=browser_args,
                **chromium_launch_options(),
            )
            try:
                self.minimize_browser_windows()
                page = context.pages[0] if context.pages else context.new_page()
                self.ensure_logged_in(page, context)
                products = self.search_products(page, context)
                self.log(f"搜索到商品数: {len(products)}")
                for product in products:
                    self.log(f"  商品 {product['rank']}: {product['url']}")

                for product in products:
                    self.log(f"开始处理商品 {product['rank']}/{len(products)}: {product['url']}")
                    try:
                        self.open_related_videos(page, product["url"])
                    except RuntimeError:
                        self.ensure_logged_in(page, context)
                        self.open_related_videos(page, product["url"])

                    videos = self.collect_top_video_rows(page)
                    self.log(f"商品 {product['rank']} 找到视频数: {len(videos)}")

                    for video in videos:
                        self.log(f"处理商品 {product['rank']} 视频 {video['video_rank']}/{len(videos)}")
                        tiktok_url = self.get_tiktok_url(page, context, video["fastmoss_video_url"])
                        row = {
                            "keyword": self.keyword,
                            "country": self.country,
                            "category": self.category,
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
                        self.log(f"已保存记录数: {len(rows)}")

                output_csv = self.build_output_csv(rows, len(products))
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(
                        handle,
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

                context.storage_state(path=str(self.storage_state))
                self.write_login_meta()
                self.log(f"已保存 CSV: {output_csv}")
                return output_csv
            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def refresh_login(self) -> None:
        self.log("开始刷新 FastMoss 登录状态")
        self.prepare_account_profile()
        with sync_playwright() as p:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            browser_args = ["--disable-blink-features=AutomationControlled"]
            if not self.show_browser and not self.headless:
                browser_args.extend(["--start-minimized", "--window-size=1440,900"])
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                slow_mo=350,
                viewport={"width": 1440, "height": 900},
                args=browser_args,
                **chromium_launch_options(),
            )
            try:
                self.minimize_browser_windows()
                page = context.pages[0] if context.pages else context.new_page()
                self.ensure_logged_in(page, context)
                self.log(f"登录状态已保存: {self.storage_state}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass


def main() -> int:
    from .config import ROOT, load_config, validate_config

    config = load_config()
    validate_config(config)
    paths = ProjectPaths(ROOT, config)
    paths.ensure()
    collector = FastMossCollector(config, paths)
    collector.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"任务失败: {exc}", flush=True)
        raise SystemExit(1)
