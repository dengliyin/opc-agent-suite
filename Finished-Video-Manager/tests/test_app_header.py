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

    def test_publish_page_has_no_group_management_controls(self) -> None:
        self.assertNotIn('id="bitGroup"', HTML)
        self.assertNotIn('/api/bitbrowser/groups', HTML)

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
