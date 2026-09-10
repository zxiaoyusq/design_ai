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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import save_result
from compile_model_output import compile_model_output
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
        self.assertTrue(view_requirement_satisfied(["side"], "left"))
        self.assertTrue(view_requirement_satisfied(["side"], "right"))
        self.assertFalse(view_requirement_satisfied(["side"], "front"))
        self.assertFalse(view_requirement_satisfied(["rear"], "unknown"))
        self.assertTrue(view_requirement_satisfied(["any"], "unknown"))


if __name__ == "__main__":
    unittest.main()
