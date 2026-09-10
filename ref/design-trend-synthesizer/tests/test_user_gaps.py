"""验证用研缺口的用户分母、逐字证据与全量趋势覆盖；不调用模型或网络。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core
import user_gaps


class UserGapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="design-user-gaps-test-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name).resolve()
        self.records = {
            f"trend:{number}": {
                "id": f"trend:{number}", "kind": "trend", "fields": {
                    "title_zh": f"合成趋势 {number}", "summary_zh": "讨论材料与制造工艺。",
                },
            }
            for number in range(1, 6)
        }
        self.evidence = {}
        for number, answer, stance in (
            (1, "喜欢蓝色。", "support"),
            (2, "不喜欢蓝色。", "counter"),
            (3, "仅在办公时接受蓝色。", "conditional"),
            (4, "喜欢轻巧的形态。", "support"),
            (5, "喜欢稳定的结构。", "support"),
        ):
            self.add_user_record(f"r{number}", f"u{number}", answer, stance=stance)
        self.add_user_record("r1-demand", "u1", "希望蓝色有更多深浅选择。", kind="user_demand")
        self.add_user_record("orphan", None, "喜欢蓝色。", kind="orphan_demand")
        self.add_user_record("unowned", None, "喜欢蓝色。")
        self.population = ["u1", "u2", "u3", "u4"]

    def add_user_record(self, identifier, user_id, answer, *, kind="user_qa", stance="support"):
        field = "ai_analysis" if kind == "user_qa" else "ai_index"
        self.records[identifier] = {
            "id": identifier, "kind": kind, "user_id": user_id,
            "fields": {field: answer, "question": "你是否喜欢蓝色？"},
        }
        self.evidence[identifier] = {
            "id": identifier, "record_id": identifier, "kind": kind, "user_id": user_id,
            "field": field, "quote": answer, "dimensions": ["color"], "stance": stance,
        }

    def findings(self, ids=None):
        return {
            "snapshot": {"evidence_sha256": core.digest(self.evidence), "records_sha256": core.digest(self.records)},
            "directions": [{
                "id": "color-expression", "title": "颜色表达及其使用条件", "summary": "用户讨论颜色选择，具体态度不同。",
                "evidence_ids": ids or ["r1", "r1-demand", "r2", "r3"],
                "boundaries": ["提及包含接受、拒绝与条件表达，不代表共同偏好。"],
                "trend_coverage": [{
                    "record_id": f"trend:{number}", "status": "unmentioned",
                    "reason": "已回查完整摘要，只讨论材料与制造，未讨论颜色表达。",
                } for number in range(1, 6)],
            }],
        }

    def compile(self, findings=None, population=None):
        return user_gaps.compile_findings(
            self.findings() if findings is None else findings,
            self.evidence, self.records,
            self.population if population is None else population, self.run,
        )

    def test_unique_users_deduplicate_questions_and_demands_and_keep_mixed_attitudes(self):
        result = self.compile()
        direction = result["directions"][0]
        stats = direction["mention_statistics"]
        self.assertEqual(stats["unique_mentioned_users"], 3)
        self.assertEqual(stats["user_ids"], ["u1", "u2", "u3"])
        self.assertEqual(stats["population_count"], 4)
        self.assertEqual(stats["mention_ratio"], 0.75)
        self.assertTrue(stats["majority"])
        self.assertEqual(len(direction["source_evidence"]), 4)
        self.assertEqual({e["relation"] for e in direction["source_evidence"]}, {"mention"})
        self.assertEqual({e["stance"] for e in direction["source_evidence"]}, {"support", "counter", "conditional"})
        self.assertIn("不是共同偏好率", stats["note"])

    def test_exactly_half_is_excluded_even_with_many_answers_by_the_same_user(self):
        result = self.compile(self.findings(["r1", "r1-demand", "r2"]))
        self.assertEqual(result["directions"], [])
        self.assertEqual(result["excluded_findings"][0]["unique_mentioned_users"], 2)
        self.assertIn("未超过", result["excluded_findings"][0]["reasons"][0])

    def test_denominator_uses_all_text_users_instead_of_only_hit_users(self):
        population = user_gaps.scope_for_run(self.run, self.records)
        self.assertEqual(population, ["u1", "u2", "u3", "u4", "u5"])
        findings = self.findings(["r1", "r1-demand", "r2"])
        # 模型即使附带更小分母，也不能覆盖调用方从运行范围生成的分母。
        findings.update(population_user_ids=["u1", "u2"], population_count=2)
        result = self.compile(findings, population=population)
        self.assertEqual(result["population_count"], 5)
        self.assertEqual(result["directions"], [])
        self.assertEqual(result["excluded_findings"][0]["unique_mentioned_users"], 2)

    def test_preview_scope_keeps_processed_users_without_matching_quotes(self):
        core.write(self.run / "scope.json", {"accepted_user_ids": self.population})
        population = user_gaps.scope_for_run(self.run, self.records)
        self.assertEqual(population, ["u1", "u2", "u3", "u4"])
        result = self.compile(population=population)
        self.assertEqual(result["directions"][0]["mention_statistics"]["population_count"], 4)
        core.write(self.run / "scope.json", {"accepted_user_ids": ["missing-user"]})
        with self.assertRaisesRegex(ValueError, "不存在的用户"):
            user_gaps.scope_for_run(self.run, self.records)

    def test_orphan_unowned_and_out_of_scope_users_cannot_inflate_mentions(self):
        for invalid_id in ("orphan", "unowned", "r5"):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaisesRegex(ValueError, "用户回答证据"):
                    self.compile(self.findings(["r1", "r2", invalid_id]))

    def test_question_words_wrong_user_and_nonverbatim_answers_are_rejected(self):
        original = copy.deepcopy(self.evidence["r3"])
        for changes in (
            {"field": "question", "quote": "你是否喜欢蓝色？"},
            {"user_id": "u4"},
            {"kind": "user_demand"},
            {"quote": "我总是喜欢蓝色。"},
            {"quote": ""},
        ):
            with self.subTest(changes=changes):
                self.evidence["r3"] = {**original, **changes}
                # 更新摘要后仍须逐条回查回答，不能把摘要一致当作证据合法。
                with self.assertRaisesRegex(ValueError, "用户回答证据"):
                    self.compile()
        self.evidence["r3"] = original

    def test_all_five_selected_trends_must_be_checked_once(self):
        for mutation in ("omitted", "duplicate", "foreign"):
            with self.subTest(mutation=mutation):
                findings = self.findings()
                checks = findings["directions"][0]["trend_coverage"]
                if mutation == "omitted":
                    checks.pop()
                elif mutation == "duplicate":
                    checks.append(copy.deepcopy(checks[0]))
                else:
                    checks[-1]["record_id"] = "trend:not-selected"
                with self.assertRaisesRegex(ValueError, "所有选中趋势"):
                    self.compile(findings)
        self.assertEqual(len(self.compile()["directions"][0]["trend_coverage"]["checks"]), 5)

    def test_mentioned_or_uncertain_coverage_cannot_publish_a_gap(self):
        for status in ("mentioned", "uncertain"):
            with self.subTest(status=status):
                findings = self.findings()
                findings["directions"][0]["trend_coverage"][-1]["status"] = status
                result = self.compile(findings)
                self.assertEqual(result["directions"], [])
                self.assertEqual(result["excluded_findings"][0]["unique_mentioned_users"], 3)
                self.assertIn("已有提及或覆盖关系仍不确定", result["excluded_findings"][0]["reasons"][0])

    def test_coverage_needs_semantic_reason_and_known_status(self):
        for changes in ({"reason": "  "}, {"status": "no-keyword-hit"}):
            with self.subTest(changes=changes):
                findings = self.findings()
                findings["directions"][0]["trend_coverage"][0].update(changes)
                with self.assertRaisesRegex(ValueError, "覆盖判断和理由"):
                    self.compile(findings)

    def test_evidence_and_source_snapshot_drift_each_rejects_compilation(self):
        findings = self.findings()
        self.evidence["r1"]["stance"] = "conditional"
        with self.assertRaisesRegex(ValueError, "摘要不匹配"):
            self.compile(findings)
        findings = self.findings()
        self.records["trend:5"]["fields"]["summary_zh"] += "也讨论颜色表达。"
        with self.assertRaisesRegex(ValueError, "摘要不匹配"):
            self.compile(findings)

    def test_prepare_context_keeps_full_trend_scope_and_separate_user_denominator(self):
        context = user_gaps.prepare_context(self.evidence, self.records, self.population)
        self.assertEqual(context["population_count"], 4)
        self.assertEqual({r["id"] for r in context["trend_records"]}, {f"trend:{n}" for n in range(1, 6)})
        recalled = {eid for item in context["recall"] for eid in item["evidence_ids"]}
        self.assertTrue({"orphan", "unowned", "r5"}.isdisjoint(recalled))
        self.assertEqual(context["snapshot"], self.findings()["snapshot"])
        self.assertIn("提及不等于偏好", context["note"])

    def test_publish_is_idempotent_and_keeps_card_jsonl_and_pause_state(self):
        for name, value in (
            ("records.json", self.records), ("evidence.json", self.evidence),
            ("scope.json", {"accepted_user_ids": self.population}),
            ("manifest.json", {"project_root": str(self.run)}),
            ("high_potential_trends.json", {"trends": [{"id": "card-1", "title": "已有主卡"}]}),
            ("validation_report.json", {"status": "preview_validated"}),
            ("completion.json", {"status": "preview_complete", "parent_pipeline_complete": False}),
        ):
            core.write(self.run / name, value)
        (self.run / "report.md").write_text("# 已有报告\n\n保留主卡内容。\n", encoding="utf-8")
        for _ in range(2):
            section = user_gaps.publish(self.run, self.findings())
        report = (self.run / "report.md").read_text(encoding="utf-8")
        self.assertEqual(report.count(user_gaps.HEADING), 1)
        self.assertEqual(report.count(user_gaps.START), 1)
        self.assertEqual(report.count(user_gaps.END), 1)
        self.assertIn("保留主卡内容。", report)
        self.assertIn("3/4 位用户", report)
        document = core.read(self.run / "high_potential_trends.json")
        self.assertEqual(document["user_research_gaps"], section)
        jsonl = [json.loads(line) for line in (self.run / "high_potential_trends.jsonl").read_text().splitlines()]
        self.assertEqual(jsonl, document["trends"])
        self.assertEqual(core.read(self.run / "user_research_gaps.json"), section)
        self.assertEqual(core.read(self.run / "validation_report.json")["user_research_gaps"]["direction_count"], 1)
        completion = core.read(self.run / "completion.json")
        self.assertEqual(completion["status"], "preview_complete")
        self.assertFalse(completion["parent_pipeline_complete"])
        self.assertEqual(completion["user_research_gaps_status"], "reviewed")
        self.assertFalse((self.run / "runner").exists())


if __name__ == "__main__":
    unittest.main()
