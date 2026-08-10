from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL DEFAULT '{}',
                    log_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            rows = connection.execute(
                "SELECT id, stage, artifacts_json FROM pipeline_tasks WHERE status='running'"
            ).fetchall()
            for task_id, stage, artifacts_json in rows:
                artifacts = json.loads(artifacts_json or "{}")
                if stage == "publishing" and artifacts.get("active_publish_index") is not None:
                    status = "needs_review"
                    error = "服务在发布过程中重启，请先确认该视频是否已经发布，再决定是否继续。"
                else:
                    status = "queued"
                    error = "服务重启，已从最近完成的阶段恢复。"
                connection.execute(
                    "UPDATE pipeline_tasks SET status=?, error=?, updated_at=? WHERE id=?",
                    (status, error, time.time(), task_id),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, spec: dict[str, Any]) -> dict[str, Any]:
        task_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pipeline_tasks(id,status,stage,spec_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (task_id, "queued", "created", json.dumps(spec, ensure_ascii=False), now, now),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM pipeline_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError("流水线任务不存在")
        return self._decode(row)

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM pipeline_tasks ORDER BY created_at DESC").fetchall()
        return [self._decode(row) for row in rows]

    def update(self, task_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"status", "stage", "artifacts", "logs", "error"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"未知任务字段：{', '.join(sorted(unknown))}")
        columns: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            column = {"artifacts": "artifacts_json", "logs": "log_json"}.get(key, key)
            columns.append(f"{column}=?")
            values.append(json.dumps(value, ensure_ascii=False) if key in {"artifacts", "logs"} else value)
        columns.append("updated_at=?")
        values.extend([time.time(), task_id])
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE pipeline_tasks SET {', '.join(columns)} WHERE id=?", values)
        return self.get(task_id)

    def append_log(self, task_id: str, message: str) -> None:
        task = self.get(task_id)
        logs = task["logs"][-199:]
        logs.append({"at": time.time(), "message": message[:2000]})
        self.update(task_id, logs=logs)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["spec"] = json.loads(item.pop("spec_json") or "{}")
        item["artifacts"] = json.loads(item.pop("artifacts_json") or "{}")
        item["logs"] = json.loads(item.pop("log_json") or "[]")
        return item
