"""在整理资料前用代码解析常见数量要求，不增加模型调用。"""

import re

FIRST_USERS = re.compile(r"前\s*([0-9零〇一二两三四五六七八九十百千]+)\s*(?:个|位|名)?\s*(?:用户|受访者)")
ALL_USERS = re.compile(r"(?:全部|所有)(?:的)?\s*(?:用户|受访者)")


def _number(text):
    if text.isdecimal():
        return int(text)
    digits = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    total, digit, last_unit = 0, None, 10000
    for char in text:
        if char in digits:
            if digit not in (None, 0):
                raise ValueError("用户数量不明确，请使用阿拉伯数字，例如前 20 位用户")
            digit = digits[char]
        elif char in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            if unit >= last_unit:
                raise ValueError("用户数量不明确，请使用阿拉伯数字")
            total += (digit if digit is not None else 1) * unit
            digit, last_unit = None, unit
        else:
            raise ValueError("用户数量不明确，请使用阿拉伯数字")
    return total + (digit or 0)


def resolve_user_scope(request):
    """界面与文字不相互覆盖；冲突或否定表达需修改后再预估，避免静默扩大范围。"""
    matches = list(FIRST_USERS.finditer(request.prompt)) + list(ALL_USERS.finditer(request.prompt))
    limits = set()
    for match in matches:
        # 简单规则只接受肯定的范围；复杂更正句交给用户明确选择，不让模型猜测。
        prefix = re.split(r"[，。；！？\n,;!?]", request.prompt[:match.start()])[-1]
        if re.search(r"不要|不用|不是|不选|不取|非|排除|除去|去掉", prefix):
            raise ValueError("用户范围包含否定或排除要求，请改成明确的“前 N 位用户”或使用用户范围选项")
        limit = _number(match.group(1)) if match.re is FIRST_USERS else None
        if limit is not None and limit < 1:
            raise ValueError("用户数量必须大于 0")
        limits.add(limit)
    if len(limits) > 1:
        raise ValueError("文字中出现多个不同的用户范围，请保留一个明确范围")
    explicit = request.user_scope != "auto"
    limit = request.user_limit if request.user_scope == "first" else None
    if limits:
        parsed = next(iter(limits))
        if explicit and parsed != limit:
            raise ValueError("文字要求与用户范围选项冲突，请修改为一致后再预估")
        limit = parsed
    origin = "option" if explicit else "prompt" if limits else "default"
    return {"user_limit": limit, "origin": origin,
            "label": f"原始资料中的前 {limit} 位用户" if limit is not None else "全部用户",
            "note": "先按 users.json 中的顺序选用户，再过滤无有效回答的内容；不补入后续用户。"}
