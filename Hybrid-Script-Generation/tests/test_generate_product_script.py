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
    def test_unreadable_mistake_book_is_treated_as_missing(self):
        knowledge_dir = Path("/tmp/mistake-books")
        mistake_book = knowledge_dir / "product.md"
        with (
            patch.object(generate_product_script, "resolve_content_knowledge_path", return_value=knowledge_dir),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(generate_product_script, "product_mistake_book_file", return_value=mistake_book),
            patch.object(generate_product_script, "read_text_file", side_effect=PermissionError("denied")),
        ):
            self.assertEqual(generate_product_script.get_content_knowledge_base({}), "")

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

    def test_stale_explicit_duration_cannot_override_reference_timeline(self):
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

        self.assertIn("### 镜头 1 (00:00.000 - 00:01.000)", corrected)
        self.assertIn("### 镜头 2 (00:01.000 - 00:04.000)", corrected)
        self.assertEqual(len(warnings), 1)
        self.assertIn("已按参考稿恢复", warnings[0])

    def test_multiple_mutations_are_validated_and_saved_independently(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 2 (00:01.000 - 00:03.000)
"""
        variant_one = """### 变体 #1
### 镜头 1 (00:00.000 - 00:02.000)
第一条
### 镜头 2 (00:02.000 - 00:04.000)
"""
        variant_two = """### 变体 #2
### 镜头 1 (00:00.000 - 00:02.000)
第二条
### 镜头 2 (00:02.000 - 00:04.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }
            raw_response = {
                "final_stage": "mutation_rewrite",
                "mutation_rewrite_raw": {
                    "mutation_variants": [variant_one, variant_two],
                    "mutation_variant_numbers": [1, 2],
                },
            }

            with patch.object(
                generate_product_script,
                "enforce_output_timeline",
                wraps=generate_product_script.enforce_output_timeline,
            ) as enforce_timeline:
                output_paths, raw_paths = generate_product_script.write_script_outputs(
                    config,
                    str(root / "outputs"),
                    f"{variant_one}\n\n{variant_two}",
                    raw_response,
                )

            self.assertEqual(len(output_paths), 2)
            self.assertEqual(len(raw_paths), 2)
            self.assertEqual(enforce_timeline.call_count, 2)
            first_text = output_paths[0].read_text(encoding="utf-8")
            second_text = output_paths[1].read_text(encoding="utf-8")
            self.assertIn("第一条", first_text)
            self.assertNotIn("第二条", first_text)
            self.assertIn("第二条", second_text)
            self.assertNotIn("第一条", second_text)
            for saved_text in (first_text, second_text):
                self.assertIn("镜头 1 (00:00.000 - 00:01.000)", saved_text)
                self.assertIn("镜头 2 (00:01.000 - 00:03.000)", saved_text)

    def test_clone_is_timeline_validated_once(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
### 镜头 2 (00:01.000 - 00:03.000)
"""
        clone = """### 镜头 1 (00:00.000 - 00:02.000)
### 镜头 2 (00:02.000 - 00:04.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }
            with patch.object(
                generate_product_script,
                "enforce_output_timeline",
                wraps=generate_product_script.enforce_output_timeline,
            ) as enforce_timeline:
                output_paths, _raw_paths = generate_product_script.write_script_outputs(
                    config,
                    str(root / "outputs"),
                    clone,
                    {},
                )

            self.assertEqual(len(output_paths), 1)
            self.assertEqual(enforce_timeline.call_count, 1)

    def test_recloning_overwrites_existing_clone_and_raw_response(self):
        reference = """### 镜头 1 (00:00.000 - 00:01.000)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "outputs"
            reference_path = root / "VN-author-1234567890123456789.md"
            reference_path.write_text(reference, encoding="utf-8")
            config = {
                "script_reference_script_path": str(reference_path),
                "script_product_document_path": str(root / "SIMC01-SIMC染发棒-产品信息.md"),
            }

            first_paths, first_raw_paths = generate_product_script.write_script_outputs(
                config,
                str(output_dir),
                "### 镜头 1 (00:00.000 - 00:01.000)\n第一次复刻",
                {"generation_marker": "first"},
            )
            second_paths, second_raw_paths = generate_product_script.write_script_outputs(
                config,
                str(output_dir),
                "### 镜头 1 (00:00.000 - 00:01.000)\n第二次复刻",
                {"generation_marker": "second"},
            )

            self.assertEqual(second_paths, first_paths)
            self.assertEqual(second_raw_paths, first_raw_paths)
            self.assertIn("第二次复刻", second_paths[0].read_text(encoding="utf-8"))
            self.assertNotIn("第一次复刻", second_paths[0].read_text(encoding="utf-8"))
            raw_payload = json.loads(second_raw_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(raw_payload["generation_marker"], "second")
            self.assertEqual(len(list(output_dir.glob("复刻-*.md"))), 1)
            self.assertEqual(len(list(output_dir.glob("复刻-*.raw.json"))), 1)

    def test_vietnam_and_philippines_country_defaults(self):
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["越南"], "越南语")
        self.assertEqual(generate_product_script.COUNTRY_DEFAULT_LANGUAGE["菲律宾"], "菲律宾语")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["越南"], "VN")
        self.assertEqual(generate_product_script.COUNTRY_FILENAME_CODE["菲律宾"], "PH")

    def test_generation_prompt_keeps_hook_and_cta_tasks_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for material_type, expected, forbidden in (
                ("混剪-钩子", "只复刻开头钩子片段", "不得补写中段产品介绍或结尾 CTA"),
                ("混剪-CTA", "只复刻结尾 CTA 片段", "不得补写开头钩子或中段产品介绍"),
            ):
                reference = root / material_type / "产品A" / "source.md"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text("### 镜头 1 (00:00.000 - 00:02.000)\n参考", encoding="utf-8")
                config = {
                    "script_reference_analysis_path": str(reference),
                    "script_reference_kind": "竞品视频拆解结果",
                    "script_hybrid_material_type": material_type,
                    "script_country": "不改变原脚本",
                    "script_target_language": "不改变原脚本",
                }
                with (
                    patch.object(generate_product_script, "get_product_manual", return_value="产品资料"),
                    patch.object(generate_product_script, "get_content_knowledge_base", return_value=""),
                ):
                    prompt = generate_product_script.build_generation_prompt(config)

                self.assertIn(expected, prompt)
                self.assertIn(forbidden, prompt)

    def test_local_model_settings_override_shared_defaults(self):
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

        self.assertEqual(config["modelmesh_base_url"], "https://stale.test")
        self.assertEqual(config["script_generation_model"], "shared-model")
        self.assertEqual(config["modelmesh_api_key"], "secret")

    def test_legacy_local_configs_migrate_to_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_inputs = root / "legacy" / "inputs.json"
            legacy_model = root / "legacy" / "model_settings.json"
            runtime_inputs = root / "runtime" / "inputs.json"
            runtime_model = root / "runtime" / "model_settings.json"
            legacy_inputs.parent.mkdir()
            legacy_inputs.write_text(json.dumps({"script_country": "美国"}), encoding="utf-8")
            legacy_model.write_text(json.dumps({"modelmesh_api_key": "secret"}), encoding="utf-8")

            with (
                patch.object(generate_product_script, "LEGACY_LOCAL_INPUTS_PATH", legacy_inputs),
                patch.object(generate_product_script, "LEGACY_LOCAL_MODEL_SETTINGS_PATH", legacy_model),
                patch.object(generate_product_script, "LOCAL_INPUTS_PATH", runtime_inputs),
                patch.object(generate_product_script, "LOCAL_MODEL_SETTINGS_PATH", runtime_model),
            ):
                migrated = generate_product_script.migrate_legacy_local_configs()

            self.assertEqual(migrated, [runtime_inputs, runtime_model])
            self.assertEqual(json.loads(runtime_inputs.read_text(encoding="utf-8"))["script_country"], "美国")
            self.assertEqual(json.loads(runtime_model.read_text(encoding="utf-8"))["modelmesh_api_key"], "secret")
            self.assertEqual(runtime_inputs.stat().st_mode & 0o777, 0o600)
            self.assertEqual(runtime_model.stat().st_mode & 0o777, 0o600)

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
