from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import product_slug, safe_name


VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT") or "/__OPC_VAULT_ROOT_NOT_CONFIGURED__"
).expanduser()
HOT_VIDEO_LIBRARY_ROOT = VAULT_ROOT / "wiki" / "视频" / "AI实拍混剪" / "01参考视频"
HYBRID_MATERIAL_TYPES = {"混剪-钩子", "混剪-CTA"}


class ProjectPaths:
    def __init__(self, root: Path, config: Dict[str, Any]) -> None:
        self.root = Path(root)
        self.config = config
        self.slug = product_slug(config)
        self.project_root = self.resolve_project_root()

    def resolve_project_root(self) -> Path:
        product = self.config.get("product") or {}
        configured_path = str(product.get("path") or "").strip()
        if configured_path:
            path = Path(configured_path).expanduser()
            if not path.is_absolute():
                path = self.root / path
            return path.resolve()
        product = self.config.get("product") or {}
        if not str(product.get("slug") or product.get("name") or "").strip():
            return self.root / "product"
        return self.root / "projects" / self.slug

    def ensure(self) -> None:
        for path in [
            self.project_root,
            self.project_root / "collection_runs",
            self.project_root / "runtime_state",
            self.project_root / "diagnostics",
            self.hot_video_dir(),
            self.run_logs_dir(),
        ]:
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_category_path(value: Any) -> List[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(">") if part.strip()] or ["全部"]
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()] or ["全部"]
        return ["全部"]

    def default_result_folder_name(self) -> str:
        return "results"

    def result_folder_name(self) -> str:
        output = self.config.get("output") or {}
        configured = str(output.get("result_folder_name") or "").strip()
        return safe_name(configured or self.default_result_folder_name(), "采集结果", 120)

    def result_dir(self, create: bool = False) -> Path:
        path = self.project_root / "collection_runs" / self.result_folder_name()
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def runtime_state_path(self, name: str) -> Path:
        path = self.project_root / "runtime_state" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def diagnostics_dir(self) -> Path:
        path = self.project_root / "diagnostics"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def collection_run_dir(self, run_stem: str) -> Path:
        return self.result_dir(create=True)

    def collection_csv_path(self, run_stem: str) -> Path:
        safe_stem = safe_name(run_stem, "collection_run")
        return self.collection_run_dir(run_stem) / f"{safe_stem}.csv"

    def product_name(self) -> str:
        product = self.config.get("product") or {}
        return str(product.get("name") or self.slug or "product").strip() or "product"

    def hot_video_dir(self) -> Path:
        hybrid = self.config.get("hybrid") or {}
        material_type = str(hybrid.get("material_type") or "混剪-钩子").strip()
        if material_type not in HYBRID_MATERIAL_TYPES:
            material_type = "混剪-钩子"
        product = self.config.get("product") or {}
        product_name = str(product.get("name") or product.get("slug") or "").strip()
        path = HOT_VIDEO_LIBRARY_ROOT / material_type
        if product_name:
            path /= safe_name(product_name, "product", 120)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def latest_collection_csv(self) -> Optional[Path]:
        collection_root = self.project_root / "collection_runs"
        if not collection_root.exists():
            return None
        candidates = sorted(collection_root.rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                with path.open(encoding="utf-8-sig") as handle:
                    fieldnames = csv.DictReader(handle).fieldnames or []
                if "tiktok_video_url" in fieldnames:
                    return path
            except OSError:
                continue
        return None

    def source_stage_dir(self, source_id: str, stage: str, result_dir: Optional[Path] = None) -> Path:
        base_dir = Path(result_dir) if result_dir else self.project_root
        path = base_dir / "hot_sources" / safe_name(source_id, "unknown_source", 120) / stage
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run_logs_dir(self) -> Path:
        return self.root / "run_logs"

    def report_path(self, stem: str, result_dir: Optional[Path] = None) -> Path:
        path = self.run_logs_dir() / f"{safe_name(stem, 'run_report')}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return Path(path).as_posix()


def infer_source_id(value: str, default: str = "unknown_source") -> str:
    text = str(value or "").strip()
    if not text:
        return default

    path = Path(text)
    parts = list(path.parts)
    if "hot_sources" in parts:
        index = parts.index("hot_sources")
        if index + 1 < len(parts):
            return safe_name(parts[index + 1], default, 120)

    for pattern in [
        r"/video/(\d{10,24})",
        r"(?:video_id|作品ID|Video ID)[^\d]{0,12}(\d{10,24})",
        r"(\d{16,24})",
        r"(\d{10,15})",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    if path.name:
        return safe_name(path.stem, default, 120)
    return default


def source_id_from_row(row: Dict[str, str]) -> str:
    for key in [
        "tiktok_video_url",
        "fastmoss_video_url",
        "video_id",
        "视频ID",
        "作品ID",
        "Video ID",
    ]:
        value = row.get(key, "")
        if value:
            source_id = infer_source_id(value, "")
            if source_id:
                return source_id
    return "unknown_source"
