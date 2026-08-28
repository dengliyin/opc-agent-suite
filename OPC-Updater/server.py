#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HOST = os.environ.get("OPC_UPDATER_HOST", "0.0.0.0")
PORT = int(os.environ.get("OPC_UPDATER_PORT", "18888"))
REPO_ROOT = Path(os.environ.get("OPC_REPO_ROOT", "/repo"))
CONFIG_ROOT = Path(os.environ.get("OPC_CONFIG_ROOT", "/config"))
STATE_DIR = CONFIG_ROOT / "updater"
STATE_FILE = STATE_DIR / "status.json"
LOG_FILE = STATE_DIR / "update.log"
TOKEN_FILE = STATE_DIR / "updater.token"
BRANCH = os.environ.get("OPC_UPDATE_BRANCH", "main")
PROJECT_NAME = os.environ.get("OPC_COMPOSE_PROJECT", "opc-agent-suite")

CORE_SERVICES = (
    "console",
    "script-analysis",
    "script-generation",
    "script-adaptation",
    "video-generation",
    "finished-video-manager",
    "product-script-rewrite",
    "hybrid-script-adaptation",
    "hybrid-video-mixer",
    "hybrid-script-analysis",
    "hybrid-script-generation",
    "hybrid-audio-generation",
    "auto-publish-pipeline",
    "unified-script-agent",
)

AI_RESTART_GROUPS = {
    "video_analysis": ("script-analysis", "hybrid-script-analysis"),
    "text": (
        "script-generation",
        "script-adaptation",
        "product-script-rewrite",
        "hybrid-script-adaptation",
        "hybrid-script-generation",
        "unified-script-agent",
    ),
    "otu": ("video-generation",),
    "grok": ("video-generation",),
}

_state_lock = threading.Lock()
_update_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_private_files() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.is_file():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        TOKEN_FILE.chmod(0o600)
    if not STATE_FILE.is_file():
        write_state({"state": "idle", "phase": "ready", "message": "更新服务已就绪"})
    LOG_FILE.touch(exist_ok=True)
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def read_state() -> dict:
    with _state_lock:
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"state": "idle", "phase": "ready", "message": "更新服务已就绪"}
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        payload["log_tail"] = lines[-80:]
        return payload


def write_state(changes: dict) -> dict:
    with _state_lock:
        try:
            current = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        current.update(changes)
        current["updated_at"] = now_iso()
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, STATE_FILE)
        return current


def log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", message.replace("\x00", ""))
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now_iso()}] {safe}\n")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    log("执行：" + " ".join(command))
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.stdout:
        for line in result.stdout.rstrip().splitlines():
            log(line)
    if check and result.returncode:
        raise RuntimeError(f"命令执行失败（退出码 {result.returncode}）：{' '.join(command)}")
    return result


def compose_command(*arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--project-directory",
        str(REPO_ROOT),
        *arguments,
    ]


def current_commit() -> str:
    return run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()


def dirty_paths() -> list[str]:
    result = run(["git", "status", "--porcelain"], check=False)
    return [line[3:] if len(line) > 3 else line for line in result.stdout.splitlines() if line.strip()]


def configured_services() -> tuple[str, ...]:
    result = run(compose_command("config", "--services"))
    services = tuple(line.strip() for line in result.stdout.splitlines() if line.strip() != "opc-updater")
    if "console" not in services:
        raise RuntimeError("Docker 配置中没有找到 8888 控制台")
    return services


def update_phase(phase: str, message: str, **extra: object) -> None:
    write_state({"state": "running", "phase": phase, "message": message, **extra})
    log(message)


def ai_restart_services(group: str) -> tuple[str, ...]:
    try:
        return AI_RESTART_GROUPS[group]
    except KeyError as exc:
        raise ValueError("未知的全局 AI 配置组") from exc


def perform_ai_restart(group: str) -> None:
    services = ai_restart_services(group)
    try:
        LOG_FILE.write_text("", encoding="utf-8")
        write_state(
            {
                "state": "running",
                "task": "ai_restart",
                "phase": "restart",
                "message": "正在重启相关 Agent",
                "group": group,
                "services": list(services),
                "started_at": now_iso(),
                "finished_at": None,
                "old_commit": None,
                "new_commit": None,
                "dirty_paths": [],
            }
        )
        log("正在重启相关 Agent：" + "、".join(services))
        run(compose_command("restart", *services))
        update_phase("verify", "正在等待相关 Agent 恢复健康")
        run(compose_command("up", "-d", "--wait", "--wait-timeout", "180", *services))
        write_state(
            {
                "state": "complete",
                "task": "ai_restart",
                "phase": "complete",
                "message": "相关 Agent 已重启并恢复健康",
                "group": group,
                "services": list(services),
                "finished_at": now_iso(),
            }
        )
        log("相关 Agent 已恢复健康")
    except Exception as exc:
        log(f"Agent 重启失败：{exc}")
        write_state(
            {
                "state": "failed",
                "task": "ai_restart",
                "phase": "failed",
                "message": str(exc),
                "group": group,
                "services": list(services),
                "finished_at": now_iso(),
            }
        )
    finally:
        _update_lock.release()


