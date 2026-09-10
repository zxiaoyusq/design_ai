"""只整理确定性的 JSON 外壳和尾逗号，不猜测、补全或改写模型正文。"""

from __future__ import annotations

import json
import math
import re


JSON_REPAIR_VERSION = "1"
_JSON_FENCE = re.compile(r"\A```json[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```\Z", re.IGNORECASE)
_JSON_WHITESPACE = " \t\r\n"


def _strict_json(text):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"JSON 重复字段：{key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"JSON 非法常数：{value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"JSON 非有限数值：{value}")
        return number

    return json.loads(text, object_pairs_hook=unique, parse_constant=constant,
                      parse_float=finite_float)


def _without_trailing_commas(text):
    """单次词法扫描；字符串、转义字符和空容器中的非法逗号都不改动。"""
    positions, in_string, escaped, previous = [], False, False, None
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                previous = char
            continue
        if char == '"':
            in_string = True
            continue
        if char == "," and previous is not None and previous not in "[{,:":
            following = index + 1
            while following < len(text) and text[following] in _JSON_WHITESPACE:
                following += 1
            if following < len(text) and text[following] in "]}":
                positions.append(index)
        if char not in _JSON_WHITESPACE:
            previous = char
    removed = set(positions)
    return "".join(char for index, char in enumerate(text) if index not in removed), positions


def parse_model_json(text):
    """返回 (JSON 值, 操作列表)；原本严格合法的响应不触发任何整理。

    只接受包住整个响应的单个 JSON 围栏，不从散文抽取局部对象。
    操作记录不含原文；尾逗号位置相对于去掉外壳后的文本，原始哈希由调用者保留。
    整理后必须一次通过完整严格解析，不能通过多次删除来修复连续逗号或截断内容。
    """
    if not isinstance(text, str):
        raise ValueError("模型 JSON 原文必须是字符串")
    try:
        return _strict_json(text), []
    except ValueError:
        pass

    changes, candidate = [], text

    def trim_outer_whitespace():
        nonlocal candidate
        trimmed = candidate.strip()
        if trimmed != candidate:
            changes.append({"operation": "trim_outer_whitespace"})
            candidate = trimmed

    trim_outer_whitespace()
    if candidate.startswith("\ufeff"):
        candidate = candidate[1:]
        changes.append({"operation": "remove_leading_bom"})
        trim_outer_whitespace()
    fence = _JSON_FENCE.fullmatch(candidate)
    if fence is not None:
        candidate = fence.group("body")
        changes.append({"operation": "remove_json_fence"})
        trim_outer_whitespace()
    candidate, positions = _without_trailing_commas(candidate)
    if positions:
        changes.append({"operation": "remove_trailing_commas", "count": len(positions),
                        "offsets": positions, "offset_reference": "after_wrapper_cleanup"})
    return _strict_json(candidate), changes
