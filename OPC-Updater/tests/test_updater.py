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

    def run_ai_restart(self, group):
        self.assertTrue(self.app._update_lock.acquire(blocking=False))
        self.app.perform_ai_restart(group)

    def test_dirty_worktree_blocks_before_migration_or_build(self):
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
        self.assertFalse(any(command[:2] in (["git", "fetch"], ["git", "pull"]) for command in commands))
        self.assertFalse(any(command[:2] == ["docker", "compose"] for command in commands))

    def test_clean_local_update_rebuilds_core_services_without_network_git(self):
        commands = []

        def fake_run(command, check=True):
            commands.append(command)
            if command[:3] == ["git", "branch", "--show-current"]:
                return self.result(command, "main\n")
            if command[:3] == ["git", "status", "--porcelain"]:
                return self.result(command, "")
            if command[:3] == ["git", "rev-parse", "--short"]:
                return self.result(command, "local456\n")
            if command[-2:] == ["config", "--services"]:
                return self.result(command, "\n".join((*self.app.CORE_SERVICES, "opc-updater")) + "\n")
            return self.result(command)

        with mock.patch.object(self.app, "run", side_effect=fake_run), mock.patch.object(
            self.app, "schedule_reload"
        ) as schedule_reload:
            self.run_update()

        status = self.app.read_state()
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["old_commit"], "local456")
        self.assertEqual(status["new_commit"], "local456")
        self.assertFalse(any(command[:2] in (["git", "fetch"], ["git", "pull"]) for command in commands))
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

    def test_ai_group_restart_only_restarts_and_waits_for_mapped_services(self):
        commands = []

        def fake_run(command, check=True):
            commands.append(command)
            return self.result(command)

        with mock.patch.object(self.app, "run", side_effect=fake_run):
            self.run_ai_restart("video_analysis")

        services = self.app.AI_RESTART_GROUPS["video_analysis"]
        self.assertTrue(
            any("restart" in command and all(item in command for item in services) for command in commands)
        )
        self.assertTrue(
            any("--wait" in command and all(item in command for item in services) for command in commands)
        )
        status = self.app.read_state()
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["group"], "video_analysis")
        self.assertEqual(status["services"], list(services))

    def test_unknown_ai_restart_group_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            self.app.ai_restart_services("unknown")

    def test_ai_restart_groups_map_to_only_the_documented_agents(self):
        self.assertEqual(
            self.app.AI_RESTART_GROUPS,
            {
                "video_analysis": ("script-analysis", "hybrid-script-analysis"),
                "text": (
                    "script-generation",
                    "script-adaptation",
                    "product-script-rewrite",
                    "hybrid-script-adaptation",
                    "hybrid-script-generation",
                ),
                "otu": ("video-generation",),
                "grok": ("video-generation",),
            },
        )


if __name__ == "__main__":
    unittest.main()
