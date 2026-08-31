from __future__ import annotations

import argparse
import json
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opc_shared.ui_theme import send_theme_css

from opc_engine.features.unified_script_agent import core


HOST = "127.0.0.1"
DEFAULT_PORT = 10006
STATIC_ROOT = Path(__file__).resolve().parent / "static"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class JobQueue:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.jobs: dict[int, dict[str, Any]] = {}
        self.queue: list[int] = []
        self.next_id = 1
        self.path = core.storage_paths().data_root / "jobs.json"
        self._load()
        threading.Thread(target=self._worker, daemon=True).start()

    def _load(self) -> None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        items = document.get("jobs") if isinstance(document, dict) else None
        if not isinstance(items, list):
            return
        for raw in items:
            if not isinstance(raw, dict):
                continue
            job = dict(raw)
            job_id = int(job.get("id") or 0)
            if not job_id:
                continue
            if job.get("status") == "running":
                job["status"] = "interrupted"
                job["error"] = "容器在任务执行期间重启；为避免重复生成，本任务未自动重跑"
                job["finished_at"] = time.time()
            elif job.get("status") == "queued":
                self.queue.append(job_id)
            self.jobs[job_id] = job
            self.next_id = max(self.next_id, job_id + 1)

    def _persist(self) -> None:
        items = sorted(self.jobs.values(), key=lambda item: int(item["id"]), reverse=True)[:50]
        _atomic_json(self.path, {"version": 1, "jobs": items})

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        validated = core.validate_task_payload(payload)
        with self.changed:
            job_id = self.next_id
            self.next_id += 1
            job = {
                "id": job_id,
                "status": "queued",
                "title": self._title(validated),
                "payload": validated,
                "logs": ["任务已加入队列"],
                "error": "",
                "result": None,
                "created_at": time.time(),
                "started_at": 0.0,
                "finished_at": 0.0,
            }
            self.jobs[job_id] = job
            self.queue.append(job_id)
            self._persist()
            self.changed.notify()
            return self._public(job)

    def _title(self, payload: dict[str, Any]) -> str:
        count = f" × {payload['variant_count']}" if payload["mode"] == "mutation" else ""
        return (
            f"{core.ROUTE_LABELS[payload['route']]} · {core.MODE_LABELS[payload['mode']]}{count} · "
            f"{payload['target_product']} · {payload['target_market']}"
        )

    def append(self, job_id: int, message: str) -> None:
        clean = str(message or "").strip()
        if not clean:
            return
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.setdefault("logs", []).append(clean)
            job["logs"] = job["logs"][-200:]
            self._persist()

    def _worker(self) -> None:
        while True:
            with self.changed:
                while not self.queue:
                    self.changed.wait()
                job_id = self.queue.pop(0)
                job = self.jobs.get(job_id)
                if not job:
                    continue
                job["status"] = "running"
                job["started_at"] = time.time()
                self._persist()
            try:
                result = core.run_task(job["payload"], lambda message: self.append(job_id, message))
                with self.lock:
                    job["result"] = result
                    job["status"] = "partial" if result.get("partial_success") else "completed"
            except Exception as exc:  # noqa: BLE001 - expose exact local job failure in the UI.
                self.append(job_id, traceback.format_exc())
                with self.lock:
                    job["status"] = "failed"
                    job["error"] = str(exc)
            finally:
                with self.lock:
                    job["finished_at"] = time.time()
                    self._persist()

    def _public(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"],
            "status": job["status"],
            "title": job["title"],
            "logs": list(job.get("logs") or []),
            "error": job.get("error") or "",
            "result": job.get("result"),
            "created_at": job.get("created_at") or 0,
            "started_at": job.get("started_at") or 0,
            "finished_at": job.get("finished_at") or 0,
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            items = [self._public(job) for job in sorted(self.jobs.values(), key=lambda item: int(item["id"]), reverse=True)[:30]]
            return {
                "running": any(job["status"] == "running" for job in self.jobs.values()),
                "queued": len(self.queue),
                "jobs": items,
            }


JOBS: JobQueue | None = None


def jobs() -> JobQueue:
    global JOBS
    if JOBS is None:
        JOBS = JobQueue()
    return JOBS


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if not length:
        return {}
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON object")
    return payload


def static_response(handler: BaseHTTPRequestHandler, filename: str, content_type: str) -> None:
    path = STATIC_ROOT / filename
    if not path.is_file():
        json_response(handler, 404, {"error": "Not found"})
        return
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            static_response(self, "index.html", "text/html; charset=utf-8")
        elif parsed.path == "/app.css":
            static_response(self, "app.css", "text/css; charset=utf-8")
        elif parsed.path == "/app.js":
            static_response(self, "app.js", "application/javascript; charset=utf-8")
        elif parsed.path == "/opc-theme.css":
            send_theme_css(self)
        elif parsed.path == "/api/state":
            query = urllib.parse.parse_qs(parsed.query)
            refresh = str((query.get("refresh") or [""])[0]).lower() in {"1", "true", "yes"}
            json_response(self, 200, core.state_payload(refresh=refresh))
        elif parsed.path == "/api/jobs":
            json_response(self, 200, jobs().snapshot())
        elif parsed.path == "/api/source-preview":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                json_response(
                    self,
                    200,
                    core.source_preview_payload(
                        str((query.get("route") or [""])[0]),
                        str((query.get("path") or [""])[0]),
                    ),
                )
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
        elif parsed.path == "/health":
            json_response(self, 200, {"ok": True, "service": "Unified-Script-Agent", "port": DEFAULT_PORT})
        else:
            json_response(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/jobs":
                json_response(self, 202, {"job": jobs().create(read_json(self))})
            else:
                json_response(self, 404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surface local configuration errors to the page.
            json_response(self, 500, {"error": str(exc)})

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified script creation and Omni adaptation agent")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    jobs()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"脚本创作与适配智能体已启动: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
