"""精简模型观察协议与确定性编译器回归测试。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.dna.extraction import (
    _apply_style_semantic_review,
    _compile_model_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / "ref" / "multimodal-design-dna-multitag-extractor"
EXAMPLE_PATH = SKILL_ROOT / "examples" / "smartphone-red-multitag.example.json"


def _lean_observation(full: dict) -> dict:
    """只保留模型需要判断的视觉/语义字段，模拟 observation_v1 输出。"""

    full = copy.deepcopy(full)
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
        nested_element_mappings = {
            path: mapping
            for path, mapping in report["source_map"].items()
            if path.startswith("design_elements.extended_dna_modules.")
        }
        self.assertEqual(
            len(nested_element_mappings),
            sum(
                len(module["elements"])
                for module in compiled["design_elements"]["extended_dna_modules"]
            ),
        )
        self.assertIn(
            "/design_observations/0",
            {
                mapping["source_pointer"]
                for mapping in nested_element_mappings.values()
            },
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

    def test_valid_evidence_region_is_declared_and_source_mapped(self) -> None:
        """证据已明确圈定的区域不应因主体清单漏登记而触发整轮模型修复。"""

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
        self.assertNotIn(
            "wheel_contact",
            observation["target_object"]["visible_regions"],
        )

        compiled, report = _compile_model_result(observation)

        self.assertIn("wheel_contact", compiled["target_object"]["visible_regions"])
        self.assertEqual(
            report["visible_region_normalizations"],
            [
                {
                    "source_pointer": f"/evidence/{len(observation['evidence']) - 1}/region",
                    "evidence_id": "EV-wheel-contact",
                    "region": "wheel_contact",
                    "action": "declared_from_valid_evidence",
                }
            ],
        )
        self.assertEqual(
            report["source_map"][f"evidence[{len(observation['evidence']) - 1}]"],
            {
                "source_pointer": f"/evidence/{len(observation['evidence']) - 1}",
                "evidence_id": "EV-wheel-contact",
                "region": "wheel_contact",
            },
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_nearby_evidence_bounds_expand_target_bbox(self) -> None:
        """证据框仅因坐标取整轻微越界时由宿主扩大主体框。"""

        observation = _lean_observation(self.full)
        observation["target_object"]["bbox_norm"] = [0.15, 0.04, 0.9, 0.96]

        compiled, report = _compile_model_result(observation)

        self.assertEqual(
            compiled["target_object"]["bbox_norm"],
            [0.1, 0.04, 0.9, 0.96],
        )
        normalization = report["target_bbox_normalizations"][0]
        self.assertEqual(
            normalization["action"],
            "expanded_to_nearby_evidence_bounds",
        )
        self.assertAlmostEqual(normalization["max_edge_expansion"], 0.05)
        self._assert_compiled_result_is_valid(compiled)

    def test_enum_single_label_wrapper_is_normalized_without_model_repair(self) -> None:
        """合法枚举的单键 label 包装属于机械格式差异，应由宿主安全展开。"""

        observation = _lean_observation(self.full)
        form_observation = next(
            item
            for item in observation["design_observations"]
            if item["field_id"] == "FORM-12"
        )
        form_observation["value"] = {"label": "几何"}

        compiled, report = _compile_model_result(observation)
        form_element = next(
            item
            for module in compiled["design_elements"]["extended_dna_modules"]
            for item in module["elements"]
            if item["field_id"] == "FORM-12"
        )

        self.assertEqual(form_element["value"], "几何")
        self.assertTrue(
            any(
                item["field_id"] == "FORM-12"
                and "枚举单键包装" in item["notes"][0]
                for item in report["value_normalizations"]
            )
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_outside_evidence_bbox_does_not_expand_visible_regions(self) -> None:
        """主体框外证据不能借区域同步绕过最终空间校验。"""

        observation = _lean_observation(self.full)
        evidence = copy.deepcopy(observation["evidence"][0])
        evidence.update(
            {
                "evidence_id": "EV-outside-region",
                "region": "outside_region",
                "description": "用于验证空间边界的证据。",
                "bbox_norm": [0, 0, 1, 1],
            }
        )
        observation["evidence"].append(evidence)

        compiled, report = _compile_model_result(observation)

        self.assertEqual(
            compiled["target_object"]["bbox_norm"],
            observation["target_object"]["bbox_norm"],
        )
        self.assertNotIn(
            "outside_region",
            compiled["target_object"]["visible_regions"],
        )
        self.assertEqual(report["visible_region_normalizations"], [])

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

        self.assertEqual(compiled["style_result"]["classification_status"], "confirmed")
        self.assertEqual(
            [item["style_id"] for item in compiled["style_result"]["style_tags"]],
            ["SaturatedBold"],
        )
        self.assertEqual(len(report["style_downgrades"]), 1)
        self.assertTrue(
            any(
                item["style_id"] == "SaturatedBold"
                and item["field_ids"] == ["CMP-13"]
                for item in report["auto_linked_style_hits"]
            )
        )
        demoted = {
            item["style_id"]: item
            for item in compiled["style_result"]["candidate_ranking"]
            if item["style_id"] in {"SaturatedBold", "RefinedMinimalism"}
        }
        self.assertTrue(demoted["SaturatedBold"]["hard_rule_passed"])
        self.assertFalse(demoted["RefinedMinimalism"]["hard_rule_passed"])
        self._assert_compiled_result_is_valid(compiled)

    def test_value_rules_build_saturated_bold_evidence_without_model_hits(self) -> None:
        """明确的高彩大面积主色和色彩对比应由宿主自动建立证据链。"""

        observation = _lean_observation(self.full)
        tag = observation["style_observations"]["confirmed_tags"][0]
        for key in (
            "applicable_rule_count",
            "not_applicable_rule_count",
            "core_feature_hits",
            "auxiliary_feature_hits",
        ):
            tag.pop(key, None)
        observation["style_observations"]["confirmed_tags"] = [tag]
        observation["style_observations"]["pairwise_reasoning"] = []

        compiled, report = _compile_model_result(observation)

        self.assertEqual(compiled["style_result"]["classification_status"], "confirmed")
        style = compiled["style_result"]["style_tags"][0]
        self.assertIn("CLR-10", style["core_feature_hits"][0])
        self.assertIn("CLR-04", style["core_feature_hits"][0])
        self.assertIn("CMP-13", style["auxiliary_feature_hits"][0])
        self.assertEqual(len(report["auto_linked_style_hits"]), 2)
        self.assertFalse(report.get("semantic_review_requests"))
        self._assert_compiled_result_is_valid(compiled)

    def test_ambiguous_missing_links_request_narrow_semantic_review(self) -> None:
        """无安全值级规则时只提交当前风格的少量强字段，并接受高置信复核挂接。"""

        observation = _lean_observation(self.full)
        tag = observation["style_observations"]["confirmed_tags"][1]
        for key in (
            "applicable_rule_count",
            "not_applicable_rule_count",
            "core_feature_hits",
            "auxiliary_feature_hits",
        ):
            tag.pop(key, None)
        observation["style_observations"]["confirmed_tags"] = [tag]
        observation["style_observations"]["pairwise_reasoning"] = []

        compiled, report = _compile_model_result(observation)

        self.assertEqual(compiled["style_result"]["classification_status"], "unclassified")
        requests = report["semantic_review_requests"]
        self.assertEqual([item["style_id"] for item in requests], ["RefinedMinimalism"])
        self.assertEqual(set(requests[0]["roles"]), {"core", "auxiliary"})
        self.assertIn(
            "DEV-03",
            {item["field_id"] for item in requests[0]["roles"]["core"]},
        )
        self.assertIn(
            "CMP-09",
            {item["field_id"] for item in requests[0]["roles"]["auxiliary"]},
        )

        reviewed, decisions, accepted_count = _apply_style_semantic_review(
            observation,
            requests,
            {
                "decisions": [
                    {
                        "style_id": "RefinedMinimalism",
                        "role": "core",
                        "field_ids": ["DEV-03", "DEV-05"],
                        "supports": True,
                        "confidence": 0.9,
                        "reason": "纵向镜头秩序可支持受控精致增量。",
                    },
                    {
                        "style_id": "RefinedMinimalism",
                        "role": "auxiliary",
                        "field_ids": ["CMP-09"],
                        "supports": True,
                        "confidence": 0.88,
                        "reason": "大面积低信息留白构成独立辅助机制。",
                    },
                ]
            },
        )
        recompiled, second_report = _compile_model_result(reviewed)

        self.assertEqual(accepted_count, 3)
        self.assertTrue(all(item["accepted"] for item in decisions))
        self.assertEqual(
            recompiled["style_result"]["classification_status"], "confirmed"
        )
        self.assertFalse(second_report.get("semantic_review_requests"))
        self._assert_compiled_result_is_valid(recompiled)

    def test_weak_extra_style_hit_is_pruned_without_demotion(self) -> None:
        """额外弱引用不应拖垮已经由强决定与辅助证据闭环的风格。"""

        observation = _lean_observation(self.full)
        observation["style_observations"]["confirmed_tags"][0][
            "core_feature_hits"
        ].append("CMF-01：低置信材质候选")

        compiled, report = _compile_model_result(observation)

        self.assertEqual(
            {item["style_id"] for item in compiled["style_result"]["style_tags"]},
            {"SaturatedBold", "RefinedMinimalism"},
        )
        self.assertTrue(
            any(
                item["style_id"] == "SaturatedBold"
                and item["field_ids"] == ["CMF-01"]
                for item in report["pruned_style_hits"]
            )
        )
        self.assertIn(
            "CMF-01",
            {item["field_id"] for item in compiled["uncertain_fields"]},
        )
        self.assertNotIn(
            "CMF-01",
            " ".join(
                compiled["style_result"]["style_tags"][0]["core_feature_hits"]
            ),
        )
        self._assert_compiled_result_is_valid(compiled)

    def test_pruning_cannot_bypass_neoretro_expressive_gate(self) -> None:
        """即使普通决定/辅助字段充分，特殊必需门槛缺失仍必须降级。"""

        observation = _lean_observation(self.full)
        observation["design_observations"].append(
            {
                "field_id": "DET-08",
                "value": {"geometry": "直"},
                "raw_visual_description": "背板存在一条直线装饰",
                "region": "back_cover",
                "observability": "observed",
                "confidence": 0.9,
                "evidence_refs": ["EV-004"],
            }
        )
        tag = copy.deepcopy(observation["style_observations"]["confirmed_tags"][0])
        tag.update(
            {
                "style_id": "NeoRetro",
                "match_score": 80,
                "confidence": 0.82,
                "dominance": 1,
                "regions": ["back_cover"],
                "core_feature_hits": ["CLR-01：高饱和红色背板"],
                "auxiliary_feature_hits": ["DET-08：直线装饰"],
            }
        )
        styles = observation["style_observations"]
        styles["classification_status"] = "confirmed"
        styles["confirmed_tags"] = [tag]
        styles["pairwise_reasoning"] = []
        styles["composition_summary"] = "红色与装饰线形成复古候选。"

        compiled, report = _compile_model_result(observation)

        self.assertEqual(compiled["style_result"]["classification_status"], "unclassified")
        self.assertEqual(compiled["style_result"]["style_tags"], [])
        downgrade = next(
            item
            for item in report["style_downgrades"]
            if item["style_id"] == "NeoRetro"
        )
        self.assertTrue(
            any("DET-17" in reason for reason in downgrade["reasons"])
        )
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
