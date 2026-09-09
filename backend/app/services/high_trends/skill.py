"""复用可分发 Skill 的代码入口，不复制分包、引用解析或图片关联规则。"""

import importlib
import sys
from argparse import Namespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = PROJECT_ROOT / "ref/design-trend-synthesizer"
# Skill 是标准库 CLI 包，内部采用同目录导入；仅加载受项目管理的固定目录。
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
lean = importlib.import_module("lean")


def prepare(root, request, output, *, dry_run, overhead):
    """预留绑定 Skill 系统文本空间，使实际消息仍在 48,000 字符预算内。"""
    return lean.prepare(Namespace(
        trends=str(root / "data/trend_data/trends.json"),
        users=str(root / "data/userreseach_data/users.json"),
        project_root=str(root), output=str(output),
        start_date=request.start_date.isoformat(), end_date=request.end_date.isoformat(),
        undated="exclude", user_limit=request.user_limit, batch_chars=48000-overhead,
        max_calls=request.max_calls, map_output_tokens=None, final_output_tokens=None,
        model=request.model_id, model_parameters='{"temperature":0}',
        dry_run=dry_run, no_cache=True,
    ))
