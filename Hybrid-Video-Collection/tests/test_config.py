from __future__ import annotations

import json
import inspect
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hot_video_agent import config as core  # noqa: E402
from hot_video_agent import kolsprite  # noqa: E402
from hot_video_agent import paths  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_downloads_use_kolsprite_only(self) -> None:
        source = inspect.getsource(kolsprite)
        self.assertNotIn("Snap" + "Tik", source)
        self.assertIn("Kolsprite 多次尝试仍然失败", source)
        self.assertIn("fetch_video_data_by_url", source)
        self.assertNotIn("DOWNLOADER_SUBMIT_TEXT", source)

    def test_browser_is_headless_when_docker_requests_it(self) -> None:
        with patch.dict(core.os.environ, {"OPC_BROWSER_HEADLESS": "1"}, clear=True):
            self.assertTrue(core.browser_headless(show_browser=True))

    def test_checked_browser_uses_available_display(self) -> None:
        with (
            patch.dict(core.os.environ, {"DISPLAY": ":0"}, clear=True),
            patch.object(core.sys, "platform", "linux"),
        ):
            self.assertFalse(core.browser_headless(show_browser=True))

    def test_unchecked_browser_stays_headless(self) -> None:
        with patch.dict(core.os.environ, {"DISPLAY": ":0"}, clear=True):
            self.assertTrue(core.browser_headless(show_browser=False))

    def test_video_filename_is_bounded_and_keeps_video_id(self) -> None:
        video_id = "7666010963795102989"
        stem = core.video_filename_stem("digimon634", video_id, "Mini drone " + "very high end " * 30)

        self.assertLessEqual(len(stem), core.VIDEO_FILENAME_STEM_MAX)
        self.assertIn(video_id, stem)

    def test_init_migrates_legacy_config_to_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy" / "config.json"
            target = root / "runtime" / "config.json"
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({"product": {"name": "测试产品"}}), encoding="utf-8")

            with (
                patch.object(core, "CONFIG_PATH", target),
                patch.object(core, "LEGACY_CONFIG_PATH", legacy),
            ):
                result = core.init_config(target)

            self.assertEqual(result, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["product"]["name"], "测试产品")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertTrue(legacy.exists())

    def test_save_config_creates_private_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "nested" / "config.json"
            core.save_config({"product": {"name": "测试产品"}}, target)

            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["product"]["name"], "测试产品")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_hybrid_output_preserves_material_type_and_product(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            config = {
                "product": {"name": "测试产品"},
                "hybrid": {"material_type": "混剪-CTA"},
            }
            with patch.object(paths, "HOT_VIDEO_LIBRARY_ROOT", output_root):
                output_dir = paths.ProjectPaths(ROOT, config).hot_video_dir()

            self.assertEqual(output_dir, output_root / "混剪-CTA" / "测试产品")
            self.assertTrue(output_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
