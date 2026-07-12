from pathlib import Path

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
