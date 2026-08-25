from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_Source = TypeVar("_Source")


def snapshot_root() -> Path:
    configured = str(os.environ.get("OPC_SCAN_INDEX_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    env_file = Path(os.environ.get("OPC_ENV_FILE", "")).expanduser()
    if env_file.is_absolute() and env_file.parent.name:
        return env_file.parent / "scan-index"
    return Path.home() / ".opc-agent-suite" / "scan-index"


def snapshot_path(namespace: str, key: str = "default") -> Path:
    safe_namespace = _safe_name(namespace)
    safe_key = _safe_name(key)
    return snapshot_root() / safe_namespace / f"{safe_key}.json"


def load_snapshot(namespace: str, key: str = "default") -> dict[str, Any] | None:
    path = snapshot_path(namespace, key)
    lock = _path_lock(path)
    with lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
    if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
        return None
    return data


def save_snapshot(namespace: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = snapshot_path(namespace, key)
    document = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "payload": payload,
    }
    lock = _path_lock(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    return document


def cached_or_empty(
    namespace: str,
    key: str,
    empty_payload: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    snapshot = load_snapshot(namespace, key)
    if snapshot is None:
        payload = empty_payload()
        payload["scan_index"] = {"ready": False, "updated_at": ""}
        return payload
    payload = dict(snapshot["payload"])
    payload["scan_index"] = {
        "ready": True,
        "updated_at": str(snapshot.get("updated_at") or ""),
    }
    return payload


def refresh_snapshot(namespace: str, key: str, builder: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    payload = builder()
    snapshot = save_snapshot(namespace, key, payload)
    result = dict(payload)
    result["scan_index"] = {
        "ready": True,
        "updated_at": str(snapshot.get("updated_at") or ""),
    }
    return result


def incremental_records(
    previous_items: Iterable[dict[str, Any]],
    sources: Iterable[_Source],
    *,
    source_key: Callable[[_Source], str],
    source_signature: Callable[[_Source], str],
    build_record: Callable[[_Source], dict[str, Any] | None],
    is_cold: Callable[[dict[str, Any]], bool],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    previous = {
        str(item.get("scan_key") or ""): item
        for item in previous_items
        if isinstance(item, dict) and str(item.get("scan_key") or "")
    }
    records: list[dict[str, Any]] = []
    reused = 0
    scanned = 0
    for source in sources:
        key = source_key(source)
        signature = source_signature(source)
        cached = previous.get(key)
        if cached and cached.get("scan_signature") == signature and cached.get("temperature") == "cold":
            records.append(dict(cached))
            reused += 1
            continue
        record = build_record(source)
        if record is None:
            continue
        record = dict(record)
        record["scan_key"] = key
        record["scan_signature"] = signature
        record["temperature"] = "cold" if is_cold(record) else "hot"
        records.append(record)
        scanned += 1
    return records, {"scanned": scanned, "cold_reused": reused, "total": len(records)}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-.")
    return cleaned or "default"


def _path_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())
