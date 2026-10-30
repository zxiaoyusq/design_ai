"""所选设计对象及其整体情绪的轻量契约；主观视觉解释不冒充物理DNA。"""
from __future__ import annotations

from copy import deepcopy
import math


DESIGN_EMOTION_VERSION = "prism.design_emotion.v1"
EMOTION_AXES = {
    "affinity": ("welcoming", "balanced", "reserved"),
    "discipline": ("relaxed", "balanced", "precise"),
    "energy": ("calm", "balanced", "lively"),
    "weight": ("light", "balanced", "grounded"),
}
EMOTION_BASIS_FIELDS = ("form", "proportion", "color", "material_texture", "detail_language")
PRIMARY_ROLES = {"primary_object", "primary_object_surface", "primary_architectural_surface",
                 "peer_object", "peer_object_surface"}
SELECTED_OBJECT_VERSION = "prism.dna_cluster_observation.v3"
DISPLAY_SCOPES = {"whole_object", "representative_detail"}

EMOTION_OBSERVATION_INSTRUCTIONS = """设计情绪是形态、比例、色彩、材料质感及细节语言组合后的整体视觉感受，是有可见依据的主观解释，不是物理DNA、真实触感或普遍心理结论。不同材料和不同品类可以产生相容的情绪；同为圆润轮廓也不能自动相同：柔织物、浅暖色、宽松细节的组合与镜面反光、锐利接缝、精密边缘的组合可能不同。不能仅凭任一材质名、圆润、颜色或单个局部决定结果，也不能用预设风格词反向填轴。
对当前指定设计对象分别记录visible_basis五项：form实际可见的形态与轮廓；proportion当前可见比例及体量安排；color该对象配色和视觉对比；material_texture实际光泽、反射、纹样与表面观感；detail_language接缝、边缘、连接、装饰等细节语言。对象可以是主物品或与其同级的其他设计物品，不能借同图其他物品的组合感受。每项为具体中文短句，缺证据填null，不猜真实成分或画外形态；展示采用局部时仍用原图对象上下文核查组合，不裁掉冲突制造统一。
随后综合五项的相互加强或牵制填写四轴：affinity=welcoming（外观趋于亲和、可接近）、reserved（外观趋于疏离、克制距离感）或balanced；discipline=relaxed（组织舒展松弛、约束感弱）、precise（秩序精密、边界与连接控制感强）或balanced；energy=calm（安静稳定）、lively（活泼跳跃）或balanced；weight=light（轻快、轻盈的视觉感）、grounded（稳重、厚实的视觉感）或balanced。每轴都由整体组合判断，不是一项物理特征的同义词，无法判断填null。
coordination_reason须说明哪些形态/比例/色彩/表面/细节共同形成当前感受，若有反向信号要解释其作用，不能只是罗列五项。expression以自然中文概括当前组合感受，可用亲和松弛、冷静精密、活泼轻快等表达，也可自行措辞；这只是展示文本，不是固定风格类别，不能用标签替代组合依据。
status=supported表示当前所选设计对象可见范围已有充分组合依据，不要求看见画面外部分；limited表示已有倾向但关键证据欠缺或冲突未明；unresolved表示无法作可靠组合判断。limitations保留遮挡、裁切、分辨率和无法归因之处，不因想成板而抬高状态。"""


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def emotion_schema() -> dict:
    """Schema允许真实未知，候选资格与聚类阈值由单独的选择政策处理。"""
    return _object({
        "status": {"type": "string", "enum": ["supported", "limited", "unresolved"]},
        "axes": _object({name: {"type": ["string", "null"], "enum": [*values, None]}
                         for name, values in EMOTION_AXES.items()}),
        "visible_basis": _object({name: {"type": ["string", "null"]} for name in EMOTION_BASIS_FIELDS}),
        "coordination_reason": {"type": "string"}, "expression": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    })


