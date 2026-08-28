from __future__ import annotations

import json
from pathlib import Path

import pytest

from opc_engine.features.unified_script_agent import core


VALID_OMNI = """#
## 每段生成提示词

---

# Segment 1：00:00.000 - 00:10.000

## A. 人物造型参考板提示词

角色ID：character_01

生成方式：首次生成

参考来源：无

本段首次生成 character_01 的人物造型参考板。

## B. 故事板图片提示词

下面是本段镜头脚本（已过滤字段）:

### 镜头 1 (00:00.000 - 00:10.000)

- [主体] character_01
- [在场景中] 普通住宅客厅
- [做什么动作] 展示图1中的该产品
- [镜头语言] 中景固定镜头
- [光线] 自然窗光
- [细节] 动作清晰稳定
- [画面风格/氛围] 真实生活化
- [音频文案] No more waiting.
"""


def configure_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    vault = tmp_path / "vault"
    pure_source = vault / "wiki/视频/纯AI视频/02参考脚本"
    pure_output = vault / "wiki/视频/纯AI视频/04适配脚本/omni"
    hybrid_source = vault / "wiki/视频/AI实拍混剪/02解析脚本"
    hybrid_output = vault / "wiki/视频/AI实拍混剪/04适配脚本/omni"
    product_info = vault / "wiki/产品/产品信息"
    mistake = vault / "wiki/视频/共享知识库/脚本错题本"
    data = tmp_path / "config/unified-script-agent"
    for path in (pure_source, pure_output, hybrid_source, hybrid_output, product_info, mistake, data):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPC_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VIDEO_TEARDOWN_OUTPUT_ROOT", str(pure_source))
    monkeypatch.setenv("SCRIPT_ROOT", str(pure_output))
    monkeypatch.setenv("HYBRID_SCRIPT_GENERATION_INPUT_ROOT", str(hybrid_source))
    monkeypatch.setenv("HYBRID_OMNI_SCRIPT_ROOT", str(hybrid_output))
    monkeypatch.setenv("PRODUCT_INFO_ROOT", str(product_info))
    monkeypatch.setenv("SCRIPT_MISTAKE_BOOK_ROOT", str(mistake))
    monkeypatch.setenv("UNIFIED_SCRIPT_AGENT_DATA_ROOT", str(data))
    return {
        "pure_source": pure_source,
        "pure_output": pure_output,
        "hybrid_source": hybrid_source,
        "hybrid_output": hybrid_output,
        "product_info": product_info,
        "mistake": mistake,
        "data": data,
    }


def test_prompt_assembly_uses_only_reviewed_omni_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("### 镜头 1 (00:00.000 - 00:10.000)", encoding="utf-8")
    payload = {
        "route": "route2",
        "mode": "mutation",
        "model": "omni",
        "source_path": str(source),
        "source_product": "P1",
        "target_product": "P2",
        "target_market": "US",
        "target_language": "英语（美式）",
        "variant_count": 2,
        "content_type": "纯AI",
    }

    prompt = core.assemble_prompt(payload, "SOURCE", "FACT", "LESSON", variant_number=7)

    assert "## 公共规则 COMMON" in prompt
    assert "## 产品改写规则 PRODUCT_REWRITE" in prompt
    assert "## 复刻规则 CLONE" in prompt
    assert "## 裂变规则 MUTATION" in prompt
    assert "## Omni 模型规则 MODEL_OMNI" in prompt
    assert "## Grok 模型规则 MODEL_GROK" not in prompt
    assert "## Veo 模型规则 MODEL_VEO" not in prompt
    assert "<SOURCE_SCRIPT>\nSOURCE\n</SOURCE_SCRIPT>" in prompt
    assert "- `VARIANT_NUMBER`：7" in prompt
    assert "ADAPTATION_NOTES" not in prompt


def test_page_has_no_task_notes_field() -> None:
    static_root = Path(core.__file__).parent / "static"
    index_html = (static_root / "index.html").read_text(encoding="utf-8")
    assert "补充说明" not in index_html
    assert 'class="routeLayout"' in index_html
    assert "参考脚本 → 复刻或裂变" not in index_html
    assert "钩子或 CTA 解析脚本" not in index_html
    assert 'id="sourceStatus"' in index_html
    assert 'class="panel jobsPanel idle"' in index_html
    assert 'id="autoProduct"' in index_html
    assert 'id="targetProductField"' in index_html
    app_js = (static_root / "app.js").read_text(encoding="utf-8")
    assert "notes:" not in app_js
    assert "counts?.pure" not in app_js
    assert "裂变 ${Number(status.mutation_count||0)} 次" in app_js
    assert "pathRow" in app_js
    assert "refreshedJobs" in app_js
    assert "route()==='route1'?source.product" in app_js


def test_omni_contract_validator_accepts_exact_downstream_format() -> None:
    assert core.validate_omni_markdown(VALID_OMNI) == []


def test_omni_contract_validator_rejects_missing_eight_field() -> None:
    broken = VALID_OMNI.replace("- [细节] 动作清晰稳定\n", "")
    issues = core.validate_omni_markdown(broken)
    assert any("恰好按顺序包含 8 个字段" in issue for issue in issues)


