#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from run_console_foreground import ROOT_DIR, ensure_storage_layout, load_env


def load_console_app():
    path = ROOT_DIR / "OPC-Console" / "kesai_app.py"
    spec = importlib.util.spec_from_file_location("opc_console_service_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Agent 注册表：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：run_agent_foreground.py <service-id>")

    env_file = Path(os.environ.get("OPC_ENV_FILE", ROOT_DIR / ".env"))
    load_env(env_file)
    ensure_storage_layout()
    app = load_console_app()
    service_id = sys.argv[1]
    if service_id not in app.SERVICES:
        raise SystemExit(f"未知 Agent：{service_id}")

    service = app.SERVICES[service_id]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if service_id in {"collect", "hybrid_collect"} and not env.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") and chrome_path.exists():
        env["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = str(chrome_path)

    command = [str(part) for part in service["command"]]
    cwd = Path(service.get("launch_cwd", service["cwd"]))
    os.chdir(cwd)
    os.execvpe(command[0], command, env)


if __name__ == "__main__":
    main()
