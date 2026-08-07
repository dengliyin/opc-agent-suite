import unittest
from unittest.mock import MagicMock

from finished_video_manager import web


class ContentQuickCheckTest(unittest.TestCase):
    def build_page(self, state: str) -> tuple[MagicMock, MagicMock]:
        page = MagicMock()
        labels = MagicMock()
        label = MagicMock()
        containers = MagicMock()
        container = MagicMock()
        thumbs = MagicMock()
        thumb = MagicMock()
        controls = MagicMock()
        control = MagicMock()

        page.get_by_text.side_effect = lambda text, exact: (
            labels if text == "内容快速检查" else self.empty_locator()
        )
        labels.count.return_value = 1
        labels.nth.return_value = label
        label.is_visible.return_value = True
        label.locator.return_value = containers
        containers.count.return_value = 1
        containers.first = container

        def locate(selector: str) -> MagicMock:
            if selector == "span[data-part='thumb']":
                return thumbs
            if selector == ".Switch__content":
                return controls
            raise AssertionError(f"Unexpected selector: {selector}")

        container.locator.side_effect = locate
        thumbs.count.return_value = 1
        thumbs.first = thumb
        controls.count.return_value = 1
        controls.first = control
        thumb.get_attribute.side_effect = lambda name: (
            state if name == "data-state" else f"Switch__thumb--checked-{state == 'checked'}"
        )
        return page, control

    @staticmethod
    def empty_locator() -> MagicMock:
        locator = MagicMock()
        locator.count.return_value = 0
        return locator

    def test_checked_switch_is_clicked_and_verified_off(self) -> None:
        page, control = self.build_page("checked")
        thumb = (
            page.get_by_text("内容快速检查", exact=True)
            .nth(0)
            .locator.return_value.first.locator("span[data-part='thumb']")
            .first
        )
        states = iter(["checked", "unchecked"])
        thumb.get_attribute.side_effect = lambda name: (
            next(states) if name == "data-state" else ""
        )

        self.assertTrue(web.disable_tiktok_content_quick_check(page))
        control.click.assert_called_once_with()

    def test_unchecked_switch_is_left_unchanged(self) -> None:
        page, control = self.build_page("unchecked")

        self.assertTrue(web.disable_tiktok_content_quick_check(page))
        control.click.assert_not_called()

    def test_missing_feature_does_not_block_publish(self) -> None:
        page = MagicMock()
        page.get_by_text.side_effect = lambda *_args, **_kwargs: self.empty_locator()

        self.assertTrue(web.disable_tiktok_content_quick_check(page))

    def test_music_copyright_switch_is_clicked_and_verified_off(self) -> None:
        page, control = self.build_page("checked")
        page.get_by_text.side_effect = lambda text, exact: (
            page.get_by_text.return_value if text == "Music copyright check" else self.empty_locator()
        )
        label = MagicMock()
        containers = MagicMock()
        container = page.get_by_text.return_value.nth.return_value.locator.return_value.first
        page.get_by_text.return_value.count.return_value = 1
        page.get_by_text.return_value.nth.return_value = label
        label.is_visible.return_value = True
        label.locator.return_value = containers
        containers.count.return_value = 1
        containers.first = container
        thumbs = MagicMock()
        controls = MagicMock()
        thumb = MagicMock()
        container.locator.side_effect = lambda selector: (
            thumbs if selector == "span[data-part='thumb']" else controls
        )
        thumbs.count.return_value = 1
        thumbs.first = thumb
        controls.count.return_value = 1
        controls.first = control
        states = iter(["checked", "unchecked"])
        thumb.get_attribute.side_effect = lambda name: next(states) if name == "data-state" else ""

        self.assertTrue(web.disable_tiktok_music_copyright_check(page))
        control.click.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
