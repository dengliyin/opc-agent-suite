#!/usr/bin/env python3
import csv
import json
import shutil
from pathlib import Path

from opc_engine.core.config_store import load_app_config, save_app_config
from opc_engine.core.project_assets import (
    ROOT,
    collection_csv_path,
    diagnostics_dir,
    ensure_project_dirs,
    infer_source_id,
    product_project_root,
    product_project_slug,
    product_profile_path,
    product_report_dir,
    project_relative,
    raw_data_dir,
    runtime_state_path,
    safe_name,
    source_stage_dir,
    unique_path,
)


LEGACY_DIRS = [
    "storage",
    "downloads",
    "analysis",
    "script_outputs",
    "adapted_scripts",
    "assembled_videos",
    "publish_records",
    "metrics",
    "script_optimizations",
    "product_profile",
]


def log(message):
    print(message, flush=True)


def load_config():
    return load_app_config()


def save_config(config):
    save_app_config(config)


def move_file(source, target, moved):
    source = Path(source)
    target = Path(target)
    if not source.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if source.is_file() and target.is_file() and source.stat().st_size == target.stat().st_size:
            source.unlink()
            moved[str(source.resolve())] = str(target.resolve())
            log(f"跳过重复文件: {source} -> {target}")
            return target
        target = unique_path(target)
    shutil.move(str(source), str(target))
    moved[str(source.resolve())] = str(target.resolve())
    log(f"移动: {source} -> {target}")
    return target


def remove_empty_or_legacy_dir(path):
    path = Path(path)
    if not path.exists():
        return
    for junk in path.rglob(".DS_Store"):
        try:
            junk.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        shutil.rmtree(path, ignore_errors=True)
        log(f"已清理旧目录: {path}")


def migrate_product_profile(config, moved):
    legacy_dir = ROOT / "product_profile"
    target = product_profile_path(config)
    for source in legacy_dir.glob("*"):
        if source.is_file():
            move_file(source, target if source.name == "current_product_profile.md" else target.parent / source.name, moved)


def migrate_storage(config, moved):
    legacy_dir = ROOT / "storage"
    if not legacy_dir.exists():
        return

    for source in sorted(legacy_dir.rglob("*")):
        if not source.is_file():
            continue
        if source.suffix.lower() == ".csv":
            target = collection_csv_path(source.stem, config)
        elif source.name in {"fastmoss-state.json", "fastmoss-login-meta.json", "tkyds-state.json"}:
            target = runtime_state_path(source.name, config)
        else:
            relative = source.relative_to(legacy_dir)
            target = diagnostics_dir(config) / relative
        move_file(source, target, moved)


def migrate_downloads(config, moved):
    legacy_dir = ROOT / "downloads"
    if not legacy_dir.exists():
        return

    for source in sorted(legacy_dir.rglob("*")):
        if not source.is_file():
            continue
        if source.name == ".DS_Store":
            try:
                source.unlink()
            except OSError:
                pass
            continue
        source_id = infer_source_id(source.name)
        target = source_stage_dir(source_id, "source", config) / source.name
        move_file(source, target, moved)


def migrate_analysis(config, moved):
    legacy_dir = ROOT / "analysis"
    if not legacy_dir.exists():
        return

    for source in sorted(legacy_dir.rglob("*")):
        if not source.is_file():
            continue
        source_id = infer_source_id(source.name)
        relative_parent = source.parent.relative_to(legacy_dir)
        if str(relative_parent) == ".":
            target = source_stage_dir(source_id, "teardown", config) / source.name
        else:
            target = source_stage_dir(source_id, "teardown", config) / relative_parent / source.name
        move_file(source, target, moved)


def source_id_from_config(config):
    for key in [
        "script_reference_analysis_path",
        "script_adaptation_input_path",
        "video_publish_input_path",
        "script_optimization_input_path",
        "script_optimization_metrics_path",
    ]:
        value = config.get(key)
        if value:
            source_id = infer_source_id(value, "")
            if source_id:
                return source_id
    return "unknown_source"


def migrate_stage_dir(config, moved, legacy_name, source_stage, product_report_stage=None):
    legacy_dir = ROOT / legacy_name
    if not legacy_dir.exists():
        return
    fallback_source_id = source_id_from_config(config)
    for source in sorted(legacy_dir.rglob("*")):
        if not source.is_file():
            continue
        source_id = infer_source_id(source.name, "") or fallback_source_id
        if source_id and source_id != "unknown_source":
            target_dir = source_stage_dir(source_id, source_stage, config)
        else:
            target_dir = product_report_dir(product_report_stage or source_stage, config)
        target = target_dir / source.name
        move_file(source, target, moved)


