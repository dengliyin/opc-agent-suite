#!/usr/bin/env bash
set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$AGENT_ROOT"

python3 -m py_compile product_script_rewrite/core.py product_script_rewrite/web.py

python3 - <<'PY'
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

from product_script_rewrite import core
from product_script_rewrite.core import (
    build_prompt,
    cross_shot_continuity_issues,
    list_products,
    load_config,
    matching_rewrite_outputs,
    normalize_source_markdown,
    product_marker_matches,
    rewrite_origin_product,
    rewrite_source_identity,
    rewritten_filename,
    unsupported_marketing_claim_issues,
    validate_rewrite,
)

config = load_config()
products = list_products(config)
assert products, "未扫描到产品"
assert any(item["name"] == "TR02-TROIL纯素藻油Omega-3" for item in products)

source = "MX-amella_brenda-7643094355414158610-_Comprando_desde_aquí.md"
expected = "MX-amella_brenda（原TR02-TROIL纯素藻油Omega-3）-7643094355414158610-_Comprando_desde_aquí.md"
assert rewritten_filename(source, "TR02-TROIL纯素藻油Omega-3") == expected

marked = "MX-amella_brenda（原omega-3）-7643094355414158610-_Comprando_desde_aquí.md"
replacement = "MX-amella_brenda（原TR05-TROIL生发精华）-7643094355414158610-_Comprando_desde_aquí.md"
assert rewritten_filename(marked, "TR05-TROIL生发精华") == replacement
assert rewrite_source_identity(source) == rewrite_source_identity(marked)
assert rewrite_source_identity(source) == rewrite_source_identity(unicodedata.normalize("NFD", marked))
assert rewrite_origin_product(marked) == 'omega-3'
assert product_marker_matches('TR02-TROIL纯素藻油Omega-3', 'omega-3')
assert not product_marker_matches('TR03-TROIL维生素D3K2', 'omega-3')
sample = next(
    path
    for path in Path(config['hot_scripts_root']).joinpath('TR02-TROIL纯素藻油Omega-3').glob('*.md')
    if '7643094355414158610' in path.name
)
prompt = build_prompt(config, sample, 'TR05-TROIL生发精华')
assert '{{SOURCE_SCRIPT}}' not in prompt
assert '{{SOURCE_STRUCTURE}}' not in prompt
assert '{{SHOT_AUDIO_BUDGETS}}' not in prompt
assert '{{SHOT_DISTRIBUTION_RULE}}' not in prompt
assert '{{VALIDATION_FEEDBACK}}' not in prompt
assert 'TR02-TROIL纯素藻油Omega-3' in prompt
assert '### 镜头 1 (00:00.000 - 00:02.100)' in prompt
assert '- **[主体]**' in prompt
assert '只继承来源脚本的爆款机制，不继承来源脚本的内容缺陷' in prompt
assert '至少两个不同镜头' in prompt
assert '不得只展示包装而完全省略' in prompt
assert '最终输出门槛（读完来源脚本后立即执行）' in prompt

budget_sample = next(
    path
    for path in Path(config['hot_scripts_root']).joinpath('TR02-TROIL纯素藻油Omega-3').glob('*.md')
    if '7644016077759859986' in path.name
)
budget_prompt = build_prompt(config, budget_sample, 'TR05-TROIL生发精华')
assert '镜头 1：7.5 秒；实际生成最多 26 个拉丁语系词，校验硬上限 30 个词；来源口播 29 个词' in budget_prompt
assert '镜头 2：10.5 秒；实际生成最多 36 个拉丁语系词，校验硬上限 42 个词；来源口播 35 个词' in budget_prompt
assert '本脚本只有 2 个镜头，因此两个镜头都必须各自包含至少 1 个不同的' in budget_prompt
assert 'antes de que lo corrijan' in budget_prompt

structure_source = """### 镜头 1 (00:00.000 - 00:02.000)
* **[主体]** 来源产品
* **[音频文案]** 原文
---
### 镜头 2 (00:02.000 - 00:04.000)
* **[主体]** 来源产品
* **[音频文案]** 原文
"""
structure_valid = structure_source.replace('来源产品', '目标产品').replace('原文', '改写文案')
assert validate_rewrite(structure_source, structure_valid) == []
plain_structure_source = """镜头 1 (00:00.000 - 00:02.000):
[主体] 来源产品
[音频文案] 原文
---
镜头 2 (00:02.000 - 00:04.000):
[主体] 来源产品
[音频文案] 原文
"""
normalized_plain = normalize_source_markdown(plain_structure_source)
assert '### 镜头 1 (00:00.000 - 00:02.000)' in normalized_plain
assert '- **[主体]** 来源产品' in normalized_plain
assert normalize_source_markdown(normalized_plain) == normalized_plain
assert validate_rewrite(plain_structure_source, structure_valid) == []

subtitle_none_source = """### 镜头 1 (00:00.000 - 00:02.000)
* **[音频文案]** 原文一
* **[字幕]** 无。
---
### 镜头 2 (00:02.000 - 00:04.000)
* **[音频文案]** 原文二
* **[字幕]** 无。
"""
subtitle_none_output = subtitle_none_source.replace('原文一', '改写一').replace('原文二', '改写二')
assert validate_rewrite(subtitle_none_source, subtitle_none_output) == []
subtitle_real_source = subtitle_none_source.replace('无。', '原字幕')
subtitle_stale_output = subtitle_real_source.replace('原文一', '改写一').replace('原文二', '改写二')
assert any('音频已改写但字幕未同步' in issue for issue in validate_rewrite(subtitle_real_source, subtitle_stale_output))
subtitle_missing_output = subtitle_stale_output.replace('原字幕', '无。')
assert any('音频已改写但字幕缺失' in issue for issue in validate_rewrite(subtitle_real_source, subtitle_missing_output))
urgency_output = structure_valid.replace('改写文案', 'Solo por tiempo limitado', 1)
assert unsupported_marketing_claim_issues(urgency_output, 'TikTok 促销价 9,90 €')
assert any('无依据的紧迫性表达' in issue for issue in validate_rewrite(structure_source, urgency_output, 'TikTok 促销价 9,90 €'))
assert unsupported_marketing_claim_issues(urgency_output, 'Oferta por tiempo limitado') == []

