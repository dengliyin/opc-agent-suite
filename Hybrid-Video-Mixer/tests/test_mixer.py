from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.mixer import (
    MixerPaths,
    build_hyperframes_html,
    choose_middle_timeline,
    originality_filter,
    scan_library,
)


class MixerTests(unittest.TestCase):
    def paths(self, root: Path) -> MixerPaths:
        return MixerPaths(
            vault_root=root,
            ai_clip_root=root / "05AI片段",
            audio_root=root / "06产品介绍音频",
            real_root=root / "07实拍素材",
            work_root=root / "08混剪工作区",
            output_root=root / "成品视频",
        )

    def test_scan_preserves_model_type_and_product_hierarchy(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.paths(Path(temp))
            files = [
                paths.ai_clip_root / "omni/混剪-钩子/测试产品/hook.mp4",
                paths.ai_clip_root / "omni/混剪-CTA/测试产品/cta.mp4",
                paths.audio_root / "测试产品/audio.mp3",
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
        self.assertEqual(product["models"]["omni"]["hooks"][0]["name"], "hook.mp4")

    def test_middle_timeline_matches_audio_and_alternates_categories(self):
        display = [{"path": f"/d/{i}.mp4", "name": f"d{i}", "duration": 5.0} for i in range(3)]
        usage = [{"path": f"/u/{i}.mp4", "name": f"u{i}", "duration": 5.0} for i in range(3)]

        timeline = choose_middle_timeline(
            display, usage, 9.7, seed=42, min_clip=1.6, max_clip=3.2,
            originality="enhanced", history={"sources": {}},
        )

        self.assertAlmostEqual(sum(item["duration"] for item in timeline), 9.7, places=2)
        self.assertTrue(all(a["role"] != b["role"] for a, b in zip(timeline, timeline[1:])))
        self.assertTrue(all(item["duration"] > 0 for item in timeline))

    def test_originality_filter_is_gentle_crop_and_color_processing(self):
        filter_text = originality_filter(123, "enhanced")
        self.assertIn("crop=1080:1920", filter_text)
        self.assertIn("eq=saturation=", filter_text)
        self.assertNotIn("hflip", filter_text)

    def test_hyperframes_composition_keeps_visual_muted_and_audio_separate(self):
        html = build_hyperframes_html(15.0, [3.0, 12.0])
        self.assertIn('data-composition-id="main"', html)
        self.assertIn('id="visual-track" class="clip"', html)
        self.assertIn('src="media/visual.mp4"', html)
        self.assertIn("muted playsinline", html)
        self.assertIn('id="audio-track" class="clip"', html)
        self.assertIn('src="media/audio.m4a"', html)
        self.assertIn("wash-1", html)


if __name__ == "__main__":
    unittest.main()
