#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from unittest import mock
import unittest
from pathlib import Path


CONSOLE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = CONSOLE_ROOT.parent


def load_console_module():
    spec = importlib.util.spec_from_file_location("opc_console_app", CONSOLE_ROOT / "kesai_app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ConsoleBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_console_module()

    def test_console_has_its_own_root(self):
        self.assertEqual(self.app.ROOT, CONSOLE_ROOT)
        self.assertEqual(self.app.WORKSPACE_ROOT, WORKSPACE_ROOT)

    def test_console_orchestrates_exactly_eight_agents(self):
        self.assertEqual(len(self.app.SERVICES), 8)
        self.assertEqual(set(self.app.ROUTE_TO_SERVICE.values()), set(self.app.SERVICES))

    def test_every_service_runs_from_its_agent_directory(self):
        for service in self.app.SERVICES.values():
            with self.subTest(service=service["label"]):
                self.assertEqual(service["cwd"].parent, WORKSPACE_ROOT)
                self.assertNotEqual(service["cwd"], CONSOLE_ROOT)

    def test_every_service_has_an_independent_launch_agent(self):
        for service_id, service in self.app.SERVICES.items():
            self.assertEqual(service["launch_agent_label"], f"com.kesai.opc-agent.{service_id}")

    def test_start_service_uses_launchctl_kickstart(self):
        with (
            mock.patch.object(self.app, "service_running", return_value=False),
            mock.patch.object(self.app.subprocess, "run") as run,
        ):
            run.side_effect = [
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=0, stdout="", stderr=""),
            ]
            result = self.app.start_service("collect")

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["launchctl", "print", f"gui/{self.app.os.getuid()}/com.kesai.opc-agent.collect"],
                ["launchctl", "kickstart", f"gui/{self.app.os.getuid()}/com.kesai.opc-agent.collect"],
            ],
        )
        self.assertTrue(result["started"])

    def test_start_service_bootstraps_an_unregistered_launch_agent(self):
        with (
            mock.patch.object(self.app, "service_running", return_value=False),
            mock.patch.object(self.app.subprocess, "run") as run,
            mock.patch.object(self.app.Path, "is_file", return_value=True),
        ):
            run.side_effect = [
                mock.Mock(returncode=1, stdout="", stderr="Could not find service"),
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=0, stdout="", stderr=""),
            ]
            result = self.app.start_service("adapt")

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][:2], ["launchctl", "print"])
        self.assertEqual(commands[1][:3], ["launchctl", "bootstrap", f"gui/{self.app.os.getuid()}"])
        self.assertEqual(commands[2][:2], ["launchctl", "kickstart"])
        self.assertTrue(result["started"])

    def test_agent_launchd_template_is_on_demand(self):
        template = (WORKSPACE_ROOT / "scripts" / "launchd" / "com.kesai.opc-agent.plist.template").read_text(encoding="utf-8")
        self.assertNotIn("RunAtLoad", template)
        self.assertNotIn("KeepAlive", template)

    def test_agent_installer_uses_each_agents_virtual_environment(self):
        installer = (WORKSPACE_ROOT / "scripts" / "install_agent_launchagents.sh").read_text(encoding="utf-8")
        for directory in (
            "Video-Collection",
            "Script-Analysis",
            "Script-Generation",
            "Script-Adaptation",
            "Video-Generation",
            "Finished-Video-Manager",
            "Product-Script-Rewrite",
            "Video-Assembly-hd",
        ):
            self.assertIn(f'"{directory}"', installer)
        self.assertIn('python_path="$ROOT_DIR/$agent_dir/.venv/bin/python"', installer)

    def test_console_no_longer_exposes_legacy_business_routes(self):
        self.assertTrue({"/product", "/publish", "/metrics", "/optimize"}.isdisjoint(self.app.ROUTE_TO_SERVICE))

    def test_script_agent_uses_script_generation_environment(self):
        command = self.app.SERVICES["script"]["command"]
        expected = WORKSPACE_ROOT / "Script-Generation" / ".venv" / "bin" / "python"
        self.assertEqual(Path(command[0]), expected)

    def test_double_click_launcher_bootstraps_missing_environment(self):
        launcher = (WORKSPACE_ROOT / "启动OPC集合控制台.command").read_text(encoding="utf-8")
        bootstrap = launcher.index('"$ROOT_DIR/scripts/bootstrap_macos.sh"')
        start = launcher.index('"$ROOT_DIR/scripts/start_console.sh"')

        self.assertIn('! -f "$ROOT_DIR/.env"', launcher)
        self.assertIn('! -x "$ROOT_DIR/OPC-Console/.venv/bin/python"', launcher)
        self.assertLess(bootstrap, start)


if __name__ == "__main__":
    unittest.main()
