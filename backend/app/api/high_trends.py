"""高潜趋势范围预估、任务进度、结果和研究图片 API。"""

from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from app.schemas.high_trends import HighTrendRequest, HighTrendResumeRequest
from app.services.high_trends.tasks import high_trend_manager

router = APIRouter(prefix="/high-trends", tags=["High potential trends"])


def call(action, *args):
    try:
        return action(*args)
    except FileNotFoundError as exc:
        raise HTTPException(404, "研究数据、任务或结果文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/catalog")
def catalog():
    return call(high_trend_manager.catalog)


@router.post("/preview")
def preview(request: HighTrendRequest):
    return call(high_trend_manager.preview, request)


@router.post("/tasks", status_code=202)
def create(request: HighTrendRequest, background_tasks: BackgroundTasks):
    task = call(high_trend_manager.create, request)
    background_tasks.add_task(high_trend_manager.run, task["id"])
    return task


@router.get("/tasks")
def tasks():
    return call(high_trend_manager.list)


@router.get("/tasks/{task_id}")
def task(task_id: str):
    return call(high_trend_manager.get, task_id)


@router.post("/tasks/{task_id}/resume", status_code=202)
def resume(task_id: str, request: HighTrendResumeRequest, background_tasks: BackgroundTasks):
    task = call(high_trend_manager.resume, task_id, request)
    background_tasks.add_task(high_trend_manager.run, task_id)
    return task


@router.get("/tasks/{task_id}/images/{image_index}")
def image(task_id: str, image_index: int):
    path = call(high_trend_manager.image, task_id, image_index)
    return FileResponse(path, content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/tasks/{task_id}/download")
def download(task_id: str, format: Literal["json", "markdown"] = "json"):
    path = call(high_trend_manager.download, task_id, format)
    return FileResponse(path, filename=path.name)
