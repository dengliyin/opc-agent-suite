#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opc_engine.features.script_generation import generate_product_script


class GenerateProductScriptTests(unittest.TestCase):
    def test_vietnam_and_philippines_country_defaults(self):
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["越南"], "越南语")
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["菲律宾"], "菲律宾语")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["越南"], "VN")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["菲律宾"], "PH")

    def test_main_creates_explicit_product_output_dir_without_saved_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "JR01-天然矿石戒指"
            args = argparse.Namespace(
                product_doc=str(Path(temp_dir) / "JR01-天然矿石戒指-产品信息.md"),
                output_dir=str(output_dir),
                dry_run=False,
            )

            def run_pipeline(_config, _args):
                self.assertTrue(output_dir.is_dir())
                return "script", {}, "endpoint", "field"

            with (
                patch.object(generate_product_script, "parse_args", return_value=args),
                patch.object(generate_product_script, "load_script_generation_config", return_value={}),
                patch.object(generate_product_script, "apply_cli_overrides", return_value={"script_product_document_path": args.product_doc}),
                patch.object(generate_product_script, "product_project_ready", return_value=False),
                patch.object(generate_product_script, "require_product_project") as require_project,
                patch.object(generate_product_script, "run_script_pipeline", side_effect=run_pipeline),
                patch.object(generate_product_script, "write_script_outputs", return_value=([], [])),
            ):
                generate_product_script.main()

            require_project.assert_not_called()


if __name__ == "__main__":
    unittest.main()
