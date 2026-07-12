#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from opc_engine.core.config_store import load_app_config
from opc_engine.core.project_assets import raw_data_dir, require_product_project


ROOT = Path(__file__).resolve().parents[3]
VAULT_ROOT = Path(
    os.environ.get("OPC_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault"))
).expanduser()
DEFAULT_EXPORTER_DIR = VAULT_ROOT / "tiktok-ads-gmvmax-exporter-py"
EXPORT_FILE_SUFFIXES = {".csv", ".xlsx", ".xlsm"}


def log(message: str) -> None:
    print(message, flush=True)


def load_config() -> dict:
    return load_app_config()


def resolve_path(value: str | None, default: Path | None = None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return default
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sanitize_log(text: str) -> str:
    cleaned = text
    replacements = {
        "TikTok Ads GMV Max": "投放数据平台",
        "TikTok Ads": "投放数据平台",
        "GMV Max": "投放数据平台",
        "GMVMax": "投放数据平台",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"https?://ads\.tiktok\.com[^\s)]+", "投放数据页面", cleaned)
    return cleaned


def collect_export_files(download_root: Path) -> set[Path]:
    if not download_root.exists():
        return set()
    return {
        path.resolve()
        for path in download_root.rglob("*")
        if path.is_file() and path.suffix.lower() in EXPORT_FILE_SUFFIXES
    }


def copy_new_exports(before: set[Path], exporter_dir: Path, output_dir: Path) -> list[Path]:
    download_root = exporter_dir / "downloads"
    after = collect_export_files(download_root)
    new_files = sorted(after - before, key=lambda item: item.stat().st_mtime)
    if not new_files:
        new_files = sorted(after, key=lambda item: item.stat().st_mtime, reverse=True)[:20]

    copied: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in new_files:
        target = output_dir / f"{timestamp()}_{source.name}"
        counter = 2
        while target.exists():
            target = output_dir / f"{timestamp()}_{counter}_{source.name}"
            counter += 1
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def main() -> int:
    config = load_config()
    require_product_project(config, "下载投放数据")
    exporter_dir = resolve_path(
        os.environ.get("AD_PERFORMANCE_EXPORTER_DIR")
        or config.get("ad_performance_exporter_dir")
        or config.get("gmvmax_exporter_dir"),
        DEFAULT_EXPORTER_DIR if DEFAULT_EXPORTER_DIR.exists() else None,
    )
    output_dir = resolve_path(
        os.environ.get("DATA_ATTRIBUTION_OUTPUT_DIR")
        or os.environ.get("OPC_DATA_ATTRIBUTION_OUTPUT_DIR"),
        raw_data_dir("ad_performance", config),
    )

    log("开始下载投放数据")
    log("日期范围: 昨天")
    if not exporter_dir:
        raise RuntimeError("未配置投放数据下载器目录。请先在本地配置 ad_performance_exporter_dir。")
    exporter_script = exporter_dir / "export_gmvmax_creatives.py"
    if not exporter_script.exists():
        raise FileNotFoundError(f"投放数据下载脚本不存在: {exporter_script}")

    before = collect_export_files(exporter_dir / "downloads")
    command = [sys.executable, str(exporter_script)]
    log("执行投放数据下载流程...")
    process = subprocess.Popen(
        command,
        cwd=str(exporter_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout:
        for line in process.stdout:
            log(sanitize_log(line.rstrip()))
    exit_code = process.wait()
    if exit_code != 0:
        log(f"投放数据下载失败，退出码: {exit_code}")
        return exit_code

    copied = copy_new_exports(before, exporter_dir, output_dir)
    if copied:
        log(f"已同步投放数据文件: {len(copied)} 个")
        for path in copied:
            log(f"- {path}")
    else:
        log("未检测到新的投放数据文件，请检查下载器配置或登录状态。")
    log("投放数据下载完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
