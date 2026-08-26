import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from finished_video_manager.publish_queue import PublishQueue


def task(name: str, profile_id: str = "profile-1") -> dict:
    return {
        "video_path": f"/tmp/{name}.mp4",
        "video_name": f"{name}.mp4",
        "product_code": "TEST",
        "country": "UK",
        "profile_id": profile_id,
        "profile_name": f"UK-shop-channel-{profile_id}",
        "caption": "Test caption #one #two #three #four #five",
        "product_id": "123",
        "product_short_name": "Test product",
        "attach_product": True,
        "ai_generated": True,
        "visibility": "public",
    }


class PublishQueueTest(unittest.TestCase):
    def test_product_link_choice_is_saved_and_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            queued = task("without-product")
            queued["attach_product"] = False
            queued["product_id"] = ""
            queued["product_short_name"] = ""
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: calls.append(item) or {},
                interval_seconds=0,
            )
            queue.enqueue([queued])

            payload = queue.payload()
            self.assertFalse(payload["tasks"][0]["attach_product"])
            self.assertEqual(payload["tasks"][0]["product_id"], "")

            queue.start()
            queue.control("resume")
            deadline = time.time() + 2
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            queue.stop()

            self.assertFalse(calls[0]["attach_product"])

    def test_legacy_tasks_default_to_attaching_product(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queued = task("legacy")
            queued.pop("attach_product")
            queue = PublishQueue(Path(directory) / "queue.sqlite3", lambda item: {})
            queue.enqueue([queued])

            self.assertTrue(queue.payload()["tasks"][0]["attach_product"])

    def test_closes_profile_after_last_consecutive_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            closed_profiles = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: calls.append(item["video_name"]) or {"url": "/tiktokstudio/content"},
                interval_seconds=0,
                profile_closer=lambda item: closed_profiles.append(item["profile_id"]) or {"success": True},
            )
            queue.enqueue([task("first"), task("second"), task("third")])
            queue.start()
            queue.control("resume")
            deadline = time.time() + 3
            while time.time() < deadline and queue.payload()["counts"].get("published") != 3:
                time.sleep(0.05)
            queue.stop()

            self.assertEqual(calls, ["first.mp4", "second.mp4", "third.mp4"])
            self.assertEqual(closed_profiles, ["profile-1"])

    def test_closes_profile_when_next_task_switches_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            closed_profiles = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: {"url": "/tiktokstudio/content"},
                interval_seconds=0,
                profile_closer=lambda item: closed_profiles.append(item["profile_id"]) or {"success": True},
            )
            queue.enqueue([task("a1", "account-a"), task("a2", "account-a"), task("b1", "account-b")])
            queue.start()
            queue.control("resume")
            deadline = time.time() + 3
            while time.time() < deadline and queue.payload()["counts"].get("published") != 3:
                time.sleep(0.05)
            queue.stop()

            self.assertEqual(closed_profiles, ["account-a", "account-b"])

    def test_enqueue_waits_for_explicit_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: calls.append(item["video_name"]) or {"url": "/tiktokstudio/content"},
                interval_seconds=0,
            )
            queue.enqueue([task("staged")])
            queue.start()
            time.sleep(0.2)

            payload = queue.payload()
            self.assertTrue(payload["paused"])
            self.assertEqual(payload["counts"].get("pending"), 1)
            self.assertEqual(calls, [])

            queue.control("resume")
            deadline = time.time() + 2
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            queue.stop()
            self.assertEqual(calls, ["staged.mp4"])

    def test_scheduled_queue_waits_until_due_and_uses_selected_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: calls.append(item["execution_mode"]) or {},
                interval_seconds=0,
            )
            queue.enqueue([task("scheduled")])
            queue.start()
            scheduled_at = time.time() + 0.4
            queue.control("schedule", "headless", scheduled_at)
            time.sleep(0.15)
            self.assertEqual(calls, [])
            self.assertAlmostEqual(queue.payload()["scheduled_at"], scheduled_at, places=2)

            deadline = time.time() + 2
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            queue.stop()

            self.assertEqual(calls, ["headless"])
            self.assertEqual(queue.payload()["scheduled_at"], 0)

    def test_cancel_schedule_keeps_queue_paused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: calls.append(item["video_name"]) or {},
                interval_seconds=0,
            )
            queue.enqueue([task("canceled-schedule")])
            queue.start()
            queue.control("schedule", "visible", time.time() + 0.2)
            queue.control("cancel_schedule")
            time.sleep(0.4)
            payload = queue.payload()
            queue.stop()

            self.assertEqual(calls, [])
            self.assertTrue(payload["paused"])
            self.assertEqual(payload["scheduled_at"], 0)

    def test_selected_execution_mode_is_forwarded_to_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            modes = []
            queue = PublishQueue(
                Path(directory) / "queue.sqlite3",
                lambda item: modes.append(item["execution_mode"]) or {},
                interval_seconds=0,
            )
            queue.enqueue([task("headless")])
            queue.start()
            queue.control("resume", "headless")
            deadline = time.time() + 2
            while time.time() < deadline and not modes:
                time.sleep(0.05)
            queue.stop()

            self.assertEqual(modes, ["headless"])
            self.assertEqual(queue.payload()["execution_mode"], "headless")

    def test_retried_task_forces_visible_without_changing_other_headless_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            closed_profiles = []
            path = Path(directory) / "queue.sqlite3"
            queue = PublishQueue(
                path,
                lambda item: calls.append((item["video_name"], item["execution_mode"])) or {},
                interval_seconds=0,
                profile_closer=lambda item: closed_profiles.append(item["profile_id"]) or {"success": True},
            )
            retry_id, _normal_id = queue.enqueue([task("retry"), task("normal", "profile-2")])
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE queue_tasks SET status='failed' WHERE id=?", (retry_id,))
            queue.task_action(retry_id, "retry")
            queue.start()
            queue.control("resume", "headless")
            deadline = time.time() + 3
            while time.time() < deadline and queue.payload()["counts"].get("published") != 2:
                time.sleep(0.05)
            queue.stop()

            self.assertEqual(calls, [("normal.mp4", "headless"), ("retry.mp4", "visible")])
            self.assertIn("profile-1", closed_profiles)
            self.assertEqual(queue.payload()["execution_mode"], "headless")

    def test_executes_in_reordered_sequence_with_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            queue = PublishQueue(Path(directory) / "queue.sqlite3", lambda item: calls.append(item["video_name"]) or {"url": "/tiktokstudio/content"}, interval_seconds=1)
            queue.control("pause")
            ids = queue.enqueue([task("first"), task("second")])
            queue.task_action(ids[0], "move_down")
            queue.start()
            queue.control("resume")
            deadline = time.time() + 5
            while time.time() < deadline and len(calls) < 2:
                time.sleep(0.1)
            queue.stop()
            self.assertEqual(calls, ["second.mp4", "first.mp4"])
            self.assertEqual(queue.payload()["counts"].get("published"), 2)

    def test_running_task_becomes_needs_review_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            queue = PublishQueue(path, lambda item: {})
            queue.control("pause")
            task_id = queue.enqueue([task("interrupted")])[0]
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE queue_tasks SET status='running' WHERE id=?", (task_id,))
            restarted = PublishQueue(path, lambda item: {})
            payload = restarted.payload()
            self.assertTrue(payload["paused"])
            self.assertEqual(payload["tasks"][0]["status"], "needs_review")

    def test_resolves_legacy_video_paths_for_queue_display_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            old_path = "/finished/omni/2026-07-13/TEST/demo.mp4"
            new_path = "/finished/TEST/demo.mp4"
            queued = task("demo")
            queued["video_path"] = old_path
            db_path = Path(directory) / "queue.sqlite3"
            legacy_queue = PublishQueue(db_path, lambda item: {})
            legacy_queue.enqueue([queued])
            queue = PublishQueue(
                db_path,
                lambda item: calls.append(item["video_path"]) or {},
                interval_seconds=0,
                video_path_resolver=lambda value: new_path if value == old_path else value,
            )

            self.assertEqual(queue.payload()["tasks"][0]["video_path"], new_path)
            queue.start()
            queue.control("resume")
            deadline = time.time() + 2
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            queue.stop()

        self.assertEqual(calls, [new_path])

    def test_completed_history_does_not_touch_vault_when_loading_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            db_path = Path(directory) / "queue.sqlite3"
            queue = PublishQueue(db_path, lambda item: {}, video_path_resolver=lambda value: calls.append(value) or value)
            task_id = queue.enqueue([task("history")])[0]
            with sqlite3.connect(db_path) as connection:
                connection.execute("UPDATE queue_tasks SET status='published' WHERE id=?", (task_id,))

            payload = queue.payload()

        self.assertEqual(payload["counts"].get("published"), 1)
        self.assertEqual(calls, ["/tmp/history.mp4"])


if __name__ == "__main__":
    unittest.main()
