"""DNA V2：原生设计卡预提取、冻结结果和图片读取接口。"""

import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.schemas.dna import ExtractionRequest, ExtractionTask
from app.services.dna.preparation import (
    list_prepared_results,
    load_prepared_result,
    preparation_overview,
    prepared_image_path,
    run_preparation_extraction,
    validate_preparation_request,
)
from app.services.dna.prism_v2 import load_prism_result, prism_result_image_path, read_ppt_enjoy_batch
from app.services.dna.tasks import ExtractionTaskManager, ExtractionTaskNotFoundError


router = APIRouter(prefix="/dna-v2", tags=["Design DNA Preparation"])
# 网页只传用户确认的图片，单图调用 Skill 原生 A 阶段并独立冻结。
prism_task_manager = ExtractionTaskManager(
    run_preparation_extraction, max_workers=2, thread_name_prefix="dna-preparation"
)


@router.post("/extractions", response_model=ExtractionTask, status_code=status.HTTP_202_ACCEPTED)
def create_extraction(request: ExtractionRequest, background_tasks: BackgroundTasks) -> ExtractionTask:
    try:
        validate_preparation_request(request.model_id, request.prompt)
        task = prism_task_manager.create(request.image_ids, request.model_id, request.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(prism_task_manager.run, task["id"])
    return ExtractionTask.model_validate(task)


@router.get("/extractions/{task_id}", response_model=ExtractionTask)
def read_extraction(task_id: str) -> ExtractionTask:
    try:
        return ExtractionTask.model_validate(prism_task_manager.get(task_id))
    except ExtractionTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="设计 DNA 预提取任务不存在") from exc


@router.get("/preparation")
def read_preparation() -> dict:
    try:
        return preparation_overview()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="设计卡冻结清单不可读取或校验失败") from exc


@router.get("/results")
def read_results(query: str = "", branch: str | None = Query(default=None, pattern="^(ID|CMF)$")) -> list[dict]:
    try:
        return list_prepared_results(query=query, branch=branch)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="设计卡冻结清单不可读取或校验失败") from exc


@router.get("/batches/ppt-enjoy")
def read_ppt_batch() -> dict:
    try:
        return read_ppt_enjoy_batch()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/results/{result_id}")
def read_result(result_id: str) -> dict:
    try:
        # 已有业务链接可继续只读回查 R5；默认图库与新任务仅使用设计卡。
        if re.fullmatch(r"[a-f0-9]{32}", result_id):
            return load_prism_result(result_id)
        return load_prepared_result(result_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="设计卡原图或证据校验失败") from exc


@router.get("/results/{result_id}/image", response_class=FileResponse)
def read_result_image(result_id: str) -> FileResponse:
    try:
        if re.fullmatch(r"[a-f0-9]{32}", result_id):
            read_result(result_id)
            image = prism_result_image_path(result_id)
            if not image.is_file():
                raise FileNotFoundError("历史结果原图不存在")
            return FileResponse(image, media_type="image/webp", content_disposition_type="inline")
        image, media_type = prepared_image_path(result_id)
        return FileResponse(image, media_type=media_type, content_disposition_type="inline")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="设计卡原图不存在") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="设计卡原图校验失败") from exc


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_result(result_id: str) -> None:
    read_result(result_id)
    raise HTTPException(status_code=409, detail="设计卡结果由原生冻结清单管理，不能单独删除")
