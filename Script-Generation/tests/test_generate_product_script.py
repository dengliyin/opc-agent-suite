#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opc_engine.features.script_generation import generate_product_script


class GenerateProductScriptTests(unittest.TestCase):
    def test_preserved_duration_restores_each_reference_shot_timecode(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):

内容

镜头 2 (00:01.000 - 00:02.500):

内容
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)

新内容

### 镜头 2 (00:02.000 - 00:04.000)

新内容
"""

        corrected, warnings = generate_product_script.enforce_output_timeline(
            {"script_total_duration": "不改变原脚本"},
            reference,
            generated,
        )

        self.assertIn("### 镜头 1 (00:00.000 - 00:01.000)", corrected)
        self.assertIn("### 镜头 2 (00:01.000 - 00:02.500)", corrected)
        self.assertEqual(len(warnings), 1)
        self.assertIn("已修正 2 个镜头", warnings[0])

    def test_preserved_duration_rejects_changed_shot_structure(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):
镜头 2 (00:01.000 - 00:02.500):
"""
        generated = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 3 (00:01.000 - 00:02.500)
"""

        with self.assertRaisesRegex(ValueError, "镜头编号或数量与参考稿不一致"):
            generate_product_script.enforce_output_timeline(
                {"script_total_duration": "不改变原脚本"},
                reference,
                generated,
            )

    def test_explicit_duration_scales_reference_timeline_not_model_timeline(self):
        reference = """镜头 1 (00:00.000 - 00:01.000):
镜头 2 (00:01.000 - 00:04.000):
"""
        generated = """### 镜头 1 (00:00.000 - 00:02.000)
### 镜头 2 (00:02.000 - 00:04.000)
"""

        corrected, warnings = generate_product_script.enforce_output_timeline(
            {"script_total_duration": "8秒"},
            reference,
            generated,
        )

        self.assertIn("### 镜头 1 (00:00.000 - 00:02.000)", corrected)
        self.assertIn("### 镜头 2 (00:02.000 - 00:08.000)", corrected)
        self.assertEqual(len(warnings), 1)
        self.assertIn("已按参考稿时间比例重算", warnings[0])

    def test_vietnam_and_philippines_country_defaults(self):
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["越南"], "越南语")
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["菲律宾"], "菲律宾语")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["越南"], "VN")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["菲律宾"], "PH")

    def test_shared_model_settings_override_stale_local_values_except_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shared = root / "model_defaults.json"
            local = root / "model_settings.json"
            inputs = root / "inputs.json"
            shared.write_text(
                json.dumps({"modelmesh_base_url": "https://shared.test", "script_generation_model": "shared-model"}),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps({"modelmesh_api_key": "secret", "modelmesh_base_url": "https://stale.test"}),
                encoding="utf-8",
            )
            inputs.write_text("{}", encoding="utf-8")

            with (
                patch.object(generate_product_script, "SHARED_MODEL_SETTINGS_PATH", shared),
                patch.object(generate_product_script, "LOCAL_MODEL_SETTINGS_PATH", local),
                patch.object(generate_product_script, "SCRIPT_INPUTS_PATH", inputs),
            ):
                config = generate_product_script.load_script_generation_config()

        self.assertEqual(config["modelmesh_base_url"], "https://shared.test")
        self.assertEqual(config["script_generation_model"], "shared-model")
        self.assertEqual(config["modelmesh_api_key"], "secret")

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
