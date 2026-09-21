"""验证脚本重构后的保存边界和共用规则，不依赖后端或模型服务。"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import save_result
from compile_fields import _normalized_controlled_value
from compile_model_output import (
    _fill_observation_descriptions,
    _normalize_observation_root_aliases,
    compile_model_output,
)
from derive_style_presets import write_derived_style_presets
from dna_rules import extract_kb_value_spaces, view_requirement_satisfied
from validation_rules import load_json


class ScriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(
            (ROOT / "examples/smartphone-red-multitag.example.json").read_text()
        )
        self.compiled, _ = compile_model_output(self.payload)
        self.presets = json.loads(
            (ROOT / "references/style-combination-presets.json").read_text()
        )

    def save(self, payload: dict, directory: Path, *, compiled: bool) -> int:
        arguments = [
            "-", "--image", "test.jpg", "--output-dir", str(directory),
            "--timestamp", "20260906_120000",
        ]
        if compiled:
            arguments.append("--compiled")
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            return save_result.main(arguments)

    def test_compiled_save_preserves_result_without_recompiling(self) -> None:
        expected = copy.deepcopy(self.compiled)
        write_derived_style_presets(expected, self.presets)
        with tempfile.TemporaryDirectory() as directory, patch(
            "save_result.compile_model_output", side_effect=AssertionError("重复编译")
        ):
            target = Path(directory)
            self.assertEqual(self.save(self.compiled, target, compiled=True), 0)
            saved = json.loads(next(target.glob("*.json")).read_text())
            self.assertEqual(saved, expected)

    def test_default_save_still_compiles_once(self) -> None:
        self.payload["quality_summary"]["mean_confidence"] = -1
        with tempfile.TemporaryDirectory() as directory, patch(
            "save_result.compile_model_output", wraps=compile_model_output
        ) as compiler:
            target = Path(directory)
            self.assertEqual(self.save(self.payload, target, compiled=False), 0)
            compiler.assert_called_once()
            saved = json.loads(next(target.glob("*.json")).read_text())
            self.assertEqual(
                saved["quality_summary"]["mean_confidence"],
                self.compiled["quality_summary"]["mean_confidence"],
            )

    def test_compiled_save_rejects_invalid_statistics_without_repair(self) -> None:
        self.compiled["quality_summary"]["mean_confidence"] = 0
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(self.save(self.compiled, target, compiled=True), 2)
            self.assertEqual(list(target.iterdir()), [])

    def test_compiled_save_rejects_non_final_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(self.save({"schema_version": "unknown"}, target, compiled=True), 2)
            self.assertEqual(list(target.iterdir()), [])

    def test_compiled_save_overwrites_forged_presets(self) -> None:
        self.compiled["style_result"]["derived_style_presets"] = [{"preset_id": "forged"}]
        expected = copy.deepcopy(self.compiled)
        write_derived_style_presets(expected, self.presets)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(self.save(self.compiled, target, compiled=True), 0)
            self.assertEqual(json.loads(next(target.glob("*.json")).read_text()), expected)

    def test_json_readers_reject_nonfinite_numbers(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                raw = '{"value":' + constant + '}'
                with self.assertRaises(ValueError):
                    save_result._strict_json_loads(raw)
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "invalid.json"
                    source.write_text(raw)
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        load_json(source)

    def test_controlled_domains_share_separator_rules(self) -> None:
        for separator in ("、", ",", "，"):
            with self.subTest(separator=separator):
                kb = "| TEX-01 | 类型：甲" + separator + "乙；enum | x | x | x |"
                self.assertEqual(extract_kb_value_spaces(kb), {"TEX-01": ("enum", {"甲", "乙"})})

    def test_view_rules_keep_side_and_missing_view_boundaries(self) -> None:
        self.assertTrue(view_requirement_satisfied(["side"], "side"))
        self.assertTrue(view_requirement_satisfied(["side"], "left"))
        self.assertTrue(view_requirement_satisfied(["side"], "right"))
        self.assertFalse(view_requirement_satisfied(["side"], "front"))
        self.assertFalse(view_requirement_satisfied(["rear"], "unknown"))
        self.assertTrue(view_requirement_satisfied(["any"], "unknown"))

    def test_root_camel_case_aliases_are_only_normalized_without_conflict(self) -> None:
        notes = {"missing_critical_fields": [], "warnings": [], "concise_summary": "ok"}
        quality = {"overall_quality": 0.8}
        payload = {"imageQuality": quality, "qualityNotes": notes}
        report = {"changed_paths": []}

        _normalize_observation_root_aliases(payload, report)

        self.assertEqual(
            payload,
            {"image_quality": quality, "quality_notes": notes},
        )
        self.assertEqual(
            [item["target_pointer"] for item in report["property_alias_normalizations"]],
            ["/image_quality", "/quality_notes"],
        )

        conflicting = {
            "qualityNotes": notes,
            "quality_notes": {"warnings": ["different"]},
        }
        _normalize_observation_root_aliases(conflicting, {"changed_paths": []})
        self.assertIn("qualityNotes", conflicting)

    def test_existing_value_description_fills_missing_observation_description(self) -> None:
        payload = {
            "design_observations": [
                {
                    "field_id": "GEO-08",
                    "value": {"label": "强", "description": "半球罩明显向上隆起"},
                }
            ]
        }
        report = {"changed_paths": []}

        _fill_observation_descriptions(payload, report)

        self.assertEqual(
            payload["design_observations"][0]["raw_visual_description"],
            "半球罩明显向上隆起",
        )
        self.assertEqual(
            report["observation_description_normalizations"][0]["action"],
            "copied_existing_description",
        )

    def test_english_ordinal_strength_aliases_map_to_registered_buckets(self) -> None:
        normalization = json.loads(
            (ROOT / "references/value-normalization.json").read_text()
        )
        value = [
            {"label": "轻", "strength": "low"},
            {"label": "中", "strength": "medium"},
            {"label": "强", "strength": "high"},
        ]

        normalized, _ = _normalized_controlled_value(
            "IMG-03",
            {"unit": "label+ordinal_strength"},
            value,
            {},
            normalization,
        )

        self.assertEqual(
            [item["strength"] for item in normalized],
            [25, 50, 75],
        )

    def test_side_view_and_mechanical_field_errors_are_compiled_in_code(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["target_object"]["view"] = "side"
        for evidence in payload["evidence"]:
            evidence["view"] = "side"

        modules = {
            module["module_id"]: module
            for module in payload["design_elements"]["extended_dna_modules"]
        }

        def append_element(module_id: str, element: dict) -> None:
            module = modules.get(module_id)
            if module is None:
                module = {"module_id": module_id, "module_name": "", "elements": []}
                modules[module_id] = module
                payload["design_elements"]["extended_dna_modules"].append(module)
            module["elements"].append(element)

        evidence_refs = [payload["evidence"][0]["evidence_id"]]
        append_element(
            "DNA-M01",
            {
                "field_id": "GEO-03",
                "value": {"label": "中", "ratio": None},
                "raw_visual_description": "侧视但厚度不可可靠计算。",
                "region": "whole_object",
                "observability": "not_observable",
                "confidence": 0.3,
                "evidence_refs": evidence_refs,
            },
        )
        append_element(
            "DNA-M04",
            {
                "field_id": "PRT-01",
                "value": "可见多个组件，但不能写成结构化清单。",
                "raw_visual_description": "只有概括描述。",
                "region": "back_cover",
                "observability": "observed",
                "confidence": 0.6,
                "evidence_refs": evidence_refs,
            },
        )
        append_element(
            "DNA-M09",
            {
                "field_id": "DET-13",
                "value": "低",
                "raw_visual_description": "缺少注册表要求的完整派生源。",
                "region": "whole_object",
                "observability": "observed",
                "confidence": 0.76,
                "evidence_refs": evidence_refs,
            },
        )
        append_element(
            "DNA-M14",
            {
                "field_id": "IMG-03",
                "value": [
                    {"label": "轻快", "ordinal_strength": 70},
                    {"label": "怀旧", "ordinal_strength": 55},
                ],
                "raw_visual_description": "由两条独立观察支持。",
                "region": "whole_object",
                "observability": "observed",
                "confidence": 0.68,
                "evidence_refs": [
                    payload["evidence"][0]["evidence_id"],
                    payload["evidence"][1]["evidence_id"],
                ],
            },
        )

        compiled, report = compile_model_output(payload)
        write_derived_style_presets(compiled, self.presets)
        elements = {
            item["field_id"]: item
            for module in compiled["design_elements"]["extended_dna_modules"]
            for item in module["elements"]
        }

        self.assertEqual(compiled["target_object"]["view"], "side")
        self.assertTrue(all(item["view"] == "side" for item in compiled["evidence"]))
        self.assertNotIn("GEO-03", elements)
        self.assertNotIn("PRT-01", elements)
        self.assertEqual(
            elements["IMG-03"]["value"],
            [{"label": "轻快", "strength": 75}, {"label": "怀旧", "strength": 50}],
        )
        self.assertNotIn("DET-13", elements)
        self.assertEqual(
            report["derived_field_degradations"][0]["field_id"], "DET-13"
        )

        schema = json.loads(
            (ROOT / "schemas/design-dna-output.schema.json").read_text()
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(compiled)), [])


if __name__ == "__main__":
    unittest.main()
