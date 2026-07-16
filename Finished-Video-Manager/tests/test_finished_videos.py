import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from finished_video_manager import web


class FinishedVideoScanTest(unittest.TestCase):
    def test_new_layout_uses_modified_date_and_hides_legacy_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = "TR05-TROIL生发精华"
            filename = f"omni-裂变-{product}-TH_008.mp4"
            new_path = root / product / filename
            legacy_path = root / "omni" / "2026-07-13" / product / filename
            new_path.parent.mkdir(parents=True)
            new_path.write_bytes(b"new")
            timestamp = datetime(2026, 7, 15, 9, 30).timestamp()
            os.utime(new_path, (timestamp, timestamp))
            record = {"status": "published", "video_path": legacy_path.as_posix()}

            with patch.object(web, "FINISHED_VIDEO_ROOT", root):
                videos = web.scan_finished_videos({}, [record])

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["path"], new_path.as_posix())
        self.assertEqual(videos[0]["date"], "2026-07-15")
        self.assertEqual(videos[0]["workflow"], "")
        self.assertTrue(videos[0]["published"])

    def test_old_path_resolves_to_new_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = "TR05-TROIL生发精华"
            filename = "demo.mp4"
            old_path = root / "omni" / "2026-07-13" / product / filename
            new_path = root / product / filename
            new_path.parent.mkdir(parents=True)
            old_path.parent.mkdir(parents=True)
            new_path.write_bytes(b"new")
            old_path.write_bytes(b"old")

            with patch.object(web, "FINISHED_VIDEO_ROOT", root):
                resolved = web.resolve_finished_video_path(old_path.as_posix())

        self.assertEqual(resolved, new_path.resolve().as_posix())

    def test_legacy_layout_keeps_path_date_when_no_new_copy_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = "TR05-TROIL生发精华"
            path = root / "omni" / "2026-07-13" / product / "legacy.mp4"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"legacy")

            with patch.object(web, "FINISHED_VIDEO_ROOT", root):
                videos = web.scan_finished_videos({}, [])

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["date"], "2026-07-13")
        self.assertEqual(videos[0]["workflow"], "omni")


if __name__ == "__main__":
    unittest.main()
