#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        if not separator or not key.strip().isidentifier():
            continue
        values = shlex.split(raw_value, comments=True, posix=True)
        value = " ".join(values) if values else ""
        os.environ[key.strip()] = os.path.expandvars(value)


def ensure_storage_layout() -> Path:
    configured = os.environ.get("OPC_VAULT_ROOT", "").strip()
    if not configured:
        raise RuntimeError("OPC_VAULT_ROOT 未配置，请先设置本机 Obsidian Vault 路径")
    vault_root = Path(configured).expanduser()
    if not vault_root.is_dir():
        raise RuntimeError(f"OPC_VAULT_ROOT 不存在或外接盘未挂载：{vault_root}")
    if not os.access(vault_root, os.W_OK):
        raise RuntimeError(f"OPC_VAULT_ROOT 不可写：{vault_root}")

    template_root = ROOT_DIR / "storage-template"
    if not template_root.is_dir():
        raise RuntimeError(f"存储目录模板不存在：{template_root}")
    for template_dir in sorted(path for path in template_root.rglob("*") if path.is_dir()):
        (vault_root / template_dir.relative_to(template_root)).mkdir(parents=True, exist_ok=True)
    return vault_root


def main() -> None:
    env_file = Path(os.environ.get("OPC_ENV_FILE", ROOT_DIR / ".env"))
    load_env(env_file)
    ensure_storage_layout()
    os.environ["KESAI_APP_NO_OPEN"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"

    console_dir = ROOT_DIR / "OPC-Console"
    os.chdir(console_dir)
    os.execve(sys.executable, [sys.executable, str(console_dir / "kesai_app.py")], os.environ)


if __name__ == "__main__":
    main()
