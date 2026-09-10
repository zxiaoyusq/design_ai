"""提取回复的可追溯机械整理；不改写原文或语义判断，也不修复 JSON 语法。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any

from contracts import DIMENSIONS, EVIDENCE_FIELDS, IMAGE_ROLES, STANCES, default_extract_field, image_code_in_text


NORMALIZATION_VERSION = "extract_metadata_v5"


def _long_quote_source(observation: dict, records: dict[str, dict]) -> tuple[str, str, str] | None:
    """先校验全部原属性；只豁免本次要拆分的引文长度和角色数量，不洗白其他错误。"""
    required = {"record_id", "dimensions", "stance", "quote"}
    if not required.issubset(observation) or observation.keys() - required - {"field", "image_roles"}:
        return None
    identifier, quote = observation["record_id"], observation["quote"]
    if (not isinstance(identifier, str) or identifier not in records
            or not isinstance(quote, str) or len(quote) <= 600):
        return None
    record = records[identifier]
    kind, fields = record.get("kind"), record.get("fields")
    if not isinstance(kind, str) or kind not in EVIDENCE_FIELDS or not isinstance(fields, dict):
        return None
    field = observation.get("field", default_extract_field(record))
    if not isinstance(field, str) or field not in EVIDENCE_FIELDS[kind]:
        return None
    source = fields.get(field)
    if not isinstance(source, str) or not quote.strip() or quote not in source:
        return None
    dimensions, stance = observation["dimensions"], observation["stance"]
    if (not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 3
            or not all(isinstance(value, str) and value in DIMENSIONS for value in dimensions)
            or len(set(dimensions)) != len(dimensions)
            or not isinstance(stance, str) or stance not in STANCES
            or (kind == "trend") != (stance == "example")):
        return None
    roles = observation.get("image_roles", {})
    if not isinstance(roles, dict):
        return None
    for code, role in roles.items():
        if (not isinstance(code, str) or not code.strip() or len(code) > 100
                or not image_code_in_text(code, quote)
                or not isinstance(role, str) or role not in IMAGE_ROLES):
            return None
    return field, source, quote


def _sentence_spans(quote: str) -> list[tuple[int, int]] | None:
    """只在明确句末且括号、引号已闭合处断开；不把分号、换行或英文小数点猜成句末。"""
    pairs = {"“": "”", "‘": "’", "「": "」", "『": "』", "（": "）", "(": ")",
             "【": "】", "[": "]", "《": "》"}
    closers = set(pairs.values())
    stack, spans = [], []
    start, position = 0, 0
    while position < len(quote):
        char = quote[position]
        if char in pairs:
            stack.append(pairs[char])
        elif char in closers:
            if not stack or stack.pop() != char:
                return None
        elif char in "。！？!?":
            end = position + 1
            while end < len(quote) and quote[end] in "。！？!?":
                end += 1
            closing_stack = list(stack)
            while end < len(quote) and quote[end] in closers:
                if not closing_stack or closing_stack.pop() != quote[end]:
                    return None
                end += 1
            # 英文问号、感叹号只认空白或末尾边界；保留所有原始空白，不 strip 或补标点。
            if not closing_stack and (char in "。！？" or end == len(quote) or quote[end].isspace()):
                while end < len(quote) and quote[end].isspace():
                    end += 1
                spans.append((start, end))
                start = end
                stack = closing_stack
                position = end
                continue
        position += 1
    # 尾部没有明确句末、括号不闭合或存在超长单句时，由原契约拒绝，不丢掉尾部凑上限。
    return spans if start == len(quote) and not stack else None


def _long_quote_parts(observation: dict, quote: str) -> list[tuple[int, int, dict]] | None:
    spans = _sentence_spans(quote)
    if not spans:
        return None
    roles = observation.get("image_roles", {})
    parts = []
    start, end = spans[0][0], spans[0][0]
    for sentence_start, sentence_end in spans:
        sentence = quote[sentence_start:sentence_end]
        sentence_roles = {code: role for code, role in roles.items() if image_code_in_text(code, sentence)}
        if len(sentence) > 600 or len(sentence_roles) > 20:
            return None
        combined = quote[start:sentence_end]
        combined_roles = {code: role for code, role in roles.items() if image_code_in_text(code, combined)}
        if len(combined) > 600 or len(combined_roles) > 20:
            parts.append((start, end, {code: role for code, role in roles.items()
                                      if image_code_in_text(code, quote[start:end])}))
            start = sentence_start
        end = sentence_end
    parts.append((start, end, {code: role for code, role in roles.items()
                              if image_code_in_text(code, quote[start:end])}))
    # 角色必须仍完整出现；包括跨句标点的罕见编码也不能因拆分而悄悄消失。
    if set(roles) != {code for _, _, part_roles in parts for code in part_roles}:
        return None
    return parts if len(parts) > 1 and "".join(quote[start:end] for start, end, _ in parts) == quote else None


def _split_long_quotes(normalized: dict, job: dict, records: dict[str, dict], changes: list[dict]) -> None:
    """长引用只做无损分包：立场、维度不变；全部计划满足总观察预算后才统一应用。"""
    limits = job.get("limits", {})
    if not isinstance(limits, dict):
        return
    budget = limits.get("max_observations", 64)
    observations = normalized["observations"]
    if type(budget) is not int or budget < len(observations):
        return
    plans = {}
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        verified = _long_quote_source(observation, records)
        if verified is None:
            continue
        field, source, quote = verified
        parts = _long_quote_parts(observation, quote)
        if parts is not None:
            plans[index] = (field, source, quote, parts)
    if len(observations) + sum(len(plan[3]) - 1 for plan in plans.values()) > budget:
        return
    expanded = []
    for index, observation in enumerate(observations):
        if index not in plans:
            expanded.append(observation)
            continue
        field, source, quote, parts = plans[index]
        fragments, offsets = [], []
        for start, end, roles in parts:
            fragment = deepcopy(observation)
            fragment["quote"] = quote[start:end]
            # 未声明 image_roles 时保持省略；已有角色只按编码在片段原文中的出现分配，不猜新角色。
            if "image_roles" in observation:
                fragment["image_roles"] = roles
            offsets.append({"index": len(expanded), "start": start, "end": end,
                            "image_roles": deepcopy(roles)})
            fragments.append(fragment)
            expanded.append(fragment)
        changes.append({
            "index": index, "original_index": index, "record_id": observation["record_id"],
            "field": "observations", "source_field": field, "operation": "split_explicit_long_quote",
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "offset_unit": "unicode_code_point", "fragments": offsets,
            "before": deepcopy(observation), "after": deepcopy(fragments),
            "reason": "按完整句末将显式连续原文无损分包，每片段最多 600 字、20 个原有角色；"
                      "片段拼接逐字等于原引用，维度及立场不变，同编码在多个片段出现时各自保留原角色",
        })
    normalized["observations"] = expanded


def _record_index(job: dict) -> dict[str, dict]:
    """重复 ID 的来源有歧义，保留给正式校验处理，不任选一条做整理。"""
    payload = job.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return {}
    records = {}
    repeated = set()
    for record in payload["records"]:
        if not isinstance(record, dict):
            continue
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        if identifier in records:
            repeated.add(identifier)
        records[identifier] = record
    return {identifier: record for identifier, record in records.items() if identifier not in repeated}


def _verified_quote(observation: dict, records: dict[str, dict]) -> tuple[str, str] | None:
    """只有合法字段内的连续原文才允许整理附属标签，避免掩盖伪造引用。"""
    identifier = observation.get("record_id")
    if not isinstance(identifier, str) or identifier not in records:
        return None
    record = records[identifier]
    fields = record.get("fields")
    kind = record.get("kind")
    if not isinstance(fields, dict) or not isinstance(kind, str) or kind not in EVIDENCE_FIELDS:
        return None
    field = observation.get("field", default_extract_field(record))
    if not isinstance(field, str) or field not in EVIDENCE_FIELDS[kind]:
        return None
    source = fields.get(field)
    if not isinstance(source, str):
        return None
    quote = observation.get("quote", source)
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 600 or quote not in source:
        return None
    return field, quote


def _restore_numbered_quote(observation: dict, records: dict[str, dict]) -> tuple[str, str] | None:
    """仅完整连续列表项可恢复编号；起止必须落在项正文边界，不能截掉否定或条件。"""
    identifier, quote = observation.get("record_id"), observation.get("quote")
    if (not isinstance(identifier, str) or identifier not in records
            or not isinstance(quote, str) or not quote.strip() or len(quote) > 600):
        return None
    record = records[identifier]
    fields, kind = record.get("fields"), record.get("kind")
    if not isinstance(fields, dict) or not isinstance(kind, str) or kind not in EVIDENCE_FIELDS:
        return None
    field = observation.get("field", default_extract_field(record))
    if not isinstance(field, str) or field not in EVIDENCE_FIELDS[kind]:
        return None
    source = fields.get(field)
    if not isinstance(source, str) or quote in source:
        return None
    # 编号只能在开头、中文句末或换行后出现；小数点后接数字时绝不视作列表编号。
    pattern = r"(?:^|(?<=[。！？\n]))[ \t]*(?P<number>[0-9]+)(?:\.(?!\d)|、)[ \t]*"
    markers = list(re.finditer(pattern, source))
    if len(markers) < 2 or any(match.group("number") != str(index) for index, match in enumerate(markers, 1)):
        return None
    positions = []
    cursor = 0
    for match in markers:
        # 前置缩进和换行仍是正文布局的一部分，只移除 N./N、与编号后的空格。
        positions.extend(range(cursor, match.start("number")))
        cursor = match.end()
    positions.extend(range(cursor, len(source)))
    view = "".join(source[position] for position in positions)
    start = view.find(quote)
    if start < 0 or view.find(quote, start + 1) >= 0:
        return None
    original_start, original_end = positions[start], positions[start + len(quote) - 1] + 1
    # 完整项边界避免从“不喜欢”中途匹配“喜欢”，或丢掉末项的限制条件。
    item_starts = {match.end() for match in markers}
    item_ends = {match.start("number") for match in markers[1:]} | {len(source)}
    if original_start not in item_starts or original_end not in item_ends:
        return None
    restored = source[original_start:original_end]
    return (field, restored) if len(restored) <= 600 else None


def _empty_unclear_field(record: dict, observation: dict) -> str | None:
    """只有空回答上的明确“不清楚”观察可转为跳过，不抹去模型声称的偏好或原文。"""
    required = {"record_id", "dimensions", "stance"}
    allowed = required | {"field", "quote", "image_roles"}
    if not required.issubset(observation) or observation.keys() - allowed:
        return None
    kind = record.get("kind")
    if not isinstance(kind, str) or kind not in {"user_qa", "user_demand", "orphan_demand"}:
        return None
    fields = record.get("fields")
    if not isinstance(fields, dict):
        return None
    field = default_extract_field(record)
    if EVIDENCE_FIELDS[kind] != {field} or observation.get("field", field) != field:
        return None
    source = fields.get(field)
    if not isinstance(source, str) or source.strip():
        return None
    quote = observation.get("quote", "")
    if not isinstance(quote, str) or quote.strip() or observation.get("stance") != "unclear":
        return None
    dimensions = observation.get("dimensions")
    if (not isinstance(dimensions, list) or not dimensions
            or not all(isinstance(value, str) and value in DIMENSIONS for value in dimensions)
            or len(set(dimensions)) > 3):
        return None
    if observation.get("image_roles", {}) != {}:
        return None
    return field


def _deduplicate_skipped(normalized: dict, records: dict[str, dict], changes: list[dict]) -> None:
    """只消除同来源、同状态、同原因的复制项；不同声明和观察冲突均不处理。"""
    skipped = normalized.get("skipped")
    if not isinstance(skipped, list):
        return
    observed = {item.get("record_id") for item in normalized["observations"]
                if isinstance(item, dict) and isinstance(item.get("record_id"), str)}
    groups = {}
    for index, item in enumerate(skipped):
        if isinstance(item, dict) and isinstance(item.get("record_id"), str):
            groups.setdefault(item["record_id"], []).append((index, item))
    removed, dedup_changes = set(), []
    for identifier, items in groups.items():
        if len(items) < 2 or identifier not in records or identifier in observed:
            continue
        retained_index, first = items[0]
        if (set(first) != {"record_id", "status", "reason"}
                or not isinstance(first["status"], str) or first["status"] not in {"not_design", "unclear"}
                or not isinstance(first["reason"], str) or not first["reason"].strip()
                or len(first["reason"]) > 400 or any(item != first for _, item in items[1:])):
            continue
        record = records[identifier]
        kind = record.get("kind")
        if not isinstance(kind, str) or kind not in EVIDENCE_FIELDS or not isinstance(record.get("fields"), dict):
            continue
        source_field = default_extract_field(record)
        for index, item in items[1:]:
            removed.add(index)
            dedup_changes.append({
                "index": index, "retained_index": retained_index, "record_id": identifier,
                "field": "skipped", "source_field": source_field,
                "before": deepcopy(item), "after": None,
                "reason": "移除同一来源且状态、原因完全相同的复制项，保留首次原始索引的声明",
            })
    changes.extend(sorted(dedup_changes, key=lambda item: item["index"]))
    if removed:
        normalized["skipped"] = [item for index, item in enumerate(skipped) if index not in removed]


def _move_empty_answers(normalized: dict, records: dict[str, dict], changes: list[dict]) -> None:
    """按记录整体移动；任何不安全观察或既有跳过声明都保留给正式覆盖校验。"""
    observations, skipped = normalized["observations"], normalized.get("skipped")
    if not isinstance(skipped, list):
        return
    groups = {}
    for index, observation in enumerate(observations):
        if isinstance(observation, dict) and isinstance(observation.get("record_id"), str):
            groups.setdefault(observation["record_id"], []).append((index, observation))
    removed = set()
    for identifier, items in groups.items():
        if identifier not in records or any(isinstance(item, dict) and item.get("record_id") == identifier for item in skipped):
            continue
        fields = [_empty_unclear_field(records[identifier], observation) for _, observation in items]
        if any(field is None for field in fields):
            continue
        target = {"record_id": identifier, "status": "unclear", "reason": "原始回答为空，仅问题或场景不足以构成用户证据"}
        skipped.append(target)
        indices = [index for index, _ in items]
        removed.update(indices)
        changes.append({
            "index": indices[0], "indices": indices, "record_id": identifier,
            "field": "observations/skipped", "source_field": fields[0],
            "before": [deepcopy(observation) for _, observation in items], "after": deepcopy(target),
            "reason": "原始回答为空，已有全部观察均仅声明 unclear；转为一次 skipped，不从问题生成证据",
        })
    if removed:
        normalized["observations"] = [observation for index, observation in enumerate(observations) if index not in removed]


def normalize_response(job: dict, response: Any) -> tuple[Any, list[dict]]:
    """返回深复制回复与逐项变更记录；整理后的回复仍必须经过完整契约校验。

    对合法长引用按完整句末无损分包，恢复可精确映射的列表编号，整理图片编码与重复维度。
    将空回答的纯 unclear 观察移为跳过。
    skipped 仅消除同来源完全相同的复制项；省略 quote 只在内部恢复原文用于判断。
    """
    normalized = deepcopy(response)
    changes = []
    if not isinstance(job, dict) or job.get("stage") != "extract" or not isinstance(normalized, dict):
        return normalized, changes
    observations = normalized.get("observations")
    if not isinstance(observations, list):
        return normalized, changes
    records = _record_index(job)
    _split_long_quotes(normalized, job, records, changes)
    observations = normalized["observations"]
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        restored = _restore_numbered_quote(observation, records)
        if restored is not None:
            source_field, restored_quote = restored
            original_quote = observation["quote"]
            observation["quote"] = restored_quote
            changes.append({
                "index": index, "record_id": observation["record_id"], "field": "quote",
                "source_field": source_field, "before": original_quote, "after": restored_quote,
                "reason": "按从 1 连续递增的原文列表编号与唯一字符映射恢复连续引用，不修改正文或标点",
            })
        verified = _verified_quote(observation, records)
        if verified is None:
            continue
        source_field, quote = verified
        roles = observation.get("image_roles")
        if isinstance(roles, dict):
            # 不推测缺失前缀或图号；编码在原文中时，错误角色值仍交给严格校验拒绝。
            cleaned_roles = {
                code: role for code, role in roles.items()
                if not isinstance(code, str) or not code.strip() or len(code) > 100
                or image_code_in_text(code, quote)
            }
            if cleaned_roles != roles:
                observation["image_roles"] = cleaned_roles
                changes.append({
                    "index": index, "record_id": observation["record_id"], "field": "image_roles",
                    "source_field": source_field, "before": deepcopy(roles), "after": deepcopy(cleaned_roles),
                    "reason": "移除当前有效引文中未完整出现的图片编码，不猜测或补写编码",
                })
        dimensions = observation.get("dimensions")
        if isinstance(dimensions, list) and all(isinstance(value, str) and value in DIMENSIONS for value in dimensions):
            # 只消除相同标签，不合并近义词，也不通过删掉不同维度来满足数量上限。
            unique = list(dict.fromkeys(dimensions))
            if unique != dimensions:
                observation["dimensions"] = unique
                changes.append({
                    "index": index, "record_id": observation["record_id"], "field": "dimensions",
                    "source_field": source_field, "before": list(dimensions), "after": list(unique),
                    "reason": "去除完全相同的合法维度标签，保留首次出现顺序",
                })
    _deduplicate_skipped(normalized, records, changes)
    _move_empty_answers(normalized, records, changes)
    return normalized, changes
