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


def test_omni_validation_uses_segment_structure_when_model_renames_heading() -> None:
    markdown = """# 商业带货短视频 AI 生成流程规划

## Omni 主结构

# Segment 1：00:00.000 - 00:10.000
## A. 人物造型参考板提示词
本段无人物，不需要生成人物造型参考板。

## B. 故事板图片提示词
生成一张单一全屏故事板。

下面是本段镜头脚本（已过滤字段）：
### 镜头 1 (00:00.000 - 00:10.000)
* **[做什么动作]**：[产品]保持静止。
* **[音频文案]**：无口播
"""

    result = web.omni_output_validation_text(markdown)

    assert result == {"valid": True, "state": "done", "message": "已适配"}


def test_normalize_segmented_markdown_inserts_canonical_heading_once() -> None:
    markdown = """# 生成流程规划

## Omni 主结构

# Segment 1：00:00.000 - 00:10.000
内容
"""

    normalized = web.normalize_segmented_markdown(markdown)

    assert normalized.count("## 每段生成提示词") == 1
    assert normalized.index("## 每段生成提示词") < normalized.index("# Segment 1")
    assert web.normalize_segmented_markdown(normalized) == normalized


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


def test_adaptation_batches_allow_any_total_and_cap_each_batch_at_three() -> None:
    batches = web.split_adaptation_batches(list(range(8)))

    assert [len(batch) for batch in batches] == [3, 3, 2]
    assert web.next_retry_batch_size(3) == 2
    assert web.next_retry_batch_size(2) == 1
    assert web.next_retry_batch_size(1) == 1


def test_openai_adaptation_payload_disables_thinking() -> None:
    payload = web.workflow.build_openai_text_payload("prompt", "deepseek-v4-pro", 32768, "disabled")

    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 32768


def test_run_text_model_caps_adaptation_output_at_32k(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(web.workflow, "get_api_key", lambda _config: "secret")

    def fake_post(_url, _headers, payload, _timeout):
        captured.update(payload)
        return 200, {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(web.workflow, "post_json", fake_post)
    text, _raw, _style = web.workflow.run_text_model(
        "prompt",
        {
            "modelmesh_base_url": "https://api.deepseek.com",
            "script_adaptation_text_model": "deepseek-v4-pro",
            "video_analysis_max_output_tokens": 98304,
        },
        "测试",
    )

    assert text == "ok"
    assert captured["max_tokens"] == 32768
    assert captured["thinking"] == {"type": "disabled"}


def test_prompt_injects_only_current_language_and_compact_product_facts() -> None:
    prompt = web.workflow.build_adaptation_prompt(
        {
            "script_adaptation_prompt": "OMNI ONLY",
            "script_adaptation_target_language": "法语",
            "product_profile": {
                "product_name": "Demo",
                "top_selling_points": "事实A",
                "_说明": "不应发送",
            },
        },
        "# 镜头 1 (00:00.000 - 00:05.000)\n[音频文案] Bonjour",
        "omni",
        10,
        "",
    )

    assert "本次仅使用 法语" in prompt
    assert "事实A" in prompt
    assert "不应发送" not in prompt
    assert "孟加拉语" not in prompt
    assert "马来语" not in prompt


def test_existing_valid_output_reuses_matching_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "output.md"
    source.write_text("source", encoding="utf-8")
    output.write_text("adapted", encoding="utf-8")

    assert web.reusable_adaptation_output(
        output,
        {"valid": True},
        {"status": "completed", "request_fingerprint": "same"},
        "same",
        source.as_posix(),
    )
    assert not web.reusable_adaptation_output(
        output,
        {"valid": True},
        {"status": "completed", "request_fingerprint": "old"},
        "new",
        source.as_posix(),
    )


def test_local_repair_applies_only_exact_replacements() -> None:
    updated = web.apply_repair_replacements(
        "Segment 1\n错误动作\nSegment 2\n保持内容",
        [{"old": "错误动作", "new": "正确动作"}],
    )

    assert updated == "Segment 1\n正确动作\nSegment 2\n保持内容"


def test_repair_request_uses_local_excerpt_and_writes_patch(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "adapted.md"
    path.write_text("开头\n" + ("稳定内容\n" * 2000) + "错误动作\n", encoding="utf-8")
    captured = {}

    def fake_model(prompt, _config, _label):
        captured["prompt"] = prompt
        return '{"replacements":[{"old":"错误动作","new":"正确动作"}]}', {}, "openai"

    monkeypatch.setattr(web.workflow, "run_text_model", fake_model)
    web.repair_adaptation_output(path, {}, "错误动作不符合要求")

    assert len(captured["prompt"]) < len("开头\n" + ("稳定内容\n" * 2000) + "错误动作\n")
    assert path.read_text(encoding="utf-8").endswith("正确动作\n")
