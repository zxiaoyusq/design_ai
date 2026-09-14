"""候选式最终结果的语义校验回归。"""
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

        self.phone = load("examples/smartphone-rear.example.json")
        self.multitag = load("examples/smartphone-red-multitag.example.json")
        self.knowledge_base = (
            ROOT / "references/design-dna-knowledge-base.zh-CN.md"
        ).read_text(encoding="utf-8")
        self.style_registry = load("references/style-registry.json")
        self.field_registry = load("references/field-registry.json")
        self.tag_relations = load("references/tag-relations.json")
        self.combination_presets = load("references/style-combination-presets.json")

    def validate(self, payload: dict) -> list[str]:
        errors, _ = validate_semantics(
            payload,
            self.knowledge_base,
            self.style_registry,
            self.field_registry,
            self.tag_relations,
            self.combination_presets,
        )
        return errors

    def test_candidate_contract_regressions(self) -> None:
        forged_presets = copy.deepcopy(self.phone)
        forged_presets["style_result"]["derived_style_presets"] = [
            {
                "preset_id": "CyberAesthetic",
                "label_en": "Cyber Aesthetic",
                "label_zh": "赛博风格",
                "matched_style_ids": ["CyberNeon"],
            }
        ]
        self.assertTrue(
            any(
                "must equal deterministic Python derivation" in item
                for item in self.validate(forged_presets)
            )
        )

        low_confidence = copy.deepcopy(self.phone)
        low_confidence["style_result"]["style_candidates"][0]["confidence"] = 0.4
        low_confidence["quality_summary"]["style_confidence"] = 0.4
        self.assertEqual(self.validate(low_confidence), [])

        missing_support = copy.deepcopy(self.phone)
        missing_support["style_result"]["style_candidates"][0]["main_support"] = []
        self.assertTrue(
            any("visible support" in item for item in self.validate(missing_support))
        )

        outside_region = copy.deepcopy(self.phone)
        outside_region["style_result"]["style_candidates"][0]["regions"] = [
            "__OUTSIDE_VISIBLE_REGIONS__"
        ]
        self.assertTrue(
            any(
                "outside target_object.visible_regions" in item
                for item in self.validate(outside_region)
            )
        )

        unstable = copy.deepcopy(self.multitag)
        unstable["style_result"]["style_candidates"].reverse()
        self.assertTrue(
            any("stable order" in item for item in self.validate(unstable))
        )

        duplicate = copy.deepcopy(self.phone)
        duplicate["style_result"]["style_candidates"].append(
            copy.deepcopy(duplicate["style_result"]["style_candidates"][0])
        )
        duplicate["style_result"]["style_candidates"][1]["rank"] = 2
        self.assertTrue(
            any("style_id values must be unique" in item for item in self.validate(duplicate))
        )

        legacy = copy.deepcopy(self.phone)
        legacy["style_result"]["classification_status"] = "confirmed"
        self.assertTrue(
            any("legacy field 'classification_status'" in item for item in self.validate(legacy))
        )

    def test_field_contract_regressions(self) -> None:
        invalid_label = copy.deepcopy(self.phone)
        for module in invalid_label["design_elements"]["extended_dna_modules"]:
            for element in module.get("elements", []):
                if element.get("field_id") == "DEV-05":
                    element["value"] = ["__INVALID__"]
        self.assertTrue(
            any("outside the controlled domain" in item for item in self.validate(invalid_label))
        )

        outside_evidence = copy.deepcopy(self.multitag)
        outside_evidence["evidence"][0]["region"] = "__OUTSIDE_VISIBLE_REGIONS__"
        self.assertTrue(
            any(
                "outside target_object.visible_regions" in item
                for item in self.validate(outside_evidence)
            )
        )


if __name__ == "__main__":
    unittest.main()
