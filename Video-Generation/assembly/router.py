#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import video_assembly as core


APP_ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_ROOT = Path(__file__).resolve().parent
CONFIRMED_REPORT_PATH = ASSEMBLY_ROOT / "data" / "confirmed-report.json"
MAX_LOG_LINES = 800
router = APIRouter(prefix="/assembly/api", tags=["assembly"])


class AssemblyRequest(BaseModel):
    confirmed: bool = False
    scan_id: str = ""
    script_dirs: list[str] = Field(default_factory=list)
    caption_mode: str = core.DEFAULT_CAPTION_MODE


class CleanupRequest(BaseModel):
    confirmed: bool = False
    verified: bool = False
    scan_id: str = ""
    script_dirs: list[str] = Field(default_factory=list)


class OpenPathRequest(BaseModel):
    path: str = ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def empty_report() -> dict[str, Any]:
    return {
        "scan_id": "",
        "scanned_at": "",
        "pending_root": str(core.PENDING_ROOT),
        "output_root": str(core.OUTPUT_ROOT),
        "total_scripts": 0,
        "by_status": {},
        "by_model": {},
        "items": [],
    }


def read_report() -> dict[str, Any]:
    if not core.REPORT_PATH.exists():
        return empty_report()
    try:
        data = json.loads(core.REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_report()
    return data if isinstance(data, dict) else empty_report()


def scan_now() -> dict[str, Any]:
    if not core.PENDING_ROOT.exists():
        raise RuntimeError(f"待拼接目录不存在：{core.PENDING_ROOT}")
    previous = {
        item.get("script_dir"): item.get("caption_mode")
        for item in read_report().get("items", [])
        if item.get("script_dir")
    }
    items = core.scan_items()
    for item in items:
        try:
            item.caption_mode = core.normalize_caption_mode(previous.get(item.script_dir))
        except ValueError:
            item.caption_mode = core.DEFAULT_CAPTION_MODE
    payload = core.report_payload(items)
    write_json(core.REPORT_PATH, payload)
    return payload


def runtime_checks() -> list[dict[str, Any]]:
    node = core.runtime_binary("node")
    ffmpeg = core.runtime_binary("ffmpeg")
    ffprobe = core.runtime_binary("ffprobe")
    browser = core.browser_path()
    hyperframes_ok = True
    try:
        hyperframes = core.hyperframes_cmd()
        hyperframes_path = Path(hyperframes[-1])
    except SystemExit:
        hyperframes_ok = False
        hyperframes_path = core.RUNTIME_ROOT / "hyperframes"
    checks = [
        ("pending", "待拼接目录", core.PENDING_ROOT, core.PENDING_ROOT.is_dir()),
        ("output", "成品目录", core.OUTPUT_ROOT, core.OUTPUT_ROOT.is_dir()),
        ("node", "Node.js", Path(node or core.RUNTIME_ROOT / "bin" / "node"), bool(node)),
        ("ffmpeg", "FFmpeg", Path(ffmpeg or core.RUNTIME_ROOT / "bin" / "ffmpeg"), bool(ffmpeg)),
        ("ffprobe", "FFprobe", Path(ffprobe or core.RUNTIME_ROOT / "bin" / "ffprobe"), bool(ffprobe)),
        ("hyperframes", "HyperFrames", hyperframes_path, hyperframes_ok),
        ("chrome", "Chrome", Path(browser or core.RUNTIME_ROOT / "chrome"), bool(browser)),
        ("gsap", "本地 GSAP", core.VENDOR_ROOT / "gsap.min.js", (core.VENDOR_ROOT / "gsap.min.js").is_file()),
    ]
    return [
        {"key": key, "label": label, "path": str(path), "ok": ok}
        for key, label, path, ok in checks
    ]


def output_items(report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    report = report or read_report()
    outputs: list[dict[str, Any]] = []
    for item in report.get("items", []):
        if item.get("status") != "done" or not item.get("output_path"):
            continue
        path = Path(item["output_path"])
        if not path.is_file():
            continue
        stat = path.stat()
        outputs.append(
            {
                "name": path.name,
                "path": str(path),
                "relative": str(path.relative_to(core.OUTPUT_ROOT)),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    outputs.sort(key=lambda item: item["modified"], reverse=True)
    return outputs[:120]


class AssemblyJob:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "id": "",
            "status": "idle",
            "total": 0,
            "completed": 0,
            "current": "",
            "logs": [],
            "outputs": [],
            "started_at": 0.0,
            "finished_at": 0.0,
            "error": "",
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            payload = copy.deepcopy(self.state)
        total = int(payload.get("total") or 0)
        completed = int(payload.get("completed") or 0)
        payload["percent"] = round((completed / total) * 100) if total else 0
        payload["running"] = payload.get("status") in {"queued", "running", "cancelling"}
        return payload

    def start(self, report: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        with self.lock:
            if self.state.get("status") in {"queued", "running", "cancelling"}:
                raise RuntimeError("已有拼接任务正在运行")
            write_json(CONFIRMED_REPORT_PATH, report)
            job_id = uuid.uuid4().hex
            self.cancel_requested = False
            self.state = {
                "id": job_id,
                "status": "queued",
                "total": len(selected),
                "completed": 0,
                "current": "等待本地渲染器启动",
                "logs": [f"已确认 {len(selected)} 个待拼接项目"],
                "outputs": [],
                "started_at": time.time(),
                "finished_at": 0.0,
                "error": "",
            }
        thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        thread.start()
        return self.snapshot()

    def _append_log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with self.lock:
            logs = self.state.setdefault("logs", [])
            logs.append(line)
            if len(logs) > MAX_LOG_LINES:
                del logs[:-MAX_LOG_LINES]

    def _run(self, job_id: str) -> None:
        command = [
            sys.executable,
            str(Path(core.__file__).resolve()),
            "assemble",
            "--all-missing",
            "--report",
            str(CONFIRMED_REPORT_PATH),
        ]
        env = core.runtime_env()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            with self.lock:
                if self.cancel_requested:
                    self.state["status"] = "cancelled"
                    self.state["finished_at"] = time.time()
                    return
                self.state["status"] = "running"
                self.state["current"] = "正在分析片段"
            process = subprocess.Popen(
                command,
                cwd=str(APP_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with self.lock:
                self.process = process
            assert process.stdout is not None
            for line in process.stdout:
                clean = line.rstrip()
                self._append_log(clean)
                if clean.startswith("ASSEMBLE "):
                    with self.lock:
                        self.state["current"] = clean.removeprefix("ASSEMBLE ")
                elif clean.lstrip().startswith("output: "):
                    raw_path = clean.strip().removeprefix("output: ").split(" (", 1)[0]
                    with self.lock:
                        self.state["completed"] = min(
                            int(self.state.get("total") or 0),
                            int(self.state.get("completed") or 0) + 1,
                        )
                        self.state.setdefault("outputs", []).append(raw_path)
            return_code = process.wait()
            with self.lock:
                cancelled = self.cancel_requested
                self.process = None
            if cancelled:
                final_status = "cancelled"
                error = "任务已终止"
            elif return_code == 0:
                final_status = "completed"
                error = ""
            else:
                final_status = "failed"
                error = f"拼接进程退出，状态码 {return_code}"
            with self.lock:
                if self.state.get("id") == job_id:
                    self.state["status"] = final_status
                    self.state["current"] = ""
                    self.state["finished_at"] = time.time()
                    self.state["error"] = error
            if final_status == "completed":
                scan_now()
        except Exception as exc:  # Keep the local server alive and expose the failure in the UI.
            with self.lock:
                self.process = None
                self.state["status"] = "failed"
                self.state["current"] = ""
                self.state["finished_at"] = time.time()
                self.state["error"] = str(exc)
            self._append_log(f"错误：{exc}")

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            if self.state.get("status") not in {"queued", "running"}:
                return self.snapshot()
            self.cancel_requested = True
            self.state["status"] = "cancelling"
            self.state["current"] = "正在终止任务"
            process = self.process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return self.snapshot()


JOB = AssemblyJob()


def confirmed_report(
    scan_id: str,
    script_dirs: list[str],
    caption_mode: str = core.DEFAULT_CAPTION_MODE,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = read_report()
    if not scan_id or report.get("scan_id") != scan_id:
        raise ValueError("扫描结果已变化，请重新扫描后再确认")
    missing = {
        item["script_dir"]: item
        for item in report.get("items", [])
        if item.get("status") == "missing"
    }
    selected_paths = list(dict.fromkeys(script_dirs))
    if not selected_paths:
        raise ValueError("请至少选择一个待拼接项目")
    unknown = [path for path in selected_paths if path not in missing]
    if unknown:
        raise ValueError("选择项不属于本次扫描，请重新扫描")
    normalized_caption_mode = core.normalize_caption_mode(caption_mode)
    if normalized_caption_mode == "karaoke" and not core.caption_runtime_ready():
        raise RuntimeError("TikTok 卡拉 OK 字幕运行依赖不完整")
    for item in report.get("items", []):
        if item.get("script_dir") in selected_paths:
            item["caption_mode"] = normalized_caption_mode
    write_json(core.REPORT_PATH, report)
    selected = [missing[path] for path in selected_paths]
    payload = copy.deepcopy(report)
    selected_set = set(selected_paths)
    for item in payload.get("items", []):
        if item.get("status") == "missing" and item.get("script_dir") not in selected_set:
            item["status"] = "skipped"
    payload["confirmed_at"] = time.time()
    payload["confirmed_script_dirs"] = selected_paths
    return payload, selected


def confirmed_cleanup_items(scan_id: str, script_dirs: list[str]) -> list[core.ScriptItem]:
    report = read_report()
    if not scan_id or report.get("scan_id") != scan_id:
        raise ValueError("扫描结果已变化，请重新扫描后再确认")
    eligible = {
        item["script_dir"]: item
        for item in report.get("items", [])
        if item.get("status") == "done" and item.get("cleanup_eligible") is True
    }
    selected_paths = list(dict.fromkeys(script_dirs))
    if not selected_paths:
        raise ValueError("请至少选择一个待清理项目")
    unknown = [path for path in selected_paths if path not in eligible]
    if unknown:
        raise ValueError("选择项不再可清理，请重新扫描")
    return [core.item_from_dict(eligible[path]) for path in selected_paths]


def allowed_local_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    roots = [APP_ROOT.resolve(), core.PENDING_ROOT.resolve(), core.OUTPUT_ROOT.resolve()]
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError("只能打开片段合成相关目录")
    if not path.exists():
        raise ValueError("路径不存在")
    return path


def api_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/state")
def state() -> dict[str, Any]:
    report = read_report()
    checks = runtime_checks()
    return {
        "report": report,
        "job": JOB.snapshot(),
        "checks": checks,
        "offline_ready": all(item["ok"] for item in checks),
        "outputs": output_items(report),
        "app_root": str(APP_ROOT),
    }


@router.get("/job")
def job() -> dict[str, Any]:
    return {"job": JOB.snapshot()}


@router.get("/outputs")
def outputs() -> dict[str, Any]:
    return {"outputs": output_items(), "root": str(core.OUTPUT_ROOT)}


@router.post("/scan")
def scan() -> dict[str, Any]:
    try:
        if JOB.snapshot()["running"]:
            raise RuntimeError("拼接运行中，暂不能重新扫描")
        report = scan_now()
        return {"report": report, "outputs": output_items(report)}
    except (OSError, ValueError, RuntimeError) as exc:
        raise api_error(exc) from exc


@router.post("/assemble", status_code=202)
def assemble(request: AssemblyRequest) -> dict[str, Any]:
    try:
        if not request.confirmed:
            raise ValueError("需要明确确认后才能开始拼接")
        checks = runtime_checks()
        if not all(item["ok"] for item in checks):
            raise RuntimeError("离线运行依赖不完整，请先检查左侧状态")
        report, selected = confirmed_report(
            request.scan_id,
            request.script_dirs,
            request.caption_mode,
        )
        return {"job": JOB.start(report, selected)}
    except (OSError, ValueError, RuntimeError) as exc:
        raise api_error(exc) from exc


@router.post("/cleanup")
def cleanup(request: CleanupRequest) -> dict[str, Any]:
    try:
        if JOB.snapshot()["running"]:
            raise RuntimeError("拼接运行中，暂不能清理素材")
        if not request.confirmed or not request.verified:
            raise ValueError("需要确认成品可用后才能清理素材")
        selected = confirmed_cleanup_items(request.scan_id, request.script_dirs)
        result = core.cleanup_items(selected)
        report = scan_now()
        return {**result, "report": report, "outputs": output_items(report)}
    except (OSError, ValueError, RuntimeError) as exc:
        raise api_error(exc) from exc


@router.post("/cancel")
def cancel() -> dict[str, Any]:
    return {"job": JOB.cancel()}


@router.post("/open")
def open_path(request: OpenPathRequest) -> dict[str, Any]:
    try:
        path = allowed_local_path(request.path)
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": str(path)}
    except (OSError, ValueError, RuntimeError) as exc:
        raise api_error(exc) from exc
