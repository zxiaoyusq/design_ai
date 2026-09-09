"""验证保守 JSON 整理的允许范围及不可越过的语义和完整性边界。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from json_repair import parse_model_json


class JsonRepairTests(unittest.TestCase):
    def test_valid_strict_json_keeps_empty_change_log(self):
        for text in ('{"中文":"原文", "n":1}', ' \n {"a": [true, false, null]} \t',
                     '[1, 2.5, -3e2]', '"字符串"', '42', 'null'):
            with self.subTest(text=text):
                value, changes = parse_model_json(text)
                self.assertEqual(value, json.loads(text))
                self.assertEqual(changes, [])

    def test_single_full_response_json_fence(self):
        for text in ('```json\n{"a":1}\n```', '  ```JSON\r\n[1,2]\r\n```  '):
            with self.subTest(text=text):
                value, changes = parse_model_json(text)
                self.assertIn(value, ({"a": 1}, [1, 2]))
                self.assertIn("remove_json_fence", [item["operation"] for item in changes])

    def test_bom_and_outer_whitespace(self):
        value, changes = parse_model_json(' \n\ufeff\t {"a":"\ufeff正文"} \n')
        self.assertEqual(value, {"a": "\ufeff正文"})
        self.assertEqual([item["operation"] for item in changes],
                         ["trim_outer_whitespace", "remove_leading_bom", "trim_outer_whitespace"])

    def test_nested_trailing_commas_have_count_and_offsets(self):
        text = '{"a":[1, 2,\n], "b":{"x":true, },}'
        value, changes = parse_model_json(text)
        self.assertEqual(value, {"a": [1, 2], "b": {"x": True}})
        self.assertEqual(changes[0]["operation"], "remove_trailing_commas")
        self.assertEqual(changes[0]["count"], 3)
        self.assertEqual([text[index] for index in changes[0]["offsets"]], [","] * 3)
        self.assertEqual(changes[0]["offset_reference"], "after_wrapper_cleanup")

    def test_combined_wrappers_and_trailing_comma(self):
        value, changes = parse_model_json('\ufeff ```json\n{"a": [1,],}\n```\n')
        self.assertEqual(value, {"a": [1]})
        self.assertEqual(changes[-1]["count"], 2)
        self.assertIn("remove_leading_bom", [item["operation"] for item in changes])
        self.assertIn("remove_json_fence", [item["operation"] for item in changes])

    def test_string_contents_and_escapes_are_never_changed(self):
        original = {"quote": '文字 ,} ,] \\" \" ```json\n保持原样', "other": "\\"}
        encoded = json.dumps(original, ensure_ascii=False)
        value, changes = parse_model_json(encoded[:-1] + ",}")
        self.assertEqual(value, original)
        self.assertEqual(changes[0]["count"], 1)
        value, changes = parse_model_json(encoded)
        self.assertEqual(value, original)
        self.assertEqual(changes, [])

    def test_duplicate_keys_are_rejected_before_or_after_cleanup(self):
        for text in ('{"a":1,"a":2}', '{"a":1,"a":2,}',
                     '```json\n{"x":{"a":1,"a":2}}\n```',
                     '{"a":1,"\\u0061":2}'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "重复字段"):
                parse_model_json(text)

    def test_nonfinite_numbers_and_float_overflow_are_rejected(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            for text in ('{"a":' + number + '}', '```json\n{"a":' + number + ',}\n```'):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    parse_model_json(text)

    def test_prose_multiple_objects_and_multiple_fences_are_rejected(self):
        for text in ('这里是结果：{"a":1}', '{"a":1}\n解释文字',
                     '这里是结果\n```json\n{"a":1}\n```',
                     '```json\n{"a":1}\n```\n附加解释',
                     '{"a":1}{"b":2}',
                     '```json\n{"a":1}\n```\n```json\n{"b":2}\n```',
                     '```python\n{"a":1}\n```', '```\n{"a":1}\n```'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_model_json(text)

    def test_truncation_missing_values_and_nontrailing_commas_are_rejected(self):
        for text in ('{"a":1', '{"a":"未完成', '{"a":[1,2,',
                     '```json\n{"a":1\n```', '{"a":}', '[,]', '{,}',
                     '{"a":,}', '[1,,]', '{"a":1,,}', '[1 2]',
                     '{"a":1, "b":}', '{"a":1, "b"}', '[1,}',
                     '\ufeff\ufeff{"a":1}', '{"a":"非法\n换行",}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_model_json(text)

    def test_non_string_response_is_rejected(self):
        for value in (None, {}, [], 1, b'{}'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "字符串"):
                parse_model_json(value)


if __name__ == "__main__":
    unittest.main()