def migrate_metrics(config, moved):
    legacy_dir = ROOT / "metrics"
    if not legacy_dir.exists():
        return
    raw_dir = legacy_dir / "raw_downloads"
    if raw_dir.exists():
        for source in sorted(raw_dir.rglob("*")):
            if not source.is_file():
                continue
            name = source.name.lower()
            if "gmv" in name or "creative" in name:
                target = raw_data_dir("ad_performance", config) / source.name
            else:
                target = raw_data_dir("natural_flow", config) / source.name
            move_file(source, target, moved)

    for source in sorted(legacy_dir.rglob("*")):
        if not source.is_file():
            continue
        if "raw_downloads" in source.parts:
            continue
        target = product_report_dir("data_attribution", config) / source.name
        move_file(source, target, moved)


def update_config_paths(config, moved):
    resolved_map = {Path(old).resolve(): Path(new).resolve() for old, new in moved.items()}
    path_fields = [
        "analysis_input_path",
        "script_reference_analysis_path",
        "script_adaptation_input_path",
        "clip_assembly_input_dir",
        "video_publish_input_path",
        "data_recovery_input_path",
        "data_recovery_natural_input_path",
        "data_recovery_ads_input_path",
        "script_optimization_input_path",
        "script_optimization_metrics_path",
    ]
    for field in path_fields:
        value = str(config.get(field, "") or "").strip()
        if not value:
            continue
        try:
            old_path = (ROOT / value).resolve() if not Path(value).expanduser().is_absolute() else Path(value).expanduser().resolve()
        except OSError:
            continue
        if old_path in resolved_map:
            config[field] = str(resolved_map[old_path])

    config["product_project_slug"] = product_project_slug(config)
    config["product_profile_path"] = project_relative(product_profile_path(config))
    config["data_attribution_download_output_dir"] = project_relative(product_project_root(config) / "raw_data")
    return config


def write_project_manifest(config):
    project_root = product_project_root(config)
    manifest = {
        "product_project_slug": product_project_slug(config),
        "product_project_root": str(project_root),
        "product_profile_path": str(product_profile_path(config)),
        "structure": {
            "collection_runs": "each FastMoss collection run CSV",
            "hot_sources/<source_id>/source": "downloaded competitor/source videos and source metrics",
            "hot_sources/<source_id>/teardown": "video teardown outputs",
            "hot_sources/<source_id>/scripts": "product scripts generated from that source",
            "hot_sources/<source_id>/adaptations": "video-model prompt packages",
            "hot_sources/<source_id>/generated_videos": "generated/assembled videos",
            "hot_sources/<source_id>/publish_records": "publishing plans or records",
            "hot_sources/<source_id>/optimizations": "script optimization notes tied to that source",
            "raw_data": "natural and paid performance raw exports",
            "product_level_reports/data_attribution": "processed attribution CSV and reports",
        },
    }
    manifest_path = project_root / "PROJECT_ASSETS.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"项目资产清单: {manifest_path}")


def main():
    config = load_config()
    ensure_project_dirs(config)
    moved = {}

    migrate_product_profile(config, moved)
    migrate_storage(config, moved)
    migrate_downloads(config, moved)
    migrate_analysis(config, moved)
    migrate_stage_dir(config, moved, "script_outputs", "scripts", "scripts")
    migrate_stage_dir(config, moved, "adapted_scripts", "adaptations", "script_adaptations")
    migrate_stage_dir(config, moved, "assembled_videos", "generated_videos", "generated_videos")
    migrate_stage_dir(config, moved, "publish_records", "publish_records", "publish_records")
    migrate_metrics(config, moved)
    migrate_stage_dir(config, moved, "script_optimizations", "optimizations", "script_optimizations")

    config = update_config_paths(config, moved)
    save_config(config)
    write_project_manifest(config)

    for name in LEGACY_DIRS:
        remove_empty_or_legacy_dir(ROOT / name)

    log(f"迁移完成，移动/合并文件数: {len(moved)}")
    log(f"新的产品项目目录: {product_project_root(config)}")


if __name__ == "__main__":
    main()
