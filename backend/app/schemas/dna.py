"""设计 DNA 提取模块的 API 数据结构。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class TaskStatus(StrEnum):
    """一次批量提取任务的生命周期状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ImageTaskStatus(StrEnum):
    """任务中单张图片的处理状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionStage(StrEnum):
    """单张图片提取过程中可公开展示的稳定阶段。"""

    QUEUED = "queued"
    PREPARING = "preparing"
    MODEL_ANALYSIS = "model_analysis"
    PARSING = "parsing"
    COMPILING = "compiling"
    SEMANTIC_REVIEW = "semantic_review"
    REPAIRING = "repairing"
    VALIDATING = "validating"
    GENERATING_VIEW = "generating_view"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProgressEventLevel(StrEnum):
    """阶段事件的展示级别，不包含模型内部思维内容。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ExtractionProgressEvent(BaseModel):
    """供前端轮询展示的一条受控过程记录。"""

    stage: ExtractionStage
    message: str
    progress: int = Field(ge=0, le=100)
    level: ProgressEventLevel = ProgressEventLevel.INFO
    created_at: datetime


class UploadedImage(BaseModel):
    """已保存、可被用户选择的图片。"""

    id: str
    filename: str
    relative_path: str | None = None
    content_type: str
    size: int
    created_at: datetime
    preview_url: str


class ExtractionRequest(BaseModel):
    """用户确认后的 DNA 提取请求。"""

    image_ids: list[str] = Field(min_length=1, max_length=50)
    model_id: str = Field(min_length=1)
    prompt: str = Field(default="", max_length=4000)

    @field_validator("image_ids")
    @classmethod
    def image_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("image_ids 不能重复")
        return value


class ExtractionTaskItem(BaseModel):
    """单张图片在批量任务中的进度。"""

    image_id: str
    filename: str
    status: ImageTaskStatus
    result_id: str | None = None
    error: str | None = None
    diagnostic_id: str | None = None
    diagnostics: list[dict] = Field(default_factory=list)
    stage: ExtractionStage = ExtractionStage.QUEUED
    stage_progress: int = Field(default=0, ge=0, le=100)
    events: list[ExtractionProgressEvent] = Field(default_factory=list)


class ExtractionTask(BaseModel):
    """供前端轮询的任务快照。"""

    id: str
    status: TaskStatus
    model_id: str
    prompt: str
    progress: int = Field(ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    items: list[ExtractionTaskItem]


class DesignDnaResultSummary(BaseModel):
    """可供用户按图片选择的已完成结果。"""

    id: str
    image_name: str
    preview_url: str | None = None
    created_at: datetime
    category: str | None = None
    style_candidates: list[str] = Field(default_factory=list)
    summary: str | None = None


class DesignDnaResult(BaseModel):
    """业务视图或完整详情 JSON。"""

    id: str
    view: str
    content: dict
