"""情绪版目录、确认生成、进度、历史与 JSON 导出。"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.schemas.moodboards import MoodboardRequest, MoodboardScopeRequest, MoodboardClusteringRequest
from app.services.moodboards.clustering import moodboard_clustering_manager
from app.services.moodboards.saved_results import saved_moodboard_results
from app.services.moodboards.tasks import moodboard_manager
from app.services.visual_workflow.web_adapter import native_asset, preview_handoff

router = APIRouter(prefix="/moodboards", tags=["Moodboards"])


@router.get("/clustering/saved-results")
def saved_results():
    """读取登记的 Skill 交付目录，保留原运行与评审身份。"""
    return call(saved_moodboard_results.list)


@router.get("/clustering/saved-results/{result_id}")
def saved_result(result_id: str):
    return call(saved_moodboard_results.get, result_id)


@router.get("/clustering/saved-results/{result_id}/download")
def saved_result_download(result_id: str):
    return FileResponse(call(saved_moodboard_results.download, result_id), filename=f"{result_id}.json")


@router.get("/clustering/saved-results/{result_id}/images/{token}")
def saved_result_image(result_id: str, token: str, original: bool = False):
    return FileResponse(call(saved_moodboard_results.image, result_id, token, original),
                        content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/clustering/catalog")
def clustering_catalog():
    return call(moodboard_clustering_manager.catalog)


@router.post("/clustering/preview")
def clustering_preview(request: MoodboardScopeRequest):
    return call(moodboard_clustering_manager.preview, request)


@router.post("/clustering/tasks", status_code=202)
def clustering_create(request: MoodboardClusteringRequest, background_tasks: BackgroundTasks):
    task = call(moodboard_clustering_manager.create, request)
    background_tasks.add_task(moodboard_clustering_manager.run, task["id"])
    return task


@router.get("/clustering/tasks")
def clustering_tasks():
    return call(moodboard_clustering_manager.list)


@router.get("/clustering/tasks/{task_id}")
def clustering_task(task_id: str):
    return call(moodboard_clustering_manager.get, task_id)


@router.get("/clustering/tasks/{task_id}/download")
def clustering_download(task_id: str):
    return FileResponse(call(moodboard_clustering_manager.download, task_id), filename=f"{task_id}.json")


@router.get("/clustering/tasks/{task_id}/images/{token}")
def clustering_image(task_id: str, token: str, original: bool = False):
    return FileResponse(call(moodboard_clustering_manager.image, task_id, token, original),
                        content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


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
