"""进程内 DNA 提取任务编排；结果仍由文件系统持久保存。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from app.schemas.dna import ImageTaskStatus, TaskStatus
from app.services.dna.extraction import run_design_dna_extraction
from app.services.dna.storage import get_uploaded_image


class ExtractionTaskNotFoundError(KeyError):
    """任务不存在或进程重启后状态已失效。"""


class ExtractionTaskManager:
    """串行处理任务内图片，保证每次 Skill 激活只接收一张图。"""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = Lock()

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
    ) -> None:
        with self._lock:
            task = self._tasks[task_id]
            item = task["items"][item_index]
            item.update(status=status, result_id=result_id, error=error)
            finished = sum(
                candidate["status"]
                in {ImageTaskStatus.COMPLETED, ImageTaskStatus.FAILED}
                for candidate in task["items"]
            )
            task["progress"] = round(finished / len(task["items"]) * 100)
            task["updated_at"] = datetime.now(UTC)

    def run(self, task_id: str) -> None:
        """由 FastAPI 后台线程执行一个已确认任务。"""

        with self._lock:
            task = self._tasks[task_id]
            task["status"] = TaskStatus.RUNNING
            task["updated_at"] = datetime.now(UTC)
            model_id = task["model_id"]
            prompt = task["prompt"]
            image_ids = [item["image_id"] for item in task["items"]]

        for index, image_id in enumerate(image_ids):
            self._update_item(task_id, index, status=ImageTaskStatus.RUNNING)
            try:
                stored, image_path = get_uploaded_image(image_id)
                output = run_design_dna_extraction(
                    image_path=image_path,
                    content_type=stored.content_type,
                    model_id=model_id,
                    user_prompt=prompt,
                )
                self._update_item(
                    task_id,
                    index,
                    status=ImageTaskStatus.COMPLETED,
                    result_id=output.result_id,
                )
            except Exception as exc:  # 单图失败不阻塞同批次其他图片。
                self._update_item(
                    task_id,
                    index,
                    status=ImageTaskStatus.FAILED,
                    error=str(exc)[:2000],
                )

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
