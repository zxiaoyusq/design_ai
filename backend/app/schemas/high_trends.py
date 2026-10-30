"""高潜趋势运行参数；日期只约束趋势资料，不筛选用户回答。"""

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class HighTrendRequest(BaseModel):
    # 新流程消费模块的已选输出；raw 默认值用于兼容历史客户端与任务。
    input_mode: Literal["raw", "module_outputs"] = "raw"
    research_output_ids: list[str] = Field(default_factory=list, max_length=200)
    trend_result_id: str | None = Field(default=None, max_length=160)
    input_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    start_date: date | None = None
    end_date: date | None = None
    model_id: str
    dataset: Literal["original", "article_table_2_selected_5"] = Field(default="original", description="使用已登记的数据组合，不接受任意文件路径")
    all_dates: bool = Field(default=False, description="纳入全部趋势，包括无日期数据；此时忽略日期区间")
    max_calls: int = Field(default=24, ge=1, le=100)
    prompt: str = Field(default="", max_length=4000, description="用户补充的设计关注方向和输出要求")
    user_scope: Literal["auto", "all", "first"] = Field(default="auto", description="自动识别文字范围、全部用户或前 N 位用户")
    user_limit: int | None = Field(default=None, ge=1, strict=True, description="按原始资料顺序选择的用户数，不是回答条数")

    @model_validator(mode="after")
    def validate_range(self):
        if self.input_mode == "module_outputs":
            if not self.research_output_ids or not self.trend_result_id:
                raise ValueError("请选择用研聚合结果和趋势洞察结果")
            if len(set(self.research_output_ids)) != len(self.research_output_ids):
                raise ValueError("用研聚合结果不能重复选择")
            if self.user_limit is not None or self.user_scope == "first":
                raise ValueError("模块结果模式使用已选用研范围，不能再按前 N 位筛选")
            return self
        if self.research_output_ids or self.trend_result_id:
            raise ValueError("选择模块结果时请使用模块结果模式")
        if not self.all_dates and (self.start_date is None or self.end_date is None):
            raise ValueError("请选择趋势起止日期，或选择全部日期")
        if not self.all_dates and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if self.user_scope == "first" and self.user_limit is None:
            raise ValueError("请选择前几位用户")
        if self.user_scope != "first" and self.user_limit is not None:
            raise ValueError("填写用户数量时，请选择前 N 位用户模式")
        return self


class HighTrendResumeRequest(BaseModel):
    """继续沿用原始范围和模型，仅允许显式调整累计调用预算。"""
    max_calls: int | None = Field(default=None, ge=1, le=100)
