"""平台登录、退出与当前会话接口。"""

from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.services.auth import COOKIE_NAME, AuthService, CurrentUser, get_auth_service


router = APIRouter(tags=["auth"])
_LOGIN_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "login.html"


class LoginRequest(BaseModel):
    """密码通过请求体传入，不接受 URL 参数，也不在模型打印时显示明文。"""

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=512)


def validate_origin(request: Request, service: AuthService) -> None:
    """Cookie 认证的写请求只接受当前站点或明确配置的前端 Origin。"""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "请求来源不受信任")
    origin = request.headers.get("origin")
    if not origin:
        return  # 命令行和服务端客户端没有浏览器 Origin。
    allowed = {value.strip().rstrip("/") for value in service.settings.allowed_origins.split(",") if value.strip()}
    allowed.add(str(request.base_url).rstrip("/"))
    if origin not in allowed:
        raise HTTPException(403, "请求来源不受信任")


def require_user(request: Request, service: AuthService = Depends(get_auth_service)) -> CurrentUser:
    """所有业务路由共用登录依赖，包含图片、下载和后台任务入口。"""
    validate_origin(request, service)
    try:
        user = service.current_user(request.cookies.get(COOKIE_NAME))
    except SQLAlchemyError:
        raise HTTPException(503, "登录服务暂时不可用，请稍后重试") from None
    if user is None:
        raise HTTPException(401, "请先登录", headers={"Cache-Control": "no-store"})
    return user


def secure_cookie(request: Request, service: AuthService) -> bool:
    """TLS 终止代理可能不传协议；经来源校验后的 HTTPS Origin 也表示安全上下文。"""
    return (
        service.settings.cookie_secure
        or request.url.scheme == "https"
        or request.headers.get("origin", "").startswith("https://")
    )


def safe_return_path(value: str | None) -> str:
    """回跳仅允许本站绝对路径，拒绝协议相对地址、反斜杠和登录循环。"""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    decoded = unquote(value)
    if decoded.startswith("//") or "\\" in decoded or any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        return "/"
    path = urlsplit(decoded)
    return "/" if path.scheme or path.netloc or path.path.lower().rstrip("/") == "/login" else value


@router.get("/login", include_in_schema=False)
def login_page(request: Request, service: AuthService = Depends(get_auth_service)):
    """登录页独立于受保护的前端资源，使静态交付与旧构建也能统一设防。"""
    try:
        user = service.current_user(request.cookies.get(COOKIE_NAME))
    except SQLAlchemyError:
        user = None
    if user:
        return RedirectResponse(safe_return_path(request.query_params.get("next")), status_code=303)
    return FileResponse(_LOGIN_TEMPLATE, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


@router.post("/api/v1/auth/login", response_model=CurrentUser)
def login(payload: LoginRequest, request: Request, response: Response, service: AuthService = Depends(get_auth_service)):
    """成功时建立 HttpOnly 会话；所有凭据错误使用同一提示。"""
    validate_origin(request, service)
    try:
        result = service.login(payload.username.strip(), payload.password.get_secret_value(), request.cookies.get(COOKIE_NAME))
    except SQLAlchemyError:
        raise HTTPException(503, "登录服务暂时不可用，请稍后重试") from None
    if result is None:
        raise HTTPException(401, "用户名或密码错误；连续失败后请稍候重试")
    user, token = result
    response.set_cookie(
        COOKIE_NAME, token, max_age=service.settings.session_seconds, httponly=True,
        secure=secure_cookie(request, service), samesite="lax", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return asdict(user)


@router.get("/api/v1/auth/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(require_user)):
    """供前端、Vite 和 Nginx 检查当前会话，不返回令牌。"""
    return asdict(user)


@router.post("/api/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, service: AuthService = Depends(get_auth_service)):
    """允许已过期会话退出，并同步清除浏览器 Cookie。"""
    validate_origin(request, service)
    try:
        service.logout(request.cookies.get(COOKIE_NAME))
    except SQLAlchemyError:
        raise HTTPException(503, "登录服务暂时不可用，请稍后重试") from None
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=secure_cookie(request, service))
    response.headers["Cache-Control"] = "no-store"
    # 清除升级登录体系前可能已缓存的资源，不删除用户保存的工作区设置。
    response.headers["Clear-Site-Data"] = '"cache"'
