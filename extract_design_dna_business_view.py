#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 multimodal-design-dna-extractor Skill 的完整结果 JSON，转换为适合设计业务人员展示的精简 JSON。

兼容输入：design_dna_extraction_v3.1
依赖：仅 Python 标准库，Python 3.9+

单文件用法：
    python extract_design_dna_business_view.py data/result/20260830_153012_product_design_dna.json

    默认输出：
    data/result/20260830_153012_product_design_dna_business_view.json

批量目录用法：
    python extract_design_dna_business_view.py data/result --recursive

显式指定输出：
    python extract_design_dna_business_view.py full_result.json -o business_view.json

作为 Python 模块调用：
    from extract_design_dna_business_view import BusinessViewConfig, extract_business_view
    business_view = extract_business_view(full_result, BusinessViewConfig())

说明：
- 不修改原始 Skill，也不调用大模型。
- 只做确定性字段筛选、证据聚合、置信度分级和业务字段重组。
- 完整 JSON 仍应作为后台审计、检索、评分和知识库演进的数据源。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


BUSINESS_SCHEMA_VERSION = "design_dna_business_view_v1.1"
SUPPORTED_SOURCE_SCHEMA = "design_dna_extraction_v3.1"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "result"
BUSINESS_VIEW_SUFFIX = "_business_view.json"


@dataclass(frozen=True)
class BusinessViewConfig:
    """业务视图提取参数。"""

    max_key_dna: int = 15
    max_secondary_styles: int = 2
    max_style_evidence: int = 3
    max_uncertain_fields: int = 3
    max_novel_dna: int = 3
    max_style_keywords: int = 5
    max_warnings: int = 5
    max_missing_critical_fields: int = 5
    min_dna_confidence: float = 0.55
    high_confidence_threshold: float = 0.80
    medium_confidence_threshold: float = 0.60
    include_source_trace: bool = False
    include_contextual_modules: bool = False


VIEW_LABELS = {
    "front": "正面",
    "rear": "背面",
    "left": "左侧",
    "right": "右侧",
    "top": "顶部",
    "bottom": "底部",
    "three_quarter": "四分之三视角",
    "detail": "局部特写",
    "unknown": "未知视角",
}

CATEGORY_LABELS = {
    "smartphone": "智能手机",
    "phone": "手机",
    "mobile_phone": "手机",
    "apparel": "服装",
    "clothing": "服装",
    "dress": "连衣裙",
    "footwear": "鞋类",
    "shoe": "鞋类",
    "sneaker": "运动鞋",
    "furniture": "家具",
    "chair": "座椅",
    "sofa": "沙发",
    "automotive": "汽车",
    "car": "汽车",
    "vehicle": "交通工具",
    "transportation": "交通工具",
}

SUBCATEGORY_LABELS = {
    "bar_phone": "直板智能手机",
    "midi_dress": "中长连衣裙",
    "micro_bubble_car": "微型泡泡车",
}

STATUS_LABELS = {
    "confirmed": "已确认",
    "provisional": "暂定",
    "unclassified": "未分类",
}

NOVELTY_TYPE_LABELS = {
    "new_module": "新模块",
    "new_field": "新字段",
    "new_enum_value": "新枚举值",
    "new_relation_rule": "新关系规则",
}

PRIORITY_RECOMMENDATIONS = {
    "P0": "建议优先纳入标准",
    "P1": "建议进入专家评审",
    "observe_more": "建议持续观察",
}

ORIGINAL_DIMENSION_GROUPS = {
    "ID形态": "形态与体量",
    "相机架构": "品类专属",
    "颜色": "色彩",
    "材质工艺": "CMF",
    "纹理图案": "纹理与图案",
    "设计细节": "设计细节",
}

MODULE_GROUPS = {
    "DNA-M01": "形态与体量",
    "DNA-M02": "形态与体量",
    "DNA-M03": "构图与秩序",
    "DNA-M04": "品类专属",
    "DNA-M05": "品类专属",
    "DNA-M06": "色彩",
    "DNA-M07": "CMF",
    "DNA-M08": "纹理与图案",
    "DNA-M09": "设计细节",
    "DNA-M10": "品牌与系列",
    "DNA-M11": "光影与光学",
    "DNA-M12": "功能与人因",
    "DNA-M13": "语义坐标",
    "DNA-M14": "意向与场景",
    "DNA-M15": "方案关系与趋势",
}

GROUP_ORDER = [
    "形态与体量",
    "构图与秩序",
    "色彩",
    "CMF",
    "纹理与图案",
    "设计细节",
    "品类专属",
    "品牌与系列",
    "光影与光学",
    "功能与人因",
    "意向与场景",
    "方案关系与趋势",
    "其他",
]

GROUP_CAPS = {
    "形态与体量": 3,
    "构图与秩序": 3,
    "色彩": 3,
    "CMF": 3,
    "纹理与图案": 2,
    "设计细节": 2,
    "品类专属": 4,
    "品牌与系列": 1,
    "光影与光学": 1,
    "功能与人因": 1,
    "意向与场景": 1,
    "方案关系与趋势": 1,
    "其他": 1,
}

GROUP_BASE_WEIGHTS = {
    "形态与体量": 13.0,
    "构图与秩序": 13.0,
    "色彩": 12.0,
    "CMF": 11.0,
    "纹理与图案": 8.0,
    "设计细节": 10.0,
    "品类专属": 15.0,
    "品牌与系列": 5.0,
    "光影与光学": 5.0,
    "功能与人因": 2.0,
    "意向与场景": 2.0,
    "方案关系与趋势": 0.0,
    "其他": 0.0,
}

