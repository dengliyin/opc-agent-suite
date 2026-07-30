from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import Settings
from .files import (
    ScriptFile,
    character_image_path,
    export_marker_path,
    script_exported,
    storyboard_image_path,
    video_output_path,
)
from .product_lock import storyboard_meta_path

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"}
DELIVERY_SIDECAR_SUFFIX = ".delivery.json"


def export_completed_scripts(
    settings: Settings,
    scripts: Iterable[ScriptFile],
    script_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    selected = {str(Path(path).expanduser().resolve()) for path in script_paths or []}
    export_root = dated_export_root(settings)
    exported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    if not selected:
        return {
            "provider": settings.provider,
            "export_root": str(export_root),
            "exported": exported,
            "skipped": skipped,
        }

    for script in scripts:
        script_key = str(script.md_path.resolve())
        if script_key not in selected:
            continue
        if script_exported(script.md_path):
            skipped.append(_skip(script, "已导出"))
            continue

        missing_videos = missing_videos_for_script(settings, script)
        if missing_videos:
            skipped.append(_skip(script, f"视频未完成：{', '.join(missing_videos[:6])}{'...' if len(missing_videos) > 6 else ''}"))
            continue

        try:
            script_export_dir = export_root / _safe_folder_name(script.product_name) / _safe_folder_name(script.md_path.stem)
            copied_files, moved_files = _copy_and_move_script_assets(settings, script, script_export_dir)
            archived_md_path = script_export_dir / script.md_path.name
            marker = {
                "schema_version": 2,
                "provider": settings.provider,
                "provider_label": settings.provider_label,
                "product_name": script.product_name,
                "md_path": str(archived_md_path),
                "active_md_path": str(script.md_path),
                "batch_id": getattr(script, "batch_id", ""),
                "batch_label": getattr(script, "batch_label", ""),
                "batch_source": getattr(script, "batch_source", ""),
                "source_script": getattr(script, "source_script", ""),
                "created_at": getattr(script, "created_at", ""),
                "upstream_script_path": getattr(script, "upstream_script_path", ""),
                "export_dir": str(script_export_dir),
                "exported_at": time.time(),
                "upload_status": "未记录",
                "media_cleaned": False,
                "media_cleaned_at": None,
                "media_files": _media_records(moved_files, archived_md_path),
                "copied_files": copied_files,
                "moved_files": moved_files,
            }
            export_marker_path(archived_md_path).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            exported.append(
                {
                    "product_name": script.product_name,
                    "md_name": script.md_path.name,
                    "md_path": str(archived_md_path),
                    "export_dir": str(script_export_dir),
                    "copied": len(copied_files),
                    "moved": len(moved_files),
                }
            )
        except Exception as exc:
            skipped.append(_skip(script, f"导出失败：{exc}"))

    return {
        "provider": settings.provider,
        "export_root": str(export_root),
        "exported": exported,
        "skipped": skipped,
    }


def deliver_hybrid_scripts(
    settings: Settings,
    scripts: Iterable[ScriptFile],
    script_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    selected = {str(Path(path).expanduser().resolve()) for path in script_paths or []}
    export_root = dated_export_root(settings)
    exported: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for script in scripts:
        if str(script.md_path.resolve()) not in selected:
            continue
        if script_exported(script.md_path):
            skipped.append(_skip(script, "已交付"))
            continue
        missing_videos = missing_videos_for_script(settings, script)
        if missing_videos:
            skipped.append(_skip(script, f"视频未完成：{', '.join(missing_videos)}"))
            continue
        try:
            script_export_dir = (
                export_root
                / _safe_folder_name(script.script_type)
                / _safe_folder_name(script.product_name)
                / _safe_folder_name(script.source_script or script.md_path.parent.name)
                / _safe_folder_name(script.md_path.stem)
            )
            copied_files = _copy_hybrid_delivery_assets(settings, script, script_export_dir)
            original_video_paths = [
                video_output_path(settings, script.product_name, script.md_path, segment.index)
                for segment in script.segments
            ]
            marker_path = export_marker_path(script.md_path)
            moved_files, delivery_sidecars = _move_hybrid_delivery_videos(
                settings,
                script,
                original_video_paths,
                script_export_dir,
                marker_path,
            )
            marker = {
                "schema_version": 2,
                "delivery_mode": "hybrid_move",
                "provider": settings.provider,
                "provider_label": settings.provider_label,
                "product_name": script.product_name,
                "script_type": script.script_type,
                "md_path": str(script.md_path),
                "active_md_path": str(script.md_path),
                "archived_md_path": str(script_export_dir / script.md_path.name),
                "source_script": script.source_script,
                "export_dir": str(script_export_dir),
                "exported_at": time.time(),
                "upload_status": "已导出",
                "media_cleaned": False,
                "media_cleaned_at": None,
                "media_files": [
                    {
                        "name": path.name,
                        "path": str(path),
                        "original_path": str(original),
                        "type": "video",
                        "exists_at_export": True,
                        "cleaned": False,
                    }
                    for path, original in zip((Path(path) for path in moved_files), original_video_paths)
                ],
                "copied_files": copied_files,
                "moved_files": moved_files,
                "delivery_sidecars": delivery_sidecars,
            }
            marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            exported.append(
                {
                    "product_name": script.product_name,
                    "md_name": script.md_path.name,
                    "md_path": str(script.md_path),
                    "export_dir": str(script_export_dir),
                    "copied": len(copied_files),
                    "moved": len(moved_files),
                }
            )
        except Exception as exc:
            skipped.append(_skip(script, f"交付失败：{exc}"))
    return {
        "provider": settings.provider,
        "export_root": str(export_root),
        "exported": exported,
        "skipped": skipped,
    }


def restore_hybrid_deliveries(
    settings: Settings,
    scripts: Iterable[ScriptFile],
    script_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    selected = {str(Path(path).expanduser().resolve()) for path in script_paths or []}
    restored: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for script in scripts:
        if str(script.md_path.resolve()) not in selected:
            continue
        marker_path = export_marker_path(script.md_path)
        if not marker_path.exists():
            skipped.append(_skip(script, "未交付"))
            continue
        try:
            marker = _read_marker(marker_path)
            restored_videos = []
            for item in marker.get("media_files") or []:
                archived = Path(str(item.get("path") or ""))
                original = Path(str(item.get("original_path") or ""))
                if archived.is_file() and str(original) not in {"", "."}:
                    if original.exists():
                        raise FileExistsError(f"恢复目标已存在：{original}")
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(archived), str(original))
                    restored_videos.append(str(original))
                archived.with_suffix(archived.suffix + DELIVERY_SIDECAR_SUFFIX).unlink(missing_ok=True)
            for raw_path in marker.get("copied_files") or []:
                Path(str(raw_path)).unlink(missing_ok=True)
            export_dir = Path(str(marker.get("export_dir") or ""))
            if str(export_dir) not in {"", "."}:
                _remove_empty_parents(export_dir, settings.completed_script_root)
            marker_path.unlink()
            restored.append(
                {
                    "product_name": script.product_name,
                    "md_name": script.md_path.name,
                    "md_path": str(script.md_path),
                    "restored_assets": restored_videos,
                    "restored_videos": restored_videos,
                }
            )
        except Exception as exc:
            skipped.append(_skip(script, f"恢复失败：{exc}"))
    return {"provider": settings.provider, "restored": restored, "skipped": skipped}


def restore_exported_scripts(
    settings: Settings,
    scripts: Iterable[ScriptFile],
    script_paths: Optional[Sequence[str]] = None,
    restore_videos: bool = False,
) -> Dict[str, Any]:
    selected = {str(Path(path).expanduser().resolve()) for path in script_paths or []}
    restored: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    if not selected:
        return {"provider": settings.provider, "restored": restored, "skipped": skipped}

    for script in scripts:
        if str(script.md_path.resolve()) not in selected:
            continue
        marker_path = export_marker_path(script.md_path)
        if not marker_path.exists():
            skipped.append(_skip(script, "未归档"))
            continue
        try:
            marker = _read_marker(marker_path)
            restored_assets = _restore_moved_assets(settings, script, marker, restore_videos)
            marker_path.unlink()
            if script.md_path.exists():
                script.md_path.unlink()
            restored.append(
                {
                    "product_name": script.product_name,
                    "md_name": script.md_path.name,
                    "md_path": str(script.md_path),
                    "restored_assets": restored_assets,
                    "restored_videos": [path for path in restored_assets if path.endswith(".mp4")],
                }
            )
        except Exception as exc:
            skipped.append(_skip(script, f"恢复失败：{exc}"))
    return {"provider": settings.provider, "restored": restored, "skipped": skipped}


def default_export_root(settings: Settings) -> Path:
    return settings.completed_script_root


def dated_export_root(settings: Settings) -> Path:
    return default_export_root(settings) / time.strftime("%Y-%m-%d")


def _copy_and_move_script_assets(settings: Settings, script: ScriptFile, target_dir: Path) -> tuple[List[str], List[str]]:
    prefix = settings.artifact_prefix
    copy_sources: List[Path] = [script.md_path]
    move_sources: List[Path] = []
    for segment in script.segments:
        character_path = character_image_path(script.md_path, segment.index, prefix)
        if character_path.exists():
            move_sources.append(character_path)
        storyboard_path = storyboard_image_path(script.md_path, segment.index, prefix)
        if storyboard_path.exists():
            move_sources.append(storyboard_path)
            meta_path = storyboard_meta_path(storyboard_path)
            if meta_path.exists():
                move_sources.append(meta_path)
        move_sources.append(video_output_path(settings, script.product_name, script.md_path, segment.index))

    missing = [str(path) for path in move_sources if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少视频文件：{missing[0]}")

    conflicts = [target_dir / source.name for source in [*copy_sources, *move_sources] if (target_dir / source.name).exists()]
    if conflicts:
        raise FileExistsError(f"归档目录已存在同名文件：{conflicts[0]}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: List[str] = []
    moved: List[str] = []
    for source in copy_sources:
        target = target_dir / source.name
        shutil.copy2(source, target)
        copied.append(str(target))
    for source in move_sources:
        target = target_dir / source.name
        if target.exists():
            target.unlink()
        shutil.move(str(source), str(target))
        moved.append(str(target))
    return copied, moved


def _copy_hybrid_delivery_assets(settings: Settings, script: ScriptFile, target_dir: Path) -> List[str]:
    sources = [script.md_path]
    for segment in script.segments:
        character = character_image_path(script.md_path, segment.index, settings.artifact_prefix)
        storyboard = storyboard_image_path(script.md_path, segment.index, settings.artifact_prefix)
        for path in (character, storyboard, storyboard_meta_path(storyboard)):
            if path.exists():
                sources.append(path)
    conflicts = [target_dir / source.name for source in sources if (target_dir / source.name).exists()]
    if conflicts:
        raise FileExistsError(f"归档目录已存在同名文件：{conflicts[0]}")
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sources:
        target = target_dir / source.name
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def _move_hybrid_delivery_videos(
    settings: Settings,
    script: ScriptFile,
    original_paths: Sequence[Path],
    target_dir: Path,
    marker_path: Path,
) -> tuple[List[str], List[str]]:
    targets = [target_dir / path.name for path in original_paths]
    conflicts = [path for path in targets if path.exists()]
    if conflicts:
        raise FileExistsError(f"归档目录已存在同名视频：{conflicts[0]}")
    moved = []
    sidecars = []
    for original, target in zip(original_paths, targets):
        shutil.move(str(original), str(target))
        moved.append(str(target))
        sidecars.append(_write_delivery_sidecar(settings, script, target, original, marker_path))
    return moved, sidecars


def _write_delivery_sidecar(
    settings: Settings,
    script: ScriptFile,
    video_path: Path,
    original_path: Path,
    marker_path: Path,
) -> str:
    sidecar = video_path.with_suffix(video_path.suffix + DELIVERY_SIDECAR_SUFFIX)
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "marker_path": str(marker_path),
                "video_path": str(video_path),
                "original_video_path": str(original_path),
                "model": settings.provider,
                "script_type": script.script_type,
                "product_name": script.product_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(sidecar)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.resolve()
    current = path
    while current.exists() and current.resolve() != stop:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def missing_videos_for_script(settings: Settings, script: ScriptFile) -> List[str]:
    missing: List[str] = []
    for segment in script.segments:
        if not video_output_path(settings, script.product_name, script.md_path, segment.index).exists():
            missing.append(f"片段{segment.index}视频")
    return missing


def _safe_folder_name(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", value.strip())
    return cleaned.strip("._") or "未命名"


def _skip(script: ScriptFile, reason: str) -> Dict[str, str]:
    return {
        "product_name": script.product_name,
        "md_name": script.md_path.name,
        "md_path": str(script.md_path),
        "reason": reason,
    }


def _read_marker(marker_path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _media_records(paths: Sequence[str], archived_md_path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.name == archived_md_path.name:
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS and not path.name.endswith(".product-lock.json"):
            continue
        records.append(
            {
                "name": path.name,
                "path": str(path),
                "type": _media_type(path),
                "exists_at_export": True,
                "cleaned": False,
            }
        )
    return records


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if path.name.endswith(".product-lock.json"):
        return "storyboard_meta"
    return "image"


def _restore_moved_assets(settings: Settings, script: ScriptFile, marker: Dict[str, Any], restore_videos: bool) -> List[str]:
    moved_files = [Path(path) for path in marker.get("moved_files") or [] if str(path).strip()]
    moved_by_name = {path.name: path for path in moved_files}
    active_md_path = _active_md_path(settings, script, marker)
    restored: List[str] = []
    for segment in script.segments:
        originals = [
            character_image_path(active_md_path, segment.index, settings.artifact_prefix),
            storyboard_image_path(active_md_path, segment.index, settings.artifact_prefix),
        ]
        originals.append(storyboard_meta_path(originals[-1]))
        if restore_videos:
            originals.append(video_output_path(settings, script.product_name, active_md_path, segment.index))
        if segment.index == 1:
            originals.insert(0, active_md_path)
        for original in originals:
            exported = moved_by_name.get(original.name)
            if not exported or not exported.exists():
                continue
            if original.exists():
                raise FileExistsError(f"恢复目标已存在：{original}")
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(exported), str(original))
            restored.append(str(original))
    return restored


def _active_md_path(settings: Settings, script: ScriptFile, marker: Dict[str, Any]) -> Path:
    raw_active = str(marker.get("active_md_path") or "").strip()
    if raw_active:
        return Path(raw_active)
    return settings.script_root / script.product_name / script.md_path.name
