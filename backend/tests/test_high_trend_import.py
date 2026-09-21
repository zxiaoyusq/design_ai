"""宿主结果导入只用微型文件，验证登记、幂等和未完成任务保护。"""

from pathlib import Path
import tempfile
import unittest

from scripts.import_high_trend_result import import_result
from app.services.high_trends.skill import lean


class HostResultImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / "data/result/high_trend" / ("web_" + "a" * 32)
        self.run.mkdir(parents=True)
        values = {
            "manifest": {"model_profile": {"model": "gpt-6-astra"}, "selection": {},
                         "inputs": {"trends": {"path": str(self.root / "data/trend_data/article_table_2/trends.json")}},
                         "created_at": "2026-09-21T00:00:00+00:00", "settings": {"max_calls": 24},
                         "counts": {}, "plan": {}, "skill_version": "3.1.0"},
            "completion": {"status": "complete"}, "high_potential_trends": {},
            "state": {"jobs": {"direct-001": {"status": "accepted"}}},
            "sources": {}, "performance_report": {},
        }
        for name, value in values.items():
            lean.write(self.run / f"{name}.json", value)
        lean.write(self.run / "accepted/direct-001.json", {"accepted_at": "2026-09-21T00:01:00+00:00"})
        (self.run / "report.md").write_text("微型报告")

    def test_import_preserves_unknown_usage_and_is_idempotent(self):
        task = import_result(self.run, self.root)
        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["request"]["all_dates"])
        self.assertEqual(task["request"]["dataset"], "article_table_2_selected_5")
        self.assertEqual(import_result(self.run, self.root), task)
        performance = lean.read(self.run / "performance_report.json")
        self.assertIsNone(performance["actual_model_calls"])
        self.assertIsNone(performance["input_tokens_known"])
        self.assertEqual(performance["host_analysis_steps"], 1)

    def test_pending_research_is_not_registered(self):
        lean.write(self.run / "state.json", {"jobs": {"direct-001": {"status": "pending"}}})
        with self.assertRaisesRegex(ValueError, "尚未结束"):
            import_result(self.run, self.root)
        self.assertFalse((self.run / "web_task.json").exists())
