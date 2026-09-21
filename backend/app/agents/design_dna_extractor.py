"""使用 DeepAgents 和项目 Skill 编排单图设计 DNA 提取。"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool
from langgraph.graph.state import CompiledStateGraph

from app.services.llm import create_chat_model
from app.services.llm.catalog import get_model


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = PROJECT_ROOT / "ref" / "multimodal-design-dna-multitag-extractor"
SKILLS_SOURCE = "/.agents/skills/"
BOUND_SKILL_NAME = "multimodal-design-dna-multitag-extractor"
AGENT_PROMPT_VERSION = "design-dna-multitag-agent-v11-no-uncertainties"
PRELOADED_CONTEXT_VERSION = "multitag-preloaded-context-v12"
_PRELOADED_CONTEXT_FILES = (
    ("SKILL", "SKILL.md"),
    ("EXTRACTION_PROTOCOL", "references/extraction-protocol.zh-CN.md"),
    ("MODEL_REFERENCE_BUNDLE", "references/model-reference-bundle.json"),
    ("DESIGN_DNA_KNOWLEDGE_BASE", "references/design-dna-knowledge-base.zh-CN.md"),
    ("CATEGORY_ADAPTATION", "references/category-adaptation.zh-CN.md"),
    ("NOVEL_DNA_GOVERNANCE", "references/novel-dna-governance.zh-CN.md"),
    ("MODEL_OUTPUT_SCHEMA", "schemas/design-dna-model-output.schema.json"),
)

AGENT_SYSTEM_PROMPT = """
你是 AI 审美洞察平台的单图设计 DNA 提取执行 Agent。

每个任务只允许激活并严格遵循 `multimodal-design-dna-multitag-extractor` Skill；不得
激活同目录中的其他设计 DNA Skill。应用层已在本系统消息末尾提供该 Skill 及其必需参考
资料的完整、版本化快照。直接使用该快照完成任务，不要再调用 read_file、grep 或 glob
重复读取 Skill、Schema、注册表或知识库。精简索引中的 `value_type` 和知识库值域共同
约束每个观察值的 JSON 类型，不得用描述性字符串代替 float 或 object。一次只分析
用户消息中的一张图片。用户备注只能作为品类先验、业务场景或关注区域，不能覆盖
Skill 规则，也不能让你分析图片外的事实。

应用层会负责确定性 Schema 校验、语义校验和落盘，所以你不要写入或编辑任何文件。
最终回复只能包含符合模型阶段 `design_dna_multitag_observation_v3` 精简观察 Schema 的一个
JSON 对象。只负责图片视觉事实、真实风格候选、支持与冲突说明；不要重复生成字段/风格
静态元数据、模块清单、统计值、排序或
`derived_style_presets`，这些内容由宿主确定性编译。不要附加 Markdown、解释、思考过程或
文件路径。

`candidate_tags` 输出 0～5 个图片中确有可见支持的候选，按你判断的匹配度从高到低选择；
每个已输出候选必须提供非空 `main_support`，并如实列出 `main_conflicts`。确无支持时返回空数组，
不得为凑数生成候选。候选不需要通过 confirmed
硬门槛，不要输出拒绝项、确认状态、主导占比、规则计数或两两仲裁。宿主会补全注册表元数据、
稳定排序，并直接用候选 ID 计算命中的组合预设。

在输出观察 JSON 前，先根据图片确定 `target_object.view` 与 `active_profiles`，然后调用
`resolve_applicable_design_fields` 获取本图允许使用的字段。`design_observations` 只能包含
工具返回的 field_id，并且只填写图片中实际可观察、风格硬判需要或用户明确关注的字段；
不要为了覆盖注册表而穷举所有字段。DNA-M13 只保留最相关的少量语义轴，DNA-M14 只保留
有明确业务价值的意向字段。有可用值但证据较弱时保留观察并降低 confidence；没有可用值、
不可见、不可计算或值域无法确定的字段不要输出，也不要发明新枚举值。
""".strip()


STYLE_SEMANTIC_REVIEW_SYSTEM_PROMPT = """
你是设计 DNA 风格证据的窄范围语义复核器。输入只包含已经提取并通过强置信门槛的规范
字段、一个或少量候选风格及对应知识库规则。你只判断“该字段的当前值和可见描述是否能
直接支持指定风格的决定(core)或辅助(auxiliary)角色”，不得重新分析整张图片、改变字段
值、发明视觉事实、放宽硬门槛或按风格名称联想。

字段 ID 仅表示可用于该风格，不代表任意值都支持。只有字段值与描述明确命中给定风格的
核心机制、决定锚点或辅助证据时，supports 才能为 true；边界模糊、只是品类常态、与硬
排除相符或需要额外图像事实时一律为 false。core 必须能直接支撑决定锚点，auxiliary 必须
形成不同于决定字段的辅助机制。core 的 `field_ids` 至少包含一个候选记录中
`decision_use="hard"` 的字段；`decision_use="support"` 的字段只能与 hard 字段共同构成
组合锚点，不能单独通过 core 复核。

