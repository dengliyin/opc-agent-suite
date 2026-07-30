from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from audio_agent.core import find_document, generate_entries, runtime_paths, scan_library


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


def generate_worker(payload: dict) -> None:
    try:
        task_update(status="running", message="开始配音", logs=[], outputs=[], error="")
        outputs = generate_entries(
            str(payload.get("document", "")),
            [str(value) for value in payload.get("entries", [])],
            str(payload.get("voice", "")),
            overwrite=bool(payload.get("overwrite", False)),
            log=task_log,
        )
        generated = sum(item["status"] == "generated" for item in outputs)
        task_update(
            status="completed",
            message=f"完成：新生成 {generated} 条，共处理 {len(outputs)} 条",
            outputs=outputs,
        )
    except Exception as exc:
        task_log(f"失败：{exc}")
        task_update(status="failed", error=f"{exc}\n{traceback.format_exc()}")


class Handler(BaseHTTPRequestHandler):
    server_version = "HybridAudioGeneration/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            try:
                runtime_paths()
                self.send_json({"ok": True, "status": task_snapshot()["status"]})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 503)
            return
        if parsed.path == "/api/library":
            self.send_json(scan_library())
            return
        if parsed.path == "/api/status":
            self.send_json(task_snapshot())
            return
        if parsed.path == "/api/audio":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                document = find_document(query.get("document", [""])[0])
                entry_id = query.get("entry", [""])[0]
                entry = next((item for item in document["entries"] if item["id"] == entry_id), None)
                if not entry:
                    raise ValueError("音频条目不存在")
                self.send_file(Path(entry["output_path"]))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 404)
            return
        target = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
        path = (STATIC_ROOT / target).resolve()
        try:
            path.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.send_error(404)
            return
        self.send_file(path)

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/api/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if task_snapshot()["status"] == "running":
                raise ValueError("已有配音任务正在运行")
            document = str(payload.get("document", "")).strip()
            entries = payload.get("entries")
            voice = str(payload.get("voice", "")).strip()
            if not document or not isinstance(entries, list) or not entries or not voice:
                raise ValueError("请选择文案、音频条目和声音")
            worker = threading.Thread(target=generate_worker, args=(payload,), daemon=True)
            worker.start()
            self.send_json({"ok": True, "message": "配音任务已创建"}, 202)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)


def main() -> None:
    parser = argparse.ArgumentParser(description="配音智能体")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10004)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"配音智能体已启动：http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
