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


def test_runtime_input_path_is_short_and_does_not_change_output_name(monkeypatch, tmp_path: Path) -> None:
    long_filename = (
        "裂变-DRN-E99Pro无人机-IE-patriciashopscreator二创-"
        "7658502767283047698_019.md"
    )
    script = {
        "filename": long_filename,
        "source_path": f"F:/Obsidian Vault/wiki/视频/纯AI视频/03产品脚本/{long_filename}",
        "adaptation_batch_key": "20260809-204823-DRN-E99Pro无人机-mixedsource-omni-001",
    }
    monkeypatch.setattr(web, "product_project_root", lambda _config: tmp_path)

    runtime_path = web.adaptation_runtime_input_path({}, script, "omni")

    assert runtime_path.name == "input.md"
    assert runtime_path.parent.parent.name == "adaptation_jobs"
    assert len(runtime_path.parent.name) == 16
    assert web.adaptation_output_stem({}, long_filename, "omni") == f"omni-{Path(long_filename).stem}"


def test_runtime_id_is_stable_and_separates_parallel_tasks() -> None:
    base_script = {
        "filename": "裂变-product-IE-author-7658502767283047698_019.md",
        "source_path": "F:/scripts/裂变-product-IE-author-7658502767283047698_019.md",
        "adaptation_batch_key": "batch-001",
    }

    first = web.adaptation_runtime_id(base_script, "omni")
    retry = web.adaptation_runtime_id(dict(base_script), "omni")
    other_model = web.adaptation_runtime_id(base_script, "veo")
    other_batch = web.adaptation_runtime_id({**base_script, "adaptation_batch_key": "batch-002"}, "omni")

    assert first == retry
    assert first != other_model
    assert first != other_batch


def test_cached_catalog_does_not_scan_until_refresh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPC_SCAN_INDEX_ROOT", str(tmp_path))
    monkeypatch.setattr(web, "script_library_root", lambda _config: tmp_path / "scripts")
    monkeypatch.setattr(web, "load_local_agent_config", lambda: {})
    calls = []
    monkeypatch.setattr(web, "list_product_scripts", lambda _target: calls.append("scan") or {"products": []})

    cached = web.cached_product_scripts("omni")
    refreshed = web.cached_product_scripts("omni", refresh=True)

    assert cached["scan_index"]["ready"] is False
    assert refreshed["scan_index"]["ready"] is True
    assert calls == ["scan"]


def test_incremental_scan_reuses_unchanged_adapted_script(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "scripts"
    product = root / "P1"
    product.mkdir(parents=True)
    cold = product / "cold.md"
    hot = product / "hot.md"
    cold.write_text("cold", encoding="utf-8")
    hot.write_text("hot", encoding="utf-8")
    previous_cold = {
        "name": cold.name,
        "path": cold.as_posix(),
        "product": "P1",
        "adapted": True,
        "adaptation_state": "done",
        "scan_key": cold.as_posix(),
        "scan_signature": "cold.md:signature",
        "temperature": "cold",
    }
    previous_hot = {
        "name": hot.name,
        "path": hot.as_posix(),
        "product": "P1",
        "adapted": False,
        "adaptation_state": "todo",
        "scan_key": hot.as_posix(),
        "scan_signature": "hot.md:signature",
        "temperature": "hot",
    }
    built = []
    monkeypatch.setattr(web, "load_local_agent_config", lambda: {})
    monkeypatch.setattr(web, "script_library_root", lambda _config: root)
    monkeypatch.setattr(web, "script_scan_signature", lambda path, _config: f"{path.name}:signature")
    monkeypatch.setattr(
        web,
        "load_snapshot",
        lambda *_args: {
            "payload": {
                "scan_state": {"schema_version": 2},
                "products": [{"scripts": [previous_cold, previous_hot]}],
            }
        },
    )
    monkeypatch.setattr(
        web,
        "indexed_script_file_payload",
        lambda path, *_args: built.append(path.name)
        or {
            "name": path.name,
            "path": path.as_posix(),
            "product": "P1",
            "adapted": path.name == "hot.md",
            "adaptation_state": "done",
            "batch_id": "b1",
        },
    )

    payload = web.list_product_scripts_incremental("omni")

    assert built == ["hot.md"]
    assert payload["scan_state"]["cold_reused"] == 1
    assert payload["scan_state"]["scanned"] == 1
    assert payload["adapted_count"] == 2
