from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.server import delete_hook_videos, plan_hook_paths, safe_hook_video_path
from app.mixer import (
    DEDUPLICATION_OPTIONS,
    MAX_REAL_FOOTAGE_USES,
    MixerPaths,
    audio_subtitle_paths,
    build_plan,
    build_hyperframes_html,
    caption_language,
    choose_middle_timeline,
    deduplication_filter,
    ensure_audio_subtitles,
    middle_route_signature,
    probe_media,
    random_deduplication_options,
    render_video_segment,
    render_plan,
    scan_library,
    shift_ass_subtitles,
    update_delivery_marker,
)


class MixerTests(unittest.TestCase):
    def paths(self, root: Path) -> MixerPaths:
        return MixerPaths(
            vault_root=root,
            audio_root=root / "06音频文件",
            real_root=root / "07实拍素材",
            work_root=root / "08混剪工作区",
            output_root=root / "成品视频",
        )

    def archived_clip(
        self,
        paths: MixerPaths,
        script_type: str,
        name: str,
        *,
        product: str = "测试产品",
        model: str = "omni",
    ) -> Path:
        path = (
            paths.work_root
            / "片段产出归档"
            / model
            / "2026-07-30"
            / script_type
            / product
            / "来源A"
            / Path(name).stem
            / name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        path.with_suffix(path.suffix + ".delivery.json").write_text(
            json.dumps(
                {
                    "model": model,
                    "script_type": script_type,
                    "product_name": product,
                    "video_path": str(path),
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_scan_preserves_model_type_and_product_hierarchy(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            files = [
                self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4"),
                self.archived_clip(paths, "混剪-CTA", "cta-IE.mp4"),
                paths.audio_root / "测试产品/AI音频-IE-test.mp3",
                paths.real_root / "测试产品/展示/display.mp4",
                paths.real_root / "测试产品/使用/use.mp4",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            library = scan_library(paths)

        product = library["products"][0]
        self.assertEqual(product["name"], "测试产品")
        self.assertEqual(list(product["models"]), ["omni"])
        self.assertTrue(product["ready"])
        self.assertEqual(product["markets"]["IE"]["label"], "IE · 爱尔兰")
        self.assertEqual(product["markets"]["IE"]["models"]["omni"]["hooks"][0]["name"], "hook-IE.mp4")

    def test_scan_ignores_unexported_ai_clips(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = Path(temp) / "05AI片段/omni/混剪-钩子/测试产品/hook-IE.mp4"
            hook.parent.mkdir(parents=True)
            hook.touch()

            library = scan_library(paths)

        self.assertEqual(library["summary"]["hooks"], 0)

    def test_scan_includes_delivered_archive_videos(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            archived_hook = (
                paths.work_root
                / "片段产出归档/omni/2026-07-30/混剪-钩子/测试产品/来源A/hook/hook-IE.mp4"
            )
            sidecar = archived_hook.with_suffix(".mp4.delivery.json")
            files = [
                archived_hook,
                paths.audio_root / "测试产品/AI音频-IE-test.mp3",
                paths.real_root / "测试产品/展示/display.mp4",
                paths.real_root / "测试产品/使用/use.mp4",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            sidecar.write_text(
                json.dumps(
                    {
                        "model": "omni",
                        "script_type": "混剪-钩子",
                        "product_name": "测试产品",
                        "video_path": str(archived_hook),
                    }
                ),
                encoding="utf-8",
            )

            library = scan_library(paths)

        product = library["products"][0]
        hook = product["markets"]["IE"]["models"]["omni"]["hooks"][0]
        self.assertEqual(hook["path"], str(archived_hook.resolve()))
        self.assertTrue(product["ready"])

    def test_hook_preview_media_is_limited_to_delivery_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = Path(temp) / "05AI片段/omni/混剪-钩子/测试产品/hook-IE.mp4"
            archived = self.archived_clip(paths, "混剪-钩子", "hook2-IE.mp4")
            cta = self.archived_clip(paths, "混剪-CTA", "cta-IE.mp4")
            outside = Path(temp) / "outside.mp4"
            for path in (hook, archived, cta, outside):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            self.assertEqual(safe_hook_video_path(str(archived), paths), archived.resolve())
            with self.assertRaisesRegex(ValueError, "不在片段产出归档目录"):
                safe_hook_video_path(str(hook), paths)
            with self.assertRaisesRegex(ValueError, "混剪钩子目录"):
                safe_hook_video_path(str(cta), paths)
            with self.assertRaisesRegex(ValueError, "不在片段产出归档目录"):
                safe_hook_video_path(str(outside), paths)

    def test_delete_hook_videos_removes_video_and_product_lock_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4")
            sidecar = hook.with_suffix(".mp4.product-lock.json")
            sidecar.write_text("{}", encoding="utf-8")

            result = delete_hook_videos([str(hook)], paths)

        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["sidecars_deleted"], 1)
        self.assertFalse(hook.exists())
        self.assertFalse(sidecar.exists())

    def test_delivery_marker_tracks_use_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hook = root / "05AI片段/omni/混剪-钩子/测试产品/hook-IE.mp4"
            marker = root / "04适配脚本/omni/混剪-钩子/测试产品/hook.exported.json"
            delivery_sidecar = hook.with_suffix(".mp4.delivery.json")
            for path in (hook, marker, delivery_sidecar):
                path.parent.mkdir(parents=True, exist_ok=True)
            hook.write_bytes(b"video")
            marker.write_text(
                json.dumps(
                    {
                        "upload_status": "已交付",
                        "media_cleaned": False,
                        "media_files": [{"path": str(hook), "cleaned": False}],
                    }
                ),
                encoding="utf-8",
            )
            delivery_sidecar.write_text(
                json.dumps({"marker_path": str(marker), "video_path": str(hook)}),
                encoding="utf-8",
            )

            self.assertTrue(update_delivery_marker(hook, used_output=root / "成品.mp4"))
            used = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(used["upload_status"], "已用于混剪")
            self.assertEqual(used["used_outputs"], [str(root / "成品.mp4")])

            hook.unlink()
            self.assertTrue(update_delivery_marker(hook, cleaned=True))
            cleaned = json.loads(marker.read_text(encoding="utf-8"))
            self.assertTrue(cleaned["media_cleaned"])
            self.assertTrue(cleaned["media_files"][0]["cleaned"])

    def test_delete_hook_updates_delivery_marker_and_removes_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4")
            marker = Path(temp) / "scripts/hook.exported.json"
            delivery_sidecar = hook.with_suffix(".mp4.delivery.json")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "media_cleaned": False,
                        "media_files": [{"path": str(hook), "cleaned": False}],
                    }
                ),
                encoding="utf-8",
            )
            delivery_sidecar.write_text(
                json.dumps({"marker_path": str(marker), "video_path": str(hook)}),
                encoding="utf-8",
            )

            result = delete_hook_videos([str(hook)], paths)

            self.assertEqual(result["delivery_markers_updated"], 1)
            self.assertFalse(delivery_sidecar.exists())
            self.assertTrue(json.loads(marker.read_text(encoding="utf-8"))["media_cleaned"])

    def test_plan_hook_paths_only_returns_ai_hook_segments(self):
        plan = {
            "variants": [
                {
                    "segments": [
                        {"role": "AI钩子", "path": "/hooks/a.mp4"},
                        {"role": "展示", "path": "/display/a.mp4"},
                    ]
                },
                {
                    "segments": [
                        {"role": "AI钩子", "path": "/hooks/b.mp4"},
                        {"role": "AI CTA", "path": "/ctas/a.mp4"},
                    ]
                },
            ]
        }

        self.assertEqual(plan_hook_paths(plan), ["/hooks/a.mp4", "/hooks/b.mp4"])

    def test_scan_is_ready_without_cta(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            files = [
                self.archived_clip(paths, "混剪-钩子", "hook-ES.mp4"),
                paths.audio_root / "测试产品/AI音频-ES-test.mp3",
                paths.real_root / "测试产品/展示/display.mp4",
                paths.real_root / "测试产品/使用/use.mp4",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            product = scan_library(paths)["products"][0]

        self.assertTrue(product["ready"])
        self.assertEqual(product["markets"]["ES"]["models"]["omni"]["ctas"], [])

    def test_scan_marks_rendered_hook_as_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4")
            files = [
                hook,
                paths.audio_root / "测试产品/AI音频-IE-test.mp3",
                paths.real_root / "测试产品/展示/display.mp4",
                paths.real_root / "测试产品/使用/use.mp4",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            paths.work_root.mkdir(parents=True, exist_ok=True)
            (paths.work_root / "usage_history.json").write_text(
                json.dumps({"sources": {str(hook.resolve()): 1}}),
                encoding="utf-8",
            )

            library = scan_library(paths)

        product = library["products"][0]
        self.assertFalse(product["ready"])
        self.assertEqual(library["summary"]["available_hooks"], 0)
        self.assertEqual(product["markets"]["IE"]["models"]["omni"]["hooks"][0]["used_count"], 1)

    def test_build_plan_omits_optional_cta(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4")
            hook2 = self.archived_clip(paths, "混剪-钩子", "hook2-IE.mp4")
            cta = self.archived_clip(paths, "混剪-CTA", "cta-IE.mp4")
            cta2 = self.archived_clip(paths, "混剪-CTA", "cta2-IE.mp4")
            audio = paths.audio_root / "测试产品/AI音频-IE-test.mp3"
            audio2 = paths.audio_root / "测试产品/AI音频-IE-test2.mp3"
            display = paths.real_root / "测试产品/展示/display.mp4"
            usage = paths.real_root / "测试产品/使用/use.mp4"
            for path in (hook, hook2, cta, cta2, audio, audio2, display, usage):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            def fake_pool(records):
                return [
                    {
                        **records[0],
                        "path": f"{records[0]['path']}-{index}",
                        "name": f"{records[0]['name']}-{index}",
                        "duration": 2.0,
                        "has_video": True,
                    }
                    for index in range(4)
                ]

            with (
                patch(
                    "app.mixer.effective_video_record",
                    return_value={
                        "path": str(hook),
                        "name": hook.name,
                        "duration": 3.0,
                        "effective_duration": 3.0,
                        "technical_tail_trimmed": False,
                    },
                ),
                patch(
                    "app.mixer.probe_media",
                    return_value={
                        "path": str(audio),
                        "name": audio.name,
                        "duration": 6.0,
                        "has_video": False,
                        "has_audio": True,
                    },
                ),
                patch("app.mixer.media_pool", side_effect=fake_pool),
                patch("app.mixer.caption_runtime_ready", return_value=True),
            ):
                plan = build_plan(
                    {
                        "product": "测试产品",
                        "market": "IE",
                        "model": "omni",
                        "include_cta": False,
                        "count": 2,
                        "deduplication_options": ["mirror", "encoding"],
                        "seed": 123,
                    },
                    paths,
                )
                plan_with_cta = build_plan(
                    {
                        "product": "测试产品",
                        "market": "IE",
                        "model": "omni",
                        "include_cta": True,
                        "use_subtitles": True,
                        "count": 2,
                        "random_deduplication": True,
                        "seed": 456,
                    },
                    paths,
                )

        variant = plan["variants"][0]
        self.assertEqual(plan["inputs"]["hook_count"], 2)
        self.assertEqual(
            Path(plan["plan_path"]).parent,
            paths.work_root / "测试产品" / "plans",
        )
        self.assertEqual(
            Path(plan_with_cta["plan_path"]).parent,
            paths.work_root / "测试产品" / "plans",
        )
        self.assertEqual(
            len({item["segments"][0]["path"] for item in plan["variants"]}),
            2,
        )
        self.assertEqual(plan["inputs"]["audio_count"], 2)
        self.assertEqual(len({item["middle_audio"] for item in plan["variants"]}), 2)
        self.assertEqual(plan["inputs"]["cta_count"], 2)
        self.assertFalse(plan["inputs"]["include_cta"])
        self.assertEqual(plan["settings"]["deduplication_options"], ["mirror", "encoding"])
        self.assertFalse(plan["settings"]["audio_deduplication"])
        self.assertEqual(variant["deduplication_options"], ["mirror", "encoding"])
        self.assertEqual(variant["total_duration"], 9.0)
        self.assertNotIn("AI CTA", [segment["role"] for segment in variant["segments"]])
        cta_variant = plan_with_cta["variants"][0]
        self.assertTrue(plan_with_cta["inputs"]["include_cta"])
        self.assertFalse(plan["settings"]["use_subtitles"])
        self.assertTrue(plan_with_cta["settings"]["use_subtitles"])
        self.assertTrue(plan_with_cta["settings"]["random_deduplication"])
        self.assertGreaterEqual(len(cta_variant["deduplication_options"]), 3)
        self.assertEqual(
            len({item["segments"][-1]["path"] for item in plan_with_cta["variants"]}),
            2,
        )
        self.assertEqual(cta_variant["total_duration"], 12.0)
        self.assertEqual(cta_variant["segments"][-1]["role"], "AI CTA")

    def test_build_plan_does_not_cross_country_for_audio_pool(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            hook = self.archived_clip(paths, "混剪-钩子", "hook-IE.mp4")
            audio = paths.audio_root / "测试产品/AI音频-ES-test.mp3"
            for path in (hook, audio):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            with self.assertRaisesRegex(ValueError, "没有可用的混剪音频"):
                build_plan(
                    {
                        "product": "测试产品",
                        "market": "IE",
                        "model": "omni",
                    },
                    paths,
                )

    def test_middle_timeline_places_display_before_usage(self):
        display = [{"path": f"/d/{i}.mp4", "name": f"d{i}", "duration": 5.0} for i in range(3)]
        usage = [{"path": f"/u/{i}.mp4", "name": f"u{i}", "duration": 5.0} for i in range(3)]

        timeline = choose_middle_timeline(
            display, usage, 9.7, seed=42,
            history={"sources": {}},
        )

        self.assertAlmostEqual(sum(item["duration"] for item in timeline), 9.7, places=2)
        roles = [item["role"] for item in timeline]
        first_usage = roles.index("使用")
        self.assertTrue(all(role == "展示" for role in roles[:first_usage]))
        self.assertTrue(all(role == "使用" for role in roles[first_usage:]))
        display_ratio = sum(item["duration"] for item in timeline if item["role"] == "展示") / 9.7
        self.assertGreaterEqual(display_ratio, 0.44)
        self.assertLessEqual(display_ratio, 0.56)
        self.assertTrue(all(item["duration"] > 0 for item in timeline))

    def test_middle_timeline_uses_source_duration_for_display_boundary(self):
        display = [{"path": f"/d/{i}.mp4", "name": f"d{i}", "duration": 1.8} for i in range(3)]
        usage = [{"path": f"/u/{i}.mp4", "name": f"u{i}", "duration": 5.0} for i in range(3)]

        timeline = choose_middle_timeline(
            display, usage, 10.0, seed=7,
            history={"sources": {}},
        )

        display_segments = [item for item in timeline if item["role"] == "展示"]
        self.assertTrue(all(item["duration"] <= 1.8 for item in display_segments))
        self.assertAlmostEqual(sum(item["duration"] for item in display_segments), 5.4, places=2)
        self.assertEqual(timeline[len(display_segments)]["role"], "使用")

    def test_middle_timeline_trims_last_clip_to_remaining_duration(self):
        display = [{"path": "/d/1.mp4", "name": "display", "duration": 3.0}]
        usage = [{"path": "/u/1.mp4", "name": "usage", "duration": 4.0}]

        timeline = choose_middle_timeline(
            display, usage, 5.0, seed=5,
            history={"sources": {}},
        )

        self.assertEqual(timeline[-1]["role"], "使用")
        self.assertAlmostEqual(timeline[-1]["duration"], 2.0, places=2)
        self.assertAlmostEqual(sum(item["duration"] for item in timeline), 5.0, places=2)

    def test_middle_timeline_excludes_footage_at_usage_limit(self):
        display = [
            {"path": "/d/exhausted.mp4", "name": "exhausted", "duration": 2.0},
            {"path": "/d/available.mp4", "name": "available", "duration": 2.0},
        ]
        usage = [{"path": "/u/available.mp4", "name": "usage", "duration": 2.0}]

        timeline = choose_middle_timeline(
            display, usage, 4.0, seed=11,
            history={"sources": {"/d/exhausted.mp4": MAX_REAL_FOOTAGE_USES}},
        )

        self.assertNotIn("/d/exhausted.mp4", [item["path"] for item in timeline])
        self.assertEqual(timeline[0]["path"], "/d/available.mp4")

    def test_middle_route_signature_uses_audio_and_real_sequence(self):
        segments = [
            {"role": "展示", "path": "/d/1.mp4", "start": 0.0, "duration": 2.0},
            {"role": "使用", "path": "/u/1.mp4", "start": 0.0, "duration": 2.0},
        ]

        first = middle_route_signature("/audio/a.m4a", segments)
        same_order = middle_route_signature(
            "/audio/a.m4a",
            [{**item, "start": 1.0, "duration": 1.0} for item in segments],
        )
        different_audio = middle_route_signature("/audio/b.m4a", segments)

        self.assertEqual(first, same_order)
        self.assertNotEqual(first, different_audio)

    def test_deduplication_filter_combines_selected_video_only_processing(self):
        filter_text = deduplication_filter(
            123,
            [
                "transform", "color", "tone", "detail", "frame_drop", "mirror",
                "speed", "border", "effect",
            ],
            duration=3.0,
        )
        self.assertIn("crop=1080:1920", filter_text)
        self.assertIn("eq=saturation=", filter_text)
        self.assertIn("colorbalance=", filter_text)
        self.assertIn("hqdn3d=", filter_text)
        self.assertIn("select=", filter_text)
        self.assertNotIn("setpts=N/(", filter_text)
        self.assertIn("hflip", filter_text)
        self.assertIn("setpts=PTS/", filter_text)
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.5", filter_text)
        self.assertIn("fps=30,trim=end_frame=90", filter_text)
        self.assertLess(
            filter_text.index("tpad=stop_mode=clone:stop_duration=0.5"),
            filter_text.index("setpts=PTS/"),
        )
        self.assertIn("drawbox=", filter_text)
        self.assertNotIn("drawtext=", filter_text)
        self.assertNotIn("enable='lt(mod(t", filter_text)
        self.assertNotIn("atempo", filter_text)
        self.assertNotIn("volume", filter_text)

    def test_probe_media_prefers_video_stream_duration_over_longer_audio(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "format": {"duration": "10.0"},
                    "streams": [
                        {
                            "codec_type": "video",
                            "duration": "8.0",
                            "width": 1080,
                            "height": 1920,
                        },
                        {"codec_type": "audio", "duration": "10.0"},
                    ],
                }
            ),
            stderr="",
        )

        with patch("app.mixer.run", return_value=completed):
            record = probe_media(Path("/tmp/test.mp4"))

        self.assertEqual(record["duration"], 8.0)

    def test_render_video_segment_writes_constant_frame_rate_duration(self):
        segment = {
            "path": "/tmp/source.mp4",
            "start": 0.0,
            "duration": 10.0,
        }

        with patch("app.mixer.run") as run_mock:
            render_video_segment(segment, Path("/tmp/output.mp4"), 123, ["frame_drop"])

        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index("-r") + 1], "30")
        self.assertEqual(command[command.index("-fps_mode") + 1], "cfr")

    def test_random_deduplication_uses_known_options_and_multiple_items(self):
        selected = random_deduplication_options(123)

        self.assertGreaterEqual(len(selected), 3)
        self.assertTrue(set(selected).issubset(DEDUPLICATION_OPTIONS))
        self.assertNotIn("watermark", DEDUPLICATION_OPTIONS)
        self.assertNotIn("flash", DEDUPLICATION_OPTIONS)

    def test_country_languages_match_assembly_agent(self):
        self.assertEqual(caption_language("ES"), "es")
        self.assertEqual(caption_language("IE"), "en")
        self.assertEqual(caption_language("IT"), "it")

    def test_scan_reports_local_audio_subtitle_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.paths(Path(temporary))
            audio_ready = paths.audio_root / "测试产品/AI音频-ES-ready.m4a"
            audio_missing = paths.audio_root / "测试产品/AI音频-ES-missing.m4a"
            for audio in (audio_ready, audio_missing):
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.touch()
            audio_ready.with_suffix(".ass").write_text(
                "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,HOLA\n",
                encoding="utf-8",
            )

            market = scan_library(paths)["products"][0]["markets"]["ES"]

        self.assertEqual(market["subtitle_count"], 1)
        self.assertEqual(market["missing_subtitle_count"], 1)
        subtitle_status = {item["name"]: item["subtitle_ready"] for item in market["audio"]}
        self.assertTrue(subtitle_status["AI音频-ES-ready.m4a"])
        self.assertFalse(subtitle_status["AI音频-ES-missing.m4a"])

    def test_audio_subtitles_reuse_valid_sidecar_without_whisper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "AI音频-IT-demo.m4a"
            audio.touch()
            paths = audio_subtitle_paths(audio)
            paths["ass"].write_text(
                "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,CIAO\n",
                encoding="utf-8",
            )
            with patch("app.mixer.run") as run_mock:
                result = ensure_audio_subtitles(audio, 5.0, "IT", root / "work")

        self.assertEqual(result["ass"], paths["ass"])
        run_mock.assert_not_called()

    def test_audio_subtitles_generate_local_sidecars_with_market_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "AI音频-IT-demo.m4a"
            audio.write_bytes(b"audio")
            captured = {}

            def command_runner(command, cwd=None, env=None, timeout=3600):
                if str(command[0]).endswith("caption.py"):
                    raise AssertionError("caption.py should be invoked through Python")
                if "--caption-mode" not in command:
                    Path(command[-1]).parent.mkdir(parents=True, exist_ok=True)
                    Path(command[-1]).write_bytes(b"video")
                    return subprocess.CompletedProcess(command, 0, "", "")
                captured["command"] = command
                captured["env"] = env
                out_dir = Path(command[command.index("--out-dir") + 1])
                stem = Path(command[2]).stem
                (out_dir / f"{stem}.ass").write_text(
                    "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,TEST\n",
                    encoding="utf-8",
                )
                (out_dir / f"{stem}.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nTEST\n", encoding="utf-8")
                (out_dir / f"{stem}-whisper.json").write_text('{"segments":[]}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch("app.mixer.caption_runtime_ready", return_value=True),
                patch("app.mixer.run", side_effect=command_runner),
                patch("app.mixer.ffmpeg_path", return_value="/usr/bin/ffmpeg"),
            ):
                result = ensure_audio_subtitles(audio, 5.0, "IT", root / "work")
            generated_files = {key: path.is_file() for key, path in result.items()}

        command = captured["command"]
        self.assertEqual(command[command.index("--language") + 1], "it")
        self.assertIn("--prefer-local", command)
        self.assertIn("--srt-only", command)
        self.assertNotIn("--script-file", command)
        self.assertEqual(captured["env"]["UV_OFFLINE"], "1")
        self.assertNotIn("DEEPGRAM_API_KEY", captured["env"])
        self.assertTrue(generated_files["ass"])
        self.assertTrue(generated_files["srt"])
        self.assertTrue(generated_files["caption_json"])

    def test_shifted_subtitles_start_after_hook_and_stop_before_cta(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "audio.ass"
            output = root / "shifted.ass"
            source.write_text(
                "[Events]\n"
                "Dialogue: 0,0:00:00.25,0:00:01.50,Default,,0,0,0,,UNO\n"
                "Dialogue: 0,0:00:02.50,0:00:04.00,Default,,0,0,0,,DOS\n",
                encoding="utf-8",
            )

            shift_ass_subtitles(source, output, offset=7.5, duration=3.0)
            text = output.read_text(encoding="utf-8")

        self.assertIn("0:00:07.75,0:00:09.00", text)
        self.assertIn("0:00:10.00,0:00:10.50", text)
        self.assertNotIn("0:00:11.50", text)

    def test_render_plan_captions_only_middle_audio_with_hook_offset(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.paths(Path(temporary))
            middle_audio = Path(temporary) / "audio.m4a"
            middle_audio.touch()
            plan = {
                "plan_id": "caption-test",
                "product": "测试产品",
                "market": "ES",
                "model": "omni",
                "settings": {
                    "use_subtitles": True,
                    "deduplication_options": ["color"],
                },
                "variants": [
                    {
                        "index": 1,
                        "seed": 123,
                        "segments": [
                            {
                                "role": "AI钩子",
                                "path": str(Path(temporary) / "hook.mp4"),
                                "duration": 1.0,
                            }
                        ],
                        "middle_audio": str(middle_audio),
                        "middle_duration": 2.0,
                        "total_duration": 3.0,
                        "route_signature": "route",
                    }
                ],
            }
            rendered = []
            generated = []
            shifted = []
            burned = []

            def hyperframes(_project, output):
                rendered.append(output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"uncaptioned")

            def subtitles(audio_path, duration, market, _project):
                generated.append((audio_path, duration, market))
                ass = Path(temporary) / "audio.ass"
                ass.write_text(
                    "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,TEST\n",
                    encoding="utf-8",
                )
                return {"ass": ass}

            def shift(source, output, *, offset, duration):
                shifted.append((source, output, offset, duration))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("Dialogue:", encoding="utf-8")

            def burn(input_path, _subtitle_path, output_path):
                burned.append((input_path, output_path))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"captioned")

            with (
                patch("app.mixer.render_video_segment"),
                patch("app.mixer.concat_video"),
                patch("app.mixer.render_audio_piece"),
                patch("app.mixer.concat_audio"),
                patch("app.mixer.prepare_hyperframes_project"),
                patch("app.mixer.run_hyperframes", side_effect=hyperframes),
                patch("app.mixer.valid_ass_subtitles", return_value=False),
                patch("app.mixer.ensure_audio_subtitles", side_effect=subtitles),
                patch("app.mixer.shift_ass_subtitles", side_effect=shift),
                patch("app.mixer.burn_ass_subtitles", side_effect=burn),
                patch(
                    "app.mixer.validate_finished_video",
                    return_value={"duration": 3.0, "has_video": True, "has_audio": True},
                ),
                patch("app.mixer.update_usage_history"),
            ):
                outputs = render_plan(plan, paths=paths)

        self.assertEqual(rendered[0].name, "uncaptioned.mp4")
        self.assertEqual(generated, [(middle_audio, 2.0, "ES")])
        self.assertEqual(shifted[0][2:], (1.0, 2.0))
        self.assertEqual(burned[0][0], rendered[0])
        self.assertEqual(len(outputs), 1)

    def test_ui_exposes_single_subtitle_checkbox_and_match_summary(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
        styles = (root / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="useSubtitles" type="checkbox"', html)
        self.assertNotIn('name="captionMode"', html)
        self.assertIn('id="subtitleSummary"', html)
        self.assertNotIn('value="watermark"', html)
        self.assertNotIn('value="flash"', html)
        self.assertIn("use_subtitles: els.useSubtitles.checked", javascript)
        self.assertIn("market.subtitle_count", javascript)
        self.assertIn("market.missing_subtitle_count", javascript)
        self.assertIn("<h2>钩子素材预览</h2>", html)
        self.assertNotIn("<h2>方案预览</h2>", html)
        self.assertIn('id="hookPreview"', html)
        self.assertIn('<aside class="status-column">', html)
        self.assertIn(
            "grid-template-columns: minmax(260px, 0.75fr) minmax(360px, 2.9fr) minmax(280px, 1fr);",
            styles,
        )
        self.assertIn("/api/hook-video?path=", javascript)
        self.assertIn('id="selectAllHooksButton"', html)
        self.assertIn('id="deleteSelectedHooksButton"', html)
        self.assertIn('id="hookPager"', html)
        self.assertIn("const HOOK_PAGE_SIZE = 10;", javascript)
        self.assertIn("/api/hook-video/delete", javascript)
        self.assertIn("function deleteSelectedHooks()", javascript)
        self.assertIn("reservedHookPaths: new Set()", javascript)
        self.assertIn('"任务占用"', javascript)
        self.assertIn("task.reserved_hook_paths", javascript)
        self.assertIn("当前渲染任务运行中", javascript)
        self.assertIn("function renderHookPreview()", javascript)
        self.assertNotIn("function renderPlan(", javascript)
        self.assertIn("color-scheme: light", styles)
        self.assertIn("--bg: #f6f3ea", styles)
        self.assertNotIn("color-scheme: dark", styles)
        self.assertNotRegex(html + javascript, r"(?i)sticker|文字贴纸")

    def test_hyperframes_composition_keeps_visual_muted_and_audio_separate(self):
        html = build_hyperframes_html(15.0)
        self.assertIn('data-composition-id="main"', html)
        self.assertIn('window.__timelines["main"]', html)
        self.assertIn("gsap.timeline({ paused: true })", html)
        self.assertIn('id="visual-track" class="clip"', html)
        self.assertIn('src="media/visual.mp4"', html)
        self.assertIn("muted playsinline", html)
        self.assertIn('id="audio-track" class="clip"', html)
        self.assertIn('src="media/audio.m4a"', html)
        self.assertNotIn("wash-", html)


if __name__ == "__main__":
    unittest.main()
