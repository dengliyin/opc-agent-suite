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


def main() -> None:
    env_file = Path(os.environ.get("OPC_ENV_FILE", ROOT_DIR / ".env"))
    load_env(env_file)
    os.environ["KESAI_APP_NO_OPEN"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"

    console_dir = ROOT_DIR / "OPC-Console"
    os.chdir(console_dir)
    os.execve(sys.executable, [sys.executable, str(console_dir / "kesai_app.py")], os.environ)


if __name__ == "__main__":
    main()
