#!/usr/bin/env python3
from __future__ import annotations

import unittest
import tempfile
import json
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from opc_engine.features.script_generation import script_generation_agent_web
from opc_engine.features.script_generation.script_generation_agent_web import HTML_PAGE, GenerationJob


class ScriptGenerationAgentWebTests(unittest.TestCase):
    def test_reference_status_uses_markdown_stems_across_target_countries(self):
        reference = Path("/tmp/MX-author-1234567890123456789-example.md")
        stems = (
            "复刻-product-IE-author-1234567890123456789",
            "裂变-product-ES-author-1234567890123456789",
            "裂变-product-IT-author-1234567890123456789_002",
            "裂变-product-IE-other-9999999999999999999",
        )

        status = script_generation_agent_web.reference_output_status("product", reference, stems)

        self.assertTrue(status["cloned"])
        self.assertEqual(status["mutation_count"], 2)

    def test_library_scans_each_product_output_directory_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            product_root = root / "products"
            reference_root = root / "references"
            output_root = root / "outputs"
            product_root.mkdir()
            (reference_root / "product").mkdir(parents=True)
            (product_root / "product-产品信息.md").write_text("product", encoding="utf-8")
            (reference_root / "product" / "MX-a-1234567890123456789.md").write_text("a", encoding="utf-8")
            (reference_root / "product" / "US-b-9999999999999999999.md").write_text("b", encoding="utf-8")

            with (
                patch.object(script_generation_agent_web, "PRODUCT_INFO_SOURCE_DIR", product_root),
                patch.object(script_generation_agent_web, "HOT_SCRIPT_SOURCE_ROOT", reference_root),
                patch.object(script_generation_agent_web, "SCRIPT_OUTPUT_SOURCE_ROOT", output_root),
                patch.object(script_generation_agent_web, "product_output_stems", return_value=()) as scan_outputs,
            ):
                payload = script_generation_agent_web.library_payload({"script_country": "不改变原脚本"})

        self.assertEqual(len(payload["references"]), 2)
        scan_outputs.assert_called_once_with("product")

    def test_run_without_reference_is_rejected_before_queueing(self):
        job = GenerationJob()

        with self.assertRaisesRegex(ValueError, "请先选择有效的爆款参考文件"):
            job.start({"script_enable_mutation_rewrite": "true", "script_mutation_variants": 5})

        self.assertEqual(job.next_id, 1)
        self.assertEqual(job.queue, [])

    def test_browser_checks_reference_before_posting_run(self):
        self.assertIn("if (!referencePath)", HTML_PAGE)
        self.assertIn("请先从爆款脚本列表选择一个参考脚本", HTML_PAGE)

    def test_job_logs_are_rendered_newest_first(self):
        self.assertIn("function renderJobLogs(logText)", HTML_PAGE)
        self.assertIn(".reverse().join('\\n')", HTML_PAGE)
        self.assertIn("logElement.scrollTop = 0", HTML_PAGE)
        self.assertIn("renderJobLogs(job.logs)", HTML_PAGE)

    def test_duration_override_is_not_exposed_or_forwarded(self):
        self.assertNotIn('id="totalDuration"', HTML_PAGE)
        command = GenerationJob()._subprocess_command({"script_total_duration": "8秒"})
        self.assertNotIn("--total-duration", command)

    def test_save_state_uses_process_only_model_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "bundled" / "model_defaults.json"
            local_model = root / "runtime" / "model_settings.json"
            local_inputs = root / "runtime" / "inputs.json"
            shared.parent.mkdir()
            local_model.parent.mkdir()
            shared.write_text(json.dumps({"script_generation_model": "default-model"}), encoding="utf-8")
            local_model.write_text(json.dumps({"modelmesh_api_key": "secret"}), encoding="utf-8")
            local_inputs.write_text("{}", encoding="utf-8")

            with (
                patch.object(script_generation_agent_web, "SHARED_MODEL_SETTINGS_PATH", shared),
                patch.object(script_generation_agent_web, "LOCAL_MODEL_SETTINGS_PATH", local_model),
                patch.object(script_generation_agent_web, "LOCAL_INPUTS_PATH", local_inputs),
                patch.object(script_generation_agent_web, "migrate_legacy_local_configs"),
                patch.object(script_generation_agent_web, "state_payload", return_value={"ok": True}),
                patch.dict(script_generation_agent_web.os.environ, {}, clear=True),
            ):
                result = script_generation_agent_web.save_state(
                    {
                        "script_generation_model": "custom-model",
                        "modelmesh_base_url": "https://example.test",
                        "script_generation_timeout": 240,
                        "script_generation_max_output_tokens": 32768,
                    }
                )
                self.assertEqual(script_generation_agent_web.os.environ["OPC_RUNTIME_TEXT_MODEL"], "custom-model")
                self.assertEqual(script_generation_agent_web.os.environ["OPC_RUNTIME_TEXT_BASE_URL"], "https://example.test")

            self.assertEqual(result, {"ok": True})
            self.assertEqual(json.loads(shared.read_text(encoding="utf-8"))["script_generation_model"], "default-model")
            saved_local = json.loads(local_model.read_text(encoding="utf-8"))
            self.assertNotIn("script_generation_model", saved_local)
            self.assertNotIn("modelmesh_api_key", saved_local)

    def test_open_markdown_uses_exact_absolute_obsidian_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "含 空格的脚本.md"
            script_path.write_text("# test", encoding="utf-8")

            with patch.object(script_generation_agent_web.subprocess, "Popen") as popen:
                result = script_generation_agent_web.open_local_path(str(script_path))

            command = popen.call_args.args[0]
            self.assertEqual(command[0], "open")
            parsed = urllib.parse.urlparse(command[1])
            self.assertEqual(parsed.scheme, "obsidian")
            self.assertEqual(parsed.netloc, "open")
            self.assertEqual(urllib.parse.parse_qs(parsed.query)["path"], [str(script_path.resolve())])
            self.assertEqual(result["path"], str(script_path.resolve()))

    def test_browser_reports_the_path_returned_by_open_endpoint(self):
        self.assertIn("`已打开：${data.path}`", HTML_PAGE)

    def test_multiple_mutation_variants_are_forwarded(self):
        command = GenerationJob()._subprocess_command(
            {"script_enable_mutation_rewrite": "true", "script_mutation_variants": 5}
        )

        self.assertIn("--enable-mutation", command)
        self.assertEqual(command[-2:], ["--mutation-variants", "5"])

    def test_country_and_language_options_match_supported_markets(self):
        self.assertIn("['越南', '越南 (VN)']", HTML_PAGE)
        self.assertIn("['菲律宾', '菲律宾 (PH)']", HTML_PAGE)
        self.assertIn("['越南语', '越南语']", HTML_PAGE)
        self.assertIn("['菲律宾语', '菲律宾语']", HTML_PAGE)
        self.assertIn("['墨西哥', '墨西哥 (MX)']", HTML_PAGE)
        self.assertIn("['巴西', '巴西 (BR)']", HTML_PAGE)
        self.assertNotIn("['尼泊尔', '尼泊尔 (NP)']", HTML_PAGE)
        self.assertNotIn("['澳大利亚', '澳大利亚 (AU)']", HTML_PAGE)
        self.assertNotIn("['尼泊尔语', '尼泊尔语']", HTML_PAGE)


if __name__ == "__main__":
    unittest.main()