def test_route3_writes_directly_to_hybrid_omni_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["hybrid_source"] / "混剪-钩子" / "P1" / "ES-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = core.validate_task_payload(
        {
            "route": "route3",
            "mode": "clone",
            "model": "omni",
            "source_path": str(source),
            "target_product": "",
            "target_market": "ES",
            "target_language": "西班牙语",
        }
    )

    output = core.output_path_for(payload)

    assert output.parent == paths["hybrid_output"] / "混剪-钩子" / "P1" / source.stem
    assert output.name == "omni-复刻-P1-ES-author-1234567890123.md"
    assert payload["use_product_info"] is False


def test_route1_always_uses_source_product_without_target_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "ES-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# P1", encoding="utf-8")

    payload = core.validate_task_payload(
        {
            "route": "route1",
            "mode": "clone",
            "model": "omni",
            "source_path": str(source),
            "target_product": "WRONG",
            "target_market": "ES",
            "target_language": "西班牙语",
        }
    )

    assert payload["target_product"] == "P1"
    assert payload["use_product_info"] is True


def test_run_task_saves_only_final_adapted_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("### 镜头 1 (00:00.000 - 00:10.000)\n- [音频文案] Hello", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# 产品信息\n- 产品名：P1", encoding="utf-8")
    (paths["mistake"] / "P1.md").write_text("# P1 错题本\n- 保持动作方向", encoding="utf-8")
    monkeypatch.setattr(core, "_call_model", lambda *_args, **_kwargs: VALID_OMNI)

    result = core.run_task(
        {
            "route": "route1",
            "mode": "clone",
            "model": "omni",
            "source_path": str(source),
            "target_product": "P1",
            "target_market": "US",
            "target_language": "英语（美式）",
        }
    )

    output = Path(result["outputs"][0]["path"])
    assert output.is_file()
    assert output.parent == paths["pure_output"] / "P1"
    assert output.read_text(encoding="utf-8").startswith("#\n## 每段生成提示词")
    assert not (paths["pure_output"].parent.parent / "03产品脚本").exists()


def test_mutation_sequence_survives_deleted_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# 产品信息\nP1", encoding="utf-8")
    payload = core.validate_task_payload(
        {
            "route": "route1",
            "mode": "mutation",
            "model": "omni",
            "source_path": str(source),
            "target_product": "P1",
            "target_market": "US",
            "target_language": "英语（美式）",
            "variant_count": 2,
        }
    )

    assert core.reserve_mutation_numbers(payload, 2) == [1, 2]
    assert core.reserve_mutation_numbers(payload, 2) == [3, 4]
    history = json.loads((paths["data"] / "mutation_history.json").read_text(encoding="utf-8"))
    assert list(history.values()) == [4]


def test_catalog_restores_legacy_clone_and_mutation_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "ES-author-1234567890123456789-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    legacy_root = paths["pure_output"].parent.parent / "03产品脚本" / "P1"
    legacy_root.mkdir(parents=True)
    (legacy_root / "复刻-P1-IE-author-1234567890123456789.raw.json").write_text("{}", encoding="utf-8")
    (legacy_root / "裂变-P1-IE-author-1234567890123456789_001.raw.json").write_text("{}", encoding="utf-8")
    (legacy_root / "裂变-P1-IE-author-1234567890123456789_001.md").write_text("old", encoding="utf-8")
    (paths["pure_output"] / "P1").mkdir(parents=True)
    (paths["pure_output"] / "P1" / "omni-裂变-P1-IE-author-1234567890123456789_001.md").write_text(
        "adapted", encoding="utf-8"
    )

    item = core.build_catalog()["sources"][0]

    assert item["status"] == {"cloned": True, "mutation_count": 1}


def test_catalog_separates_sources_that_share_a_video_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    product_root = paths["pure_source"] / "P1"
    product_root.mkdir(parents=True)
    (product_root / "ES-author-1234567890123456789-demo.md").write_text("source", encoding="utf-8")
    (product_root / "ES-author二创-1234567890123456789-demo.md").write_text("source", encoding="utf-8")
    legacy_root = paths["pure_output"].parent.parent / "03产品脚本" / "P1"
    legacy_root.mkdir(parents=True)
    (legacy_root / "裂变-P1-IE-author二创-1234567890123456789.md").write_text("mutation", encoding="utf-8")

    by_name = {item["name"]: item["status"] for item in core.build_catalog()["sources"]}

    assert by_name["ES-author-1234567890123456789-demo.md"]["mutation_count"] == 0
    assert by_name["ES-author二创-1234567890123456789-demo.md"]["mutation_count"] == 1


def test_runtime_history_keeps_status_after_outputs_are_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123456789-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = {
        "route": "route1",
        "mode": "mutation",
        "model": "omni",
        "source_path": str(source),
        "source_product": "P1",
        "target_product": "P1",
        "target_market": "US",
        "target_language": "英语（美式）",
        "variant_count": 3,
        "content_type": "纯AI",
    }
    core.reserve_mutation_numbers(payload, 3)
    core._record_clone(payload)

    catalog = core._catalog_with_runtime_history(core.build_catalog())

    assert catalog["sources"][0]["status"] == {"cloned": True, "mutation_count": 3}
