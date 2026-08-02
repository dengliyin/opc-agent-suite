from pathlib import Path

import pytest
from fastapi import HTTPException

from agent import app as app_module
from agent.app import (
    ArtifactDeleteRequest,
    ExportRequest,
    ScriptDeleteRequest,
    _api_summary_payload,
    _delete_artifact,
    _delete_scripts,
    _export_completed,
    _function_api_model_options,
)
from agent.config import Settings
from agent.files import character_image_path, scan_scripts, storyboard_image_path, video_output_path
from agent.product_lock import storyboard_meta_path


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        provider="omni",
        provider_label="Omni",
        api_base_path="/omni/api",
        otu_api_key="otu",
        otu_base_url="https://otuapi.com",
        image_model="image2",
        image_fallback_models=[],
        omni_model="omni_flash-10s",
        grok_api_key="grok",
        grok_base_url="https://www.runninghub.cn",
        grok_image_aspect_ratio="9:16",
        grok_image_resolution="4k",
        grok_video_aspect_ratio="9:16",
        grok_video_resolution="720p",
        grok_video_duration=10,
        image_size="4096x3072",
        video_size="720x1280",
        overwrite=False,
        script_root=tmp_path / "scripts",
        reference_root=tmp_path / "refs",
        video_output_root=tmp_path / "videos",
    )


