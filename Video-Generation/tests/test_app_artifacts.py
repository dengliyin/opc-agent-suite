from pathlib import Path

import pytest
from fastapi import HTTPException

from agent import app as app_module
from agent.app import ArtifactDeleteRequest, ScriptDeleteRequest, _delete_artifact, _delete_scripts
from agent.config import Settings
from agent.files import character_image_path, storyboard_image_path, video_output_path
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


def test_delete_scripts_removes_script_assets_and_metadata_only(monkeypatch, tmp_path: Path) -> None:
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
    assert result["files_deleted"] == 6
    assert not script.exists()
    assert all(not path.exists() for path in assets)
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
