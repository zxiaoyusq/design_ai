"""人工通过／不通过与恢复未审核的版本化写入契约。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class TrendQualitySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    image_ids: list[str] = Field(min_length=1, max_length=1000)
    decision: Literal['PASS', 'FAIL'] | None
