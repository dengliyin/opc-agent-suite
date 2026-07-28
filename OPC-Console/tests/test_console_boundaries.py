#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
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

    def test_console_orchestrates_exactly_thirteen_agents(self):
        self.assertEqual(len(self.app.SERVICES), 13)
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
                ["launchctl", "kickstart", "-k", f"gui/{self.app.os.getuid()}/com.kesai.opc-agent.collect"],
            ],
        )
        self.assertTrue(result["started"])

    def test_console_waits_for_agent_health_after_start(self):
        html = self.app.INDEX_HTML

        self.assertIn("const startingServices=new Set()", html)
        self.assertIn("await waitForService(id)", html)
        self.assertIn("Agent 启动超时", html)

    def test_console_groups_agents_into_three_workflow_lines(self):
        html = self.app.INDEX_HTML

        self.assertIn("线路 1 · 爆款复刻", html)
        self.assertIn("线路 2 · 产品脚本改写", html)
        self.assertIn("线路 3 · AI＋实拍混剪", html)
        self.assertIn("统一归口 · 成品管理与发布", html)
        self.assertIn("steps:['collect','analyze','script','adapt','assemble','compose']", html)
        self.assertIn("steps:['rewrite','script','adapt','assemble','compose']", html)
        self.assertIn("steps:['hybrid_collect','hybrid_analyze','hybrid_script','hybrid_adapt'", html)

    def test_agent_cards_do_not_render_descriptions(self):
        self.assertNotIn('<p class="desc">', self.app.INDEX_HTML)

    def test_agent_cards_use_equal_dimensions(self):
        html = self.app.INDEX_HTML

        self.assertIn("grid-template-columns:repeat(6,minmax(0,1fr))", html)
        self.assertIn(".card{display:flex;flex-direction:column;height:160px", html)
        self.assertIn(".destination .card{width:calc((100% - 50px)/6)", html)

    def test_hybrid_mix_agent_is_connected_as_an_independent_service(self):
        html = self.app.INDEX_HTML

        self.assertIn("'hybrid_adapt'", html)
        self.assertIn("'hybrid_mix'", html)
        self.assertNotIn("10000 待开发", html)
        self.assertEqual(len(self.app.SERVICES), 13)
        service_urls = [str(service.get("url", "")) for service in self.app.SERVICES.values()]
        self.assertTrue(any(":9999" in url for url in service_urls))
        self.assertTrue(any(":10000" in url for url in service_urls))
        self.assertTrue(any(":10003" in url for url in service_urls))

    def test_console_exposes_global_path_settings_page(self):
        self.assertIn('href="/settings/paths"', self.app.INDEX_HTML)
        self.assertIn("全局路径设置", self.app.PATH_SETTINGS_HTML)
        self.assertIn("/api/global-paths", self.app.PATH_SETTINGS_HTML)
        group_labels = {group["label"] for group in self.app.GLOBAL_PATH_GROUPS}
        self.assertIn("9992 · 脚本解析", group_labels)
        self.assertIn("10003 · 钩子与 CTA 脚本复刻裂变", group_labels)
        self.assertIn("9995 · 片段产出", group_labels)
        self.assertIn("9998 · 片段合成", group_labels)
        self.assertIn("10000 · AI＋实拍混剪", group_labels)
        self.assertIn("其他 Agent", self.app.PATH_SETTINGS_HTML)

    def test_global_paths_are_read_from_current_env_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                'OPC_VAULT_ROOT="/tmp/opc vault"\n'
                'SCRIPT_ROOT="${OPC_VAULT_ROOT}/scripts"\n',
                encoding="utf-8",
            )

            payload = self.app.global_paths_payload(env_file)
            settings = {item["key"]: item for item in payload["paths"]}

        self.assertEqual(settings["OPC_VAULT_ROOT"]["value"], "/tmp/opc vault")
        self.assertEqual(settings["SCRIPT_ROOT"]["value"], "${OPC_VAULT_ROOT}/scripts")
        self.assertEqual(settings["SCRIPT_ROOT"]["resolved"], "/tmp/opc vault/scripts")
        self.assertEqual(settings["OPC_VAULT_ROOT"]["group"], "shared")
        self.assertEqual(settings["SCRIPT_ROOT"]["group"], "9995")
        self.assertEqual(settings["VIDEO_TEARDOWN_INPUT_ROOT"]["group"], "9992")
        self.assertEqual(settings["VIDEO_TITLE_LIBRARY_ROOT"]["group"], "9996")
        self.assertEqual(settings["SCRIPT_MISTAKE_BOOK_ROOT"]["group"], "script_knowledge")
        self.assertEqual(
            settings["VIDEO_TEARDOWN_INPUT_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/纯AI视频/01来源素材",
        )
        self.assertEqual(
            settings["VIDEO_TITLE_LIBRARY_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/成品视频/视频标题库",
        )
        self.assertEqual(
            settings["SCRIPT_MISTAKE_BOOK_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/共享知识库/脚本错题本",
        )
        self.assertEqual(
            settings["VIDEO_ASSEMBLY_OUTPUT_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/成品视频",
        )
        self.assertEqual(
            settings["HYBRID_REAL_FOOTAGE_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/AI实拍混剪/07实拍素材",
        )

    def test_saving_global_paths_preserves_non_path_env_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                'OPC_VAULT_ROOT="/old"\n'
                'SCRIPT_ROOT="${OPC_VAULT_ROOT}/scripts"\n'
                'MODELMESH_API_KEY="keep-me"\n',
                encoding="utf-8",
            )

            payload = self.app.save_global_paths(
                {
                    "OPC_VAULT_ROOT": "/new vault",
                    "SCRIPT_ROOT": "${OPC_VAULT_ROOT}/new scripts",
                },
                env_file,
            )
            saved = env_file.read_text(encoding="utf-8")

        self.assertIn('MODELMESH_API_KEY="keep-me"', saved)
        self.assertIn('OPC_VAULT_ROOT="/new vault"', saved)
        self.assertIn('SCRIPT_ROOT="${OPC_VAULT_ROOT}/new scripts"', saved)
        settings = {item["key"]: item for item in payload["paths"]}
        self.assertEqual(settings["SCRIPT_ROOT"]["resolved"], "/new vault/new scripts")

    def test_global_path_save_rejects_relative_and_unknown_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text('OPC_VAULT_ROOT="/old"\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "绝对路径"):
                self.app.save_global_paths({"OPC_VAULT_ROOT": "relative/path"}, env_file)
            with self.assertRaisesRegex(ValueError, "未知路径配置"):
                self.app.save_global_paths({"UNSUPPORTED_PATH": "/tmp"}, env_file)

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
            "Hybrid-Video-Collection",
            "Hybrid-Script-Analysis",
            "Hybrid-Script-Generation",
            "Script-Generation",
            "Script-Adaptation",
            "Hybrid-Script-Adaptation",
            "Video-Generation",
            "Finished-Video-Manager",
            "Product-Script-Rewrite",
            "Video-Assembly-hd",
            "Hybrid-Video-Mixer",
        ):
            self.assertIn(f'"{directory}"', installer)
        self.assertIn('python_path="$ROOT_DIR/$agent_dir/.venv/bin/python"', installer)

    def test_console_no_longer_exposes_legacy_business_routes(self):
        self.assertTrue({"/product", "/publish", "/metrics", "/optimize"}.isdisjoint(self.app.ROUTE_TO_SERVICE))

    def test_script_agent_uses_script_generation_environment(self):
        command = self.app.SERVICES["script"]["command"]
        expected = WORKSPACE_ROOT / "Script-Generation" / ".venv" / "bin" / "python"
        self.assertEqual(Path(command[0]), expected)

    def test_hybrid_adaptation_agent_uses_its_independent_environment(self):
        service = self.app.SERVICES["hybrid_adapt"]
        expected = WORKSPACE_ROOT / "Hybrid-Script-Adaptation" / ".venv" / "bin" / "python"

        self.assertEqual(Path(service["command"][0]), expected)
        self.assertEqual(service["cwd"], WORKSPACE_ROOT / "Hybrid-Script-Adaptation")
        self.assertEqual(service["url"], "http://127.0.0.1:9999/")

    def test_hybrid_collection_and_analysis_use_independent_environments(self):
        collection = self.app.SERVICES["hybrid_collect"]
        analysis = self.app.SERVICES["hybrid_analyze"]

        self.assertEqual(
            Path(collection["command"][0]),
            WORKSPACE_ROOT / "Hybrid-Video-Collection" / ".venv" / "bin" / "python",
        )
        self.assertEqual(collection["url"], "http://127.0.0.1:10001/")
        self.assertEqual(
            Path(analysis["command"][0]),
            WORKSPACE_ROOT / "Hybrid-Script-Analysis" / ".venv" / "bin" / "python",
        )
        self.assertEqual(analysis["url"], "http://127.0.0.1:10002/")

    def test_hybrid_mixer_uses_its_independent_environment(self):
        service = self.app.SERVICES["hybrid_mix"]
        self.assertEqual(
            Path(service["command"][0]),
            WORKSPACE_ROOT / "Hybrid-Video-Mixer" / ".venv" / "bin" / "python",
        )
        self.assertEqual(service["cwd"], WORKSPACE_ROOT / "Hybrid-Video-Mixer")
        self.assertEqual(service["url"], "http://127.0.0.1:10000/")

    def test_double_click_launcher_bootstraps_missing_environment(self):
        launcher = (WORKSPACE_ROOT / "启动OPC集合控制台.command").read_text(encoding="utf-8")
        bootstrap = launcher.index('"$ROOT_DIR/scripts/bootstrap_macos.sh"')
        start = launcher.index('"$ROOT_DIR/scripts/start_console.sh"')

        self.assertIn('! -f "$ROOT_DIR/.env"', launcher)
        self.assertIn('! -x "$ROOT_DIR/OPC-Console/.venv/bin/python"', launcher)
        self.assertLess(bootstrap, start)


if __name__ == "__main__":
    unittest.main()
