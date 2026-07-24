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


def test_shared_settings_override_stale_local_model_values(tmp_path: Path, monkeypatch) -> None:
    shared = tmp_path / "agent_settings.env"
    shared.write_text(
        "OTU_BASE_URL=https://shared.test\n"
        "IMAGE_MODEL=shared-image\n"
        "IMAGE_FALLBACK_MODELS=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SETTINGS_PATH", shared)
    monkeypatch.setenv("OTU_API_KEY", "secret")
    monkeypatch.setenv("OTU_BASE_URL", "https://stale.test")
    monkeypatch.setenv("IMAGE_MODEL", "stale-image")

    settings = config.load_settings("omni")

    assert settings.otu_api_key == "secret"
    assert settings.otu_base_url == "https://shared.test"
    assert settings.image_model == "shared-image"
    assert settings.image_fallback_models == []


def test_tracked_video_generation_settings_contain_no_api_keys() -> None:
    text = config.SETTINGS_PATH.read_text(encoding="utf-8")

    assert "OTU_API_KEY=" not in text
    assert "GROK_API_KEY=" not in text
