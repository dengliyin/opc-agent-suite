from pathlib import Path

from agent import config
from agent.config import update_env_values


def test_update_env_values_preserves_existing_and_quotes_paths(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OTU_API_KEY=secret\n"
        "SCRIPT_ROOT=/old/scripts\n"
        "# keep me\n",
        encoding="utf-8",
    )

    update_env_values(
        {
            "SCRIPT_ROOT": "/new path/脚本",
            "REFERENCE_ROOT": "/refs",
        },
        env_path,
    )

    text = env_path.read_text(encoding="utf-8")
    assert "OTU_API_KEY=secret" in text
    assert "# keep me" in text
    assert 'SCRIPT_ROOT="/new path/脚本"' in text
    assert 'REFERENCE_ROOT="/refs"' in text


def test_global_settings_override_stale_local_model_values(tmp_path: Path, monkeypatch) -> None:
    global_env = tmp_path / ".env"
    global_env.write_text(
        "OTU_API_KEY=global-secret\n"
        "OTU_BASE_URL=https://global.test\n"
        "IMAGE_MODEL=global-image\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPC_ENV_FILE", str(global_env))
    monkeypatch.setenv("OTU_API_KEY", "secret")
    monkeypatch.setenv("OTU_BASE_URL", "https://stale.test")
    monkeypatch.setenv("IMAGE_MODEL", "stale-image")
    monkeypatch.setenv("IMAGE_FALLBACK_MODELS", "")

    settings = config.load_settings("omni")

    assert settings.otu_api_key == "global-secret"
    assert settings.otu_base_url == "https://global.test"
    assert settings.image_model == "global-image"
    assert settings.image_fallback_models == []


def test_completed_root_follows_configured_video_output_root(tmp_path: Path, monkeypatch) -> None:
    video_output_root = tmp_path / "纯AI视频" / "05AI片段" / "omni"
    monkeypatch.setenv("VIDEO_OUTPUT_ROOT", str(video_output_root))
    monkeypatch.delenv("VIDEO_ASSEMBLY_PENDING_ROOT", raising=False)

    settings = config.load_settings("omni")

    assert settings.completed_script_root == tmp_path / "纯AI视频" / "06合成工作区" / "omni"


def test_tracked_video_generation_settings_contain_no_api_keys() -> None:
    text = config.SETTINGS_PATH.read_text(encoding="utf-8")

    assert "OTU_API_KEY=" not in text
    assert "GROK_API_KEY=" not in text


def test_hybrid_omni_settings_use_independent_paths(tmp_path: Path, monkeypatch) -> None:
    script_root = tmp_path / "04适配脚本" / "omni"
    output_root = tmp_path / "05AI片段" / "omni"
    monkeypatch.setenv("HYBRID_OMNI_SCRIPT_ROOT", str(script_root))
    monkeypatch.setenv("HYBRID_OMNI_VIDEO_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("HYBRID_MIX_WORK_ROOT", "/stale/other-computer/path")

    settings = config.load_hybrid_omni_settings()

    assert settings.provider == "omni"
    assert settings.workflow == "hybrid_omni"
    assert settings.api_base_path == "/hybrid-omni/api"
    assert settings.script_root == script_root
    assert settings.video_output_root == output_root
    assert settings.completed_script_root == tmp_path / "08混剪工作区" / "片段产出归档" / "omni"
