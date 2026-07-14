from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


PRODUCT_LOCK_VERSION = 5


def build_storyboard_product_lock_prompt(
    product_name: str,
    base_prompt: str,
    image_size: str,
    aspect_ratio: str = "4:3",
) -> str:
    size_note = f"尺寸{image_size}" if image_size else "尺寸按接口参数输出"
    return (
        "【最高优先级：产品视觉参考锁定】\n"
        "产品外观只能来自输入的产品参考图像，不能来自文字想象、脚本文案、口播词、品牌猜测或模型常识。\n"
        "图1到图N中的产品参考图像是唯一合法产品视觉来源；人物图只用于人物一致性，不能覆盖、改写或替换产品外观。\n"
        "所有产品露出、产品缩略图、手持道具、使用动作、产品细节区、包装/膏体展示，都必须直接参考输入图像中的同一款产品。\n"
        "不要把产品参考图先转写成文字描述后再重新设计产品；必须按图像参考保留颜色、形状、结构、包装、标识、文字、材质、比例和关键细节。\n"
        "如果脚本文字、音频文案、场景描述或任何文本信息与产品参考图像冲突，必须忽略文本，以产品参考图像为准。\n"
        "禁止生成非产品参考图中的替代产品、替代品牌、通用道具或新产品造型。\n"
        "脚本中的拍摄设备、固定方式和机位摆放只用于定义视角、景别和运动感；不得把拍摄设备、支撑物、固定物或其倒影作为画面内容生成。\n"
        f"输出为4K画质，画面比例{aspect_ratio}，{size_note}。如原提示词出现8K要求，以本行4K要求为准。\n\n"
        "【原故事版提示词】\n"
        f"{base_prompt}"
    )


def storyboard_meta_path(storyboard_path: Path) -> Path:
    return storyboard_path.with_suffix(storyboard_path.suffix + ".product-lock.json")


def write_storyboard_product_lock_meta(
    storyboard_path: Path,
    product_name: str,
    product_reference: Path,
    product_reference_count: int,
) -> None:
    metadata = {
        "product_lock_version": PRODUCT_LOCK_VERSION,
        "product_name": product_name,
        "product_reference": str(product_reference),
        "product_reference_count": product_reference_count,
        "created_at": time.time(),
    }
    storyboard_meta_path(storyboard_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def has_current_storyboard_product_lock(
    storyboard_path: Path,
    product_name: Optional[str] = None,
    product_reference: Optional[Path] = None,
) -> bool:
    if not storyboard_path.exists():
        return False
    meta_path = storyboard_meta_path(storyboard_path)
    if not meta_path.exists():
        return False
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if metadata.get("product_lock_version") != PRODUCT_LOCK_VERSION:
        return False
    if product_name and metadata.get("product_name") != product_name:
        return False
    if product_reference and Path(str(metadata.get("product_reference") or "")).resolve() != product_reference.resolve():
        return False
    return True
