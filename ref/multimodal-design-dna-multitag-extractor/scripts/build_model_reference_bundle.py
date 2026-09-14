#!/usr/bin/env python3
"""生成模型候选召回所需的精简风格与字段索引。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STYLE_REGISTRY = ROOT / "references" / "style-registry.json"
FIELD_REGISTRY = ROOT / "references" / "field-registry.json"
DEFAULT_OUTPUT = ROOT / "references" / "model-reference-bundle.json"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"注册表根节点必须是对象：{path}")
    return data


def build_bundle() -> dict[str, Any]:
    styles = _load(STYLE_REGISTRY)
    fields = _load(FIELD_REGISTRY)
    return {
        "knowledge_base_version": styles.get("knowledge_base_version"),
        "purpose": "model_style_candidate_recall",
        "active_styles": [
            {
                "style_id": item.get("style_id"),
                "tag_kind": item.get("tag_kind"),
                "facet_ids": item.get("facet_ids", []),
                "confusion_groups": item.get("confusion_groups", []),
                "decisive_field_ids": item.get("decisive_field_ids", []),
                "auxiliary_field_ids": item.get("auxiliary_field_ids", []),
            }
            for item in styles.get("styles", [])
            if isinstance(item, dict) and item.get("status") == "active"
        ],
        "canonical_fields": [
            {
                key: item[key]
                for key in (
                    "field_id",
                    "module_id",
                    "name",
                    "value_type",
                    "evidence_mode",
                    "required_views",
                    "applicability",
                    "derived_from",
                )
                if key in item
            }
            for item in fields.get("fields", [])
            if isinstance(item, dict)
        ],
    }


def _render() -> str:
    return json.dumps(build_bundle(), ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        rendered = _render()
        if args.check:
            if args.output.read_text(encoding="utf-8") != rendered:
                print("model reference bundle is stale", file=sys.stderr)
                return 1
            print("model reference bundle is current")
            return 0
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
