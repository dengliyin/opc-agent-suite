import unittest

from finished_video_manager.web import close_confirmed_tiktok_publish_page


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class PublishPageCleanupTest(unittest.TestCase):
    def test_closes_confirmed_content_page(self) -> None:
        page = FakePage("https://www.tiktok.com/tiktokstudio/content")

        result = close_confirmed_tiktok_publish_page(page, timeout_seconds=0)

        self.assertTrue(result["publish_page_closed"])
        self.assertTrue(page.closed)

    def test_keeps_unconfirmed_upload_page_open(self) -> None:
        page = FakePage("https://www.tiktok.com/tiktokstudio/upload")

        result = close_confirmed_tiktok_publish_page(page, timeout_seconds=0)

        self.assertFalse(result["publish_page_closed"])
        self.assertFalse(page.closed)


if __name__ == "__main__":
    unittest.main()
