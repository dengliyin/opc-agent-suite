import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "software/Script-Adaptation-app/opc_engine/features/script_adaptation/script_adaptation_agent_web.py"
)
SPEC = importlib.util.spec_from_file_location("script_adaptation_agent_web", MODULE_PATH)
assert SPEC and SPEC.loader
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


def test_status_record_uses_preloaded_log_without_reading_directory(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "P1" / "adapted.md"
    preloaded = {
        "files": {
            "adapted.md": {
                "status": "completed",
                "source_filename": "source.md",
            }
        }
    }

    def unexpected_read(_output_dir: Path):
        raise AssertionError("preloaded status log should be reused")

    monkeypatch.setattr(web, "read_adaptation_status_log", unexpected_read)

    record = web.adaptation_status_record_for_script(
        output_path,
        "source.md",
        "/scripts/source.md",
        status_log=preloaded,
    )

    assert record["status"] == "completed"
