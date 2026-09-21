"""进程内 DNA 提取任务编排；结果仍由文件系统持久保存。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from app.schemas.dna import (
    ExtractionStage,
    ImageTaskStatus,
    ProgressEventLevel,
    TaskStatus,
)
from app.services.dna.extraction import run_design_dna_extraction
from app.services.dna.storage import get_uploaded_image


MAX_CONCURRENT_IMAGE_EXTRACTIONS = 4


class ExtractionTaskNotFoundError(KeyError):
    """任务不存在或进程重启后状态已失效。"""


class ExtractionTaskManager:
    """并行处理独立图片，所有批次共享最多四个单图执行槽位。"""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = Lock()
        # 共享线程池使并发量随待处理图片数自然变化，同时约束多个批次的进程级总并发。
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_IMAGE_EXTRACTIONS,
            thread_name_prefix="dna-extraction",
        )

    def create(self, image_ids: list[str], model_id: str, prompt: str) -> dict:
        now = datetime.now(UTC)
        items = []
        for image_id in image_ids:
            stored, _ = get_uploaded_image(image_id)
            items.append(
                {
                    "image_id": image_id,
                    "filename": stored.filename,
                    "status": ImageTaskStatus.PENDING,
                    "result_id": None,
                    "error": None,
                    "diagnostic_id": None,
                    "diagnostics": [],
                    "stage": ExtractionStage.QUEUED,
                    "stage_progress": 0,
                    "events": [
                        {
                            "stage": ExtractionStage.QUEUED,
                            "message": "已加入提取队列",
                            "progress": 0,
                            "level": ProgressEventLevel.INFO,
                            "created_at": now,
                        }
                    ],
                }
            )
        task = {
            "id": uuid4().hex,
            "status": TaskStatus.QUEUED,
            "model_id": model_id,
            "prompt": prompt,
            "progress": 0,
            "created_at": now,
            "updated_at": now,
            "items": items,
        }
        with self._lock:
            self._tasks[task["id"]] = task
        return deepcopy(task)

    def get(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ExtractionTaskNotFoundError(task_id)
            return deepcopy(task)

    def is_image_in_active_task(self, image_id: str) -> bool:
        """删除素材前判断它是否正在等待或执行提取。"""

        with self._lock:
            return any(
                task["status"] in {TaskStatus.QUEUED, TaskStatus.RUNNING}
                and any(item["image_id"] == image_id for item in task["items"])
                for task in self._tasks.values()
            )

    def _update_item(
        self,
        task_id: str,
        item_index: int,
        *,
        status: ImageTaskStatus,
        result_id: str | None = None,
        error: str | None = None,
        diagnostic_id: str | None = None,
        diagnostics: list[dict] | None = None,
    ) -> None:
        with self._lock:
            task = self._tasks[task_id]
            item = task["items"][item_index]
            item.update(
                status=status,
                result_id=result_id,
                error=error,
                diagnostic_id=diagnostic_id,
                diagnostics=diagnostics or [],
            )
            if status in {ImageTaskStatus.COMPLETED, ImageTaskStatus.FAILED}:
                stage = (
                    ExtractionStage.COMPLETED
                    if status is ImageTaskStatus.COMPLETED
                    else ExtractionStage.FAILED
                )
                message = (
                    "设计 DNA 提取完成"
                    if status is ImageTaskStatus.COMPLETED
                    else "提取流程已结束，请查看错误详情"
                )
                level = (
                    ProgressEventLevel.INFO
                    if status is ImageTaskStatus.COMPLETED
                    else ProgressEventLevel.ERROR
                )
                item["stage"] = stage
                item["stage_progress"] = 100
                item["events"].append(
                    {
                        "stage": stage,
                        "message": message,
                        "progress": 100,
                        "level": level,
                        "created_at": datetime.now(UTC),
                    }
                )
            self._recalculate_task_progress(task)
            task["updated_at"] = datetime.now(UTC)

    @staticmethod
    def _recalculate_task_progress(task: dict) -> None:
        """批量任务进度取各图片阶段进度的平均值，仅用于过程提示。"""

        task["progress"] = round(
            sum(item["stage_progress"] for item in task["items"])
            / len(task["items"])
        )

    def _report_item_progress(
        self,
        task_id: str,
        item_index: int,
        stage: ExtractionStage,
        message: str,
        progress: int,
        level: ProgressEventLevel = ProgressEventLevel.INFO,
    ) -> None:
        """追加一条用户可读阶段事件，并保持估算进度单调递增。"""
        now = datetime.now(UTC)
        with self._lock:
            task = self._tasks[task_id]
            item = task["items"][item_index]
            normalized_progress = max(
                item["stage_progress"], min(99, max(0, progress))
            )
            item["stage"] = stage
            item["stage_progress"] = normalized_progress
            event = {
                "stage": stage,
                "message": message,
                "progress": normalized_progress,
                "level": level,
                "created_at": now,
            }
            previous = item["events"][-1] if item["events"] else None
            if not previous or (
                previous["stage"] != stage or previous["message"] != message
            ):
                item["events"].append(event)
                # 防止异常模型产生无限事件，轮询接口只保留最近的可读记录。
                item["events"] = item["events"][-80:]
            self._recalculate_task_progress(task)
            task["updated_at"] = now

    def _run_item(
        self,
        task_id: str,
        item_index: int,
        image_id: str,
        model_id: str,
        prompt: str,
    ) -> None:
        """执行一个固定索引的单图任务；失败只记录，不重新提交。"""

        self._update_item(task_id, item_index, status=ImageTaskStatus.RUNNING)
        try:
            self._report_item_progress(
                task_id,
                item_index,
                ExtractionStage.PREPARING,
                "正在读取图片并准备模型与 Skill",
                4,
            )
            stored, image_path = get_uploaded_image(image_id)

            def report_progress(
                stage: ExtractionStage,
                message: str,
                progress: int,
                level: ProgressEventLevel,
            ) -> None:
                # 固定 item_index，避免并行任务把过程事件写入其他图片。
                self._report_item_progress(
                    task_id,
                    item_index,
                    stage,
                    message,
                    progress,
                    level,
                )

            output = run_design_dna_extraction(
                image_path=image_path,
                content_type=stored.content_type,
                model_id=model_id,
                user_prompt=prompt,
                progress_callback=report_progress,
            )
            self._update_item(
                task_id,
                item_index,
                status=ImageTaskStatus.COMPLETED,
                result_id=output.result_id,
            )
        except Exception as exc:  # 单图失败不阻塞同批次其他图片，也不重试。
            self._update_item(
                task_id,
                item_index,
                status=ImageTaskStatus.FAILED,
                error=str(exc),
                diagnostic_id=getattr(exc, "diagnostic_id", None),
                diagnostics=getattr(exc, "issues", []),
            )

    def run(self, task_id: str) -> None:
        """由 FastAPI 后台线程提交一个已确认任务中的全部图片。"""

        with self._lock:
            task = self._tasks[task_id]
            task["status"] = TaskStatus.RUNNING
            task["updated_at"] = datetime.now(UTC)
            model_id = task["model_id"]
            prompt = task["prompt"]
            image_ids = [item["image_id"] for item in task["items"]]

        futures = [
            self._executor.submit(
                self._run_item,
                task_id,
                index,
                image_id,
                model_id,
                prompt,
            )
            for index, image_id in enumerate(image_ids)
        ]
        for future in as_completed(futures):
            future.result()

        with self._lock:
            task = self._tasks[task_id]
            completed = sum(
                item["status"] is ImageTaskStatus.COMPLETED
                for item in task["items"]
            )
            if completed == len(task["items"]):
                task["status"] = TaskStatus.COMPLETED
            elif completed:
                task["status"] = TaskStatus.PARTIAL
            else:
                task["status"] = TaskStatus.FAILED
            task["updated_at"] = datetime.now(UTC)


extraction_task_manager = ExtractionTaskManager()