def schedule_reload() -> None:
    def reload_process() -> None:
        os.execv(sys.executable, [sys.executable, "-u", str(Path(__file__).resolve())])

    timer = threading.Timer(3, reload_process)
    timer.daemon = True
    timer.start()


def perform_update() -> None:
    try:
        LOG_FILE.write_text("", encoding="utf-8")
        write_state(
            {
                "state": "running",
                "task": "system_update",
                "phase": "preflight",
                "message": "正在检查本地代码",
                "started_at": now_iso(),
                "finished_at": None,
                "old_commit": None,
                "new_commit": None,
                "group": None,
                "services": [],
                "dirty_paths": [],
            }
        )
        run(["git", "config", "--global", "--add", "safe.directory", str(REPO_ROOT)], check=False)
        if run(["git", "rev-parse", "--is-inside-work-tree"], check=False).returncode:
            raise RuntimeError("当前程序目录不是 Git 仓库，无法自动更新")
        branch = run(["git", "branch", "--show-current"]).stdout.strip()
        if branch != BRANCH:
            write_state(
                {
                    "state": "blocked",
                    "phase": "preflight",
                    "message": f"当前位于 {branch or '游离提交'}，请先切换到 {BRANCH} 后再更新",
                    "finished_at": now_iso(),
                }
            )
            return
        dirty = dirty_paths()
        if dirty:
            write_state(
                {
                    "state": "blocked",
                    "phase": "preflight",
                    "message": "检测到尚未提交的本地改动。为避免文件被覆盖，本次更新已停止。",
                    "dirty_paths": dirty,
                    "finished_at": now_iso(),
                }
            )
            log("更新已停止，存在本地改动：" + "、".join(dirty))
            return

        local_commit = current_commit()
        update_phase(
            "prepare",
            "正在应用已手动拉取的本地代码",
            old_commit=local_commit,
            new_commit=local_commit,
        )

        update_phase("validate", "正在检查 Docker 配置", new_commit=local_commit)
        run(compose_command("config", "--quiet"))
        services = configured_services()

        update_phase("migrate", "正在迁移旧配置并保留现有设置")
        run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "migrate_legacy_ai_config.py"),
                "--repo-root",
                str(REPO_ROOT),
                "--config-dir",
                str(CONFIG_ROOT),
            ]
        )

        update_phase("rebuild", "正在重建并重启全部 Agent，这期间 8888 可能短暂断开")
        run(compose_command("up", "-d", "--build", "--wait", "--wait-timeout", "600", *services))

        update_phase("verify", "正在确认全部 Agent 已恢复正常")
        run(compose_command("ps", *services))
        write_state(
            {
                "state": "complete",
                "phase": "complete",
                "message": "本地更新完成，8888 和全部 Agent 已恢复正常",
                "finished_at": now_iso(),
                "old_commit": local_commit,
                "new_commit": local_commit,
            }
        )
        log("更新完成")
        schedule_reload()
    except Exception as exc:
        log(f"更新失败：{exc}")
        write_state(
            {
                "state": "failed",
                "phase": "failed",
                "message": str(exc),
                "finished_at": now_iso(),
            }
        )
    finally:
        _update_lock.release()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        supplied = self.headers.get("X-OPC-Updater-Token", "")
        expected = ensure_private_files()
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 65536:
            raise ValueError("请求内容过大")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "OPC-Updater"})
        elif path == "/status" and self.authorized():
            self.send_json(200, read_state())
        elif path == "/status":
            self.send_json(403, {"error": "Forbidden"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/update", "/restart-ai-agents"}:
            self.send_json(404, {"error": "Not found"})
            return
        if not self.authorized():
            self.send_json(403, {"error": "Forbidden"})
            return
        group = ""
        if path == "/restart-ai-agents":
            try:
                payload = self.read_json()
                if not isinstance(payload, dict):
                    raise ValueError("AI 重启请求格式错误")
                group = str(payload.get("group") or "").strip()
                services = ai_restart_services(group)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
        if not _update_lock.acquire(blocking=False):
            self.send_json(409, read_state())
            return
        if path == "/restart-ai-agents":
            write_state(
                {
                    "state": "running",
                    "task": "ai_restart",
                    "phase": "queued",
                    "message": "Agent 重启任务已开始",
                    "group": group,
                    "services": list(services),
                }
            )
            thread = threading.Thread(target=perform_ai_restart, args=(group,), daemon=True)
            message = "Agent 重启任务已开始"
        else:
            thread = threading.Thread(target=perform_update, daemon=True)
            message = "更新任务已开始"
        thread.start()
        self.send_json(202, {"state": "running", "message": message, "group": group or None})

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    ensure_private_files()
    if read_state().get("state") == "running":
        write_state(
            {
                "state": "failed",
                "phase": "interrupted",
                "message": "上一次更新被意外中断，请重新点击更新",
                "finished_at": now_iso(),
            }
        )
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"OPC 独立更新服务已启动: http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