def test_delete_artifact_removes_storyboard_and_product_lock_meta(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    storyboard = settings.script_root / "P1" / "demo-片段1-故事版.png"
    storyboard.parent.mkdir(parents=True)
    storyboard.write_bytes(b"story")
    meta_path = storyboard_meta_path(storyboard)
    meta_path.write_text("{}", encoding="utf-8")

    result = _delete_artifact(settings, ArtifactDeleteRequest(path=str(storyboard)))

    assert result["deleted"] == [str(storyboard.resolve()), str(meta_path.resolve())]
    assert not storyboard.exists()
    assert not meta_path.exists()


def test_delete_artifact_rejects_script_file(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    script = settings.script_root / "P1" / "demo.md"
    script.parent.mkdir(parents=True)
    script.write_text("# script", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _delete_artifact(settings, ArtifactDeleteRequest(path=str(script)))

    assert exc.value.status_code == 403
    assert script.exists()


class FakeManager:
    def __init__(self, jobs=None):
        self.jobs = jobs or []

    def list_jobs(self):
        return self.jobs


def create_script_with_assets(settings: Settings) -> tuple[Path, list[Path]]:
    script = settings.script_root / "P1" / "demo.md"
    script.parent.mkdir(parents=True)
    script.write_text(
        "# Segment 1：00:00.000 - 00:10.000\n"
        "## A. 人物造型参考板提示词\n人物\n"
        "## B. 故事板图片提示词\n故事\n"
        "### 镜头 1 (00:00.000 - 00:10.000)\n内容\n",
        encoding="utf-8",
    )
    character = character_image_path(script, 1, settings.artifact_prefix)
    storyboard = storyboard_image_path(script, 1, settings.artifact_prefix)
    video = video_output_path(settings, "P1", script, 1)
    video.parent.mkdir(parents=True)
    for path in (character, storyboard, video):
        path.write_bytes(b"asset")
    storyboard_meta_path(storyboard).write_text("{}", encoding="utf-8")
    storyboard_meta_path(video).write_text("{}", encoding="utf-8")
    return script, [character, storyboard, storyboard_meta_path(storyboard), video, storyboard_meta_path(video)]


def test_delete_scripts_preserves_adapted_script_and_removes_fragment_assets(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    script, assets = create_script_with_assets(settings)
    reference = settings.reference_root / "P1.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"reference")
    sibling = script.parent / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(app_module, "_settings_for", lambda _provider: settings)
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: FakeManager())

    result = _delete_scripts("omni", ScriptDeleteRequest(script_paths=[str(script)]))

    assert result["scripts_deleted"] == 1
    assert result["files_deleted"] == 5
    assert script.exists()
    assert all(not path.exists() for path in assets)
    assert scan_scripts(settings) == []
    assert reference.exists()
    assert sibling.exists()


def test_delete_scripts_rejects_script_in_active_job(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    script, assets = create_script_with_assets(settings)
    manager = FakeManager([{"status": "running", "script_paths": [str(script)]}])
    monkeypatch.setattr(app_module, "_settings_for", lambda _provider: settings)
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: manager)

    with pytest.raises(HTTPException) as exc:
        _delete_scripts("omni", ScriptDeleteRequest(script_paths=[str(script)]))

    assert exc.value.status_code == 409
    assert script.exists()
    assert all(path.exists() for path in assets)


def test_export_allows_selected_script_outside_active_job(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    selected = settings.script_root / "P1" / "completed.md"
    active = settings.script_root / "P1" / "running.md"
    manager = FakeManager([{"status": "running", "script_paths": [str(active)]}])
    monkeypatch.setattr(app_module, "_settings_for", lambda _provider: settings)
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: manager)
    monkeypatch.setattr(app_module, "scan_scripts", lambda _settings: ["catalog"])
    monkeypatch.setattr(
        app_module,
        "export_completed_scripts",
        lambda _settings, scripts, paths: {"scripts": scripts, "paths": paths},
    )

    result = _export_completed("omni", ExportRequest(script_paths=[str(selected)]))

    assert result == {"scripts": ["catalog"], "paths": [str(selected)]}


def test_export_rejects_selected_script_in_active_job(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    selected = settings.script_root / "P1" / "running.md"
    manager = FakeManager([{"status": "queued", "script_paths": [str(selected)]}])
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: manager)

    with pytest.raises(HTTPException) as exc:
        _export_completed("omni", ExportRequest(script_paths=[str(selected)]))

    assert exc.value.status_code == 409
    assert "所选脚本正在运行或排队" in exc.value.detail


def test_export_allows_script_already_done_in_running_batch(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    selected = settings.script_root / "P1" / "done.md"
    manager = FakeManager(
        [
            {
                "status": "running",
                "script_paths": [str(selected)],
                "script_statuses": {str(selected): {"status": "done"}},
            }
        ]
    )
    monkeypatch.setattr(app_module, "_settings_for", lambda _provider: settings)
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: manager)
    monkeypatch.setattr(app_module, "scan_scripts", lambda _settings: ["catalog"])
    monkeypatch.setattr(
        app_module,
        "export_completed_scripts",
        lambda _settings, scripts, paths: {"scripts": scripts, "paths": paths},
    )

    result = _export_completed("omni", ExportRequest(script_paths=[str(selected)]))

    assert result == {"scripts": ["catalog"], "paths": [str(selected)]}


def test_export_rejects_when_active_job_processes_all_scripts(monkeypatch, tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    selected = settings.script_root / "P1" / "completed.md"
    manager = FakeManager([{"status": "running", "script_paths": None}])
    monkeypatch.setattr(app_module, "_manager_for", lambda _provider: manager)

    with pytest.raises(HTTPException) as exc:
        _export_completed("omni", ExportRequest(script_paths=[str(selected)]))

    assert exc.value.status_code == 409
    assert "处理全部脚本" in exc.value.detail


def test_otu_image_ui_only_exposes_async_gpt_image_2() -> None:
    summary = _api_summary_payload()
    otu_models = next(item["models"] for item in summary["api_inventory"] if item["api"] == "OTU API")
    image_models = [item for item in otu_models if "图片" in item["role"]]

    assert summary["endpoint_count"] == 7
    assert [item["name"] for item in image_models] == ["gpt-image-2 / gpt-image-2-2K / gpt-image-2-4K"]
    assert image_models[0]["endpoints"] == ["/v1/videos", "/v1/videos/{task_id}"]

    options = _function_api_model_options("characters", "otu:gpt-image-2-4K")
    otu_values = [item["value"] for item in options if item["value"].startswith("otu:")]
    assert otu_values == ["otu:gpt-image-2-4K"]
