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


def dataset_paths(root, dataset="original"):
    """数据源使用固定组合，避免网页传入任意本地路径；旧任务继续保留原选择。"""
    if dataset == "article_table_2_selected_5":
        return root / "data/trend_data/article_table_2/trends.json", root / "data/userreseach_data/users_selected_5.json"
    if dataset == "original":
        return root / "data/trend_data/trends.json", root / "data/userreseach_data/users.json"
    raise ValueError("未知研究数据组合")


def prepare(root, request, output, *, dry_run, overhead):
    """预留绑定 Skill 系统文本空间，使实际消息仍在 48,000 字符预算内。"""
    trends, users = dataset_paths(root, request.dataset)
    return lean.prepare(Namespace(
        trends=str(trends), users=str(users),
        project_root=str(root), output=str(output),
        start_date=None if request.all_dates else request.start_date.isoformat(),
        end_date=None if request.all_dates else request.end_date.isoformat(),
        undated="include" if request.all_dates else "exclude", user_limit=request.user_limit, batch_chars=48000-overhead,
        max_calls=request.max_calls, map_output_tokens=None, final_output_tokens=None,
        model=request.model_id, model_parameters='{"temperature":0}',
        dry_run=dry_run, no_cache=True,
    ))
