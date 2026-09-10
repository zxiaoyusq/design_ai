"""核对来源类别来自明确源字段，紧凑提取与缺失用户品类不会生成假类别。"""

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import core
import reporting
import prepare
import test_pipeline as fixtures


class ReportingCategoryTests(unittest.TestCase):
    def test_uses_cited_source_categories_instead_of_model_category(self):
        records = {
            "t1": {"kind": "trend", "fields": {"primary_category": "家居"}},
            "t2": {"kind": "trend", "fields": {"primary_category": "运动户外"}},
            "unused": {"kind": "trend", "fields": {"primary_category": "汽车"}},
        }
        evidence = [{"record_id": "t1", "category": ""},
                    {"record_id": "t1", "category": "模型推断的手机"},
                    {"record_id": "t2"}]
        scope = reporting.source_category_scope(evidence, records)
        self.assertEqual(scope["source_categories"], sorted(["家居", "运动户外"]))
        self.assertEqual(scope["source_category_unknown_record_ids"], [])

    def test_user_category_stays_unknown_despite_phone_context(self):
        records = {"u1": {"kind": "user_qa", "fields": {
            "question": "你喜欢手机的哪种后盖？", "question_type": "色彩",
            "scenario_type": "手机外观整体风格", "ai_analysis": "喜欢哑光。",
        }}}
        evidence = [{"record_id": "u1", "category": "手机"}, {"record_id": "u1"}]
        scope = reporting.source_category_scope(evidence, records)
        self.assertEqual(scope["source_categories"], [])
        self.assertEqual(scope["source_category_unknown_record_ids"], ["u1"])
        self.assertIn("primary_category", scope["source_category_scope"])
        self.assertIn("品类未知", scope["source_category_scope"])

    def test_empty_or_invalid_primary_category_is_not_guessed_from_subcategory(self):
        values = [None, "", "  ", ["家具"], 123]
        records = {str(i): {"fields": {"primary_category": value, "subcategory": "家具"}}
                   for i, value in enumerate(values)}
        records["known"] = {"fields": {"primary_category": " 家居 "}}
        scope = reporting.source_category_scope([{"record_id": rid} for rid in records], records)
        self.assertEqual(scope["source_categories"], ["家居"])
        self.assertEqual(scope["source_category_unknown_record_ids"], sorted(str(i) for i in range(len(values))))

    def test_existing_finalize_interface_populates_category_scope(self):
        # 复用离线流水线夹具，确保实际成品使用源字段，未增加模型契约或调用参数。
        fixture = fixtures.PipelineTests("test_six_stages_keep_user_counts_paths_and_traceability")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        args = fixture.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        fixture.complete(run)
        card = core.read(run / "high_potential_trends.json")["trends"][0]
        self.assertEqual(card["evidence_scope"]["source_categories"], ["家具"])
        expected_unknown = sorted({item["record_id"] for item in card["source_evidence"]
                                   if item["kind"] != "trend"})
        self.assertTrue(expected_unknown)
        self.assertEqual(card["evidence_scope"]["source_category_unknown_record_ids"], expected_unknown)
        self.assertTrue((run / "completion.json").is_file())


if __name__ == "__main__":
    unittest.main()
