from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.app import ArtifactDeleteRequest, _delete_artifact
from agent.config import Settings
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
