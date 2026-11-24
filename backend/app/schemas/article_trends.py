"""文章浏览及纯文本趋势聚类的显式范围契约。"""

from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArticleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=300)
    region: str = Field(default="", max_length=100)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class ClusterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: ArticleFilters = Field(default_factory=ArticleFilters)
    article_ids: list[str] | None = Field(default=None, max_length=20000)
    limit: int | None = Field(default=None, ge=1, le=20000)
    model_id: str
    min_source_groups: int = Field(default=3, ge=2, le=100)
    max_calls: int = Field(default=30, ge=1, le=5000)


class ArticleListQuery(ArticleFilters):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)


class ArticleImportSample(BaseModel):
    """预览中展示的待新增文章。"""

    article_id: str
    title: str
    published_at: date | None


class ArticleImportIssue(BaseModel):
    """跳过的异常行及原表行号。"""

    row: int
    reason: str


class ArticleImportPreview(BaseModel):
    """导入预览只读，摘要绑定文件原字节与本次可新增的文章。"""

    selection_digest: str
    total_rows: int
    new_count: int
    duplicate_count: int
    invalid_count: int
    image_count: int
    sample_articles: list[ArticleImportSample]
    issues: list[ArticleImportIssue]


class ArticleRegionJob(BaseModel):
    """一份导入的地区分析进度，包含已判断但无地区证据的文章。"""

    id: str
    model_id: str
    status: str
    article_count: int
    processed_count: int
    tagged_count: int
    calls: int
    error: str | None = None


class ArticleImportResult(BaseModel):
    """确认导入后的新增、跳过与资料库总量。"""

    added_count: int
    duplicate_count: int
    invalid_count: int
    total_articles: int
    region_job: ArticleRegionJob | None = None


class ClusterCreateRequest(ClusterRequest):
    selection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False


class ClusterResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_calls: int = Field(ge=1, le=5000)
