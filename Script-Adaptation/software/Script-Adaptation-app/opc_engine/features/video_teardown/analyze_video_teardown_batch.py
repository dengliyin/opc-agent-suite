#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from opc_engine.features.video_teardown.analyze_video_teardown import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    analyze_video,
    load_config,
)
from opc_engine.core.project_assets import ensure_project_dirs, infer_source_id, product_project_root, require_product_project, source_stage_dir


ROOT = Path(__file__).resolve().parents[3]


def log(message):
    print(message, flush=True)


def safe_output_name(value):
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_") or "videos"


def resolve_input_path(config):
    configured = str(config.get("analysis_input_path", "") or "").strip()
    if not configured:
        raise SystemExit("请先在视频拆解页选择一个 MP4 视频或包含 MP4 的文件夹")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"拆解视频路径不存在: {path}")
    return path


def find_videos(input_path):
    if input_path.is_file():
        if input_path.suffix.lower() != ".mp4":
            raise SystemExit(f"选择的文件不是 MP4: {input_path}")
        return [input_path]
    return sorted(input_path.glob("*.mp4"))


def write_outputs(output_dir, source_id, text, raw_response):
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_id}_gemini_teardown.md"
    raw_path = output_dir / f"{source_id}_gemini_teardown.raw.json"
    output_path.write_text(text.strip() + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, raw_path


def main():
    config = load_config("video_teardown")
    require_product_project(config, "拆解视频")
    ensure_project_dirs(config)
    input_path = resolve_input_path(config)

    videos = find_videos(input_path)
    if not videos:
        raise SystemExit(f"没有可拆解的视频: {input_path}")

    args = SimpleNamespace(
        model=config.get("video_analysis_model") or DEFAULT_MODEL,
        base_url=config.get("modelmesh_base_url") or DEFAULT_BASE_URL,
        prompt="",
        prompt_file="",
        knowledge_file="",
        timeout=240,
        max_output_tokens=int(config.get("video_analysis_max_output_tokens", 32768) or 32768),
    )

    log("开始视频拆解任务")
    log(f"读取视频路径: {input_path}")
    log(f"项目目录: {product_project_root(config)}")
    log("输出目录: 当前产品项目 / hot_sources / 视频ID / teardown")
    log(f"模型: {args.model}")
    log(f"视频数量: {len(videos)}")

    success_count = 0
    for index, video_path in enumerate(videos, start=1):
        log(f"[{index}/{len(videos)}] 拆解视频: {video_path.name}")
        try:
            text, raw_response, endpoint_style, field_style = analyze_video(video_path, config, args)
            source_id = infer_source_id(video_path)
            output_dir = source_stage_dir(source_id, "teardown", config)
            output_path, _ = write_outputs(output_dir, source_id, text, raw_response)
            success_count += 1
            log(f"  拆解完成: {output_path}")
            log(f"  接口格式: {endpoint_style}, 字段格式: {field_style}")
        except Exception as exc:
            log(f"  拆解失败: {exc}")

    log(f"视频拆解任务完成: 成功 {success_count}/{len(videos)}")
    return 0 if success_count == len(videos) else 1


if __name__ == "__main__":
    sys.exit(main())