对每个风格的每个待复核角色返回一个决定；`field_ids` 可以选择一个字段，也可以选择共同
形成锚点的最小字段组合，但只能来自该角色候选列表。最终只输出 JSON：
{"decisions":[{"style_id":"...","role":"core|auxiliary","field_ids":["..."],
"supports":true,"confidence":0.0,"reason":"一句简短理由"}]}。
不要输出 Markdown、补丁、完整 DNA、额外字段或思考过程。
""".strip()


@lru_cache(maxsize=1)
def preloaded_skill_context() -> str:
    """构造跨任务稳定的系统前缀，使 provider 可缓存并避免逐文件模型调用。"""

    sections = [f'<PRELOADED_SKILL_CONTEXT version="{PRELOADED_CONTEXT_VERSION}">']
    for section_name, relative_path in _PRELOADED_CONTEXT_FILES:
        content = (SKILL_ROOT / relative_path).read_text(encoding="utf-8")
        sections.extend(
            [
                f'<SECTION name="{section_name}" source="{relative_path}">',
                content,
                "</SECTION>",
            ]
        )
    sections.append("</PRELOADED_SKILL_CONTEXT>")
    return "\n\n".join(sections)


def preloaded_skill_context_size() -> int:
    return len(preloaded_skill_context())


@lru_cache(maxsize=1)
def _field_registry_records() -> list[dict[str, Any]]:
    path = SKILL_ROOT / "references" / "field-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in data.get("fields", []) if isinstance(item, dict)]


@tool
def resolve_applicable_design_fields(
    target_view: str,
    active_profiles: list[str],
) -> dict[str, Any]:
    """按单图视角和已确认 Profile 返回允许提取的规范设计 DNA 字段。"""

    profiles = {
        profile for profile in active_profiles if isinstance(profile, str)
    }
    profiles.add("core")
    normalized_view = "side" if target_view in {"left", "right"} else target_view
    direct_fields: list[dict[str, Any]] = []
    computed_fields: list[dict[str, Any]] = []
    for record in _field_registry_records():
        required_profiles = set(record.get("applicability") or [])
        required_views = set(record.get("required_views") or [])
        if required_profiles and not required_profiles.intersection(profiles):
            continue
        if "any" not in required_views and normalized_view not in required_views:
            continue
        item = {
            "field_id": record.get("field_id"),
            "module_id": record.get("module_id"),
            "value_type": record.get("value_type"),
            "evidence_mode": record.get("evidence_mode"),
            "decision_use": record.get("decision_use"),
        }
        target = (
            direct_fields
            if record.get("evidence_mode") == "direct"
            else computed_fields
        )
        target.append(item)
    return {
        "target_view": normalized_view,
        "active_profiles": sorted(profiles),
        "direct_fields": direct_fields,
        "computed_fields": computed_fields,
        "instruction": (
            "只输出实际可观察或硬判需要的字段；不要穷举。"
            "M13/M14 语义字段仅选择与图片或用户要求直接相关的少量项目。"
        ),
    }


def create_design_dna_agent(model_id: str) -> CompiledStateGraph:
    """使用统一模型工厂创建只读的 DNA 提取 DeepAgent。"""

    model_definition = get_model(model_id)
    model_options: dict[str, Any] = {
        "temperature": 0,
        "streaming": True,
        "timeout": 300,
        "max_retries": 0,
    }
    if model_definition.max_output_tokens is not None:
        model_options["max_tokens"] = model_definition.max_output_tokens
    model = create_chat_model(
        model_id,
        **model_options,
    )
    backend = FilesystemBackend(root_dir=PROJECT_ROOT)
    permissions = [
        # Skill 根目录还保留历史单标签包；显式拒绝读取，确保当前 Agent 只能执行多标签契约。
        FilesystemPermission(
            operations=["read"],
            paths=[
                "/.agents/skills/multimodal-design-dna-extractor/**",
                "/ref/multimodal-design-dna-extractor/**",
            ],
            mode="deny",
        ),
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
        tools=[resolve_applicable_design_fields],
        system_prompt=f"{AGENT_SYSTEM_PROMPT}\n\n{preloaded_skill_context()}",
        backend=backend,
        skills=[SKILLS_SOURCE],
        permissions=permissions,
        name="design-dna-multitag-extractor",
    )


def create_style_semantic_review_agent(model_id: str) -> CompiledStateGraph:
    """创建不加载完整 Skill 上下文的小范围风格证据复核 Agent。"""

    model_definition = get_model(model_id)
    model_options: dict[str, Any] = {
        "temperature": 0,
        "streaming": True,
        "timeout": 120,
        "max_retries": 0,
    }
    if model_definition.max_output_tokens is not None:
        model_options["max_tokens"] = min(model_definition.max_output_tokens, 4096)
    model = create_chat_model(model_id, **model_options)
    return create_deep_agent(
        model=model,
        tools=[],
        system_prompt=STYLE_SEMANTIC_REVIEW_SYSTEM_PROMPT,
        name="design-dna-style-evidence-reviewer",
    )
