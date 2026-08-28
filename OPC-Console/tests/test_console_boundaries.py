#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_console_orchestrates_exactly_thirteen_agents(self):
        self.assertEqual(len(self.app.SERVICES), 13)
        self.assertEqual(set(self.app.ROUTE_TO_SERVICE.values()), set(self.app.SERVICES))
        self.assertNotIn("compose", self.app.SERVICES)
        self.assertNotIn("/compose", self.app.ROUTE_TO_SERVICE)

    def test_services_only_expose_navigation_and_health_metadata(self):
        forbidden = {"cwd", "command", "launch_cwd", "launch_agent_label", "windows_task_name"}
        for service_id, service in self.app.SERVICES.items():
            with self.subTest(service=service_id):
                self.assertTrue(forbidden.isdisjoint(service))
                self.assertTrue(service["health_path"].startswith("/"))
                self.assertNotEqual(service["health_path"], "/")

    def test_all_agent_health_checks_are_lightweight(self):
        self.assertTrue(all(service["health_path"] == "/health" for service in self.app.SERVICES.values()))

    def test_service_can_use_internal_health_url_and_public_browser_url(self):
        with mock.patch.dict(
            self.app.os.environ,
            {
                "OPC_VIDEO_TEARDOWN_AGENT_URL": "http://script-analysis:9992/",
                "OPC_VIDEO_TEARDOWN_AGENT_URL_PUBLIC": "http://localhost:9992/",
            },
        ):
            service = self.app.build_services()["analyze"]

        self.assertEqual(service["health_url"], "http://script-analysis:9992/")
        self.assertEqual(service["url"], "http://localhost:9992/")

    def test_service_status_is_read_only(self):
        with mock.patch.object(self.app, "service_running", return_value=True):
            status = self.app.service_status("analyze")

        self.assertTrue(status["running"])
        self.assertNotIn("controllable", status)
        self.assertFalse(hasattr(self.app, "start_service"))
        self.assertFalse(hasattr(self.app, "stop_service"))

    def test_service_health_uses_business_http_probe(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        with mock.patch.object(self.app.urllib.request, "urlopen", return_value=response) as urlopen:
            self.assertTrue(self.app.service_running(self.app.SERVICES["hybrid_adapt"]))

        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/health"))

    def test_command_line_healthcheck_uses_business_probe_paths(self):
        healthcheck = (WORKSPACE_ROOT / "scripts" / "docker_health.sh").read_text(encoding="utf-8")
        self.assertEqual(healthcheck.count('"health"'), 14)
        self.assertIn('[[ "$status" =~ ^2 ]]', healthcheck)

    def test_console_cards_are_navigation_only(self):
        html = self.app.INDEX_HTML
        self.assertNotIn("toggleService", html)
        self.assertNotIn("/api/agent-services/${action}", html)
        self.assertNotIn("Compose 管理", html)
        self.assertIn(">打开</a>", html)

    def test_console_shows_each_primary_agent_once_without_workflow_lines(self):
        html = self.app.INDEX_HTML
        self.assertIn("OPC 大 Agent 控制台", html)
        self.assertNotIn("线路 1 · 爆款复刻", html)
        self.assertNotIn("统一归口 · 成品管理与发布", html)
        self.assertIn(
            "const dashboardAgentIds=['analyze','unified_script','assemble','hybrid_voice','hybrid_mix','finished','auto_publish'];",
            html,
        )
        for primary_agent in ("analyze", "unified_script", "assemble", "hybrid_voice", "hybrid_mix", "finished", "auto_publish"):
            self.assertEqual(html.count(f"'{primary_agent}'"), 1)
        for legacy_agent in ("script", "adapt", "rewrite", "hybrid_adapt", "hybrid_analyze", "hybrid_script"):
            self.assertNotIn(f"'{legacy_agent}'", html)

    def test_agent_cards_are_compact_and_equal_sized(self):
        html = self.app.INDEX_HTML
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", html)
        self.assertIn(".card{display:flex;flex-direction:column;min-height:210px", html)
        self.assertIn('${esc(service.description)}', html)

    def test_console_exposes_global_path_settings_page(self):
        self.assertIn('href="/settings/paths"', self.app.INDEX_HTML)
        self.assertIn("全局路径设置", self.app.PATH_SETTINGS_HTML)
        self.assertIn("/api/global-paths", self.app.PATH_SETTINGS_HTML)
        group_labels = {group["label"] for group in self.app.GLOBAL_PATH_GROUPS}
        self.assertIn("9992 · 脚本解析", group_labels)
        self.assertIn("10006 → 9995 · 适配稿与片段产出", group_labels)
        group = next(group for group in self.app.GLOBAL_PATH_GROUPS if group["id"] == "9995")
        self.assertIn("VIDEO_ASSEMBLY_PENDING_ROOT", group["keys"])
        self.assertIn("VIDEO_ASSEMBLY_OUTPUT_ROOT", group["keys"])
        self.assertIn("10000 · AI＋实拍混剪", group_labels)

    def test_console_exposes_global_ai_settings_page(self):
        self.assertIn('href="/settings/ai"', self.app.INDEX_HTML)
        self.assertIn("全局 API / 模型设置", self.app.AI_SETTINGS_HTML)
        self.assertIn("/api/global-ai-settings", self.app.AI_SETTINGS_HTML)
        group_ids = {group["id"] for group in self.app.GLOBAL_AI_GROUPS}
        self.assertEqual(group_ids, {"video_analysis", "text", "otu", "grok"})
        self.assertIn("/api/global-ai-migration", self.app.AI_SETTINGS_HTML)
        self.assertIn("发现旧 Agent 配置冲突", self.app.AI_SETTINGS_HTML)
        self.assertIn("/api/ai-agent-restart", self.app.AI_SETTINGS_HTML)
        restart_labels = {group["id"]: group["restart_label"] for group in self.app.GLOBAL_AI_GROUPS}
        self.assertEqual(restart_labels["video_analysis"], "重启 9992、10002")
        self.assertEqual(restart_labels["text"], "重启 10006 与旧脚本 Agent")
        self.assertEqual(restart_labels["otu"], "重启 9995")
        self.assertEqual(restart_labels["grok"], "重启 9995")

    def test_saving_global_ai_settings_masks_secrets_and_preserves_other_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                'OPC_VAULT_ROOT="/vault"\n'
                'MODELMESH_API_KEY="legacy-key"\n',
                encoding="utf-8",
            )
            payload = self.app.save_global_ai_settings(
                {
                    "OPC_TEXT_API_BASE_URL": "https://text.example/v1/",
                    "OPC_TEXT_MODEL": "text-model",
                    "OPC_TEXT_API_KEY": "new-secret",
                },
                env_file,
            )
            saved = env_file.read_text(encoding="utf-8")

        self.assertIn('OPC_VAULT_ROOT="/vault"', saved)
        self.assertIn('OPC_TEXT_API_BASE_URL="https://text.example/v1"', saved)
        self.assertIn('OPC_TEXT_API_KEY="new-secret"', saved)
        secret = next(item for item in payload["fields"] if item["key"] == "OPC_TEXT_API_KEY")
        self.assertEqual(secret["value"], "")
        self.assertTrue(secret["configured"])

    def test_legacy_environment_secrets_migrate_to_global_private_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text('OPC_VAULT_ROOT="/vault"\n', encoding="utf-8")
            with mock.patch.dict(
                self.app.os.environ,
                {"VIDEO_TEARDOWN_AGENT_API_KEY": "vision-secret", "DEEPSEEK_API_KEY": "text-secret"},
                clear=True,
            ):
                count = self.app.migrate_global_ai_secrets(env_file)
            saved = env_file.read_text(encoding="utf-8")

        self.assertEqual(count, 2)
        self.assertIn('OPC_VIDEO_ANALYSIS_API_KEY="vision-secret"', saved)
        self.assertIn('OPC_TEXT_API_KEY="text-secret"', saved)

    def test_global_paths_are_read_from_container_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                'OPC_VAULT_ROOT="/tmp/opc vault"\n'
                'SCRIPT_ROOT="${OPC_VAULT_ROOT}/scripts"\n',
                encoding="utf-8",
            )
            payload = self.app.global_paths_payload(env_file)
            settings = {item["key"]: item for item in payload["paths"]}

        self.assertEqual(settings["SCRIPT_ROOT"]["resolved"], "/tmp/opc vault/scripts")
        self.assertEqual(settings["VIDEO_TEARDOWN_INPUT_ROOT"]["group"], "9992")
        self.assertEqual(settings["VIDEO_TITLE_LIBRARY_ROOT"]["group"], "9996")
        self.assertEqual(
            settings["VIDEO_ASSEMBLY_OUTPUT_ROOT"]["resolved"],
            "/tmp/opc vault/wiki/视频/成品视频",
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
                {"OPC_VAULT_ROOT": "/new vault", "SCRIPT_ROOT": "${OPC_VAULT_ROOT}/new scripts"},
                env_file,
            )
            saved = env_file.read_text(encoding="utf-8")

        self.assertIn('MODELMESH_API_KEY="keep-me"', saved)
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

    def test_native_service_entrypoints_are_absent(self):
        native_paths = (
            ".env.example",
            ".env.windows.example",
            "启动OPC集合控制台.command",
            "scripts/bootstrap_macos.sh",
            "scripts/bootstrap_windows.ps1",
            "scripts/install_agent_launchagents.sh",
            "scripts/install_windows_tasks.ps1",
        )
        for relative_path in native_paths:
            with self.subTest(path=relative_path):
                self.assertFalse((WORKSPACE_ROOT / relative_path).exists())


if __name__ == "__main__":
    unittest.main()
