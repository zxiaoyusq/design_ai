"""登录配置、密码校验和 PostgreSQL 会话存储。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import hashlib
import hmac
from pathlib import Path
import secrets

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.auth import AuthSession, AuthUser


COOKIE_NAME = "design_ai_session"
PASSWORD_ITERATIONS = 600_000
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class AuthSettings(BaseSettings):
    """独立账号数据库配置；生产账号和会话均由 PostgreSQL 持久化。"""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=True, populate_by_name=True,
    )
    database_url: SecretStr = Field(validation_alias="AUTH_DATABASE_URL")
    session_seconds: int = Field(default=43_200, ge=60, le=2_592_000, validation_alias="AUTH_SESSION_SECONDS")
    cookie_secure: bool = Field(default=False, validation_alias="AUTH_COOKIE_SECURE")
    # Origin 必须精确匹配；自定义部署域名通过环境配置显式加入。
    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,"
        "http://127.0.0.1:5174,http://gamedevcenter.ahagamecenter.com,"
        "https://gamedevcenter.ahagamecenter.com",
        validation_alias="AUTH_ALLOWED_ORIGINS",
    )


@dataclass(frozen=True)
class CurrentUser:
    """可向浏览器返回的账号信息，不包含密码或会话令牌。"""

    username: str
    role: str


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 使用随机盐和带版本参数的存储格式。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """摘要使用恒定时间比较；损坏或不支持的存储值不能登录。"""
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    # SQLite 离线测试会去掉时区；数据库时间的业务含义始终为 UTC。
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AuthService:
    """账号和会话操作共用短事务；令牌、明文密码均不写入日志和数据库。"""

    def __init__(self, settings: AuthSettings, engine: Engine | None = None):
        self.settings = settings
        self.engine = engine or create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
        # 未知账号也执行同等成本的校验，避免通过响应时间枚举用户名。
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))

    def login(self, username: str, password: str, previous_token: str | None = None) -> tuple[CurrentUser, str] | None:
        """连续五次失败暂停该账号登录一分钟；成功后轮换当前浏览器会话。"""
        now = datetime.now(UTC)
        with Session(self.engine) as db, db.begin():
            user = db.scalar(select(AuthUser).where(AuthUser.username == username).with_for_update())
            matches = verify_password(password, user.password_hash if user else self._dummy_hash)
            if user is None or not user.is_active:
                return None
            if user.locked_until and _utc(user.locked_until) > now:
                return None
            if not matches:
                user.failed_logins += 1
                if user.failed_logins >= 5:
                    user.locked_until = now + timedelta(minutes=1)
                    user.failed_logins = 0
                return None
            user.failed_logins = 0
            user.locked_until = None
            db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
            if previous_token:
                db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(previous_token)))
            token = secrets.token_urlsafe(32)
            db.add(AuthSession(
                token_hash=_token_hash(token), user_id=user.id, created_at=now,
                expires_at=now + timedelta(seconds=self.settings.session_seconds),
            ))
            return CurrentUser(user.username, user.role), token

    def current_user(self, token: str | None) -> CurrentUser | None:
        """每次访问检查会话有效期和账号状态，使退出、禁用和改密立即生效。"""
        if not token or len(token) > 128:
            return None
        with Session(self.engine) as db:
            user = db.scalar(
                select(AuthUser).join(AuthSession).where(
                    AuthSession.token_hash == _token_hash(token),
                    AuthSession.expires_at > datetime.now(UTC), AuthUser.is_active.is_(True),
                )
            )
            return CurrentUser(user.username, user.role) if user else None

    def logout(self, token: str | None) -> None:
        """只撤销当前会话，其他已登录设备可继续工作。"""
        if token:
            with Session(self.engine) as db, db.begin():
                db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))

    def create_admin(self, username: str, password: str) -> None:
        """显式管理命令创建账号；已有账号不被重置或覆盖。"""
        self._validate_credentials(username, password)
        with Session(self.engine) as db, db.begin():
            if db.scalar(select(AuthUser.id).where(AuthUser.username == username)) is not None:
                raise ValueError("该用户名已存在")
            db.add(AuthUser(
                username=username, password_hash=hash_password(password),
                role="admin", is_active=True, created_at=datetime.now(UTC),
            ))

    def set_password(self, username: str, password: str) -> None:
        """改密后撤销该账号的全部会话，要求各设备重新登录。"""
        self._validate_credentials(username, password)
        with Session(self.engine) as db, db.begin():
            user = db.scalar(select(AuthUser).where(AuthUser.username == username).with_for_update())
            if user is None:
                raise ValueError("账号不存在")
            user.password_hash = hash_password(password)
            user.failed_logins = 0
            user.locked_until = None
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))

    @staticmethod
    def _validate_credentials(username: str, password: str) -> None:
        if not username or username != username.strip() or len(username) > 128:
            raise ValueError("用户名应为 1–128 个字符，首尾不能包含空白")
        if not 6 <= len(password) <= 512:
            raise ValueError("密码应为 6–512 个字符")


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """按进程复用连接池，连接配置不会发送给前端。"""
    return AuthService(AuthSettings())
