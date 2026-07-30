from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def load_launcher_module():
    path = WORKSPACE_ROOT / "scripts" / "run_console_foreground.py"
    spec = importlib.util.spec_from_file_location("run_console_foreground_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StorageLayoutTests(unittest.TestCase):
    def test_startup_creates_missing_template_directories_without_touching_files(self):
        launcher = load_launcher_module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            vault = root / "vault"
            (workspace / "storage-template/wiki/视频/新增目录").mkdir(parents=True)
            existing = vault / "wiki/视频/已有目录/内容.txt"
            existing.parent.mkdir(parents=True)
            existing.write_text("保留", encoding="utf-8")

            with (
                mock.patch.object(launcher, "ROOT_DIR", workspace),
                mock.patch.dict(os.environ, {"OPC_VAULT_ROOT": str(vault)}),
            ):
                result = launcher.ensure_storage_layout()

            self.assertEqual(result, vault)
            self.assertTrue((vault / "wiki/视频/新增目录").is_dir())
            self.assertEqual(existing.read_text(encoding="utf-8"), "保留")

    def test_startup_rejects_missing_vault_root(self):
        launcher = load_launcher_module()
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing-vault"
            with mock.patch.dict(os.environ, {"OPC_VAULT_ROOT": str(missing)}):
                with self.assertRaisesRegex(RuntimeError, "不存在或外接盘未挂载"):
                    launcher.ensure_storage_layout()


if __name__ == "__main__":
    unittest.main()
