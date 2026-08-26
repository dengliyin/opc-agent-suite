import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import app as app_module


STATIC_APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


class FakeManager:
    def __init__(self, *, block_start=False):
        self.block_start = block_start
        self.started = []

    def start(self, stage="all", overwrite=None, script_paths=None, script_concurrency=None, reference_images=None):
        if self.block_start:
            raise ValueError("当前 Agent 已有任务正在运行，请先停止或等待完成后再启动新任务")
        self.started.append((stage, overwrite, script_paths, script_concurrency, reference_images))
        return {
            "id": "fake_job",
            "stage": stage,
            "status": "queued",
            "overwrite": overwrite,
            "script_paths": script_paths,
            "script_concurrency": script_concurrency,
            "total": 0,
            "done": 0,
            "logs": [],
            "errors": [],
        }

    def list_jobs(self):
        return []

    def get(self, job_id):
        return {"id": job_id}

    def cancel(self, job_id=None):
        return []

    def update_concurrency(self, script_concurrency, job_id=None):
        return {
            "id": job_id or "fake_job",
            "stage": "repair",
            "status": "running",
            "script_concurrency": script_concurrency,
            "total": 0,
            "done": 0,
            "logs": [],
            "errors": [],
        }


def test_run_lock_is_per_agent(monkeypatch):
    omni = FakeManager(block_start=True)
    grok = FakeManager()
    monkeypatch.setattr(app_module, "job_managers", {"omni": omni, "grok": grok})
    client = TestClient(app_module.app)

    response = client.post(
        "/grok/api/run",
        json={"stage": "characters", "overwrite": False, "script_paths": ["/tmp/a.md"], "script_concurrency": 8},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "fake_job"
    assert grok.started == [("characters", False, ["/tmp/a.md"], 8, None)]


def test_same_agent_run_is_accepted_for_manager_queue(monkeypatch):
    omni = FakeManager()
    monkeypatch.setattr(
        app_module,
        "job_managers",
        {"omni": omni, "grok": FakeManager()},
    )
    client = TestClient(app_module.app)

    response = client.post("/omni/api/run", json={"stage": "characters", "overwrite": False, "script_paths": ["/tmp/a.md"]})

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert omni.started == [("characters", False, ["/tmp/a.md"], None, None)]


def test_product_video_stage_is_accepted(monkeypatch):
    omni = FakeManager()
    monkeypatch.setattr(app_module, "job_managers", {"omni": omni, "grok": FakeManager()})
    client = TestClient(app_module.app)

    response = client.post(
        "/omni/api/run",
        json={"stage": "product_videos", "overwrite": False, "script_paths": ["/tmp/a.md"]},
    )

    assert response.status_code == 200
    assert omni.started == [("product_videos", False, ["/tmp/a.md"], None, None)]


def test_omni_page_has_product_reference_fastest_mode():
    response = TestClient(app_module.app).get("/omni")

    assert response.status_code == 200
    assert 'data-stage="product_videos"' in response.text
    assert "功能3 故事版图 → 视频" in response.text
    assert "功能4 人物图+产品图 → 视频" in response.text
    assert "功能5 产品图+镜头脚本 → 视频" in response.text
    assert "功能6 一键完整流程（1→2→3）" in response.text


def test_update_concurrency_is_per_agent(monkeypatch):
    omni = FakeManager()
    grok = FakeManager()
    monkeypatch.setattr(app_module, "job_managers", {"omni": omni, "grok": grok})
    client = TestClient(app_module.app)

    response = client.post("/grok/api/jobs/concurrency", json={"job_id": "job_1", "script_concurrency": 12})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "job_1"
    assert body["script_concurrency"] == 12


def test_hybrid_omni_run_uses_independent_manager(monkeypatch):
    hybrid = FakeManager()
    monkeypatch.setattr(
        app_module,
        "job_managers",
        {"omni": FakeManager(), "grok": FakeManager(), "hybrid_omni": hybrid},
    )
    client = TestClient(app_module.app)

    response = client.post(
        "/hybrid-omni/api/run",
        json={"stage": "videos", "overwrite": False, "script_paths": ["/tmp/hook.md"]},
    )

    assert response.status_code == 200
    assert hybrid.started == [("videos", False, ["/tmp/hook.md"], None, None)]


def test_hybrid_omni_routes_and_page_exist():
    paths = {route.path for route in app_module.app.routes}
    client = TestClient(app_module.app)

    assert "/hybrid-omni/api/catalog" in paths
    assert "/hybrid-omni/api/jobs" in paths
    assert "/hybrid-omni/api/artifact" in paths
    assert "/hybrid-omni/api/export-completed" in paths
    assert "/hybrid-omni/api/restore-exported" in paths
    assert "/hybrid-omni/api/scripts" in paths
    assert "/hybrid-omni/api/archived-scripts" in paths
    response = client.get("/hybrid-omni")
    assert response.status_code == 200
    assert "混剪钩子与 CTA Omni 片段产出" in response.text
    assert 'id="exportSelectedButton"' in response.text
    assert "导出已选" in response.text
    assert 'id="deleteSelectedScriptsButton"' in response.text
    assert "删除所选" in response.text


def test_health_is_lightweight(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "scan_scripts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("health must not scan files")),
    )
    client = TestClient(app_module.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_catalog_does_not_scan_until_explicit_refresh(monkeypatch, tmp_path):
    calls = []
    app_module._clear_catalog_cache()
    monkeypatch.setenv("OPC_SCAN_INDEX_ROOT", str(tmp_path))
    monkeypatch.setattr(app_module, "CATALOG_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(
        app_module,
        "scan_scripts",
        lambda *_args, **_kwargs: calls.append("scan") or [],
    )
    client = TestClient(app_module.app)

    first = client.get("/api/catalog")
    refreshed = client.get("/api/catalog?refresh=true")
    second = client.get("/api/catalog")

    assert first.status_code == 200
    assert first.json()["scan_index"]["ready"] is False
    assert refreshed.status_code == 200
    assert second.status_code == 200
    assert calls == ["scan"]
    app_module._clear_catalog_cache()


def test_incremental_catalog_reuses_completed_cold_script(monkeypatch, tmp_path):
    from agent.files import ScriptCandidate

    cold_path = tmp_path / "P1" / "cold.md"
    hot_path = tmp_path / "P1" / "hot.md"
    cold_path.parent.mkdir(parents=True)
    cold_path.write_text("cold", encoding="utf-8")
    hot_path.write_text("hot", encoding="utf-8")
    candidates = [
        ScriptCandidate("P1", cold_path.parent, cold_path, None),
        ScriptCandidate("P1", hot_path.parent, hot_path, None),
    ]
    previous = [
        {
            "product_name": "P1",
            "md_path": str(cold_path),
            "segments": [],
            "complete": True,
            "full_mode_complete": True,
            "exported": False,
            "scan_key": str(cold_path.resolve()),
            "scan_signature": "cold.md:signature",
            "temperature": "cold",
        },
        {
            "product_name": "P1",
            "md_path": str(hot_path),
            "segments": [],
            "complete": False,
            "full_mode_complete": False,
            "exported": False,
            "scan_key": str(hot_path.resolve()),
            "scan_signature": "hot.md:signature",
            "temperature": "hot",
        },
    ]
    built = []
    monkeypatch.setattr(
        app_module,
        "load_snapshot",
        lambda *_args: {"payload": {"scripts": previous, "scan_state": {"schema_version": 2, "archive_active_paths": []}}},
    )
    monkeypatch.setattr(app_module, "discover_active_script_candidates", lambda *_args: candidates)
    monkeypatch.setattr(app_module, "_candidate_signature", lambda _settings, candidate: f"{candidate.md_path.name}:signature")
    monkeypatch.setattr(app_module, "load_script_candidate", lambda candidate: built.append(candidate.md_path.name) or candidate)
    monkeypatch.setattr(
        app_module,
        "script_to_dict",
        lambda _settings, candidate: {
            "product_name": candidate.product_name,
            "md_path": str(candidate.md_path),
            "segments": [],
            "complete": candidate.md_path.name == "hot.md",
            "full_mode_complete": candidate.md_path.name == "hot.md",
            "exported": False,
        },
    )

    payload = app_module._incremental_catalog_payload(SimpleNamespace(workflow="standard"), "test")

    assert built == ["hot.md"]
    assert payload["scan_state"]["cold_reused"] == 1
    assert payload["scan_state"]["scanned"] == 1
    assert payload["scan_state"]["cold"] == 2


def test_incremental_catalog_rebases_archived_paths_to_current_vault(monkeypatch, tmp_path):
    active_root = tmp_path / "current-vault" / "04适配脚本" / "omni"
    archived_path = tmp_path / "current-vault" / "06合成工作区" / "2026-08-26" / "P1" / "script" / "script.md"
    previous = [
        {
            "product_name": "P1",
            "md_path": str(archived_path),
            "segments": [],
            "complete": True,
            "exported": True,
            "scan_key": str(archived_path),
            "scan_signature": "archived",
            "temperature": "cold",
        }
    ]
    captured = []
    monkeypatch.setattr(
        app_module,
        "load_snapshot",
        lambda *_args: {
            "payload": {
                "scripts": previous,
                "scan_state": {
                    "schema_version": 2,
                    "archive_active_paths": ["D:/old-vault/04适配脚本/omni/P1/script.md"],
                },
            }
        },
    )
    monkeypatch.setattr(
        app_module,
        "discover_active_script_candidates",
        lambda _settings, archive_paths: captured.extend(archive_paths) or [],
    )
    settings = SimpleNamespace(workflow="standard", script_root=active_root)

    payload = app_module._incremental_catalog_payload(settings, "test")

    expected = str((active_root / "P1" / "script.md").resolve())
    assert captured == [expected]
    assert payload["scan_state"]["archive_active_paths"] == [expected]
    assert payload["scripts"] == previous


def test_media_cleanup_route_is_owned_by_assembly_agent():
    paths = {route.path for route in app_module.app.routes}

    assert "/api/clear-archived-media" not in paths
    assert "/omni/api/clear-archived-media" not in paths
    assert "/grok/api/clear-archived-media" not in paths


def test_script_delete_routes_exist_for_both_agents():
    paths = {route.path for route in app_module.app.routes}

    assert "/omni/api/scripts" in paths
    assert "/grok/api/scripts" in paths


def test_catalog_polling_is_deduplicated_after_terminal_job():
    source = STATIC_APP_JS.read_text(encoding="utf-8")

    assert "if (state.pollingJobs) return;" in source
    assert "terminalKey !== state.lastTerminalCatalogJobKey" in source
    assert "refreshAll().catch" in source
    assert "}).finally(() => {\n  setInterval(pollJobs, 4000);\n});" in source
    assert 'full ? "&full=true" : ""' in source
    assert 'id="fullRefreshButton"' in (Path(__file__).resolve().parents[1] / "static" / "omni.html").read_text(encoding="utf-8")


def test_api_settings_save_is_process_only(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "update_env_values", lambda updates, path: calls.append((updates, path)))
    monkeypatch.setattr(app_module, "_reload_runtime_settings", lambda: None)
    monkeypatch.setenv("OPC_RUNTIME_VIDEO_GENERATION_OMNI_CHARACTER_API_MODEL", "before")
    monkeypatch.setenv("OPC_RUNTIME_OTU_API_KEY", "before")

    app_module.save_api_settings(
        {
            "omni_character_api_model": "otu:shared-model",
            "otu_api_key": "local-secret",
        }
    )

    assert calls == []
    assert os.environ["OPC_RUNTIME_VIDEO_GENERATION_OMNI_CHARACTER_API_MODEL"] == "otu:shared-model"
    assert os.environ["OPC_RUNTIME_OTU_API_KEY"] == "local-secret"
