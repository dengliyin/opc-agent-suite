import unittest
from pathlib import Path

from finished_video_manager.web import select_tiktok_video


class FakeInput:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    def set_input_files(self, path: str, timeout: int) -> None:
        self.calls.append((path, timeout))
        if self.error:
            raise self.error


class FakeInputs:
    def __init__(self, file_input: FakeInput) -> None:
        self.file_input = file_input

    def count(self) -> int:
        return 1

    def nth(self, index: int) -> FakeInput:
        return self.file_input


class FakePage:
    def __init__(self, file_input: FakeInput) -> None:
        self.inputs = FakeInputs(file_input)
        self.context = None

    def locator(self, selector: str) -> FakeInputs:
        return self.inputs


class TikTokVideoSelectionTest(unittest.TestCase):
    def test_file_input_allows_sixty_seconds(self) -> None:
        file_input = FakeInput()
        page = FakePage(file_input)
        video_path = Path("/tmp/video.mp4")

        result = select_tiktok_video(page, video_path)

        self.assertEqual(result, 'input:input[type="file"][accept*="video"]:0')
        self.assertEqual(file_input.calls, [(video_path.as_posix(), 60000)])

    def test_large_file_uses_local_cdp_path_instead_of_transfer(self) -> None:
        file_input = FakeInput(
            RuntimeError("Cannot transfer files larger than 50Mb to a browser not co-located with the server")
        )
        page = FakePage(file_input)
        session = unittest.mock.MagicMock()
        session.send.side_effect = [
            {"root": {"nodeId": 1}},
            {"nodeIds": [7]},
            {},
        ]
        page.context = unittest.mock.MagicMock()
        page.context.new_cdp_session.return_value = session
        video_path = Path("/tmp/large-video.mp4")

        result = select_tiktok_video(page, video_path)

        self.assertEqual(result, 'cdp:input[type="file"][accept*="video"]:0')
        session.send.assert_any_call(
            "DOM.setFileInputFiles",
            {"nodeId": 7, "files": [video_path.as_posix()]},
        )
        session.detach.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
