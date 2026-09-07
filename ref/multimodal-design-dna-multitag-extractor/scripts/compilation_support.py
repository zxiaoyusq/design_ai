"""编译阶段共用的稳定去重和可追溯赋值；不包含领域推断。"""
from __future__ import annotations

import json
from typing import Any, Sequence


def _ordered_unique(values: Sequence[Any]) -> list[Any]:
    """在不改变首次出现顺序的前提下去重 JSON 标量。"""

    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _record_change(report: dict[str, Any], path: str) -> None:
    changes = report.setdefault("changed_paths", [])
    if path not in changes:
        changes.append(path)


def _replace_if_changed(
    target: dict[str, Any],
    key: str,
    value: Any,
    path: str,
    report: dict[str, Any],
) -> None:
    if target.get(key) != value:
        target[key] = value
        _record_change(report, f"{path}/{key}")
