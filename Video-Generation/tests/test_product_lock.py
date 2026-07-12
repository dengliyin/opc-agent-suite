from pathlib import Path

from agent.product_lock import (
    build_storyboard_product_lock_prompt,
    has_current_storyboard_product_lock,
    write_storyboard_product_lock_meta,
)


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
