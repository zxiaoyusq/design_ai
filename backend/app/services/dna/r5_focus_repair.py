"""只从已保存的 R5 复核回复恢复完整检查项；不补写视觉事实、不请求模型。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


_PLACEHOLDER = {
    "decision": "uncertain", "value": None,
    "evidence": "离线恢复：原回复缺失或不合规，待人工复核",
}
_CHECKS = re.compile(r'"checks"\s*:\s*\{')


def _value_end(raw: str, start: int) -> int | None:
    """找完整值的边界，字符串内的括号不参与配对；截断字符串绝不补闭合。"""
    if start >= len(raw):
        return None
    if raw[start] not in "[{":
        try:
            _, end = json.JSONDecoder().raw_decode(raw, start)
            return end
        except ValueError:
            end = start
            while end < len(raw) and raw[end] not in ",}":
                end += 1
            return end if end > start else None
    stack: list[str] = []
    quoted = escaped = False
    for offset in range(start, len(raw)):
        char = raw[offset]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{":
            stack.append(char)
        elif char in "]}":
            if not stack or stack.pop() != {"]": "[", "}": "{"}[char]:
                return None
            if not stack:
                return offset + 1
    return None


def _contains_check_candidate(raw: str, expected_ids: set[str]) -> bool:
    """缺分隔符的尾部若仍有检查项，不能采纳前值；忽略证据字符串内部的文本。"""
    offset = 0
    while offset < len(raw):
        if raw[offset] != '"':
            offset += 1
            continue
        try:
            token, end = json.JSONDecoder().raw_decode(raw, offset)
        except ValueError:
            # 剩余内容仍属于截断或损坏字符串，不把其中片段当作另一检查项。
            return False
        if (token in expected_ids or token.isdecimal()) and re.match(r"\s*:\s*\{", raw[end:]):
            return True
        offset = end
    return False


def recover_focus(raw: str, schema: dict[str, Any], portable: Any, engine: Any) -> dict[str, Any]:
    """保留逐项严格合规的原值；所有占位项显式标记为主机生成且保持未决。"""
    if not isinstance(raw, str):
        raise ValueError("复核原回复必须是字符串")
    audit: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    prefix = re.match(r"\s*```(?:json)?\s*", raw)
    begin = prefix.end() if prefix else 0
    if prefix:
        audit.append({"kind": "discard_markdown_prefix", "source_span": [0, begin]})
    try:
        portable.loads(raw)
    except ValueError as exc:
        audit.append({"kind": "original_json_invalid", "error": str(exc)})
    match = re.match(r'\s*(\{\s*)?"checks"\s*:\s*\{', raw[begin:])
    if not match:
        raise ValueError("无法识别唯一的顶层 checks 对象")
    if match.group(1) is None:
        audit.append({"kind": "missing_outer_opening_brace", "source_span": [begin, begin + match.end()]})
    offset = begin + match.end()
    entries: dict[str, list[dict[str, Any]]] = {}
    closed = False
    while True:
        while offset < len(raw) and raw[offset].isspace():
            offset += 1
        if offset >= len(raw):
            break
        if raw[offset] == "}":
            closed = True
            offset += 1
            break
        key_start = offset
        try:
            key, offset = json.JSONDecoder().raw_decode(raw, offset)
        except ValueError:
            offset = key_start
            break
        if not isinstance(key, str):
            offset = key_start
            break
        while offset < len(raw) and raw[offset].isspace():
            offset += 1
        if offset >= len(raw) or raw[offset] != ":":
            entries.setdefault(key, []).append({"check_id": key, "source_span": [key_start, len(raw)],
                                               "raw": raw[key_start:], "error": "检查项缺少冒号"})
            offset = key_start
            break
        offset += 1
        while offset < len(raw) and raw[offset].isspace():
            offset += 1
        value_start = offset
        end = _value_end(raw, offset)
        if end is None:
            entries.setdefault(key, []).append({"check_id": key, "error": "检查项被截断或括号不匹配",
                                               "source_span": [key_start, len(raw)], "raw": raw[key_start:]})
            offset = value_start
            break
        entry = {"check_id": key, "source_span": [value_start, end], "raw": raw[value_start:end]}
        try:
            entry["value"] = portable.loads(entry["raw"])
        except ValueError as exc:
            entry["error"] = str(exc)
        entries.setdefault(key, []).append(entry)
        offset = end
        while offset < len(raw) and raw[offset].isspace():
            offset += 1
        if offset < len(raw) and raw[offset] == ",":
            offset += 1
        elif offset >= len(raw) or raw[offset] == "}":
            continue
        else:
            break

    tail = raw[offset:]
    properties = schema["properties"]["checks"]["properties"]
    # 不在多份 JSON 答案中择一；恢复尾部垃圾只允许不包含另一结构化候选。
    if _CHECKS.search(tail) or (closed and any(char in tail for char in "{[")):
        raise ValueError("复核回复含多个或有歧义的结构化对象，不能自动择一")
    if not closed and _contains_check_candidate(tail, set(properties)):
        raise ValueError("复核检查项分隔符损坏且尾部仍有结构化检查项，不能自动择值")
    if tail.strip() not in ("", "}") or not closed:
        audit.append({"kind": "incomplete_or_extra_outer_text", "source_span": [offset, len(raw)], "raw": tail})

    answer: dict[str, Any] = {"checks": {}}
    generated: list[str] = []
    for key, candidates in entries.items():
        if key not in properties:
            quarantined.extend({**entry, "reason": "不在本次复核清单中的编号"} for entry in candidates)
            continue
        if any("error" in entry for entry in candidates):
            quarantined.extend({**entry, "reason": "检查项 JSON 不合规或包含重复键"} for entry in candidates)
            continue
        canonical = {json.dumps(entry["value"], sort_keys=True, ensure_ascii=False) for entry in candidates}
        if len(canonical) != 1:
            quarantined.extend({**entry, "reason": "同一复核编号存在冲突，全部隔离"} for entry in candidates)
            continue
        value = candidates[0]["value"]
        item_schema = {**deepcopy(properties[key]), "$defs": deepcopy(schema.get("$defs", {}))}
        try:
            portable.validate(engine, item_schema, value)
        except ValueError as exc:
            quarantined.extend({**entry, "reason": "不符合冻结复核 Schema", "error": str(exc)} for entry in candidates)
            continue
        answer["checks"][key] = value
        audit.append({"kind": "preserved_check", "check_id": key,
                      "source_spans": [entry["source_span"] for entry in candidates],
                      "identical_occurrences": len(candidates), "host_generated": False})
    for key in properties:
        if key not in answer["checks"]:
            answer["checks"][key] = deepcopy(_PLACEHOLDER)
            generated.append(key)
            audit.append({"kind": "pending_placeholder", "check_id": key, "host_generated": True})
    portable.validate(engine, schema, answer)
    return {"answer": answer, "audit": audit, "quarantined": quarantined,
            "host_generated_check_ids": generated, "usable_checks": len(properties) - len(generated),
            "complete": not generated and not quarantined}
