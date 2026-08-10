from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from auto_publish_pipeline.domain import build_task_spec, infer_product_name, infer_script_country
from auto_publish_pipeline.runner import PipelineRunner
from auto_publish_pipeline.store import TaskStore


class PipelineDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.clone = root / "产品A" / "复刻-产品A-US-author-1234567890123456789.md"
        self.clone.parent.mkdir()
        self.clone.write_text("# 有效复刻脚本\n内容", encoding="utf-8")
        self.image = root / "product.png"
        self.image.write_bytes(b"png")
        self.existing_video = root / "existing.mp4"
        self.existing_video.write_bytes(b"video")
        captions = [
            {"full_text": f"Caption {index} #a #b #c #d #e", "tags": ["#a", "#b", "#c", "#d", "#e"]}
            for index in range(1, 10)
        ]
        self.catalog = {
            "profiles": [
                {"id": "b", "name": "B", "country": "US"},
                {"id": "a", "name": "A", "country": "US"},
            ],
            "libraries": [
                {"code": "P001", "key": "P001-产品A", "name": "产品A", "by_country": {"US": {"items": captions}}}
            ],
            "videos": [
                {"path": str(self.existing_video.resolve()), "product_code": "P001", "countries": ["US"], "published": False}
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def payload(self) -> dict:
        return {
            "clone_path": str(self.clone), "product_code": "P001",
            "target_language": "English", "video_model": "omni", "reference_image": str(self.image),
            "concurrency": 4, "caption_mode": "karaoke", "profile_ids": ["b", "a"],
            "auto_publish": False,
        }

    @staticmethod
    def mapping(profile_id: str, _product: str, _country: str) -> dict:
        return {"product_id": f"link-{profile_id}", "product_short_name": "Short"}

    def test_assigns_three_unique_variants_per_account_in_selection_order(self):
        spec = build_task_spec(self.payload(), self.catalog, self.mapping, chooser=random.Random(7))

        self.assertEqual(spec["variant_count"], 9)
        self.assertEqual(spec["publish_count"], 6)
        self.assertEqual(spec["candidate_budget"], 9)
        self.assertEqual(spec["generation_count"], 9)
        self.assertEqual([item["profile_id"] for item in spec["assignments"]], ["b"] * 3 + ["a"] * 3)
        self.assertEqual(len({item["caption"] for item in spec["assignments"]}), 6)
        self.assertEqual(spec["interval_seconds"], 10)
        self.assertEqual(spec["start_mode"], "manual")
        self.assertEqual(spec["country"], "US")

    def test_country_and_default_language_are_inferred_from_clone_filename(self):
        payload = self.payload()
        payload.pop("target_language")

        spec = build_task_spec(payload, self.catalog, self.mapping, chooser=random.Random(7))

        self.assertEqual(spec["country"], "US")
        self.assertEqual(spec["target_language"], "英语")

    def test_user_can_override_the_inferred_default_language(self):
        payload = self.payload()
        payload["target_language"] = "西班牙语"

        spec = build_task_spec(payload, self.catalog, self.mapping, chooser=random.Random(7))

        self.assertEqual(spec["country"], "US")
        self.assertEqual(spec["target_language"], "西班牙语")

    def test_rejects_submitted_country_that_conflicts_with_script(self):
        payload = self.payload()
        payload["country"] = "UK"
        with self.assertRaisesRegex(ValueError, "复刻脚本"):
            build_task_spec(payload, self.catalog, self.mapping)

    def test_infers_country_after_hyphenated_product_name(self):
        path = Path("复刻-DRN-E99Pro无人机-IE-author-1234567890123456789.md")

        self.assertEqual(infer_script_country(path), "IE")
        self.assertEqual(infer_product_name(path), "DRN-E99Pro无人机")

    def test_existing_finished_video_is_used_before_new_generation_budget(self):
        payload = self.payload()
        payload["existing_video_paths"] = [str(self.existing_video)]
        spec = build_task_spec(payload, self.catalog, self.mapping, chooser=random.Random(7))

        self.assertEqual(spec["existing_videos"], [str(self.existing_video.resolve())])
        self.assertEqual(spec["candidate_budget"], 9)
        self.assertEqual(spec["generation_count"], 8)

    def test_three_accounts_create_nine_publish_slots_and_fourteen_candidates(self):
        self.catalog["profiles"].append({"id": "c", "name": "C", "country": "US"})
        items = self.catalog["libraries"][0]["by_country"]["US"]["items"]
        items.extend(
            {"full_text": f"Extra {index} #a #b #c #d #e", "tags": ["#a", "#b", "#c", "#d", "#e"]}
            for index in range(10, 15)
        )
        payload = self.payload()
        payload["profile_ids"] = ["b", "a", "c"]
        spec = build_task_spec(payload, self.catalog, self.mapping, chooser=random.Random(7))

        self.assertEqual(spec["publish_count"], 9)
        self.assertEqual(spec["candidate_budget"], 14)
        self.assertEqual(spec["generation_count"], 14)

    def test_rejects_title_pool_smaller_than_account_count_times_three(self):
        self.catalog["libraries"][0]["by_country"]["US"]["items"] = self.catalog["libraries"][0]["by_country"]["US"]["items"][:5]
        with self.assertRaisesRegex(ValueError, "标题库不足"):
            build_task_spec(self.payload(), self.catalog, self.mapping)

    def test_rejects_account_from_another_country(self):
        self.catalog["profiles"][0]["country"] = "UK"
        with self.assertRaisesRegex(ValueError, "账号国家"):
            build_task_spec(self.payload(), self.catalog, self.mapping)


class TaskStoreTests(unittest.TestCase):
    def test_restart_during_publish_requires_manual_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pipeline.sqlite3"
            store = TaskStore(path)
            task = store.create({"assignments": []})
            store.update(task["id"], status="running", stage="publishing", artifacts={"active_publish_index": 2})

            recovered = TaskStore(path).get(task["id"])

        self.assertEqual(recovered["status"], "needs_review")
        self.assertIn("确认", recovered["error"])

    def test_failed_task_can_resume_from_saved_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TaskStore(Path(temp_dir) / "pipeline.sqlite3")
            task = store.create({"assignments": []})
            store.update(task["id"], status="failed", stage="adapting", artifacts={"variants": ["one.md"]})
            runner = PipelineRunner(store, Path(temp_dir))

            resumed = runner.retry(task["id"])

        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["artifacts"]["variants"], ["one.md"])


if __name__ == "__main__":
    unittest.main()
