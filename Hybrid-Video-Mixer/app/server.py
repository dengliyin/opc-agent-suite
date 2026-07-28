from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from app.mixer import build_plan, list_outputs, mixer_paths, read_json, render_plan, scan_library
except ModuleNotFoundError:
    from mixer import build_plan, list_outputs, mixer_paths, read_json, render_plan, scan_library


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "static"
TASK_LOCK = threading.Lock()
TASK = {
    "status": "idle",
    "message": "空闲",
    "logs": [],
    "outputs": [],
    "error": "",
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


def render_worker(plan_path: str) -> None:
    try:
        task_update(status="running", message="开始渲染", logs=[], outputs=[], error="")
        path = Path(plan_path)
        plan = read_json(path, {})
        if not plan:
            raise ValueError("编排计划不存在或无法读取")
        outputs = render_plan(plan, log=task_log)
        task_update(status="completed", message=f"已完成 {len(outputs)} 条成片", outputs=outputs)
    except Exception as exc:
        task_log(f"失败：{exc}")
        task_update(status="failed", error=f"{exc}\n{traceback.format_exc()}")


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
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "agent": "AI＋实拍混剪智能体", "port": self.server.server_port})
            return
        if parsed.path == "/api/library":
            try:
                self.send_json({"ok": True, **scan_library()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
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
