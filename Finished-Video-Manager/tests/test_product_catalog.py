import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finished_video_manager.web import load_product_info_catalog


class ProductCatalogTest(unittest.TestCase):
    def test_reads_all_product_info_filenames_and_skips_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "HTC-生发茶-产品信息.md").write_text("# 生发茶\n", encoding="utf-8")
            (root / "JR01-天然矿石戒指-产品信息.md").write_text("# 戒指\n", encoding="utf-8")
            (root / "_template.md").write_text("# 产品名称\n", encoding="utf-8")
            (root / "说明.md").write_text("说明\n", encoding="utf-8")

            with patch("finished_video_manager.web.PRODUCT_INFO_ROOT", root):
                products = load_product_info_catalog()

        self.assertEqual(
            products,
            [
                {"code": "HTC", "name": "生发茶"},
                {"code": "JR01", "name": "天然矿石戒指"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
