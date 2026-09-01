#!/usr/bin/env python3
"""从已确认原子风格中确定性派生组合预设，并写入最终结果 JSON。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESETS = ROOT / "references" / "style-combination-presets.json"


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"不允许非有限数值 {value!r}")


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        parse_constant=_reject_nonfinite_constant,
    )


def compute_derived_style_presets(
    confirmed_style_ids: Sequence[str],
    preset_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """按注册表顺序匹配全部子句，只使用已确认标签，不读取图像或候选分数。"""

    confirmed = {style_id for style_id in confirmed_style_ids if isinstance(style_id, str)}
    derived: list[dict[str, Any]] = []
    presets = preset_registry.get("presets")
    if not isinstance(presets, list):
        raise ValueError("组合预设注册表缺少 presets 数组")

    for preset in presets:
        if not isinstance(preset, dict):
            raise ValueError("组合预设必须是对象")
        clauses = preset.get("clauses")
        minimum_distinct = preset.get("min_distinct_style_ids")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(f"组合预设 {preset.get('preset_id')!r} 缺少有效 clauses")
        if not isinstance(minimum_distinct, int) or isinstance(minimum_distinct, bool):
            raise ValueError(
                f"组合预设 {preset.get('preset_id')!r} 缺少 min_distinct_style_ids"
            )

        matched_union: set[str] = set()
        all_clauses_passed = True
        for clause in clauses:
            style_ids = clause.get("style_ids") if isinstance(clause, dict) else None
            minimum = clause.get("min_match") if isinstance(clause, dict) else None
            if (
                not isinstance(style_ids, list)
                or not all(isinstance(style_id, str) for style_id in style_ids)
                or not isinstance(minimum, int)
                or isinstance(minimum, bool)
            ):
                raise ValueError(f"组合预设 {preset.get('preset_id')!r} 含无效子句")
            matched = confirmed.intersection(style_ids)
            if len(matched) < minimum:
                all_clauses_passed = False
                break
            matched_union.update(matched)

        if not all_clauses_passed or len(matched_union) < minimum_distinct:
            continue
        derived.append(
            {
                "preset_id": preset["preset_id"],
                "label_en": preset["display_name_en"],
                "label_zh": preset["display_name_zh"],
                "matched_style_ids": sorted(matched_union),
            }
        )
    return derived


def write_derived_style_presets(
    data: dict[str, Any],
    preset_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """覆盖任何来路不明的派生值，保证最终字段只由 Python 规则生成。"""

    style_result = data.get("style_result")
    if not isinstance(style_result, dict):
        raise ValueError("结果缺少 style_result 对象")
    style_tags = style_result.get("style_tags")
    if not isinstance(style_tags, list):
        raise ValueError("style_result.style_tags 必须是数组")
    confirmed_style_ids = [
        item.get("style_id")
        for item in style_tags
        if isinstance(item, dict) and isinstance(item.get("style_id"), str)
    ]
    derived = compute_derived_style_presets(confirmed_style_ids, preset_registry)
    style_result["derived_style_presets"] = derived
    return derived


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, ensure_ascii=False, indent=2, allow_nan=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="模型输出 JSON")
    parser.add_argument("--output", type=Path, help="最终 JSON；省略时输出到标准输出")
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        data = _load_json(args.input)
        preset_registry = _load_json(args.presets)
        if not isinstance(data, dict) or not isinstance(preset_registry, dict):
            raise ValueError("结果和组合预设注册表的根节点都必须是对象")
        write_derived_style_presets(data, preset_registry)
        if args.output is None:
            json.dump(data, fp=sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
            print()
        else:
            _atomic_write_json(args.output, data)
            print(args.output)
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
