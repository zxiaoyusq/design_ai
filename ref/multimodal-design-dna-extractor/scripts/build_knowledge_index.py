#!/usr/bin/env python3
"""Generate the stable knowledge index from style and field registries."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STYLE_REGISTRY = ROOT / "references/style-registry.json"
FIELD_REGISTRY = ROOT / "references/field-registry.json"
DEFAULT_OUTPUT = ROOT / "references/knowledge-index.zh-CN.md"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 根节点必须是对象")
    return value


def _render() -> str:
    styles = _load(STYLE_REGISTRY)
    fields = _load(FIELD_REGISTRY)
    if styles.get("knowledge_base_version") != fields.get("knowledge_base_version"):
        raise ValueError("style/field registry 知识库版本不一致")

    parent_order = [item["parent_style_id"] for item in styles.get("parents", [])]
    parent_names = {
        item["parent_style_id"]: item["display_name"]
        for item in styles.get("parents", [])
    }
    active_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deprecated: list[dict[str, Any]] = []
    for style in styles.get("styles", []):
        if style.get("status") == "active":
            active_by_parent[style["parent_style_id"]].append(style)
        else:
            deprecated.append(style)

    module_fields: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for field in fields.get("fields", []):
        module_fields[field["module_id"]].append(field)

    lines = [
        "# 设计 DNA 知识库稳定索引",
        "",
        "本索引只用于通过稳定 ID 定位完整知识库；不包含判定规则。风格分类必须读取候选、冲突对象、硬排除和异混淆特征的完整记录。",
        "",
        f"- 知识库版本：`{styles.get('knowledge_base_version')}`",
        f"- 一级导航族：{len(parent_order)}",
        f"- 活动二级风格：{sum(len(items) for items in active_by_parent.values())}",
        f"- 规范 DNA 字段：{sum(len(items) for items in module_fields.values())}",
        "",
        "## 风格索引",
        "",
    ]
    for parent_id in parent_order:
        lines.extend([f"### `{parent_id}`｜{parent_names[parent_id]}", ""])
        for style in active_by_parent[parent_id]:
            groups = ", ".join(style.get("confusion_groups", [])) or "—"
            lines.append(
                f"- `{style['style_id']}`｜{style.get('display_name_en', '')}｜"
                f"{style.get('display_name_zh', '')}｜混淆组 `{groups}`"
            )
        lines.append("")
    if deprecated:
        lines.extend(["### 迁移别名", ""])
        for style in deprecated:
            lines.append(f"- `{style['style_id']}` → `{style.get('replaced_by')}`")
        lines.append("")

    lines.extend(["## 规范 DNA 字段索引", ""])
    for module_id in sorted(module_fields):
        entries = sorted(module_fields[module_id], key=lambda item: item["field_id"])
        lines.extend([f"### `{module_id}`（{len(entries)}）", ""])
        lines.append(
            "、".join(f"`{item['field_id']}` {item['name']}" for item in entries)
        )
        lines.append("")

    lines.extend(
        [
            "## 加载规则",
            "",
            "1. 先读取全局判定规则，再按 `style_id` 读取候选及同混淆组风格的完整记录。",
            "2. 按品类 profile 读取启用字段；同一字段 ID 不得跨品类改义。",
            "3. 提出新 DNA 前检索规范字段、真 aliases 与零权重 compatibility_derived，避免重复。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="只检查现有索引是否最新")
    args = parser.parse_args()
    try:
        rendered = _render()
        if args.check:
            current = args.output.read_text(encoding="utf-8")
            if current != rendered:
                print("knowledge index is stale", file=sys.stderr)
                return 1
            print("knowledge index is current")
            return 0
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
