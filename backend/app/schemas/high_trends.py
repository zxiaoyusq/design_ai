"""高潜趋势运行参数；日期只约束趋势资料，不筛选用户回答。"""

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class HighTrendRequest(BaseModel):
    start_date: date
    end_date: date
    model_id: str
    dataset: Literal["original", "article_table_2_selected_5"] = Field(default="original", description="使用已登记的数据组合，不接受任意文件路径")
    all_dates: bool = Field(default=False, description="纳入全部趋势，包括无日期数据；此时忽略日期区间")
    max_calls: int = Field(default=24, ge=1, le=100)
    prompt: str = Field(default="", max_length=4000, description="用户补充的设计关注方向和输出要求")
    user_scope: Literal["auto", "all", "first"] = Field(default="auto", description="自动识别文字范围、全部用户或前 N 位用户")
    user_limit: int | None = Field(default=None, ge=1, strict=True, description="按原始资料顺序选择的用户数，不是回答条数")

    @model_validator(mode="after")
    def validate_range(self):
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
