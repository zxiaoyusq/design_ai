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
TAG_RELATIONS = ROOT / "references/tag-relations.json"
FIELD_REGISTRY = ROOT / "references/field-registry.json"
COMBINATION_PRESETS = ROOT / "references/style-combination-presets.json"
DEFAULT_OUTPUT = ROOT / "references/knowledge-index.zh-CN.md"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 根节点必须是对象")
    return value


def _render() -> str:
    styles = _load(STYLE_REGISTRY)
    relations = _load(TAG_RELATIONS)
    fields = _load(FIELD_REGISTRY)
    presets = _load(COMBINATION_PRESETS)
    versions = {
        styles.get("knowledge_base_version"),
        relations.get("knowledge_base_version"),
        fields.get("knowledge_base_version"),
        presets.get("knowledge_base_version"),
    }
    if len(versions) != 1:
        raise ValueError("style/tag-relations/field/preset registry 知识库版本不一致")

    active = sorted(
        (item for item in styles.get("styles", []) if item.get("status") == "active"),
        key=lambda item: item["style_id"],
    )
    deprecated = sorted(
        (item for item in styles.get("styles", []) if item.get("status") != "active"),
        key=lambda item: item["style_id"],
    )
    facets = relations.get("facets", [])
    pair_relations = relations.get("pair_relations", [])
    combination_presets = sorted(
        presets.get("presets", []), key=lambda item: item["preset_id"]
    )

    module_fields: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for field in fields.get("fields", []):
        module_fields[field["module_id"]].append(field)

    lines = [
        "# 设计 DNA 知识库稳定索引",
        "",
        "本索引只用于通过稳定 ID 定位完整知识库；不包含判定规则。风格标签必须读取候选、关系、硬排除和异混淆特征的完整记录。",
        "",
        f"- 知识库版本：`{styles.get('knowledge_base_version')}`",
        f"- 活动扁平风格标签：{len(active)}",
        f"- 检索 facet：{len(facets)}",
        f"- 显式标签对关系：{len(pair_relations)}",
        f"- 查询组合预设：{len(combination_presets)}",
        f"- 规范 DNA 字段：{sum(len(items) for items in module_fields.values())}",
        "",
        "## 扁平风格标签索引",
        "",
        "| style_id | English | 中文 | kind | facets | similarity_weight | 混淆组 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for style in active:
        groups = ", ".join(style.get("confusion_groups", [])) or "—"
        facet_ids = ", ".join(style.get("facet_ids", [])) or "—"
        lines.append(
            f"| `{style['style_id']}` | {style.get('display_name_en', '')} | "
            f"{style.get('display_name_zh', '')} | `{style.get('tag_kind', '')}` | "
            f"`{facet_ids}` | {style.get('similarity_weight', '')} | `{groups}` |"
        )
    lines.append("")

    lines.extend(["## 查询组合预设", ""])
    lines.append("预设只把已确认标签转换为检索条件，不是可输出的风格标签。")
    lines.append("")
    lines.append("| preset_id | 中文 | 子句门槛 | 可选原子标签 |")
    lines.append("|---|---|---|---|")
    for preset in combination_presets:
        clauses = preset.get("clauses", [])
        members = ", ".join(
            sorted({style_id for clause in clauses for style_id in clause.get("style_ids", [])})
        ) or "—"
        thresholds = "+".join(str(clause.get("min_match", "")) for clause in clauses)
        lines.append(
            f"| `{preset['preset_id']}` | {preset.get('display_name_zh', '')} | "
            f"{thresholds} | `{members}` |"
        )
    lines.append("")

    if deprecated:
        lines.extend(["### 迁移别名", ""])
        for style in deprecated:
            if style.get("replaced_by"):
                target = f"`{style['replaced_by']}`"
            else:
                fields_target = ", ".join(style.get("replacement_field_ids", [])) or "—"
                target = f"DNA 字段 `{fields_target}`"
            lines.append(f"- `{style['style_id']}` → {target}")
        lines.append("")

    lines.extend(["## Facet 索引", ""])
    for facet in facets:
        lines.append(
            f"- `{facet.get('facet_id')}`｜{facet.get('display_name', '')}｜"
            f"{facet.get('description', '')}"
        )
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
            "2. 返回多标签前读取 `tag-relations.json`，对每一对已确认标签执行关系仲裁。",
            "3. 需要解释命名组合时，原子标签确认后再读取组合预设；不得把预设写入输出或用于反向补证。",
            "4. 按品类 profile 读取启用字段；同一字段 ID 不得跨品类改义。",
            "5. 提出新 DNA 前检索规范字段、真 aliases 与零权重 compatibility_derived，避免重复。",
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
