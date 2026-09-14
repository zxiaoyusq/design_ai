"""平台允许使用的大模型目录。

调用层与模型列表 API 都必须从这里读取模型信息，避免模型 ID 和 provider
映射散落在业务代码中。
"""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class ModelProvider(StrEnum):
    """LangChain `init_chat_model` 使用的模型协议提供方。"""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    """可用模型及其调用协议的只读定义。"""

    id: str
    name: str
    model_provider: ModelProvider
    # 仅记录供应商明确公布且调用协议必须传入的最大输出值。
    max_output_tokens: int | None = None


_MODELS = (
    ModelDefinition(
        id="claude-opus-5-20260820",
        name="Claude Opus 5",
        model_provider=ModelProvider.ANTHROPIC,
        max_output_tokens=128_000,
    ),
    ModelDefinition(
        id="gpt-5.6-terra",
        name="GPT-5.6 Terra",
        model_provider=ModelProvider.OPENAI,
    ),
    ModelDefinition(
        id="gpt-5.6-sol",
        name="GPT-5.6 Sol",
        model_provider=ModelProvider.OPENAI,
    ),
    ModelDefinition(
        id="MiniMax-M3",
        name="MiniMax M3",
        model_provider=ModelProvider.OPENAI,
    ),
    ModelDefinition(
        id="qwen3.8-max-20260820",
        name="Qwen 3.8 Max",
        model_provider=ModelProvider.OPENAI,
    ),
    ModelDefinition(
        id="deepseek-v4-pro-official",
        name="deepseek v4.1 flash",
        model_provider=ModelProvider.OPENAI,
    ),
    ModelDefinition(
        id="gemini-3.7-flash",
        name="gemini 3.7 flash",
        model_provider=ModelProvider.OPENAI,
    ),
)

_MODELS_BY_ID = MappingProxyType({model.id: model for model in _MODELS})


def list_models() -> tuple[ModelDefinition, ...]:
    """返回平台当前允许选择的全部模型。"""

    return _MODELS


def get_model(model_id: str) -> ModelDefinition:
    """按 ID 获取模型定义，不允许调用目录之外的模型。"""

    try:
        return _MODELS_BY_ID[model_id]
    except KeyError as exc:
        available_ids = ", ".join(_MODELS_BY_ID)
        raise ValueError(
            f"不支持模型 {model_id!r}，可用模型：{available_ids}"
        ) from exc
