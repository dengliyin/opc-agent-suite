import json
from pathlib import Path

from agent import files as files_module
from agent.config import Settings
from agent.files import (
    character_image_path,
    export_marker_path,
    find_product_reference,
    find_product_references,
    image_output_current,
    scan_scripts,
    script_to_dict,
    storyboard_image_path,
    video_output_path,
)
from agent.exporter import (
    dated_export_root,
    deliver_hybrid_scripts,
    export_completed_scripts,
    restore_exported_scripts,
    restore_hybrid_deliveries,
)
from agent.product_lock import storyboard_meta_path, write_storyboard_product_lock_meta
from PIL import Image


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        provider="omni",
        provider_label="Omni",
        api_base_path="/omni/api",
        otu_api_key="",
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


def test_reference_matching_and_output_names(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "SIMC染发棒"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    reference = settings.reference_root / "SIMC染发棒.png"
    reference.write_bytes(b"png")
    md_path = product_dir / "demo.md"

    assert find_product_reference(settings.reference_root, "SIMC染发棒") == reference
    assert character_image_path(md_path, 2).name == "demo-片段2-人物图.png"
    assert storyboard_image_path(md_path, 2).name == "demo-片段2-故事版.png"
    assert video_output_path(settings, "SIMC染发棒", md_path, 2).name == "demo-片段2-omni.mp4"
    grok_settings = Settings(**{**settings.__dict__, "provider": "grok", "provider_label": "Grok", "api_base_path": "/grok/api"})
    assert character_image_path(md_path, 2, grok_settings.artifact_prefix).name == "demo-片段2-人物图.png"
    assert storyboard_image_path(md_path, 2, grok_settings.artifact_prefix).name == "demo-片段2-故事版.png"
    assert video_output_path(grok_settings, "SIMC染发棒", md_path, 2).name == "demo-片段2-grok.mp4"


def test_reference_matching_returns_all_product_skus(tmp_path: Path) -> None:
    reference_root = tmp_path / "refs"
    reference_root.mkdir()
    first = reference_root / "LUX-轻奢戒指-RG001-银色六爪.png"
    second = reference_root / "LUX-轻奢戒指-RG002-玫瑰金排钻.jpg"
    unrelated = reference_root / "LUX-轻奢项链-NK001.png"
    for path in [first, second, unrelated]:
        path.write_bytes(b"image")

    assert find_product_references(reference_root, "LUX-轻奢戒指") == [first, second]


def test_scan_scripts_requires_selection_when_product_has_multiple_references(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "LUX-轻奢戒指"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    first = settings.reference_root / "LUX-轻奢戒指-RG001.png"
    second = settings.reference_root / "LUX-轻奢戒指-RG002.png"
    first.write_bytes(b"image")
    second.write_bytes(b"image")
    (product_dir / "script.md").write_text("# Segment 1\n", encoding="utf-8")

    script = scan_scripts(settings)[0]

    assert script.reference_image is None
    assert script.reference_images == (first, second)


def test_scan_scripts_reads_product_md(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.jpg").write_bytes(b"jpg")
    (product_dir / "script.md").write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A\n"
        "## B. 故事板图片提示词\n"
        "B\n",
        encoding="utf-8",
    )

    scripts = scan_scripts(settings)

    assert len(scripts) == 1
    assert scripts[0].product_name == "P1"
    assert scripts[0].reference_image is not None
    assert scripts[0].segments[0].character_prompt == "A"


def test_hybrid_scan_and_output_preserve_type_and_product(tmp_path: Path) -> None:
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider_label": "混剪 Omni",
            "api_base_path": "/hybrid-omni/api",
            "workflow": "hybrid_omni",
        }
    )
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.jpg").write_bytes(b"jpg")
    markdown = (
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A\n"
        "## B. 故事板图片提示词\n"
        "B\n"
    )
    hook = settings.script_root / "混剪-钩子" / "P1" / "来源A" / "hook.md"
    cta = settings.script_root / "混剪-CTA" / "P1" / "来源B" / "cta.md"
    hook.parent.mkdir(parents=True)
    cta.parent.mkdir(parents=True)
    hook.write_text(markdown, encoding="utf-8")
    cta.write_text(markdown, encoding="utf-8")

    scripts = scan_scripts(settings)

    assert [(item.script_type, item.product_name) for item in scripts] == [
        ("混剪-CTA", "P1"),
        ("混剪-钩子", "P1"),
    ]
    hook_script = next(item for item in scripts if item.script_type == "混剪-钩子")
    payload = script_to_dict(settings, hook_script)
    assert payload["script_type"] == "混剪-钩子"
    assert video_output_path(settings, "P1", hook, 1) == (
        settings.video_output_root / "混剪-钩子" / "P1" / "hook-片段1-omni.mp4"
    )


