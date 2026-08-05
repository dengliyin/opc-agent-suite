from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))


def load_module(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


console_launcher = load_module("run_console_foreground.py", "run_console_foreground_test")
agent_launcher = load_module("run_agent_foreground.py", "run_agent_foreground_test")


class StoragePreflightTests(unittest.TestCase):
    def test_preflight_actually_reads_and_writes_vault_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "existing").mkdir()

            identity = console_launcher.verify_vault_access(root)

            self.assertEqual(identity, console_launcher.storage_identity(root))
            self.assertEqual(list(root.iterdir()), [root / "existing"])

    def test_preflight_reports_permission_error(self):
        root = Path("/vault")
        with mock.patch.object(console_launcher.os, "scandir", side_effect=PermissionError(1, "Operation not permitted")):
            with self.assertRaisesRegex(RuntimeError, "不可读"):
                console_launcher.verify_vault_access(root)


class AgentSupervisorTests(unittest.TestCase):
    def test_permission_error_is_recognized_from_probe_response(self):
        self.assertTrue(
            agent_launcher.response_has_permission_error(
                b'{"error":"[Errno 1] Operation not permitted: /Volumes/seafer"}'
            )
        )
        self.assertFalse(agent_launcher.response_has_permission_error(b'{"error":"bad config"}'))

    def test_health_status_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "health" / "hybrid_adapt.json"

            agent_launcher.write_health_status(path, healthy=False, detail="EPERM")

            self.assertIn('"healthy": false', path.read_text(encoding="utf-8"))
            self.assertFalse(any(item.name.endswith(".tmp") for item in path.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
