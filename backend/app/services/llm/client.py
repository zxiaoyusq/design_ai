"""基于模型目录创建并调用 LangChain ChatModel。"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, TypeAlias

from langchain.chat_models import init_chat_model as langchain_init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.services.llm.catalog import ModelProvider, get_model
from app.services.llm.settings import LLMSettings, get_llm_settings


ModelInput: TypeAlias = str | Sequence[BaseMessage]

# 连接信息只能由统一配置层注入，调用方不能通过模型参数绕过网关。
_RESERVED_MODEL_OPTIONS = frozenset(
    {
        "model",
        "model_provider",
        "api_key",
        "openai_api_key",
        "anthropic_api_key",
        "base_url",
    }
)


def create_chat_model(
    model_id: str,
    *,
    settings: LLMSettings | None = None,
    **model_options: Any,
) -> BaseChatModel:
    """创建目录内模型的 LangChain 客户端。

    `temperature`、`max_tokens` 等模型参数可由调用方传入；模型、provider、Key
    和调用地址由本模块统一控制。
    """

    overridden_options = _RESERVED_MODEL_OPTIONS.intersection(model_options)
    if overridden_options:
        option_names = ", ".join(sorted(overridden_options))
        raise ValueError(f"以下连接参数不允许覆盖：{option_names}")

    model = get_model(model_id)
    llm_settings = settings or get_llm_settings()
    connection_options: dict[str, Any] = {}

    # LangChain 的 Anthropic 与 OpenAI 集成使用不同的密钥参数名。
    if model.model_provider is ModelProvider.ANTHROPIC:
        connection_options["base_url"] = llm_settings.base_url
        connection_options["anthropic_api_key"] = llm_settings.api_key
    elif model.model_provider is ModelProvider.OPENAI:
        # 当前网关的 OpenAI 兼容接口位于 `/v1`；已配置时不重复追加。
        connection_options["base_url"] = _openai_base_url(llm_settings.base_url)
        connection_options["api_key"] = llm_settings.api_key
    else:  # pragma: no cover - 新 provider 必须先显式补充连接适配。
        raise ValueError(f"尚未配置 provider：{model.model_provider}")

    return langchain_init_chat_model(
        model=model.id,
        model_provider=model.model_provider.value,
        **connection_options,
        **model_options,
    )


def _openai_base_url(base_url: str) -> str:
    """规范化 OpenAI 兼容接口地址。"""

    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


def invoke_model(
    model_id: str,
    model_input: ModelInput,
    *,
    model_options: Mapping[str, Any] | None = None,
    settings: LLMSettings | None = None,
    **invoke_options: Any,
) -> BaseMessage:
    """同步调用指定模型并返回完整消息。"""

    model = create_chat_model(
        model_id,
        settings=settings,
        **dict(model_options or {}),
    )
    return model.invoke(model_input, **invoke_options)


def stream_model(
    model_id: str,
    model_input: ModelInput,
    *,
    model_options: Mapping[str, Any] | None = None,
    settings: LLMSettings | None = None,
    **stream_options: Any,
) -> Iterator[BaseMessage]:
    """流式调用指定模型并逐块返回消息。"""

    model = create_chat_model(
        model_id,
        settings=settings,
        **dict(model_options or {}),
    )
    return model.stream(model_input, **stream_options)
