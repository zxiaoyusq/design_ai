"""登录边界使用独立临时库验证，不触碰真实账号或调用模型。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.api.auth import safe_return_path
from app.main import create_app
from app.models.auth import AuthBase, AuthSession, AuthUser
from app.services.auth import (
    COOKIE_NAME, AuthService, AuthSettings, get_auth_service, hash_password, verify_password,
)


class AuthTests(unittest.TestCase):
    """真实密码摘要、Cookie 和服务端会话覆盖完整登录生命周期。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'auth.db'}", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        AuthBase.metadata.create_all(self.engine)
        settings = AuthSettings(
            _env_file=None, database_url="sqlite://", allowed_origins="http://trusted.example,https://trusted.example",
        )
        self.service = AuthService(settings, self.engine)
        self.service.create_admin("test-admin", "fixture-password")
        self.app = create_app()
        self.app.dependency_overrides[get_auth_service] = lambda: self.service
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def login(self, client=None, **extra):
        return (client or self.client).post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "fixture-password"}, **extra,
        )

    def test_every_business_route_and_api_docs_require_login(self):
        count = 0
        for path, operations in self.app.openapi()["paths"].items():
            if path.startswith("/api/v1/auth/"):
                continue
            for method in operations:
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                concrete_path = re.sub(r"\{[^}]+\}", "fixture", path)
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.client.request(method, concrete_path).status_code, 401)
                count += 1
        self.assertGreater(count, 40)
        for path in ("/docs", "/redoc", "/openapi.json", "/api/v1/auth/me"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_login_refresh_logout_and_token_replay(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"username": "test-admin", "role": "admin"})
        cookie = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "SameSite=lax", "Max-Age=43200", "Path=/"):
            self.assertIn(attribute, cookie)
        token = self.client.cookies[COOKIE_NAME]
        with Session(self.engine) as db:
            stored = db.scalar(select(AuthSession))
            self.assertNotEqual(stored.token_hash, token)
            self.assertNotIn("fixture-password", db.scalar(select(AuthUser)).password_hash)
        self.assertEqual(self.client.get("/api/v1/llm/models").status_code, 200)
        # 另一服务实例可恢复会话，证明登录状态不只存在于某个进程内。
        restarted = AuthService(self.service.settings, self.engine)
        self.assertEqual(restarted.current_user(token).username, "test-admin")
        logout = self.client.post("/api/v1/auth/logout")
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(logout.headers.get("clear-site-data"), '"cache"')
        self.assertNotIn(COOKIE_NAME, self.client.cookies)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code, 401)

    def test_wrong_unknown_or_inactive_account_has_same_error(self):
        for username in ("test-admin", "missing-user"):
            response = self.client.post("/api/v1/auth/login", json={"username": username, "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("set-cookie", response.headers)
            if username == "test-admin":
                expected = response.json()
            else:
                self.assertEqual(response.json(), expected)
        with Session(self.engine) as db, db.begin():
            db.execute(update(AuthUser).values(is_active=False))
        self.assertEqual(self.login().json(), expected)

    def test_malformed_login_does_not_echo_secret(self):
        for body in ({"password": "private-password"}, {"username": "test-admin", "password": "x" * 513}):
            response = self.client.post("/api/v1/auth/login", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json(), {"detail": "请填写有效的用户名和密码"})

    def test_expired_tampered_and_disabled_sessions_are_rejected(self):
        self.login()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Cookie": f"{COOKIE_NAME}=invented"}).status_code, 401)
        with Session(self.engine) as db, db.begin():
            db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        self.login()
        with Session(self.engine) as db, db.begin():
            db.execute(update(AuthUser).values(is_active=False))
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_login_rotates_token_and_password_change_revokes_all_sessions(self):
        self.login()
        old = self.client.cookies[COOKIE_NAME]
        self.login()
        current = self.client.cookies[COOKIE_NAME]
        self.assertNotEqual(old, current)
        self.assertIsNone(self.service.current_user(old))
        self.service.set_password("test-admin", "updated-password")
        self.assertIsNone(self.service.current_user(current))
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"username": "test-admin", "password": "updated-password"}).status_code, 200)

    def test_logout_does_not_revoke_another_device(self):
        self.login()
        with TestClient(self.app) as other:
            self.login(other)
            self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 204)
            self.assertEqual(other.get("/api/v1/auth/me").status_code, 200)

    def test_failures_lock_account_until_pause_expires(self):
        for _ in range(5):
            self.client.post("/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"})
        self.assertEqual(self.login().status_code, 401)
        restarted = AuthService(self.service.settings, self.engine)
        self.assertIsNone(restarted.login("test-admin", "fixture-password"))
        with Session(self.engine) as db, db.begin():
            db.execute(update(AuthUser).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        self.assertEqual(self.login().status_code, 200)

    def test_cross_site_mutations_are_rejected(self):
        self.assertEqual(self.login(headers={"Origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.login(headers={"Origin": "https://trusted.example", "Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.login(headers={"Origin": "http://trusted.example"}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/dna/images", headers={"Origin": "https://attacker.example"}).status_code, 403)

    def test_https_sets_secure_cookie_and_login_page_redirects_safely(self):
        with TestClient(self.app, base_url="https://testserver") as https:
            self.assertIn("Secure", self.login(https).headers["set-cookie"])
            response = https.get("/login?next=/moodboards", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/moodboards")
        for value in ("//evil.example", "https://evil.example", "/\\evil", "/login", "/\n/evil", "/%5cevil", "/%2flogin", "/LOGIN"):
            self.assertEqual(safe_return_path(value), "/")
        self.assertEqual(safe_return_path("/high-trends?a=1&b=2"), "/high-trends?a=1&b=2")

    def test_tls_termination_without_forwarded_scheme_preserves_secure_cookie(self):
        response = self.login(headers={"Origin": "https://trusted.example"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])

    def test_password_salts_and_duplicate_account_protection(self):
        first, second = hash_password("same-password"), hash_password("same-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("same-password", first))
        self.assertFalse(verify_password("incorrect", first))
        self.assertFalse(verify_password("same-password", "invalid-hash"))
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.service.create_admin("test-admin", "other-password")
        self.assertEqual(self.login().status_code, 200)


if __name__ == "__main__":
    unittest.main()
