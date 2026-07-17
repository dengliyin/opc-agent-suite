#!/usr/bin/env python3
from __future__ import annotations

import unittest

from opc_engine.features.script_generation.script_generation_agent_web import HTML_PAGE, GenerationJob


class ScriptGenerationAgentWebTests(unittest.TestCase):
    def test_run_without_reference_is_rejected_before_queueing(self):
        job = GenerationJob()

        with self.assertRaisesRegex(ValueError, "请先选择有效的爆款参考文件"):
            job.start({"script_enable_mutation_rewrite": "true", "script_mutation_variants": 5})

        self.assertEqual(job.next_id, 1)
        self.assertEqual(job.queue, [])

    def test_browser_checks_reference_before_posting_run(self):
        self.assertIn("if (!referencePath)", HTML_PAGE)
        self.assertIn("请先从爆款脚本列表选择一个参考脚本", HTML_PAGE)

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
