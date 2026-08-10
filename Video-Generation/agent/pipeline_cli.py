from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import load_settings
from .exporter import export_completed_scripts
from .files import scan_scripts
from .tasks import JobManager


RESULT_PREFIX = "OPC_PIPELINE_RESULT="


def existing_exports(settings, requested: list[str]) -> list[dict]:
    selected = {str(Path(path).expanduser().resolve()) for path in requested}
    exports = []
    root = settings.completed_script_root
    if not root.is_dir():
        return exports
    for marker_path in root.rglob("*.exported.json"):
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        active_path = str(Path(str(marker.get("active_md_path") or "")).expanduser().resolve())
        export_dir = Path(str(marker.get("export_dir") or ""))
        if active_path in selected and export_dir.is_dir():
            exports.append(
                {
                    "product_name": str(marker.get("product_name") or ""),
                    "md_name": Path(str(marker.get("md_path") or "")).name,
                    "md_path": str(marker.get("md_path") or ""),
                    "active_md_path": active_path,
                    "export_dir": str(export_dir),
                    "copied": len(marker.get("copied_files") or []),
                    "moved": len(marker.get("moved_files") or []),
                }
            )
    return exports


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one independent video-generation pipeline job.")
    parser.add_argument("--provider", choices=("omni", "grok"), required=True)
    parser.add_argument("--script", action="append", dest="scripts", required=True)
    parser.add_argument("--reference-image", required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--minimum-success", type=int, default=1)
    args = parser.parse_args()

    settings = load_settings(args.provider)
    recovered = existing_exports(settings, args.scripts)
    recovered_active_paths = {item["active_md_path"] for item in recovered}
    remaining = [path for path in args.scripts if str(Path(path).resolve()) not in recovered_active_paths]
    job = {"status": "completed", "recovered_exports": len(recovered)}
    exported = []
    skipped = []
    if remaining:
        manager = JobManager(settings)
        job = manager.start(
            stage="all",
            overwrite=False,
            script_paths=remaining,
            script_concurrency=args.concurrency,
            reference_images={path: args.reference_image for path in remaining},
        )
        while job["status"] in {"queued", "running"}:
            time.sleep(1)
            job = manager.get(job["id"])
        scripts = scan_scripts(settings)
        fresh = export_completed_scripts(settings, scripts, remaining)
        exported = fresh.get("exported") or []
        skipped = fresh.get("skipped") or []
    export = {"provider": settings.provider, "exported": [*recovered, *exported], "skipped": skipped}
    payload = {"job": job, "export": export}
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)
    return 0 if len(export.get("exported") or []) >= args.minimum_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
