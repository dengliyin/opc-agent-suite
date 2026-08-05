import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "software/Script-Adaptation-app/opc_engine/features/script_adaptation/script_adaptation_agent_web.py"
)
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
