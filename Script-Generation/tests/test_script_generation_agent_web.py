#!/usr/bin/env python3
from __future__ import annotations

import unittest
import tempfile
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
