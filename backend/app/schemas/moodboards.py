"""情绪版选择范围与两阶段模型输出契约。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MoodboardScopeRequest(BaseModel):
    """高潜结果只限定候选来源，不预先决定情绪板的类别。"""

    model_config = ConfigDict(extra="forbid")
    source_result_id: str = Field(min_length=1, max_length=100)
    direction_ids: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("direction_ids")
    @classmethod
    def unique_directions(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("选择方向不能重复")
        return value


class MoodboardClusteringRequest(BaseModel):
    """人工确认只绑定服务端预览；不接受任意原图路径或客户端 DNA。"""

    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(pattern=r"^mbp_[a-f0-9]{32}$")
    model_id: str
    prepare_missing: bool = False
    max_calls: int = Field(default=100, ge=1, le=2000)
    workers: int = Field(default=4, ge=1, le=10)
    confirmed: Literal[True]


class MoodboardRequest(BaseModel):
    """确认后冻结趋势方向和 DNA 结果；不接受图片内容或任意路径。"""

    model_config = ConfigDict(extra="forbid")
    trend_task_id: str
    direction_ids: list[str] = Field(min_length=1, max_length=20)
    result_ids: list[str] = Field(min_length=1, max_length=100)
    model_id: str
    confirmed: Literal[True]

    @field_validator("direction_ids", "result_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("选择 ID 不能重复")
        return value


class Assignment(BaseModel):
    """每张图只归属一个方向；没有可信依据时 direction_id 为 null。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    result_id: str
    direction_id: str | None
    reason: str = Field(min_length=1, max_length=1600)
    evidence_paths: list[str] = Field(min_length=1, max_length=8)


class Assignments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignments: list[Assignment]


class Cluster(BaseModel):
    """方向内的非空子类；成员必须恰好覆盖该方向的全部图片。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=3000)
    result_ids: list[str] = Field(min_length=1)


class Clusters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clusters: list[Cluster] = Field(min_length=1, max_length=3)


class Dominance(BaseModel):
    """DNA 文本支持的主导性判断；未知不能由置信度或虚构面积替代。"""

    model_config = ConfigDict(extra="forbid")
    strength: Literal["strong", "moderate", "weak", "unknown"]
    scope: Literal["global", "local", "unknown"]
    salience: Literal["primary", "secondary", "unknown"]


class CuratedAssignment(Assignment):
    """只有强、整体、主导特征进入候选池；竞争不清时保留未归属。"""

    status: Literal["matched", "ambiguous", "insufficient", "unmatched"]
    dominant_style: str = Field(min_length=1, max_length=240)
    dominance: Dominance
    competing_direction_ids: list[str]

    @model_validator(mode="after")
    def coherent_status(self):
        if len(set(self.competing_direction_ids)) != len(self.competing_direction_ids):
            raise ValueError("竞争方向不能重复")
        if self.status == "matched":
            if self.direction_id is None or self.dominance.model_dump() != {
                "strength": "strong", "scope": "global", "salience": "primary"
            }:
                raise ValueError("匹配必须具有强、整体、主导的 DNA 依据及唯一方向")
        elif self.direction_id is not None:
            raise ValueError("非 matched 状态不能强行归属方向")
        if self.status == "ambiguous" and len(self.competing_direction_ids) < 2:
            raise ValueError("歧义状态至少记录两个竞争方向")
        return self


class CuratedAssignments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignments: list[CuratedAssignment]


class CuratedCluster(Cluster):
    """单一风格成板只收录 6–8 张，其他候选必须明确说明未入选原因。"""

    result_ids: list[str] = Field(min_length=6, max_length=8)
    primary_axis: str = Field(min_length=1, max_length=400)
    required_features: list[str] = Field(min_length=2, max_length=4)
    exclusions: list[str] = Field(min_length=1, max_length=4)

    @field_validator("name")
    @classmethod
    def single_theme(cls, value):
        if any(char in value for char in "与和及、＆&＋+/／"):
            raise ValueError("类别必须使用单一风格名称，不能拼接多个主题")
        return value

    @field_validator("required_features", "exclusions")
    @classmethod
    def meaningful_rules(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("主题条件及排除条件不能为空")
        return value


class ExcludedCandidate(BaseModel):
    """记录未成板、同质备选或违反主题边界的候选，保证输入可追溯。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    result_id: str
    reason: str = Field(min_length=1, max_length=1600)


class CuratedClusters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clusters: list[CuratedCluster] = Field(max_length=3)
    excluded: list[ExcludedCandidate]


class CuratedClusterV3(CuratedCluster):
    """v3 将成板下限降至 4 张；v2 的冻结任务仍按 6 张校验。"""

    result_ids: list[str] = Field(min_length=4, max_length=8)


class CuratedClustersV3(CuratedClusters):
    clusters: list[CuratedClusterV3] = Field(max_length=3)
