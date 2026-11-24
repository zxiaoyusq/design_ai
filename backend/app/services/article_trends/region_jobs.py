"""导入批次的主题地区分析，逐批保存已校验结果。"""

import json
import os
import re

from pydantic import ValidationError

from app.agents.article_trend_clusterer import run_text_step
from app.services.article_trends.catalog import ArticleCatalog
from app.services.article_trends.region_labels import (
    SYSTEM_PROMPT, RegionResponseError, batches, encode, input_sha256, result_for, validate_answer,
)
from app.services.article_trends.tasks import file_lock, now, owner_alive, process_identity, read, strict_object, write
from app.services.high_trends.errors import error_detail


def _lease():
    pid = os.getpid()
    return {"owner_pid": pid, "owner_identity": process_identity(pid)}


def new_job(task_id: str, model_id: str, article_count: int) -> dict:
    """与新增文章一起写入导入批次，保证中断后仍能发现任务。"""
    return {"id": task_id, "model_id": model_id, "status": "queued", "article_count": article_count,
            "processed_count": 0, "tagged_count": 0, "calls": 0, "error": None, **_lease()}


def _answer(response, packet):
    if response.get("truncated"):
        raise RegionResponseError("模型输出被截断")
    raw = response["text"].strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.partition("\n")[2][:-3].strip()
    try:
        return validate_answer(json.loads(raw, object_pairs_hook=strict_object), packet)
    except (TypeError, ValueError) as exc:
        raise RegionResponseError("模型结果格式、地区或引文未通过校验") from exc


class ArticleRegionJobs:
    """只处理已确认导入的新增文章，失败后由用户显式继续。"""

    def __init__(self, catalog: ArticleCatalog, runner=None):
        self.catalog = catalog
        self.output = catalog.region_dir
        self.runner = runner or run_text_step

    def _batch(self, task_id):
        if not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise FileNotFoundError("地区分析任务不存在")
        path = next(self.catalog.import_dir.glob(f"*-{task_id}.json"), None)
        if path is None:
            raise FileNotFoundError("地区分析任务不存在")
        batch = read(path)
        if batch.get("region_job", {}).get("id") != task_id:
            raise FileNotFoundError("地区分析任务不存在")
        return batch

    def _state(self, batch):
        job = batch["region_job"]
        path = self.output / f'{job["id"]}.json'
        return read(path) if path.is_file() else {"schema_version": 1, "task": job, "articles": []}

    @staticmethod
    def _status(state):
        job = state["task"].copy()
        if job["status"] in ("queued", "running") and not owner_alive(job):
            job.update(status="interrupted", error="服务已中断，可以继续分析剩余文章。")
        return job

    def get(self, task_id):
        return self._status(self._state(self._batch(task_id)))

    def latest(self):
        for path in sorted(self.catalog.import_dir.glob("*.json"), reverse=True):
            batch = read(path)
            if batch.get("region_job"):
                return self._status(self._state(batch))
        return None

    def retry(self, task_id):
        batch = self._batch(task_id)
        self.output.mkdir(parents=True, exist_ok=True)
        with file_lock(self.output / f".{task_id}.lock"):
            state = self._state(batch)
            if self._status(state)["status"] not in ("failed", "interrupted"):
                raise RuntimeError("只有失败或中断的地区分析才能继续")
            state["task"].update(status="queued", error=None, **_lease())
            write(self.output / f"{task_id}.json", state)
            return state["task"]

    def run(self, task_id):
        batch = self._batch(task_id)
        self.output.mkdir(parents=True, exist_ok=True)
        with file_lock(self.output / f".{task_id}.lock"):
            state = self._state(batch)
            job = state["task"]
            if job["status"] != "queued":
                return
            path = self.output / f"{task_id}.json"
            previous = {result["article_id"]: result for result in state["articles"]}
            pending = []
            for article in batch["articles"]:
                result = previous.get(article["article_id"])
                if not result or result["input_sha256"] != input_sha256(article):
                    pending.append(article)
                    previous.pop(article["article_id"], None)
            state["articles"] = list(previous.values())
            job.update(status="running", processed_count=len(previous),
                       tagged_count=sum(bool(result["tags"]) for result in previous.values()), **_lease())
            write(path, state)
            try:
                for packet in batches(pending):
                    # 请求前保存尝试次数，重启或异常时不自动再次调用网关。
                    job["calls"] += 1
                    write(path, state)
                    response = self.runner(job["model_id"], SYSTEM_PROMPT, encode(packet))
                    tags = _answer(response, packet)
                    actual = response.get("response_model")
                    # 只保存供应商报告的模型标识，不保存响应头和连接信息。
                    if not isinstance(actual, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,120}", actual):
                        actual = None
                    analyzed_at = now()
                    state["articles"].extend(result_for(
                        article, tags[article["article_id"]], model_id=job["model_id"], runtime="deepagents",
                        analyzed_at=analyzed_at, response_model=actual,
                    ) for article in packet)
                    job["processed_count"] += len(packet)
                    job["tagged_count"] += sum(bool(value) for value in tags.values())
                    write(path, state)
                job["status"] = "completed"
            except RegionResponseError as exc:
                job.update(status="failed", error=str(exc))
            except ValidationError:
                job.update(status="failed", error="模型配置或输入校验失败，请检查后端模型网关配置。")
            except Exception as exc:
                job.update(status="failed", error=error_detail(exc)["message"])
            write(path, state)