def validate_emotion(value: dict) -> None:
    """只核事实解释的结构，不由文本长短、情绪标签或材质名授予视觉通过。"""
    if not isinstance(value, dict) or set(value) != set(emotion_schema()["properties"]):
        raise ValueError("design_emotion字段不完整或含未定义键")
    if not isinstance(value["status"], str) or value["status"] not in {"supported", "limited", "unresolved"}:
        raise ValueError("design_emotion.status不合法")
    if not isinstance(value["axes"], dict) or set(value["axes"]) != set(EMOTION_AXES):
        raise ValueError("设计情绪四轴必须完整保留，未知用null")
    for name, values in EMOTION_AXES.items():
        if value["axes"][name] is not None and value["axes"][name] not in values:
            raise ValueError(f"设计情绪{name}取值不合法")
    basis = value["visible_basis"]
    if not isinstance(basis, dict) or set(basis) != set(EMOTION_BASIS_FIELDS):
        raise ValueError("设计情绪须保留五类组合依据，未知用null")
    if any(item is not None and (not isinstance(item, str) or not item.strip()) for item in basis.values()):
        raise ValueError("设计情绪依据必须是可见短句或null，不能用空白冒充依据")
    if any(not isinstance(value[key], str) for key in ("coordination_reason", "expression")):
        raise ValueError("组合理由和自然语言表达须为字符串")
    if not isinstance(value["limitations"], list) or any(not isinstance(item, str) for item in value["limitations"]):
        raise ValueError("设计情绪限制须为文字数组")


def _valid_bbox(value: object) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)
            and value[0] >= 0 and value[1] >= 0 and value[2] > 0 and value[3] > 0
            and value[0] + value[2] <= 1.00001 and value[1] + value[3] <= 1.00001)


def _same_bbox(left: object, right: object) -> bool:
    return (_valid_bbox(left) and _valid_bbox(right)
            and all(abs(a - b) <= 1e-5 for a, b in zip(left, right, strict=True)))


def _contains_bbox(outer: list, inner: list) -> bool:
    return (outer[0] <= inner[0] + 1e-5 and outer[1] <= inner[1] + 1e-5
            and outer[0] + outer[2] >= inner[0] + inner[2] - 1e-5
            and outer[1] + outer[3] >= inner[1] + inner[3] - 1e-5)


def validate_display_contract(unit: dict) -> None:
    """v3只校验真实取景契约；表达是否清楚、是否裁掉冲突仍由原图与实板审阅。"""
    scope = unit.get("display_scope")
    if scope not in DISPLAY_SCOPES or not isinstance(unit.get("crop_reason"), str) or not unit["crop_reason"].strip():
        raise ValueError("新取景须明确display_scope和有依据的crop_reason")
    subject = unit.get("primary_subject", {})
    boxes = (subject.get("bbox"), unit.get("evidence_bbox"), unit.get("display_bbox"))
    if not all(_valid_bbox(box) for box in boxes):
        raise ValueError("对象、事实或展示框不合法")
    subject_box, evidence_box, display_box = boxes
    if not _same_bbox(unit.get("bbox"), evidence_box):
        raise ValueError("bbox须保留为evidence_bbox，不能把展示框写成事实")
    if not _contains_bbox(display_box, evidence_box):
        raise ValueError("实际展示框须包含本单元事实证据，不能把事实藏到框外")
    if unit.get("target_role") in PRIMARY_ROLES and not _contains_bbox(subject_box, evidence_box):
        raise ValueError("事实须属于所选设计对象，不能借用背景")
    if scope == "whole_object" and not _contains_bbox(display_box, subject_box):
        raise ValueError("whole_object展示须完整包含所选对象")
    if not unit.get("usable"):
        return
    if unit.get("target_role") not in PRIMARY_ROLES:
        raise ValueError("可用目标只能是主物品或有明确依据的同级设计对象")
    if unit.get("branch") == "ID":
        if unit["target_role"] not in {"primary_object", "peer_object"}:
            raise ValueError("ID须绑定所选设计对象，不能以背景表面冒充")
        if scope == "whole_object" and (not unit.get("whole_object_visible") or not subject.get("whole_visible")
                                       or not _contains_bbox(evidence_box, subject_box)):
            raise ValueError("整物ID须有完整对象事实；代表性局部必须显式另标范围")
    elif unit.get("branch") == "CMF" and unit["target_role"] in {"primary_object", "peer_object"}:
        raise ValueError("CMF须声明所选对象的表面角色")
    if ((not subject.get("whole_visible")) or (unit.get("branch") == "ID" and scope == "representative_detail")):
        saved = unit.get("subject_visibility_limitations") or {}
        limits = [*unit.get("limitations", []), *saved.get("unit", []), *saved.get("image", [])]
        if not any(isinstance(line, str) and line.strip() for line in limits):
            raise ValueError("代表性ID局部或原图不完整对象须保留明确的观察范围限制")


