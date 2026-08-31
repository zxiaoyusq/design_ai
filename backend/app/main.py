"""FastAPI 应用入口。"""

from fastapi import FastAPI

from app.api.router import api_router


app = FastAPI(title="AI 审美洞察平台 API", version="0.1.0")
app.include_router(api_router, prefix="/api/v1")
