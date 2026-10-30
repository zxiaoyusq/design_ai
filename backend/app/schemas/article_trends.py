"""文章浏览及纯文本趋势聚类的显式范围契约。"""

from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArticleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=300)
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


class ClusterCreateRequest(ClusterRequest):
    selection_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: bool = False


class ClusterResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_calls: int = Field(ge=1, le=5000)
