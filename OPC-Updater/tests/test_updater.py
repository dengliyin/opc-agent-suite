from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


UPDATER_ROOT = Path(__file__).resolve().parents[1]


def load_updater_module():
    spec = importlib.util.spec_from_file_location("opc_updater", UPDATER_ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.app = load_updater_module()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app.STATE_DIR = root / "updater"
        self.app.STATE_FILE = self.app.STATE_DIR / "status.json"
        self.app.LOG_FILE = self.app.STATE_DIR / "update.log"
        self.app.TOKEN_FILE = self.app.STATE_DIR / "updater.token"
        self.app.ensure_private_files()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def result(command, stdout="", returncode=0):
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=None)

    def run_update(self):
        self.assertTrue(self.app._update_lock.acquire(blocking=False))
        self.app.perform_update()

    def test_dirty_worktree_blocks_before_fetch_or_build(self):
        commands = []

        def fake_run(command, check=True):
            commands.append(command)
            if command[:3] == ["git", "branch", "--show-current"]:
                return self.result(command, "main\n")
            if command[:3] == ["git", "status", "--porcelain"]:
                return self.result(command, " M local-change.txt\n")
            return self.result(command)

        with mock.patch.object(self.app, "run", side_effect=fake_run):
            self.run_update()

        status = self.app.read_state()
        self.assertEqual(status["state"], "blocked")
        self.assertEqual(status["dirty_paths"], ["local-change.txt"])
        self.assertFalse(any(command[:2] == ["git", "fetch"] for command in commands))
        self.assertFalse(any(command[:2] == ["docker", "compose"] for command in commands))

    def test_clean_update_rebuilds_core_services_but_not_updater(self):
        commands = []
        commits = iter(("old123\n", "new456\n"))

        def fake_run(command, check=True):
            commands.append(command)
            if command[:3] == ["git", "branch", "--show-current"]:
                return self.result(command, "main\n")
            if command[:3] == ["git", "status", "--porcelain"]:
                return self.result(command, "")
            if command[:3] == ["git", "rev-parse", "--short"]:
                return self.result(command, next(commits))
            if command[-2:] == ["config", "--services"]:
                return self.result(command, "\n".join((*self.app.CORE_SERVICES, "opc-updater")) + "\n")
            return self.result(command)

        with mock.patch.object(self.app, "run", side_effect=fake_run), mock.patch.object(
            self.app, "schedule_reload"
        ) as schedule_reload:
            self.run_update()

        status = self.app.read_state()
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["old_commit"], "old123")
        self.assertEqual(status["new_commit"], "new456")
        compose_up = next(command for command in commands if "up" in command and "--build" in command)
        self.assertNotIn("opc-updater", compose_up)
        for service in self.app.CORE_SERVICES:
            self.assertIn(service, compose_up)
        schedule_reload.assert_called_once_with()

    def test_status_and_token_are_persisted(self):
        token = self.app.ensure_private_files()
        self.app.write_state({"state": "running", "message": "testing"})
        self.assertEqual(self.app.ensure_private_files(), token)
        self.assertEqual(self.app.read_state()["message"], "testing")
        self.assertEqual(self.app.TOKEN_FILE.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
