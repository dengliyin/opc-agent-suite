#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import random
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import video_assembly as core


APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = APP_ROOT / "static"
CONFIRMED_REPORT_PATH = APP_ROOT / "data" / "confirmed-report.json"
MAX_LOG_LINES = 800


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
        item.get("script_dir"): item.get("sticker")
        for item in read_report().get("items", [])
        if item.get("script_dir")
    }
    items = core.scan_items()
    for item in items:
        try:
            item.sticker = core.normalize_sticker_options(previous.get(item.script_dir))
        except ValueError:
            item.sticker = core.normalize_sticker_options(None)
    payload = core.report_payload(items)
    write_json(core.REPORT_PATH, payload)
    return payload


def runtime_checks() -> list[dict[str, Any]]:
    checks = [
        ("pending", "待拼接目录", core.PENDING_ROOT, core.PENDING_ROOT.is_dir()),
        ("output", "成品目录", core.OUTPUT_ROOT, core.OUTPUT_ROOT.is_dir()),
        ("node", "Node.js", core.RUNTIME_ROOT / "bin" / "node", (core.RUNTIME_ROOT / "bin" / "node").is_file()),
        ("ffmpeg", "FFmpeg", core.RUNTIME_ROOT / "bin" / "ffmpeg", (core.RUNTIME_ROOT / "bin" / "ffmpeg").is_file()),
        ("ffprobe", "FFprobe", core.RUNTIME_ROOT / "bin" / "ffprobe", (core.RUNTIME_ROOT / "bin" / "ffprobe").is_file()),
        (
            "hyperframes",
            "HyperFrames",
            core.RUNTIME_ROOT / "hyperframes" / "package" / "dist" / "cli.js",
            (core.RUNTIME_ROOT / "hyperframes" / "package" / "dist" / "cli.js").is_file(),
        ),
        (
            "chrome",
            "离线 Chrome",
            core.RUNTIME_ROOT / "chrome" / "chrome-headless-shell",
            (core.RUNTIME_ROOT / "chrome" / "chrome-headless-shell").is_file(),
        ),
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
    sticker: dict[str, Any] | None = None,
    sticker_random_country: str = "",
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
    if sticker is not None and not isinstance(sticker, dict):
        raise ValueError("文字贴纸设置格式无效")
    sticker_options = core.normalize_sticker_options(sticker)
    randomized_texts: dict[str, str] = {}
    if sticker_random_country:
        if not sticker_options["enabled"]:
            raise ValueError("随机分配文案前请先启用文字贴纸")
        products = {str(missing[path].get("product") or "") for path in selected_paths}
        if len(products) != 1:
            raise ValueError("随机分配文案时只能选择同一产品")
        library = core.load_sticker_library(products.pop())
        country = next(
            (item for item in library["countries"] if item["code"] == sticker_random_country),
            None,
        )
        if not country or not country["presets"]:
            raise ValueError("所选销售国家暂无可用的贴纸文案")
        texts = [preset["text"] for preset in country["presets"]]
        assigned: list[str] = []
        generator = random.SystemRandom()
        while len(assigned) < len(selected_paths):
            batch = list(texts)
            generator.shuffle(batch)
            if assigned and len(batch) > 1 and assigned[-1] == batch[0]:
                batch.append(batch.pop(0))
            assigned.extend(batch)
        randomized_texts = dict(zip(selected_paths, assigned))
    for item in report.get("items", []):
        if item.get("script_dir") in selected_paths:
            item["sticker"] = copy.deepcopy(sticker_options)
            if item["script_dir"] in randomized_texts:
                item["sticker"]["text"] = randomized_texts[item["script_dir"]]
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


def sticker_library_for_selection(scan_id: str, script_dirs: list[str]) -> dict[str, Any]:
    report = read_report()
    if not scan_id or report.get("scan_id") != scan_id:
        raise ValueError("扫描结果已变化，请重新扫描后再选择文案")
    missing = {
        item["script_dir"]: item
        for item in report.get("items", [])
        if item.get("status") == "missing"
    }
    selected_paths = list(dict.fromkeys(script_dirs))
    unknown = [path for path in selected_paths if path not in missing]
    if not selected_paths or unknown:
        raise ValueError("请先选择本次扫描中的待拼接项目")
    products = sorted({str(missing[path].get("product") or "") for path in selected_paths})
    if len(products) != 1:
        return {
            "available": False,
            "product": "",
            "path": "",
            "countries": [],
            "reason": "已混选多个产品，请选择同一产品后调用文案库",
        }
    library = core.load_sticker_library(products[0])
    if not library["available"]:
        library["reason"] = "该产品暂无可用的文字贴纸库"
    return library


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


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoAssemblyOffline/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("请求内容过大")
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._file(STATIC_ROOT / "index.html")
            elif parsed.path.startswith("/static/"):
                relative = Path(unquote(parsed.path.removeprefix("/static/")))
                target = (STATIC_ROOT / relative).resolve()
                if STATIC_ROOT.resolve() not in target.parents:
                    raise ValueError("静态资源路径无效")
                self._file(target)
            elif parsed.path == "/api/state":
                report = read_report()
                checks = runtime_checks()
                self._json(
                    200,
                    {
                        "report": report,
                        "job": JOB.snapshot(),
                        "checks": checks,
                        "offline_ready": all(item["ok"] for item in checks),
                        "outputs": output_items(report),
                        "app_root": str(APP_ROOT),
                    },
                )
            elif parsed.path == "/api/job":
                self._json(200, {"job": JOB.snapshot()})
            elif parsed.path == "/api/outputs":
                self._json(200, {"outputs": output_items(), "root": str(core.OUTPUT_ROOT)})
            else:
                self.send_error(404)
        except (OSError, ValueError, RuntimeError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        parsed = urlparse(self.path)
        try:
            payload = self._body()
            if parsed.path == "/api/scan":
                if JOB.snapshot()["running"]:
                    raise RuntimeError("拼接运行中，暂不能重新扫描")
                report = scan_now()
                self._json(200, {"report": report, "outputs": output_items(report)})
            elif parsed.path == "/api/sticker-library":
                library = sticker_library_for_selection(
                    str(payload.get("scan_id") or ""),
                    [str(path) for path in payload.get("script_dirs", [])],
                )
                self._json(200, {"library": library})
            elif parsed.path == "/api/assemble":
                if payload.get("confirmed") is not True:
                    raise ValueError("需要明确确认后才能开始拼接")
                checks = runtime_checks()
                if not all(item["ok"] for item in checks):
                    raise RuntimeError("离线运行依赖不完整，请先检查左侧状态")
                report, selected = confirmed_report(
                    str(payload.get("scan_id") or ""),
                    [str(path) for path in payload.get("script_dirs", [])],
                    payload.get("sticker"),
                    str(payload.get("sticker_random_country") or ""),
                )
                self._json(202, {"job": JOB.start(report, selected)})
            elif parsed.path == "/api/cleanup":
                if JOB.snapshot()["running"]:
                    raise RuntimeError("拼接运行中，暂不能清理素材")
                if payload.get("confirmed") is not True or payload.get("verified") is not True:
                    raise ValueError("需要确认成品可用后才能清理素材")
                selected = confirmed_cleanup_items(
                    str(payload.get("scan_id") or ""),
                    [str(path) for path in payload.get("script_dirs", [])],
                )
                result = core.cleanup_items(selected)
                report = scan_now()
                self._json(200, {**result, "report": report, "outputs": output_items(report)})
            elif parsed.path == "/api/cancel":
                self._json(200, {"job": JOB.cancel()})
            elif parsed.path == "/api/open":
                path = allowed_local_path(str(payload.get("path") or ""))
                subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._json(200, {"opened": str(path)})
            else:
                self.send_error(404)
        except json.JSONDecodeError:
            self._json(400, {"error": "请求 JSON 无效"})
        except (OSError, ValueError, RuntimeError) as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="完全离线的片段合成智能体 Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9998)
    args = parser.parse_args()
    if not core.REPORT_PATH.exists():
        try:
            scan_now()
        except RuntimeError:
            pass
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"片段合成智能体：{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
