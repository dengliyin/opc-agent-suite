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
