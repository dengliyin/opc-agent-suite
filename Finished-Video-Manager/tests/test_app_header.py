import unittest
from unittest.mock import patch

from finished_video_manager.web import (
    APP_HEADER_STYLE,
    DAILY_KPI_HTML,
    HTML,
    PRODUCT_ID_HTML,
    QUEUE_HTML,
    bitbrowser_open_payload,
    list_bitbrowser_profiles,
    render_app_page,
)


class AppHeaderTest(unittest.TestCase):
    def test_headless_open_uses_bitbrowser_required_parameters(self) -> None:
        self.assertEqual(bitbrowser_open_payload("profile-1"), {"id": "profile-1"})
        self.assertEqual(
            bitbrowser_open_payload("profile-1", "headless"),
            {
                "id": "profile-1",
                "args": ["--headless"],
                "queue": True,
                "ignoreDefaultUrls": True,
            },
        )

    def test_queue_page_offers_visible_and_headless_execution(self) -> None:
        self.assertIn('id="visibleButton"', QUEUE_HTML)
        self.assertIn('id="headlessButton"', QUEUE_HTML)

    @patch("finished_video_manager.web.bitbrowser_post")
    def test_profiles_are_read_from_current_subaccount_without_group_filter(self, post) -> None:
        post.return_value = {"success": True, "data": {"list": [], "totalNum": 0}}

        self.assertEqual(list_bitbrowser_profiles(), {"profiles": [], "total": 0})

        post.assert_called_once_with("/browser/list", {"page": 0, "pageSize": 100})

    @patch("finished_video_manager.web.bitbrowser_post")
    def test_profiles_are_sorted_by_country_then_descending_sequence(self, post) -> None:
        post.return_value = {
            "success": True,
            "data": {
                "list": [
                    {"id": "ie-11", "seq": 11, "name": "IE-shop-type-channel-user"},
                    {"id": "fr-14", "seq": 14, "name": "FR-shop-type-channel-user"},
                    {"id": "es-9", "seq": 9, "name": "ES-shop-type-channel-user"},
                    {"id": "fr-13", "seq": 13, "name": "FR-shop-type-channel-user2"},
                    {"id": "unknown", "seq": 99, "name": "未命名窗口"},
                ],
                "totalNum": 5,
            },
        }

        profiles = list_bitbrowser_profiles()["profiles"]

        self.assertEqual(
            [profile["id"] for profile in profiles],
            ["es-9", "fr-14", "fr-13", "ie-11", "unknown"],
        )

    def test_publish_page_has_no_group_management_controls(self) -> None:
        self.assertNotIn('id="bitGroup"', HTML)
        self.assertNotIn('/api/bitbrowser/groups', HTML)

    def test_publish_page_only_offers_queue_publishing(self) -> None:
        self.assertIn('onclick="enqueueSelected()">加入队列</button>', HTML)
        self.assertNotIn('onclick="manualUpload()"', HTML)
        self.assertNotIn('onclick="autoPublish()"', HTML)
        self.assertNotIn('/api/tiktok/manual-upload', HTML)
        self.assertNotIn('/api/tiktok/publish', HTML)

    def test_home_video_grid_is_paginated_without_preloading(self) -> None:
        self.assertIn('const PAGE_SIZE = 24;', HTML)
        self.assertIn('id="videoPager"', HTML)
        self.assertIn('const pageVideos = allVideos.slice(start, start + PAGE_SIZE);', HTML)
        self.assertIn('renderVideos(pageVideos);', HTML)
        self.assertIn('poster="${escapeAttr(v.thumbnail_url)}"', HTML)
        self.assertIn('preload="none"', HTML)
        self.assertNotIn('preload="metadata"', HTML)

    def test_product_mapping_options_use_product_info_catalog(self) -> None:
        self.assertIn("products = payload.products || [];", PRODUCT_ID_HTML)
        self.assertNotIn("fetch('/api/state')", PRODUCT_ID_HTML)

    def test_home_page_reports_state_api_errors_before_rendering(self) -> None:
        error_check = "if (!res.ok || state.error) throw new Error(state.error || '读取成品管理数据失败');"
        self.assertIn(error_check, HTML)
        self.assertLess(HTML.index(error_check), HTML.index("state.videos.map"))

    def test_shared_header_controls_use_a_fixed_border_box_height(self) -> None:
        self.assertIn("box-sizing:border-box;", APP_HEADER_STYLE)
        self.assertIn("height:32px;", APP_HEADER_STYLE)

    def test_all_pages_render_the_complete_shared_header(self) -> None:
        pages = [HTML, PRODUCT_ID_HTML, DAILY_KPI_HTML, QUEUE_HTML]
        expected = [
            'id="videoBadge"',
            'id="productBadge"',
            'id="libraryBadge"',
            'href="/product-id"',
            'href="/Daily-KPIs"',
            'id="queueBadge"',
            'onclick="refreshCurrentPage()"',
        ]

        for page in pages:
            rendered = render_app_page(page)
            for fragment in expected:
                with self.subTest(fragment=fragment):
                    self.assertIn(fragment, rendered)


if __name__ == "__main__":
    unittest.main()
