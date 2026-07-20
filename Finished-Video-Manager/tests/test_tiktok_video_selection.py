import unittest
from pathlib import Path

from finished_video_manager.web import select_tiktok_video


class FakeInput:
    def __init__(self) -> None:
        self.calls = []

    def set_input_files(self, path: str, timeout: int) -> None:
        self.calls.append((path, timeout))


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


if __name__ == "__main__":
    unittest.main()
