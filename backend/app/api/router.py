"""后端 API 路由汇总。"""

from fastapi import APIRouter

from app.api.dna import router as dna_router
from app.api.llm import router as llm_router
from app.api.high_trends import router as high_trends_router
from app.api.high_trend_image_review import router as high_trend_image_review_router


api_router = APIRouter()
api_router.include_router(llm_router)
api_router.include_router(dna_router)
api_router.include_router(high_trends_router)
api_router.include_router(high_trend_image_review_router)
