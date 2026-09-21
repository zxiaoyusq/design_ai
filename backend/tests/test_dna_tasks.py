"""DNA 批量任务编排测试。"""

import unittest
from pathlib import Path
from threading import Event, Lock, Thread
from time import sleep
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
        image_a = "a" * 32
        image_b = "b" * 32

        def resolve_image(image_id):
            name = "a.png" if image_id == image_a else "b.png"
            return SimpleNamespace(filename=name, content_type="image/png"), Path(name)

        def extract_image(**kwargs):
            if kwargs["image_path"].name == "a.png":
                return SimpleNamespace(result_id="result-a")
            raise RuntimeError("模型暂时不可用")

        get_image.side_effect = resolve_image
        run_extraction.side_effect = extract_image
        manager = ExtractionTaskManager()
        task = manager.create([image_a, image_b], "model-id", "关注材质")

        self.assertTrue(manager.is_image_in_active_task(image_a))

        manager.run(task["id"])
        completed = manager.get(task["id"])

        self.assertIs(completed["status"], TaskStatus.PARTIAL)
        self.assertEqual(completed["progress"], 100)
        self.assertIs(completed["items"][0]["status"], ImageTaskStatus.COMPLETED)
        self.assertEqual(completed["items"][0]["result_id"], "result-a")
        self.assertIs(completed["items"][1]["status"], ImageTaskStatus.FAILED)
        self.assertEqual(run_extraction.call_count, 2)
        self.assertFalse(manager.is_image_in_active_task(image_a))

    @patch("app.services.dna.tasks.run_design_dna_extraction")
    @patch("app.services.dna.tasks.get_uploaded_image")
    def test_batch_runs_at_most_four_images_and_keeps_progress_isolated(
        self,
        get_image,
        run_extraction,
    ) -> None:
        image_ids = [f"{index:032x}" for index in range(6)]
        state = {"active": 0, "maximum": 0, "started": 0}
        state_lock = Lock()
        four_started = Event()

        def resolve_image(image_id):
            return (
                SimpleNamespace(filename=f"{image_id}.png", content_type="image/png"),
                Path(f"{image_id}.png"),
            )

        def extract_image(**kwargs):
            image_id = kwargs["image_path"].stem
            with state_lock:
                state["active"] += 1
                state["started"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                if state["started"] == 4:
                    four_started.set()
            four_started.wait(timeout=1)
            kwargs["progress_callback"](
                ExtractionStage.MODEL_ANALYSIS,
                f"正在分析 {image_id}",
                14,
                "info",
            )
            sleep(0.01)
            with state_lock:
                state["active"] -= 1
            return SimpleNamespace(result_id=f"result-{image_id}")

        get_image.side_effect = resolve_image
        run_extraction.side_effect = extract_image
        manager = ExtractionTaskManager()
        task = manager.create(image_ids, "model-id", "")

        manager.run(task["id"])
        completed = manager.get(task["id"])

        self.assertEqual(state["maximum"], 4)
        self.assertIs(completed["status"], TaskStatus.COMPLETED)
        for item in completed["items"]:
            messages = [event["message"] for event in item["events"]]
            self.assertIn(f"正在分析 {item['image_id']}", messages)

    @patch("app.services.dna.tasks.run_design_dna_extraction")
    @patch("app.services.dna.tasks.get_uploaded_image")
    def test_concurrent_batches_share_the_four_image_limit(
        self,
        get_image,
        run_extraction,
    ) -> None:
        image_ids = [f"{index + 10:032x}" for index in range(8)]
        state = {"active": 0, "maximum": 0, "started": 0}
        state_lock = Lock()
        four_started = Event()

        def resolve_image(image_id):
            return (
                SimpleNamespace(filename=f"{image_id}.png", content_type="image/png"),
                Path(f"{image_id}.png"),
            )

        def extract_image(**kwargs):
            with state_lock:
                state["active"] += 1
                state["started"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                if state["started"] == 4:
                    four_started.set()
            four_started.wait(timeout=1)
            sleep(0.01)
            with state_lock:
                state["active"] -= 1
            return SimpleNamespace(result_id=f"result-{kwargs['image_path'].stem}")

        get_image.side_effect = resolve_image
        run_extraction.side_effect = extract_image
        manager = ExtractionTaskManager()
        first = manager.create(image_ids[:4], "model-id", "")
        second = manager.create(image_ids[4:], "model-id", "")
        runners = [
            Thread(target=manager.run, args=(first["id"],)),
            Thread(target=manager.run, args=(second["id"],)),
        ]

        for runner in runners:
            runner.start()
        for runner in runners:
            runner.join(timeout=2)

        self.assertTrue(all(not runner.is_alive() for runner in runners))
        self.assertEqual(state["maximum"], 4)
        self.assertIs(manager.get(first["id"])["status"], TaskStatus.COMPLETED)
        self.assertIs(manager.get(second["id"])["status"], TaskStatus.COMPLETED)

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
