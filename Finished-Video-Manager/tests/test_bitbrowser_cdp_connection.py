import unittest
import os
from unittest.mock import MagicMock, patch

from finished_video_manager import web


class BitBrowserCdpConnectionTest(unittest.TestCase):
    def test_docker_endpoint_replaces_localhost_with_host_gateway_ip(self) -> None:
        with (
            patch.dict(os.environ, {"BITBROWSER_API_URL": "http://host.docker.internal:54345"}),
            patch.object(web.socket, "gethostbyname", return_value="192.168.65.254"),
        ):
            self.assertEqual(
                web.normalize_cdp_endpoint("127.0.0.1:58401"),
                "http://192.168.65.254:58401",
            )

    def test_connects_using_latest_endpoint(self) -> None:
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser

        with patch.object(
            web,
            "bitbrowser_post",
            return_value={"success": True, "data": {"http": "127.0.0.1:1234"}},
        ) as open_browser:
            result = web.connect_bitbrowser_cdp(playwright, "profile-1")

        self.assertIs(result, browser)
        open_browser.assert_called_once_with(
            "/browser/open",
            {"id": "profile-1"},
            timeout=30,
        )
        playwright.chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:1234")

    def test_reopens_window_when_first_port_is_not_ready(self) -> None:
        playwright = MagicMock()
        browser = MagicMock()
        playwright.chromium.connect_over_cdp.side_effect = [ConnectionError("ECONNREFUSED"), browser]
        responses = [
            {"success": True, "data": {"http": "127.0.0.1:56468"}},
            {"success": True, "data": {"http": "127.0.0.1:56469"}},
        ]

        with (
            patch.object(web, "bitbrowser_post", side_effect=responses) as open_browser,
            patch.object(web.time, "sleep") as sleep,
        ):
            result = web.connect_bitbrowser_cdp(playwright, "profile-1")

        self.assertIs(result, browser)
        self.assertEqual(open_browser.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(
            [call.args[0] for call in playwright.chromium.connect_over_cdp.call_args_list],
            ["http://127.0.0.1:56468", "http://127.0.0.1:56469"],
        )


if __name__ == "__main__":
    unittest.main()
