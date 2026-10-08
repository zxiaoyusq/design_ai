"""D02 两代图片解析共用的受限 DeepAgent 模型入口。"""

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.middleware.types import AgentMiddleware

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


class SingleImageRequestMiddleware(AgentMiddleware):
    """批量单图阶段不暴露内建工具；拒绝意外工具调用，防止子代理增加费用。"""

    def wrap_model_call(self, request, handler):
        return handler(request.override(tools=[], tool_choice=None))

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(tools=[], tool_choice=None))

    def wrap_tool_call(self, request, handler):
        raise RuntimeError("单图DNA阶段禁止调用工具或子代理")

    async def awrap_tool_call(self, request, handler):
        raise RuntimeError("单图DNA阶段禁止调用工具或子代理")


def create_dna_agent(model_id: str, system_prompt: str, name: str, *, reasoning_effort: str = "low",
                     single_request: bool = False):
    """只允许模型看传入图片和提示；模型选择由工程目录校验，网络失败不自动重试。"""

    model = create_chat_model(model_id, **_model_options(model_id, reasoning_effort=reasoning_effort))
    permissions = [FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny")]
    backend = FilesystemBackend(root_dir=PROJECT_ROOT)
    middleware = [FilesystemMiddleware(backend=backend, tools=["read_file"], _permissions=permissions)]
    if single_request:
        middleware.extend([SingleImageRequestMiddleware(), ModelCallLimitMiddleware(run_limit=1, exit_behavior="error")])
    return create_deep_agent(
        model=model,
        tools=[],
        system_prompt=system_prompt,
        backend=backend,
        skills=[],
        permissions=permissions,
        middleware=middleware,
        name=name,
    )
