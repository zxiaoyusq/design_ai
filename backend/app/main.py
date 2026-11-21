"""FastAPI 应用入口。"""

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse

from app.api.auth import require_user, router as auth_router
from app.api.router import api_router


def create_app() -> FastAPI:
    """统一创建受登录保护的应用；测试可在独立实例中替换登录依赖。"""
    application = FastAPI(
        title="AI 审美洞察平台 API", version="0.1.0",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://gamedevcenter.ahagamecenter.com", "https://gamedevcenter.ahagamecenter.com",
        ],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    application.include_router(auth_router)
    application.include_router(api_router, prefix="/api/v1")

    @application.middleware("http")
    async def private_responses(request: Request, call_next):
        # 登录后的数据不能被浏览器、代理或共享 CDN 当作公共响应缓存。
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/api/v1/auth/login":
            # FastAPI 默认错误会回显非法输入，凭据接口必须去掉输入值。
            return JSONResponse(status_code=422, content={"detail": "请填写有效的用户名和密码"})
        return await request_validation_exception_handler(request, exc)

    @application.get("/health", include_in_schema=False)
    def health():
        """公开探活仅返回服务状态，不暴露模型、用户或业务数据。"""
        return {"status": "ok"}

    @application.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_user)])
    def openapi():
        return JSONResponse(application.openapi())

    @application.get("/docs", include_in_schema=False, dependencies=[Depends(require_user)])
    def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=application.title)

    @application.get("/redoc", include_in_schema=False, dependencies=[Depends(require_user)])
    def redoc():
        return get_redoc_html(openapi_url="/openapi.json", title=application.title)

    return application


app = create_app()
