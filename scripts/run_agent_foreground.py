#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from run_console_foreground import (
    DEFAULT_ENV_FILE,
    ROOT_DIR,
    ensure_storage_layout,
    load_env,
    storage_identity,
)


MONITOR_INTERVAL_SECONDS = 5
HEALTH_PROBE_INTERVAL_SECONDS = 30
STARTUP_PROBE_INTERVAL_SECONDS = 2
PERMISSION_ERROR_MARKERS = (b"operation not permitted", b"permissionerror", b"[errno 1]")


def load_console_app():
    path = ROOT_DIR / "OPC-Console" / "kesai_app.py"
    spec = importlib.util.spec_from_file_location("opc_console_service_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Agent 注册表：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response_has_permission_error(payload: bytes) -> bool:
    lowered = payload.lower()
    return any(marker in lowered for marker in PERMISSION_ERROR_MARKERS)


def write_health_status(path: Path, *, healthy: bool, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "healthy": healthy,
        "checked_at": time.time(),
        "detail": detail[:1000],
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def probe_service(service: dict) -> tuple[bool, bool, str]:
    url = urljoin(service["url"], service["health_path"].lstrip("/"))
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            healthy = 200 <= response.status < 300
            return healthy, response_has_permission_error(body), f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        body = exc.read()
        detail = body.decode("utf-8", errors="replace")[:1000]
        return False, response_has_permission_error(body), f"HTTP {exc.code}: {detail}"
    except OSError as exc:
        detail = str(exc)
        return False, response_has_permission_error(detail.encode()), detail


def stop_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def wait_for_vault(status_path: Path) -> tuple[Path, tuple[int, int, int | None]]:
    while True:
        try:
            vault_root = ensure_storage_layout()
            return vault_root, storage_identity(vault_root)
        except RuntimeError as exc:
            write_health_status(status_path, healthy=False, detail=str(exc))
            print(f"Agent 等待资料库恢复：{exc}", file=sys.stderr, flush=True)
            time.sleep(MONITOR_INTERVAL_SECONDS)


def supervise(service: dict, command: list[str], cwd: Path, env: dict[str, str]) -> int:
    status_path = Path(service["health_status_path"])
    child_holder: dict[str, subprocess.Popen | None] = {"child": None}

    def forward_signal(signum: int, _frame) -> None:
        child = child_holder["child"]
        if child is not None:
            stop_child(child)
        write_health_status(status_path, healthy=False, detail=f"stopped by signal {signum}")
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    while True:
        vault_root, initial_identity = wait_for_vault(status_path)
        child = subprocess.Popen(command, cwd=cwd, env=env)
        child_holder["child"] = child
        next_storage_check = 0.0
        next_health_probe = 0.0
        restart_reason = ""

        while child.poll() is None:
            now = time.monotonic()
            if now >= next_storage_check:
                next_storage_check = now + MONITOR_INTERVAL_SECONDS
                try:
                    with os.scandir(vault_root) as entries:
                        next(entries, None)
                    if storage_identity(vault_root) != initial_identity:
                        restart_reason = "检测到资料库所在磁盘重新挂载"
                except OSError as exc:
                    restart_reason = f"资料库访问失败：{exc}"

            if not restart_reason and now >= next_health_probe:
                healthy, permission_error, detail = probe_service(service)
                next_health_probe = now + (
                    HEALTH_PROBE_INTERVAL_SECONDS
                    if healthy or detail.startswith("HTTP ")
                    else STARTUP_PROBE_INTERVAL_SECONDS
                )
                write_health_status(status_path, healthy=healthy, detail=detail)
                if permission_error:
                    restart_reason = f"业务探针检测到权限错误：{detail}"

            if restart_reason:
                print(f"Agent 将自动重启：{restart_reason}", file=sys.stderr, flush=True)
                write_health_status(status_path, healthy=False, detail=restart_reason)
                stop_child(child)
                time.sleep(MONITOR_INTERVAL_SECONDS)
                break
            time.sleep(1)

        if restart_reason:
            continue

        return_code = child.returncode or 0
        write_health_status(status_path, healthy=False, detail=f"Agent 已退出，状态码 {return_code}")
        return return_code


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：run_agent_foreground.py <service-id>")

    env_file = Path(os.environ.get("OPC_ENV_FILE", DEFAULT_ENV_FILE)).expanduser()
    load_env(env_file)
    app = load_console_app()
    service_id = sys.argv[1]
    if service_id not in app.SERVICES:
        raise SystemExit(f"未知 Agent：{service_id}")

    service = app.SERVICES[service_id]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if os.name != "nt":
        chrome_path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if service_id in {"collect", "hybrid_collect"} and not env.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") and chrome_path.exists():
            env["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = str(chrome_path)

    command = [str(part) for part in service["command"]]
    if service_id == "finished":
        command[0] = sys.executable
    cwd = Path(service.get("launch_cwd", service["cwd"]))
    raise SystemExit(supervise(service, command, cwd, env))


if __name__ == "__main__":
    main()
