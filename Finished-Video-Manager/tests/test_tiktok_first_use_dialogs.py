import unittest
from unittest.mock import MagicMock, patch

from finished_video_manager import web


class TikTokFirstUseDialogsTest(unittest.TestCase):
    def test_upload_preview_dialog_is_dismissed_via_backdrop(self) -> None:
        page = MagicMock()
        page.evaluate.return_value = {"x": 8, "y": 8}

        self.assertTrue(web.dismiss_tiktok_upload_preview_dialog(page))

        page.mouse.click.assert_called_once_with(8.0, 8.0)
        page.wait_for_timeout.assert_called_once_with(500)

    def test_missing_upload_preview_dialog_does_nothing(self) -> None:
        page = MagicMock()
        page.evaluate.return_value = None

        self.assertFalse(web.dismiss_tiktok_upload_preview_dialog(page))

        page.mouse.click.assert_not_called()

    def test_ai_disclosure_dialog_clicks_primary_button(self) -> None:
        page = MagicMock()
        page.evaluate.return_value = True

        self.assertTrue(web.confirm_tiktok_ai_disclosure_dialog(page))

        page.wait_for_timeout.assert_called_once_with(800)

    def test_ai_label_confirms_first_use_dialog_after_enabling(self) -> None:
        page = MagicMock()
        advanced = MagicMock()
        advanced.count.return_value = 0
        switch = MagicMock()
        switch.is_checked.return_value = True
        page.locator.side_effect = lambda selector: (
            advanced if selector == '[data-e2e="advanced_settings_container"]' else switch
        )
        page.evaluate.side_effect = [
            {"checked": False, "disabled": False},
            True,
        ]

        with patch.object(web, "confirm_tiktok_ai_disclosure_dialog", return_value=True) as confirm:
            self.assertTrue(web.set_tiktok_ai_label(page, True))

        confirm.assert_called_once_with(page)


if __name__ == "__main__":
    unittest.main()
