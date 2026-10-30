"""高潜趋势范围预估、任务进度、结果和研究图片 API。"""

from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from app.schemas.high_trends import HighTrendRequest, HighTrendResumeRequest
from app.services.high_trends.tasks import high_trend_manager
from app.services.high_trends.native_result import NativeHighTrendResult, RESULT_ID as NATIVE_RESULT_ID

router = APIRouter(prefix="/high-trends", tags=["High potential trends"])
native_result = NativeHighTrendResult()


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
def catalog(dataset: Literal["original", "article_table_2_selected_5"] = "original"):
    return call(high_trend_manager.catalog, dataset)


@router.post("/preview")
def preview(request: HighTrendRequest):
    return call(high_trend_manager.preview, request)


@router.get("/inputs")
def inputs():
    return call(high_trend_manager.inputs)


def _native(result_id: str):
    """仅开放已登记的冻结运行，不能通过 URL 传入任意本地目录。"""
    if result_id != NATIVE_RESULT_ID:
        raise HTTPException(404, "高潜筛选结果不存在")
    return native_result


@router.get("/native-results/{result_id}")
def native_details(result_id: str):
    return call(_native(result_id).get)


@router.get("/native-results/{result_id}/directions/{direction_id}/images")
def native_images(result_id: str, direction_id: str, page: int = Query(1, ge=1),
                  page_size: int = Query(12, ge=1, le=48),
                  scope: Literal["all", "cited", "associated"] = "all"):
    return call(_native(result_id).images, direction_id, page, page_size, scope)


@router.get("/native-results/{result_id}/images/{image_key}")
def native_image(result_id: str, image_key: str, thumbnail: bool = False):
    path = call(_native(result_id).image, image_key, thumbnail)
    return FileResponse(path, content_disposition_type="inline", headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600",
    })


@router.get("/native-results/{result_id}/download")
def native_download(result_id: str, format: Literal["json", "selection", "sources", "markdown"] = "json"):
    path = call(_native(result_id).download, format)
    return FileResponse(path, filename=path.name)


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
    return FileResponse(path, content_disposition_type="inline", headers={
        "X-Content-Type-Options": "nosniff",
        # 图片 URL 带文件身份版本；同一路径只在内容未变时长期缓存。
        "Cache-Control": "private, max-age=31536000, immutable",
    })


@router.get("/tasks/{task_id}/download")
def download(task_id: str, format: Literal["json", "markdown", "images_markdown", "performance", "handoff", "sources"] = "json"):
    path = call(high_trend_manager.download, task_id, format)
    return FileResponse(path, filename=path.name)
