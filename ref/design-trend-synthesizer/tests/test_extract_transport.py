"""传输压缩的无损性、短 ID 隔离与输入体积；全部离线运行。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = str(Path(__file__).parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from extract_transport import (
    TRANSPORT_VERSION, WIRE_INSTRUCTIONS, decode_response, pack_job, record_aliases, unpack_job,
)


def make_job(records):
    return {"id": "extract-original-job", "stage": "extract", "limits": {"max_observations": 48},
            "payload": {"records": deepcopy(records)}}


def record(identifier="user:67:user_qa:2413", answer="P12 舒适，但不喜欢 P13 的粗糙表面。"):
    return {"id": identifier, "kind": "user_qa", "user_id": "67",
            "profile": {"country": "印度尼西亚", "profession": "设计师", "age": 30},
            "fields": {"ai_analysis": answer, "question": "你最喜欢的细节有哪些？请对应前一问的产品回答。",
                       "answer_type": "直觉", "question_type": "色彩", "scenario_type": "电子产品偏好"}}


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ExtractTransportTests(unittest.TestCase):
    def assert_roundtrip(self, job):
        before = deepcopy(job)
        packed = pack_job(job)
        unpacked = unpack_job(packed)
        expected = deepcopy(job["payload"])
        for item, alias in zip(expected["records"], record_aliases(job), strict=True):
            item["id"] = alias
        self.assertEqual(unpacked["payload"], expected)
        self.assertEqual(unpacked["id"], job["id"])
        self.assertEqual(unpacked["limits"], job.get("limits", {}))
        self.assertEqual(job, before)
        return packed, unpacked

    def test_shared_32_short_answers_roundtrip_and_size(self):
        job = make_job([record(f"user:67:user_qa:{2413 + index}", f"P{index + 12} 舒适、可弯曲、有调节切口和缓冲。")
                        for index in range(32)])
        packed, _ = self.assert_roundtrip(job)
        self.assertEqual(len(packed["payload"]["records"]), 32)
        self.assertEqual(len(packed["payload"]["contexts"]), 1)
        self.assertEqual(len(packed["payload"]["profiles"]), 1)
        # 与已经按用户去重画像的旧格式比较，额外计入压缩格式的说明，避免夸大收益。
        baseline = deepcopy(job)
        baseline["payload"]["profiles"] = {"67": baseline["payload"]["records"][0]["profile"]}
        for item in baseline["payload"]["records"]:
            del item["profile"]
        self.assertLess(len(serialized(packed)) + len(WIRE_INSTRUCTIONS), len(serialized(baseline)) * 0.45)

    def test_many_unique_questions_still_send_field_names_once(self):
        records = [record(f"user:67:user_qa:{index}") for index in range(32)]
        for index, item in enumerate(records):
            item["fields"]["question"] = f"问题 {index}：你最喜欢的细节有哪些？"
        packed, _ = self.assert_roundtrip(make_job(records))
        self.assertEqual(len(packed["payload"]["contexts"]), 32)
        text = serialized(packed)
        self.assertEqual(text.count('"scenario_type"'), 1)
        self.assertEqual(text.count('"question_type"'), 1)
        self.assertEqual(text.count('"user_id"'), 2)  # 一次列定义，一次画像表。

    def test_context_deduplication_and_columns_ignore_dictionary_key_order(self):
        first = record("a")
        second = dict(reversed(list(record("b").items())))
        second["fields"] = dict(reversed(list(second["fields"].items())))
        packed = pack_job(make_job([first, second]))
        self.assertEqual(len(packed["payload"]["contexts"]), 1)
        reordered = dict(reversed(list(first.items())))
        reordered["fields"] = dict(reversed(list(first["fields"].items())))
        self.assertEqual(pack_job(make_job([first])), pack_job(make_job([reordered])))

    def test_all_kinds_and_unknown_fields_remain_exact(self):
        records = [
            {"id": "trend:1", "kind": "trend", "release_time": "2026-08-12", "confidence": None,
             "fields": {"summary_zh": "循環材料。\n仍需验证寿命。", "title_zh": "椅子", "local_vl_info": "原有文字",
                        "primary_category": "家具", "tags": ["羊毛", "材质"], "future": {"a": None}}},
            {"id": "trend:2", "kind": "trend", "fields": {"title_zh": "只有标题"}},
            record(),
            {"id": "user:1:demand:1", "kind": "user_demand", "user_id": "1",
             "fields": {"ai_index": "薄但不要刮手。", "scenario": "通勤", "ref_pic": "P12||P20"}},
            {"id": "orphan:1", "kind": "orphan_demand", "fields": {"ai_index": "粗纹理不适合。", "extra": False}},
        ]
        job = make_job(records)
        job["payload"].update(contexts={"original": "额外资料"}, profiles=None)
        packed, unpacked = self.assert_roundtrip(job)
        self.assertEqual(packed["transport_version"], TRANSPORT_VERSION)
        unpacked["payload"]["records"][0]["fields"]["tags"].append("修改副本")
        self.assertEqual(job["payload"]["records"][0]["fields"]["tags"], ["羊毛", "材质"])

    def test_missing_null_empty_values_and_missing_fields_are_distinct(self):
        records = [{"id": f"u{i}", "kind": "user_qa", "fields": {"ai_analysis": value, "question": None}}
                   for i, value in enumerate([None, "", False, 0, [], {}])]
        records.extend([{"id": "absent-answer", "kind": "user_qa", "fields": {"question": None}},
                        {"id": "absent-question", "kind": "user_qa", "fields": {"ai_analysis": None}},
                        {"id": "empty-fields", "kind": "user_qa", "fields": {}},
                        {"id": "absent-fields", "kind": "user_qa"}])
        packed, _ = self.assert_roundtrip(make_job(records))
        self.assertEqual(len(packed["payload"]["records"][0]), 3)
        self.assertEqual(len(packed["payload"]["records"][6]), 2)
        self.assertIn("context_missing", packed["payload"])

    def test_profile_missing_null_and_user_id_types_preserved(self):
        records = [
            {"id": "a", "kind": "user_qa", "user_id": 1, "profile": None, "fields": {}},
            {"id": "b", "kind": "user_qa", "user_id": "1", "profile": {}, "fields": {}},
            {"id": "c", "kind": "user_qa", "user_id": 1, "fields": {}},
            {"id": "d", "kind": "user_qa", "user_id": 1, "profile": None, "fields": {}},
        ]
        packed, _ = self.assert_roundtrip(make_job(records))
        self.assertEqual(len(packed["payload"]["profiles"]), 2)

    def test_profiles_cannot_cross_users(self):
        job = make_job([record()])
        packed = pack_job(job)
        packed["payload"]["profiles"][0]["user_id"] = "other-user"
        with self.assertRaisesRegex(ValueError, "画像归属"):
            unpack_job(packed)

    def test_profile_conflicts_and_missing_user_id_fail_explicitly(self):
        job = make_job([record("a"), record("b")])
        job["payload"]["records"][1]["profile"] = None
        with self.assertRaisesRegex(ValueError, "画像不一致"):
            pack_job(job)
        job = make_job([record()])
        del job["payload"]["records"][0]["user_id"]
        with self.assertRaisesRegex(ValueError, "没有 user_id"):
            pack_job(job)

    def test_aliases_are_deterministic_and_disjoint_from_original_ids(self):
        job = make_job([record("r1"), record("canonical-id"), record("r3")])
        expected = {"r2": "r1", "r4": "canonical-id", "r5": "r3"}
        self.assertEqual(record_aliases(job), expected)
        self.assertEqual(record_aliases(deepcopy(job)), expected)
        self.assert_roundtrip(job)
        with self.assertRaisesRegex(ValueError, "重复"):
            record_aliases(make_job([record("same"), record("same")]))

    def test_frozen_aliases_survive_reordered_subset(self):
        job = make_job([record("a"), record("b"), record("c")])
        job["transport_aliases"] = record_aliases(job)
        subset = deepcopy(job)
        subset["payload"]["records"] = [subset["payload"]["records"][2], subset["payload"]["records"][0]]
        self.assertEqual(record_aliases(subset), {"r3": "c", "r1": "a"})
        self.assert_roundtrip(subset)
        reply = {"observations": [{"record_id": "r2"}, {"record_id": "r3"}]}
        decoded, changes = decode_response(subset, reply)
        self.assertEqual(decoded["observations"], [{"record_id": "r2"}, {"record_id": "c"}])
        self.assertEqual(len(changes), 1)

    def test_invalid_frozen_aliases_are_rejected(self):
        for frozen in ({"a": "a"}, {"r1": "a", "r2": "a"}, {"r1": "missing"},
                       {"r1": "a", "r2": "r1"}, {"r1": None}, []):
            with self.subTest(frozen=frozen):
                job = make_job([record("a")])
                job["transport_aliases"] = frozen
                with self.assertRaises(ValueError):
                    record_aliases(job)

    def test_decode_only_known_record_ids_and_is_idempotent(self):
        job = make_job([record("canonical-a"), record("canonical-b")])
        reply = {"job_id": "r1", "observations": [
            {"record_id": "r1", "quote": "r1 与 P12", "image_roles": {"P12": "target", "r1": "comparison"}},
            {"record_id": "canonical-b"}, {"record_id": "unknown"},
        ], "skipped": [{"record_id": "r2", "reason": "r1"}]}
        before = deepcopy(reply)
        decoded, changes = decode_response(job, reply)
        self.assertEqual(decoded["observations"][0]["record_id"], "canonical-a")
        self.assertEqual(decoded["observations"][0]["quote"], "r1 与 P12")
        self.assertEqual(decoded["observations"][0]["image_roles"], reply["observations"][0]["image_roles"])
        self.assertEqual(decoded["job_id"], "r1")
        self.assertEqual(decoded["skipped"][0], {"record_id": "canonical-b", "reason": "r1"})
        self.assertEqual(len(changes), 2)
        self.assertEqual(reply, before)
        self.assertEqual(decode_response(job, decoded), (decoded, []))

    def test_decode_keeps_local_bad_items_for_strict_validation_and_reuse(self):
        job = make_job([record("canonical-a")])
        bad = [None, "r1", 42, {}, {"record_id": None}, {"record_id": 1},
               {"record_id": ["r1"]}, {"record_id": {"r1": "bad"}}]
        reply = {"observations": bad + [{"record_id": "r1"}], "skipped": "invalid-list"}
        decoded, changes = decode_response(job, reply)
        self.assertEqual(decoded["observations"][:-1], bad)
        self.assertEqual(decoded["observations"][-1], {"record_id": "canonical-a"})
        self.assertEqual(decoded["skipped"], "invalid-list")
        self.assertEqual(len(changes), 1)
        for invalid in (None, [], "bad", 42):
            self.assertEqual(decode_response(job, invalid), (invalid, []))

    def test_empty_and_nonextract_jobs_remain_usable(self):
        packed, _ = self.assert_roundtrip(make_job([]))
        self.assertEqual(packed["payload"]["contexts"], [])
        job = {"id": "theme-1", "stage": "theme", "payload": {"evidence": [1]}}
        self.assertEqual(pack_job(job), job)
        self.assertEqual(unpack_job(job), job)
        self.assertEqual(decode_response(job, {"observations": [{"record_id": "r1"}]}),
                         ({"observations": [{"record_id": "r1"}]}, []))


if __name__ == "__main__":
    unittest.main()
