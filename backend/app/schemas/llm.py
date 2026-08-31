"""大模型相关 API 数据结构。"""

from pydantic import BaseModel, Field

from app.services.llm.catalog import ModelProvider


class AvailableModel(BaseModel):
    """前端可选择的模型信息。"""

    id: str = Field(description="调用模型时使用的稳定 ID")
    name: str = Field(description="界面显示名称")
    model_provider: ModelProvider = Field(description="模型使用的调用协议")


class AvailableModelList(BaseModel):
    """可用模型列表响应。"""

    models: list[AvailableModel]
