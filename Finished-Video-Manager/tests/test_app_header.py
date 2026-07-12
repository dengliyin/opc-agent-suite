import unittest

from finished_video_manager.web import (
    APP_HEADER_STYLE,
    DAILY_KPI_HTML,
    HTML,
    PRODUCT_ID_HTML,
    QUEUE_HTML,
    render_app_page,
)


class AppHeaderTest(unittest.TestCase):
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
