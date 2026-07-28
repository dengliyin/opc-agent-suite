from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hot_video_agent import paths, web  # noqa: E402


class WebPathTests(unittest.TestCase):
    def test_hot_video_path_can_be_resolved_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "library"
            with patch.object(paths, "HOT_VIDEO_LIBRARY_ROOT", library):
                result = paths.ProjectPaths(ROOT, {"product": {"name": "测试产品"}}).hot_video_dir(create=False)

            self.assertEqual(result, library / "测试产品")
            self.assertFalse(result.exists())

    def test_category_tree_skips_unreadable_source(self) -> None:
        blocked = Path("/blocked/category-tree.json")
        with (
            patch.object(web, "CATEGORY_TREE_PATHS", [blocked]),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", side_effect=PermissionError("blocked")),
        ):
            result = web.load_category_tree()

        self.assertEqual(result["category_tree"], {})
        self.assertEqual(result["top_categories"], ["全部"])

    def test_runtime_support_files_are_migrated_out_of_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy_tree = root / "source" / "category.json"
            runtime_tree = root / "runtime" / "category.json"
            legacy_index = root / "source" / "products.json"
            runtime_index = root / "runtime" / "products.json"
            legacy_tree.parent.mkdir()
            legacy_tree.write_text(json.dumps({"category_tree": {}}), encoding="utf-8")
            legacy_index.write_text("[]", encoding="utf-8")

            with (
                patch.object(web, "LEGACY_CATEGORY_TREE_PATH", legacy_tree),
                patch.object(web, "CATEGORY_TREE_RUNTIME_PATH", runtime_tree),
                patch.object(web, "LEGACY_PRODUCT_INFO_INDEX_PATH", legacy_index),
                patch.object(web, "PRODUCT_INFO_INDEX_PATH", runtime_index),
            ):
                web.migrate_runtime_support_files()

            self.assertEqual(runtime_tree.read_bytes(), legacy_tree.read_bytes())
            self.assertEqual(runtime_index.read_bytes(), legacy_index.read_bytes())


if __name__ == "__main__":
    unittest.main()
