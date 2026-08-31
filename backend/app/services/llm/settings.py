"""大模型网关配置。"""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parents[3]


class LLMSettings(BaseSettings):
    """只从环境变量或后端 `.env` 读取的大模型连接配置。"""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    llm_key: SecretStr = Field(validation_alias="LLM_KEY")
    llm_url: AnyHttpUrl = Field(validation_alias="LLM_URL")

    @property
    def api_key(self) -> str:
        """仅在构造模型客户端时解开密钥。"""

        return self.llm_key.get_secret_value()

    @property
    def base_url(self) -> str:
        """返回不带末尾斜杠的网关地址，避免 SDK 重复拼接路径。"""

        return str(self.llm_url).rstrip("/")


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    """进程内只加载一次连接配置。"""

    return LLMSettings()
