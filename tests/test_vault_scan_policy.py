from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_all_compose_agents_use_lightweight_health_endpoints() -> None:
    compose = read("docker-compose.yml")

    assert compose.count("HEALTH_PATH: /health") == 14
    assert "HEALTH_PATH: /api/" not in compose


def test_high_volume_agents_use_persistent_vault_snapshots() -> None:
    files = (
        "Script-Analysis/scripts/web_app.py",
        "Hybrid-Script-Analysis/scripts/web_app.py",
        "Script-Generation/opc_engine/features/script_generation/script_generation_agent_web.py",
        "Hybrid-Script-Generation/opc_engine/features/script_generation/script_generation_agent_web.py",
        "Script-Adaptation/software/Script-Adaptation-app/opc_engine/features/script_adaptation/script_adaptation_agent_web.py",
        "Hybrid-Script-Adaptation/software/Hybrid-Script-Adaptation-app/opc_engine/features/script_adaptation/script_adaptation_agent_web.py",
        "Video-Generation/agent/app.py",
        "Finished-Video-Manager/finished_video_manager/web.py",
        "Product-Script-Rewrite/product_script_rewrite/web.py",
        "Hybrid-Video-Mixer/app/server.py",
        "Hybrid-Audio-Generation/audio_agent/web.py",
        "Auto-Publish-Pipeline/auto_publish_pipeline/web.py",
        "Script-Generation/opc_engine/features/unified_script_agent/core.py",
    )

    for relative in files:
        source = read(relative)
        assert "cached_or_empty" in source, relative
        assert "refresh_snapshot" in source, relative


def test_video_generation_initial_page_load_does_not_refresh_catalog() -> None:
    source = read("Video-Generation/static/app.js")

    assert "refreshAll().catch" in source
    assert 'api(catalogPath)' in source
    assert '$("#refreshButton").addEventListener("click", () => refreshAll(true));' in source


def test_video_assembly_does_not_scan_on_process_start() -> None:
    source = read("Video-Generation/assembly/router.py")

    assert "\nscan_now()\n" not in source
