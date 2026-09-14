"""候选式模型观察协议与确定性编译器回归测试。"""

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
    """只保留模型负责的视觉、候选和不确定性字段。"""

    full = copy.deepcopy(full)
    style_result = full["style_result"]
    all_elements = [
        element
        for module in full["design_elements"]["extended_dna_modules"]
        for element in module["elements"]
    ]
    return {
        "schema_version": "design_dna_multitag_observation_v2",
        "knowledge_base_version": full["knowledge_base_version"],
        "target_object": full["target_object"],
        "image_quality": full["image_quality"],
        "active_profiles": full["module_applicability"]["active_profiles"],
        "rule_adaptations": full["module_applicability"]["rule_adaptations"],
        "style_observations": {
            "candidate_tags": [
                {
                    key: item[key]
                    for key in (
                        "style_id",
                        "match_score",
                        "confidence",
                        "regions",
                        "main_support",
                        "main_conflicts",
                    )
                }
                for item in style_result["style_candidates"]
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

        self.assertEqual(report["source_contract"], "design_dna_multitag_observation_v2")
        self.assertEqual(compiled["schema_version"], "design_dna_multitag_extraction_v1.2")
        self.assertEqual(
            [item["rank"] for item in compiled["style_result"]["style_candidates"]],
            [1, 2],
        )
        self.assertNotIn("classification_status", compiled["style_result"])
        self.assertNotIn("style_tags", compiled["style_result"])
        self.assertTrue(
            all(item["main_support"] for item in compiled["style_result"]["style_candidates"])
        )
        self.assertIn("style_result.style_candidates[0]", report["source_map"])
        self.assertLess(
            len(json.dumps(observation, ensure_ascii=False, separators=(",", ":"))),
            len(json.dumps(self.full, ensure_ascii=False, separators=(",", ":"))) * 0.75,
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_candidate_metadata_sorting_and_low_confidence_are_preserved(self) -> None:
        observation = _lean_observation(self.full)
        candidates = observation["style_observations"]["candidate_tags"]
        candidates.reverse()
        candidates[0]["confidence"] = 0.4
        candidates[0]["match_score"] = 95

        compiled, _ = _compile_model_result(observation)
        result = compiled["style_result"]["style_candidates"]

        self.assertEqual(result[0]["match_score"], 95)
        self.assertEqual(result[0]["confidence"], 0.4)
        self.assertEqual(result[0]["label_zh"], "精致克制")
        self.assertEqual(compiled["quality_summary"]["style_confidence"], 0.91)
        self._assert_compiled_result_is_valid(compiled)

    def test_valid_evidence_region_is_declared_and_source_mapped(self) -> None:
        observation = _lean_observation(self.full)
        evidence = copy.deepcopy(observation["evidence"][0])
        evidence.update(
            {
                "evidence_id": "EV-wheel-contact",
                "region": "wheel_contact",
                "description": "前后轮与地面接触区域清晰可见。",
                "bbox_norm": [0.17, 0.7, 0.81, 0.95],
            }
        )
        observation["evidence"].append(evidence)

        compiled, report = _compile_model_result(observation)

        self.assertIn("wheel_contact", compiled["target_object"]["visible_regions"])
        self.assertEqual(
            report["source_map"][f"evidence[{len(observation['evidence']) - 1}]"][
                "source_pointer"
            ],
            f"/evidence/{len(observation['evidence']) - 1}",
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_nearby_evidence_bounds_expand_target_bbox(self) -> None:
        observation = _lean_observation(self.full)
        observation["target_object"]["bbox_norm"] = [0.15, 0.04, 0.9, 0.96]

        compiled, report = _compile_model_result(observation)

        self.assertEqual(compiled["target_object"]["bbox_norm"], [0.1, 0.04, 0.9, 0.96])
        self.assertAlmostEqual(
            report["target_bbox_normalizations"][0]["max_edge_expansion"], 0.05
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_enum_single_label_wrapper_is_normalized(self) -> None:
        observation = _lean_observation(self.full)
        form_observation = next(
            item
            for item in observation["design_observations"]
            if item["field_id"] == "FORM-12"
        )
        form_observation["value"] = {"label": "几何"}

        compiled, _ = _compile_model_result(observation)
        form_element = next(
            item
            for module in compiled["design_elements"]["extended_dna_modules"]
            for item in module["elements"]
            if item["field_id"] == "FORM-12"
        )
        self.assertEqual(form_element["value"], "几何")
        self._assert_compiled_result_is_valid(compiled)

    def test_high_confidence_uncertainty_is_promoted(self) -> None:
        observation = _lean_observation(self.full)
        uncertainty = copy.deepcopy(observation["uncertainties"][0])
        uncertainty.update(
            field_id="GEO-01",
            region="whole_object",
            best_estimate=75,
            observability="observed",
            confidence=0.78,
        )
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
        self.assertEqual(
            report["observation_contract_normalizations"][0]["action"],
            "promoted_to_design_observation",
        )
        self._assert_compiled_result_is_valid(compiled)


if __name__ == "__main__":
    unittest.main()
