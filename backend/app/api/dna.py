"""图片上传、DNA 提取任务和结果读取 API。"""

from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from app.schemas.dna import (
    DesignDnaResult,
    DesignDnaResultSummary,
    ExtractionRequest,
    ExtractionTask,
    UploadedImage,
)
from app.services.dna.storage import (
    ImageStorageError,
    delete_result,
    delete_uploaded_image,
    get_result_image,
    get_uploaded_image,
    list_results,
    list_uploaded_images,
    load_result,
    save_uploaded_image,
)
from app.services.dna.tasks import (
    ExtractionTaskNotFoundError,
    extraction_task_manager,
)
from app.services.llm.catalog import get_model


router = APIRouter(prefix="/dna", tags=["Design DNA"])


@router.post(
    "/images",
    response_model=list[UploadedImage],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    files: Annotated[list[UploadFile], File(description="一张或多张图片")],
    paths: Annotated[list[str] | None, Form()] = None,
) -> list[UploadedImage]:
    """统一接收单张、批量和浏览器文件夹上传。"""

    if not files:
        raise HTTPException(status_code=400, detail="至少上传一张图片")
    relative_paths = paths or []
    saved: list[UploadedImage] = []
    for index, upload in enumerate(files):
        relative_path = relative_paths[index] if index < len(relative_paths) else None
        try:
            stored = await save_uploaded_image(upload, relative_path)
        except ImageStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{upload.filename}: {exc}",
            ) from exc
        saved.append(UploadedImage.model_validate(stored.to_api_dict()))
    return saved


@router.get("/images", response_model=list[UploadedImage])
def read_uploaded_images() -> list[UploadedImage]:
    return [
        UploadedImage.model_validate(image.to_api_dict())
        for image in list_uploaded_images()
    ]


@router.get("/images/{image_id}/content", response_class=FileResponse)
def read_uploaded_image_content(image_id: str) -> FileResponse:
    try:
        stored, path = get_uploaded_image(image_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=stored.content_type,
        filename=stored.filename,
        content_disposition_type="inline",
    )


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_uploaded_image(image_id: str) -> None:
    """删除素材，但保留已经完成的设计 DNA 结果。"""

    if extraction_task_manager.is_image_in_active_task(image_id):
        raise HTTPException(status_code=409, detail="图片正在提取中，任务结束后才能删除")
    try:
        delete_uploaded_image(image_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImageStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/extractions",
    response_model=ExtractionTask,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_extraction(
    request: ExtractionRequest,
    background_tasks: BackgroundTasks,
) -> ExtractionTask:
    """用户确认后创建任务，每张图片单独激活一次提取 Skill。"""

    try:
        get_model(request.model_id)
        task = extraction_task_manager.create(
            request.image_ids,
            request.model_id,
            request.prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(extraction_task_manager.run, task["id"])
    return ExtractionTask.model_validate(task)


@router.get("/extractions/{task_id}", response_model=ExtractionTask)
def read_extraction(task_id: str) -> ExtractionTask:
    try:
        return ExtractionTask.model_validate(extraction_task_manager.get(task_id))
    except ExtractionTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="提取任务不存在") from exc


@router.get("/results", response_model=list[DesignDnaResultSummary])
def read_results() -> list[DesignDnaResultSummary]:
    return [DesignDnaResultSummary.model_validate(item) for item in list_results()]


@router.get("/results/{result_id}/image", response_class=FileResponse)
def read_result_image(result_id: str) -> FileResponse:
    try:
        path, content_type = get_result_image(result_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=content_type, content_disposition_type="inline")


@router.get("/results/{result_id}", response_model=DesignDnaResult)
def read_result(
    result_id: str,
    view: Literal["business", "detail"] = "business",
) -> DesignDnaResult:
    try:
        content = load_result(result_id, view)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DesignDnaResult(id=result_id, view=view, content=content)


@router.delete("/results/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_result(result_id: str) -> None:
    try:
        delete_result(result_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
