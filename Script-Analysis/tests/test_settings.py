from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyze_video = load_module("script_analysis_analyze_video", ROOT / "scripts" / "analyze_video.py")
        cls.web_app = load_module("script_analysis_web_app", ROOT / "scripts" / "web_app.py")

    def test_tracked_settings_do_not_contain_api_key(self):
        settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))

        self.assertEqual(settings["base_url"], "https://zexapi.com")
        self.assertEqual(settings["model"], "gemini-3.5-flash")
        self.assertNotIn("api_key", settings)

    def test_runner_merges_only_local_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "settings.json"
            local = root / "settings.local.json"
            shared.write_text(json.dumps({"base_url": "https://shared.test", "model": "shared-model"}), encoding="utf-8")
            local.write_text(json.dumps({"api_key": "secret", "base_url": "https://stale.test"}), encoding="utf-8")

            with patch.object(self.analyze_video, "DEFAULT_SETTINGS_PATH", shared), patch.object(
                self.analyze_video, "DEFAULT_SECRETS_PATH", local
            ):
                settings = self.analyze_video.load_settings(shared)

        self.assertEqual(settings["api_key"], "secret")
        self.assertEqual(settings["base_url"], "https://shared.test")

    def test_web_saves_shared_settings_and_api_key_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "settings.json"
            local = root / "settings.local.json"
            shared.write_text("{}", encoding="utf-8")

            with patch.object(self.web_app, "SETTINGS_PATH", shared), patch.object(self.web_app, "SECRETS_PATH", local):
                self.web_app.update_settings(
                    {"base_url": "https://shared.test", "model": "shared-model", "api_key": "secret"}
                )

            shared_settings = json.loads(shared.read_text(encoding="utf-8"))
            local_settings = json.loads(local.read_text(encoding="utf-8"))

        self.assertEqual(shared_settings, {"base_url": "https://shared.test", "model": "shared-model"})
        self.assertEqual(local_settings["api_key"], "secret")

    def test_business_paths_prefer_global_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths_file = Path(temp_dir) / "paths.local.json"
            paths_file.write_text(
                json.dumps({"video_dir": "/fallback/videos", "script_dir": "/fallback/scripts"}),
                encoding="utf-8",
            )
            with patch.object(self.web_app, "PATHS_PATH", paths_file), patch.dict(
                self.web_app.os.environ,
                {
                    "VIDEO_TEARDOWN_INPUT_ROOT": "/global/videos",
                    "VIDEO_TEARDOWN_OUTPUT_ROOT": "/global/scripts",
                },
            ):
                video_dir, script_dir = self.web_app.local_paths()

        self.assertEqual(video_dir, Path("/global/videos"))
        self.assertEqual(script_dir, Path("/global/scripts"))

    def test_long_video_names_use_short_queue_and_output_names(self):
        video_id = "7666010963795102989"
        name = f"digimon634-{video_id}-" + "very_long_title_" * 20 + ".mp4"
        item = {"path": name, "video_id": video_id}

        self.assertEqual(self.web_app.queue_item_output_name(1, item), f"001_{video_id}")
        self.assertLessEqual(len(self.web_app.compact_stem(name)), 96)
        self.assertIn(video_id, self.web_app.compact_stem(name))
        self.assertLessEqual(len(self.analyze_video.output_stem(name)), 64)
        self.assertIn(video_id, self.analyze_video.output_stem(name))


if __name__ == "__main__":
    unittest.main()
