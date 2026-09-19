from pathlib import Path

from agent.product_lock import (
    build_character_product_reference_prompt,
    build_storyboard_product_lock_prompt,
    has_current_storyboard_product_lock,
    write_storyboard_product_lock_meta,
)


def test_character_prompt_uses_product_as_first_reference_without_forcing_it_on_canvas() -> None:
    prompt = build_character_product_reference_prompt("人物板不得出现产品", has_character_references=True)

    assert "输入图1是本批脚本所选的产品参考图" in prompt
    assert "输入图2及后续图片是之前片段的人物参考图" in prompt
    assert "不得强行把产品画进人物板" in prompt
    assert prompt.endswith("人物板不得出现产品")


def test_storyboard_prompt_locks_product_to_images_without_hardcoded_visuals() -> None:
    prompt = build_storyboard_product_lock_prompt("SIMC染发棒", "8K分辨率 原提示词", "4096x3072")

    assert "产品外观只能来自输入的产品参考图像" in prompt
    assert "不要把产品参考图先转写成文字描述后再重新设计产品" in prompt
    assert "以产品参考图像为准" in prompt
    assert "亮橙色" not in prompt
    assert "SA JAPAN" not in prompt
    assert "输出为4K画质" in prompt
    assert "8K分辨率 原提示词" in prompt


def test_storyboard_product_lock_metadata_marks_current_output(tmp_path: Path) -> None:
    storyboard = tmp_path / "story.png"
    storyboard.write_bytes(b"png")
    reference = tmp_path / "product.png"
    reference.write_bytes(b"ref")

    assert has_current_storyboard_product_lock(storyboard, "SIMC染发棒") is False

    write_storyboard_product_lock_meta(storyboard, "SIMC染发棒", reference, 1)

    assert has_current_storyboard_product_lock(storyboard, "SIMC染发棒") is True
    assert has_current_storyboard_product_lock(storyboard, "Other") is False
    assert has_current_storyboard_product_lock(storyboard, "SIMC染发棒", reference) is True
    assert has_current_storyboard_product_lock(storyboard, "SIMC染发棒", tmp_path / "other.png") is False
