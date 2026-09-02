"""精简模型观察协议与确定性编译器回归测试。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.dna.extraction import _compile_model_result


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / "ref" / "multimodal-design-dna-multitag-extractor"
EXAMPLE_PATH = SKILL_ROOT / "examples" / "smartphone-red-multitag.example.json"


def _lean_observation(full: dict) -> dict:
    """只保留模型需要判断的视觉/语义字段，模拟 observation_v1 输出。"""

    style_result = full["style_result"]
    confirmed_ids = {item["style_id"] for item in style_result["style_tags"]}
    all_elements = [
        element
        for module in full["design_elements"]["extended_dna_modules"]
        for element in module["elements"]
    ]
    return {
        "schema_version": "design_dna_multitag_observation_v1",
        "knowledge_base_version": full["knowledge_base_version"],
        "target_object": full["target_object"],
        "image_quality": full["image_quality"],
        "active_profiles": full["module_applicability"]["active_profiles"],
        "rule_adaptations": full["module_applicability"]["rule_adaptations"],
        "style_observations": {
            "classification_status": style_result["classification_status"],
            "confirmed_tags": [
                {
                    "style_id": item["style_id"],
                    "match_score": item["match_score"],
                    "confidence": item["confidence"],
                    "dominance": item["dominance"],
                    "regions": item["regions"],
                    "applicable_rule_count": item["rule_coverage"][
                        "applicable_rule_count"
                    ],
                    "not_applicable_rule_count": item["rule_coverage"][
                        "not_applicable_rule_count"
                    ],
                    "color_requirement_status": item["color_requirement"]["status"],
                    "core_feature_hits": item["core_feature_hits"],
                    "auxiliary_feature_hits": item["auxiliary_feature_hits"],
                }
                for item in style_result["style_tags"]
            ],
            "other_candidates": [
                {
                    key: item[key]
                    for key in (
                        "style_id",
                        "match_score",
                        "confidence",
                        "regions",
                        "candidate_status",
                        "hard_rule_passed",
                        "main_support",
                        "main_conflicts",
                    )
                }
                for item in style_result["candidate_ranking"]
                if item["style_id"] not in confirmed_ids
            ],
            "pairwise_reasoning": [
                {
                    "style_id_a": item["style_id_a"],
                    "style_id_b": item["style_id_b"],
                    "reason": item["reason"],
                }
                for item in style_result["pairwise_arbitrations"]
            ],
            "composition_summary": style_result["composition_summary"],
        },
        "design_observations": [
            {
                key: element[key]
                for key in (
                    "field_id",
                    "value",
                    "raw_visual_description",
                    "region",
                    "observability",
                    "confidence",
                    "evidence_refs",
                )
            }
            for element in all_elements
        ],
        "uncertainties": [
            {
                key: item[key]
                for key in (
                    "field_id",
                    "region",
                    "reason_type",
                    "reason",
                    "observability",
                    "confidence",
                    "best_estimate",
                    "candidate_values",
                    "recommended_additional_view_or_info",
                )
            }
            | {
                "evidence_refs": next(
                    element["evidence_refs"]
                    for element in all_elements
                    if element["field_id"] == item["field_id"]
                    and element["region"] == item["region"]
                )
            }
            for item in full["uncertain_fields"]
        ],
        "novel_dna_elements": full["novel_dna_elements"],
        "evidence": full["evidence"],
        "quality_notes": {
            "missing_critical_fields": full["quality_summary"][
                "missing_critical_fields"
            ],
            "warnings": full["quality_summary"]["warnings"],
            "concise_summary": full["quality_summary"]["concise_summary"],
        },
    }


class DnaCompilationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.full = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_lean_observation_compiles_to_valid_final_result(self) -> None:
        observation = _lean_observation(self.full)
        uncertainty = observation["uncertainties"][0]
        observation["design_observations"] = [
            item
            for item in observation["design_observations"]
            if (item["field_id"], item["region"])
            != (uncertainty["field_id"], uncertainty["region"])
        ]

        compiled, report = _compile_model_result(observation)

        self.assertEqual(report["source_contract"], "design_dna_multitag_observation_v1")
        self.assertEqual(compiled["schema_version"], "design_dna_multitag_extraction_v1.1")
        self.assertEqual(compiled["quality_summary"]["low_confidence_field_count"], 1)
        self.assertTrue(
            any(
                element["field_id"] == uncertainty["field_id"]
                and element["region"] == uncertainty["region"]
                for module in compiled["design_elements"]["extended_dna_modules"]
                for element in module["elements"]
            )
        )
        self.assertEqual(
            [item["rank"] for item in compiled["style_result"]["candidate_ranking"]],
            [1, 2, 3, 4],
        )
        self.assertLess(
            len(json.dumps(observation, ensure_ascii=False, separators=(",", ":"))),
            len(json.dumps(self.full, ensure_ascii=False, separators=(",", ":"))) * 0.65,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            compiled_path = Path(temporary_directory) / "compiled.json"
            final_path = Path(temporary_directory) / "final.json"
            compiled_path.write_text(json.dumps(compiled, ensure_ascii=False), encoding="utf-8")
            derive = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "derive_style_presets.py"),
                    str(compiled_path),
                    "--output",
                    str(final_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(derive.returncode, 0, derive.stderr)
            validate = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "validate_output.py"),
                    str(final_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    def test_full_result_mechanical_inconsistencies_are_normalized(self) -> None:
        malformed = copy.deepcopy(self.full)
        malformed["quality_summary"]["mean_confidence"] = 0
        malformed["style_result"]["style_tags"][0]["label_zh"] = "错误名称"
        malformed["style_result"]["style_tags"].reverse()
        malformed["style_result"]["candidate_ranking"][0]["rank"] = 99
        malformed["uncertain_fields"][0]["confidence"] = 0.1

        compiled, report = _compile_model_result(malformed)

        self.assertGreater(report["deterministic_correction_count"], 0)
        self.assertEqual(
            compiled["style_result"]["style_tags"][0]["style_id"],
            "SaturatedBold",
        )
        self.assertEqual(
            compiled["style_result"]["style_tags"][0]["label_zh"],
            "个性鲜彩",
        )
        self.assertEqual(
            compiled["uncertain_fields"][0]["confidence"],
            next(
                element["confidence"]
                for module in compiled["design_elements"]["extended_dna_modules"]
                for element in module["elements"]
                if element["field_id"] == compiled["uncertain_fields"][0]["field_id"]
                and element["region"] == compiled["uncertain_fields"][0]["region"]
            ),
        )


if __name__ == "__main__":
    unittest.main()
