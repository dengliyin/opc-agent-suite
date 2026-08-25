from __future__ import annotations

import json

from opc_shared import vault_snapshot


def test_missing_snapshot_returns_empty_without_calling_builder(monkeypatch, tmp_path):
    monkeypatch.setenv("OPC_SCAN_INDEX_ROOT", str(tmp_path))
    calls = []

    payload = vault_snapshot.cached_or_empty("agent", "catalog", lambda: calls.append("empty") or {"items": []})

    assert calls == ["empty"]
    assert payload == {"items": [], "scan_index": {"ready": False, "updated_at": ""}}
    assert list(tmp_path.rglob("*.json")) == []


def test_refresh_is_atomic_and_reused(monkeypatch, tmp_path):
    monkeypatch.setenv("OPC_SCAN_INDEX_ROOT", str(tmp_path))

    refreshed = vault_snapshot.refresh_snapshot("agent", "catalog", lambda: {"items": ["a"]})
    cached = vault_snapshot.cached_or_empty("agent", "catalog", lambda: {"items": []})

    assert refreshed["items"] == ["a"]
    assert refreshed["scan_index"]["ready"] is True
    assert cached["items"] == ["a"]
    assert cached["scan_index"]["ready"] is True
    path = vault_snapshot.snapshot_path("agent", "catalog")
    assert json.loads(path.read_text(encoding="utf-8"))["payload"] == {"items": ["a"]}
    assert list(path.parent.glob("*.tmp")) == []


def test_incremental_records_reuses_unchanged_cold_items_and_rebuilds_hot_items():
    previous = [
        {"scan_key": "cold", "scan_signature": "1", "temperature": "cold", "done": True},
        {"scan_key": "hot", "scan_signature": "1", "temperature": "hot", "done": False},
    ]
    built = []

    records, stats = vault_snapshot.incremental_records(
        previous,
        [("cold", "1", True), ("hot", "1", True), ("new", "2", False)],
        source_key=lambda source: source[0],
        source_signature=lambda source: source[1],
        build_record=lambda source: built.append(source[0]) or {"done": source[2]},
        is_cold=lambda record: bool(record["done"]),
    )

    assert built == ["hot", "new"]
    assert [record["temperature"] for record in records] == ["cold", "cold", "hot"]
    assert stats == {"scanned": 2, "cold_reused": 1, "total": 3}
