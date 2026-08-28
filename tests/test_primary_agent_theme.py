from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME_HREF = "/opc-theme.css?v=20260828"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_static_primary_agents_use_shared_theme_and_console_navigation() -> None:
    pages = (
        "Script-Analysis/web/index.html",
        "Script-Generation/opc_engine/features/unified_script_agent/static/index.html",
        "Video-Generation/static/index.html",
        "Video-Generation/static/omni.html",
        "Video-Generation/static/grok.html",
        "Video-Generation/static/hybrid-omni.html",
        "Video-Generation/static/settings.html",
        "Video-Generation/static/api-settings.html",
        "Video-Generation/static/assembly/index.html",
        "Hybrid-Audio-Generation/static/index.html",
        "Hybrid-Video-Mixer/static/index.html",
    )
    for page in pages:
        html = read(page)
        assert THEME_HREF in html, page
        assert 'class="opc-agent"' in html, page
        assert "127.0.0.1:8888" in html or "localhost:8888" in html, page


def test_shared_theme_matches_console_palette() -> None:
    css = read("opc_shared/ui/opc-theme.css")
    for value in ("#0b0d10", "#15191f", "#29313b", "#f3f5f7", "#98a2ad", "#70a7ff", "#66d19e"):
        assert value in css


def test_shared_theme_overrides_legacy_light_surfaces() -> None:
    css = read("opc_shared/ui/opc-theme.css")
    for selector in (
        ".agent-status-chip.idle",
        ".script-item",
        ".api-info-card",
        ".queueToolbar",
        ".progressPanel",
        ".badge.ready",
        ".statusPill.mutation",
        ".statusFilters button.active",
        ".smallPath",
    ):
        assert selector in css


def test_inline_primary_agents_inject_shared_theme() -> None:
    finished_source = read("Finished-Video-Manager/finished_video_manager/web.py")
    auto_source = read("Auto-Publish-Pipeline/auto_publish_pipeline/web.py")
    for source in (finished_source, auto_source):
        assert THEME_HREF in source
        assert "opc-agent" in source
        assert "127.0.0.1:8888" in source
        assert '"/opc-theme.css"' in source


def test_theme_file_exists_and_has_no_workspace_dependency() -> None:
    spec = importlib.util.spec_from_file_location("opc_ui_theme", ROOT / "opc_shared/ui_theme.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.THEME_PATH.is_file()
    assert module.theme_css().startswith(":root")
