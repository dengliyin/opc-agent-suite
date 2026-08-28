from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class UrlDownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.downloader = load_module("script_analysis_url_downloader", ROOT / "scripts" / "url_downloader.py")
        cls.web_app = load_module("script_analysis_web_app_for_download", ROOT / "scripts" / "web_app.py")

    def test_extracts_normalizes_and_deduplicates_urls(self):
        text = """
        https://www.tiktok.com/@alice/video/1234567890123456789?lang=en
        https://www.tiktok.com/@alice/video/1234567890123456789，
        https://example.com/not-tiktok
        https://www.tiktok.com/@bob/video/9876543210987654321。
        """
        self.assertEqual(
            self.downloader.extract_tiktok_urls(text),
            [
                "https://www.tiktok.com/@alice/video/1234567890123456789",
                "https://www.tiktok.com/@bob/video/9876543210987654321",
            ],
        )

    def test_download_one_saves_video_and_metadata(self):
        url = "https://www.tiktok.com/@alice/video/1234567890123456789"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            def fake_fetcher(_url):
                return {"hdUrls": ["https://cdn.test/video.mp4"], "desc": "Demo title"}

            def fake_saver(_url, target):
                target.write_bytes(b"x" * 100001)

            status, target, video_id = self.downloader.download_one(
                url, output_dir, fetcher=fake_fetcher, saver=fake_saver
            )
            second_status, second_target, _ = self.downloader.download_one(
                url, output_dir, fetcher=fake_fetcher, saver=fake_saver
            )

            self.assertEqual(status, "downloaded")
            self.assertEqual(second_status, "skipped")
            self.assertEqual(second_target, target)
            self.assertEqual(video_id, "1234567890123456789")
            self.assertTrue(target.with_suffix(".json").exists())

    def test_product_directory_stays_inside_video_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = self.web_app.download_product_dir(root, "产品A")
            self.assertEqual(target, (root / "产品A").resolve())
            with self.assertRaises(ValueError):
                self.web_app.download_product_dir(root, "../outside")

    def test_product_picker_uses_native_select(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<select id="downloadProductInput">', html)
        self.assertNotIn('list="downloadProductOptions"', html)

    def test_content_line_picker_replaces_visible_path_inputs(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<select id="contentLineInput">', html)
        self.assertIn('<select id="materialTypeInput">', html)
        self.assertNotIn('id="videoDirInput"', html)
        self.assertNotIn('id="scriptDirInput"', html)

    def test_four_stage_layout_keeps_collection_and_queue_separate(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        self.assertIn('id="urlDownloadBlock"', html)
        self.assertIn('<h2>视频采集</h2>', html)
        self.assertIn('<h2>扫描拆解视频</h2>', html)
        self.assertIn('<h2>拆解运行</h2>', html)
        self.assertIn('<h2>脚本结果</h2>', html)
        self.assertNotIn('$("urlDownloadBlock").open = false;', javascript)
        self.assertIn("minmax(280px, 0.8fr)", stylesheet)
        self.assertIn("minmax(400px, 1.2fr)", stylesheet)

    def test_hybrid_download_and_script_paths_keep_material_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_dir = root / "videos"
            script_dir = root / "scripts"
            video_dir.mkdir()
            script_dir.mkdir()
            product_dir = self.web_app.download_product_dir(
                video_dir, "产品A", "hybrid", "混剪-CTA"
            )
            video = product_dir / "alice-1234567890123456789-demo.mp4"
            video.write_bytes(b"video")

            scan = self.web_app.scan_teardown_queue(video_dir, script_dir, "hybrid")

            self.assertEqual(product_dir, (video_dir / "混剪-CTA" / "产品A").resolve())
            self.assertEqual(scan["content_line"], "hybrid")
            self.assertEqual(scan["pending"][0]["relative_dir"], "混剪-CTA/产品A")
            self.assertEqual(
                Path(scan["pending"][0]["target_path"]).parent.resolve(),
                (script_dir / "混剪-CTA" / "产品A").resolve(),
            )

    def test_download_job_continues_after_one_url_fails(self):
        urls = [
            "https://www.tiktok.com/@alice/video/1234567890123456789",
            "https://www.tiktok.com/@bob/video/9876543210987654321",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_dir = root / "videos"
            script_dir = root / "scripts"
            product_dir = video_dir / "产品A"
            product_dir.mkdir(parents=True)
            script_dir.mkdir()
            target = product_dir / "alice-1234567890123456789-demo.mp4"
            job_id = "download-test"
            self.web_app.JOBS.clear()
            self.web_app.set_job(
                job_id,
                id=job_id,
                type="url_download",
                status="queued",
                total=2,
                items=[{"url": url, "status": "queued"} for url in urls],
                logs=[],
            )

            def fake_download(url, _output_dir):
                if "alice" in url:
                    return "downloaded", target, "1234567890123456789"
                raise RuntimeError("download failed")

            with patch.object(self.web_app.url_downloader, "download_one", side_effect=fake_download), patch.object(
                self.web_app.time, "sleep"
            ):
                self.web_app.run_url_download_job(job_id, urls, video_dir, script_dir, product_dir)

            job = self.web_app.get_job(job_id)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["downloaded"], 1)
            self.assertEqual(job["failed"], 1)
            self.assertEqual(job["items"][0]["status"], "downloaded")
            self.assertEqual(job["items"][1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
