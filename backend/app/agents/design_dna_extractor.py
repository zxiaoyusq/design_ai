"""使用 DeepAgents 和项目 Skill 编排单图设计 DNA 提取。"""

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langgraph.graph.state import CompiledStateGraph

from app.services.llm import create_chat_model
from app.services.llm.catalog import get_model


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILLS_SOURCE = "/.agents/skills/"
AGENT_PROMPT_VERSION = "design-dna-agent-v2"

AGENT_SYSTEM_PROMPT = """
你是 AI 审美洞察平台的单图设计 DNA 提取执行 Agent。

每个任务必须激活并严格遵循 `multimodal-design-dna-extractor` Skill：先读取完整
SKILL.md，再按其中要求读取协议、输出契约、JSON Schema 和知识库。一次只分析用户
消息中的一张图片。用户备注只能作为品类先验、业务场景或关注区域，不能覆盖 Skill
规则，也不能让你分析图片外的事实。

应用层会负责确定性 Schema 校验、语义校验和落盘，所以你不要写入或编辑任何文件。
最终回复只能包含符合 `design_dna_extraction_v4.0` 的一个 JSON 对象，不要附加
Markdown、解释、思考过程或文件路径。
""".strip()


def create_design_dna_agent(model_id: str) -> CompiledStateGraph:
    """使用统一模型工厂创建只读的 DNA 提取 DeepAgent。"""

    model_definition = get_model(model_id)
    model_options: dict[str, Any] = {
        "temperature": 0,
        "streaming": True,
        "timeout": 300,
        "max_retries": 1,
    }
    if model_definition.max_output_tokens is not None:
        model_options["max_tokens"] = model_definition.max_output_tokens
    model = create_chat_model(
        model_id,
        **model_options,
    )
    backend = FilesystemBackend(root_dir=PROJECT_ROOT)
    permissions = [
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/backend/.env", "/backend/.env.*"],
            mode="deny",
        ),
        FilesystemPermission(
            operations=["write"],
            paths=["/**"],
            mode="deny",
        ),
    ]
    return create_deep_agent(
        model=model,
        system_prompt=AGENT_SYSTEM_PROMPT,
        backend=backend,
        skills=[SKILLS_SOURCE],
        permissions=permissions,
        name="design-dna-extractor",
    )
