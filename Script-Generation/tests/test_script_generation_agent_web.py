#!/usr/bin/env python3
from __future__ import annotations

import unittest

from opc_engine.features.script_generation.script_generation_agent_web import HTML_PAGE


class ScriptGenerationAgentWebTests(unittest.TestCase):
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
