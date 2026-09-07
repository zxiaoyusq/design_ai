"""编译与校验共用的值域解析和视角准入规则。"""
from __future__ import annotations

import re

VALUE_SPACE_ROW_PATTERN = re.compile(r"^\| ([A-Z][A-Z0-9_]*-\d{2,3}) \| (.*?) \| .*? \| .*? \| .*? \|$", re.M)

def extract_kb_value_spaces(knowledge_base: str) -> dict[str, tuple[str, set[str]]]:
    """从知识库字段表提取 enum 与受控列表值域。"""

    section = knowledge_base.split("## 四、规范字段定义", 1)[-1].split(
        "## 五、别名、合并与派生", 1
    )[0]
    spaces: dict[str, tuple[str, set[str]]] = {}
    for field_id, description in VALUE_SPACE_ROW_PATTERN.findall(section):
        type_match = re.search(
            r"；(enum|list|multi_label)(?:\s*/\s*(.*))?$", description
        )
        if not type_match:
            continue
        before_type = description[: type_match.start()]
        slash_values = (type_match.group(2) or "").strip()
        if "：" in before_type:
            raw_values = before_type.split("：", 1)[1]
        elif "、" in slash_values:
            raw_values = slash_values
        else:
            continue
        values = {
            value.strip()
            for value in re.split(r"[、,，]", raw_values)
            if value.strip()
        }
        if values:
            spaces[field_id] = (type_match.group(1), values)
    return spaces


def view_requirement_satisfied(required_views: list[str], target_view: str) -> bool:
    """左右视图统一匹配侧视图；缺少必要视角时不得确认字段。"""
    if "any" in required_views:
        return True
    normalized_view = "side" if target_view in {"left", "right"} else target_view
    return normalized_view in required_views
