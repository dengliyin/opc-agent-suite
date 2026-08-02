import unittest
from unittest.mock import MagicMock

from finished_video_manager.web import discard_tiktok_local_draft


class TikTokLocalDraftTest(unittest.TestCase):
    def test_visible_local_draft_is_discarded_with_first_button(self) -> None:
        page = MagicMock()
        containers = MagicMock()
        container = MagicMock()
        buttons = MagicMock()
        discard_button = MagicMock()
        modals = MagicMock()
        modal = MagicMock()
        primary_buttons = MagicMock()
        confirm_button = MagicMock()
        page.locator.side_effect = lambda selector: (
            containers if selector == '[data-e2e="local_draft_container"]' else modals
        )
        containers.count.return_value = 1
        containers.nth.return_value = container
        container.is_visible.return_value = True
        container.locator.return_value = buttons
        buttons.count.return_value = 2
        buttons.first = discard_button
        modals.count.return_value = 1
        modals.nth.return_value = modal
        modal.is_visible.side_effect = [False, True]
        modal.locator.return_value = primary_buttons
        primary_buttons.count.return_value = 1
        primary_buttons.last = confirm_button

        self.assertTrue(discard_tiktok_local_draft(page))

        discard_button.click.assert_called_once_with(timeout=5000)
        confirm_button.click.assert_called_once_with(timeout=5000)
        container.wait_for.assert_called_once_with(state="hidden", timeout=10000)

    def test_missing_local_draft_does_nothing(self) -> None:
        page = MagicMock()
        containers = MagicMock()
        page.locator.return_value = containers
        containers.count.return_value = 0

        self.assertFalse(discard_tiktok_local_draft(page))


if __name__ == "__main__":
    unittest.main()
