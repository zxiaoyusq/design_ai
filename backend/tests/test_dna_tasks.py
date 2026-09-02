"""DNA 批量任务编排测试。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.dna import ExtractionStage, ImageTaskStatus, TaskStatus
from app.services.dna.extraction import DesignDnaExtractionError
from app.services.dna.tasks import ExtractionTaskManager


class DnaTaskManagerTestCase(unittest.TestCase):
    @patch("app.services.dna.tasks.run_design_dna_extraction")
    @patch("app.services.dna.tasks.get_uploaded_image")
    def test_batch_task_processes_each_image_independently(
        self,
        get_image,
        run_extraction,
    ) -> None:
        get_image.side_effect = [
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
            (SimpleNamespace(filename="b.png", content_type="image/png"), Path("b.png")),
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
            (SimpleNamespace(filename="b.png", content_type="image/png"), Path("b.png")),
        ]
        run_extraction.side_effect = [
            SimpleNamespace(result_id="result-a"),
            RuntimeError("模型暂时不可用"),
        ]
        manager = ExtractionTaskManager()
        task = manager.create(["a" * 32, "b" * 32], "model-id", "关注材质")

        self.assertTrue(manager.is_image_in_active_task("a" * 32))

        manager.run(task["id"])
        completed = manager.get(task["id"])

        self.assertIs(completed["status"], TaskStatus.PARTIAL)
        self.assertEqual(completed["progress"], 100)
        self.assertIs(completed["items"][0]["status"], ImageTaskStatus.COMPLETED)
        self.assertEqual(completed["items"][0]["result_id"], "result-a")
        self.assertIs(completed["items"][1]["status"], ImageTaskStatus.FAILED)
        self.assertEqual(run_extraction.call_count, 2)
        self.assertFalse(manager.is_image_in_active_task("a" * 32))

    @patch("app.services.dna.tasks.run_design_dna_extraction")
    @patch("app.services.dna.tasks.get_uploaded_image")
    def test_failed_item_keeps_structured_diagnostics(
        self,
        get_image,
        run_extraction,
    ) -> None:
        get_image.side_effect = [
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
        ]
        issue = {
            "code": "STYLE_FIELD_UNAVAILABLE",
            "repair_owner": "compiler",
            "message": "风格证据字段没有可用值",
            "final_path": "style_result.style_tags[0]",
            "source_pointer": "/style_observations/confirmed_tags/0",
        }
        run_extraction.side_effect = DesignDnaExtractionError(
            "结果未通过校验",
            diagnostic_id="failure-001",
            issues=[issue],
        )
        manager = ExtractionTaskManager()
        task = manager.create(["a" * 32], "model-id", "关注材质")

        manager.run(task["id"])
        item = manager.get(task["id"])["items"][0]

        self.assertIs(item["status"], ImageTaskStatus.FAILED)
        self.assertEqual(item["diagnostic_id"], "failure-001")
        self.assertEqual(item["diagnostics"], [issue])

    @patch("app.services.dna.tasks.run_design_dna_extraction")
    @patch("app.services.dna.tasks.get_uploaded_image")
    def test_task_exposes_live_stage_events(
        self,
        get_image,
        run_extraction,
    ) -> None:
        get_image.side_effect = [
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
            (SimpleNamespace(filename="a.png", content_type="image/png"), Path("a.png")),
        ]

        def run_with_progress(**kwargs):
            callback = kwargs["progress_callback"]
            callback(
                ExtractionStage.MODEL_ANALYSIS,
                "第 1 次模型请求已发送，等待响应",
                14,
                "info",
            )
            callback(
                ExtractionStage.VALIDATING,
                "正在执行最终校验",
                86,
                "info",
            )
            return SimpleNamespace(result_id="result-a")

        run_extraction.side_effect = run_with_progress
        manager = ExtractionTaskManager()
        task = manager.create(["a" * 32], "model-id", "关注材质")

        manager.run(task["id"])
        completed = manager.get(task["id"])
        item = completed["items"][0]

        self.assertEqual(completed["progress"], 100)
        self.assertIs(item["stage"], ExtractionStage.COMPLETED)
        self.assertEqual(item["stage_progress"], 100)
        self.assertEqual(
            [event["stage"] for event in item["events"]],
            [
                ExtractionStage.QUEUED,
                ExtractionStage.PREPARING,
                ExtractionStage.MODEL_ANALYSIS,
                ExtractionStage.VALIDATING,
                ExtractionStage.COMPLETED,
            ],
        )


if __name__ == "__main__":
    unittest.main()
