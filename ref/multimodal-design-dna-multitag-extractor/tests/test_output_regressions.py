"""独立验证最终结果校验器对错误样本的拒绝行为。"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_output import validate_semantics


class OutputRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        def load(relative: str):
            return json.loads((ROOT / relative).read_text(encoding="utf-8"))

        self.inputs = (
            load("examples/smartphone-rear.example.json"),
            load("examples/apparel.example.json"),
            load("examples/smartphone-red-multitag.example.json"),
            (ROOT / "references/design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8"),
            load("references/style-registry.json"),
            load("references/field-registry.json"),
            load("references/tag-relations.json"),
            load("references/style-combination-presets.json"),
        )

    def test_phone_regressions(self) -> None:
        errors: list[str] = []
        (phone, apparel, multitag, knowledge_base, style_registry,
         field_registry, tag_relations, combination_presets) = self.inputs
        forged_presets = copy.deepcopy(phone)
        forged_presets["style_result"]["derived_style_presets"] = [
            {
                "preset_id": "CyberAesthetic",
                "label_en": "Cyber Aesthetic",
                "label_zh": "赛博风格",
                "matched_style_ids": ["CyberNeon"],
            }
        ]
        mutation_errors, _ = validate_semantics(
            forged_presets,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
            combination_presets if isinstance(combination_presets, dict) else None,
        )
        if not any("must equal deterministic Python derivation" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: forged derived style preset was accepted")

        invalid_label = copy.deepcopy(phone)
        for module in invalid_label.get("design_elements", {}).get("extended_dna_modules", []):
            for element in module.get("elements", []):
                if element.get("field_id") == "DEV-05":
                    element["value"] = ["__INVALID__"]
        mutation_errors, _ = validate_semantics(
            invalid_label, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("outside the controlled domain" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: invalid multi_label value was accepted")

        # 通用表面字段不得绕过 NeoRetro 的线索族和表达角色门槛。
        generic_retro = copy.deepcopy(phone)
        neoretro = next(
            item for item in style_registry["styles"] if item.get("style_id") == "NeoRetro"
        )
        tag = generic_retro["style_result"]["style_tags"][0]
        candidate = generic_retro["style_result"]["candidate_ranking"][0]
        for item in (tag, candidate):
            item.update(
                style_id="NeoRetro",
                label_en=neoretro["display_name_en"],
                label_zh=neoretro["display_name_zh"],
                aliases=neoretro["aliases"],
                tag_kind=neoretro["tag_kind"],
                facet_ids=neoretro["facet_ids"],
            )
        tag["core_feature_hits"] = ["CMF-01：普通视觉材质候选。"]
        tag["auxiliary_feature_hits"] = ["CMF-04：普通材质对比。"]
        mutation_errors, _ = validate_semantics(
            generic_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("cue_family_policy expressive_gate requires core" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: generic NeoRetro cues were accepted")

        # 两个 cue family 不能用同一证据换字段；DET-17 必须是受控的“历史造型化”。
        same_evidence_retro = copy.deepcopy(generic_retro)
        same_evidence_retro["module_applicability"]["applicable_modules"].append(
            {
                "module_id": "DNA-M09",
                "module_name": "细节语法",
                "reason": "定向变异门禁。",
            }
        )
        same_evidence_retro["design_elements"]["extended_dna_modules"].append(
            {
                "module_id": "DNA-M09",
                "module_name": "细节语法",
                "elements": [
                    {
                        "field_id": "DET-08",
                        "field_name": "装饰线几何",
                        "source_path": "DNA-M09/DET-08",
                        "schema_source": "md_extension",
                        "value": {"role": "trim"},
                        "raw_visual_description": "可见包边轮廓。",
                        "value_type": "object",
                        "evidence_mode": "direct",
                        "region": "back_cover",
                        "applicability_status": "applicable",
                        "observability": "observed",
                        "computation_status": "not_requested",
                        "confidence": 0.9,
                        "evidence_refs": ["EV-003"],
                    },
                    {
                        "field_id": "DET-17",
                        "field_name": "细节语法角色",
                        "source_path": "DNA-M09/DET-17",
                        "schema_source": "md_extension",
                        "value": "历史造型化",
                        "raw_visual_description": "只按可见细节组合归入历史造型化语法，不推断年代。",
                        "value_type": "enum",
                        "evidence_mode": "inferred",
                        "region": "back_cover",
                        "applicability_status": "applicable",
                        "observability": "observed",
                        "computation_status": "computed",
                        "confidence": 0.9,
                        "evidence_refs": ["EV-003", "EV-004"],
                    },
                ],
            }
        )
        for module in same_evidence_retro["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "CMF-01":
                    element["confidence"] = 0.8
        same_evidence_retro["uncertain_fields"] = []
        same_evidence_retro["quality_summary"]["low_confidence_field_count"] = 0
        same_tag = same_evidence_retro["style_result"]["style_tags"][0]
        same_tag["core_feature_hits"] = [
            "CMF-01：异质视觉表面。",
            "DET-17：细节语法角色为历史造型化。",
        ]
        same_tag["auxiliary_feature_hits"] = ["DET-08：可见包边。"]
        same_tag["evidence_refs"] = ["EV-001", "EV-002", "EV-003", "EV-004"]
        mutation_errors, _ = validate_semantics(
            same_evidence_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("mutually unshared field evidence" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: NeoRetro cue families reused one evidence")

        valid_retro = copy.deepcopy(same_evidence_retro)
        valid_retro["quality_summary"]["mean_confidence"] = 0.856
        for module in valid_retro["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "DET-08":
                    element["evidence_refs"] = ["EV-002"]
        valid_errors, _ = validate_semantics(
            valid_retro, knowledge_base, style_registry, field_registry, tag_relations
        )
        if valid_errors:
            errors.append(
                "validator mutation gate failed: NeoRetro with independent surface/hardware evidence "
                f"and DET-17=历史造型化 was rejected: {valid_errors}"
            )

        wrong_expressive_role = copy.deepcopy(valid_retro)
        for module in wrong_expressive_role["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "DET-17":
                    element["value"] = "当代技术化"
        mutation_errors, _ = validate_semantics(
            wrong_expressive_role, knowledge_base, style_registry, field_registry, tag_relations
        )
        if not any("cue_family_policy expressive_gate requires core" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: NeoRetro accepted a non-historical DET-17 role")

        self.assertEqual(errors, [])

    def test_apparel_regressions(self) -> None:
        errors: list[str] = []
        (phone, apparel, multitag, knowledge_base, style_registry,
         field_registry, tag_relations, combination_presets) = self.inputs
        missing_dependency = copy.deepcopy(apparel)
        modules = missing_dependency.get("design_elements", {}).get("extended_dna_modules", [])
        color_module = next((item for item in modules if item.get("module_id") == "DNA-M06"), None)
        if isinstance(color_module, dict):
            color_module.setdefault("elements", []).append(
                {
                    "field_id": "CLR-20",
                    "field_name": "调色板结构",
                    "source_path": "DNA-M06/CLR-20",
                    "schema_source": "md_extension",
                    "value": "单主色",
                    "raw_visual_description": "仅由已有主色记录直接推导。",
                    "value_type": "enum",
                    "evidence_mode": "derived",
                    "region": "whole_object",
                    "applicability_status": "applicable",
                    "observability": "observed",
                    "computation_status": "computed",
                    "confidence": 0.9,
                    "evidence_refs": ["EV-003"],
                }
            )
            mutation_errors, _ = validate_semantics(
                missing_dependency, knowledge_base, style_registry, field_registry, tag_relations
            )
            if not any("missing usable derived sources" in item for item in mutation_errors):
                errors.append("validator mutation gate failed: derived field without sources was accepted")

        self.assertEqual(errors, [])

    def test_multitag_regressions(self) -> None:
        errors: list[str] = []
        (phone, apparel, multitag, knowledge_base, style_registry,
         field_registry, tag_relations, combination_presets) = self.inputs
        def require_semantic_rejection(
            gate_name: str,
            payload: dict[str, Any],
            expected_fragment: str,
            *,
            styles: dict[str, Any] = style_registry,
            relations: dict[str, Any] = tag_relations,
        ) -> None:
            mutation_errors, _ = validate_semantics(
                payload,
                knowledge_base,
                styles,
                field_registry,
                relations,
            )
            if not any(expected_fragment in item for item in mutation_errors):
                errors.append(f"validator mutation gate failed: {gate_name} was accepted")

        outside_evidence = copy.deepcopy(multitag)
        outside_evidence["evidence"][0]["region"] = "__OUTSIDE_VISIBLE_REGIONS__"
        require_semantic_rejection(
            "evidence region outside visible_regions",
            outside_evidence,
            "outside target_object.visible_regions",
        )

        outside_element = copy.deepcopy(multitag)
        outside_element["design_elements"]["extended_dna_modules"][0]["elements"][0][
            "region"
        ] = "__OUTSIDE_VISIBLE_REGIONS__"
        require_semantic_rejection(
            "design-element region outside visible_regions",
            outside_element,
            "outside target_object.visible_regions",
        )

        low_style_confidence = copy.deepcopy(multitag)
        low_style_confidence["style_result"]["style_tags"][0]["confidence"] = 0.74
        low_style_confidence["style_result"]["candidate_ranking"][0]["confidence"] = 0.74
        require_semantic_rejection(
            "confirmed confidence below 0.75",
            low_style_confidence,
            "confidence must be >= 0.75",
        )

        low_core_confidence = copy.deepcopy(multitag)
        for module in low_core_confidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "CLR-01":
                    element["confidence"] = 0.74
        require_semantic_rejection(
            "confirmed style citing a low-confidence core DNA field",
            low_core_confidence,
            "CLR-01 confidence must be >=0.75 to support a confirmed style",
        )

        hard_pass_without_conflict = copy.deepcopy(multitag)
        rejected = hard_pass_without_conflict["style_result"]["candidate_ranking"][2]
        rejected["hard_rule_passed"] = True
        rejected["main_conflicts"] = []
        require_semantic_rejection(
            "non-confirmed hard pass without pair conflict",
            hard_pass_without_conflict,
            "requires non-empty main_conflicts",
        )

        unstable_tags = copy.deepcopy(multitag)
        unstable_tags["style_result"]["style_tags"].reverse()
        require_semantic_rejection(
            "unstable style-tag ordering",
            unstable_tags,
            "must use stable order (-dominance, -match_score, style_id)",
        )

        unstable_candidates = copy.deepcopy(multitag)
        unstable_candidates["style_result"]["candidate_ranking"][2]["match_score"] = 50
        unstable_candidates["style_result"]["candidate_ranking"][3]["match_score"] = 50
        require_semantic_rejection(
            "unstable candidate tie ordering",
            unstable_candidates,
            "must use stable order (-match_score, style_id)",
        )

        # 构造同区域、同冲突 facet、但 core 字段不同的条件关系，防止字段 ID 绕过互斥。
        conflict_case = copy.deepcopy(multitag)
        conflict_styles = copy.deepcopy(style_registry)
        refined_record = next(
            item
            for item in conflict_styles["styles"]
            if item.get("style_id") == "RefinedMinimalism"
        )
        refined_record["facet_ids"].append("color_optics")
        conflict_case["style_result"]["style_tags"][1]["facet_ids"].append("color_optics")
        conflict_case["style_result"]["candidate_ranking"][1]["facet_ids"].append(
            "color_optics"
        )
        conflict_relations = copy.deepcopy(tag_relations)
        conflict_relation = next(
            item
            for item in conflict_relations["pair_relations"]
            if set(item.get("style_ids", [])) == {"RefinedMinimalism", "SaturatedBold"}
        )
        conflict_relation.update(
            relation="conditional",
            scope="same_region_same_mechanism",
            conflict_facet_ids=["color_optics"],
            same_region_coexistence="forbidden",
        )
        conflict_case["style_result"]["pairwise_arbitrations"][0].update(
            relation="conditional",
            scope="same_region_same_mechanism",
        )
        require_semantic_rejection(
            "overlapping conditional conflict facet",
            conflict_case,
            "same_region_coexistence=forbidden",
            styles=conflict_styles,
            relations=conflict_relations,
        )

        independent_case = copy.deepcopy(conflict_case)
        independent_relations = copy.deepcopy(conflict_relations)
        independent_relation = next(
            item
            for item in independent_relations["pair_relations"]
            if set(item.get("style_ids", [])) == {"RefinedMinimalism", "SaturatedBold"}
        )
        independent_relation["same_region_coexistence"] = "independent_evidence"
        independent_errors, _ = validate_semantics(
            independent_case,
            knowledge_base,
            conflict_styles,
            field_registry,
            independent_relations,
        )
        if independent_errors:
            errors.append(
                "validator mutation gate failed: same-region conditional pair with independent "
                "core evidence was rejected"
            )

        reused_core_evidence = copy.deepcopy(independent_case)
        for module in reused_core_evidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") in {"DEV-03", "DEV-05"}:
                    element["evidence_refs"] = ["EV-003"]
        require_semantic_rejection(
            "same-region conditional pair reusing core evidence",
            reused_core_evidence,
            "mutually exclusive core field evidence",
            styles=conflict_styles,
            relations=independent_relations,
        )

        # 未显式登记且 facet 无交集的同区组合仍须执行默认独立证据门，不能换字段复用证据。
        default_reused_evidence = copy.deepcopy(multitag)
        default_relations = copy.deepcopy(tag_relations)
        default_relations["pair_relations"] = [
            relation
            for relation in default_relations["pair_relations"]
            if set(relation.get("style_ids", [])) != {"RefinedMinimalism", "SaturatedBold"}
        ]
        default_reused_evidence["style_result"]["pairwise_arbitrations"][0].update(
            relation="conditional",
            scope="same_region_same_mechanism",
        )
        for module in default_reused_evidence["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") in {"DEV-03", "DEV-05"}:
                    element["evidence_refs"] = ["EV-003"]
        require_semantic_rejection(
            "default same-region pair reusing core evidence across different fields",
            default_reused_evidence,
            "mutually exclusive core field evidence",
            relations=default_relations,
        )

        allowed_hard_pass = copy.deepcopy(multitag)
        allowed_candidate = allowed_hard_pass["style_result"]["candidate_ranking"][2]
        allowed_candidate["hard_rule_passed"] = True
        allowed_candidate["main_conflicts"] = ["与已确认标签存在成对冲突"]
        allowed_errors, _ = validate_semantics(
            allowed_hard_pass,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
        )
        if allowed_errors:
            errors.append(
                "validator mutation gate failed: non-confirmed hard pass with conflict was rejected"
            )

        zero_rule_tag = copy.deepcopy(multitag)
        zero_rule_tag["style_result"]["style_tags"][0]["rule_coverage"].update(
            applicable_rule_count=0,
            passed_rule_count=0,
        )
        require_semantic_rejection(
            "confirmed tag with zero applicable rules",
            zero_rule_tag,
            "applicable_rule_count>=1 and passed_rule_count>=1",
        )

        self.assertEqual(errors, [])

    def test_single_dominance_regressions(self) -> None:
        errors: list[str] = []
        (phone, apparel, multitag, knowledge_base, style_registry,
         field_registry, tag_relations, combination_presets) = self.inputs
        invalid_single_dominance = copy.deepcopy(phone)
        invalid_single_dominance["style_result"]["style_tags"][0]["dominance"] = 0.9
        invalid_single_dominance["style_result"]["candidate_ranking"][0]["dominance"] = 0.9
        mutation_errors, _ = validate_semantics(
            invalid_single_dominance,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
        )
        if not any("single confirmed tag requires dominance=1" in item for item in mutation_errors):
            errors.append("validator mutation gate failed: single-tag dominance below 1 was accepted")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
