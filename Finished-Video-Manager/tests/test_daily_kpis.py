import unittest

from finished_video_manager.web import build_daily_kpi_rows, normalize_daily_kpi_date


class DailyKpisTest(unittest.TestCase):
    def test_counts_published_records_per_profile_and_date(self) -> None:
        profiles = [
            {"id": "a", "name": "UK-shop-store-channel-a", "country": "UK"},
            {"id": "b", "name": "UK-shop-store-channel-b", "country": "UK"},
        ]
        records = [
            {"status": "published", "profile_id": "a", "published_at": "2026-07-11 09:00:00 +0800"},
            {"status": "published", "profile_id": "a", "published_at": "2026-07-11 10:00:00 +0800"},
            {"status": "published", "profile_id": "a", "published_at": "2026-07-11 11:00:00 +0800"},
            {"status": "published", "profile_id": "b", "published_at": "2026-07-10 11:00:00 +0800"},
            {"status": "failed", "profile_id": "b", "published_at": "2026-07-11 12:00:00 +0800"},
        ]

        result = build_daily_kpi_rows(profiles, records, "2026-07-11", 3)
        rows = {row["id"]: row for row in result["rows"]}

        self.assertEqual(rows["a"]["published"], 3)
        self.assertTrue(rows["a"]["met"])
        self.assertEqual(rows["b"]["published"], 0)
        self.assertEqual(rows["b"]["remaining"], 3)
        self.assertEqual(result["summary"]["met_count"], 1)
        self.assertEqual(result["summary"]["total_published"], 3)

    def test_rejects_invalid_date(self) -> None:
        with self.assertRaises(ValueError):
            normalize_daily_kpi_date("2026-02-31")


if __name__ == "__main__":
    unittest.main()
