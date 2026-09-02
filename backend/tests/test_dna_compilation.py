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

    def test_field_gate_value_normalization_and_uncertainty_mirroring(self) -> None:
        """覆盖罐体样例暴露的视角、Profile、值域、序数和低置信错误。"""

        observation = _lean_observation(self.full)
        evidence_a = observation["evidence"][0]["evidence_id"]
        evidence_b = observation["evidence"][1]["evidence_id"]
        base = {
            "raw_visual_description": "回归测试观察",
            "region": "whole_object",
            "observability": "observed",
            "confidence": 0.9,
            "evidence_refs": [evidence_a],
        }
        observation["design_observations"].extend(
            [
                {**base, "field_id": "FORM-05", "value": "连续"},
                {**base, "field_id": "TEX-08", "value": {}},
                {
                    **base,
                    "field_id": "HUM-03",
                    "value": "高",
                    "evidence_refs": [evidence_a, evidence_b],
                },
                {
                    **base,
                    "field_id": "PRT-03",
                    "value": [
                        "图文区—包含—中央文字",
                        "外围边框—包围—中央图文区",
                        "罐身—承载—中央图文区",
                    ],
                },
                {**base, "field_id": "PRT-08", "value": "镜像"},
                {
                    **base,
                    "field_id": "IMG-03",
                    "value": [{"label": "未来", "strength": 62}],
                    "evidence_refs": [evidence_a, evidence_b],
                },
            ]
        )
        for item in observation["design_observations"]:
            if item["field_id"] == "SEM-01":
                item["value"] = 62
            if item["field_id"] == "GEO-01":
                item["confidence"] = 0.62
        observation["uncertainties"] = [
            item
            for item in observation["uncertainties"]
            if item["field_id"] != "GEO-01"
        ]

        compiled, report = _compile_model_result(observation)
        elements = {
            item["field_id"]: item
            for module in compiled["design_elements"]["extended_dna_modules"]
            for item in module["elements"]
        }

        self.assertTrue(
            {"FORM-05", "TEX-08", "HUM-03"}.issubset(
                {item["field_id"] for item in report["filtered_fields"]}
            )
        )
        self.assertEqual(elements["PRT-03"]["value"], ["包含", "包围", "承载"])
        self.assertIsNone(elements["PRT-08"]["value"])
        self.assertEqual(elements["SEM-01"]["value"], 50)
        self.assertEqual(elements["IMG-03"]["value"][0]["strength"], 50)
        uncertain_ids = {item["field_id"] for item in compiled["uncertain_fields"]}
        self.assertIn("GEO-01", uncertain_ids)
        self.assertIn("PRT-08", uncertain_ids)
        self._assert_compiled_result_is_valid(compiled)

    def test_invalid_style_evidence_is_reclassified_or_demoted(self) -> None:
        """覆盖微型车样例中的字段角色、缺值和无区域证据错误。"""

        observation = _lean_observation(self.full)
        first, second = observation["style_observations"]["confirmed_tags"]
        first["auxiliary_feature_hits"] = [
            "CLR-13：面积色彩",
            "CMF-07：表面统一",
        ]
        first["regions"] = ["back_cover", "front_nose"]
        second["core_feature_hits"] = ["FORM-01：圆润轮廓"]
        second["auxiliary_feature_hits"] = [
            "GEO-12：低姿态",
            "FORM-14：均匀曲率",
            "PRT-13：功能组件",
        ]

        compiled, report = _compile_model_result(observation)

        self.assertEqual(compiled["style_result"]["classification_status"], "unclassified")
        self.assertEqual(compiled["style_result"]["style_tags"], [])
        self.assertEqual(len(report["style_downgrades"]), 2)
        demoted = {
            item["style_id"]: item
            for item in compiled["style_result"]["candidate_ranking"]
            if item["style_id"] in {"SaturatedBold", "RefinedMinimalism"}
        }
        self.assertFalse(demoted["SaturatedBold"]["hard_rule_passed"])
        self.assertFalse(demoted["RefinedMinimalism"]["hard_rule_passed"])
        self._assert_compiled_result_is_valid(compiled)

    def test_high_confidence_uncertainty_is_promoted_without_model_repair(self) -> None:
        """模型把高置信观察误放入 uncertainties 时由宿主机械归类。"""

        observation = _lean_observation(self.full)
        uncertainty = copy.deepcopy(observation["uncertainties"][0])
        uncertainty["field_id"] = "GEO-01"
        uncertainty["region"] = "whole_object"
        uncertainty["best_estimate"] = 75
        uncertainty["observability"] = "observed"
        uncertainty["confidence"] = 0.78
        observation["uncertainties"] = [uncertainty]
        observation["design_observations"] = [
            item
            for item in observation["design_observations"]
            if item["field_id"] != "GEO-01"
        ]

        compiled, report = _compile_model_result(observation)
        elements = {
            item["field_id"]: item
            for module in compiled["design_elements"]["extended_dna_modules"]
            for item in module["elements"]
        }

        self.assertEqual(elements["GEO-01"]["value"], 75)
        self.assertEqual(elements["GEO-01"]["confidence"], 0.78)
        self.assertNotIn(
            "GEO-01",
            {item["field_id"] for item in compiled["uncertain_fields"]},
        )
        self.assertEqual(
            report["observation_contract_normalizations"][0]["action"],
            "promoted_to_design_observation",
        )
        self._assert_compiled_result_is_valid(compiled)

    def _assert_compiled_result_is_valid(self, compiled: dict) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            compiled_path = Path(temporary_directory) / "compiled.json"
            final_path = Path(temporary_directory) / "final.json"
            compiled_path.write_text(
                json.dumps(compiled, ensure_ascii=False), encoding="utf-8"
            )
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


if __name__ == "__main__":
    unittest.main()
