from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hot_video_agent import config as core  # noqa: E402


class ConfigTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
