"""情绪版目录、确认生成、进度、历史与 JSON 导出。"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.schemas.moodboards import MoodboardRequest
from app.services.moodboards.tasks import moodboard_manager
from app.services.visual_workflow.web_adapter import native_asset, preview_handoff

router = APIRouter(prefix="/moodboards", tags=["Moodboards"])


def call(action, *args):
    try:
        return action(*args)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


class NativePreviewRequest(BaseModel):
    """只读投影原生运行目录，模型参数和审阅结论不接受浏览器提交。"""
    model_config = ConfigDict(extra="forbid")
    run_path: str = Field(min_length=1, max_length=1000)


@router.post("/native-results/preview")
def native_preview(request: NativePreviewRequest):
    return call(preview_handoff, request.run_path)


@router.get("/native-assets")
def read_native_asset(run_path: str, image_id: str):
    return FileResponse(call(native_asset, run_path, image_id), content_disposition_type="inline")


@router.get("/catalog")
def catalog():
    return call(moodboard_manager.catalog)


@router.post("/tasks", status_code=202)
def create(request: MoodboardRequest, background_tasks: BackgroundTasks):
    """确认选择后启动后台任务，浏览器只提交结果 ID，不上传图片。"""
    task = call(moodboard_manager.create, request)
    background_tasks.add_task(moodboard_manager.run, task["id"])
    return task


@router.get("/tasks")
def tasks():
    return call(moodboard_manager.list)


@router.get("/tasks/{task_id}")
def task(task_id: str):
    return call(moodboard_manager.get, task_id)


class ResumeRequest(BaseModel):
    """继续会产生剩余阶段的模型调用，需沿用明确的人工确认。"""
    confirmed: Literal[True]


@router.post("/tasks/{task_id}/resume", status_code=202)
def resume(task_id: str, request: ResumeRequest, background_tasks: BackgroundTasks):
    task = call(moodboard_manager.resume, task_id)
    background_tasks.add_task(moodboard_manager.run, task_id)
    return task


@router.get("/tasks/{task_id}/download")
def download(task_id: str):
    path = call(moodboard_manager.download, task_id)
    return FileResponse(path, filename=f"{task_id}.json")
