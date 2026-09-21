from __future__ import annotations

import json
import re
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
- [做什么动作] 展示[产品]
- [镜头语言] 中景固定镜头
- [光线] 自然窗光
- [细节] 动作清晰稳定
- [画面风格/氛围] 真实生活化
- [音频文案] No more waiting.
- [背景音乐] 无
"""

VALID_SEEDANCE = """#
## 每段生成提示词

---

# Segment 1：00:00.000–00:12.000

## A. 人物造型参考板提示词

角色ID：character_01

生成方式：首次生成

参考来源：无

本段首次生成 character_01 的人物造型参考板。

## B. 故事板图片提示词

生成一张竖版 9:16 的逐镜头分镜故事板执行单。

### 01｜等待承诺

**画面内容：**
character_01 在卧室展示空无一物的无名指。

**动作/景别：**
中景，抬起右手并在结束时保持展示。

**构图：**
人物居中，面部和右手同时清晰。

**拍摄方式：**
正面固定机位，真实手机拍摄。

**声音：**
轻微室内环境声和无版权 Lo-fi 音乐。

**台词：**
无口播。

**时间：**
00:00.000–00:03.000｜3.0秒

---

### 02｜展示产品

**画面内容：**
character_01 在明亮房间展示无名指上的 [产品]。

**动作/景别：**
中特写，缓慢抬手并在结束时停在脸旁。

**构图：**
人物面部、右手和 [产品] 同时清晰。

**拍摄方式：**
正面拍摄，轻微手持晃动。

**声音：**
自然室内环境声和无版权温馨音乐。

**台词：**
无口播。