CORE_GROUPS = [
    "形态与体量",
    "构图与秩序",
    "色彩",
    "CMF",
    "品类专属",
    "纹理与图案",
    "设计细节",
]

CORE_SEMANTIC_AXES = {
    "SEM-01": "极简—装饰",
    "SEM-02": "硬朗—柔和",
    "SEM-03": "轻盈—厚重",
    "SEM-04": "安静—动感",
    "SEM-06": "自然—科技",
    "SEM-08": "克制—张扬",
}

HIGH_VALUE_FIELD_IDS = {
    # 形态与构图
    "GEO-02", "GEO-03", "GEO-05", "GEO-06", "GEO-10", "GEO-11", "GEO-12",
    "FORM-01", "FORM-03", "FORM-04", "FORM-07", "FORM-10", "FORM-11",
    "CMP-01", "CMP-02", "CMP-03", "CMP-04", "CMP-05", "CMP-06", "CMP-09", "CMP-10", "CMP-13", "CMP-15",
    # 手机品类专属
    "CAM-03", "CAM-04", "CAM-05", "CAM-06", "CAM-07", "CAM-10", "CAM-11", "CAM-13", "CAM-16", "CAM-17",
    "FRN-03", "FRN-05", "FRN-06", "FRN-08", "FRN-09", "FRN-12",
    # 色彩、CMF、纹理、细节
    "CLR-01", "CLR-02", "CLR-03", "CLR-07", "CLR-08", "CLR-11", "CLR-12", "CLR-13", "CLR-14", "CLR-16",
    "CMF-01", "CMF-04", "CMF-05", "CMF-07", "CMF-08", "CMF-09", "CMF-10", "CMF-11", "CMF-12", "CMF-13",
    "TEX-01", "TEX-02", "TEX-03", "TEX-04", "TEX-05", "TEX-07", "TEX-08", "TEX-10", "TEX-11", "TEX-12",
    "DET-01", "DET-02", "DET-05", "DET-08", "DET-09", "DET-10", "DET-11", "DET-12", "DET-13", "DET-14", "DET-15",
    # 可直接观察的品牌/光学字段
    "BRD-01", "BRD-03", "BRD-04", "BRD-05", "BRD-06", "BRD-09",
    "OPT-06", "OPT-07", "OPT-08", "OPT-09", "OPT-10", "OPT-11", "OPT-13",
}

COMPARISON_DEPENDENT_FIELD_IDS = {
    "BRD-07", "BRD-08", "BRD-10", "BRD-11", "BRD-12",
    "REL-01", "REL-02", "REL-03", "REL-05", "REL-06", "REL-07", "REL-08", "REL-09", "REL-10",
}

TECHNICAL_ONLY_FIELD_IDS = {
    "CLR-18",  # 颜色可靠度
    "OPT-14",  # 光照混淆风险
    "IMG-14",  # 语义证据链
}

HIGH_VALUE_NAME_KEYWORDS = (
    "整体轮廓", "主体廓形", "版型", "比例", "体量", "视觉厚度", "视觉重心",
    "主导线性", "边缘", "曲面", "边界", "转接", "构图", "对称", "平衡",
    "视觉焦点", "视觉层级", "层级强度", "信息密度", "留白", "主要对比",
    "主体颜色", "主色", "辅色", "点缀色", "配色", "色温", "渐变",
    "主体材质", "视觉材质", "材质关系", "材质对比", "表面处理", "工艺",
    "光泽", "反射", "透明", "触感", "纹理", "图案", "装饰", "标志性",
    "相机", "镜头", "模组", "屏幕", "前摄", "按键", "端口", "灯组",
    "领型", "领口", "袖型", "袖", "腰线", "衣长", "裙摆", "裁片", "闭合",
    "鞋底", "鞋面", "鞋型", "系带", "前脸", "车身", "支撑", "腿部", "软包",
)

TECHNICAL_NAME_KEYWORDS = (
    "可靠度", "混淆风险", "证据链", "归一化坐标", "中心坐标", "参考集版本",
)

NUMERIC_DETAIL_KEYWORDS = (
    "面积占比", "长宽比", "直径占比", "数量", "中心与跨度", "中心位置",
)

CATEGORY_SPECIFIC_KEYWORDS = {
    "smartphone": ("相机", "镜头", "模组", "背板", "中框", "屏幕", "前摄", "按键", "端口", "扬声器"),
    "apparel": ("廓形", "版型", "领", "袖", "腰", "衣长", "裙摆", "裁片", "闭合", "面料", "垂坠", "褶", "拼接"),
    "footwear": ("鞋型", "鞋底", "鞋面", "系带", "鞋头", "后跟", "中底", "外底", "支撑"),
    "furniture": ("主体结构", "支撑", "腿", "软包", "靠背", "座面", "连接", "转角"),
    "automotive": ("车身", "姿态", "前脸", "灯组", "格栅", "轮眉", "型面", "尾灯", "扰流", "空气动力"),
}


class BusinessViewError(ValueError):
    """输入结构不符合预期。"""


def _unique(items: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    seen: set[str] = set()
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
            key = f"s:{item}"
        else:
            try:
                key = "j:" + json.dumps(item, ensure_ascii=False, sort_keys=True)
            except TypeError:
                key = "r:" + repr(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, number))


def _confidence_label(value: Any, config: BusinessViewConfig) -> str:
    score = _clamp(value)
    if score >= config.high_confidence_threshold:
        return "高"
    if score >= config.medium_confidence_threshold:
        return "中"
    return "低"


