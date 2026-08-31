"""DNA 批量任务编排测试。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.dna import ImageTaskStatus, TaskStatus
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


if __name__ == "__main__":
    unittest.main()
