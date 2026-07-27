from __future__ import annotations

import importlib.util
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

    def test_caption_mode_language_and_no_speech_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            md_path = Path(temporary) / "omni-裂变-产品-FR-demo.md"
            md_path.write_text(
                "# Segment 1：0 - 1\n**[音频文案]** (Voiceover, French): Bonjour\n"
                "**[音频文案]**：tout le monde\n"
                "# Segment 2：1 - 2\n**[音频文案]** （French）：à bientôt\n",
                encoding="utf-8",
            )
            language = core.caption_language(md_path)
            silent_path = Path(temporary) / "omni-裂变-产品-IT-demo.md"
            silent_path.write_text(
                "# Segment 1：0 - 1\n"
                "**[音频文案]**：无人物口播、无旁白、无对白、无歌词。仅保留环境声。\n"
                "# Segment 2：1 - 2\n"
                "**[音频文案]**：无口播、无旁白、无对白。仅保留背景音乐。\n",
                encoding="utf-8",
            )
            has_speech = core.caption_has_no_speech(md_path)
            has_no_speech = core.caption_has_no_speech(silent_path)

        self.assertEqual(core.normalize_caption_mode(None), "none")
        self.assertEqual(core.normalize_caption_mode("karaoke"), "karaoke")
        with self.assertRaisesRegex(ValueError, "字幕模式"):
            core.normalize_caption_mode("classic")
        self.assertEqual(language, "fr")
        self.assertFalse(has_speech)
        self.assertTrue(has_no_speech)

    def test_karaoke_skips_whisper_when_script_has_no_speech(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "uncaptioned.mp4"
            input_path.write_bytes(b"video")
            output_path = root / "output" / "final.mp4"
            md_path = root / "omni-裂变-产品-IT-demo.md"
            md_path.write_text(
                "**[音频文案]**：无人物口播、无旁白、无对白、无歌词。仅保留环境声。\n",
                encoding="utf-8",
            )
            with (
                patch.object(core, "caption_runtime_ready", return_value=False),
                patch.object(core, "run") as runner,
                patch.object(core, "verify_finished_output"),
            ):
                core.run_karaoke_captioner(input_path, output_path, md_path, root)
            output_bytes = output_path.read_bytes()

        runner.assert_not_called()
        self.assertEqual(output_bytes, b"video")

    def test_karaoke_uses_country_language_and_raw_whisper_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "uncaptioned.mp4"
            input_path.write_bytes(b"video")
            output_path = root / "output" / "final.mp4"
            md_path = root / "omni-裂变-产品-IT-demo.md"
            md_path.write_text(
                "**[音频文案]**：Questa è una vera voce italiana.\n",
                encoding="utf-8",
            )
            captured = {}

            def caption(command, cwd=None, env=None):
                captured["command"] = command
                captioned = root / "captions" / output_path.name
                captioned.parent.mkdir(exist_ok=True)
                captioned.write_bytes(b"captioned")
                return core.subprocess.CompletedProcess(command, 0, "")

            with (
                patch.object(core, "caption_runtime_ready", return_value=True),
                patch.object(core, "runtime_env", return_value={}),
                patch.object(core, "run", side_effect=caption),
                patch.object(core, "verify_finished_output"),
            ):
                core.run_karaoke_captioner(input_path, output_path, md_path, root)
            output_bytes = output_path.read_bytes()

        self.assertEqual(captured["command"][captured["command"].index("--language") + 1], "it")
        self.assertNotIn("--script-file", captured["command"])
        self.assertEqual(output_bytes, b"captioned")

    def test_karaoke_style_matches_reference_size_and_position(self) -> None:
        caption_path = ROOT / "vendor" / "tiktok-karaoke-captions" / "caption.py"
        spec = importlib.util.spec_from_file_location("karaoke_caption", caption_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            ass_path = Path(temporary) / "caption.ass"
            module.write_ass_tiktok(
                [[{"text": "three", "start": 0.0, "end": 0.4}]],
                ass_path,
                1080,
                1920,
            )
            ass = ass_path.read_text(encoding="utf-8")

        self.assertIn("Style: Default,Roboto Black,76,", ass)
        self.assertIn("1,4,1,5,40,40,0,1", ass)
        self.assertIn(r"{\an5\pos(540,1113)}", ass)

    def test_confirmation_persists_caption_mode_in_latest_scan(self) -> None:
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
                    caption_mode="karaoke",
                )
            persisted = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(selected[0]["caption_mode"], "karaoke")
        self.assertEqual(confirmed["items"][0]["caption_mode"], "karaoke")
        self.assertEqual(persisted["items"][0]["caption_mode"], "karaoke")
        self.assertNotIn("caption_mode", persisted["items"][1])

    def test_scan_preserves_saved_caption_mode(self) -> None:
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

    def test_ui_contract_includes_caption_modes_without_text_stickers(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        ids = re.findall(r'\bid="([^"]+)"', html)

        self.assertEqual(len(ids), len(set(ids)))
        for required in (
            "confirmCaptionModeLabel",
            "openOutputBtn",
            "outputs",
        ):
            self.assertIn(required, ids)
            self.assertIn(required, javascript)
        self.assertEqual(set(re.findall(r'name="captionMode" value="([^"]+)"', html)), set(core.CAPTION_MODES))
        self.assertNotRegex(html + javascript + css, r"(?i)sticker|文字贴纸")

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
