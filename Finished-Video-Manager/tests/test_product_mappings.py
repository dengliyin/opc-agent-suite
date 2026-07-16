import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finished_video_manager.web import load_publish_config, save_publish_config


class ProductMappingsTest(unittest.TestCase):
    def test_shared_mappings_override_stale_local_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_path = root / "data" / "publish_config.json"
            mappings_path = root / "config" / "product_mappings.json"
            local_path.parent.mkdir()
            mappings_path.parent.mkdir()
            local_path.write_text(
                json.dumps({"accounts": {"local": {}}, "product_links_by_store": {"OLD": {}}}),
                encoding="utf-8",
            )
            mappings_path.write_text(
                json.dumps(
                    {
                        "product_links_by_store": {"NEW": {"UK": {"store": {"channel": "123"}}}},
                        "product_short_names": {"NEW": {"UK": "Shared name"}},
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("finished_video_manager.web.DATA_ROOT", local_path.parent),
                patch("finished_video_manager.web.PUBLISH_CONFIG_PATH", local_path),
                patch("finished_video_manager.web.PUBLISH_RECORDS_PATH", root / "data" / "publish_records.json"),
                patch("finished_video_manager.web.PRODUCT_MAPPINGS_PATH", mappings_path),
            ):
                config = load_publish_config()

        self.assertEqual(config["accounts"], {"local": {}})
        self.assertEqual(set(config["product_links_by_store"]), {"NEW"})
        self.assertEqual(config["product_short_names"]["NEW"]["UK"], "Shared name")

    def test_save_separates_shared_mappings_from_local_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_path = root / "data" / "publish_config.json"
            mappings_path = root / "config" / "product_mappings.json"

            with (
                patch("finished_video_manager.web.PUBLISH_CONFIG_PATH", local_path),
                patch("finished_video_manager.web.PRODUCT_MAPPINGS_PATH", mappings_path),
            ):
                save_publish_config(
                    {
                        "accounts": {"local": {"name": "Local account"}},
                        "daily_kpis": {"target_per_account": 3},
                        "product_links_by_store": {"P1": {"UK": {"store": {"channel": "123"}}}},
                        "product_short_names": {"P1": {"UK": "Product"}},
                    }
                )

            local = json.loads(local_path.read_text(encoding="utf-8"))
            shared = json.loads(mappings_path.read_text(encoding="utf-8"))

        self.assertIn("accounts", local)
        self.assertNotIn("product_links_by_store", local)
        self.assertNotIn("product_short_names", local)
        self.assertEqual(shared["product_links_by_store"]["P1"]["UK"]["store"]["channel"], "123")
        self.assertEqual(shared["product_short_names"]["P1"]["UK"], "Product")


if __name__ == "__main__":
    unittest.main()
