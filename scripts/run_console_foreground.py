#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OPC-Agent-Suite"
    if os.name == "nt"
    else Path.home() / "Library" / "Application Support" / "OPC-Agent-Suite"
)
DEFAULT_ENV_FILE = LOCAL_CONFIG_ROOT / ".env"


def storage_identity(vault_root: Path) -> tuple[int, int, int | None]:
    stat = vault_root.stat()
    if hasattr(os, "statvfs"):
        statvfs = os.statvfs(vault_root)
        return stat.st_dev, stat.st_ino, getattr(statvfs, "f_fsid", None)
    return stat.st_dev, stat.st_ino, None


def verify_vault_access(vault_root: Path) -> tuple[int, int, int | None]:
    try:
        with os.scandir(vault_root) as entries:
            next(entries, None)
    except OSError as exc:
        raise RuntimeError(f"OPC_VAULT_ROOT 不可读：{vault_root}: {exc}") from exc

    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".opc-storage-check-", dir=vault_root)
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"opc-storage-check")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RuntimeError(f"OPC_VAULT_ROOT 不可写：{vault_root}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return storage_identity(vault_root)


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
        if os.name == "nt":
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                try:
                    import json

                    value = json.loads(value)
                except (TypeError, ValueError):
                    value = value[1:-1]
            elif len(value) >= 2 and value[0] == value[-1] == "'":
                value = value[1:-1]
        else:
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
    verify_vault_access(vault_root)

    template_root = ROOT_DIR / "storage-template"
    if not template_root.is_dir():
        raise RuntimeError(f"存储目录模板不存在：{template_root}")
    for template_dir in sorted(path for path in template_root.rglob("*") if path.is_dir()):
        (vault_root / template_dir.relative_to(template_root)).mkdir(parents=True, exist_ok=True)
    return vault_root


def wait_for_storage_layout() -> Path:
    while True:
        try:
            return ensure_storage_layout()
        except RuntimeError as exc:
            print(f"控制台等待资料库恢复：{exc}", file=sys.stderr, flush=True)
            time.sleep(5)


def main() -> None:
    env_file = Path(os.environ.get("OPC_ENV_FILE", DEFAULT_ENV_FILE)).expanduser()
    load_env(env_file)
    wait_for_storage_layout()
    os.environ["KESAI_APP_NO_OPEN"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"

    console_dir = ROOT_DIR / "OPC-Console"
    os.chdir(console_dir)
    command = [sys.executable, str(console_dir / "kesai_app.py")]
    if os.name == "nt":
        raise SystemExit(subprocess.call(command, env=os.environ))
    os.execve(sys.executable, command, os.environ)


if __name__ == "__main__":
    main()
