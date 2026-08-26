import unittest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from finished_video_manager import web


class ProductLinkOptionTest(unittest.TestCase):
    def test_bitbrowser_api_url_can_point_to_docker_host(self) -> None:
        with patch.dict(os.environ, {"BITBROWSER_API_URL": "http://host.docker.internal:54345/"}):
            self.assertEqual(web.bitbrowser_api_url(), "http://host.docker.internal:54345")

    def build_tasks(self, attach_product: bool) -> list[dict]:
        video_path = Path("/finished/TEST/video.mp4")
        profile = {
            "id": "profile-1",
            "name": "ES-shop-channel-user",
            "country": "ES",
            "store_name": "shop",
            "account_type": "channel",
        }
        video = {
            "path": video_path.as_posix(),
            "name": video_path.name,
            "product_code": "TEST",
            "countries": ["ES"],
            "published": False,
        }
        payload = {
            "profile_id": profile["id"],
            "attach_product": attach_product,
            "tasks": [
                {
                    "video_path": video_path.as_posix(),
                    "caption": "Caption #one #two #three #four #five",
                }
            ],
        }
        with (
            patch.object(web, "list_bitbrowser_profiles", return_value={"profiles": [profile]}),
            patch.object(web, "load_publish_config", return_value={}),
            patch.object(
                web,
                "cached_state_for_client",
                return_value={"videos": [video], "scan_index": {"ready": True}},
            ),
            patch.object(web, "safe_video_path", return_value=video_path),
        ):
            return web.build_queue_tasks(payload)

    def test_queue_build_uses_snapshot_without_scanning_vault(self) -> None:
        with patch.object(web, "scan_finished_videos") as scan:
            self.build_tasks(False)

        scan.assert_not_called()

    def test_without_product_link_does_not_require_mapping(self) -> None:
        tasks = self.build_tasks(False)

        self.assertFalse(tasks[0]["attach_product"])
        self.assertEqual(tasks[0]["product_id"], "")
        self.assertEqual(tasks[0]["product_short_name"], "")

    def test_product_link_remains_required_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "商品 ID 未配置"):
            self.build_tasks(True)

    def test_publish_without_product_link_skips_tiktok_product_step(self) -> None:
        caption = "Caption #one #two #three #four #five"
        runtime = MagicMock()
        browser = MagicMock()
        context = MagicMock()
        page = MagicMock()
        locator = MagicMock()
        runtime.chromium.connect_over_cdp.return_value = browser
        browser.contexts = [context]

        with (
            patch("playwright.sync_api.sync_playwright") as sync_playwright,
            patch.object(web, "prepare_tiktok_upload", return_value={"caption_filled": True}),
            patch.object(
                web,
                "bitbrowser_post",
                return_value={"success": True, "data": {"http": "127.0.0.1:1234"}},
            ),
            patch.object(web, "find_tiktok_upload_page", return_value=page),
            patch.object(web, "dismiss_tiktok_upload_preview_dialog", return_value=False),
            patch.object(web, "visible_tiktok_caption_input", return_value=locator),
            patch.object(web, "caption_text", return_value=caption),
            patch.object(web, "tiktok_hashtags_are_mentions", return_value=True),
            patch.object(web, "add_tiktok_product_link") as add_product,
            patch.object(web, "set_tiktok_ai_label", return_value=True),
            patch.object(web, "ensure_tiktok_public_visibility", return_value=True),
            patch.object(web, "disable_tiktok_music_copyright_check", return_value=True) as disable_music,
            patch.object(web, "disable_tiktok_content_quick_check", return_value=True) as disable_check,
            patch.object(web, "wait_for_tiktok_upload_complete", return_value=True),
            patch.object(web, "click_tiktok_publish_button", return_value={"url": "/content"}),
            patch.object(web, "append_publish_record", return_value={"status": "published"}) as append_record,
            patch.object(web, "close_confirmed_tiktok_publish_page", return_value={"publish_page_closed": True}),
            patch.object(web, "safe_video_path", return_value=Path("/finished/TEST/video.mp4")),
        ):
            sync_playwright.return_value.start.return_value = runtime
            result = web.publish_tiktok_video(
                "profile-1",
                "/finished/TEST/video.mp4",
                caption,
                "",
                "",
                attach_product=False,
            )

        add_product.assert_not_called()
        disable_music.assert_called_once_with(page)
        disable_check.assert_called_once_with(page)
        self.assertFalse(result["product_linked"])
        self.assertFalse(append_record.call_args.args[-1])


if __name__ == "__main__":
    unittest.main()
