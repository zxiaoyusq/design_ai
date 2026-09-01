"""设计 DNA 业务视图的跨 Schema 兼容测试。"""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from extract_design_dna_business_view import _flatten_elements, _normalize_level_2  # noqa: E402


class BusinessViewCompatibilityTestCase(unittest.TestCase):
    def test_normalizes_v3_and_v4_style_labels(self) -> None:
        self.assertEqual(
            _normalize_level_2("Soft Pastel / （柔和粉彩）"),
            "柔和粉彩（Soft Pastel）",
        )
        self.assertEqual(
            _normalize_level_2("Soft Pastel / 柔和粉彩"),
            "柔和粉彩（Soft Pastel）",
        )
        self.assertEqual(
            _normalize_level_2("旧显示值", "精致克制", "Refined Restraint"),
            "精致克制（Refined Restraint）",
        )

    def test_uses_schema_specific_module_groups(self) -> None:
        modules = [
            {"module_id": "DNA-M04", "elements": [{"field_id": "TEST-04"}]},
            {"module_id": "DNA-M10", "elements": [{"field_id": "TEST-10"}]},
        ]

        v3_records = _flatten_elements(
            {
                "schema_version": "design_dna_extraction_v3.1",
                "design_elements": {"extended_dna_modules": modules},
            }
        )
        v4_records = _flatten_elements(
            {
                "schema_version": "design_dna_extraction_v4.0",
                "design_elements": {"extended_dna_modules": modules},
            }
        )

        self.assertEqual(
            [record["group"] for record in v3_records],
            ["品类专属", "品牌与系列"],
        )
        self.assertEqual(
            [record["group"] for record in v4_records],
            ["组件与负空间", "标识与文字"],
        )


if __name__ == "__main__":
    unittest.main()
