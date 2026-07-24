from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import server  # noqa: E402
import video_assembly as core  # noqa: E402


class CoreTests(unittest.TestCase):
    def test_parse_segments_reads_target_duration_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "script.md"
            path.write_text(
                "# Segment 1：00:00 - 00:09.5\n**[音频文案]** 第一段\n"
                "# Segment 2: 00:09.5 - 00:17\n**[音频文案]** 第二段\n",
                encoding="utf-8",
            )
            segments = core.parse_segments(path)
        self.assertEqual([segment.index for segment in segments], [1, 2])
        self.assertEqual([segment.target_duration for segment in segments], [9.5, 7.5])
        self.assertEqual(segments[1].audio_text, "第二段")

    def test_prepare_project_keeps_active_tail_at_original_speed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script_dir = root / "script"
            script_dir.mkdir()
            md_path = script_dir / "script.md"
            source = script_dir / "片段1.mp4"
            md_path.write_text("# Segment 1：0 - 5\n**[音频文案]** 完整口播\n", encoding="utf-8")
            source.touch()
            vendor_root = root / "vendor"
            vendor_root.mkdir()
            (vendor_root / "gsap.min.js").write_text("", encoding="utf-8")
            item = core.ScriptItem(
                model="omni",
                date="2026-07-14",
                product="产品",
                script_dir=str(script_dir),
                md_path=str(md_path),
                video_paths=[str(source)],
                output_path=str(root / "output.mp4"),
                status="missing",
            )
            with (
                patch.object(core, "WORK_ROOT", root / "work"),
                patch.object(core, "VENDOR_ROOT", vendor_root),
                patch.object(core, "media_duration", return_value=6.0),
                patch.object(core, "tail_audio_is_active", return_value=True),
            ):
                project_dir, clips = core.prepare_project(item)
                self.assertTrue((project_dir / "media" / "segment_01.mp4").exists())

        self.assertEqual(clips[0]["duration"], 6.0)
        self.assertEqual(clips[0]["action"], "keep_active_tail")
        self.assertEqual(clips[0]["speed"], 1.0)

    def test_scan_classifies_all_four_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "pending"
            output = root / "output"
            product = pending / "omni" / "2026-07-11" / "产品"
            product.mkdir(parents=True)

            done = product / "done"
            done.mkdir()
            (done / "done.md").write_text("# Segment 1：0 - 1", encoding="utf-8")
            (done / "片段1.mp4").touch()
            done_output = output / "产品"
            done_output.mkdir(parents=True)
            (done_output / "done.mp4").touch()

            missing = product / "missing"
            missing.mkdir()
            (missing / "missing.md").write_text("# Segment 1：0 - 1", encoding="utf-8")
            (missing / "片段1.mp4").touch()

            archived = product / "archived"
            archived.mkdir()
            (archived / "archived.md").write_text("# Segment 1：0 - 1", encoding="utf-8")

            invalid = product / "invalid"
            invalid.mkdir()
            (invalid / "片段1.mp4").touch()

            items = core.scan_items(pending, output)

        status_by_name = {Path(item.script_dir).name: item.status for item in items}
        self.assertEqual(
            status_by_name,
            {"done": "done", "missing": "missing", "archived": "archived", "invalid": "invalid"},
        )
        missing_item = next(item for item in items if Path(item.script_dir).name == "missing")
        self.assertEqual(Path(missing_item.output_path), output / "产品" / "missing.mp4")

    def test_scan_recognizes_legacy_finished_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "pending"
            output = root / "output"
            script_dir = pending / "omni" / "2026-07-11" / "产品" / "demo"
            script_dir.mkdir(parents=True)
            (script_dir / "demo.md").write_text("# Segment 1：0 - 1", encoding="utf-8")
            (script_dir / "片段1.mp4").touch()
            legacy_output = output / "omni" / "2026-07-11" / "产品" / "demo.mp4"
            legacy_output.parent.mkdir(parents=True)
            legacy_output.touch()

            item = core.scan_items(pending, output)[0]

        self.assertEqual(item.status, "done")
        self.assertEqual(Path(item.output_path), legacy_output)

    def test_confirmation_rejects_stale_scan_and_filters_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "scan.json"
            report = {
                "scan_id": "current",
                "items": [
                    {"script_dir": "/one", "status": "missing"},
                    {"script_dir": "/two", "status": "missing"},
                ],
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with patch.object(server.core, "REPORT_PATH", report_path):
                with self.assertRaisesRegex(ValueError, "重新扫描"):
                    server.confirmed_report("stale", ["/one"])
                confirmed, selected = server.confirmed_report("current", ["/one"])

        self.assertEqual([item["script_dir"] for item in selected], ["/one"])
        states = {item["script_dir"]: item["status"] for item in confirmed["items"]}
        self.assertEqual(states, {"/one": "missing", "/two": "skipped"})

    def test_cleanup_confirmation_only_accepts_done_items_with_source_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "scan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "scan_id": "current",
                        "items": [
                            {
                                "model": "omni",
                                "date": "2026-07-12",
                                "product": "产品",
                                "script_dir": "/ready",
                                "md_path": "/ready/ready.md",
                                "video_paths": ["/ready/clip.mp4"],
                                "output_path": "/output/ready.mp4",
                                "status": "done",
                                "cleanup_eligible": True,
                            },
                            {
                                "model": "omni",
                                "date": "2026-07-12",
                                "product": "产品",
                                "script_dir": "/clean",
                                "md_path": "/clean/clean.md",
                                "video_paths": [],
                                "output_path": "/output/clean.mp4",
                                "status": "done",
                                "cleanup_eligible": False,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(server.core, "REPORT_PATH", report_path):
                selected = server.confirmed_cleanup_items("current", ["/ready"])
                with self.assertRaisesRegex(ValueError, "不再可清理"):
                    server.confirmed_cleanup_items("current", ["/clean"])

        self.assertEqual([item.script_dir for item in selected], ["/ready"])

    def test_generated_composition_uses_only_local_gsap(self) -> None:
        html = core.build_index_html(
            [{"duration": 1.0, "media_name": "segment_01.mp4"}],
            total_duration=1.0,
        )
        self.assertIn('src="vendor/gsap.min.js"', html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_sticker_options_support_four_styles_and_reject_invalid_text(self) -> None:
        self.assertEqual(set(core.STICKER_STYLES), {"serif", "bubbly", "tiktok", "cinematic"})
        for style in core.STICKER_STYLES:
            options = core.normalize_sticker_options(
                {"enabled": True, "text": "立即入手", "style": style, "position": "top", "timing": "full"}
            )
            self.assertEqual(options["style"], style)
            self.assertTrue(options["enabled"])
        with self.assertRaisesRegex(ValueError, "贴纸文字"):
            core.normalize_sticker_options({"enabled": True, "text": ""})
        with self.assertRaisesRegex(ValueError, "36"):
            core.normalize_sticker_options({"enabled": True, "text": "字" * 37})

    def test_caption_mode_script_and_language_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            md_path = Path(temporary) / "omni-裂变-产品-FR-demo.md"
            md_path.write_text(
                "# Segment 1：0 - 1\n**[音频文案]** (Voiceover, French): Bonjour\n"
                "# Segment 2：1 - 2\n**[音频文案]** tout le monde\n",
                encoding="utf-8",
            )
            script = core.caption_script_text(md_path)
            language = core.caption_language(md_path)

        self.assertEqual(core.normalize_caption_mode(None), "none")
        self.assertEqual(core.normalize_caption_mode("karaoke"), "karaoke")
        with self.assertRaisesRegex(ValueError, "字幕模式"):
            core.normalize_caption_mode("classic")
        self.assertEqual(script, "Bonjour\ntout le monde")
        self.assertEqual(language, "fr")

    def test_sticker_library_loads_presets_by_product_and_country(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "CAR-车载吸尘器.md").write_text(
                "## 国家：英国 (UK)\n\n"
                "### UK-001\n\n- 文案：Clean every corner\n- 中文释义：清洁每个角落\n\n"
                "## 国家：法国 (FR)\n\n"
                "### FR-001\n\n- 文案：Nettoyez chaque recoin\n- 中文释义：清洁每个缝隙\n",
                encoding="utf-8",
            )
            library = core.load_sticker_library("CAR-车载吸尘器", root)
            missing = core.load_sticker_library("不存在的产品", root)

        self.assertTrue(library["available"])
        self.assertEqual([country["code"] for country in library["countries"]], ["UK", "FR"])
        self.assertEqual(library["countries"][1]["presets"][0]["text"], "Nettoyez chaque recoin")
        self.assertEqual(library["countries"][1]["presets"][0]["translation"], "清洁每个缝隙")
        self.assertFalse(missing["available"])

    def test_sticker_library_selection_requires_one_product(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "scan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "scan_id": "current",
                        "items": [
                            {"script_dir": "/one", "status": "missing", "product": "CAR-车载吸尘器"},
                            {"script_dir": "/two", "status": "missing", "product": "CAR-车载吸尘器"},
                            {"script_dir": "/three", "status": "missing", "product": "DRN-E99Pro无人机"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded = {
                "available": True,
                "product": "CAR-车载吸尘器",
                "path": "/library/CAR-车载吸尘器.md",
                "countries": [{"name": "英国", "code": "UK", "presets": []}],
            }
            with (
                patch.object(server.core, "REPORT_PATH", report_path),
                patch.object(server.core, "load_sticker_library", return_value=loaded) as loader,
            ):
                library = server.sticker_library_for_selection("current", ["/one", "/two"])
                mixed = server.sticker_library_for_selection("current", ["/one", "/three"])

        loader.assert_called_once_with("CAR-车载吸尘器")
        self.assertEqual(library["countries"][0]["code"], "UK")
        self.assertFalse(mixed["available"])
        self.assertIn("多个产品", mixed["reason"])

    def test_generated_composition_renders_escaped_timed_sticker(self) -> None:
        html = core.build_index_html(
            [{"duration": 5.0, "media_name": "segment_01.mp4"}],
            total_duration=5.0,
            sticker={
                "enabled": True,
                "text": "立即 <入手>",
                "style": "bubbly",
                "position": "bottom",
                "timing": "custom",
                "start": 1,
                "end": 3.5,
            },
        )

        self.assertIn('id="text-sticker"', html)
        self.assertIn('class="clip text-sticker-slot position-bottom"', html)
        self.assertIn('class="text-sticker-body style-bubbly"', html)
        for style in core.STICKER_STYLES:
            self.assertIn(f".text-sticker-body.style-{style}", html)
            block = re.search(rf"\.text-sticker-body\.style-{style} \{{(.*?)\n      \}}", html, re.S).group(1)
            self.assertNotIn("background:", block)
            self.assertNotIn("border:", block)
            self.assertNotIn("box-shadow:", block)
        self.assertIn('font-family: Georgia, "Songti SC", "STSong", serif', html)
        self.assertIn('font-family: "TikTok Sans", "Avenir Next", "PingFang SC", Arial, sans-serif', html)
        self.assertIn('data-start="1.000" data-duration="2.500" data-track-index="7"', html)
        self.assertIn("data-layout-allow-occlusion", html)
        self.assertIn('src: local("PingFang SC")', html)
        for font in (
            "Songti SC",
            "STSong",
            "Arial Rounded MT Bold",
            "PingFang SC",
            "TikTok Sans",
            "Avenir Next Condensed",
            "Arial Narrow",
        ):
            self.assertRegex(html, rf'@font-face \{{\s+font-family: "{re.escape(font)}";\s+src: local\("{re.escape(font)}"\);')
        self.assertIn("立即 &lt;入手&gt;", html)
        self.assertNotIn("立即 <入手>", html)
        self.assertIn('tl.fromTo("#text-sticker-body"', html)

    def test_confirmation_persists_sticker_settings_in_latest_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "scan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "scan_id": "current",
                        "items": [
                            {"script_dir": "/one", "status": "missing"},
                            {"script_dir": "/two", "status": "missing"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(server.core, "REPORT_PATH", report_path),
                patch.object(server.core, "caption_runtime_ready", return_value=True),
            ):
                confirmed, selected = server.confirmed_report(
                    "current",
                    ["/one"],
                    {"enabled": True, "text": "新品上市", "style": "cinematic", "position": "center", "timing": "full"},
                    caption_mode="karaoke",
                )
            persisted = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(selected[0]["sticker"]["style"], "cinematic")
        self.assertEqual(selected[0]["caption_mode"], "karaoke")
        self.assertEqual(confirmed["items"][0]["sticker"]["text"], "新品上市")
        self.assertEqual(persisted["items"][0]["sticker"]["position"], "center")
        self.assertEqual(persisted["items"][0]["caption_mode"], "karaoke")
        self.assertNotIn("sticker", persisted["items"][1])

    def test_confirmation_randomizes_distinct_sticker_texts_per_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "scan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "scan_id": "current",
                        "items": [
                            {"script_dir": "/one", "status": "missing", "product": "CAR-车载吸尘器"},
                            {"script_dir": "/two", "status": "missing", "product": "CAR-车载吸尘器"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            library = {
                "available": True,
                "product": "CAR-车载吸尘器",
                "path": "/library/CAR-车载吸尘器.md",
                "countries": [
                    {
                        "name": "英国",
                        "code": "UK",
                        "presets": [
                            {"id": "UK-001", "text": "Clean every corner", "translation": "清洁每个角落"},
                            {"id": "UK-002", "text": "Crumbs disappear fast", "translation": "碎屑快速消失"},
                        ],
                    }
                ],
            }
            with (
                patch.object(server.core, "REPORT_PATH", report_path),
                patch.object(server.core, "load_sticker_library", return_value=library),
            ):
                _, selected = server.confirmed_report(
                    "current",
                    ["/one", "/two"],
                    {"enabled": True, "text": "preview", "style": "tiktok", "position": "top", "timing": "full"},
                    "UK",
                )

        texts = [item["sticker"]["text"] for item in selected]
        self.assertEqual(set(texts), {"Clean every corner", "Crumbs disappear fast"})
        self.assertTrue(all(item["sticker"]["style"] == "tiktok" for item in selected))

    def test_scan_preserves_saved_sticker_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "pending"
            pending.mkdir()
            report_path = root / "scan.json"
            report_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "script_dir": "/saved",
                                "sticker": {
                                    "enabled": True,
                                    "text": "限时优惠",
                                    "style": "serif",
                                    "position": "bottom",
                                    "timing": "full",
                                },
                                "caption_mode": "karaoke",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            item = core.ScriptItem(
                model="omni",
                date="2026-07-13",
                product="产品",
                script_dir="/saved",
                md_path="/saved/saved.md",
                video_paths=["/saved/clip.mp4"],
                output_path="/output/saved.mp4",
                status="missing",
            )
            with (
                patch.object(server.core, "PENDING_ROOT", pending),
                patch.object(server.core, "REPORT_PATH", report_path),
                patch.object(server.core, "scan_items", return_value=[item]),
            ):
                payload = server.scan_now()

        self.assertEqual(payload["items"][0]["sticker"]["text"], "限时优惠")
        self.assertEqual(payload["items"][0]["sticker"]["style"], "serif")
        self.assertEqual(payload["items"][0]["caption_mode"], "karaoke")

    def test_assemble_karaoke_renders_temporary_video_then_captions_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_dir = root / "project"
            project_dir.mkdir()
            md_path = root / "demo.md"
            md_path.write_text("# Segment 1：0 - 1\n**[音频文案]** Hello world\n", encoding="utf-8")
            output_path = root / "output" / "demo.mp4"
            item = core.ScriptItem(
                model="omni",
                date="2026-07-23",
                product="产品",
                script_dir=str(root),
                md_path=str(md_path),
                video_paths=[str(root / "clip.mp4")],
                output_path=str(output_path),
                status="missing",
                caption_mode="karaoke",
            )

            def render(_project, path, skip_inspect=False):
                path.write_bytes(b"uncaptioned")

            def caption(input_path, final_path, script_path, _project):
                self.assertEqual(input_path, project_dir / "uncaptioned.mp4")
                self.assertEqual(script_path, md_path)
                final_path.parent.mkdir(parents=True)
                final_path.write_bytes(b"captioned")

            with (
                patch.object(core, "prepare_project", return_value=(project_dir, [{"index": 1, "actual_duration": 1.0, "target_duration": 1.0, "duration": 1.0, "action": "target_or_actual"}])),
                patch.object(core, "run_hyperframes", side_effect=render) as renderer,
                patch.object(core, "run_karaoke_captioner", side_effect=caption) as captioner,
            ):
                core.assemble_item(item, skip_existing=False)

        self.assertEqual(renderer.call_args.args[1], project_dir / "uncaptioned.mp4")
        captioner.assert_called_once()

    def test_ui_contract_includes_output_panel_and_modal_sticker_designer(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        ids = re.findall(r'\bid="([^"]+)"', html)

        self.assertEqual(len(ids), len(set(ids)))
        for required in (
            "stickerEnabled",
            "stickerCountry",
            "stickerPreset",
            "stickerPresetTranslation",
            "randomStickerBtn",
            "stickerText",
            "stickerStyleField",
            "stickerPositionField",
            "stickerTimingField",
            "stickerPreviewText",
            "confirmCaptionModeLabel",
            "openOutputBtn",
            "outputs",
        ):
            self.assertIn(required, ids)
            self.assertIn(required, javascript)
        self.assertEqual(set(re.findall(r'name="stickerStyle" value="([^"]+)"', html)), set(core.STICKER_STYLES))
        self.assertEqual(set(re.findall(r'name="captionMode" value="([^"]+)"', html)), set(core.CAPTION_MODES))
        for style in core.STICKER_STYLES:
            preview = re.search(rf"\.stickerPreviewText\.preview-{style} \{{([^}}]+)\}}", css).group(1)
            self.assertNotIn("background:", preview)
            self.assertNotIn("border:", preview)
            self.assertNotIn("box-shadow:", preview)
        self.assertGreater(html.index('id="stickerEnabled"'), html.index('id="confirmModal"'))

    def test_cleanup_keeps_script_marker_and_finished_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "pending"
            output = root / "output"
            script_dir = pending / "omni" / "2026-07-12" / "产品" / "demo"
            script_dir.mkdir(parents=True)
            md_path = script_dir / "demo.md"
            md_path.write_text("# Segment 1：0 - 1", encoding="utf-8")
            source_video = script_dir / "demo-片段1-omni.mp4"
            source_video.write_bytes(b"clip")
            source_image = script_dir / "demo-片段1-人物图.png"
            source_image.write_bytes(b"image")
            source_meta = script_dir / "demo-片段1-人物图.png.product-lock.json"
            source_meta.write_text("{}", encoding="utf-8")
            marker_path = script_dir / "demo.exported.json"
            marker_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provider": "omni",
                        "md_path": str(md_path),
                        "export_dir": str(script_dir),
                        "upload_status": "未记录",
                        "media_cleaned": False,
                        "media_files": [
                            {"name": source_video.name, "path": str(source_video), "type": "video", "cleaned": False},
                            {"name": source_image.name, "path": str(source_image), "type": "image", "cleaned": False},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_dir = output / "产品"
            output_dir.mkdir(parents=True)
            finished = output_dir / "demo.mp4"
            finished.write_bytes(b"finished")

            item = core.scan_items(pending, output)[0]
            self.assertTrue(item.cleanup_eligible)
            self.assertEqual(item.cleanup_file_count, 3)
            with patch.object(core, "verify_finished_output", return_value={"duration": 1.0, "has_video": True, "has_audio": True}):
                result = core.cleanup_items([item])

            self.assertEqual(result["deleted_count"], 3)
            self.assertFalse(source_video.exists())
            self.assertFalse(source_image.exists())
            self.assertFalse(source_meta.exists())
            self.assertTrue(md_path.exists())
            self.assertTrue(marker_path.exists())
            self.assertTrue(finished.exists())
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(marker["upload_status"], "已清理")
            self.assertTrue(marker["media_cleaned"])

            rescanned = core.scan_items(pending, output)[0]
            self.assertEqual(rescanned.status, "done")
            self.assertTrue(rescanned.media_cleaned)
            self.assertFalse(rescanned.cleanup_eligible)

    def test_cleanup_validates_every_output_before_deleting_any_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "pending"
            output = root / "output"
            product = pending / "omni" / "2026-07-12" / "产品"
            output_product = output / "产品"
            output_product.mkdir(parents=True)
            sources = []
            for name in ("one", "two"):
                script_dir = product / name
                script_dir.mkdir(parents=True)
                (script_dir / f"{name}.md").write_text("# Segment 1：0 - 1", encoding="utf-8")
                source = script_dir / f"{name}-片段1.mp4"
                source.write_bytes(b"clip")
                sources.append(source)
                (output_product / f"{name}.mp4").write_bytes(b"finished")

            items = core.scan_items(pending, output)
            with patch.object(
                core,
                "verify_finished_output",
                side_effect=[{"duration": 1.0, "has_video": True, "has_audio": True}, RuntimeError("第二个成品无效")],
            ):
                with self.assertRaisesRegex(RuntimeError, "第二个成品无效"):
                    core.cleanup_items(items)

            self.assertTrue(all(path.exists() for path in sources))


if __name__ == "__main__":
    unittest.main()
