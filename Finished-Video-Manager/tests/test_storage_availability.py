import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finished_video_manager import web


class StorageAvailabilityTest(unittest.TestCase):
    def test_storage_is_not_ready_without_a_title_library_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = root / "videos"
            titles = videos / "titles"
            titles.mkdir(parents=True)

            with (
                patch.object(web, "FINISHED_VIDEO_ROOT", videos),
                patch.object(web, "TITLE_LIBRARY_ROOT", titles),
            ):
                self.assertFalse(web.finished_storage_ready())

    def test_storage_is_ready_when_video_root_and_title_library_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = root / "videos"
            titles = videos / "titles"
            titles.mkdir(parents=True)
            (titles / "product.md").write_text("# title", encoding="utf-8")

            with (
                patch.object(web, "FINISHED_VIDEO_ROOT", videos),
                patch.object(web, "TITLE_LIBRARY_ROOT", titles),
            ):
                self.assertTrue(web.finished_storage_ready())

    def test_startup_retries_with_a_fresh_process_when_storage_stays_unavailable(self) -> None:
        with (
            patch.object(web, "finished_storage_ready", return_value=False),
            patch.object(web, "STORAGE_STARTUP_RETRY_SECONDS", 30),
            patch.object(web.time, "monotonic", side_effect=[100, 131]),
            patch.object(web.time, "sleep"),
        ):
            with self.assertRaisesRegex(SystemExit, "75"):
                web.wait_for_finished_storage()


if __name__ == "__main__":
    unittest.main()
