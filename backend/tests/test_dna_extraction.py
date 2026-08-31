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
            "Nordic Calm / （静雅北欧）",
        )


if __name__ == "__main__":
    unittest.main()
