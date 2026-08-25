from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from opc_shared.vault_snapshot import cached_or_empty, refresh_snapshot

try:
    from app.mixer import (
        VIDEO_EXTS,
        build_plan,
        delivery_sidecar_path,
        list_outputs,
        mixer_paths,
        read_json,
        render_plan,
        scan_library,
        update_delivery_marker,
    )
except ModuleNotFoundError:
    from mixer import (
        VIDEO_EXTS,
        build_plan,
        delivery_sidecar_path,
        list_outputs,
        mixer_paths,
        read_json,
        render_plan,
        scan_library,
        update_delivery_marker,
    )


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "static"
TASK_LOCK = threading.Lock()
TASK = {
    "status": "idle",
    "message": "空闲",
    "logs": [],
    "outputs": [],
    "error": "",
    "reserved_hook_paths": [],
}


def task_snapshot() -> dict:
    with TASK_LOCK:
        return json.loads(json.dumps(TASK, ensure_ascii=False))


def task_update(**values) -> None:
    with TASK_LOCK:
        TASK.update(values)


def task_log(message: str) -> None:
    with TASK_LOCK:
        TASK["logs"] = [*TASK.get("logs", []), message][-300:]
        TASK["message"] = message


def plan_hook_paths(plan: dict) -> list[str]:
    paths = {
        str(segment.get("path"))
        for variant in plan.get("variants") or []
        for segment in variant.get("segments") or []
        if segment.get("role") == "AI钩子" and segment.get("path")
    }
    return sorted(paths)


def render_worker(plan_path: str) -> None:
    try:
        task_update(
            status="running",
            message="开始渲染",
            logs=[],
            outputs=[],
            error="",
            reserved_hook_paths=[],
        )
        path = Path(plan_path)
        plan = read_json(path, {})
        if not plan:
            raise ValueError("编排计划不存在或无法读取")
        task_update(reserved_hook_paths=plan_hook_paths(plan))
        outputs = render_plan(plan, log=task_log)
        task_update(
            status="completed",
            message=f"已完成 {len(outputs)} 条成片",
            outputs=outputs,
            reserved_hook_paths=[],
        )
    except Exception as exc:
        task_log(f"失败：{exc}")
        task_update(
            status="failed",
            error=f"{exc}\n{traceback.format_exc()}",
            reserved_hook_paths=[],
        )


def safe_hook_video_path(value: str, paths=None) -> Path:
    paths = paths or mixer_paths()
    path = Path(value).expanduser().resolve()
    try:
        relative = path.relative_to((paths.work_root / "片段产出归档").resolve())
    except ValueError as exc:
        raise ValueError("钩子视频不在片段产出归档目录内") from exc
    if "混剪-钩子" not in relative.parts:
        raise ValueError("只允许访问混剪钩子目录中的视频")
    if path.suffix.lower() not in VIDEO_EXTS or not path.is_file():
        raise ValueError("钩子视频不存在或格式无效")
    return path


def delete_hook_videos(values, paths=None) -> dict:
    if not isinstance(values, list) or not values:
        raise ValueError("请至少选择一个钩子视频")
    paths = paths or mixer_paths()
    targets = []
    for value in values:
        target = safe_hook_video_path(str(value), paths)
        if target not in targets:
            targets.append(target)
    sidecars_deleted = 0
    delivery_markers_updated = 0
    for target in targets:
        target.unlink()
        if update_delivery_marker(target, cleaned=True):
            delivery_markers_updated += 1
        sidecar = target.with_suffix(target.suffix + ".product-lock.json")
        if sidecar.is_file():
            sidecar.unlink()
            sidecars_deleted += 1
        delivery_sidecar_path(target).unlink(missing_ok=True)
    return {
        "deleted_count": len(targets),
        "sidecars_deleted": sidecars_deleted,
        "delivery_markers_updated": delivery_markers_updated,
        "deleted": [str(path) for path in targets],
    }


def serve_video(handler: BaseHTTPRequestHandler, path: Path) -> None:
    file_size = path.stat().st_size
    start = 0
    end = file_size - 1
    status = 200
    range_header = handler.headers.get("Range", "")
    if range_header.startswith("bytes="):
        status = 206
        start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
        if start_text:
            start = int(start_text)
        if end_text:
            end = min(int(end_text), file_size - 1)
    length = max(0, end - start + 1)
    handler.send_response(status)
    handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(length))
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    handler.end_headers()
    try:
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        return


class Handler(BaseHTTPRequestHandler):
    server_version = "HybridVideoMixer/1.0"

    def log_message(self, _format: str, *_args) -> None:
        return

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def serve_static(self, relative: str) -> None:
        target = (STATIC_ROOT / relative).resolve()
        try:
            target.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.serve_static("index.html")
            return
        if parsed.path.startswith("/static/"):
            self.serve_static(parsed.path.removeprefix("/static/"))
            return
        if parsed.path in {"/health", "/api/health"}:
            self.send_json({"ok": True, "agent": "AI＋实拍混剪智能体", "port": self.server.server_port})
            return
        if parsed.path == "/api/library":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                refresh = query.get("refresh", [""])[0] == "1"
                payload = (
                    refresh_snapshot("hybrid-video-mixer", "library", scan_library)
                    if refresh
                    else cached_or_empty("hybrid-video-mixer", "library", lambda: {"products": [], "paths": {}})
                )
                self.send_json({"ok": True, **payload})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if parsed.path == "/api/hook-video":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                serve_video(self, safe_hook_video_path(query.get("path", [""])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
            return
        if parsed.path == "/api/task":
            self.send_json({"ok": True, "task": task_snapshot()})
            return
        if parsed.path == "/api/outputs":
            self.send_json({"ok": True, "outputs": list_outputs()})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_payload()
            if parsed.path == "/api/hook-video/delete":
                if task_snapshot()["status"] == "running":
                    self.send_json({"ok": False, "error": "渲染运行中，暂时不能删除钩子素材"}, 409)
                    return
                result = delete_hook_videos(payload.get("hook_paths"))
                self.send_json({"ok": True, **result})
                return
            if parsed.path == "/api/plan":
                plan = build_plan(payload)
                self.send_json({"ok": True, "plan": plan})
                return
            if parsed.path == "/api/render":
                current = task_snapshot()
                if current["status"] == "running":
                    self.send_json({"ok": False, "error": "当前已有渲染任务运行中"}, 409)
                    return
                plan_path = str(payload.get("plan_path") or "")
                paths = mixer_paths()
                resolved = Path(plan_path).expanduser().resolve()
                try:
                    resolved.relative_to(paths.work_root.resolve())
                except ValueError as exc:
                    raise ValueError("编排计划不在混剪工作区") from exc
                thread = threading.Thread(target=render_worker, args=(str(resolved),), daemon=True)
                thread.start()
                self.send_json({"ok": True, "message": "渲染任务已启动"})
                return
            self.send_error(404)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI＋实拍混剪智能体")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI＋实拍混剪智能体：http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
