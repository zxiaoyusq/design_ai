"""DNA 提取结果的应用层确定性修正测试。"""

import unittest

from app.services.dna.extraction import (
    _canonicalize_style_names,
    _recalculate_quality_summary,
)


class DnaExtractionTestCase(unittest.TestCase):
    def test_recalculates_low_confidence_field_count(self) -> None:
        data = {
            "design_elements": {
                "original_md_dimensions": [
                    {
                        "elements": [
                            {"confidence": 0.74},
                            {"confidence": 0.75},
                        ]
                    }
                ],
                "extended_dna_modules": [
                    {"elements": [{"confidence": 0.5}, {"value": "unknown"}]}
                ],
            },
            "quality_summary": {"low_confidence_field_count": 99},
        }

        _recalculate_quality_summary(data)

        self.assertEqual(data["quality_summary"]["low_confidence_field_count"], 2)

    def test_canonicalizes_equivalent_style_name_punctuation(self) -> None:
        data = {
            "style_result": {
                "primary_style": {
                    "level_1": "1.极简品质",
                    "level_2": "Nordic Calm（静雅北欧）",
                },
                "secondary_styles": [],
                "candidate_ranking": [],
            }
        }

        _canonicalize_style_names(data)

        self.assertEqual(
            data["style_result"]["primary_style"]["level_2"],
            "Warm Calm / 温润静雅",
        )
        self.assertEqual(
            data["style_result"]["primary_style"]["style_id"],
            "NordicCalm",
        )
        self.assertEqual(
            data["style_result"]["primary_style"]["parent_style_id"],
            "restrained_craft",
        )

    def test_migrates_deprecated_style_alias(self) -> None:
        data = {
            "style_result": {
                "primary_style": {
                    "level_1": "奢华品质",
                    "level_2": "Quiet Elegant Luxury / （静奢简雅）",
                },
                "secondary_styles": [],
                "candidate_ranking": [],
            }
        }

        _canonicalize_style_names(data)

        primary = data["style_result"]["primary_style"]
        self.assertEqual(primary["style_id"], "RefinedMinimalism")
        self.assertEqual(primary["parent_style_id"], "restrained_craft")
        self.assertEqual(primary["level_2"], "Refined Restraint / 精致克制")
        self.assertEqual(primary["label_en"], "Refined Restraint")
        self.assertEqual(primary["label_zh"], "精致克制")
        self.assertEqual(
            primary["aliases"],
            ["Refined Minimalism", "现代简致", "静奢简雅"],
        )


if __name__ == "__main__":
    unittest.main()
