"""图片人工选择的批量写入协议；revision 防止多页面覆盖。"""

from pydantic import BaseModel, Field, StrictBool


class ImageReviewSelection(BaseModel):
    revision: int = Field(ge=1)
    image_ids: list[str] = Field(min_length=1, max_length=10000)
    retained: StrictBool
