"""统一情绪的请求投影与决策约束；不改冻结 DNA，不用代码替模型判断审美。"""

from copy import deepcopy
from functools import lru_cache
import importlib.util
from pathlib import Path


VERSION = "prism.unified_selection.v1"
PROMPT_VERSION = "prism-unified-conflict-first-20261011-v1"
POLICY = Path(__file__).resolve().parents[1] / "references/unified-selection-policy.md"


@lru_cache(maxsize=1)
def feedback_module():
    path = Path(__file__).with_name("feedback_contract.py")
    spec = importlib.util.spec_from_file_location("prism_feedback_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def card_projection(card):
    """单图自洽的情绪解释不等于跨图协调依据；原解释仍保留在冻结卡。"""
    row = deepcopy(card)
    if "design_emotion" in row:
        row["single_image_counter_signals"] = row.pop("design_emotion").get("counter_signals", [])
    if "design_quality" in row:
        row["design_expression_evidence"] = row.pop("design_quality").get("evidence", [])
    return row


GUIDANCE = {
    "discover": "读取全部当前卡，从具体可见组织提出关系假设；跨历史分支、品类和材质比较。每模板至少两个不同原图，逐卡交代candidate_ids或unassigned。代表和边界属于该模板。只读文字不称已看图；标题最后归纳。",
    "merge": "比较模板及实际代表/边界卡，按具体关系合并、拆分或保留。覆盖全部source_template_ids。不同来源标签不阻止归并，名称近似不构成依据。",
    "catalogue": "为候选关系生成导航摘要，保留区别和未知；目录节点不是情绪板，不宣称子项已经协调。",
    "route": "逐卡比较allowed_target_ids_by_card内的当前关系，最多三路；routed须有目标，其余为空。每卡恰好一条assignments；可new_direction/outlier/needs_dna。历史ID/CMF不限制路由。未命中不是低质量。",
    "select_directions": "依据代表/边界DNA、明确关系及已知冲突选少量值得扩充的方向，不提前批准板。每模板一次selected/deferred/not_suitable/needs_evidence，不超selection_limit。不因种子不足6或尚未看图拒绝方向。",
    "nominate": "比较当前池全部卡，按具体共同关系和设计表达提名真实看图候选，不超selection_limit；其余逐项not_nominated。旧模板仅为召回假设，不能为保留成员而放宽主导标准。显著冲突不因配额、同色或情绪词抵消；不得把旧成员身份当优先权。active_feedback是当前未解决问题，不能丢失或当永久黑名单。",
    "visual": "附件包含真实原图及冻结裁片，通过image_bindings核对。先写relation_hypotheses，明确具体主导关系、必要条件、允许变化与破坏条件；再对每张候选写candidate_decisions，最后才确定groups。dominant_conflict必须exclude，uncertain不能include。入组须支持同一假设，不能成员选定后把关系改宽；每组dominant_relation须与所引用假设一致。逐员写decision_basis而非强求为差异开脱。实际比较全组最不一致一对，hardest_pair.verdict为conflict或unresolved时不输出该组。允许全拒绝、拆组或小组。每张卡恰好一项决策，并在groups或not_selected交代；图卡矛盾写dna_issues且不入组。逐项回答active_feedback，模型回应不能关闭设计师问题。选择在本次请求内完成，不追加独立长审。",
}


def prepare_task(item, registry, *, aliases=None):
    item = deepcopy(item)
    payload = item["payload"]
    payload.update(comparison_mode="unified", unified_selection_version=VERSION,
                   prompt_version=PROMPT_VERSION)
    payload["cards"] = [card_projection(c) for c in payload.get("cards", [])]
    for template in payload.get("templates", []):
        if "evidence_cards" in template:
            template["evidence_cards"] = [card_projection(c) for c in template["evidence_cards"]]
    # 模板名称只保留为召回出处；选择仍由当前对象事实与可见组合决定。
    if registry:
        payload["feedback_registry_ref"] = registry.get("registry_ref")
    evidence_ids = {c["card_id"] for c in payload["cards"]}
    evidence_ids.update(c["card_id"] for t in payload.get("templates", []) for c in t.get("evidence_cards", []))
    payload["active_feedback"] = feedback_module().relevant_feedback(registry or {"issues": []}, sorted(evidence_ids), aliases=aliases)
    if item["stage"] != "visual":
        return item
    schema = item["schema"]
    text = {"type": "string", "minLength": 1, "maxLength": 900}
    identity = {"type": "string", "minLength": 1, "maxLength": 160}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def arr(value, maximum, minimum=0):
        return {"type": "array", "items": value, "minItems": minimum, "maxItems": maximum}

    def enum(*values):
        return {"type": "string", "enum": list(values)}

    group = schema["properties"]["groups"]["items"]
    group["properties"]["relation_key"] = deepcopy(identity)
    group["required"] = list(dict.fromkeys([*group["required"], "relation_key"]))
    evidence = group["properties"]["member_evidence"]["items"]
    if "why_coordinated" in evidence["properties"]:
        evidence["properties"]["decision_basis"] = evidence["properties"].pop("why_coordinated")
    evidence["required"] = ["decision_basis" if x == "why_coordinated" else x for x in evidence["required"]]
    pair = group["properties"]["hardest_pair"]
    pair["properties"]["verdict"] = enum("coherent", "conflict", "unresolved")
    pair["required"] = list(dict.fromkeys([*pair["required"], "verdict"]))
    prefix = {
        "relation_hypotheses": arr(obj({
            "relation_key": deepcopy(identity), "dominant_relation": text,
            "must_hold": arr(obj({"dimension": enum("palette", "silhouette", "planes", "lines", "optics", "texture", "details"),
                                  "condition": text}), 7, 1),
            "allowed_variations": arr(text, 7), "break_conditions": arr(text, 7, 1)}), 8),
        "candidate_decisions": arr(obj({
            "card_id": deepcopy(identity), "relation_key": {"type": ["string", "null"]},
            "decision": enum("include", "exclude", "unresolved"),
            "dominant_evidence": text, "strongest_conflict": text,
            "conflict_effect": enum("compatible_variation", "dominant_conflict", "uncertain"),
            "reason": text}), 24),
    }
    schema["properties"] = {**prefix, **schema["properties"],
                            "feedback_decisions": arr(feedback_module().FEEDBACK_DECISION_SCHEMA,
                                                      len(payload["active_feedback"]))}
    schema["required"] = list(schema["properties"])
    return item


def validate_decisions(answer, payload):
    """只拦截决策自相矛盾及遗漏；不能把文本完整性当作审美正确率。"""
    if payload.get("task") != "visual":
        return
    allowed = {c["card_id"] for c in payload["cards"]}
    hypotheses = {h["relation_key"]: h for h in answer["relation_hypotheses"]}
    if len(hypotheses) != len(answer["relation_hypotheses"]):
        raise ValueError("统一关系假设身份重复")
    decisions = {d["card_id"]: d for d in answer["candidate_decisions"]}
    if len(decisions) != len(answer["candidate_decisions"]) or set(decisions) != allowed:
        raise ValueError("候选决策必须恰好覆盖全部当前卡")
    for row in decisions.values():
        if row["relation_key"] is not None and row["relation_key"] not in hypotheses:
            raise ValueError("候选决策引用未知关系")
        if row["conflict_effect"] == "dominant_conflict" and row["decision"] != "exclude":
            raise ValueError("已判断主导冲突的候选必须排除")
        if row["decision"] == "include" and (row["conflict_effect"] != "compatible_variation" or row["relation_key"] is None):
            raise ValueError("未决或没有具体关系的候选不得入组")
    selected = set()
    for group in answer["groups"]:
        key = group["relation_key"]
        if key not in hypotheses or group["dominant_relation"] != hypotheses[key]["dominant_relation"]:
            raise ValueError("成员确定后不能改宽原关系假设")
        if group["hardest_pair"]["verdict"] != "coherent":
            raise ValueError("最不一致对仍冲突或未决，不能保留该组")
        for identity in group["member_ids"]:
            row = decisions.get(identity, {})
            if row.get("decision") != "include" or row.get("relation_key") != key:
                raise ValueError("入组成员与先前取舍不一致")
            selected.add(identity)
    if selected != {key for key, row in decisions.items() if row["decision"] == "include"}:
        raise ValueError("已选择候选没有对应真实组")
    feedback_module().validate_feedback_decisions(answer, payload)
