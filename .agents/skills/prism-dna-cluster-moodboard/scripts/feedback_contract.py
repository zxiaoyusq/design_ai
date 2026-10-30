"""承接可核验的用户反馈；本次模型回应不修改历史，也不构成设计师销项。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote


VERSION = "prism.design_feedback_registry.v1"
COMPARISON_SCOPE_VERSION = "prism.feedback_comparison_scope.v2"
DECISIONS = ("retained_with_evidence", "excluded_from_this_group", "unresolved", "context_changed")
FEEDBACK_DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["issue_id", "affected_card_ids", "decision", "evidence"],
    "properties": {
        "issue_id": {"type": "string", "minLength": 1},
        "affected_card_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                              "items": {"type": "string"}},
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "evidence": {
            "type": "object", "additionalProperties": False,
            "required": ["observation", "compared_card_ids", "context_change", "remaining_uncertainty"],
            "properties": {
                "observation": {"type": "string", "minLength": 1},
                "compared_card_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                      "items": {"type": "string"}},
                "context_change": {"type": "string"},
                "remaining_uncertainty": {"type": "string", "minLength": 1},
            },
        },
    },
}


def _reference(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _read_reference(ref: dict) -> bytes:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("反馈引用必须具有 path 与 sha256")
    path = Path(ref["path"])
    if not path.is_absolute() or _reference(path) != ref:
        raise ValueError("反馈来源路径或 SHA 不一致")
    return path.read_bytes()


def _ids(value: object, allowed: set[str], label: str, *, nonempty: bool = False) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(i, str) or not i for i in value):
        raise ValueError(label + "必须为卡 ID 列表")
    if len(value) != len(set(value)) or not set(value) <= allowed or (nonempty and not value):
        raise ValueError(label + "包含重复、未知或缺失身份")
    return set(value)


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == "id" and value is not None)


def _check_pointer(raw: bytes, ref: dict, pointer: str) -> None:
    if not isinstance(pointer, str):
        raise ValueError("反馈定位必须是字符串")
    if Path(ref["path"]).suffix.lower() in {".html", ".htm"}:
        parser = _Anchors()
        parser.feed(raw.decode("utf-8"))
        if not pointer.startswith("#") or parser.ids.count(unquote(pointer[1:])) != 1:
            raise ValueError("HTML 反馈定位需唯一且真实存在的 #anchor")
        return
    value = json.loads(raw)
    if pointer == "":
        return
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("反馈 JSON pointer 格式无效")
    try:
        for part in pointer[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", part):
                    raise ValueError("JSON pointer 数组下标无效")
                value = value[int(part)]
            elif isinstance(value, dict):
                value = value[part]
            else:
                raise ValueError("JSON pointer 不能继续下钻")
    except (KeyError, IndexError) as error:
        raise ValueError("反馈 JSON pointer 不存在") from error


def _bound_cards(registry: dict, cards: dict | list) -> dict:
    """别名仅从同一 prepared 的完整冻结卡导出，不接受外部猜测的对应关系。"""
    manifest = json.loads(_read_reference(registry["prepared_ref"]))
    if manifest.get("schema_version") != "prism.design_cards_prepared.v1":
        raise ValueError("反馈只能绑定关系设计卡 prepared")
    frozen = json.loads(_read_reference(manifest["design_cards_ref"]))
    rows = cards["cards"] if isinstance(cards, dict) and "cards" in cards else list(cards.values()) if isinstance(cards, dict) else cards
    by_id = {row["card_id"]: row for row in rows}
    frozen_by_id = {row["card_id"]: row for row in frozen["cards"]}
    if len(by_id) != len(rows) or len(frozen_by_id) != len(frozen["cards"]) or by_id != frozen_by_id:
        raise ValueError("反馈收到的卡片与完整冻结卡不一致")
    return by_id


def load_feedback(path: str | Path, prepared: str | Path, cards: dict | list) -> dict:
    """绑定完整冻结卡；反馈文本只是待处理意见，不被写回 DNA 或解释为执行指令。"""
    registry = json.loads(Path(path).read_bytes())
    if set(registry) != {"schema_version", "prepared_ref", "issues"} or registry["schema_version"] != VERSION:
        raise ValueError("反馈注册表结构或版本无效")
    prepared = Path(prepared)
    if registry["prepared_ref"] != _reference(prepared):
        raise ValueError("反馈与当前 prepared 不是同一冻结输入")
    by_id = _bound_cards(registry, cards)
    if not isinstance(registry["issues"], list):
        raise ValueError("反馈 issues 必须为列表")
    required = {"issue_id", "feedback_ref", "feedback_pointer", "affected_card_ids", "context_card_ids",
                "issue_kind", "observation", "resolution_condition"}
    seen = set()
    sources = {}
    for issue in registry["issues"]:
        if not isinstance(issue, dict) or set(issue) != required:
            raise ValueError("反馈问题字段不完整或含未授权状态字段")
        for key in ("issue_id", "observation", "resolution_condition"):
            if not isinstance(issue[key], str) or not issue[key].strip():
                raise ValueError("反馈缺少 " + key)
        if issue["issue_id"] in seen or issue["issue_kind"] not in {"relationship", "display", "fact"}:
            raise ValueError("反馈 issue_id 重复或类型无效")
        seen.add(issue["issue_id"])
        affected = _ids(issue["affected_card_ids"], set(by_id), "反馈对象", nonempty=True)
        context = _ids(issue["context_card_ids"], set(by_id), "反馈上下文")
        if affected & context:
            raise ValueError("反馈对象与比较上下文应分别登记")
        # HTML 可能内嵌原图；同一来源只读一次，但每处指针仍单独验证。
        key = json.dumps(issue["feedback_ref"], sort_keys=True)
        if key not in sources:
            sources[key] = _read_reference(issue["feedback_ref"])
        _check_pointer(sources[key], issue["feedback_ref"], issue["feedback_pointer"])
    return deepcopy(registry)


def build_feedback_aliases(registry: dict, cards: dict | list) -> dict[str, list[str]]:
    """同对象同证据窗跨 ID/CMF 承接反馈；同图其他对象或裁片不继承。

    返回单独的运行投影，原注册表保持原样，避免把派生身份回写用户历史。
    这不合并两张卡的 DNA，只防止以历史分支标签更换同一反馈对象。
    """
    by_id = _bound_cards(registry, cards)
    buckets = {}
    keys = {}
    required = ("image_sha256", "subject", "display_bbox", "evidence_bbox", "display_scope", "bbox_format")
    for card_id, card in by_id.items():
        # 缺少对象或证据身份时不能只靠图 SHA 推断；明确 null 也不视为完整身份。
        if any(key not in card or card[key] is None for key in required) or not card["subject"]:
            keys[card_id] = ("exact_card_only", card_id)
        else:
            identity = {key: card[key] for key in required}
            # 字段缺失与显式 null 不相同；证据范围不同即使图框相同也不能自动继承。
            if "evidence_scope" in card:
                identity["evidence_scope"] = card["evidence_scope"]
            keys[card_id] = ("exact_object_view", json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                                           separators=(",", ":"), allow_nan=False))
        buckets.setdefault(keys[card_id], []).append(card_id)
    return {card_id: sorted(buckets[key]) for card_id, key in keys.items()}


def relevant_feedback(registry: dict, card_ids: list[str] | set[str], *, aliases: dict | None = None) -> list[dict]:
    """按对象承接反馈，不因换板名丢失，也不把旧组合问题变成全局排除。"""
    current = set(card_ids)
    active = []
    for issue in registry["issues"]:
        sources = list(dict.fromkeys(issue["affected_card_ids"] + issue["context_card_ids"]))
        source_aliases = {source: sorted(set((aliases or {}).get(source, [source]))) for source in sources}
        affected_aliases = sorted({alias for source in issue["affected_card_ids"] for alias in source_aliases[source]})
        context_aliases = sorted({alias for source in issue["context_card_ids"] for alias in source_aliases[source]})
        affected = [i for i in affected_aliases if i in current]
        if not affected:
            continue
        present = [i for i in context_aliases if i in current]
        missing = [source for source in issue["context_card_ids"] if not current.intersection(source_aliases[source])]
        active.append({**deepcopy(issue), "current_affected_card_ids": affected,
                       "current_context_card_ids": present, "missing_context_card_ids": missing,
                       "context_fully_present": not missing,
                       "affected_alias_card_ids": affected_aliases, "context_alias_card_ids": context_aliases,
                       "source_card_aliases": source_aliases})
    return active


def validate_feedback_decisions(answer: dict, payload: dict) -> None:
    """核对反馈回应与实际成员一致；只核执行边界，不凭文字长度认定审美问题已解决。"""
    active = payload.get("active_feedback", [])
    if "active_feedback" not in payload and not answer.get("feedback_decisions"):
        return  # 历史请求没有反馈协议，不为它补写新版结论。
    decisions = answer.get("feedback_decisions")
    if not isinstance(decisions, list):
        raise ValueError("缺少反馈逐项回应")
    expected = {issue["issue_id"]: issue for issue in active}
    identities = [row.get("issue_id") for row in decisions]
    if len(expected) != len(active) or len(identities) != len(set(identities)) or set(identities) != set(expected):
        raise ValueError("反馈回应遗漏、重复或伪造 issue_id")
    allowed = {row["card_id"] for row in payload.get("cards", [])}
    groups = [set(row["member_ids"]) for row in answer.get("groups", [])]
    used = set().union(*groups) if groups else set()
    for row in decisions:
        if set(row) != set(FEEDBACK_DECISION_SCHEMA["required"]):
            raise ValueError("反馈回应不能增删协议字段或写入用户销项状态")
        issue = expected[row["issue_id"]]
        affected = _ids(row["affected_card_ids"], allowed, "本次反馈对象", nonempty=True)
        affected_aliases = set(issue.get("affected_alias_card_ids", issue["affected_card_ids"]))
        if affected != set(issue["current_affected_card_ids"]) or affected != affected_aliases & allowed:
            raise ValueError("反馈未覆盖当前候选中全部受影响对象")
        decision, evidence = row["decision"], row["evidence"]
        if decision not in DECISIONS or not isinstance(evidence, dict) or set(evidence) != set(FEEDBACK_DECISION_SCHEMA["properties"]["evidence"]["required"]):
            raise ValueError("反馈决定或证据结构无效")
        for key in ("observation", "remaining_uncertainty"):
            if not isinstance(evidence[key], str) or not evidence[key].strip():
                raise ValueError("反馈证据缺少具体观察或未解决状态说明")
        if not isinstance(evidence["context_change"], str):
            raise ValueError("反馈 context_change 必须为文字说明")
        compared = _ids(evidence["compared_card_ids"], allowed, "反馈实际比较对象", nonempty=True)
        # affected已精确覆盖本条目标，compared可只列其它对照对象，两字段联合构成比较范围。
        # 要求目标ID在两处重复并不会增加视觉证据；同组其它成员与未决门仍在下方核对。
        retained = affected & used
        if retained and (decision in {"excluded_from_this_group", "unresolved"} or issue["issue_kind"] == "fact"):
            raise ValueError("未决、事实待核或声称已排除的反馈对象不得入组")
        if decision in {"retained_with_evidence", "context_changed"}:
            if not retained:
                raise ValueError("反馈声称保留但实际组中没有受影响对象")
            for members in groups:
                if not members & retained:
                    continue
                if not compared & (members - affected):
                    raise ValueError("保留依据必须比较新组中的具体其他成员")
                if decision == "context_changed":
                    if not evidence["context_change"].strip() or not issue["context_card_ids"]:
                        raise ValueError("context_changed 缺少可核的原上下文与具体变化依据")
                    if members & set(issue.get("context_alias_card_ids", issue["context_card_ids"])):
                        raise ValueError("原问题上下文仍在同组，不能仅改板名或移除部分上下文宣称已改变")
