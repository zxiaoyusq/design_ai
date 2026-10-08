"""冻结 Sol R5 的资产入口；提取直接执行同事 CLI，不再改写提示。"""

from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "prism-dna-sol-r5"
PRIMARY_PROMPT_PATH = SKILL_ROOT / "assets" / "primary.prompt.txt"
PRIMARY_SCHEMA_PATH = SKILL_ROOT / "assets" / "primary.schema.json"
SKILL_NAME = "prism-dna-sol-r5"
PROMPT_VERSION = "sol-coverage-dna-r5-20260929-codex-frozen-v2"
FROZEN_MODEL = "gpt-6-sol"


@lru_cache(maxsize=1)
def skill_context() -> str:
    return (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")


def primary_system_prompt() -> str:
    """兼容历史离线脚本读取名称，返回逐字冻结资产，不附加工程说明。"""
    return PRIMARY_PROMPT_PATH.read_text(encoding="utf-8")
