"""预载 Skill 阶段的 DeepAgents 入口：显式工具、逐次预算、完整输入。"""

from collections.abc import Sequence

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

AGENT_RUNTIME_VERSION = "bounded-deepagents-v1"


class StagePolicyMiddleware(AgentMiddleware):
    """工具可见性与执行权限分别校验；同步和异步遵循相同的阶段契约。"""

    def __init__(self, system_prompt: str, tools: Sequence[BaseTool], max_input_chars: int | None):
        self.system_prompt = system_prompt
        self.allowed_tools = frozenset(tool.name for tool in tools)
        self.max_input_chars = max_input_chars

    def _request(self, request: ModelRequest) -> ModelRequest:
        if self.max_input_chars is not None:
            size = len(self.system_prompt) + sum(len(str(m.content)) for m in request.messages)
            if size > self.max_input_chars:
                raise ValueError("本次模型输入超过字符预算")
        # tools=[] 只是应用工具列表，DeepAgents 仍会注入 task 等内建工具。
        # 固定系统消息避免无关工具说明混入已冻结的 Skill 快照。
        return request.override(
            tools=[tool for tool in request.tools if getattr(tool, "name", None) in self.allowed_tools],
            tool_choice=None,
            system_message=SystemMessage(content=self.system_prompt),
        )

    def _check_tool(self, name: str) -> None:
        if name not in self.allowed_tools:
            raise RuntimeError("本阶段禁止调用工具或子代理：" + name)

    def _response(self, response: ModelResponse) -> ModelResponse:
        # 在进入工具节点前拒绝越权响应，包括同一回复中混有合法/非法调用的情况。
        for message in response.result:
            if isinstance(message, AIMessage):
                if message.invalid_tool_calls:
                    raise RuntimeError("模型返回了无法解析的工具调用，阶段已停止")
                for call in message.tool_calls:
                    self._check_tool(call["name"])
        return response

    def wrap_model_call(self, request, handler):
        return self._response(handler(self._request(request)))

    async def awrap_model_call(self, request, handler):
        return self._response(await handler(self._request(request)))

    def wrap_tool_call(self, request, handler):
        self._check_tool(request.tool_call["name"])
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        self._check_tool(request.tool_call["name"])
        return await handler(request)


def create_bounded_agent(
    *,
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    tools: Sequence[BaseTool] = (),
    model_call_limit: int = 1,
    max_input_chars: int | None = None,
) -> CompiledStateGraph:
    """Skill 由宿主预载；无工具阶段仅一次推理，有工具阶段最多执行一次业务工具。

    不接入工作区文件系统或自动摘要，避免读取宿主文件、丢失原始证据与隐式模型费用。
    预算由官方中间件保存在本次图运行状态中，同一 Agent 的不同调用不共享计数。
    """
    backend = StateBackend()
    middleware = [
        FilesystemMiddleware(
            # 当前 SDK 强制保留 read_file；阶段策略会将它隐藏并拒绝执行。
            backend=backend, tools=["read_file"],
            human_message_token_limit_before_evict=None,
            tool_token_limit_before_evict=None,
        ),
        # 官方支持按 .name 替换默认中间件。LangChain 的 trigger=None 不做摘要，
        # 同时移除 DeepAgents 摘要器在上下文溢出时自动压缩/补调的行为。
        SummarizationMiddleware(model=model, trigger=None),
        ModelCallLimitMiddleware(run_limit=model_call_limit, exit_behavior="error"),
        StagePolicyMiddleware(system_prompt, tools, max_input_chars),
    ]
    if tools:
        middleware.append(ToolCallLimitMiddleware(run_limit=1, exit_behavior="error"))
    return create_deep_agent(
        model=model, tools=list(tools), system_prompt=system_prompt,
        backend=backend, middleware=middleware, name=name,
    )
