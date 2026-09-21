"""两类三篇文章与极小用户夹具验证分类聚合、共享用研和确定性输出；无真实模型。"""

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import lean
from lean_input import pack_sources
import test_lean_input as fixture


class ClusterFlowTests(unittest.TestCase):
    def setUp(self):
        self.sample = fixture.LeanInputTests()
        self.sample.setUp()
        self.addCleanup(self.sample.doCleanups)
        self.root = self.sample.root
        rows = self.sample.trends["trends"]
        rows[0]["clustering_label"] = "材料美学"
        rows[1]["clustering_label"] = "灵活形态"
        rows.append({**rows[0], "id": "third", "title_zh": "再生纹理"})
        self.sample.save_inputs()

    def args(self, output, budget):
        return SimpleNamespace(trends=str(self.sample.trend_path), users=str(self.sample.user_path),
                               project_root=str(self.root), output=str(output), start_date="2026-01-01",
                               end_date="2026-01-31", undated="exclude", user_limit=2, batch_chars=budget,
                               max_calls=24, map_output_tokens=None, final_output_tokens=None,
                               model="offline", model_parameters="{}", dry_run=False, no_cache=True)

    def test_nonadjacent_articles_group_before_packing_and_date_filter(self):
        data = self.sample.build()
        packs = pack_sources(data["sources"], 10000)
        self.assertEqual([p["clustering_label"] for p in packs], ["材料美学", "灵活形态", None])
        self.assertEqual(packs[0]["source_ids"], ["T00001", "T00003"])
        self.assertEqual(data["trend_categories"][0]["article_count"], 2)
        self.assertEqual(json.loads(packs[0]["text"])["clustering_label"], "材料美学")
        filtered = self.sample.build(start_date="2026-01-02")
        self.assertEqual([c["label"] for c in filtered["trend_categories"]], ["灵活形态"])
        self.sample.trends["trends"][0]["clustering_label"] = None
        self.sample.save_inputs()
        self.assertEqual(self.sample.build()["sources"]["T00001"]["clustering_label"], "未分类")

    def test_grouped_notes_share_user_input_then_publish_category_directions(self):
        # 足够小的字符预算触发真实分包代码，数据仍仅几条。
        for row in self.sample.trends["trends"]:
            row["summary_zh"] = "材料与形态带来柔和触感。" * 35
        self.sample.save_inputs()
        run = self.root / "grouped"
        manifest = lean.prepare(self.args(run, 2400))
        self.assertFalse(manifest["plan"]["direct"])
        submitted_user_ids = []
        for jid in lean.status(run)["pending"]:
            job = lean.read(run / "requests" / f"{jid}.json")
            if job["clustering_labels"]:
                self.assertEqual(len(job["clustering_labels"]), 1)
            else:
                submitted_user_ids.extend(job["source_ids"])
            self.assertNotIn("max_tokens", job["model_profile"]["parameters"])
            lean.accept(run, jid, "## 柔和设计\n材料与触感结合。[" + " ".join(job["source_ids"]) + "]")
        sources = lean.read(run / "sources.json")
        expected_users = [k for k, v in sources.items() if v["kind"] != "trend"]
        self.assertCountEqual(submitted_user_ids, expected_users)
        jid = lean.next_job(run)["pending"][0]
        job = lean.read(run / "requests" / f"{jid}.json")
        payload = json.loads(job["messages"][1]["content"])
        categories = payload["trend_categories"]
        self.assertEqual([c["label"] for c in categories], ["材料美学", "灵活形态"])
        self.assertTrue(all(c["note_ids"] for c in categories))
        user_notes = [n["id"] for n in payload["notes"] if n["sides"] == ["user"]]
        text = "\n".join(f"# 大趋势分类：{c['label']}\n## 新设计方向 {i}\n结合用户诉求。[{' '.join(c['note_ids'] + user_notes)}]"
                         for i, c in enumerate(categories, 1))
        lean.accept(run, jid, text)
        document = lean.read(run / "high_potential_trends.json")
        self.assertEqual([c["clustering_labels"] for c in document["trends"]], [["材料美学"], ["灵活形态"]])
        self.assertEqual(len(document["trend_categories"]), 2)
        self.assertIn("材料美学", (run / "report.md").read_text())

    def test_small_direct_request_preserves_both_category_groups(self):
        run = self.root / "direct"
        manifest = lean.prepare(self.args(run, 48000))
        self.assertTrue(manifest["plan"]["direct"])
        job = lean.read(run / "requests/synthesize-001.json")
        payloads = [json.loads(line) for line in job["messages"][1]["content"].splitlines()]
        self.assertEqual([p["clustering_label"] for p in payloads if "trends" in p], ["材料美学", "灵活形态"])
        self.assertEqual(len([p for p in payloads if "rows" in p]), 1)


if __name__ == "__main__":
    unittest.main()