with TemporaryDirectory() as directory:
    workspace = Path(directory)
    scripts_root = workspace / 'scripts'
    info_root = workspace / 'products'
    source_product = 'A产品-旧简称'
    source_folder = scripts_root / source_product
    other_source_folder = scripts_root / 'C产品'
    target_folder = scripts_root / 'B产品'
    source_folder.mkdir(parents=True)
    other_source_folder.mkdir()
    target_folder.mkdir(parents=True)
    info_root.mkdir()
    (info_root / 'B产品-产品信息.md').write_text('目标产品信息', encoding='utf-8')
    source_file = source_folder / source
    source_file.write_text(plain_structure_source, encoding='utf-8')
    other_source_file = other_source_folder / source
    other_source_file.write_text(structure_source, encoding='utf-8')
    legacy_output = target_folder / rewritten_filename(source, '旧简称')
    canonical_output = target_folder / rewritten_filename(source, source_product)
    legacy_output.write_text('旧版一', encoding='utf-8')
    canonical_output.write_text('旧版二', encoding='utf-8')
    temp_config = {
        'hot_scripts_root': scripts_root.as_posix(),
        'product_info_root': info_root.as_posix(),
        'rewrite_prompt_path': config['rewrite_prompt_path'],
    }
    assert len(matching_rewrite_outputs(temp_config, source_file, 'B产品')) == 2
    assert matching_rewrite_outputs(temp_config, other_source_file, 'B产品') == []

    original_call = core.call_deepseek
    calls = []
    try:
        core.call_deepseek = lambda prompt, call_config: calls.append(prompt) or structure_valid
        written = core.run_rewrite(source_file, 'B产品', config=temp_config)
        assert calls and len(calls) == 1
        assert written == canonical_output.resolve()
        assert written.read_text(encoding='utf-8') == structure_valid.rstrip() + '\n'
        assert source_file.read_text(encoding='utf-8') == plain_structure_source
        assert matching_rewrite_outputs(temp_config, source_file, 'B产品') == [written]

        calls.clear()
        responses = [
            structure_valid.replace('改写文案', 'uno dos tres cuatro cinco seis siete ocho nueve'),
            structure_valid,
        ]
        core.call_deepseek = lambda prompt, call_config: calls.append(prompt) or responses.pop(0)
        written = core.run_rewrite(source_file, 'B产品', config=temp_config)
        assert len(calls) == 2
        assert '只允许缩短存在超时风险镜头' in calls[1]
        assert written.read_text(encoding='utf-8') == structure_valid.rstrip() + '\n'
        assert source_file.read_text(encoding='utf-8') == plain_structure_source

        preserved = written.read_text(encoding='utf-8')
        calls.clear()
        core.call_deepseek = lambda prompt, call_config: calls.append(prompt) or ''
        try:
            core.run_rewrite(source_file, 'B产品', config=temp_config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('质量校验失败时应中止覆盖')
        assert len(calls) == 1
        assert written.read_text(encoding='utf-8') == preserved
        assert matching_rewrite_outputs(temp_config, source_file, 'B产品') == [written]
    finally:
        core.call_deepseek = original_call

preamble_source = "**【来源分析】**\n分析内容\n\n---\n\n" + structure_source
preamble_output = "改写后的脚本\n\n" + structure_valid
assert validate_rewrite(preamble_source, preamble_output) == []
block_fields = structure_valid.replace('* **[主体]**', '**[主体]**')
assert any('Markdown 结构不一致' in issue for issue in validate_rewrite(structure_source, block_fields))
structure_invalid = structure_valid.replace('* **[主体]** 目标产品\n* **[音频文案]**', '* **[音频文案]** 改写文案\n* **[主体]**', 1)
assert any('Markdown 结构不一致' in issue for issue in validate_rewrite(structure_source, structure_invalid))
time_invalid = structure_valid.replace('00:02.000)', '00:02.500)', 1)
assert any('Markdown 结构不一致' in issue for issue in validate_rewrite(structure_source, time_invalid))
long_audio = structure_valid.replace('改写文案', 'uno dos tres cuatro cinco seis siete ocho nueve', 1)
assert any('口播超时风险' in issue for issue in validate_rewrite(structure_source, long_audio))

broken_continuity = """### 镜头 1 (00:00.000 - 00:03.000)
- **[音频文案]** "Si tú esperaste..."
### 镜头 2 (00:03.000 - 00:06.000)
- **[音频文案]** "Este es el producto."
"""
assert cross_shot_continuity_issues(broken_continuity)
fixed_continuity = broken_continuity.replace('"Este es el producto."', '"...entonces hoy tienes suerte."')
assert cross_shot_continuity_issues(fixed_continuity) == []

copy_source = structure_source + """---
### 镜头 3 (00:04.000 - 00:06.000)
* **[主体]** 来源产品
* **[音频文案]** 原文三
"""
copy_insufficient = copy_source.replace('原文三', '只改这一句')
assert any('产品改写不足' in issue for issue in validate_rewrite(copy_source, copy_insufficient))
print(f"validation: ok ({len(products)} products)")
PY
