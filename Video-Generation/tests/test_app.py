from fastapi.testclient import TestClient

from agent import app as app_module


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


def test_media_cleanup_route_is_owned_by_assembly_agent():
    paths = {route.path for route in app_module.app.routes}

    assert "/api/clear-archived-media" not in paths
    assert "/omni/api/clear-archived-media" not in paths
    assert "/grok/api/clear-archived-media" not in paths
