"""历史 R17 批次使用的 D02 Agent；冻结提示和结果身份继续可复现。"""

from functools import lru_cache
from pathlib import Path

from app.agents.dna_deep_agent import create_dna_agent


PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 既有 V2/R17 候选与批次结果仍按原冻结文本计算哈希，不能被新版 Sol R5 包覆盖。
SKILL_ROOT = PROJECT_ROOT / ".agents" / "legacy-skills" / "prism-image-dna-r17"
PROMPT_PATH = SKILL_ROOT / "references" / "r41-primary.prompt.txt"
SCHEMA_PATH = SKILL_ROOT / "references" / "r41-primary.schema.json"
SKILL_NAME = "prism-image-dna"
PROMPT_VERSION = "d02-r17-r41-selectable-model-v1"
REVIEW_VERSION = "d02-local-cmf-independent-review-v1"


@lru_cache(maxsize=1)
def skill_context() -> str:
    return (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")


def create_primary_agent(model_id: str):
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    system = (
        "你只执行 D02 prism-image-dna Skill 的单图 R17 图片 DNA 候选提取。"
        "用户选择的模型属于新候选，不得声称通过原 Astra 冻结验收。"
        "下方已给出 Skill 和冻结 R41 提示全文，不需读取其他文件。"
        "只返回符合 R41 输出协议的 JSON 对象，不要 Markdown 或说明。\n\n"
        f"<D02_SKILL>\n{skill_context()}\n</D02_SKILL>\n\n"
        f"<R41_PRIMARY_PROMPT>\n{prompt}\n</R41_PRIMARY_PROMPT>"
    )
    return create_dna_agent(model_id, system, "prism-d02-r17-candidate")


def create_review_agent(model_id: str):
    system = (
        "你是 D02 的独立视觉复核 Agent。必须重新看同一张原图，逐条核对传入的"
        "局部 CMF 观察是否属于对应对象、区域，且图片中确实可见。"
        "只核对给出的观察，不补造字段、不修改主提取输出。材质只能判视觉外观，"
        "不能断言真实材料或工艺。不确定时判 unknown，不能判 supported。"
        "返回 JSON 对象：{\"reviews\":[{\"object_index\":0,\"field_id\":\"OPT-001\","
        "\"verdict\":\"supported|contradicted|unknown\",\"reason\":\"简短视觉理由\"}]}。"
        "每个输入观察必须恰好返回一项，不要 Markdown。\n\n"
        f"<D02_SKILL>\n{skill_context()}\n</D02_SKILL>"
    )
    return create_dna_agent(model_id, system, "prism-d02-local-cmf-reviewer")
