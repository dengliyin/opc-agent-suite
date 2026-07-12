from __future__ import annotations

import json
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
            done_output = output / "omni" / "2026-07-11" / "产品"
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
            output_dir = output / "omni" / "2026-07-12" / "产品"
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
            output_product = output / "omni" / "2026-07-12" / "产品"
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
