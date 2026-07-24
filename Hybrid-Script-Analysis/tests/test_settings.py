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
                    "HYBRID_VIDEO_TEARDOWN_INPUT_ROOT": "/global/videos",
                    "HYBRID_VIDEO_TEARDOWN_OUTPUT_ROOT": "/global/scripts",
                },
            ):
                video_dir, script_dir = self.web_app.local_paths()

        self.assertEqual(video_dir, Path("/global/videos"))
        self.assertEqual(script_dir, Path("/global/scripts"))

    def test_queue_preserves_material_type_and_product_and_scopes_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_dir = root / "01参考视频"
            script_dir = root / "02解析脚本"
            hook_dir = video_dir / "混剪-钩子" / "产品A"
            cta_dir = video_dir / "混剪-CTA" / "产品A"
            hook_dir.mkdir(parents=True)
            cta_dir.mkdir(parents=True)
            video_name = "creator-7569257172798803221-demo.mp4"
            (hook_dir / video_name).write_bytes(b"hook")
            (cta_dir / video_name).write_bytes(b"cta")
            existing_dir = script_dir / "混剪-钩子" / "产品A"
            existing_dir.mkdir(parents=True)
            (existing_dir / "MY-creator-7569257172798803221-demo.md").write_text("# done", encoding="utf-8")

            scan = self.web_app.scan_teardown_queue(video_dir, script_dir)

        self.assertEqual(scan["summary"]["total"], 2)
        self.assertEqual(scan["summary"]["skipped"], 1)
        self.assertEqual(scan["summary"]["pending"], 1)
        pending = scan["pending"][0]
        self.assertEqual(pending["material_type"], "混剪-CTA")
        self.assertEqual(pending["product"], "产品A")
        self.assertEqual(
            Path(pending["target_path"]).parent,
            script_dir / "混剪-CTA" / "产品A",
        )


if __name__ == "__main__":
    unittest.main()
