from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ACTIVE_STATUSES = ("pending", "running")
RETRYABLE_STATUSES = ("failed", "needs_review")


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


class PublishQueue:
    def __init__(
        self,
        db_path: Path,
        executor: Callable[[dict[str, Any]], dict[str, Any]],
        interval_seconds: int = 10,
        profile_closer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        video_path_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.db_path = db_path
        self.executor = executor
        self.interval_seconds = interval_seconds
        self.profile_closer = profile_closer
        self.video_path_resolver = video_path_resolver
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    video_name TEXT NOT NULL,
                    product_code TEXT NOT NULL,
                    country TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    product_short_name TEXT NOT NULL,
                    attach_product INTEGER NOT NULL DEFAULT 1,
                    ai_generated INTEGER NOT NULL DEFAULT 1,
                    visibility TEXT NOT NULL DEFAULT 'public',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    result_url TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(queue_tasks)")}
            if "execution_mode_override" not in columns:
                connection.execute(
                    "ALTER TABLE queue_tasks ADD COLUMN execution_mode_override TEXT NOT NULL DEFAULT ''"
                )
            if "attach_product" not in columns:
                connection.execute(
                    "ALTER TABLE queue_tasks ADD COLUMN attach_product INTEGER NOT NULL DEFAULT 1"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute("INSERT OR IGNORE INTO queue_meta(key, value) VALUES('paused', '1')")
            connection.execute("INSERT OR IGNORE INTO queue_meta(key, value) VALUES('next_run_at', '0')")
            connection.execute("INSERT OR IGNORE INTO queue_meta(key, value) VALUES('execution_mode', 'visible')")
            connection.execute("INSERT OR IGNORE INTO queue_meta(key, value) VALUES('scheduled_at', '0')")
            interrupted = connection.execute(
                "UPDATE queue_tasks SET status='needs_review', completed_at=?, error=? WHERE status='running'",
                (now_text(), "服务在发布过程中重启，请先确认 TikTok 是否已经发布，再决定是否重试。"),
            ).rowcount
            if interrupted:
                self._set_meta(connection, "paused", "1")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="tiktok-publish-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _get_meta(self, connection: sqlite3.Connection, key: str, default: str = "") -> str:
        row = connection.execute("SELECT value FROM queue_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def _set_meta(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO queue_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _resolve_video_path(self, value: str) -> str:
        if not self.video_path_resolver:
            return value
        try:
            return str(self.video_path_resolver(value))
        except Exception:
            return value

    def enqueue(self, tasks: list[dict[str, Any]]) -> list[int]:
        if not tasks:
            raise ValueError("请至少选择一个视频")
        batch_id = uuid.uuid4().hex
        created_at = now_text()
        inserted: list[int] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            next_position = int(connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM queue_tasks").fetchone()[0])
            active_paths = {
                self._resolve_video_path(str(row[0]))
                for row in connection.execute(
                    "SELECT video_path FROM queue_tasks WHERE status IN ('pending', 'running')"
                ).fetchall()
            }
            for task in tasks:
                video_path = self._resolve_video_path(str(task.get("video_path", "")).strip())
                if video_path in active_paths:
                    raise ValueError(f"视频已在队列中：{Path(video_path).name}")
                cursor = connection.execute(
                    """
                    INSERT INTO queue_tasks (
                        batch_id, position, status, video_path, video_name, product_code, country,
                        profile_id, profile_name, caption, product_id, product_short_name,
                        attach_product, ai_generated, visibility, created_at
                    ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        next_position,
                        video_path,
                        str(task.get("video_name", "")).strip() or Path(video_path).name,
                        str(task.get("product_code", "")).strip(),
                        str(task.get("country", "")).strip(),
                        str(task.get("profile_id", "")).strip(),
                        str(task.get("profile_name", "")).strip(),
                        str(task.get("caption", "")).strip(),
                        str(task.get("product_id", "")).strip(),
                        str(task.get("product_short_name", "")).strip(),
                        1 if task.get("attach_product", True) else 0,
                        1 if task.get("ai_generated", True) else 0,
                        str(task.get("visibility", "public")).strip() or "public",
                        created_at,
                    ),
                )
                inserted.append(int(cursor.lastrowid))
                active_paths.add(video_path)
                next_position += 1
            self._set_meta(connection, "paused", "1")
        self._wake_event.set()
        return inserted

    def payload(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM queue_tasks ORDER BY position, id")]
            paused = self._get_meta(connection, "paused", "0") == "1"
            next_run_at = float(self._get_meta(connection, "next_run_at", "0") or 0)
            execution_mode = self._get_meta(connection, "execution_mode", "visible")
            scheduled_at = float(self._get_meta(connection, "scheduled_at", "0") or 0)
        counts: dict[str, int] = {}
        for row in rows:
            if row.get("status") in (*ACTIVE_STATUSES, *RETRYABLE_STATUSES):
                row["video_path"] = self._resolve_video_path(str(row.get("video_path", "")))
            row["ai_generated"] = bool(row.get("ai_generated"))
            row["attach_product"] = bool(row.get("attach_product"))
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "tasks": rows,
            "counts": counts,
            "paused": paused,
            "execution_mode": execution_mode,
            "interval_seconds": self.interval_seconds,
            "next_run_at": next_run_at,
            "scheduled_at": scheduled_at,
            "server_time": time.time(),
        }

    def control(self, action: str, execution_mode: str = "", scheduled_at: float = 0) -> dict[str, Any]:
        with self._connect() as connection:
            if action == "pause":
                self._set_meta(connection, "paused", "1")
                self._set_meta(connection, "scheduled_at", "0")
            elif action == "resume":
                execution_mode = execution_mode.strip() or "visible"
                if execution_mode not in ("visible", "headless"):
                    raise ValueError("不支持的执行方式")
                self._set_meta(connection, "execution_mode", execution_mode)
                self._set_meta(connection, "paused", "0")
                self._set_meta(connection, "scheduled_at", "0")
            elif action == "schedule":
                execution_mode = execution_mode.strip() or "visible"
                if execution_mode not in ("visible", "headless"):
                    raise ValueError("不支持的执行方式")
                if scheduled_at <= time.time():
                    raise ValueError("预约时间必须晚于当前时间")
                pending = int(
                    connection.execute("SELECT COUNT(*) FROM queue_tasks WHERE status='pending'").fetchone()[0]
                )
                running = int(
                    connection.execute("SELECT COUNT(*) FROM queue_tasks WHERE status='running'").fetchone()[0]
                )
                if not pending:
                    raise ValueError("当前没有等待执行的任务")
                if running:
                    raise ValueError("已有任务正在执行，不能设置预约")
                self._set_meta(connection, "execution_mode", execution_mode)
                self._set_meta(connection, "paused", "1")
                self._set_meta(connection, "scheduled_at", str(scheduled_at))
            elif action == "cancel_schedule":
                self._set_meta(connection, "scheduled_at", "0")
                self._set_meta(connection, "paused", "1")
            elif action == "clear_pending":
                connection.execute(
                    "UPDATE queue_tasks SET status='canceled', completed_at=?, error='' WHERE status='pending'",
                    (now_text(),),
                )
                self._set_meta(connection, "scheduled_at", "0")
            else:
                raise ValueError("不支持的队列操作")
        self._wake_event.set()
        return self.payload()

    def task_action(self, task_id: int, action: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM queue_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("队列任务不存在")
            status = str(row["status"])
            if action == "cancel" and status in ("pending", "failed", "needs_review"):
                connection.execute(
                    "UPDATE queue_tasks SET status='canceled', completed_at=?, error='' WHERE id=?",
                    (now_text(), task_id),
                )
            elif action == "retry" and status in RETRYABLE_STATUSES:
                next_position = int(connection.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM queue_tasks").fetchone()[0])
                connection.execute(
                    """
                    UPDATE queue_tasks
                    SET status='pending', position=?, started_at='', completed_at='', error='', result_url='',
                        execution_mode_override='visible'
                    WHERE id=?
                    """,
                    (next_position, task_id),
                )
            elif action in ("move_up", "move_down") and status == "pending":
                operator = "<" if action == "move_up" else ">"
                order = "DESC" if action == "move_up" else "ASC"
                neighbor = connection.execute(
                    f"SELECT id, position FROM queue_tasks WHERE status='pending' AND position {operator} ? ORDER BY position {order} LIMIT 1",
                    (row["position"],),
                ).fetchone()
                if neighbor:
                    connection.execute("UPDATE queue_tasks SET position=? WHERE id=?", (neighbor["position"], task_id))
                    connection.execute("UPDATE queue_tasks SET position=? WHERE id=?", (row["position"], neighbor["id"]))
            else:
                raise ValueError("当前状态不允许这个操作")
        self._wake_event.set()
        return self.payload()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._execute_next()
            except Exception:
                pass
            self._wake_event.wait(timeout=1)
            self._wake_event.clear()

    def _execute_next(self) -> None:
        with self._connect() as connection:
            transaction_started = False
            if self._get_meta(connection, "paused", "0") == "1":
                scheduled_at = float(self._get_meta(connection, "scheduled_at", "0") or 0)
                if not scheduled_at or scheduled_at > time.time():
                    return
                connection.execute("BEGIN IMMEDIATE")
                transaction_started = True
                self._set_meta(connection, "paused", "0")
                self._set_meta(connection, "scheduled_at", "0")
            next_run_at = float(self._get_meta(connection, "next_run_at", "0") or 0)
            if next_run_at > time.time():
                return
            execution_mode = self._get_meta(connection, "execution_mode", "visible")
            if not transaction_started:
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM queue_tasks WHERE status='pending' ORDER BY position, id LIMIT 1"
            ).fetchone()
            if not row:
                return
            started_at = now_text()
            connection.execute(
                "UPDATE queue_tasks SET status='running', started_at=?, attempts=attempts+1, error='' WHERE id=?",
                (started_at, row["id"]),
            )
            task = dict(row)
            task["video_path"] = self._resolve_video_path(str(task.get("video_path", "")))
            task["ai_generated"] = bool(task.get("ai_generated"))
            task["attach_product"] = bool(task.get("attach_product"))
            retry_visible = str(task.get("execution_mode_override", "")) == "visible"
            task["execution_mode"] = "visible" if retry_visible else execution_mode

        status = "published"
        error = ""
        result_url = ""
        close_failed = False
        try:
            if retry_visible and self.profile_closer:
                try:
                    self.profile_closer(task)
                except Exception:
                    pass
            result = self.executor(task)
            result_url = str(result.get("url") or result.get("tiktok_upload_url") or "")
        except Exception as exc:
            error = str(exc)
            status = "needs_review" if "发布后没有返回成功状态" in error else "failed"

        if status == "published" and self.profile_closer and self._profile_block_complete(task):
            try:
                self.profile_closer(task)
            except Exception as exc:
                close_failed = True
                error = f"视频已发布，但关闭比特浏览器失败：{exc}"

        with self._connect() as connection:
            connection.execute(
                "UPDATE queue_tasks SET status=?, completed_at=?, error=?, result_url=? WHERE id=?",
                (status, now_text(), error, result_url, task["id"]),
            )
            self._set_meta(connection, "next_run_at", str(time.time() + self.interval_seconds))
            if status == "needs_review" or close_failed:
                self._set_meta(connection, "paused", "1")

    def _profile_block_complete(self, task: dict[str, Any]) -> bool:
        with self._connect() as connection:
            if self._get_meta(connection, "paused", "0") == "1":
                return True
            next_task = connection.execute(
                "SELECT profile_id FROM queue_tasks WHERE status='pending' ORDER BY position, id LIMIT 1"
            ).fetchone()
        return not next_task or str(next_task["profile_id"]) != str(task.get("profile_id", ""))
