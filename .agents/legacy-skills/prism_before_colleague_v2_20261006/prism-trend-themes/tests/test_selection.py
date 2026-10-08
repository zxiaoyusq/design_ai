"""收敛阶段只用微型合成证据测试，不运行模型或真实全量数据。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import select_trends as s

p = s.p
ANALYSIS = {"actor": "synthetic_test", "model_id": None, "model_version": None, "completed_at": "2026-10-01T00:00:00+00:00"}


def theme(cid):
    return {"cluster_id": cid, "title": "局部亮面映衬哑光主体", "definition": "主次区域光泽对比。", "design_question": "如何以局部高光组织层次？",
            "dimensions": ["surface"], "boundaries": {"shared_design_mechanism": "局部亮面映衬哑光主体", "includes": ["光泽对比"], "excludes": ["全表面同光泽"]},
            "hypotheses": [], "unknowns": []}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.final, self.run = self.root / "old", self.root / "selection"
        self.final.mkdir()
        self.skill = self.root / "skill"
        p.write(self.skill / "placeholder.json", {})
        (self.skill / "references").mkdir()
        (self.skill / "references/selection.md").write_text("只按明确机制归并。所有seed均需审阅。", encoding="utf-8")
        self.catalogue = {"articles": [], "evidence": []}
        self.clusters, self.coverage = [], []
        for i in range(1, 5):
            sid, eid = f"T:{i}", f"T:{i}:summary_zh"
            self.catalogue["articles"].append({"source_id": sid, "source_group_id": f"G{i}", "claim_origin_id": f"G{i}"})
            self.catalogue["evidence"].append({"evidence_id": eid, "source_id": sid, "source_group_id": f"G{i}", "claim_origin_id": f"G{i}", "field": "summary_zh", "text": "哑光主体与局部亮面形成对比。", "text_kind": "source_paraphrase"})
            member = {"point_id": f"P{i}", "evidence_id": eid, "quote": "哑光主体与局部亮面", "subject": "主体与细节", "feature": "主次光泽对比", "condition": None, "dimension": "surface", "reason": "局部亮面衬托主体"}
            self.clusters.append({**theme(f"S{i}"), "lineage": [{**theme(f"C{i}"), "members": [member]}]})
            self.coverage.append({"source_id": sid, "status": "clustered", "reason": "保留对比机制", "residuals": []})
        self.save_source()

    def tearDown(self):
        self.tmp.cleanup()

    def save_source(self):
        for name, value in {"trend-clusters.json": {"schema_version": "prism.trends.semantic_clusters.v0.1", "clusters": self.clusters},
                            "trend-catalogue.json": self.catalogue, "coverage.json": self.coverage, "execution.json": {"merge_analysis": ANALYSIS}}.items():
            p.write(self.final / name, value)

    def prepare(self, **kwargs):
        with patch.object(p, "SKILL", self.skill):
            return s.prepare(self.run, from_final=self.final, **kwargs)

    def plan(self, selected=None, deferred=None):
        selected = ["P1", "P2", "P3"] if selected is None else selected
        deferred = ["P4"] if deferred is None else deferred
        value = {"selection_manifest_sha256": p.digest(self.run / "manifest.json"), "analysis": ANALYSIS,
                 "clusters": [{**theme("T1"), "point_ids": selected, "variations": []}] if selected else [],
                 "deferred_points": [{"point_ids": deferred, "reason_code": "single_source", "reason": "暂作单篇线索保留"}] if deferred else []}
        path = self.root / "plan.json"
        p.write(path, value)
        return path

    def test_all_singleton_seeds_retained_then_cross_seed_merge(self):
        self.prepare()
        seeds = p.read(self.run / "seeds.json")
        self.assertEqual(len(seeds), 4)
        self.assertEqual([s["source_group_count"] for s in seeds], [1] * 4)
        packets = p.read(self.run / "selection-packets.json")
        self.assertEqual(sum(len(x["seed_ids"]) for x in packets["packets"]), 4)
        self.assertTrue(all(x["characters"] <= 28000 for x in packets["packets"]))
        result = s.check(self.run, self.plan())
        self.assertEqual(result[-2][0]["source_group_count"], 3)

    def test_evidence_pool_and_article_status(self):
        self.prepare()
        out = self.root / "new"
        summary = s.finalize(self.run, self.plan(), out)
        self.assertEqual(summary["main_trends"], 1)
        self.assertEqual(p.read(out / "coverage.json")[-1]["status"], "evidence_only")
        self.assertEqual(p.read(out / "coverage.json")[-1]["extraction_status"], "clustered")
        self.assertEqual(p.read(out / "evidence-pool.json")["points"][0]["point_id"], "P4")
        self.assertEqual(len(p.read(out / "point-dispositions.json")), 4)
        self.assertNotIn("T:4:summary_zh", (out / "report.md").read_text())
        self.assertEqual((out / "report.md").read_text().count("- T:"), 3)
        with self.assertRaises(ValueError):
            s.finalize(self.run, self.plan(), out)

    def test_same_source_group_does_not_increase_support(self):
        self.catalogue["articles"][1]["source_group_id"] = "G1"
        self.catalogue["evidence"][1]["source_group_id"] = "G1"
        self.save_source()
        self.prepare()
        with self.assertRaisesRegex(ValueError, "支持不足"):
            s.check(self.run, self.plan())

    def test_many_points_from_same_article_do_not_increase_support(self):
        for i in (1, 2):
            m = self.clusters[i]["lineage"][0]["members"][0]
            m["evidence_id"] = "T:1:summary_zh"
            self.coverage[i]["status"] = "non_aesthetic"
        self.save_source()
        self.prepare()
        with self.assertRaisesRegex(ValueError, "支持不足"):
            s.check(self.run, self.plan())

    def test_duplicate_missing_unknown_point_rejected(self):
        self.prepare()
        for selected, deferred in [(["P1", "P2", "P3"], ["P3", "P4"]), (["P1", "P2", "P3"], []), (["P1", "P2", "P3"], ["unknown"])]:
            with self.subTest(selected=selected, deferred=deferred), self.assertRaises(ValueError):
                s.check(self.run, self.plan(selected, deferred))

    def test_empty_clusters_require_explicit_disposition_of_all_points(self):
        self.prepare()
        result = s.check(self.run, self.plan([], ["P1", "P2", "P3", "P4"]))
        self.assertEqual(result[-2], [])
        self.assertEqual(len(result[-1]), 4)

    def test_threshold_limits_and_hard_cap(self):
        for kwargs in ({"max_trends": 101}, {"max_trends": 0}, {"min_source_groups": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.prepare(**kwargs)
        self.prepare()
        path = self.plan()
        value = p.read(path)
        value["clusters"] = [{**theme(f"T{i}"), "point_ids": ["P1", "P2", "P3"], "variations": []} for i in range(101)]
        p.write(path, value)
        with self.assertRaisesRegex(ValueError, "超过上限"):
            s.check(self.run, path)

    def test_frozen_input_and_manifest_binding(self):
        self.prepare()
        path = self.plan()
        original = (self.run / "points.json").read_bytes()
        (self.run / "points.json").write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "冻结输入"):
            s.check(self.run, path)
        (self.run / "points.json").write_bytes(original)
        value = p.read(path)
        value["selection_manifest_sha256"] = "wrong"
        p.write(path, value)
        with self.assertRaisesRegex(ValueError, "不匹配"):
            s.check(self.run, path)

    def test_duplicate_point_in_old_lineage_rejected(self):
        self.clusters[1]["lineage"][0]["members"][0]["point_id"] = "P1"
        self.save_source()
        with self.assertRaisesRegex(ValueError, "point_id 重复"):
            self.prepare()
        self.assertFalse(self.run.exists())

    def test_exact_quote_and_coverage_required(self):
        self.clusters[0]["lineage"][0]["members"][0]["quote"] = "编造引文"
        self.save_source()
        with self.assertRaisesRegex(ValueError, "非精确"):
            self.prepare()
        self.clusters[0]["lineage"][0]["members"][0]["quote"] = "哑光主体"
        self.coverage.pop()
        self.save_source()
        with self.assertRaisesRegex(ValueError, "覆盖全部"):
            self.prepare()

    def test_correction_keeps_original_quote_and_feature(self):
        corrections = self.root / "correction.json"
        p.write(corrections, {"point_interpretation_limits": {"P1": {"effective_feature": "仅局部亮面", "rejected_inference": "非整体高光"}}})
        self.prepare(corrections=corrections)
        point = p.read(self.run / "points.json")[0]
        self.assertEqual(point["original_feature"], "主次光泽对比")
        self.assertEqual(point["effective_feature"], "仅局部亮面")
        self.assertEqual(point["feature"], "仅局部亮面")
        self.assertEqual(point["quote"], "哑光主体与局部亮面")
        out = self.root / "new"
        s.finalize(self.run, self.plan(), out)
        member = p.read(out / "trend-clusters.json")["clusters"][0]["lineage"][0]["members"][0]
        self.assertEqual(member["rejected_inference"], "非整体高光")
        self.assertEqual(member["feature"], "仅局部亮面")

    def test_packet_overflow_is_not_truncated(self):
        with self.assertRaisesRegex(ValueError, "超过字符预算"):
            self.prepare(max_chars=10)
        self.assertFalse(self.run.exists())

    def test_from_run_uses_gather_and_needs_no_final(self):
        candidates = [{**theme(c["cluster_id"]), "members": c["lineage"][0]["members"]} for c in self.clusters]
        source = self.root / "run_source"
        p.write(source / "manifest.json", {})
        p.write(source / "catalogue.json", self.catalogue)
        collection = {"candidates": candidates, "coverage": self.coverage, "analyses": [ANALYSIS], "accepted_sha256": {"B1": "fixture"}}
        with patch.object(p, "gather", return_value=({}, self.catalogue, collection)) as gather, patch.object(p, "SKILL", self.skill):
            s.prepare(self.run, from_run=source)
        gather.assert_called_once_with(source)
        self.assertEqual(len(p.read(self.run / "points.json")), 4)

    def test_support_sort_tie_break_and_read_only_check(self):
        self.prepare(min_source_groups=2)
        path = self.plan()
        value = p.read(path)
        value["clusters"] = [{**theme("Z"), "point_ids": ["P1", "P2"], "variations": []},
                             {**theme("A"), "point_ids": ["P3", "P4"], "variations": []}]
        value["deferred_points"] = []
        p.write(path, value)
        before = {str(f): f.read_bytes() for f in self.run.iterdir()}
        self.assertEqual([c["cluster_id"] for c in s.check(self.run, path)[-2]], ["A", "Z"])
        self.assertEqual(before, {str(f): f.read_bytes() for f in self.run.iterdir()})

    def test_valid_exactly_100_main_trends(self):
        # 同一个微型机制复制为合成身份，仅测试边界数量，不宣称语义不同。
        member = self.clusters[0]["lineage"][0]["members"][0]
        article, evidence, coverage = self.catalogue["articles"][0], self.catalogue["evidence"][0], self.coverage[0]
        self.catalogue = {"articles": [], "evidence": []}
        self.clusters, self.coverage = [], []
        for i in range(200):
            sid, eid, gid, pid = f"T:{i}", f"T:{i}:summary_zh", f"G{i}", f"P{i}"
            self.catalogue["articles"].append({**article, "source_id": sid, "source_group_id": gid, "claim_origin_id": gid})
            self.catalogue["evidence"].append({**evidence, "source_id": sid, "evidence_id": eid, "source_group_id": gid, "claim_origin_id": gid})
            self.coverage.append({**coverage, "source_id": sid})
            self.clusters.append({**theme(f"S{i}"), "lineage": [{**theme(f"C{i}"), "members": [{**member, "point_id": pid, "evidence_id": eid}]}]})
        self.save_source()
        self.prepare(min_source_groups=2)
        path = self.plan()
        value = p.read(path)
        value["clusters"] = [{**theme(f"T{i:03d}"), "point_ids": [f"P{i*2}", f"P{i*2+1}"], "variations": []} for i in range(100)]
        value["deferred_points"] = []
        p.write(path, value)
        self.assertEqual(len(s.check(self.run, path)[-2]), 100)


if __name__ == "__main__":
    unittest.main()
