import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).parents[1] / "software/Hybrid-Script-Adaptation-app"
MODULE_PATH = APP_ROOT / "opc_engine/features/script_adaptation/script_adaptation_agent_web.py"
sys.path.insert(0, str(APP_ROOT))
SPEC = importlib.util.spec_from_file_location("script_adaptation_agent_web", MODULE_PATH)
assert SPEC and SPEC.loader
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


def test_status_record_uses_preloaded_log_without_reading_directory(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "P1" / "adapted.md"
    preloaded = {
        "files": {
            "adapted.md": {
                "status": "completed",
                "source_filename": "source.md",
            }
        }
    }

    def unexpected_read(_output_dir: Path):
        raise AssertionError("preloaded status log should be reused")

    monkeypatch.setattr(web, "read_adaptation_status_log", unexpected_read)

    record = web.adaptation_status_record_for_script(
        output_path,
        "source.md",
        "/scripts/source.md",
        status_log=preloaded,
    )

    assert record["status"] == "completed"


class HybridAgentConfigurationTests(unittest.TestCase):
    def test_hybrid_agent_has_independent_identity_and_default_paths(self) -> None:
        settings_path = (
            Path(__file__).parents[1]
            / "software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/agent_config/agent_settings.json"
        )
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        adaptation = settings["adaptation"]

        self.assertEqual(web.DEFAULT_PORT, 9999)
        self.assertIn("钩子与 CTA 脚本适配智能体", web.HTML)
        self.assertEqual(adaptation["script_adaptation_target_model"], "omni")
        self.assertEqual(
            [Path(path).name for path in adaptation["script_adaptation_input_dirs"]],
            ["混剪-钩子", "混剪-CTA"],
        )
        self.assertTrue(
            adaptation["script_adaptation_output_roots"]["omni"].endswith(
                "/wiki/视频/AI实拍混剪/04适配脚本/omni"
            )
        )

    def test_script_library_scans_only_configured_hook_and_cta_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hook_dir = root / "混剪-钩子"
            cta_dir = root / "混剪-CTA"
            unrelated_dir = root / "其他脚本"
            for directory in (hook_dir, cta_dir, unrelated_dir):
                directory.mkdir()
            (hook_dir / "产品A").mkdir()
            (cta_dir / "产品A").mkdir()
            (hook_dir / "产品A" / "hook.md").write_text("# hook\n", encoding="utf-8")
            (cta_dir / "产品A" / "cta.md").write_text("# cta\n", encoding="utf-8")
            (unrelated_dir / "other.md").write_text("# other\n", encoding="utf-8")
            config = {
                "script_adaptation_input_dirs": [str(hook_dir), str(cta_dir)],
                "script_adaptation_output_root": str(root / "outputs"),
                "script_adaptation_target_model": "omni",
                "script_adaptation_segment_seconds": 10,
            }

            with patch.object(web, "load_local_agent_config", return_value=config):
                payload = web.list_product_scripts("omni")

            self.assertEqual(payload["total_count"], 2)
            self.assertEqual(payload["roots"], [str(hook_dir.resolve()), str(cta_dir.resolve())])
            self.assertEqual(
                {product["name"] for product in payload["products"]},
                {"混剪-钩子 / 产品A", "混剪-CTA / 产品A"},
            )

    def test_adaptation_output_preserves_model_type_product_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hook_root = root / "03复刻裂变脚本" / "混剪-钩子"
            script_path = hook_root / "产品A" / "来源脚本A" / "hook.md"
            script_path.parent.mkdir(parents=True)
            script_path.write_text("# hook\n", encoding="utf-8")
            output_root = root / "04适配脚本" / "omni"
            config = {
                "script_adaptation_input_dirs": [str(hook_root)],
                "script_adaptation_output_root": str(output_root),
                "script_adaptation_target_model": "omni",
            }
            classification = web.hybrid_script_classification(script_path, config)
            config["script_adaptation_output_relative_dir"] = classification["relative_dir"]

            output_dir = web.workflow.output_dir_for_stage("adapt", config, script_path)

            self.assertEqual(
                output_dir,
                output_root.resolve() / "混剪-钩子" / "产品A" / "来源脚本A",
            )
