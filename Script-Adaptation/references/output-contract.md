# Output Contract

## Naming

Every web-imported adaptation run uses this base name:

```text
YYYYMMDD_当天三位序号_原脚本文件名stem_模型名
```

Example:

```text
20260525_003_7570561984886852882_GlowRoot_Herbal_Hair_Color_Shampoo_veo
```

The run directory under `projects/<product>/hot_sources/` should use the same base name. The copied input script and all adaptation outputs should also use the same base name.

## Markdown

`<base>.md` contains the full model response plus model-call context and local script-cut references.

## Image JSON

`<base>_image_prompts.json` is extracted from module one of the model response. The expected module-one structure is:

```json
{
  "image_generation_model": "NanoBananaPro",
  "output_mode": "storyboard_grid_preview",
  "grid_layout": "auto",
  "allowed_grid_layouts": ["2x2", "3x2", "3x3"],
  "grid_aspect_ratio": "9:16",
  "blank_cell_policy": {
    "enabled": true,
    "style": "plain white or very light neutral empty cell",
    "no_objects": true,
    "no_people": true,
    "no_product": true,
    "no_text": true,
    "no_number": true
  },
  "export_rules": {
    "split_grid": true,
    "export_only_real_shots": true,
    "skip_blank_cells": true,
    "expected_export_count": "same_as_shots_length"
  },
  "global_watermark": {
    "position": "bottom_center",
    "size": "extremely small"
  },
  "shots": [
    {
      "shot_number": "01",
      "prompt_text": "..."
    }
  ]
}
```

## Veo Batch CSV

`<base>_video_prompts.csv` must use exactly these columns:

```text
序号,提示词,横竖屏,模型系列,清晰度,图片模式,首帧图片,尾帧图片,参考图,次数
```

Column values:

- `序号`: 1, 2, 3...
- `提示词`: original `video_model_input_text` content extracted from module two.
- `横竖屏`: `1`
- `模型系列`: `1`
- `清晰度`: `1`
- `图片模式`: `2`
- `首帧图片`: empty
- `尾帧图片`: empty
- `参考图`: longest digit sequence found in the input/output stem, such as `7570561984886852882`.
- `次数`: `1`
