"""复核离线恢复不能捏造证据，也不能通过冲突值覆盖绕过原校验。"""

import importlib.util
import json
from pathlib import Path
from unittest import TestCase

from app.services.dna.r5_focus_repair import recover_focus


class R5FocusRepairTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).resolve().parents[2] / ".agents/skills/prism-dna-sol-r5/scripts/engine.py"
        spec = importlib.util.spec_from_file_location("r5_focus_test_engine", path)
        cls.portable = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.portable)
        cls.engine = cls.portable.load_original()
        cls.schema = cls.engine.focus_schema([
            {"fact": {"p": "OPT-001"}}, {"fact": {"p": "GEO-008"}},
        ])
        cls.first = {"decision": "present", "value": "金属外观", "evidence": "表面可见金属反射"}
        cls.second = {"decision": "uncertain", "value": None, "evidence": "未见切口断面"}

    def repair(self, raw: str):
        return recover_focus(raw, self.schema, self.portable, self.engine)

    def test_complete_checks_survive_missing_outer_brace_and_trailing_garbage(self):
        answer = {"checks": {"0": self.first, "1": self.second}}
        raw = json.dumps(answer, ensure_ascii=False)
        for text in [raw, raw[:-1], raw + '`', raw + ' controls"}', '```json\n' + raw + '\n```']:
            with self.subTest(text=text):
                result = self.repair(text)
                self.assertEqual(result["answer"], answer)
                self.assertEqual(result["host_generated_check_ids"], [])
                self.assertTrue(result["complete"])

    def test_truncated_evidence_preserves_only_prior_complete_check(self):
        raw = '{"checks":{"0":' + json.dumps(self.first) + ',"1":{"decision":"present","value":"圆形","evidence":"截断'
        result = self.repair(raw)
        self.assertEqual(result["answer"]["checks"]["0"], self.first)
        self.assertEqual(result["host_generated_check_ids"], ["1"])
        self.assertEqual(result["answer"]["checks"]["1"]["decision"], "uncertain")
        self.assertIsNone(result["answer"]["checks"]["1"]["value"])
        self.assertFalse(result["complete"])

    def test_duplicate_conflicts_are_isolated_not_last_wins(self):
        conflicting = {**self.first, "value": "玻璃外观"}
        raw = '{"checks":{"0":' + json.dumps(self.first) + ',"0":' + json.dumps(conflicting) + ',"1":' + json.dumps(self.second) + '}}'
        result = self.repair(raw)
        self.assertEqual(result["host_generated_check_ids"], ["0"])
        self.assertEqual(result["usable_checks"], 1)
        self.assertEqual(len(result["quarantined"]), 2)

    def test_invalid_enum_and_inner_duplicate_keys_remain_pending(self):
        for value in ['{"decision":"present","value":"其他","evidence":"材料不明"}',
                      '{"decision":"present","value":"金属外观","value":"玻璃外观","evidence":"两值冲突"}']:
            with self.subTest(value=value):
                result = self.repair('{"checks":{"0":' + value + ',"1":' + json.dumps(self.second) + '}}')
                self.assertEqual(result["host_generated_check_ids"], ["0"])
                self.assertEqual(result["answer"]["checks"]["1"], self.second)

    def test_truncated_duplicate_cannot_admit_earlier_value(self):
        result = self.repair('{"checks":{"0":' + json.dumps(self.first) + ',"0":{"decision":"present","evidence":"截断')
        self.assertEqual(result["usable_checks"], 0)
        self.assertEqual(result["host_generated_check_ids"], ["0", "1"])

    def test_missing_comma_cannot_hide_conflicting_check_in_tail(self):
        schema = self.engine.focus_schema([{"fact": {"p": "OPT-001"}}])
        conflicting = {**self.first, "value": "玻璃外观"}
        raw = '{"checks":{"0":' + json.dumps(self.first) + ' "0":' + json.dumps(conflicting) + '}}'
        with self.assertRaisesRegex(ValueError, "尾部仍有结构化检查项"):
            recover_focus(raw, schema, self.portable, self.engine)

    def test_truncated_evidence_containing_check_text_does_not_block_prior_item(self):
        raw = '{"checks":{"0":' + json.dumps(self.first) + ',"1":{"decision":"uncertain","value":null,"evidence":"文字里有 \\"0\\":{ 截断'
        result = self.repair(raw)
        self.assertEqual(result["answer"]["checks"]["0"], self.first)
        self.assertEqual(result["host_generated_check_ids"], ["1"])

    def test_multiple_answers_and_unrecognizable_structure_are_rejected(self):
        raw = json.dumps({"checks": {"0": self.first, "1": self.second}})
        for text in [raw + raw, raw + ',"checks":{}', '{"other":{}}', 'just prose']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.repair(text)
