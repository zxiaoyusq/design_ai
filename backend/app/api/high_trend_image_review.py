"""高潜趋势结果图片整理 API，选择状态与研究结果独立保存。"""

from typing import Literal
from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.api.high_trends import call
from app.schemas.high_trend_image_review import ImageReviewSelection
from app.services.high_trends.image_review import HighTrendImageReview
from app.services.high_trends.skill import PROJECT_ROOT


router = APIRouter(prefix="/high-trends/tasks/{task_id}/image-review", tags=["High trend image review"])
image_review = HighTrendImageReview(PROJECT_ROOT)
remaining_review = HighTrendImageReview(PROJECT_ROOT, "remaining")
Collection = Literal["result", "remaining"]


def service(collection):
    return remaining_review if collection == "remaining" else image_review


@router.post("")
def create(task_id: str, collection: Collection = "result"):
    return call(service(collection).create, task_id)


@router.get("")
def get(task_id: str, collection: Collection = "result"):
    return call(service(collection).get, task_id)


@router.patch("")
def update(task_id: str, request: ImageReviewSelection, collection: Collection = "result"):
    return call(service(collection).update, task_id, request.revision, request.image_ids, request.retained)


@router.get("/images/{image_id}")
def image(task_id: str, image_id: str, collection: Collection = "result", thumbnail: bool = False):
    path = call(service(collection).image, task_id, image_id, thumbnail)
    return FileResponse(path, content_disposition_type="inline", headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable",
    })


@router.get("/download")
def download(task_id: str, format: Literal["zip", "json"] = "zip", collection: Collection = "result"):
    path = call(service(collection).download, task_id, format)
    return FileResponse(path, filename=path.name)
