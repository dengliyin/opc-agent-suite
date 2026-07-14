#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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

    def test_console_no_longer_exposes_legacy_business_routes(self):
        self.assertTrue({"/product", "/publish", "/metrics", "/optimize"}.isdisjoint(self.app.ROUTE_TO_SERVICE))

    def test_script_agent_uses_script_generation_environment(self):
        command = self.app.SERVICES["script"]["command"]
        expected = WORKSPACE_ROOT / "Script-Generation" / ".venv" / "bin" / "python"
        self.assertEqual(Path(command[0]), expected)


if __name__ == "__main__":
    unittest.main()