def test_hybrid_delivery_moves_video_to_archive_and_persists_completion(tmp_path: Path) -> None:
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider_label": "混剪 Omni",
            "api_base_path": "/hybrid-omni/api",
            "workflow": "hybrid_omni",
            "completed_root": tmp_path / "08混剪工作区" / "片段产出归档",
        }
    )
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.jpg").write_bytes(b"ref")
    md_path = settings.script_root / "混剪-钩子" / "P1" / "来源A" / "hook.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\nA\n"
        "## B. 故事板图片提示词\nB\n",
        encoding="utf-8",
    )
    video = video_output_path(settings, "P1", md_path, 1)
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")

    result = deliver_hybrid_scripts(settings, scan_scripts(settings), [str(md_path)])

    assert len(result["exported"]) == 1
    assert export_marker_path(md_path).exists()
    archive_dir = Path(result["exported"][0]["export_dir"])
    archived_video = archive_dir / video.name
    assert not video.exists()
    assert archived_video.exists()
    assert archived_video.with_suffix(".mp4.delivery.json").exists()
    assert archive_dir == dated_export_root(settings) / "混剪-钩子" / "P1" / "来源A" / "hook"
    assert (archive_dir / md_path.name).exists()

    payload = script_to_dict(settings, scan_scripts(settings)[0])
    assert payload["exported"] is True
    assert payload["complete"] is True
    assert payload["upload_status"] == "已导出"
    assert payload["segments"][0]["video_exists"] is True


def test_restore_hybrid_delivery_moves_video_back_and_removes_delivery_records(tmp_path: Path) -> None:
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider_label": "混剪 Omni",
            "api_base_path": "/hybrid-omni/api",
            "workflow": "hybrid_omni",
            "completed_root": tmp_path / "08混剪工作区" / "片段产出归档",
        }
    )
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.jpg").write_bytes(b"ref")
    md_path = settings.script_root / "混剪-CTA" / "P1" / "来源B" / "cta.md"
    md_path.parent.mkdir(parents=True)
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\nA\n"
        "## B. 故事板图片提示词\nB\n",
        encoding="utf-8",
    )
    video = video_output_path(settings, "P1", md_path, 1)
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    delivered = deliver_hybrid_scripts(settings, scan_scripts(settings), [str(md_path)])
    archived_video = Path(delivered["exported"][0]["export_dir"]) / video.name

    result = restore_hybrid_deliveries(settings, scan_scripts(settings), [str(md_path)])

    assert len(result["restored"]) == 1
    assert video.exists()
    assert not archived_video.exists()
    assert not export_marker_path(md_path).exists()
    assert not video.with_suffix(".mp4.delivery.json").exists()
    assert script_to_dict(settings, scan_scripts(settings)[0])["exported"] is False


def test_scan_scripts_matches_reference_with_code_prefix(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "海蓝之谜精粹水"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "LM01-海蓝之谜精粹水.jpg").write_bytes(b"jpg")
    (product_dir / "script.md").write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A\n"
        "## B. 故事板图片提示词\n"
        "B\n",
        encoding="utf-8",
    )

    scripts = scan_scripts(settings)

    assert len(scripts) == 1
    assert scripts[0].reference_image == settings.reference_root / "LM01-海蓝之谜精粹水.jpg"


