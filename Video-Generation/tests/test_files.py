from pathlib import Path

from agent.config import Settings
from agent.files import (
    character_image_path,
    export_marker_path,
    find_product_reference,
    image_output_current,
    scan_scripts,
    script_to_dict,
    storyboard_image_path,
    video_output_path,
)
from agent.exporter import dated_export_root, export_completed_scripts, restore_exported_scripts
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
