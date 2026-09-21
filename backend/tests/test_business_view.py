"""设计 DNA 业务视图的跨 Schema 兼容测试。"""

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from extract_design_dna_business_view import (  # noqa: E402
    MULTITAG_BUSINESS_SCHEMA_VERSION,
    _flatten_elements,
    _normalize_level_2,
    extract_business_view,
)


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

    def test_multitag_business_view_keeps_flat_style_candidates(self) -> None:
        example_path = (
            PROJECT_ROOT
            / "ref"
            / "multimodal-design-dna-multitag-extractor"
            / "examples"
            / "smartphone-red-multitag.example.json"
        )
        full_result = json.loads(example_path.read_text(encoding="utf-8"))

        business = extract_business_view(full_result)

        self.assertEqual(business["schema_version"], MULTITAG_BUSINESS_SCHEMA_VERSION)
        self.assertEqual(
            [tag["style_id"] for tag in business["style"]["style_candidates"]],
            ["SaturatedBold", "RefinedMinimalism"],
        )
        self.assertNotIn("primary", business["style"])
        self.assertNotIn("secondary", business["style"])
        self.assertNotIn("status", business["style"])
        self.assertNotIn("pairwise_arbitrations", business["style"])
        self.assertNotIn("uncertain_fields", business)
        self.assertEqual(
            business["source_schema_version"],
            "design_dna_multitag_extraction_v1.3",
        )

    def test_legacy_multitag_uncertainty_is_read_but_not_displayed(self) -> None:
        """v1.2 历史结果继续可读，但废弃字段不传播到新版业务视图。"""

        full_result = {
            "schema_version": "design_dna_multitag_extraction_v1.2",
            "knowledge_base_version": "4.1",
            "target_object": {"category": "phone", "view": "rear"},
            "style_result": {"style_candidates": [], "composition_summary": "无候选。"},
            "design_elements": {"extended_dna_modules": []},
            "uncertain_fields": [{"field_name": "历史字段"}],
            "novel_dna_elements": [],
            "quality_summary": {"concise_summary": "历史结果。"},
        }

        business = extract_business_view(full_result)

        self.assertEqual(business["schema_version"], MULTITAG_BUSINESS_SCHEMA_VERSION)
        self.assertNotIn("uncertain_fields", business)


if __name__ == "__main__":
    unittest.main()
