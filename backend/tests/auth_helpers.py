"""业务接口测试使用独立应用和已登录身份，避免依赖真实账号数据库。"""

from fastapi.testclient import TestClient

from app.api.auth import require_user
from app.main import create_app
from app.services.auth import CurrentUser


def authenticated_client() -> TestClient:
    """仅在测试应用内覆盖身份依赖，业务规则仍通过真实路由执行。"""
    application = create_app()
    application.dependency_overrides[require_user] = lambda: CurrentUser("test-admin", "admin")
    return TestClient(application)
