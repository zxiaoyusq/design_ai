"""大模型元数据接口。"""

from fastapi import APIRouter

from app.schemas.llm import AvailableModel, AvailableModelList
from app.services.llm.catalog import list_models


router = APIRouter(prefix="/llm", tags=["LLM"])


@router.get("/models", response_model=AvailableModelList)
def read_available_models() -> AvailableModelList:
    """返回前端当前可以选择的模型，不包含任何连接凭据。"""

    return AvailableModelList(
        models=[
            AvailableModel.model_validate(model, from_attributes=True)
            for model in list_models()
        ]
    )