def _round_score(value: Any, digits: int = 2) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _display_code(value: Any, mapping: Mapping[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    return mapping.get(value, value)


def _normalize_level_1(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return re.sub(r"^\s*\d+\s*[\.、]\s*", "", value).strip()


def _normalize_level_2(value: Any) -> Any:
    """将 `English / （中文）` 转为更适合业务展示的 `中文（English）`。"""
    if not isinstance(value, str):
        return value
    raw = value.strip()
    chinese_match = re.search(r"[（(]\s*([^（）()]+?)\s*[）)]", raw)
    english = raw.split("/", 1)[0].strip() if "/" in raw else ""
    chinese = chinese_match.group(1).strip() if chinese_match else ""
    if chinese and english and chinese != english:
        return f"{chinese}（{english}）"
    return chinese or raw


def _value_is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "unknown", "not_observable", "null", "n/a", "na", "—", "-"}
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _value_is_none(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"none", "无", "不存在"}


def _normalize_business_value(value: Any) -> Any:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower == "none":
            return "无"
        return value.strip()
    if isinstance(value, list):
        return [_normalize_business_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalize_business_value(v) for k, v in value.items()}
    return value


def _value_to_text(value: Any, max_length: int = 90) -> str:
    value = _normalize_business_value(value)
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "是" if value else "否"
    elif isinstance(value, list):
        text = "、".join(_value_to_text(v, max_length=max_length) for v in value)
    elif isinstance(value, dict):
        parts = [f"{k}={_value_to_text(v, max_length=max_length)}" for k, v in value.items()]
        text = "；".join(parts)
    else:
        text = str(value)
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"
    return text


def _unwrap_result(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise BusinessViewError("输入 JSON 根节点必须是对象。")
    if "target_object" in payload and "design_elements" in payload:
        return payload
    for key in ("full_result", "result", "data", "output", "analysis", "design_dna_result"):
        nested = payload.get(key)
        if isinstance(nested, dict) and "target_object" in nested and "design_elements" in nested:
            return nested
    raise BusinessViewError("未找到完整 DNA 结果：缺少 target_object 或 design_elements。")


def _build_evidence_map(data: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for item in data.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            result[evidence_id] = item
    return result


def _resolve_evidence_texts(
    refs: Sequence[Any],
    evidence_map: Mapping[str, Mapping[str, Any]],
    max_items: int,
) -> List[str]:
    texts: List[str] = []
    for ref in refs or []:
        if not isinstance(ref, str):
            continue
        evidence = evidence_map.get(ref)
        if not evidence:
            continue
        description = evidence.get("description")
        if isinstance(description, str) and description.strip():
            texts.append(description.strip())
        elif isinstance(evidence.get("visual_cues"), list):
            cues = [str(v).strip() for v in evidence["visual_cues"] if str(v).strip()]
            if cues:
                texts.append("、".join(cues[:3]))
    return _unique(texts)[:max_items]


def _category_bucket(category: Any, subcategory: Any = None) -> str:
    text = f"{category or ''} {subcategory or ''}".lower()
    if any(token in text for token in ("smartphone", "phone", "mobile", "手机")):
        return "smartphone"
    if any(token in text for token in ("apparel", "clothing", "garment", "dress", "shirt", "coat", "skirt", "服装", "连衣裙", "上衣", "外套", "裙")):
        return "apparel"
    if any(token in text for token in ("footwear", "shoe", "sneaker", "boot", "鞋")):
        return "footwear"
    if any(token in text for token in ("furniture", "chair", "sofa", "table", "家具", "椅", "沙发", "桌")):
        return "furniture"
    if any(token in text for token in ("automotive", "car", "vehicle", "automobile", "transportation", "汽车", "车辆", "交通工具")):
        return "automotive"
    return "generic"


def _image_usability_score(data: Mapping[str, Any]) -> float:
    target = data.get("target_object", {}) or {}
    quality = data.get("image_quality", {}) or {}
    score = (
        0.35 * _clamp(quality.get("overall_quality"), default=0.5)
        + 0.25 * _clamp(quality.get("object_visible_ratio"), default=0.5)
        + 0.20 * _clamp(target.get("selection_confidence"), default=0.5)
        + 0.10 * _clamp(quality.get("color_reliability"), default=0.5)
        + 0.10 * _clamp(quality.get("material_reliability"), default=0.5)
    )
    risk_keys = (
        "occlusion_level",
        "blur_level",
        "exposure_risk",
        "perspective_distortion",
        "background_interference",
        "lighting_bias",
    )
    risks = [_clamp(quality.get(key), default=0.0) for key in risk_keys]
    score -= 0.12 * (sum(risks) / len(risks))
    return _clamp(score)


def _image_usability_label(score: float, config: BusinessViewConfig) -> str:
    if score >= config.high_confidence_threshold:
        return "高"
    if score >= config.medium_confidence_threshold:
        return "中"
    return "低"


def _extract_object_view(data: Mapping[str, Any], config: BusinessViewConfig) -> Dict[str, Any]:
    target = data.get("target_object", {}) or {}
    score = _image_usability_score(data)
    category = target.get("category")
    subcategory = target.get("subcategory")
    result: Dict[str, Any] = {
        "category": _display_code(category, CATEGORY_LABELS),
        "subcategory": _display_code(subcategory, SUBCATEGORY_LABELS) if subcategory is not None else None,
        "view": _display_code(target.get("view", "unknown"), VIEW_LABELS),
        "image_usability": _image_usability_label(score, config),
    }
    if config.include_source_trace:
        result.update(
            {
                "category_code": category,
                "subcategory_code": subcategory,
                "view_code": target.get("view", "unknown"),
                "image_usability_score": _round_score(score),
                "object_id": target.get("object_id"),
            }
        )
    return result


def _extract_style_keywords(data: Mapping[str, Any], primary: Optional[Mapping[str, Any]], max_items: int) -> List[str]:
    keywords: List[Any] = []
    if primary:
        keywords.extend(primary.get("core_feature_hits", []) or [])
        keywords.extend(primary.get("auxiliary_feature_hits", []) or [])

    # 补充 M14 的情绪关键词，但不把整套意向模块铺到业务视图。
    design_elements = data.get("design_elements", {}) or {}
    for module in design_elements.get("extended_dna_modules", []) or []:
        if not isinstance(module, dict) or module.get("module_id") != "DNA-M14":
            continue
        for element in module.get("elements", []) or []:
            if not isinstance(element, dict) or element.get("field_id") != "IMG-03":
                continue
            value = element.get("value")
            if isinstance(value, list):
                keywords.extend(value)
            elif value is not None:
                keywords.append(value)

    return [str(item).strip() for item in _unique(keywords) if str(item).strip()][:max_items]


def _style_item_view(
    item: Mapping[str, Any],
    config: BusinessViewConfig,
    include_evidence: bool = False,
    evidence_map: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    confidence = _clamp(item.get("confidence"))
    result: Dict[str, Any] = {
        "level_1": _normalize_level_1(item.get("level_1")),
        "level_2": _normalize_level_2(item.get("level_2")),
        "match_score": _round_score(item.get("match_score"), 1),
        "confidence": _confidence_label(confidence, config),
        "confidence_score": _round_score(confidence),
    }
    if include_evidence:
        result["evidence"] = _resolve_evidence_texts(
            item.get("evidence_refs", []) or [], evidence_map or {}, config.max_style_evidence
        )
    if config.include_source_trace:
        result["level_1_raw"] = item.get("level_1")
        result["level_2_raw"] = item.get("level_2")
        result["hard_rule_passed"] = item.get("hard_rule_passed")
        result["evidence_refs"] = item.get("evidence_refs", []) or []
    return result


def _extract_style_view(
    data: Mapping[str, Any],
    evidence_map: Mapping[str, Mapping[str, Any]],
    config: BusinessViewConfig,
) -> Dict[str, Any]:
    style_result = data.get("style_result", {}) or {}
    status = style_result.get("classification_status", "unclassified")
    primary = style_result.get("primary_style")
    primary_map = primary if isinstance(primary, dict) else None

    result: Dict[str, Any] = {
        "status": STATUS_LABELS.get(status, status),
        "primary": _style_item_view(primary_map, config, False, evidence_map) if primary_map else None,
        "secondary": [],
        "keywords": _extract_style_keywords(data, primary_map, config.max_style_keywords),
        "evidence": _resolve_evidence_texts(
            primary_map.get("evidence_refs", []) if primary_map else [],
            evidence_map,
            config.max_style_evidence,
        ),
    }

    secondaries = style_result.get("secondary_styles", []) or []
    for item in secondaries[: config.max_secondary_styles]:
        if isinstance(item, dict):
            result["secondary"].append(_style_item_view(item, config))

    conflict_note = primary_map.get("conflict_arbitration") if primary_map else None
    if isinstance(conflict_note, str) and conflict_note.strip():
        result["conflict_note"] = conflict_note.strip()

    # 未分类时保留最多两个候选，避免业务端只看到空结论。
    if not primary_map:
        candidates: List[Dict[str, Any]] = []
        for item in style_result.get("candidate_ranking", []) or []:
            if not isinstance(item, dict):
                continue
            candidate = _style_item_view(item, config)
            candidate["main_support"] = (item.get("main_support", []) or [])[:3]
            candidate["main_conflicts"] = (item.get("main_conflicts", []) or [])[:3]
            candidates.append(candidate)
            if len(candidates) >= 2:
                break
        result["candidates"] = candidates

    if config.include_source_trace:
        result["status_code"] = status
    return result


def _flatten_elements(data: Mapping[str, Any]) -> List[Dict[str, Any]]:
    elements_root = data.get("design_elements", {}) or {}
    flattened: List[Dict[str, Any]] = []

    for dimension in elements_root.get("original_md_dimensions", []) or []:
        if not isinstance(dimension, dict):
            continue
        dimension_name = str(dimension.get("dimension") or "其他")
        group = ORIGINAL_DIMENSION_GROUPS.get(dimension_name, "其他")
        for element in dimension.get("elements", []) or []:
            if isinstance(element, dict):
                flattened.append(
                    {
                        "element": element,
                        "group": group,
                        "source_kind": "original",
                        "source_container_id": dimension_name,
                        "source_container_name": dimension_name,
                    }
                )

    for module in elements_root.get("extended_dna_modules", []) or []:
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("module_id") or "")
        module_name = str(module.get("module_name") or module_id or "其他")
        group = MODULE_GROUPS.get(module_id, "其他")
        for element in module.get("elements", []) or []:
            if isinstance(element, dict):
                flattened.append(
                    {
                        "element": element,
                        "group": group,
                        "source_kind": "extension",
                        "source_container_id": module_id,
                        "source_container_name": module_name,
                    }
                )
    return flattened


def _is_business_eligible(record: Mapping[str, Any], config: BusinessViewConfig) -> bool:
    element = record.get("element", {}) or {}
    module_id = str(record.get("source_container_id") or "")
    field_id = str(element.get("field_id") or "")
    field_name = str(element.get("field_name") or "")
    value = element.get("value")
    observability = element.get("observability")
    confidence = _clamp(element.get("confidence"))

    if observability not in {"observed", "inferred"}:
        return False
    if _value_is_missing(value):
        return False
    if confidence < config.min_dna_confidence:
        return False
    if field_id in TECHNICAL_ONLY_FIELD_IDS:
        return False
    if any(keyword in field_name for keyword in TECHNICAL_NAME_KEYWORDS):
        return False
    if module_id == "DNA-M13":
        return False

    # 默认不展示需要外部参考集或较强主观推断的模块。
    if module_id == "DNA-M15" and not config.include_contextual_modules:
        return False
    if module_id == "DNA-M12" and not config.include_contextual_modules:
        return False
    if module_id == "DNA-M14" and not config.include_contextual_modules:
        return False
    if field_id in COMPARISON_DEPENDENT_FIELD_IDS and not config.include_contextual_modules:
        return False

    # 光学模块仅保留真正成为设计特征的字段，避免把棚拍高光当 DNA。
    if module_id == "DNA-M11" and not config.include_contextual_modules:
        if field_id not in {"OPT-06", "OPT-07", "OPT-08", "OPT-09", "OPT-10", "OPT-11", "OPT-13"}:
            return False
        if _value_is_none(value):
            return False
        if confidence < 0.75:
            return False

    # 品牌模块默认只保留可直接观察的显性设计编码。
    if module_id == "DNA-M10" and not config.include_contextual_modules:
        if field_id not in {"BRD-01", "BRD-03", "BRD-04", "BRD-05", "BRD-06", "BRD-09"}:
            return False
        if confidence < 0.75:
            return False

    return True


def _element_relevance_score(record: Mapping[str, Any], category_bucket: str) -> float:
    element = record.get("element", {}) or {}
    group = str(record.get("group") or "其他")
    field_id = str(element.get("field_id") or "")
    field_name = str(element.get("field_name") or "")
    value = element.get("value")
    confidence = _clamp(element.get("confidence"))
    observability = element.get("observability")
    source_kind = record.get("source_kind")

    score = confidence * 58.0
    score += GROUP_BASE_WEIGHTS.get(group, 0.0)
    score += 11.0 if observability == "observed" else 3.0
    score += 7.0 if source_kind == "original" else 0.0
    score += 9.0 if field_id in HIGH_VALUE_FIELD_IDS else 0.0
    score += 8.0 if any(keyword in field_name for keyword in HIGH_VALUE_NAME_KEYWORDS) else 0.0
    score += 4.0 if element.get("evidence_refs") else 0.0

    category_keywords = CATEGORY_SPECIFIC_KEYWORDS.get(category_bucket, ())
    if category_keywords and any(keyword in field_name for keyword in category_keywords):
        score += 14.0

    if any(keyword in field_name for keyword in NUMERIC_DETAIL_KEYWORDS):
        score -= 4.0
    if _value_is_none(value):
        score -= 7.0
    if group in {"品牌与系列", "光影与光学", "功能与人因", "意向与场景", "方案关系与趋势"}:
        score -= 4.0

    return score


def _design_role(group: str, field_name: str, category_bucket: str) -> str:
    if any(token in field_name for token in ("签名", "标识", "品牌", "铭牌")):
        return "签名元素"
    if group == "形态与体量":
        return "基础造型"
    if group == "构图与秩序":
        return "视觉秩序"
    if group == "色彩":
        return "整体基调" if any(token in field_name for token in ("主色", "主体颜色", "色温")) else "色彩关系"
    if group == "CMF":
        return "品质表达"
    if group == "纹理与图案":
        return "表面语言"
    if group == "设计细节":
        return "识别细节"
    if group == "品类专属":
        if category_bucket == "smartphone" and any(token in field_name for token in ("相机", "镜头", "模组")):
            return "主导识别"
        return "品类结构"
    if group == "品牌与系列":
        return "品牌识别"
    if group == "光影与光学":
        return "光学表现"
    if group == "功能与人因":
        return "使用感知"
    if group == "意向与场景":
        return "情绪表达"
    if group == "方案关系与趋势":
        return "关系判断"
    return "辅助特征"


def _semantic_record_key(record: Mapping[str, Any]) -> Tuple[str, str]:
    """生成面向业务语义的去重键，合并同义或同结果字段。"""
    element = record.get("element", {}) or {}
    group = str(record.get("group") or "其他")
    field_name = re.sub(r"\s+", "", str(element.get("field_name") or "")).lower()
    value = element.get("value")

    # “纹理家族=无”和“显性纹理图案=无”对业务人员表达的是同一个事实。
    if group == "纹理与图案" and _value_is_none(value):
        return (group, "无显性纹理图案")

    return (group, field_name)


def _deduplicate_records(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """相同业务语义只保留得分更高者。"""
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in records:
        key = _semantic_record_key(record)
        current = best.get(key)
        if current is None or float(record.get("_score", 0.0)) > float(current.get("_score", 0.0)):
            best[key] = record
    return list(best.values())


def _select_key_dna_records(
    data: Mapping[str, Any], config: BusinessViewConfig
) -> List[Dict[str, Any]]:
    target = data.get("target_object", {}) or {}
    category_bucket = _category_bucket(target.get("category"), target.get("subcategory"))

    eligible: List[Dict[str, Any]] = []
    for record in _flatten_elements(data):
        if not _is_business_eligible(record, config):
            continue
        enriched = dict(record)
        enriched["_score"] = _element_relevance_score(record, category_bucket)
        eligible.append(enriched)

    eligible = _deduplicate_records(eligible)
    eligible.sort(key=lambda item: float(item.get("_score", 0.0)), reverse=True)

    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for item in eligible:
        by_group.setdefault(str(item.get("group") or "其他"), []).append(item)

    selected: List[Dict[str, Any]] = []
    selected_ids: set[int] = set()
    group_counts: Dict[str, int] = {}

    # 第一轮：核心分组若有可靠内容，至少选择一项，避免结果被单一模块垄断。
    for group in CORE_GROUPS:
        candidates = by_group.get(group, [])
        if not candidates or len(selected) >= config.max_key_dna:
            continue
        candidate = candidates[0]
        selected.append(candidate)
        selected_ids.add(id(candidate))
        group_counts[group] = 1

    # 第二轮：按综合业务价值补齐，同时遵守各分组上限。
    for candidate in eligible:
        if len(selected) >= config.max_key_dna:
            break
        if id(candidate) in selected_ids:
            continue
        group = str(candidate.get("group") or "其他")
        cap = GROUP_CAPS.get(group, 1)
        if group_counts.get(group, 0) >= cap:
            continue
        selected.append(candidate)
        selected_ids.add(id(candidate))
        group_counts[group] = group_counts.get(group, 0) + 1

    order_index = {group: idx for idx, group in enumerate(GROUP_ORDER)}
    selected.sort(
        key=lambda item: (
            order_index.get(str(item.get("group") or "其他"), 999),
            -float(item.get("_score", 0.0)),
        )
    )
    return selected


def _extract_key_dna(
    data: Mapping[str, Any],
    evidence_map: Mapping[str, Mapping[str, Any]],
    config: BusinessViewConfig,
) -> List[Dict[str, Any]]:
    target = data.get("target_object", {}) or {}
    category_bucket = _category_bucket(target.get("category"), target.get("subcategory"))
    output: List[Dict[str, Any]] = []

    for record in _select_key_dna_records(data, config):
        element = record.get("element", {}) or {}
        group = str(record.get("group") or "其他")
        confidence = _clamp(element.get("confidence"))
        evidence_texts = _resolve_evidence_texts(
            element.get("evidence_refs", []) or [], evidence_map, max_items=2
        )
        if not evidence_texts:
            raw_description = element.get("raw_visual_description")
            if isinstance(raw_description, str) and raw_description.strip():
                evidence_texts = [raw_description.strip()]

        item: Dict[str, Any] = {
            "group": group,
            "name": element.get("field_name"),
            "value": _normalize_business_value(element.get("value")),
            "design_role": _design_role(group, str(element.get("field_name") or ""), category_bucket),
            "confidence": _confidence_label(confidence, config),
            "confidence_score": _round_score(confidence),
            "evidence": "；".join(evidence_texts),
        }
        region = element.get("region")
        if isinstance(region, str) and region and region != "whole_object":
            item["region"] = region
        if element.get("observability") == "inferred":
            item["inference_note"] = "该字段为视觉推断"
        if config.include_source_trace:
            item.update(
                {
                    "source_field_id": element.get("field_id"),
                    "source_path": element.get("source_path"),
                    "source_container_id": record.get("source_container_id"),
                    "source_container_name": record.get("source_container_name"),
                    "observability": element.get("observability"),
                    "evidence_refs": element.get("evidence_refs", []) or [],
                    "selection_score": _round_score(record.get("_score"), 1),
                }
            )
        output.append(item)
    return output


def _extract_semantic_profile(data: Mapping[str, Any], config: BusinessViewConfig) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    design_elements = data.get("design_elements", {}) or {}
    for module in design_elements.get("extended_dna_modules", []) or []:
        if not isinstance(module, dict) or module.get("module_id") != "DNA-M13":
            continue
        for element in module.get("elements", []) or []:
            if not isinstance(element, dict):
                continue
            field_id = element.get("field_id")
            if field_id not in CORE_SEMANTIC_AXES:
                continue
            if element.get("observability") not in {"observed", "inferred"}:
                continue
            if _value_is_missing(element.get("value")):
                continue
            value = element.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = max(0, min(100, value))
            profile[CORE_SEMANTIC_AXES[field_id]] = value
    return profile


def _uncertain_importance(item: Mapping[str, Any]) -> float:
    field_name = str(item.get("field_name") or "")
    source_path = str(item.get("source_path") or "")
    confidence = _clamp(item.get("confidence"))
    score = (1.0 - confidence) * 20.0
    if any(keyword in field_name for keyword in HIGH_VALUE_NAME_KEYWORDS):
        score += 15.0
    if any(token in field_name + source_path for token in ("材质", "颜色", "轮廓", "构图", "相机", "版型", "面料", "纹理")):
        score += 12.0
    if item.get("reason_type") == "not_observable":
        score -= 5.0
    return score


def _extract_uncertain_fields(data: Mapping[str, Any], config: BusinessViewConfig) -> List[Dict[str, Any]]:
    items = [item for item in (data.get("uncertain_fields", []) or []) if isinstance(item, dict)]
    items.sort(key=_uncertain_importance, reverse=True)
    output: List[Dict[str, Any]] = []
    for item in items[: config.max_uncertain_fields]:
        confidence = _clamp(item.get("confidence"))
        best_estimate = item.get("best_estimate")
        result: Dict[str, Any] = {
            "field_name": item.get("field_name"),
            "best_estimate": _normalize_business_value(best_estimate) if best_estimate is not None else "暂无法判断",
            "confidence": _confidence_label(confidence, config),
            "confidence_score": _round_score(confidence),
            "reason": item.get("reason"),
            "needed_view": item.get("recommended_additional_view_or_info") or "补充更清晰或更多视角图片",
        }
        if config.include_source_trace:
            result.update(
                {
                    "source_field_id": item.get("field_id"),
                    "source_path": item.get("source_path"),
                    "reason_type": item.get("reason_type"),
                    "observability": item.get("observability"),
                }
            )
        output.append(result)
    return output


def _novel_priority(item: Mapping[str, Any]) -> Tuple[int, float]:
    priority_order = {"P0": 0, "P1": 1, "observe_more": 2}
    return (priority_order.get(str(item.get("suggested_priority")), 3), -_clamp(item.get("confidence")))


def _extract_novel_dna(data: Mapping[str, Any], config: BusinessViewConfig) -> List[Dict[str, Any]]:
    items = [item for item in (data.get("novel_dna_elements", []) or []) if isinstance(item, dict)]
    items.sort(key=_novel_priority)
    output: List[Dict[str, Any]] = []
    for item in items[: config.max_novel_dna]:
        novelty_type = str(item.get("novelty_type") or "")
        name = item.get("proposed_module_name") if novelty_type == "new_module" else item.get("proposed_field_name")
        if not name:
            name = item.get("proposed_field_name") or item.get("proposed_module_name")
        confidence = _clamp(item.get("confidence"))
        result: Dict[str, Any] = {
            "name": name,
            "type": NOVELTY_TYPE_LABELS.get(novelty_type, novelty_type),
            "current_expression": _normalize_business_value(item.get("observed_value")),
            "why_new": item.get("distinct_from_existing_fields"),
            "design_value": item.get("design_relevance"),
            "confidence": _confidence_label(confidence, config),
            "confidence_score": _round_score(confidence),
            "recommendation": PRIORITY_RECOMMENDATIONS.get(
                str(item.get("suggested_priority")), str(item.get("suggested_priority") or "建议评审")
            ),
        }
        if config.include_source_trace:
            result.update(
                {
                    "temp_id": item.get("temp_id"),
                    "novelty_type_code": novelty_type,
                    "proposed_module_id": item.get("proposed_module_id"),
                    "proposed_field_name": item.get("proposed_field_name"),
                    "definition": item.get("definition"),
                    "evidence_refs": item.get("evidence_refs", []) or [],
                }
            )
        output.append(result)
    return output


def _extract_quality_view(data: Mapping[str, Any], config: BusinessViewConfig) -> Dict[str, Any]:
    summary = data.get("quality_summary", {}) or {}
    image_quality = data.get("image_quality", {}) or {}
    mean_confidence = _clamp(summary.get("mean_confidence"), default=0.0)
    style_confidence = _clamp(summary.get("style_confidence"), default=0.0)
    usability_score = _image_usability_score(data)

    warnings = _unique(
        list(summary.get("warnings", []) or [])
        + list(image_quality.get("notes", []) or [])
    )[: config.max_warnings]

    result: Dict[str, Any] = {
        "overall_confidence": _confidence_label(mean_confidence, config),
        "overall_confidence_score": _round_score(mean_confidence),
        "style_confidence": _confidence_label(style_confidence, config),
        "visible_coverage": _round_score(summary.get("visible_coverage"), 2),
        "image_usability": _image_usability_label(usability_score, config),
        "warnings": warnings,
        "missing_critical_fields": (summary.get("missing_critical_fields", []) or [])[
            : config.max_missing_critical_fields
        ],
    }
    if config.include_source_trace:
        result["image_usability_score"] = _round_score(usability_score)
        result["low_confidence_field_count"] = summary.get("low_confidence_field_count", 0)
    return result


def _fallback_summary(
    object_view: Mapping[str, Any],
    style_view: Mapping[str, Any],
    key_dna: Sequence[Mapping[str, Any]],
) -> str:
    category = object_view.get("subcategory") or object_view.get("category") or "主物品"
    primary = style_view.get("primary")
    style_text = primary.get("level_2") if isinstance(primary, dict) else None
    parts = []
    for item in key_dna[:3]:
        name = item.get("name")
        value = item.get("value")
        if name and not _value_is_missing(value):
            parts.append(f"{name}为{_value_to_text(value)}")
    if style_text and parts:
        return f"主物品为{category}，整体偏向{style_text}；" + "，".join(parts) + "。"
    if style_text:
        return f"主物品为{category}，整体偏向{style_text}。"
    if parts:
        return f"主物品为{category}；" + "，".join(parts) + "。"
    return f"主物品为{category}，当前图片可提取信息有限。"


def extract_business_view(
    full_result: Mapping[str, Any],
    config: Optional[BusinessViewConfig] = None,
) -> Dict[str, Any]:
    """把完整 DNA 结果转换为业务展示结果。"""
    config = config or BusinessViewConfig()
    data = _unwrap_result(dict(full_result))

    source_schema = data.get("schema_version")
    if source_schema and source_schema != SUPPORTED_SOURCE_SCHEMA:
        print(
            f"警告：输入 schema_version={source_schema!r}，脚本按 {SUPPORTED_SOURCE_SCHEMA!r} 的字段结构兼容处理。",
            file=sys.stderr,
        )

    evidence_map = _build_evidence_map(data)
    object_view = _extract_object_view(data, config)
    style_view = _extract_style_view(data, evidence_map, config)
    key_dna = _extract_key_dna(data, evidence_map, config)
    semantic_profile = _extract_semantic_profile(data, config)
    uncertain_fields = _extract_uncertain_fields(data, config)
    novel_dna = _extract_novel_dna(data, config)
    quality = _extract_quality_view(data, config)

    summary = (data.get("quality_summary", {}) or {}).get("concise_summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = _fallback_summary(object_view, style_view, key_dna)
    else:
        summary = summary.strip()

    result: Dict[str, Any] = {
        "schema_version": BUSINESS_SCHEMA_VERSION,
        # 模型信息由调用方在生成业务视图后写入；独立运行脚本时明确保留空值。
        "model_id": data.get("model_id"),
        "object": object_view,
        "design_summary": summary,
        "style": style_view,
        "key_dna": key_dna,
        "semantic_profile": semantic_profile,
        "uncertain_fields": uncertain_fields,
        "novel_dna": novel_dna,
        "quality": quality,
    }
    if config.include_source_trace:
        result["source_schema_version"] = source_schema
        result["source_knowledge_base_version"] = data.get("knowledge_base_version")
        result["selection_stats"] = {
            "full_element_count": len(_flatten_elements(data)),
            "selected_key_dna_count": len(key_dna),
            "full_uncertain_count": len(data.get("uncertain_fields", []) or []),
            "selected_uncertain_count": len(uncertain_fields),
            "full_novel_dna_count": len(data.get("novel_dna_elements", []) or []),
            "selected_novel_dna_count": len(novel_dna),
        }
    return result


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise BusinessViewError(f"{path}: JSON 解析失败：{exc}") from exc
    except OSError as exc:
        raise BusinessViewError(f"{path}: 文件读取失败：{exc}") from exc
    if not isinstance(data, dict):
        raise BusinessViewError(f"{path}: JSON 根节点必须是对象。")
    return data


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _default_output_file(input_file: Path, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    return output_dir / f"{input_file.stem}{BUSINESS_VIEW_SUFFIX}"


def _build_config(args: argparse.Namespace) -> BusinessViewConfig:
    return BusinessViewConfig(
        max_key_dna=args.max_key_dna,
        max_secondary_styles=args.max_secondary_styles,
        max_style_evidence=args.max_style_evidence,
        max_uncertain_fields=args.max_uncertain,
        max_novel_dna=args.max_novel,
        min_dna_confidence=args.min_dna_confidence,
        high_confidence_threshold=args.high_threshold,
        medium_confidence_threshold=args.medium_threshold,
        include_source_trace=args.include_source_trace,
        include_contextual_modules=args.include_contextual_modules,
    )


def _process_file(input_file: Path, output_file: Path, config: BusinessViewConfig) -> None:
    full_result = _load_json(input_file)
    business_view = extract_business_view(full_result, config)
    _write_json(output_file, business_view)


def _iter_json_files(input_dir: Path, recursive: bool) -> Iterable[Path]:
    iterator = input_dir.rglob("*.json") if recursive else input_dir.glob("*.json")
    for path in iterator:
        if path.name.endswith(".business.json") or path.name.endswith(BUSINESS_VIEW_SUFFIX):
            continue
        if path.is_file():
            yield path


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将完整设计 DNA JSON 转换为适合设计业务人员展示的精简 JSON。"
    )
    parser.add_argument("input", type=Path, help="输入 JSON 文件或包含 JSON 的目录")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=f"输出文件或输出目录；默认写入 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--recursive", action="store_true", help="输入为目录时递归处理子目录")
    parser.add_argument("--max-key-dna", type=int, default=15, help="核心 DNA 最大数量，默认 15")
    parser.add_argument("--max-secondary-styles", type=int, default=2, help="次风格最大数量，默认 2")
    parser.add_argument("--max-style-evidence", type=int, default=3, help="风格证据最大数量，默认 3")
    parser.add_argument("--max-uncertain", type=int, default=3, help="不确定字段最大数量，默认 3")
    parser.add_argument("--max-novel", type=int, default=3, help="新 DNA 最大数量，默认 3")
    parser.add_argument("--min-dna-confidence", type=float, default=0.55, help="进入核心 DNA 的最低置信度，默认 0.55")
    parser.add_argument("--high-threshold", type=float, default=0.80, help="高置信度阈值，默认 0.80")
    parser.add_argument("--medium-threshold", type=float, default=0.60, help="中置信度阈值，默认 0.60")
    parser.add_argument(
        "--include-source-trace",
        action="store_true",
        help="额外输出 field_id、source_path、evidence_refs 等后台追踪信息",
    )
    parser.add_argument(
        "--include-contextual-modules",
        action="store_true",
        help="允许展示 M12/M14/M15 及依赖参考集的品牌/趋势字段；单图业务页默认不建议开启",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    config = _build_config(args)
    input_path: Path = args.input

    if not input_path.exists():
        print(f"错误：输入路径不存在：{input_path}", file=sys.stderr)
        return 2

    try:
        if input_path.is_file():
            output_file = args.output or _default_output_file(input_path)
            if output_file.exists() and output_file.is_dir():
                output_file = output_file / _default_output_file(input_path).name
            _process_file(input_path, output_file, config)
            print(f"已生成：{output_file}")
            return 0

        output_dir = args.output or DEFAULT_OUTPUT_DIR
        if output_dir.exists() and output_dir.is_file():
            raise BusinessViewError("输入为目录时，--output 必须是目录路径。")

        files = list(_iter_json_files(input_path, args.recursive))
        if not files:
            raise BusinessViewError(f"目录中未找到可处理的 JSON：{input_path}")

        success = 0
        failures: List[str] = []
        for source_file in files:
            relative = source_file.relative_to(input_path)
            target_file = output_dir / relative.parent / f"{source_file.stem}{BUSINESS_VIEW_SUFFIX}"
            try:
                _process_file(source_file, target_file, config)
                success += 1
            except Exception as exc:  # 批量模式继续处理其他文件
                failures.append(f"{source_file}: {exc}")

        print(f"处理完成：成功 {success} 个，失败 {len(failures)} 个；输出目录：{output_dir}")
        for failure in failures:
            print(f"失败：{failure}", file=sys.stderr)
        return 1 if failures else 0

    except BusinessViewError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"错误：文件操作失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
