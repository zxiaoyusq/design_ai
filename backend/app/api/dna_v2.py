"""D02 图片 DNA V2 独立任务与候选结果接口。"""

import shutil

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from app.schemas.dna import ExtractionRequest, ExtractionTask
from app.services.dna.prism_r5 import RUN_DIR, ensure_r5_execution_allowed, run_prism_r5_extraction, validate_r5_request
from app.services.dna.prism_v2 import (
    load_prism_result,
    list_prism_results,
    prism_result_image_path,
    prism_result_path,
    read_ppt_enjoy_batch,
)
from app.services.dna.tasks import ExtractionTaskManager, ExtractionTaskNotFoundError


router = APIRouter(prefix="/dna-v2", tags=["Design DNA D02 V2"])
# 新请求走 Sol R5 主提取与至多一次困难项复核；旧 R17 结果仅保留读取。
prism_task_manager = ExtractionTaskManager(
    run_prism_r5_extraction, max_workers=2, thread_name_prefix="dna-d02-r5"
)


@router.post("/extractions", response_model=ExtractionTask, status_code=status.HTTP_202_ACCEPTED)
def create_extraction(request: ExtractionRequest, background_tasks: BackgroundTasks) -> ExtractionTask:
    try:
        validate_r5_request(request.model_id, request.prompt)
        ensure_r5_execution_allowed()
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
        raise HTTPException(status_code=404, detail="D02 任务不存在") from exc


@router.get("/results")
def read_results() -> list[dict]:
    return list_prism_results()


@router.get("/batches/ppt-enjoy")
def read_ppt_batch() -> dict:
    try:
        return read_ppt_enjoy_batch()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/results/{result_id}")
def read_result(result_id: str) -> dict:
    try:
        return load_prism_result(result_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/results/{result_id}/image", response_class=FileResponse)
def read_result_image(result_id: str) -> FileResponse:
    read_result(result_id)
    image = prism_result_image_path(result_id)
    if not image.is_file():
        raise HTTPException(status_code=404, detail="D02 结果图片不存在")
    return FileResponse(image, media_type="image/webp", content_disposition_type="inline")


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_result(result_id: str) -> None:
    result = read_result(result_id)
    if (result.get("source", {}).get("research") or {}).get("batch_id"):
        raise HTTPException(status_code=409, detail="批次结果由冻结清单管理，不能单独删除")
    result_path = prism_result_path(result_id)
    image_path = prism_result_image_path(result_id)
    if result.get("schema_version") == "prism_sol_r5_candidate_v1":
        # 结果删除入口同样清理新版调用账本，避免留下不可从界面访问的原始图片分析。
        trace_dir = RUN_DIR / result_id
        if trace_dir.is_dir():
            shutil.rmtree(trace_dir)
    result_path.unlink()
    image_path.unlink(missing_ok=True)
