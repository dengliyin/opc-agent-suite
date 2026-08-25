from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from PIL import Image, ImageOps

from .config import Settings
from .markdown_parser import Segment, parse_segments
from .product_lock import has_current_storyboard_product_lock


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
EXPORT_MARKER_SUFFIX = ".exported.json"
FRAGMENT_DELETE_MARKER_SUFFIX = ".fragment-deleted"


@dataclass(frozen=True)
class ScriptFile:
    product_name: str
    product_dir: Path
    md_path: Path
    reference_image: Optional[Path]
    segments: List[Segment]
    reference_images: tuple[Path, ...] = ()
    batch_id: str = ""
    batch_label: str = ""
    batch_source: str = ""
    source_script: str = ""
    created_at: str = ""
    upstream_script_path: str = ""
    exported: bool = False
    script_type: str = ""


@dataclass(frozen=True)
class ScriptCandidate:
    product_name: str
    product_dir: Path
    md_path: Path
    reference_image: Optional[Path]
    reference_images: tuple[Path, ...] = ()
    batch_id: str = ""
    batch_label: str = ""
    batch_source: str = ""
    source_script: str = ""
    created_at: str = ""
    upstream_script_path: str = ""
    script_type: str = ""


def scan_scripts(settings: Settings, include_archived: bool = False) -> List[ScriptFile]:
    if settings.workflow == "hybrid_omni":
        return _scan_hybrid_script_root(settings)
    scripts = _scan_script_root(settings, settings.script_root, exported=False)
    if include_archived:
        scripts.extend(_scan_script_root(settings, settings.completed_script_root, exported=True))
    return scripts


def discover_active_script_candidates(
    settings: Settings,
    archived_active_paths: Iterable[str] = (),
) -> List[ScriptCandidate]:
    if settings.workflow == "hybrid_omni":
        return _discover_hybrid_candidates(settings)
    root = settings.script_root
    if not root.exists():
        return []
    archived = {str(Path(path).expanduser().resolve()) for path in archived_active_paths if path}
    candidates: List[ScriptCandidate] = []
    for product_dir in [path for path in _safe_iterdir(root) if path.is_dir()]:
        if product_dir.name.startswith("_") or product_dir.name.startswith("."):
            continue
        md_paths = [
            path
            for path in _safe_glob(product_dir, "*.md")
            if not script_suppressed(path) and str(path.resolve()) not in archived
        ]
        if not md_paths:
            continue
        references = tuple(find_product_references(settings.reference_root, product_dir.name))
        reference = references[0] if len(references) == 1 else None
        for md_path in md_paths:
            candidates.append(
                ScriptCandidate(
                    product_name=product_dir.name,
                    product_dir=product_dir,
                    md_path=md_path,
                    reference_image=reference,
                    reference_images=references,
                )
            )
    return candidates


def _discover_hybrid_candidates(settings: Settings) -> List[ScriptCandidate]:
    root = settings.script_root
    if not root.exists():
        return []
    candidates: List[ScriptCandidate] = []
    references_by_product: Dict[str, tuple[Path, ...]] = {}
    for md_path in _recursive_markdown_files(root):
        if script_suppressed(md_path):
            continue
        relative = md_path.relative_to(root)
        if len(relative.parts) < 3:
            continue
        script_type, product_name = relative.parts[:2]
        if script_type not in {"混剪-钩子", "混剪-CTA"}:
            continue
        if any(part.startswith("_") or part.startswith(".") for part in relative.parts[:-1]):
            continue
        if product_name not in references_by_product:
            references_by_product[product_name] = tuple(find_product_references(settings.reference_root, product_name))
        references = references_by_product[product_name]
        source_script = relative.parts[2] if len(relative.parts) > 3 else md_path.stem
        candidates.append(
            ScriptCandidate(
                product_name=product_name,
                product_dir=root / script_type / product_name,
                md_path=md_path,
                reference_image=references[0] if len(references) == 1 else None,
                reference_images=references,
                batch_id=f"{script_type}-{product_name}-{source_script}",
                batch_label=source_script,
                batch_source="hybrid_adaptation",
                source_script=source_script,
                script_type=script_type,
            )
        )
    return candidates


