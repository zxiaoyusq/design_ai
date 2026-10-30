"""D02 两代图片解析共用的受限 DeepAgent 模型入口。"""

from pathlib import Path

from app.agents.bounded import create_bounded_agent
from app.services.llm import create_chat_model
from app.services.llm.catalog import get_model


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _model_options(model_id: str, *, reasoning_effort: str = "low") -> dict:
    definition = get_model(model_id)
    options = {"streaming": True, "timeout": 600, "max_retries": 0}
    if model_id == "gpt-6-sol":
        # 网关的 Chat Completions 不接受该模型同时使用推理与 DeepAgents 工具。
        if reasoning_effort not in {"low", "medium"}:
            raise ValueError("GPT-6 Sol 的 DNA 推理强度仅支持 low 或 medium")
        options.update(use_responses_api=True, reasoning={"effort": reasoning_effort})
    else:
        if reasoning_effort != "low":
            raise ValueError("只有 GPT-6 Sol 支持本批次的推理强度覆盖")
        options["temperature"] = 0
    if definition.max_output_tokens is not None:
        options["max_tokens"] = definition.max_output_tokens
    return options


def create_dna_agent(model_id: str, system_prompt: str, name: str, *, reasoning_effort: str = "low",
                     single_request: bool = True):
    """只分析传入图片；兼容旧 single_request 参数，所有无工具阶段均限制单次请求。"""

    model = create_chat_model(model_id, **_model_options(model_id, reasoning_effort=reasoning_effort))
    return create_bounded_agent(model=model, system_prompt=system_prompt, name=name)