def test_scan_archived_scripts_requires_date_product_script_layout(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.png").write_bytes(b"ref")
    (settings.reference_root / "P2.png").write_bytes(b"ref")
    dated_dir = settings.completed_script_root / "2026-07-08" / "P1" / "dated"
    legacy_dir = settings.completed_script_root / "P2" / "legacy"
    dated_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    markdown = (
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A\n"
        "## B. 故事板图片提示词\n"
        "B\n"
    )
    (dated_dir / "dated.md").write_text(markdown, encoding="utf-8")
    (legacy_dir / "legacy.md").write_text(markdown, encoding="utf-8")

    scripts = scan_scripts(settings, include_archived=True)

    assert [script.product_name for script in scripts] == ["P1"]
    assert [script.product_dir.name for script in scripts] == ["P1"]
    assert all(script.exported for script in scripts)


def test_catalog_summary_separates_video_full_mode_and_cleaned_archive(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.png").write_bytes(b"ref")
    archive_dir = settings.completed_script_root / "2026-07-08" / "P1" / "quick"
    archive_dir.mkdir(parents=True)
    md_path = archive_dir / "quick.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\nA\n"
        "## B. 故事板图片提示词\nB\n",
        encoding="utf-8",
    )
    marker = {
        "media_cleaned": True,
        "moved_files": [str(archive_dir / "quick-片段1-omni.mp4")],
        "copied_files": [str(md_path)],
        "media_files": [{"name": "quick-片段1-omni.mp4", "type": "video", "cleaned": True}],
    }
    export_marker_path(md_path).write_text(json.dumps(marker), encoding="utf-8")

    scripts = scan_scripts(settings, include_archived=True)
    summary = files_module.summarize_catalog(settings, scripts)
    payload = script_to_dict(settings, scripts[0])

    assert summary["video_scripts"] == 1
    assert summary["full_mode_completed_scripts"] == 0
    assert summary["exported_scripts"] == 1
    assert summary["cleaned_exported_scripts"] == 1
    assert payload["has_video"] is True
    assert payload["full_mode_complete"] is False


def test_scan_archived_scripts_matches_references_once_per_product(tmp_path: Path, monkeypatch) -> None:
    settings = settings_for(tmp_path)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.png").write_bytes(b"ref")
    markdown = (
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\nA\n"
        "## B. 故事板图片提示词\nB\n"
    )
    for date in ("2026-07-08", "2026-07-09"):
        script_dir = settings.completed_script_root / date / "P1" / date
        script_dir.mkdir(parents=True)
        (script_dir / f"{date}.md").write_text(markdown, encoding="utf-8")

    original = files_module.find_product_references
    calls: list[str] = []

    def counted(reference_root: Path, product_name: str):
        calls.append(product_name)
        return original(reference_root, product_name)

    monkeypatch.setattr(files_module, "find_product_references", counted)

    scripts = scan_scripts(settings, include_archived=True)

    assert len(scripts) == 2
    assert calls == ["P1"]


def test_grok_image_outputs_must_match_configured_aspect(tmp_path: Path) -> None:
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "grok",
            "provider_label": "Grok",
            "api_base_path": "/grok/api",
        }
    )
    vertical = tmp_path / "vertical.png"
    landscape = tmp_path / "landscape.png"
    Image.new("RGB", (1080, 1920), (255, 255, 255)).save(vertical)
    Image.new("RGB", (1448, 1086), (255, 255, 255)).save(landscape)

    assert image_output_current(settings, vertical) is True
    assert image_output_current(settings, landscape) is False


def test_grok_stale_image_reports_aspect_reason(tmp_path: Path) -> None:
    settings = Settings(
        **{
            **settings_for(tmp_path).__dict__,
            "provider": "grok",
            "provider_label": "Grok",
            "api_base_path": "/grok/api",
        }
    )
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.png").write_bytes(b"ref")
    md_path = product_dir / "demo.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A1\n"
        "## B. 故事板图片提示词\n"
        "B1\n",
        encoding="utf-8",
    )
    Image.new("RGB", (1536, 1024), (255, 255, 255)).save(character_image_path(md_path, 1, settings.artifact_prefix))

    payload = script_to_dict(settings, scan_scripts(settings)[0])
    segment = payload["segments"][0]

    assert segment["character_exists"] is False
    assert segment["character_stale"] is True
    assert segment["character_stale_reason"] == "比例不符：1536x1024，要求 9:16"