**时间：**
00:03.000–00:12.000｜9.0秒
"""


def seedance_with_inline_fields() -> str:
    markdown = VALID_SEEDANCE
    for field in core.SEEDANCE_FIELDS:
        markdown = re.sub(
            rf"\*\*{re.escape(field)}：\*\*\n([^\n]+)",
            lambda match, name=field: f"- **{name}**： {match.group(1)}",
            markdown,
        )
    return markdown


def seedance_with_spoken_line(delivery: str) -> str:
    return VALID_SEEDANCE.replace(
        "中景，抬起右手并在结束时保持展示。",
        f"中景，抬起右手并在结束时保持展示。{delivery}",
        1,
    ).replace("**台词：**\n无口播。", "**台词：**\nTell me now.", 1)


def configure_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    vault = tmp_path / "vault"
    pure_source = vault / "wiki/视频/纯AI视频/02参考脚本"
    pure_output = vault / "wiki/视频/纯AI视频/04适配脚本/omni"
    pure_seedance_output = vault / "wiki/视频/纯AI视频/04适配脚本/seedance"
    hybrid_source = vault / "wiki/视频/AI实拍混剪/02解析脚本"
    hybrid_output = vault / "wiki/视频/AI实拍混剪/04适配脚本/omni"
    hybrid_seedance_output = vault / "wiki/视频/AI实拍混剪/04适配脚本/seedance"
    product_info = vault / "wiki/产品/产品信息"
    mistake = vault / "wiki/视频/共享知识库/脚本错题本"
    data = tmp_path / "config/unified-script-agent"
    for path in (
        pure_source,
        pure_output,
        pure_seedance_output,
        hybrid_source,
        hybrid_output,
        hybrid_seedance_output,
        product_info,
        mistake,
        data,
    ):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPC_VAULT_ROOT", str(vault))
    monkeypatch.setenv("VIDEO_TEARDOWN_OUTPUT_ROOT", str(pure_source))
    monkeypatch.setenv("SCRIPT_ROOT", str(pure_output))
    monkeypatch.setenv("SEEDANCE_SCRIPT_ROOT", str(pure_seedance_output))
    monkeypatch.setenv("HYBRID_SCRIPT_GENERATION_INPUT_ROOT", str(hybrid_source))
    monkeypatch.setenv("HYBRID_OMNI_SCRIPT_ROOT", str(hybrid_output))
    monkeypatch.setenv("HYBRID_SEEDANCE_SCRIPT_ROOT", str(hybrid_seedance_output))
    monkeypatch.setenv("PRODUCT_INFO_ROOT", str(product_info))
    monkeypatch.setenv("SCRIPT_MISTAKE_BOOK_ROOT", str(mistake))
    monkeypatch.setenv("UNIFIED_SCRIPT_AGENT_DATA_ROOT", str(data))
    return {
        "pure_source": pure_source,
        "pure_output": pure_output,
        "pure_seedance_output": pure_seedance_output,
        "hybrid_source": hybrid_source,
        "hybrid_output": hybrid_output,
        "hybrid_seedance_output": hybrid_seedance_output,
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
    assert "## Seedance 模型规则 MODEL_SEEDANCE" not in prompt
    assert "## Grok 模型规则 MODEL_GROK" not in prompt
    assert "## Veo 模型规则 MODEL_VEO" not in prompt
    assert "最终镜头的任何字段都不得描述产品颜色" in prompt
    assert "[细节]` 也不得例外" in prompt
    assert "来源脚本里的旧产品颜色、形状、包装、标签" in prompt
    assert "<SOURCE_SCRIPT>\nSOURCE\n</SOURCE_SCRIPT>" in prompt
    assert "- `VARIANT_NUMBER`：7" in prompt
    assert "ADAPTATION_NOTES" not in prompt
    assert "## Omni 最终输出硬性约束" in prompt
    assert "真实直观的产品使用演示" in prompt
    assert prompt.index("</SOURCE_SCRIPT>") < prompt.index("## Omni 最终输出硬性约束")
    assert prompt.rstrip().endswith("不要输出自检报告、解释或代码围栏。")


def test_prompt_assembly_adds_only_seedance_model_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("### 镜头 1 (00:00.000 - 00:12.000)", encoding="utf-8")
    payload = {
        "route": "route1",
        "mode": "clone",
        "model": "seedance",
        "source_path": str(source),
        "source_product": "P1",
        "target_product": "P1",
        "target_market": "US",
        "target_language": "英语（美式）",
        "variant_count": 1,
        "content_type": "纯AI",
    }

    prompt = core.assemble_prompt(payload, "SOURCE", "FACT", "LESSON")

    assert "## 公共规则 COMMON" in prompt
    assert "## 复刻规则 CLONE" in prompt
    assert "## Seedance 模型规则 MODEL_SEEDANCE" in prompt
    assert "## Omni 模型规则 MODEL_OMNI" not in prompt
    assert "## Grok 模型规则 MODEL_GROK" not in prompt
    assert "## Veo 模型规则 MODEL_VEO" not in prompt
    assert "- `MODEL_SEGMENT_SECONDS`：15" in prompt
    assert "字幕、贴纸、日期、标题、营销文字和其他屏幕文字在 Seedance 适配阶段直接忽略" in prompt
    assert "来源只提供口播文字而没有明确发声者时，默认使用画外旁白" in prompt
    assert "发声方式：character_XX 画内说出台词；其他出镜人物不说话。" in prompt
    assert "发声方式：画外旁白；画面内人物不说话、不做口型。" in prompt
    assert prompt.index("</SOURCE_SCRIPT>") < prompt.index("## Seedance 最终输出硬性约束")
    assert prompt.rstrip().endswith("不要把本提醒复述进最终文件。")


def test_seedance_uses_full_markdown_repair_without_changing_omni_repair() -> None:
    seedance_prompt = core._repair_prompt("候选稿", ["没有找到任何 # Segment 段落"], "seedance")
    omni_prompt = core._repair_prompt("候选稿", ["没有找到任何 # Segment 段落"], "omni")

    assert "## Seedance 完整稿修复规则 REPAIR_SEEDANCE" in seedance_prompt
    assert "必须返回修复后的完整 Markdown 文件" in seedance_prompt
    assert "来源未明确发声者时默认画外旁白" in seedance_prompt
    assert "只返回合法 JSON" not in seedance_prompt
    assert "## 局部修复规则 REPAIR" in omni_prompt
    assert "只返回合法 JSON" in omni_prompt
    assert "不要返回完整 Markdown" in omni_prompt
    assert "Seedance 完整稿修复规则" not in omni_prompt


def test_seedance_repairs_nonconforming_first_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# 产品信息\nP1", encoding="utf-8")
    payload = core.validate_task_payload(
        {
            "route": "route1",
            "mode": "clone",
            "model": "seedance",
            "source_path": str(source),
            "target_product": "P1",
            "target_market": "US",
            "target_language": "英语（美式）",
        }
    )
    responses = iter(["没有外层结构的候选稿", seedance_with_inline_fields()])
    prompts: list[str] = []

    def fake_call(prompt: str, *_args: object, **_kwargs: object) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(core, "_call_model", fake_call)

    result = core._generate_one(payload, "source", "fact", "lesson", lambda _message: None)

    assert len(prompts) == 2
    assert "## Seedance 最终输出硬性约束" in prompts[0]
    assert "## Seedance 完整稿修复规则 REPAIR_SEEDANCE" in prompts[1]
    saved = Path(result["path"]).read_text(encoding="utf-8")
    assert saved.startswith("#\n## 每段生成提示词")
    assert "**画面内容：**\ncharacter_01" in saved


def test_omni_applies_json_local_repair_to_original_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# 产品信息\nP1", encoding="utf-8")
    payload = core.validate_task_payload(
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
    invalid = VALID_OMNI.replace("- [细节] 动作清晰稳定", "- [细节] 白色产品包装瓶")
    repairs = [
        {
            "replacements": [
                {
                    "old": "- [细节] 白色产品包装瓶",
                    "new": "- [细节] 黑色产品包装瓶",
                }
            ]
        },
        {
            "replacements": [
                {
                    "old": "- [细节] 黑色产品包装瓶",
                    "new": "- [细节] 红色产品包装瓶",
                }
            ]
        },
        {
            "replacements": [
                {
                    "old": "- [细节] 红色产品包装瓶",
                    "new": "- [细节] 动作清晰稳定",
                }
            ]
        },
    ]
    responses = iter(
        [invalid, *(f"```json\n{json.dumps(repair, ensure_ascii=False)}\n```" for repair in repairs)]
    )
    prompts: list[str] = []

    def fake_call(prompt: str, *_args: object, **_kwargs: object) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(core, "_call_model", fake_call)

    result = core._generate_one(payload, "source", "fact", "lesson", lambda _message: None)

    assert len(prompts) == 4
    assert "## 局部修复规则 REPAIR" in prompts[1]
    assert "不要返回完整 Markdown" in prompts[1]
    saved = Path(result["path"]).read_text(encoding="utf-8")
    assert saved == VALID_OMNI.strip() + "\n"


def test_omni_local_repair_can_replace_repeated_invalid_text() -> None:
    candidate = "- [细节] 白色产品包装瓶\n- [细节] 白色产品包装瓶"
    repair = json.dumps(
        {
            "replacements": [
                {
                    "old": "- [细节] 白色产品包装瓶",
                    "new": "- [细节] 仅保留人物动作",
                }
            ]
        },
        ensure_ascii=False,
    )

    assert core._apply_omni_repair(candidate, repair) == (
        "- [细节] 仅保留人物动作\n- [细节] 仅保留人物动作"
    )


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
    assert 'class="sideRail"' in index_html
    assert 'class="detailTabs"' in index_html
    assert 'id="logTab"' in index_html
    assert 'id="sourceTab"' in index_html
    assert 'id="sourcePreview"' in index_html
    assert '<option value="omni">Omni（已开放）</option>' in index_html
    assert '<option value="seedance">Seedance（已开放）</option>' in index_html
    assert index_html.index('id="taskForm"') < index_html.index('class="sideRail"')
    assert 'id="sourceHint"' not in index_html
    assert 'id="outputs"' not in index_html
    assert index_html.index('name="mode" value="clone"') < index_html.index('name="mode" value="mutation"')
    assert index_html.index('name="mode" value="mutation"') < index_html.index('id="variantField"')
    app_js = (static_root / "app.js").read_text(encoding="utf-8")
    assert "notes:" not in app_js
    assert "counts?.pure" not in app_js
    assert "裂变 ${Number(status.mutation_count||0)} 次" in app_js
    assert "pathRow" in app_js
    assert "refreshedJobs" in app_js
    assert "route()==='route1'?source.product" in app_js
    assert "model:$('#targetModel').value" in app_js
    assert "model:'omni'" not in app_js
    assert "/api/source-preview" in app_js
    assert "variantCount').disabled=!mutation" in app_js
    assert "$('#outputs')" not in app_js


def test_source_preview_reads_only_selected_source_inside_current_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 来源脚本\n完整内容", encoding="utf-8")

    preview = core.source_preview_payload("route1", str(source))

    assert preview == {
        "name": source.name,
        "path": source.as_posix(),
        "content": "# 来源脚本\n完整内容",
    }
    outside = tmp_path / "outside.md"
    outside.write_text("不允许读取", encoding="utf-8")
    with pytest.raises(ValueError, match="不在当前线路允许的资料库目录内"):
        core.source_preview_payload("route1", str(outside))


def test_omni_contract_validator_accepts_exact_downstream_format() -> None:
    assert core.validate_omni_markdown(VALID_OMNI) == []


def test_omni_contract_validator_rejects_missing_ninth_field() -> None:
    broken = VALID_OMNI.replace("- [细节] 动作清晰稳定\n", "")
    issues = core.validate_omni_markdown(broken)
    assert any("恰好按顺序包含 9 个字段" in issue for issue in issues)


def test_omni_contract_validator_rejects_product_visual_details_in_any_field() -> None:
    broken = VALID_OMNI.replace("- [细节] 动作清晰稳定", "- [细节] 棕褐色半透明膏体从白色包装瓶流出，SIMC 标签清晰")

    issues = core.validate_omni_markdown(broken)

    assert any("不得描述产品颜色、形状、包装、标签、膏体颜色或材质" in issue for issue in issues)


def test_omni_contract_validator_requires_product_fact_for_usage_structure() -> None:
    with_pump_action = VALID_OMNI.replace("展示[产品]", "拿起[手持产品]并按压泵头")

    assert any("产品资料未确认的使用结构：泵头" in issue for issue in core.validate_omni_markdown(with_pump_action))
    assert core.validate_omni_markdown(with_pump_action, "使用方法：按压泵头取用适量产品") == []


def test_omni_contract_validator_requires_placeholders_for_visual_product_identity() -> None:
    fact_card = 'aliases: ["SIMC泡泡染"]\n| **品牌** | SIMC | 用户提供 |\n| **型号-SKU** | SIMC04 | 用户提供 |'
    broken = VALID_OMNI.replace("展示[产品]", "展示SIMC泡泡染产品")

    issues = core.validate_omni_markdown(broken, fact_card)

    assert any("商品视觉引用必须使用 [产品] 或 [手持产品]" in issue for issue in issues)
    assert any("不得直接写商品名称、品牌或 SKU" in issue for issue in issues)


def test_omni_contract_validator_allows_product_identity_in_spoken_copy() -> None:
    fact_card = 'aliases: ["SIMC泡泡染"]\n| **品牌** | SIMC | 用户提供 |'
    with_brand_audio = VALID_OMNI.replace("No more waiting.", "SIMC memang mudah digunakan.")

    assert core.validate_omni_markdown(with_brand_audio, fact_card) == []


def test_omni_contract_validator_checks_usage_action_against_product_facts() -> None:
    spray_action = VALID_OMNI.replace("展示[产品]", "拿起[手持产品]喷洒在头发上")

    issues = core.validate_omni_markdown(spray_action, "使用方法：涂抹在头发上后冲洗")

    assert any("使用动作“喷洒”未在产品资料中确认" in issue for issue in issues)
    assert core.validate_omni_markdown(spray_action, "使用方法：均匀喷洒在头发上") == []


def test_omni_contract_validator_does_not_treat_prop_details_as_product_appearance() -> None:
    with_props_and_foam = VALID_OMNI.replace(
        "展示[产品]",
        "从绿色塑料桶旁拿起[产品]，从[产品]挤出泡沫到掌心",
    ).replace(
        "动作清晰稳定",
        "头发上泡沫增多，左手腕戴着一只黑色手表",
    )

    assert core.validate_omni_markdown(with_props_and_foam, "使用方法：挤出泡泡后涂抹头发") == []


def test_omni_contract_validator_keeps_story_props_as_real_categories() -> None:
    with_story_props = VALID_OMNI.replace("展示[产品]", "拿起手机连接自拍杆并调整拍摄角度")

    assert core.validate_omni_markdown(with_story_props) == []


def test_seedance_contract_validator_accepts_seven_field_format() -> None:
    assert core.validate_seedance_markdown(VALID_SEEDANCE) == []


def test_seedance_contract_validator_checks_product_usage_action_against_facts() -> None:
    spray_action = VALID_SEEDANCE.replace(
        "character_01 在卧室展示空无一物的无名指。",
        "character_01 在卧室拿着[手持产品]。",
    ).replace(
        "中景，抬起右手并在结束时保持展示。",
        "中景，使用[手持产品]喷洒在头发上。",
    )

    issues = core.validate_seedance_markdown(spray_action, "使用方法：涂抹在头发上")

    assert any("使用动作“喷洒”未在产品资料中确认" in issue for issue in issues)
    assert core.validate_seedance_markdown(spray_action, "使用方法：喷洒在头发上") == []


@pytest.mark.parametrize(
    "delivery",
    [
        "发声方式：character_01 画内说出台词；其他出镜人物不说话。",
        "发声方式：画外旁白；画面内人物不说话、不做口型。",
    ],
)
def test_seedance_contract_validator_accepts_explicit_speech_delivery(delivery: str) -> None:
    assert core.validate_seedance_markdown(seedance_with_spoken_line(delivery)) == []


def test_seedance_contract_validator_rejects_spoken_line_without_delivery() -> None:
    broken = seedance_with_spoken_line("")

    issues = core.validate_seedance_markdown(broken)

    assert any("有台词时必须在动作/景别明确唯一发声方式" in issue for issue in issues)


def test_seedance_contract_validator_rejects_voiceover_with_onscreen_lip_movement() -> None:
    broken = seedance_with_spoken_line("发声方式：画外旁白。")

    issues = core.validate_seedance_markdown(broken)

    assert any("画外旁白时必须注明画面内人物不说话、不做口型" in issue for issue in issues)


def test_seedance_normalizer_canonicalizes_inline_field_layout() -> None:
    inline = seedance_with_inline_fields()

    assert core.validate_seedance_markdown(inline)
    normalized = core.normalize_seedance_markdown(inline)

    assert core.validate_seedance_markdown(normalized) == []
    assert "- **画面内容**：" not in normalized
    assert "**画面内容：**\ncharacter_01" in normalized

    plain = VALID_SEEDANCE.replace(
        "**画面内容：**\ncharacter_01 在卧室展示空无一物的无名指。",
        "画面内容： character_01 在卧室展示空无一物的无名指。",
        1,
    )
    assert core.validate_seedance_markdown(core.normalize_seedance_markdown(plain)) == []


def test_seedance_contract_validator_rejects_extra_screen_text_field() -> None:
    broken = VALID_SEEDANCE.replace(
        "**时间：**\n00:00.000–00:03.000｜3.0秒",
        "**屏幕文字：**\n后期添加日期\n\n**时间：**\n00:00.000–00:03.000｜3.0秒",
        1,
    )

    issues = core.validate_seedance_markdown(broken)

    assert any("恰好按顺序包含 7 个字段" in issue for issue in issues)
    assert any("不得输出字幕、贴纸、屏幕文字或特效字段" in issue for issue in issues)


def test_seedance_contract_validator_rejects_segment_over_fifteen_seconds() -> None:
    broken = VALID_SEEDANCE.replace("00:12.000", "00:16.000").replace("9.0秒", "13.0秒")

    issues = core.validate_seedance_markdown(broken)

    assert any("不超过 15 秒" in issue for issue in issues)


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


def test_seedance_writes_to_its_own_output_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["hybrid_source"] / "混剪-钩子" / "P1" / "ES-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("source", encoding="utf-8")
    payload = core.validate_task_payload(
        {
            "route": "route3",
            "mode": "clone",
            "model": "seedance",
            "source_path": str(source),
            "target_product": "",
            "target_market": "ES",
            "target_language": "西班牙语",
        }
    )

    output = core.output_path_for(payload)

    assert output.parent == paths["hybrid_seedance_output"] / "混剪-钩子" / "P1" / source.stem
    assert output.name == "seedance-复刻-P1-ES-author-1234567890123.md"


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


def test_run_task_saves_seedance_without_changing_omni_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = configure_storage(monkeypatch, tmp_path)
    source = paths["pure_source"] / "P1" / "US-author-1234567890123-demo.md"
    source.parent.mkdir(parents=True)
    source.write_text("### 镜头 1 (00:00.000 - 00:12.000)", encoding="utf-8")
    (paths["product_info"] / "P1-产品信息.md").write_text("# 产品信息\n- 产品名：P1", encoding="utf-8")
    monkeypatch.setattr(core, "_call_model", lambda *_args, **_kwargs: VALID_SEEDANCE)

    result = core.run_task(
        {
            "route": "route1",
            "mode": "clone",
            "model": "seedance",
            "source_path": str(source),
            "target_product": "P1",
            "target_market": "US",
            "target_language": "英语（美式）",
        }
    )

    output = Path(result["outputs"][0]["path"])
    assert output.parent == paths["pure_seedance_output"] / "P1"
    assert output.read_text(encoding="utf-8").startswith("#\n## 每段生成提示词")
    assert list(paths["pure_output"].rglob("*.md")) == []


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
