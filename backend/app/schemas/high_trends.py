"""高潜趋势运行参数；日期只约束趋势资料，不筛选用户回答。"""

from datetime import date
from pydantic import BaseModel, Field, model_validator


class HighTrendRequest(BaseModel):
    start_date: date
    end_date: date
    model_id: str
    max_calls: int = Field(default=24, ge=1, le=100)
    prompt: str = Field(default="", max_length=4000, description="用户补充的设计关注方向和输出要求")

    @model_validator(mode="after")
    def validate_range(self):
        if self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class HighTrendResumeRequest(BaseModel):
    """继续沿用原始范围和模型，仅允许显式调整累计调用预算。"""
    max_calls: int | None = Field(default=None, ge=1, le=100)
