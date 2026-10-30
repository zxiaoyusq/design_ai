"""全量文章库与用户显式确认的纯文本趋势聚类任务。"""

from typing import Annotated, Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from app.schemas.article_trends import ArticleFilters, ArticleListQuery, ClusterCreateRequest, ClusterRequest, ClusterResumeRequest
from app.services.article_trends.tasks import cluster_manager
from app.services.article_trends.history import HistoricalTrendResults

router = APIRouter(prefix="/article-trends", tags=["article-trends"])
# 历史图库与文章库共用同一份缓存及图片路径校验。
historical_results = HistoricalTrendResults(catalog=cluster_manager.catalog)


def checked(action: Callable):
    """仅映射预期业务错误，模型网关异常已在任务层脱敏。"""
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(404, "文章、图片或任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/catalog")
def catalog():
    return checked(lambda: cluster_manager.catalog.facets(cluster_manager.engine.VERSION))


@router.get("/history")
def history():
    return checked(historical_results.list)


@router.get("/history/{history_id}")
def historical_result(history_id: str):
    return checked(lambda: historical_results.get(history_id))


@router.get("/history/{history_id}/download")
def historical_download(history_id: str):
    # 下载原始趋势档，不以新任务结果格式重写历史数据。
    path = checked(lambda: historical_results.download_path(history_id))
    return FileResponse(path, media_type="application/json", filename=f"trend-clusters-{history_id}-original.json",
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/articles")
def articles(query: Annotated[ArticleListQuery, Query()]):
    filters = ArticleFilters(**query.model_dump(exclude={"page", "page_size"}))
    return checked(lambda: cluster_manager.catalog.listing(filters, query.page, query.page_size))


@router.get("/articles/{article_id}")
def article(article_id: str):
    return checked(lambda: cluster_manager.catalog.article(article_id))


@router.get("/articles/{article_id}/images/{index}")
def image(article_id: str, index: int):
    path = checked(lambda: cluster_manager.catalog.image(article_id, index))
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.post("/preview")
def preview(request: ClusterRequest):
    # 预估只读取文字、冻结范围摘要；不创建任务、不调用模型。
    return checked(lambda: cluster_manager.preview(request))


@router.post("/tasks", status_code=202)
def create(request: ClusterCreateRequest, background: BackgroundTasks):
    task = checked(lambda: cluster_manager.create(request))
    if task["status"] == "queued":
        background.add_task(cluster_manager.run, task["id"])
    return task


@router.get("/tasks")
def tasks():
    return checked(cluster_manager.list)


@router.get("/tasks/{task_id}")
def task(task_id: str):
    return checked(lambda: cluster_manager.get(task_id))


@router.post("/tasks/{task_id}/resume", status_code=202)
def resume(task_id: str, request: ClusterResumeRequest, background: BackgroundTasks):
    task = checked(lambda: cluster_manager.resume(task_id, request.max_calls))
    background.add_task(cluster_manager.run, task["id"])
    return task


@router.get("/tasks/{task_id}/download")
def download(task_id: str):
    task = checked(lambda: cluster_manager.get(task_id, include_result=False))
    if task["status"] != "completed":
        raise HTTPException(409, "任务尚未完成")
    return FileResponse(cluster_manager.output / task_id / "result.json", media_type="application/json",
                        filename=f"trend-clusters-{task_id}.json")
