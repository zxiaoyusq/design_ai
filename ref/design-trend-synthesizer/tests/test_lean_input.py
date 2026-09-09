"""只用 2 条趋势、3 位用户和 8 条问答/需求验证轻量输入；无模型调用。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from lean_input import build_sources, pack_sources


class LeanInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lean-input-small-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.trend_path = self.root / "trends.json"
        self.user_path = self.root / "users.json"
        self.question = "在夜间办公时，哪种表面更合适？请完整解释取舍。"
        self.scenario = "夜间使用共享办公室，需要降低屏幕旁的反光，同时保留辨识度。"
        self.answer = "  喜欢 P25 的哑光表面，\n但不喜欢 P253 的硬边。  "
        self.trends = {"trends": [
            {"id": "first", "release_time": "2026-01-01T23:59:59-12:00",
             "title_zh": "柔和表面", "summary_zh": "保留细腻纹理。\n完整摘要。",
             "primary_category": "家具", "tags": ["哑光"],
             "images": [{"image_id": "trend-image", "local_path": "images/trend.jpg"}]},
            {"id": "last", "release_time": "2026-01-31T00:00:00+14:00",
             "title_zh": "硬边", "summary_zh": "用硬边表达辨识度。", "primary_category": "办公用品"},
        ]}
        self.users = {"users": [
            {"id": "user-b", "profile": {"profession": "设计师"}, "aesthetic_research": [
                {"id": "qa-1", "question": self.question, "ai_analysis": self.answer},
                {"id": "qa-2", "question": "原因？", "ai_analysis": "未提及相关理由"},
                {"id": "qa-3", "question": "其它？", "ai_analysis": None}],
             "demand_research": [{"id": "d-1", "scenario": self.scenario,
                                  "ai_index": "需要 P25 低反光，但边界清晰。", "ref_pic": "P25",
                                  "ref_pic_links": [{"code": "P25", "image_ids": ["d-image"],
                                                     "local_paths": ["images/demand.jpg"]}]}],
             "image_preferences": [
                 {"image_id": "qa-image", "ref_pic_code": "P25", "local_path": "images/qa.jpg"},
                 {"image_id": "not-mentioned", "ref_pic_code": "P2", "local_path": "images/no.jpg"}]},
            {"id": "user-a", "profile": {"profession": "工程师"}, "aesthetic_research": [
                {"id": "qa-4", "question": self.question, "ai_analysis": "喜欢清晰硬边。"}],
             "demand_research": [{"id": "d-2", "scenario": self.scenario, "ai_index": " \n "}]},
            {"id": "user-c", "profile": {}, "aesthetic_research": [
                {"id": "qa-5", "question": self.question, "ai_analysis": "无特别偏好。"}]},
        ], "unlinked_demand_research": [{"id": "orphan", "ai_index": "无法归属用户的回答。"}]}
        self.save_inputs()

    def save_inputs(self):
        self.trend_path.write_text(json.dumps(self.trends, ensure_ascii=False), encoding="utf-8")
        self.user_path.write_text(json.dumps(self.users, ensure_ascii=False), encoding="utf-8")

    def build(self, **options):
        return build_sources(self.trend_path, self.user_path, self.root, **options)

    def test_dates_include_source_calendar_boundaries_and_undated_policy(self):
        result = self.build(start_date="2026-01-01", end_date="2026-01-31")
        self.assertEqual(result["counts"]["selected_trends"], 2)
        self.assertEqual([row["release_time"] for row in result["sources"].values()
                          if row["kind"] == "trend"], ["2026-01-01", "2026-01-31"])
        narrowed = self.build(start_date="2026-01-02", end_date="2026-01-31")
        self.assertEqual(narrowed["sources"]["T00001"]["json_pointer"], "/trends/1")
        self.assertEqual(narrowed["selection"]["excluded"]["outside_range"], 1)
        self.trends["trends"][0]["release_time"] = None
        self.save_inputs()
        self.assertEqual(self.build()["counts"]["selected_trends"], 1)
        self.assertEqual(self.build(undated="include")["counts"]["selected_trends"], 2)

    def test_first_users_keep_all_valid_children_and_original_file_pointers(self):
        result = self.build(user_limit=2)
        self.assertEqual(result["selection"]["selected_user_ids"], ["user-b", "user-a"])
        self.assertEqual([item["json_pointer"] for item in result["sources"].values()
                          if item["kind"] != "trend"], [
                              "/users/0/aesthetic_research/0", "/users/0/demand_research/0",
                              "/users/1/aesthetic_research/0"])
        counts = result["counts"]
        self.assertEqual([counts[key] for key in (
            "excluded_unmentioned_qa", "excluded_empty_qa", "excluded_empty_demand",
            "excluded_unlinked_demands", "excluded_users_by_limit")], [1, 1, 1, 1, 1])
        for side, path in (("trends", self.trend_path), ("users", self.user_path)):
            self.assertEqual(result["inputs"][side], {
                "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        qa = result["sources"]["U000001"]
        self.assertEqual((qa["id"], qa["source_id"], qa["source_file"]),
                         ("user:user-b:user_qa:qa-1", "qa-1", "users"))
        self.assertEqual([ref["image_id"] for ref in qa["image_refs"]], ["qa-image"])
        self.assertEqual(qa["image_refs"][0]["source_root"], str(self.root.resolve()))
        demand = result["sources"]["U000002"]
        self.assertEqual(demand["image_refs"][0]["local_path"], "images/demand.jpg")

    def test_empty_qa_values_are_filtered_without_interpreting_short_answers(self):
        for value in ("", " \n ", [], {}):
            with self.subTest(value=value):
                self.users["users"][0]["aesthetic_research"][2]["ai_analysis"] = value
                self.save_inputs()
                self.assertEqual(self.build()["counts"]["excluded_empty_qa"], 1)
        self.users["users"][0]["aesthetic_research"][2]["ai_analysis"] = "无"
        self.save_inputs()
        self.assertEqual(self.build()["counts"]["excluded_empty_qa"], 0)

    def test_large_packs_cross_users_deduplicate_context_and_preserve_text(self):
        result = self.build()
        packs = pack_sources(result["sources"], 10000)
        self.assertEqual([pack["side"] for pack in packs], ["trend", "user"])
        payload = json.loads(packs[1]["text"])
        self.assertEqual(list(payload["profiles"]), ["user-b", "user-a", "user-c"])
        self.assertEqual(len(payload["contexts"]), 2)
        self.assertEqual(payload["rows"][0], ["U000001", "user-b", "C001", self.answer])
        self.assertEqual(payload["contexts"]["C001"]["question"], self.question)
        self.assertEqual(payload["contexts"]["C002"]["scenario"], self.scenario)
        self.assertEqual(payload["rows"][2][2], "C001")
        self.assertEqual(packs[1]["text"].count(self.question), 1)
        self.assertNotIn("images/", packs[1]["text"])
        self.assertNotIn("source_file", packs[1]["text"])
        self.assertNotIn("json_pointer", packs[1]["text"])
        trend = json.loads(packs[0]["text"])["trends"][0]
        self.assertEqual(trend["summary"], self.trends["trends"][0]["summary_zh"])
        self.assertNotIn("image_refs", packs[0]["text"])

    def test_character_budget_splits_complete_records_and_rejects_oversized_one(self):
        sources = self.build()["sources"]
        budget = max(len(pack_sources({alias: record}, 10000)[0]["text"])
                     for alias, record in sources.items())
        packs = pack_sources(sources, budget)
        self.assertTrue(all(len(pack["text"]) <= budget for pack in packs))
        self.assertEqual([alias for pack in packs for alias in pack["source_ids"]], list(sources))
        self.assertGreater(len(packs), 2)
        restored = {row[0]: row[3] for pack in packs if pack["side"] == "user"
                    for row in json.loads(pack["text"])["rows"]}
        for alias, record in sources.items():
            if record["kind"] != "trend":
                field = "ai_analysis" if record["kind"] == "user_qa" else "ai_index"
                self.assertEqual(restored[alias], record["fields"][field])
        single = {"U000001": sources["U000001"]}
        exact = len(pack_sources(single, 10000)[0]["text"])
        self.assertEqual(len(pack_sources(single, exact)[0]["text"]), exact)
        with self.assertRaisesRegex(ValueError, "U000001.*不会截断"):
            pack_sources(single, exact - 1)
        with self.assertRaisesRegex(ValueError, "正整数"):
            self.build(user_limit=0)


if __name__ == "__main__":
    unittest.main()