def load_script_candidate(candidate: ScriptCandidate) -> Optional[ScriptFile]:
    markdown = _read_markdown(candidate.md_path)
    if markdown is None:
        return None
    return ScriptFile(
        product_name=candidate.product_name,
        product_dir=candidate.product_dir,
        md_path=candidate.md_path,
        reference_image=candidate.reference_image,
        segments=parse_segments(markdown),
        reference_images=candidate.reference_images,
        batch_id=candidate.batch_id,
        batch_label=candidate.batch_label,
        batch_source=candidate.batch_source,
        source_script=candidate.source_script,
        created_at=candidate.created_at,
        upstream_script_path=candidate.upstream_script_path,
        script_type=candidate.script_type,
    )


def _recursive_markdown_files(root: Path) -> List[Path]:
    """Return a stable snapshot while tolerating concurrently removed directories."""
    paths: List[Path] = []
    for directory, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(".md"):
                paths.append(Path(directory) / filename)
    return paths


def _read_markdown(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        # Obsidian/sync clients can rename or remove a file after enumeration.
        return None


def _safe_iterdir(root: Path) -> List[Path]:
    try:
        return sorted(root.iterdir())
    except OSError:
        return []


def _safe_glob(root: Path, pattern: str) -> List[Path]:
    try:
        return sorted(root.glob(pattern))
    except OSError:
        return []


def _scan_hybrid_script_root(settings: Settings) -> List[ScriptFile]:
    root = settings.script_root
    if not root.exists():
        return []

    scripts: List[ScriptFile] = []
    references_by_product: Dict[str, List[Path]] = {}
    for md_path in _recursive_markdown_files(root):
        if script_suppressed(md_path):
            continue
        relative = md_path.relative_to(root)
        if len(relative.parts) < 3:
            continue
        script_type, product_name = relative.parts[:2]
        if script_type not in {"混剪-钩子", "混剪-CTA"}:
            continue
        if any(part.startswith("_") or part.startswith(".") for part in relative.parts[:-1]):
            continue
        if product_name not in references_by_product:
            references_by_product[product_name] = find_product_references(
                settings.reference_root, product_name
            )
        reference_images = references_by_product[product_name]
        reference_image = reference_images[0] if len(reference_images) == 1 else None
        markdown = _read_markdown(md_path)
        if markdown is None:
            continue
        source_script = relative.parts[2] if len(relative.parts) > 3 else md_path.stem
        scripts.append(
            ScriptFile(
                product_name=product_name,
                product_dir=root / script_type / product_name,
                md_path=md_path,
                reference_image=reference_image,
                segments=parse_segments(markdown),
                reference_images=tuple(reference_images),
                batch_id=f"{script_type}-{product_name}-{source_script}",
                batch_label=source_script,
                batch_source="hybrid_adaptation",
                source_script=source_script,
                script_type=script_type,
            )
        )
    return scripts


def _scan_script_root(settings: Settings, root: Path, exported: bool) -> List[ScriptFile]:
    if not root.exists():
        return []

    scripts: List[ScriptFile] = []
    if exported:
        references_by_product: Dict[str, List[Path]] = {}
        for md_path in _recursive_markdown_files(root):
            if any(part.startswith("_") or part.startswith(".") for part in md_path.relative_to(root).parts[:-1]):
                continue
            product_dir = _exported_product_dir(root, md_path)
            if product_dir is None:
                continue
            product_name = product_dir.name
            if product_name not in references_by_product:
                references_by_product[product_name] = find_product_references(settings.reference_root, product_name)
            reference_images = references_by_product[product_name]
            reference_image = reference_images[0] if len(reference_images) == 1 else None
            markdown = _read_markdown(md_path)
            if markdown is None:
                continue
            segments = parse_segments(markdown)
            scripts.append(
                ScriptFile(
                    product_name=product_name,
                    product_dir=product_dir,
                    md_path=md_path,
                    reference_image=reference_image,
                    segments=segments,
                    reference_images=tuple(reference_images),
                    exported=True,
                )
            )
        return scripts

    for product_dir in [path for path in _safe_iterdir(root) if path.is_dir()]:
        if product_dir.name.startswith("_") or product_dir.name.startswith("."):
            continue
        md_paths = _safe_glob(product_dir, "*.md")
        md_paths = [
            md_path
            for md_path in md_paths
            if not script_suppressed(md_path)
            and not _active_script_archived(settings, product_dir.name, md_path)
        ]
        if not md_paths:
            continue
        reference_images = find_product_references(settings.reference_root, product_dir.name)
        reference_image = reference_images[0] if len(reference_images) == 1 else None
        for md_path in md_paths:
            markdown = _read_markdown(md_path)
            if markdown is None:
                continue
            segments = parse_segments(markdown)
            scripts.append(
                ScriptFile(
                    product_name=product_dir.name,
                    product_dir=product_dir,
                    md_path=md_path,
                    reference_image=reference_image,
                    segments=segments,
                    reference_images=tuple(reference_images),
                    exported=exported,
                )
            )
    return scripts


def _exported_product_dir(root: Path, md_path: Path) -> Optional[Path]:
    parts = md_path.relative_to(root).parts
    if len(parts) < 4 or not _is_date_folder(parts[0]):
        return None
    return root / parts[0] / parts[1]


def _is_date_folder(name: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", name))


def _active_script_archived(settings: Settings, product_name: str, md_path: Path) -> bool:
    completed_root = settings.completed_script_root
    if not completed_root.exists():
        return False
    for date_dir in _safe_iterdir(completed_root):
        if not date_dir.is_dir() or not _is_date_folder(date_dir.name):
            continue
        archived_md = date_dir / product_name / md_path.stem / md_path.name
        if archived_md.exists():
            return True
    return False


def fragment_delete_marker_path(md_path: Path) -> Path:
    return md_path.with_name(f"{md_path.name}{FRAGMENT_DELETE_MARKER_SUFFIX}")


def suppress_script(md_path: Path) -> Path:
    marker = fragment_delete_marker_path(md_path)
    stat = md_path.stat()
    marker.write_text(
        json.dumps(
            {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "sha256": _file_sha256(md_path),
            }
        ),
        encoding="utf-8",
    )
    return marker


def script_suppressed(md_path: Path) -> bool:
    marker = fragment_delete_marker_path(md_path)
    if not marker.is_file():
        return False
    try:
        raw_marker = marker.read_text(encoding="utf-8").strip()
        stat = md_path.stat()
        try:
            payload = json.loads(raw_marker)
        except json.JSONDecodeError:
            return raw_marker == str(stat.st_mtime_ns)
        if not isinstance(payload, dict):
            return False
        if payload.get("mtime_ns") != stat.st_mtime_ns or payload.get("size") != stat.st_size:
            return False
        return str(payload.get("sha256") or "") == _file_sha256(md_path)
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_upstream_batch_map(settings: Settings) -> Dict[str, Dict[str, str]]:
    base_url = os.getenv("ADAPTATION_AGENT_URL", "http://127.0.0.1:8788").rstrip("/")
    query = urllib.parse.urlencode({"target_model": settings.provider})
    url = f"{base_url}/api/scripts?{query}"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for product in payload.get("products") or []:
        product_name = str(product.get("product_name") or product.get("name") or product.get("product") or "")
        for batch in product.get("batches") or []:
            for script in batch.get("scripts") or []:
                output_path = str(script.get("adapted_output_path") or "").strip()
                if not output_path:
                    continue
                result[str(Path(output_path).expanduser().resolve())] = upstream_batch_metadata(product_name, batch, script)
    return result


def upstream_batch_metadata(product_name: str, batch: Dict[str, Any], script: Dict[str, Any]) -> Dict[str, str]:
    raw_batch_id = str(script.get("batch_id") or batch.get("batch_id") or "").strip()
    raw_batch_source = str(script.get("batch_source") or batch.get("batch_source") or "").strip()
    source_script = str(script.get("source_script") or batch.get("source_script") or script.get("name") or "").strip()
    source_script = base_source_script_name(source_script)
    created_at = str(script.get("created_at") or batch.get("created_at") or "").strip()
    upstream_script_path = str(script.get("path") or "").strip()
    has_explicit_batch = bool(raw_batch_id and not raw_batch_id.startswith("tmp-") and raw_batch_source != "fallback")
    if has_explicit_batch:
        return {
            "batch_id": raw_batch_id,
            "batch_label": str(script.get("batch_label") or batch.get("batch_label") or raw_batch_id),
            "batch_source": raw_batch_source or "upstream",
            "source_script": source_script,
            "created_at": created_at,
            "upstream_script_path": upstream_script_path,
        }

    source_stem = Path(source_script).stem or Path(str(script.get("name") or "")).stem or "未命名母脚本"
    return {
        "batch_id": f"source-{_safe_key(product_name)}-{_safe_key(source_stem)}",
        "batch_label": source_stem,
        "batch_source": "source_script",
        "source_script": source_script,
        "created_at": created_at,
        "upstream_script_path": upstream_script_path,
    }


def fallback_batch_metadata(settings: Settings, product_name: str, md_path: Path) -> Dict[str, str]:
    try:
        mtime = md_path.stat().st_mtime
    except OSError:
        mtime = time.time()
    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
    source_stem = md_path.stem
    provider_prefix = f"{settings.provider}-"
    if source_stem.startswith(provider_prefix):
        source_stem = source_stem[len(provider_prefix):]
    source_stem = re.sub(r"_\d{3,}$", "", source_stem)
    source_script = f"{source_stem}.md"
    batch_id = f"source-{_safe_key(product_name)}-{_safe_key(source_stem)}"
    return {
        "batch_id": batch_id,
        "batch_label": source_stem,
        "batch_source": "local",
        "source_script": source_script,
        "created_at": created_at,
        "upstream_script_path": "",
    }


def base_source_script_name(filename: str) -> str:
    path = Path(str(filename or "").strip() or "未命名.md")
    stem = re.sub(r"_\d{3,}$", "", path.stem)
    suffix = path.suffix or ".md"
    return f"{stem}{suffix}"


def _safe_key(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip()).strip("-") or "未命名"


def find_product_reference(reference_root: Path, product_name: str) -> Optional[Path]:
    references = find_product_references(reference_root, product_name)
    return references[0] if references else None


def find_product_references(reference_root: Path, product_name: str) -> List[Path]:
    matches: List[Path] = []

    def add(candidate: Path) -> None:
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS and candidate not in matches:
            matches.append(candidate)

    for ext in IMAGE_EXTENSIONS:
        candidate = reference_root / f"{product_name}{ext}"
        if candidate.exists():
            add(candidate)

    for candidate in _safe_glob(reference_root, f"{product_name}-*"):
        add(candidate)

    product_folder = reference_root / product_name
    if product_folder.is_dir():
        for candidate in _safe_iterdir(product_folder):
            add(candidate)

    if matches:
        return matches

    for candidate in _safe_iterdir(reference_root):
        if candidate.stem.endswith(f"-{product_name}"):
            add(candidate)
    return matches


def product_reference_label(product_name: str, reference: Path) -> str:
    prefix = f"{product_name}-"
    if reference.stem.startswith(prefix):
        return reference.stem[len(prefix):]
    if reference.parent.name == product_name:
        return reference.stem
    return reference.stem


def md_stem(md_path: Path) -> str:
    return md_path.stem


def _artifact_name(md_path: Path, segment_index: int, label: str, prefix: str = "") -> str:
    provider = f"{prefix}-" if prefix else ""
    return f"{md_stem(md_path)}-片段{segment_index}-{provider}{label}"


def character_image_path(md_path: Path, segment_index: int, prefix: str = "") -> Path:
    return md_path.parent / _artifact_name(md_path, segment_index, "人物图.png", prefix)


def storyboard_image_path(md_path: Path, segment_index: int, prefix: str = "") -> Path:
    return md_path.parent / _artifact_name(md_path, segment_index, "故事版.png", prefix)


def video_output_path(settings: Settings, product_name: str, md_path: Path, segment_index: int) -> Path:
    suffix = "omni" if settings.provider == "omni" else settings.provider
    if settings.workflow == "hybrid_omni":
        relative = md_path.resolve().relative_to(settings.script_root.resolve())
        if len(relative.parts) < 3 or relative.parts[0] not in {"混剪-钩子", "混剪-CTA"}:
            raise ValueError(f"混剪适配脚本目录层级无效：{md_path}")
        script_type = relative.parts[0]
        return (
            settings.video_output_root
            / script_type
            / product_name
            / f"{md_stem(md_path)}-片段{segment_index}-{suffix}.mp4"
        )
    return settings.video_output_root / product_name / f"{md_stem(md_path)}-片段{segment_index}-{suffix}.mp4"


def export_marker_path(md_path: Path) -> Path:
    return md_path.with_name(f"{md_path.stem}{EXPORT_MARKER_SUFFIX}")


def script_exported(md_path: Path) -> bool:
    return export_marker_path(md_path).exists()


def read_export_marker(md_path: Path) -> Dict[str, Any]:
    marker_path = export_marker_path(md_path)
    if not marker_path.exists():
        return {}
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def exported_asset_path(marker: Dict[str, Any], original: Path, file_key: str = "copied_files") -> Optional[Path]:
    original_name = original.name
    for raw_path in marker.get(file_key) or []:
        path = Path(str(raw_path))
        if path.name == original_name and path.exists():
            return path
    export_dir = str(marker.get("export_dir") or "").strip()
    if export_dir:
        candidate = Path(export_dir) / original_name
        if candidate.exists():
            return candidate
    return None


def image_to_data_uri(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def image_matches_aspect(path: Path, aspect_ratio: str, tolerance: float = 0.03) -> bool:
    if not path.exists():
        return False
    expected = _parse_aspect_ratio(aspect_ratio)
    if expected is None:
        return True
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
    except Exception:
        return False
    if width <= 0 or height <= 0:
        return False
    actual = width / height
    return abs(actual - expected) <= tolerance


def image_output_current(settings: Settings, path: Path) -> bool:
    if not path.exists():
        return False
    if settings.provider != "grok":
        return True
    return image_matches_aspect(path, settings.grok_image_aspect_ratio)


def image_stale_reason(settings: Settings, path: Path, *, product_lock_current: bool = True) -> str:
    if not path.exists():
        return ""
    if not product_lock_current:
        return "产品参考锁已失效"
    if settings.provider != "grok":
        return "需重做"
    expected = settings.grok_image_aspect_ratio
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
    except Exception:
        return f"图片无法读取，要求 {expected}"
    if not image_matches_aspect(path, expected):
        return f"比例不符：{width}x{height}，要求 {expected}"
    return "需重做"


def _parse_aspect_ratio(aspect_ratio: str) -> Optional[float]:
    parts = [part.strip() for part in aspect_ratio.split(":", 1)]
    if len(parts) != 2:
        return None
    try:
        width = float(parts[0])
        height = float(parts[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def artifact_url(path: Optional[Path], api_base_path: str = "/api") -> Optional[str]:
    if path is None:
        return None
    version = ""
    try:
        if path.exists():
            version = f"&v={path.stat().st_mtime_ns}"
    except OSError:
        version = ""
    return f"{api_base_path.rstrip('/')}/artifact?path={quote(str(path))}{version}"


def script_to_dict(settings: Settings, script: ScriptFile) -> Dict[str, object]:
    exported = bool(getattr(script, "exported", False)) or script_exported(script.md_path)
    marker = read_export_marker(script.md_path) if exported else {}
    segments = [
        segment_to_dict(settings, script, segment, marker=marker)
        for segment in script.segments
    ]
    generation_status = script_generation_status(script, segments, marker)
    reference_images = getattr(script, "reference_images", ())
    if not reference_images and script.reference_image is not None:
        reference_images = (script.reference_image,)
    return {
        "product_name": script.product_name,
        "product_dir": str(script.product_dir),
        "md_path": str(script.md_path),
        "md_name": script.md_path.name,
        "reference_image": str(script.reference_image) if script.reference_image else None,
        "reference_url": artifact_url(script.reference_image, settings.api_base_path) if script.reference_image else None,
        "reference_images": [
            {
                "path": str(reference),
                "name": reference.name,
                "label": product_reference_label(script.product_name, reference),
                "url": artifact_url(reference, settings.api_base_path),
            }
            for reference in reference_images
        ],
        "batch_id": getattr(script, "batch_id", ""),
        "batch_label": getattr(script, "batch_label", ""),
        "batch_source": getattr(script, "batch_source", ""),
        "source_script": getattr(script, "source_script", ""),
        "created_at": getattr(script, "created_at", ""),
        "upstream_script_path": getattr(script, "upstream_script_path", ""),
        "script_type": getattr(script, "script_type", ""),
        "complete": True if exported else generation_status["full_mode_complete"],
        "has_video": generation_status["has_video"],
        "full_mode_complete": generation_status["full_mode_complete"],
        "exported": exported,
        "export_marker": str(export_marker_path(script.md_path)) if exported else None,
        "upload_status": marker.get("upload_status", "") if exported else "",
        "media_cleaned": bool(marker.get("media_cleaned")) if exported else False,
        "segments": segments,
    }


def segment_to_dict(settings: Settings, script: ScriptFile, segment: Segment, marker: Optional[Dict[str, Any]] = None) -> Dict[str, object]:
    prefix = settings.artifact_prefix
    marker = marker or {}
    original_character_path = character_image_path(script.md_path, segment.index, prefix)
    original_storyboard_path = storyboard_image_path(script.md_path, segment.index, prefix)
    character_path = (
        exported_asset_path(marker, original_character_path, "moved_files")
        or exported_asset_path(marker, original_character_path, "copied_files")
        or original_character_path
    )
    storyboard_path = (
        exported_asset_path(marker, original_storyboard_path, "moved_files")
        or exported_asset_path(marker, original_storyboard_path, "copied_files")
        or original_storyboard_path
    )
    character_current = image_output_current(settings, character_path)
    storyboard_product_lock_current = has_current_storyboard_product_lock(storyboard_path, script.product_name, script.reference_image)
    storyboard_current = (
        storyboard_product_lock_current
        and image_output_current(settings, storyboard_path)
    )
    original_video_path = video_output_path(settings, script.product_name, script.md_path, segment.index)
    video_path = exported_asset_path(marker, original_video_path, "moved_files") or original_video_path
    return {
        "index": segment.index,
        "title": segment.title,
        "time_range": segment.time_range,
        "reuses_character": segment.reuses_character,
        "referenced_character_index": segment.referenced_character_index,
        "character_path": str(character_path),
        "character_exists": character_current,
        "character_stale": character_path.exists() and not character_current,
        "character_stale_reason": image_stale_reason(settings, character_path) if character_path.exists() and not character_current else "",
        "character_url": artifact_url(character_path, settings.api_base_path) if character_current else None,
        "storyboard_path": str(storyboard_path),
        "storyboard_exists": storyboard_current,
        "storyboard_stale": storyboard_path.exists() and not storyboard_current,
        "storyboard_stale_reason": image_stale_reason(settings, storyboard_path, product_lock_current=storyboard_product_lock_current) if storyboard_path.exists() and not storyboard_current else "",
        "storyboard_url": artifact_url(storyboard_path, settings.api_base_path) if storyboard_current else None,
        "video_path": str(video_path),
        "video_exists": video_path.exists(),
        "video_url": artifact_url(video_path, settings.api_base_path) if video_path.exists() else None,
    }


def summarize_catalog(settings: Settings, scripts: Iterable[ScriptFile]) -> Dict[str, int]:
    product_names = set()
    script_count = 0
    segment_count = 0
    missing_references = 0
    complete_scripts = 0
    video_scripts = 0
    exported_scripts = 0
    cleaned_exported_scripts = 0
    for script in scripts:
        product_names.add(script.product_name)
        script_count += 1
        segment_count += len(script.segments)
        if not getattr(script, "reference_images", ()) and script.reference_image is None:
            missing_references += 1
        exported = bool(getattr(script, "exported", False)) or script_exported(script.md_path)
        marker = read_export_marker(script.md_path) if exported else {}
        segments = [segment_to_dict(settings, script, segment, marker=marker) for segment in script.segments]
        generation_status = script_generation_status(script, segments, marker)
        if generation_status["has_video"]:
            video_scripts += 1
        if generation_status["full_mode_complete"]:
            complete_scripts += 1
        if exported:
            exported_scripts += 1
            if bool(marker.get("media_cleaned")):
                cleaned_exported_scripts += 1
    return {
        "products": len(product_names),
        "scripts": script_count,
        "segments": segment_count,
        "missing_references": missing_references,
        "video_scripts": video_scripts,
        "complete_scripts": complete_scripts,
        "full_mode_completed_scripts": complete_scripts,
        "exported_scripts": exported_scripts,
        "cleaned_exported_scripts": cleaned_exported_scripts,
    }


def script_generation_status(
    script: ScriptFile,
    segments: List[Dict[str, object]],
    marker: Dict[str, Any],
) -> Dict[str, bool]:
    exported_names = {
        Path(str(path)).name
        for key in ("copied_files", "moved_files")
        for path in marker.get(key, [])
        if path
    }
    exported_names.update(
        str(item.get("name") or Path(str(item.get("path") or "")).name)
        for item in marker.get("media_files", [])
        if isinstance(item, dict)
    )
    has_video = False
    full_mode_complete = bool(segments)
    for parsed, segment in zip(script.segments, segments):
        character_name = character_image_path(script.md_path, parsed.index).name
        storyboard_name = storyboard_image_path(script.md_path, parsed.index).name
        video_name = next(
            (
                name
                for name in exported_names
                if name.startswith(f"{script.md_path.stem}-片段{parsed.index}-")
                and Path(name).suffix.lower() in {".mp4", ".mov", ".webm"}
            ),
            "",
        )
        character_done = bool(segment["character_exists"]) or character_name in exported_names
        storyboard_done = bool(segment["storyboard_exists"]) or storyboard_name in exported_names
        video_done = bool(segment["video_exists"]) or bool(video_name)
        has_video = has_video or video_done
        full_mode_complete = full_mode_complete and character_done and storyboard_done and video_done
    return {"has_video": has_video, "full_mode_complete": full_mode_complete}


def script_is_complete(settings: Settings, script: ScriptFile) -> bool:
    if not script.segments:
        return False
    if bool(getattr(script, "exported", False)) or script_exported(script.md_path):
        return True
    return not missing_assets_for_script(settings, script)


def missing_assets_for_script(settings: Settings, script: ScriptFile) -> List[str]:
    missing: List[str] = []
    prefix = settings.artifact_prefix
    marker = read_export_marker(script.md_path) if bool(getattr(script, "exported", False)) or script_exported(script.md_path) else {}
    if marker:
        return []
    for segment in script.segments:
        original_character_path = character_image_path(script.md_path, segment.index, prefix)
        character_path = (
            exported_asset_path(marker, original_character_path, "moved_files")
            or exported_asset_path(marker, original_character_path, "copied_files")
            or original_character_path
        )
        if not image_output_current(settings, character_path):
            missing.append(f"片段{segment.index}人物图")
        original_storyboard_path = storyboard_image_path(script.md_path, segment.index, prefix)
        storyboard_path = (
            exported_asset_path(marker, original_storyboard_path, "moved_files")
            or exported_asset_path(marker, original_storyboard_path, "copied_files")
            or original_storyboard_path
        )
        storyboard_current = (
            has_current_storyboard_product_lock(storyboard_path, script.product_name, script.reference_image)
            and image_output_current(settings, storyboard_path)
        )
        if not storyboard_current:
            missing.append(f"片段{segment.index}故事版")
        original_video_path = video_output_path(settings, script.product_name, script.md_path, segment.index)
        video_path = exported_asset_path(marker, original_video_path, "moved_files") or original_video_path
        if not video_path.exists():
            missing.append(f"片段{segment.index}视频")
    return missing
