import json
from types import SimpleNamespace

from agent.pipeline_cli import existing_exports


def test_existing_exports_recovers_completed_work_after_restart(tmp_path):
    active = tmp_path / "active" / "script.md"
    export_dir = tmp_path / "pending" / "script"
    export_dir.mkdir(parents=True)
    archived = export_dir / "script.md"
    archived.write_text("script", encoding="utf-8")
    marker = export_dir / "script.exported.json"
    marker.write_text(
        json.dumps(
            {
                "active_md_path": str(active),
                "md_path": str(archived),
                "export_dir": str(export_dir),
                "product_name": "Product",
                "copied_files": [],
                "moved_files": [],
            }
        ),
        encoding="utf-8",
    )

    recovered = existing_exports(SimpleNamespace(completed_script_root=tmp_path / "pending"), [str(active)])

    assert len(recovered) == 1
    assert recovered[0]["active_md_path"] == str(active.resolve())
    assert recovered[0]["export_dir"] == str(export_dir)
