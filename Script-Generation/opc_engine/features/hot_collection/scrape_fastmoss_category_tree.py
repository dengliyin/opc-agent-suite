#!/usr/bin/env python3
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from opc_engine.features.hot_collection import collect_fastmoss_product_videos as fastmoss


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = ROOT / "data" / "fastmoss_category_tree.json"


def log(message):
    print(message, flush=True)


def visible_category_menus(page):
    return page.locator("ul.ant-cascader-menu").evaluate_all(
        """
        (menus) => menus.flatMap((menu, index) => {
          const rect = menu.getBoundingClientRect();
          const style = getComputedStyle(menu);
          const text = (menu.innerText || "").trim();
          if (!text || style.display === "none" || style.visibility === "hidden") return [];
          if (rect.width < 20 || rect.height < 20) return [];
          return [{
            index,
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            text,
          }];
        })
        """
    )


def menu_titles(menu):
    titles = []
    for line in str(menu.get("text") or "").splitlines():
        title = line.strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def get_top_categories(page):
    try:
        page.get_by_text("展开", exact=True).first.click(timeout=1500)
        page.wait_for_timeout(500)
    except Exception:
        pass
    categories = page.evaluate(
        """
        () => [...document.querySelectorAll('label')].flatMap((el) => {
          const rect = el.getBoundingClientRect();
          const text = (el.innerText || "").trim();
          if (!text || text === "全部") return [];
          if (["跨境店", "本土店"].includes(text)) return [];
          if (rect.top < 300 || rect.top > 490 || rect.left < 380 || rect.left > 1320) return [];
          return [{text, left: rect.left, top: rect.top}];
        }).sort((a, b) => a.top - b.top || a.left - b.left).map((item) => item.text)
        """
    )
    seen = []
    for category in categories:
        if category not in seen:
            seen.append(category)
    return seen


def hover_text(page, text):
    locator = page.get_by_text(text, exact=True).first
    locator.scroll_into_view_if_needed(timeout=5000)
    locator.hover(timeout=5000)
    page.wait_for_timeout(500)


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
    page.wait_for_timeout(250)


def scrape_tree(page):
    tree = {}
    top_categories = get_top_categories(page)

    for top in top_categories:
        log(f"一级类目: {top}")
        try:
            hover_text(page, top)
            menus = visible_category_menus(page)
            if not menus:
                tree[top] = {}
                log("  未发现二级菜单")
                continue

            first_menu = sorted(menus, key=lambda item: item["left"])[0]
            second_titles = menu_titles(first_menu)
            tree[top] = {}

            for second in second_titles:
                try:
                    hover_cascader_item(page, first_menu["index"], second)
                    menus_after_hover = visible_category_menus(page)
                    third_candidates = [
                        menu
                        for menu in menus_after_hover
                        if menu["left"] >= first_menu["right"] - 2 and menu["text"] != first_menu["text"]
                    ]
                    if third_candidates:
                        third_menu = sorted(third_candidates, key=lambda item: item["left"])[0]
                        third_titles = menu_titles(third_menu)
                    else:
                        third_titles = []
                    tree[top][second] = third_titles
                    log(f"  二级类目: {second}，三级 {len(third_titles)} 个")
                except Exception as exc:
                    tree[top][second] = []
                    log(f"  二级类目抓取失败: {second} ({exc})")
        except Exception as exc:
            tree[top] = {}
            log(f"一级类目抓取失败: {top} ({exc})")

    return {"top_categories": ["全部"] + top_categories, "category_tree": tree}


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fastmoss.prepare_account_profile()
    with sync_playwright() as p:
        fastmoss.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(fastmoss.PROFILE_DIR),
            headless=False,
            slow_mo=80,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1440,900",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        fastmoss.ensure_logged_in(page, context)
        page.goto(fastmoss.SEARCH_URL, wait_until="domcontentloaded")
        fastmoss.close_entry_popup(page)
        page.wait_for_timeout(1200)
        data = scrape_tree(page)
        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"已保存 FastMoss 类目树: {OUTPUT_PATH}")
        context.close()


if __name__ == "__main__":
    main()