def selected_subject_groups(units: list[dict]) -> list[dict]:
    """同图多个同级对象独立分组；同对象才共享情绪，不用品类或文字相近猜归属。"""
    groups = []
    for unit in units:
        binding = primary_subject_binding([unit])
        if binding is None:
            continue
        match = None
        for group in groups:
            prior = group["primary_subject"]
            same_identity = prior["identity"] == binding["identity"]
            same_box = _same_bbox(prior["bbox"], binding["bbox"])
            if same_identity != same_box:
                raise ValueError("同一对象身份和位置声明冲突，不能混借另一对象情绪")
            if same_identity:
                match = group
                break
        if match is None:
            match = {"primary_subject": binding, "unit_ids": []}
            groups.append(match)
        match["unit_ids"].append(unit["unit_id"])
    return groups


def primary_subject_binding(units: list[dict]) -> dict | None:
    """返回同一所选对象绑定；历史键名保留，多对象调用方须先分组。"""
    subjects = [unit.get("primary_subject") for unit in units
                if unit.get("usable") is True and unit.get("target_role") in PRIMARY_ROLES]
    if not subjects:
        return None
    for subject in subjects:
        if (not isinstance(subject, dict) or not isinstance(subject.get("identity"), str)
                or not subject["identity"].strip() or not _valid_bbox(subject.get("bbox"))):
            raise ValueError("设计情绪绑定缺少明确主体身份或合法主体框")
    first = subjects[0]
    if any(subject["identity"].strip() != first["identity"].strip()
           or not _same_bbox(subject["bbox"], first["bbox"]) for subject in subjects[1:]):
        raise ValueError("同图存在不同主物品声明，不能共享一份设计情绪")
    return {"identity": first["identity"].strip(), "bbox": list(first["bbox"])}


def bind_emotion(value: dict, image: dict, subject: dict, source: dict) -> dict:
    """绑定实际原图及原回答位置；调用方传递真实回执，不推断模型身份或执行时间。"""
    validate_emotion(value)
    return {"design_emotion": deepcopy(value), "design_emotion_provenance": {
        **source, "schema_version": DESIGN_EMOTION_VERSION,
        "image_id": image["image_id"], "image_sha256": image["sha256"],
        "primary_subject_identity": subject["identity"], "primary_subject_bbox": list(subject["bbox"]),
        "inference_kind": "subjective_visual_interpretation", "universal_user_emotion_claimed": False,
        "raw_physical_DNA_modified": False}}


def emotion_binding_matches(unit: dict) -> bool:
    """结构、主体与出处须同时相符；旧tone字段不能冒充新的组合情绪观察。"""
    try:
        validate_emotion(unit.get("design_emotion"))
        binding = primary_subject_binding([unit])
        provenance = unit.get("design_emotion_provenance", {})
        if binding is None or not isinstance(provenance, dict):
            return False
        required = (provenance.get("schema_version") == DESIGN_EMOTION_VERSION
                    and provenance.get("image_id") == unit.get("image_id")
                    and bool(unit.get("image_sha256"))
                    and provenance.get("image_sha256") == unit["image_sha256"]
                    and provenance.get("primary_subject_identity") == binding["identity"]
                    and _same_bbox(provenance.get("primary_subject_bbox"), binding["bbox"])
                    and provenance.get("inference_kind") == "subjective_visual_interpretation"
                    and bool(provenance.get("observation_pointer")) and bool(provenance.get("prompt_version")))
        for key in ("observation_ref", "receipt_ref"):
            reference = provenance.get(key, {})
            required = required and isinstance(reference, dict) and bool(reference.get("path")) and bool(reference.get("sha256"))
        return bool(required)
    except (ValueError, TypeError, KeyError):
        return False