def test_export_completed_script_copies_script_and_moves_assets_to_completed_root(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.write_bytes(b"ref")
    md_path = product_dir / "demo.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A1\n"
        "## B. 故事板图片提示词\n"
        "B1\n"
        "# Segment 2：00:01 - 00:02\n"
        "## A. 人物造型参考板提示词\n"
        "A2\n"
        "## B. 故事板图片提示词\n"
        "B2\n",
        encoding="utf-8",
    )

    scripts = scan_scripts(settings)
    script = scripts[0]
    for index in [1, 2]:
        character_image_path(md_path, index).write_bytes(f"character-{index}".encode())
        storyboard = storyboard_image_path(md_path, index)
        storyboard.write_bytes(f"storyboard-{index}".encode())
        write_storyboard_product_lock_meta(storyboard, "P1", reference, 1)
        video = video_output_path(settings, "P1", md_path, index)
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(f"video-{index}".encode())

    before = script_to_dict(settings, script)
    assert before["complete"] is True
    assert before["exported"] is False

    result = export_completed_scripts(settings, scripts, [str(md_path)])

    assert len(result["exported"]) == 1
    export_dir = Path(result["exported"][0]["export_dir"])
    archived_md_path = export_dir / md_path.name
    assert export_dir == dated_export_root(settings) / "P1" / md_path.stem
    assert (export_dir / md_path.name).exists()
    assert (export_dir / character_image_path(md_path, 1).name).exists()
    assert (export_dir / storyboard_image_path(md_path, 1).name).exists()
    assert (export_dir / storyboard_meta_path(storyboard_image_path(md_path, 1)).name).exists()
    assert (export_dir / video_output_path(settings, "P1", md_path, 1).name).exists()
    assert not video_output_path(settings, "P1", md_path, 1).exists()
    assert not character_image_path(md_path, 1).exists()
    assert not storyboard_image_path(md_path, 1).exists()
    assert not storyboard_meta_path(storyboard_image_path(md_path, 1)).exists()
    assert md_path.exists()
    assert not export_marker_path(md_path).exists()
    assert export_marker_path(archived_md_path).exists()
    assert scan_scripts(settings) == []
    marker = export_marker_path(archived_md_path).read_text(encoding="utf-8")
    assert '"upload_status": "未记录"' in marker
    assert '"media_files"' in marker

    archived_scripts = scan_scripts(settings, include_archived=True)
    assert len(archived_scripts) == 1
    after = script_to_dict(settings, archived_scripts[0])
    assert after["exported"] is True
    assert after["complete"] is True
    first_segment = after["segments"][0]
    assert first_segment["character_exists"] is True
    assert first_segment["storyboard_exists"] is True
    assert first_segment["video_exists"] is True
    assert str(export_dir) in first_segment["character_path"]
    assert str(export_dir) in first_segment["storyboard_path"]
    assert str(export_dir) in first_segment["video_path"]


def test_restore_exported_script_moves_images_back_but_leaves_videos_exported_by_default(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    reference = settings.reference_root / "P1.png"
    reference.write_bytes(b"ref")
    md_path = product_dir / "demo.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A1\n"
        "## B. 故事板图片提示词\n"
        "B1\n",
        encoding="utf-8",
    )
    character = character_image_path(md_path, 1)
    character.write_bytes(b"character")
    storyboard = storyboard_image_path(md_path, 1)
    storyboard.write_bytes(b"storyboard")
    write_storyboard_product_lock_meta(storyboard, "P1", reference, 1)
    video = video_output_path(settings, "P1", md_path, 1)
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")

    scripts = scan_scripts(settings)
    export_completed_scripts(settings, scripts, [str(md_path)])
    archived_script = scan_scripts(settings, include_archived=True)[0]
    archived_md_path = archived_script.md_path

    assert not character.exists()
    assert not storyboard.exists()
    assert not storyboard_meta_path(storyboard).exists()
    assert not video.exists()
    assert md_path.exists()

    result = restore_exported_scripts(settings, [archived_script], [str(archived_md_path)], restore_videos=False)

    assert len(result["restored"]) == 1
    assert md_path.exists()
    assert character.exists()
    assert storyboard.exists()
    assert storyboard_meta_path(storyboard).exists()
    assert not video.exists()
    assert not archived_md_path.exists()
    assert not export_marker_path(archived_md_path).exists()


def test_export_script_with_videos_only(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    product_dir = settings.script_root / "P1"
    product_dir.mkdir(parents=True)
    settings.reference_root.mkdir(parents=True)
    (settings.reference_root / "P1.png").write_bytes(b"ref")
    md_path = product_dir / "video-only.md"
    md_path.write_text(
        "# Segment 1：00:00 - 00:01\n"
        "## A. 人物造型参考板提示词\n"
        "A1\n"
        "## B. 故事板图片提示词\n"
        "B1\n",
        encoding="utf-8",
    )
    video = video_output_path(settings, "P1", md_path, 1)
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")

    scripts = scan_scripts(settings)
    result = export_completed_scripts(settings, scripts, [str(md_path)])

    assert len(result["exported"]) == 1
    assert result["skipped"] == []
    export_dir = Path(result["exported"][0]["export_dir"])
    assert export_dir == dated_export_root(settings) / "P1" / md_path.stem
    assert (export_dir / md_path.name).exists()
    assert (export_dir / video.name).exists()
    assert md_path.exists()
    assert not video.exists()
    assert not (export_dir / character_image_path(md_path, 1).name).exists()
    assert not (export_dir / storyboard_image_path(md_path, 1).name).exists()
    assert export_marker_path(export_dir / md_path.name).exists()
