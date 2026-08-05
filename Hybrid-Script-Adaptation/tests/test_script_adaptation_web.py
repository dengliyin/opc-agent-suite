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
from opc_engine.features.script_adaptation import script_adaptation_agent as agent

SPEC = importlib.util.spec_from_file_location("script_adaptation_agent_web", MODULE_PATH)
assert SPEC and SPEC.loader
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


def test_omni_validation_accepts_level_one_simple_structure_heading() -> None:
    markdown = """# 每段生成提示词

# Segment 1：00:00.000 - 00:10.000
## A. 人物造型参考板提示词
本段无人物，不需要生成人物造型参考板。

## B. 故事板图片提示词
生成一张单一全屏故事板。

下面是我的完整脚本：
### 镜头 1 (00:00.000 - 00:10.000)
* **[做什么动作]**：[产品]保持静止。
* **[音频文案]**：无口播
"""

    result = web.omni_output_validation_text(markdown)

    assert result == {"valid": True, "state": "done", "message": "已适配"}


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
    def test_vault_root_is_required_when_process_environment_is_missing(self) -> None:
        with patch.dict(agent.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPC_VAULT_ROOT 未配置"):
                agent.ensure_vault_root_environment()

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

    def test_fixed_duration_models_receive_exact_black_silent_padding_plan(self) -> None:
        source_text = "### 镜头 1 (00:00.000 - 00:07.500)\n\n* **[做什么动作]** 保持原动作。\n"

        omni_note = web.workflow.fixed_duration_padding_note(source_text, "omni", 10)
        veo_note = web.workflow.fixed_duration_padding_note(source_text, "veo", 8)
        grok_note = web.workflow.fixed_duration_padding_note(source_text, "grok", 30)

        self.assertIn("- 本段有效内容时长：7.500秒", omni_note)
        self.assertIn("- 技术占位时长：2.500秒", omni_note)
        self.assertIn("- 模型片段时长：10.000秒", omni_note)
        self.assertIn("- 技术占位时长：0.500秒", veo_note)
        self.assertEqual(grok_note, "")

    def test_padding_validation_rejects_missing_or_incorrect_machine_fields(self) -> None:
        source_text = "### 镜头 1 (00:00.000 - 00:07.500)\n"
        valid_padding = """
- 原脚本总时长：7.500秒
- 本段有效内容时长：7.500秒
- 有效内容结束：7.500秒
- 技术占位开始：7.500秒
- 技术占位时长：2.500秒
- 模型片段时长：10.000秒
[TECHNICAL_PADDING: BLACK_SILENT]
技术占位为纯黑画面、完全静音、无人物、无产品、无字幕、无贴纸、无动作、无转场内容。
"""

        self.assertEqual(
            web.fixed_duration_padding_issues(valid_padding, source_text, "omni", 10),
            [],
        )
        issues = web.fixed_duration_padding_issues(
            valid_padding.replace("2.500秒", "3.000秒", 1),
            source_text,
            "omni",
            10,
        )
        self.assertTrue(any("技术占位时长应为 2.500秒" in issue for issue in issues))

    def test_no_padding_is_allowed_when_source_exactly_fills_segment(self) -> None:
        source_text = "### 镜头 1 (00:00.000 - 00:10.000)\n"

        self.assertEqual(
            web.fixed_duration_padding_issues("", source_text, "omni", 10),
            [],
        )
        self.assertTrue(
            web.fixed_duration_padding_issues(
                "[TECHNICAL_PADDING: BLACK_SILENT]",
                source_text,
                "omni",
                10,
            )
        )

    def test_omni_machine_structure_is_added_deterministically(self) -> None:
        source_text = "### 镜头 1 (00:00.000 - 00:07.500)\n"
        model_output = """
# Segment 1：00:00.000 - 00:07.500
- 技术占位时长：3.000秒
[TECHNICAL_PADDING: BLACK_SILENT]

## A. 人物造型参考板提示词
本段为产品特写段落，无人物主体，不需要生成人物造型参考板。

## B. 故事板图片提示词
下面是本段镜头脚本（已过滤字段）:
### 镜头 1 (00:00.000 - 00:07.500)
"""

        normalized = web.workflow.normalize_omni_machine_structure(
            model_output,
            source_text,
            10,
        )

        self.assertIn("## 每段生成提示词", normalized)
        self.assertEqual(normalized.count("[TECHNICAL_PADDING: BLACK_SILENT]"), 1)
        self.assertIn("- 技术占位时长：2.500秒", normalized)
        self.assertNotIn("- 技术占位时长：3.000秒", normalized)
        self.assertIn("技术占位为纯黑画面、完全静音", normalized)
        self.assertEqual(
            web.fixed_duration_padding_issues(normalized, source_text, "omni", 10),
            [],
        )

    def test_validation_failure_message_becomes_retry_feedback(self) -> None:
        message = (
            "输出质检未通过：缺少 ## 每段生成提示词；"
            "失败产物已隔离: /tmp/failed.md.txt"
        )

        self.assertEqual(
            web.validation_retry_feedback(message),
            "缺少 ## 每段生成提示词",
        )
        self.assertEqual(web.validation_retry_feedback("HTTP 500"), "")
