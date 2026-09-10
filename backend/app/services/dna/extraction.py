"""执行 DeepAgent 多模态推理，并由应用层统一校验与落盘。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.design_dna_extractor import (
    AGENT_PROMPT_VERSION,
    BOUND_SKILL_NAME,
    PRELOADED_CONTEXT_VERSION,
    create_design_dna_agent,
    create_style_semantic_review_agent,
    preloaded_skill_context_size,
)
from app.schemas.dna import ExtractionStage, ProgressEventLevel
from app.services.dna.storage import (
    save_business_view_model,
    save_failure_trace,
    save_result_image,
    save_result_trace,
)
from app.services.llm.telemetry import ModelCallTelemetry


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SAVE_RESULT_SCRIPT = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-multitag-extractor"
    / "scripts"
    / "save_result.py"
)
COMPILE_MODEL_OUTPUT_SCRIPT = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-multitag-extractor"
    / "scripts"
    / "compile_model_output.py"
)
STYLE_EVIDENCE_RULES_PATH = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-multitag-extractor"
    / "references"
    / "style-evidence-rules.json"
)
STYLE_KNOWLEDGE_BASE_PATH = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-multitag-extractor"
    / "references"
    / "design-dna-knowledge-base.zh-CN.md"
)
BUSINESS_VIEW_SCRIPT = PROJECT_ROOT / "extract_design_dna_business_view.py"
MAX_PATCH_REPAIR_ATTEMPTS = 1
MAX_FULL_FALLBACK_ATTEMPTS = 1
MAX_AGENT_NETWORK_RETRIES = 1
_DETERMINISTIC_ERROR_MARKERS = (
    "quality_summary.mean_confidence",
    "quality_summary.style_confidence",
    "quality_summary.low_confidence_field_count",
    "stable order",
    "ranks must be consecutive",
    "single confirmed tag requires dominance=1",
    "dominance values must sum",
    "label_en=",
    "label_zh=",
    "aliases must match style registry",
    "tag_kind=",
    "facet_ids must match style registry",
    "candidate_ranking value differs",
    "candidate_status=confirmed IDs must exactly equal",
    "source_path=",
    "field_name does not match field registry",
    "value_type=",
    "evidence_mode=",
    "must match design_elements",
    "relation must match tag-relations",
    "scope must match tag-relations",
    "style_id_a/style_id_b must use canonical lexical order",
    "requires active profile",
    "requires view in",
    "ordinal value must be one of",
    "but no matching uncertain_fields record",
    "is not allowed by this style's auxiliary_field_ids",
    "is not allowed by this style's decisive_field_ids",
    "has no observed/computed value in this result",
    "regions lack matching referenced evidence",
)

_ISSUE_CODE_PATTERNS = (
    ("REGION_NOT_DECLARED", "outside target_object.visible_regions"),
    ("FIELD_PROFILE_NOT_APPLICABLE", "requires active profile"),
    ("FIELD_VIEW_NOT_APPLICABLE", "requires view in"),
    ("FIELD_ORDINAL_OUT_OF_DOMAIN", "ordinal value must be one of"),
    ("FIELD_UNCERTAINTY_MISSING", "no matching uncertain_fields record"),
    ("STYLE_AUXILIARY_FIELD_NOT_ALLOWED", "auxiliary_field_ids"),
    ("STYLE_DECISIVE_FIELD_NOT_ALLOWED", "decisive_field_ids"),
    ("STYLE_FIELD_UNAVAILABLE", "has no observed/computed value"),
    ("STYLE_REGION_EVIDENCE_MISSING", "regions lack matching referenced evidence"),
    ("FIELD_VALUE_OUT_OF_DOMAIN", "outside the controlled domain"),
    ("FIELD_ENUM_OUT_OF_DOMAIN", "outside the enum domain"),
    ("MODEL_SCHEMA_INVALID", "model_schema"),
    ("FINAL_SCHEMA_INVALID", "schema "),
)


class DesignDnaExtractionError(RuntimeError):
    """单图 DNA 提取无法完成。"""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_id: str | None = None,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_id = diagnostic_id
        self.issues = issues or []


@dataclass(frozen=True, slots=True)
class ExtractionOutput:
    """校验并落盘后的两个结果文件。"""

    full_result_path: Path
    business_view_path: Path

    @property
    def result_id(self) -> str:
        return self.full_result_path.stem


ProgressCallback = Callable[
    [ExtractionStage, str, int, ProgressEventLevel],
    None,
]


def _emit_progress(
    callback: ProgressCallback | None,
    stage: ExtractionStage,
    message: str,
    progress: int,
    level: ProgressEventLevel = ProgressEventLevel.INFO,
) -> None:
    """过程展示属于旁路能力，回调异常不能中断提取主链路。"""

    if callback is None:
        return
    try:
        callback(stage, message, progress, level)
    except Exception:
        return


def _image_content_block(image_path: Path, content_type: str) -> dict[str, str]:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "base64": encoded,
        "mime_type": content_type,
    }


def _task_text(user_prompt: str) -> str:
    notes = user_prompt.strip() or "无额外业务备注。"
    return (
        f"请只使用 {BOUND_SKILL_NAME} Skill 分析随消息提供的单张图片。"
        "严格完成单一主物品锁定、品类适用性、可观察设计 DNA、0～3 个同层风格标签的"
        "独立硬规则判定、标签两两关系仲裁、证据、不确定字段和新 DNA 检查。"
        "先确定视角与 active_profiles，并调用字段准入工具；只提取工具允许且图片实际可观察、"
        "风格判定需要或用户明确关注的字段，不要穷举全部语义字段。"
        "最终只返回符合精简模型观察 Schema 的 JSON；字段和风格静态元数据、模块清单、"
        "统计值、排序、候选镜像、证据闭环与组合预设均由宿主编译，不要重复输出。\n\n"
        "confirmed 风格省略规则计数以及 core/auxiliary 命中数组；宿主会根据规范字段值"
        "自动挂接，歧义项另做小范围语义复核。\n\n"
        f"用户业务备注：\n{notes}"
    )


@lru_cache(maxsize=1)
def _style_review_policy() -> dict[str, Any]:
    data = json.loads(STYLE_EVIDENCE_RULES_PATH.read_text(encoding="utf-8"))
    policy = data.get("review_policy")
    return policy if isinstance(policy, dict) else {}


@lru_cache(maxsize=1)
def _style_knowledge_sections() -> dict[str, str]:
    """按稳定 style_id 切分知识库，只向复核模型提供命中的少量段落。"""

    knowledge_base = STYLE_KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    matches = list(
        re.finditer(
            r"^### ([A-Za-z][A-Za-z0-9]*) — .*?(?=^### |\Z)",
            knowledge_base,
            re.MULTILINE | re.DOTALL,
        )
    )
    return {
        match.group(1): match.group(0).strip()
        for match in matches
    }


def _style_semantic_review_messages(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造不含图片和完整注册表的窄范围复核消息。"""

    policy = _style_review_policy()
    max_styles = policy.get("max_styles_per_review", 3)
    if not isinstance(max_styles, int) or max_styles < 1:
        max_styles = 3
    sections = _style_knowledge_sections()
    review_items = []
    for request in requests[:max_styles]:
        if not isinstance(request, dict):
            continue
        style_id = str(request.get("style_id") or "")
        review_items.append(
            {
                "style_id": style_id,
                "knowledge_rule": sections.get(style_id, ""),
                "missing_roles": request.get("missing_roles", []),
                "current_core_field_ids": request.get(
                    "current_core_field_ids", []
                ),
                "current_auxiliary_field_ids": request.get(
                    "current_auxiliary_field_ids", []
                ),
                "candidate_fields_by_role": request.get("roles", {}),
                "current_downgrade_reasons": request.get(
                    "downgrade_reasons", []
                ),
            }
        )
    payload = {
        "task": "只复核候选字段的当前值是否支持指定风格证据角色",
        "minimum_acceptance_confidence": policy.get(
            "minimum_review_confidence", 0.75
        ),
        "styles": review_items,
    }
    return [
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        }
    ]


def _apply_style_semantic_review(
    observation: dict[str, Any],
    requests: list[dict[str, Any]],
    review_result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """仅把高置信正向复核挂回模型观察；否定结论不会删除原始 DNA。"""

    result = deepcopy(observation)
    policy = _style_review_policy()
    threshold = policy.get("minimum_review_confidence", 0.75)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        threshold = 0.75
    allowed: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for request in requests:
        if not isinstance(request, dict):
            continue
        style_id = str(request.get("style_id") or "")
        roles = request.get("roles")
        if not isinstance(roles, dict):
            continue
        for role, candidates in roles.items():
            if role not in {"core", "auxiliary"} or not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                field_id = str(candidate.get("field_id") or "")
                allowed.setdefault((style_id, role), {}).setdefault(
                    field_id, candidate
                )

    decisions: list[dict[str, Any]] = []
    accepted: dict[
        tuple[str, str], list[tuple[list[str], list[dict[str, Any]]]]
    ] = {}
    raw_decisions = review_result.get("decisions")
    if not isinstance(raw_decisions, list):
        raw_decisions = []
    seen: set[tuple[str, str]] = set()
    for item in raw_decisions:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("style_id") or ""),
            str(item.get("role") or ""),
        )
        role_candidates = allowed.get(key)
        raw_field_ids = item.get("field_ids")
        if not isinstance(raw_field_ids, list):
            legacy_field_id = str(item.get("field_id") or "")
            raw_field_ids = [legacy_field_id] if legacy_field_id else []
        field_ids = _ordered_unique_text(raw_field_ids)
        if (
            role_candidates is None
            or key in seen
            or any(field_id not in role_candidates for field_id in field_ids)
        ):
            continue
        seen.add(key)
        confidence = item.get("confidence")
        supports = item.get("supports") is True
        role_requirement_satisfied = bool(
            key[1] != "core"
            or any(
                role_candidates[field_id].get("decision_use") == "hard"
                for field_id in field_ids
            )
        )
        accepted_decision = bool(
            supports
            and field_ids
            and role_requirement_satisfied
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) >= float(threshold)
        )
        normalized = {
            "style_id": key[0],
            "role": key[1],
            "field_ids": field_ids,
            "supports": supports,
            "confidence": confidence,
            "accepted": accepted_decision,
            "reason": str(item.get("reason") or "").strip(),
        }
        decisions.append(normalized)
        if accepted_decision:
            accepted.setdefault(key, []).append(
                (
                    field_ids,
                    [role_candidates[field_id] for field_id in field_ids],
                )
            )

    styles = result.get("style_observations")
    confirmed_tags = styles.get("confirmed_tags") if isinstance(styles, dict) else None
    accepted_count = 0
    if isinstance(confirmed_tags, list):
        for tag in confirmed_tags:
            if not isinstance(tag, dict):
                continue
            style_id = str(tag.get("style_id") or "")
            for role, target_key in (
                ("core", "core_feature_hits"),
                ("auxiliary", "auxiliary_feature_hits"),
            ):
                additions = accepted.get((style_id, role), [])
                if not additions:
                    continue
                hits = tag.get(target_key)
                if not isinstance(hits, list):
                    hits = []
                for field_ids, candidates in additions:
                    descriptions = _ordered_unique_text(
                        [
                            candidate.get("raw_visual_description")
                            or candidate.get("field_name")
                            or "语义复核确认该字段值支持当前风格"
                            for candidate in candidates
                        ]
                    )
                    hit = f"{'、'.join(field_ids)}：{'；'.join(descriptions)}"
                    if hit not in hits:
                        hits.append(hit)
                        accepted_count += len(field_ids)
                tag[target_key] = hits
    return result, decisions, accepted_count


def _annotate_style_review_outcome(
    compiled: dict[str, Any], decisions: list[dict[str, Any]]
) -> None:
    """把未采纳的复核理由写入 provisional 候选，便于前端解释未分类。"""

    candidates = compiled.get("style_result", {}).get("candidate_ranking")
    if not isinstance(candidates, list):
        return
    decisions_by_style: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        if isinstance(decision, dict) and not decision.get("accepted"):
            decisions_by_style.setdefault(
                str(decision.get("style_id") or ""), []
            ).append(decision)
    for candidate in candidates:
        if (
            not isinstance(candidate, dict)
            or candidate.get("candidate_status") == "confirmed"
        ):
            continue
        style_decisions = decisions_by_style.get(str(candidate.get("style_id") or ""))
        if not style_decisions:
            continue
        conflicts = list(candidate.get("main_conflicts") or [])
        for decision in style_decisions:
            reason = str(decision.get("reason") or "语义支持不足").strip()
            field_ids = "、".join(decision.get("field_ids") or []) or "候选字段"
            conflicts.append(
                "语义复核未采纳 "
                f"{field_ids} 作为 {decision.get('role')} 证据：{reason}"
            )
        candidate["main_conflicts"] = _ordered_unique_text(conflicts)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _parse_json_response(result: dict[str, Any]) -> dict[str, Any]:
    messages = result.get("messages") or []
    if not messages:
        raise DesignDnaExtractionError("DeepAgent 没有返回消息")
    text = _message_text(messages[-1]).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
        if text.startswith("json"):
            text = text[4:].lstrip()

    object_start = text.find("{")
    if object_start < 0:
        raise DesignDnaExtractionError("模型输出中没有 JSON 对象")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[object_start:])
    except json.JSONDecodeError as exc:
        raise DesignDnaExtractionError(
            f"模型 JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise DesignDnaExtractionError("模型输出的 JSON 根节点不是对象")
    return data


def _compile_model_result(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用 Skill 自带编译器，并返回完整结果骨架与确定性改动报告。"""

    process = subprocess.run(
        [sys.executable, str(COMPILE_MODEL_OUTPUT_SCRIPT), "-", "--envelope"],
        input=json.dumps(data, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout).strip()
        raise DesignDnaExtractionError(details or "模型观察结果编译失败")
    try:
        envelope = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise DesignDnaExtractionError("模型观察结果编译器没有返回有效 JSON") from exc
    result = envelope.get("result") if isinstance(envelope, dict) else None
    report = envelope.get("report") if isinstance(envelope, dict) else None
    if not isinstance(result, dict) or not isinstance(report, dict):
        raise DesignDnaExtractionError("模型观察结果编译器返回结构不完整")
    return result, report


def _validation_failure_kind(error: DesignDnaExtractionError) -> str:
    """区分宿主可确定处理的错误与必须回到视觉/语义判断的错误。"""

    lines = [
        line.strip().removeprefix("-").strip()
        for line in str(error).splitlines()
        if line.strip().startswith("-")
    ]
    if lines and all(
        any(marker in line for marker in _DETERMINISTIC_ERROR_MARKERS)
        for line in lines
    ):
        return "deterministic"
    return "semantic"


def _validation_issues(
    error: DesignDnaExtractionError,
    compilation_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把最终校验文本转换为稳定问题对象，并关联模型观察 JSON Pointer。"""

    lines = [
        line.strip().removeprefix("-").strip()
        for line in str(error).splitlines()
        if line.strip().startswith("-")
    ]
    if not lines:
        lines = [str(error).strip()]
    source_map = (
        compilation_report.get("source_map", {})
        if isinstance(compilation_report, dict)
        else {}
    )
    issues: list[dict[str, Any]] = []
    for message in lines:
        code = next(
            (
                candidate_code
                for candidate_code, marker in _ISSUE_CODE_PATTERNS
                if marker in message
            ),
            "SEMANTIC_VALIDATION_FAILED",
        )
        if ":" in message:
            final_path = message.split(":", 1)[0].strip()
        else:
            # 部分语义错误在路径后直接接 “=”；只截取路径，避免前端重复整句。
            path_match = re.match(
                r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?"
                r"(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)*",
                message,
            )
            final_path = path_match.group(0) if path_match else message
        if final_path.startswith("schema "):
            final_path = final_path.removeprefix("schema ").strip()
        mapping: dict[str, Any] = {}
        for path_key in sorted(source_map, key=len, reverse=True):
            if final_path == path_key or final_path.startswith(f"{path_key}."):
                candidate = source_map.get(path_key)
                if isinstance(candidate, dict):
                    mapping = candidate
                break
        compiler_owned = any(
            marker in message for marker in _DETERMINISTIC_ERROR_MARKERS
        )
        issue = {
            "code": code,
            "repair_owner": "compiler" if compiler_owned else "model",
            "message": message,
            "final_path": final_path,
            "source_pointer": mapping.get("source_pointer"),
        }
        for key in ("field_id", "style_id", "evidence_id", "region"):
            if mapping.get(key) is not None:
                issue[key] = mapping[key]
        issues.append(issue)
    return issues


def _contextualize_validation_error(
    error: DesignDnaExtractionError,
    compiled: dict[str, Any] | None,
    model_data: dict[str, Any] | None,
    compilation_report: dict[str, Any] | None = None,
) -> DesignDnaExtractionError:
    """为兼容文本错误追加结构化源路径；旧编译结果仍使用字段匹配兜底。"""

    issues = _validation_issues(error, compilation_report)
    mapped_issues = [issue for issue in issues if issue.get("source_pointer")]
    if mapped_issues:
        mappings = [
            f"{issue['final_path']} -> {issue['source_pointer']}"
            for issue in mapped_issues
        ]
        return DesignDnaExtractionError(
            f"{error}\n模型观察路径映射：\n"
            + "\n".join(f"- {item}" for item in mappings)
        )

    if compiled is None or model_data is None:
        return error
    design_observations = model_data.get("design_observations")
    uncertainties = model_data.get("uncertainties")
    style_observations = model_data.get("style_observations")
    if not isinstance(design_observations, list):
        design_observations = []
    if not isinstance(uncertainties, list):
        uncertainties = []
    if not isinstance(style_observations, dict):
        style_observations = {}

    error_text = str(error)
    mappings: list[str] = []
    modules = compiled.get("design_elements", {}).get("extended_dna_modules", [])
    for module_index, module in enumerate(modules if isinstance(modules, list) else []):
        if not isinstance(module, dict):
            continue
        for element_index, element in enumerate(module.get("elements", [])):
            if not isinstance(element, dict):
                continue
            field_id = element.get("field_id")
            region = element.get("region")
            candidates = [
                index
                for index, observation in enumerate(design_observations)
                if isinstance(observation, dict)
                and observation.get("field_id") == field_id
                and observation.get("region") == region
            ]
            if not candidates:
                candidates = [
                    index
                    for index, observation in enumerate(design_observations)
                    if isinstance(observation, dict)
                    and observation.get("field_id") == field_id
                ]
            if len(candidates) == 1:
                compiled_path = f"design_element[{sum(len(candidate.get('elements', [])) for candidate in modules[:module_index] if isinstance(candidate, dict)) + element_index}]"
                if compiled_path not in error_text:
                    continue
                mappings.append(
                    f"{compiled_path} -> "
                    f"/design_observations/{candidates[0]} ({field_id}@{region})"
                )

    for index, item in enumerate(uncertainties):
        if isinstance(item, dict) and f"uncertain_fields[{index}]" in error_text:
            mappings.append(
                f"uncertain_fields.{index} -> /uncertainties/{index} "
                f"({item.get('field_id')}@{item.get('region')})"
            )

    confirmed_tags = style_observations.get("confirmed_tags")
    if isinstance(confirmed_tags, list):
        for index, item in enumerate(confirmed_tags):
            if isinstance(item, dict) and f"style_result.style_tags[{index}]" in error_text:
                mappings.append(
                    f"style_result.style_tags.{index} -> "
                    f"/style_observations/confirmed_tags/{index} ({item.get('style_id')})"
                )
    pairwise = style_observations.get("pairwise_reasoning")
    if isinstance(pairwise, list):
        for index, item in enumerate(pairwise):
            if (
                isinstance(item, dict)
                and f"style_result.pairwise_arbitrations[{index}]" in error_text
            ):
                mappings.append(
                    f"style_result.pairwise_arbitrations.{index} -> "
                    f"/style_observations/pairwise_reasoning/{index}"
                )

    if not mappings:
        return error
    return DesignDnaExtractionError(
        f"{error}\n模型观察路径映射：\n" + "\n".join(f"- {item}" for item in mappings)
    )


def _decode_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _apply_json_patch(data: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """应用受限的 add/replace/remove JSON Pointer 补丁，避免再次生成完整结果。"""

    updates = patch.get("updates")
    if not isinstance(updates, list) or not 1 <= len(updates) <= 64:
        raise DesignDnaExtractionError("修复补丁必须包含 1～64 个 updates")
    result: Any = deepcopy(data)
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            raise DesignDnaExtractionError(f"修复补丁 updates[{index}] 不是对象")
        operation = update.get("op", "replace")
        path = update.get("path")
        if operation not in {"add", "replace", "remove"}:
            raise DesignDnaExtractionError(f"修复补丁 updates[{index}].op 不受支持")
        if not isinstance(path, str) or not path.startswith("/") or path == "/":
            raise DesignDnaExtractionError(f"修复补丁 updates[{index}].path 不合法")
        tokens = [_decode_json_pointer_token(item) for item in path[1:].split("/")]
        parent: Any = result
        for token in tokens[:-1]:
            if isinstance(parent, list):
                try:
                    parent = parent[int(token)]
                except (IndexError, TypeError, ValueError) as exc:
                    raise DesignDnaExtractionError(
                        f"修复补丁路径不存在：{path}"
                    ) from exc
            elif isinstance(parent, dict) and token in parent:
                parent = parent[token]
            else:
                raise DesignDnaExtractionError(f"修复补丁路径不存在：{path}")
        final_token = tokens[-1]
        if isinstance(parent, list):
            if operation == "add" and final_token == "-":
                parent.append(deepcopy(update.get("value")))
                continue
            try:
                item_index = int(final_token)
                if operation == "remove":
                    parent.pop(item_index)
                elif operation == "add":
                    parent.insert(item_index, deepcopy(update.get("value")))
                else:
                    parent[item_index] = deepcopy(update.get("value"))
            except (IndexError, TypeError, ValueError) as exc:
                raise DesignDnaExtractionError(f"修复补丁路径不存在：{path}") from exc
        elif isinstance(parent, dict):
            if operation == "remove":
                if final_token not in parent:
                    raise DesignDnaExtractionError(f"修复补丁路径不存在：{path}")
                del parent[final_token]
            else:
                if operation == "replace" and final_token not in parent:
                    raise DesignDnaExtractionError(f"修复补丁路径不存在：{path}")
                parent[final_token] = deepcopy(update.get("value"))
        else:
            raise DesignDnaExtractionError(f"修复补丁父节点不是容器：{path}")
    if not isinstance(result, dict):  # pragma: no cover - 根节点不能由受限路径替换。
        raise DesignDnaExtractionError("修复补丁不能替换 JSON 根节点")
    return result


def _safely_degrade_invalid_observations(
    data: dict[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """删除无可判定值的字段或降级无证据风格，不补造任何视觉事实。"""

    result = deepcopy(data)
    design_indices: set[int] = set()
    uncertainty_indices: set[int] = set()
    style_issue_messages: dict[int, list[str]] = {}
    for issue in issues:
        pointer = issue.get("source_pointer")
        if not isinstance(pointer, str):
            continue
        match = re.fullmatch(r"/design_observations/(\d+)", pointer)
        if match:
            design_indices.add(int(match.group(1)))
            continue
        match = re.fullmatch(r"/uncertainties/(\d+)", pointer)
        if match:
            uncertainty_indices.add(int(match.group(1)))
            continue
        match = re.fullmatch(
            r"/style_observations/confirmed_tags/(\d+)", pointer
        )
        if match:
            style_issue_messages.setdefault(int(match.group(1)), []).append(
                str(issue.get("message") or issue.get("code") or "风格证据未闭合")
            )

    design_observations = result.get("design_observations")
    if isinstance(design_observations, list):
        for index in sorted(design_indices, reverse=True):
            if 0 <= index < len(design_observations):
                design_observations.pop(index)
    uncertainties = result.get("uncertainties")
    if isinstance(uncertainties, list):
        for index in sorted(uncertainty_indices, reverse=True):
            if 0 <= index < len(uncertainties):
                uncertainties.pop(index)

    style_observations = result.get("style_observations")
    if isinstance(style_observations, dict):
        confirmed = style_observations.get("confirmed_tags")
        other_candidates = style_observations.get("other_candidates")
        if not isinstance(confirmed, list):
            confirmed = []
        if not isinstance(other_candidates, list):
            other_candidates = []
        demoted: list[dict[str, Any]] = []
        for index in sorted(style_issue_messages, reverse=True):
            if not 0 <= index < len(confirmed):
                continue
            tag = confirmed.pop(index)
            if not isinstance(tag, dict):
                continue
            demoted.append(
                {
                    "style_id": tag.get("style_id"),
                    "match_score": tag.get("match_score", 0),
                    "confidence": tag.get("confidence", 0),
                    "regions": deepcopy(tag.get("regions", [])),
                    "candidate_status": "provisional",
                    "hard_rule_passed": False,
                    "main_support": _ordered_unique_text(
                        [
                            *(tag.get("core_feature_hits") or []),
                            *(tag.get("auxiliary_feature_hits") or []),
                        ]
                    ),
                    "main_conflicts": _ordered_unique_text(
                        style_issue_messages[index]
                    ),
                }
            )
        demoted_ids = {
            item.get("style_id") for item in demoted if item.get("style_id")
        }
        other_candidates = [
            item
            for item in other_candidates
            if not isinstance(item, dict) or item.get("style_id") not in demoted_ids
        ]
        other_candidates.extend(reversed(demoted))
        confirmed_ids = {
            item.get("style_id") for item in confirmed if isinstance(item, dict)
        }
        pairwise = style_observations.get("pairwise_reasoning")
        if isinstance(pairwise, list):
            style_observations["pairwise_reasoning"] = [
                item
                for item in pairwise
                if isinstance(item, dict)
                and item.get("style_id_a") in confirmed_ids
                and item.get("style_id_b") in confirmed_ids
            ]
        style_observations["confirmed_tags"] = confirmed
        style_observations["other_candidates"] = other_candidates
        style_observations["classification_status"] = (
            "confirmed" if confirmed else "unclassified"
        )
        if not confirmed:
            style_observations["composition_summary"] = (
                "候选风格证据未通过确定性闭环检查，已保守降级为未分类。"
            )

    action_count = (
        len(design_indices) + len(uncertainty_indices) + len(style_issue_messages)
    )
    return result, action_count


def _ordered_unique_text(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _merge_compilation_metrics(
    metrics: dict[str, Any], report: dict[str, Any]
) -> None:
    metrics["deterministic_compilation_count"] += 1
    metrics["deterministic_correction_count"] += int(
        report.get("deterministic_correction_count") or 0
    )
    metrics["pruned_style_hit_count"] += len(
        report.get("pruned_style_hits") or []
    )
    metrics["style_downgrade_count"] += len(
        report.get("style_downgrades") or []
    )
    metrics["auto_linked_style_hit_count"] += len(
        report.get("auto_linked_style_hits") or []
    )
    correction_areas = metrics["deterministic_corrections_by_area"]
    samples = metrics["deterministic_changed_path_samples"]
    for path in report.get("changed_paths", []):
        if not isinstance(path, str):
            continue
        area = path.lstrip("/").split("/", 1)[0] or "root"
        correction_areas[area] = correction_areas.get(area, 0) + 1
        if path not in samples and len(samples) < 24:
            samples.append(path)


def _record_validation_failure(
    metrics: dict[str, Any],
    kind: str,
    error: DesignDnaExtractionError,
    issues: list[dict[str, Any]] | None = None,
) -> None:
    metrics["validation_failure_kinds"].append(kind)
    summaries = metrics["validation_failure_summaries"]
    error_lines = [
        line.strip().removeprefix("-").strip()
        for line in str(error).splitlines()
        if line.strip().startswith("-")
    ]
    summary = " | ".join(error_lines[:8])[:2000] or str(error)[:2000]
    summaries.append(summary)
    issue_history = metrics.setdefault("validation_issues", [])
    issue_history.append(deepcopy(issues or _validation_issues(error)))


def _invoke_agent(
    agent: Any,
    messages: list[Any],
    telemetry: ModelCallTelemetry,
    metrics: dict[str, Any],
    *,
    invocation_metric: str = "agent_invocation_count",
    recursion_limit: int = 120,
    on_retry: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    for network_attempt in range(MAX_AGENT_NETWORK_RETRIES + 1):
        metrics[invocation_metric] = metrics.get(invocation_metric, 0) + 1
        try:
            result = agent.invoke(
                {"messages": messages},
                config={
                    "recursion_limit": recursion_limit,
                    "callbacks": [telemetry],
                },
            )
            if not isinstance(result, dict):
                raise DesignDnaExtractionError("DeepAgent 返回结构不合法")
            return result
        except Exception as exc:
            if (
                isinstance(exc, DesignDnaExtractionError)
                or network_attempt >= MAX_AGENT_NETWORK_RETRIES
                or not _is_transient_model_error(exc)
            ):
                raise
            metrics["application_network_retry_count"] += 1
            if on_retry is not None:
                try:
                    on_retry(network_attempt + 2)
                except Exception:
                    pass
    raise DesignDnaExtractionError("DeepAgent 网络重试后仍未返回结果")  # pragma: no cover


def _is_transient_model_error(error: Exception) -> bool:
    """识别 SDK 未自动覆盖的断流、超时与网关瞬时错误。"""

    module_name = type(error).__module__.lower()
    type_name = type(error).__name__.lower()
    message = str(error).lower()
    provider_error = module_name.startswith(
        (
            "openai",
            "anthropic",
            "langchain_openai",
            "langchain_anthropic",
            "httpx",
            "httpcore",
        )
    )
    transient_type = any(
        marker in type_name
        for marker in ("apierror", "connection", "timeout", "internalserver")
    )
    transient_message = any(
        marker in message
        for marker in (
            "stream disconnected",
            "stream closed",
            "timed out",
            "timeout",
            "connection reset",
            "connection closed",
            "502",
            "503",
            "504",
            "524",
        )
    )
    return provider_error and (transient_type or transient_message)


def _save_validated_result(image_path: Path, data: dict[str, Any]) -> Path:
    process = subprocess.run(
        [
            sys.executable,
            str(SAVE_RESULT_SCRIPT),
            "--compiled",
            "--image",
            str(image_path),
            "-",
        ],
        input=json.dumps(data, ensure_ascii=False),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout).strip()
        raise DesignDnaExtractionError(details or "设计 DNA 结果未通过校验")
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise DesignDnaExtractionError("结果保存脚本没有返回文件路径")
    result_path = Path(lines[-1]).resolve()
    if not result_path.is_file():
        raise DesignDnaExtractionError("完整结果保存后未找到文件")
    return result_path


def _create_business_view(full_result_path: Path) -> Path:
    process = subprocess.run(
        [sys.executable, str(BUSINESS_VIEW_SCRIPT), str(full_result_path)],
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout).strip()
        raise DesignDnaExtractionError(details or "业务视图生成失败")
    business_path = full_result_path.with_name(
        f"{full_result_path.stem}_business_view.json"
    )
    if not business_path.is_file():
        raise DesignDnaExtractionError("业务视图生成后未找到文件")
    return business_path


def run_design_dna_extraction(
    image_path: Path,
    content_type: str,
    model_id: str,
    user_prompt: str,
    progress_callback: ProgressCallback | None = None,
) -> ExtractionOutput:
    """运行单图 Skill，并优先用确定性编译和局部补丁完成修复。"""

    started_at = datetime.now(UTC)
    _emit_progress(
        progress_callback,
        ExtractionStage.PREPARING,
        "正在加载模型配置和多标签 DNA Skill",
        6,
    )
    agent = create_design_dna_agent(model_id)
    messages: list[Any] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _task_text(user_prompt)},
                _image_content_block(image_path, content_type),
            ],
        }
    ]
    model_phase: dict[str, Any] = {
        "stage": ExtractionStage.MODEL_ANALYSIS,
        "label": "主模型分析",
        "progress": 14,
    }

    def report_model_event(event: str, request_count: int) -> None:
        stage = model_phase["stage"]
        label = model_phase["label"]
        progress = model_phase["progress"]
        if event == "request_started":
            message = f"{label}：第 {request_count} 次模型请求已发送，等待响应"
            level = ProgressEventLevel.INFO
        elif event == "request_completed":
            message = f"{label}：第 {request_count} 次模型请求已返回，正在整理上下文"
            progress += 3
            level = ProgressEventLevel.INFO
        else:
            message = f"{label}：第 {request_count} 次模型请求返回异常"
            level = ProgressEventLevel.WARNING
        _emit_progress(progress_callback, stage, message, progress, level)

    def select_model_phase(
        stage: ExtractionStage,
        label: str,
        progress: int,
    ) -> None:
        model_phase.update(stage=stage, label=label, progress=progress)

    def report_retry(attempt: int) -> None:
        _emit_progress(
            progress_callback,
            model_phase["stage"],
            f"{model_phase['label']}连接异常，正在进行第 {attempt} 次尝试",
            model_phase["progress"],
            ProgressEventLevel.WARNING,
        )

    telemetry = ModelCallTelemetry(on_event=report_model_event)
    metrics: dict[str, Any] = {
        "agent_invocation_count": 0,
        "deterministic_compilation_count": 0,
        "deterministic_correction_count": 0,
        "pruned_style_hit_count": 0,
        "style_downgrade_count": 0,
        "auto_linked_style_hit_count": 0,
        "deterministic_corrections_by_area": {},
        "deterministic_changed_path_samples": [],
        "style_semantic_review_attempt_count": 0,
        "style_semantic_review_agent_invocation_count": 0,
        "style_semantic_review_accepted_count": 0,
        "style_semantic_review_rejected_count": 0,
        "style_semantic_review_recovered_style_count": 0,
        "style_semantic_review_error_count": 0,
        "style_semantic_review_decisions": [],
        "style_semantic_review_errors": [],
        "semantic_patch_attempt_count": 0,
        "safe_degradation_count": 0,
        "full_fallback_attempt_count": 0,
        "validation_failure_kinds": [],
        "validation_failure_summaries": [],
        "validation_issues": [],
        "application_network_retry_count": 0,
        # provider SDK 内部重试仍不可观测；流式断连由上面的应用层计数覆盖。
        "provider_internal_retry_count_observable": False,
        "preloaded_context_version": PRELOADED_CONTEXT_VERSION,
        "preloaded_context_chars": preloaded_skill_context_size(),
    }
    result: dict[str, Any] = {}
    model_data: dict[str, Any] | None = None
    last_error: DesignDnaExtractionError | None = None
    last_issues: list[dict[str, Any]] = []
    full_result_path: Path | None = None
    compiled_data: dict[str, Any] | None = None
    compilation_report: dict[str, Any] | None = None
    semantic_review_attempted = False

    def compile_and_save(candidate: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        nonlocal compiled_data, compilation_report
        nonlocal semantic_review_attempted
        compiled_data = None
        compilation_report = None
        _emit_progress(
            progress_callback,
            ExtractionStage.COMPILING,
            "正在进行字段归一化、统计计算与风格证据整理",
            64,
        )
        compiled, report = _compile_model_result(candidate)
        _merge_compilation_metrics(metrics, report)
        review_decisions: list[dict[str, Any]] = []
        review_requests = report.get("semantic_review_requests")
        if (
            isinstance(review_requests, list)
            and review_requests
            and not semantic_review_attempted
        ):
            semantic_review_attempted = True
            metrics["style_semantic_review_attempt_count"] += 1
            _emit_progress(
                progress_callback,
                ExtractionStage.SEMANTIC_REVIEW,
                f"发现 {len(review_requests)} 个风格证据歧义，正在进行小范围语义复核",
                74,
            )
            before_style_ids = {
                str(item.get("style_id") or "")
                for item in compiled.get("style_result", {}).get("style_tags", [])
                if isinstance(item, dict)
            }
            try:
                review_agent = create_style_semantic_review_agent(model_id)
                select_model_phase(
                    ExtractionStage.SEMANTIC_REVIEW,
                    "风格语义复核",
                    76,
                )
                review_response = _invoke_agent(
                    review_agent,
                    _style_semantic_review_messages(review_requests),
                    telemetry,
                    metrics,
                    invocation_metric="style_semantic_review_agent_invocation_count",
                    recursion_limit=24,
                    on_retry=report_retry,
                )
                review_data = _parse_json_response(review_response)
                reviewed_candidate, decisions, accepted_count = (
                    _apply_style_semantic_review(
                        candidate,
                        review_requests,
                        review_data,
                    )
                )
                metrics["style_semantic_review_decisions"].extend(decisions)
                review_decisions = decisions
                metrics["style_semantic_review_accepted_count"] += accepted_count
                metrics["style_semantic_review_rejected_count"] += sum(
                    1 for item in decisions if not item.get("accepted")
                )
                if accepted_count:
                    _emit_progress(
                        progress_callback,
                        ExtractionStage.COMPILING,
                        f"语义复核采纳 {accepted_count} 条证据，正在重新闭合风格规则",
                        80,
                    )
                    candidate.clear()
                    candidate.update(reviewed_candidate)
                    compiled, report = _compile_model_result(candidate)
                    _merge_compilation_metrics(metrics, report)
                    after_style_ids = {
                        str(item.get("style_id") or "")
                        for item in compiled.get("style_result", {}).get(
                            "style_tags", []
                        )
                        if isinstance(item, dict)
                    }
                    metrics["style_semantic_review_recovered_style_count"] += len(
                        after_style_ids - before_style_ids
                    )
                report["semantic_review"] = {
                    "status": "completed",
                    "accepted_link_count": accepted_count,
                    "decisions": deepcopy(decisions),
                }
            except Exception as review_error:
                # 复核失败不能放宽证据门槛；保留首次编译的保守降级结果继续落盘。
                metrics["style_semantic_review_error_count"] += 1
                metrics["style_semantic_review_errors"].append(
                    str(review_error)[:1000]
                )
                report["semantic_review"] = {
                    "status": "failed_conservative",
                    "error": str(review_error)[:1000],
                }
                _emit_progress(
                    progress_callback,
                    ExtractionStage.SEMANTIC_REVIEW,
                    "语义复核未完成，保持保守候选并继续最终校验",
                    80,
                    ProgressEventLevel.WARNING,
                )
                quality = compiled.get("quality_summary")
                if isinstance(quality, dict):
                    quality["warnings"] = _ordered_unique_text(
                        [
                            *(quality.get("warnings") or []),
                            "小范围风格语义复核未完成，候选保持保守降级。",
                        ]
                    )
        _annotate_style_review_outcome(compiled, review_decisions)
        compiled_data = compiled
        compilation_report = report
        _emit_progress(
            progress_callback,
            ExtractionStage.VALIDATING,
            "正在执行最终 Schema 与语义一致性校验",
            86,
        )
        return _save_validated_result(image_path, compiled), compiled

    def persist_failure(error: Exception) -> DesignDnaExtractionError:
        metrics.update(telemetry.snapshot())
        try:
            relative_image_path = str(image_path.resolve().relative_to(PROJECT_ROOT))
        except ValueError:
            relative_image_path = str(image_path.resolve())
        messages_result = result.get("messages") if isinstance(result, dict) else None
        raw_response = None
        if isinstance(messages_result, list) and messages_result:
            raw_response = _message_text(messages_result[-1])
        trace = {
            "status": "failed",
            "input_image": {
                "path": relative_image_path,
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            },
            "model_id": model_id,
            "user_prompt": user_prompt,
            "agent_prompt_version": AGENT_PROMPT_VERSION,
            "skill": BOUND_SKILL_NAME,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "error": str(error),
            "issues": deepcopy(last_issues),
            "raw_model_response": raw_response,
            "model_observation": deepcopy(model_data),
            "compiled_result": deepcopy(compiled_data),
            "compilation_report": deepcopy(compilation_report),
            "execution_metrics": deepcopy(metrics),
        }
        try:
            diagnostic_id, _path = save_failure_trace(trace)
        except (OSError, TypeError, ValueError):
            diagnostic_id = None
        message = str(error)
        if diagnostic_id:
            message = f"{message}\n诊断编号：{diagnostic_id}"
        return DesignDnaExtractionError(
            message,
            diagnostic_id=diagnostic_id,
            issues=deepcopy(last_issues),
        )

    _emit_progress(
        progress_callback,
        ExtractionStage.MODEL_ANALYSIS,
        "主提取 Agent 已启动，正在分析图片中的可观察设计特征",
        12,
    )
    select_model_phase(ExtractionStage.MODEL_ANALYSIS, "主模型分析", 14)
    try:
        result = _invoke_agent(
            agent,
            messages,
            telemetry,
            metrics,
            on_retry=report_retry,
        )
    except Exception as exc:
        raise persist_failure(exc) from exc

    try:
        _emit_progress(
            progress_callback,
            ExtractionStage.PARSING,
            "主模型响应完成，正在解析精简观察结果",
            56,
        )
        model_data = _parse_json_response(result)
        full_result_path, compiled_data = compile_and_save(model_data)
    except DesignDnaExtractionError as exc:
        last_issues = _validation_issues(exc, compilation_report)
        last_error = _contextualize_validation_error(
            exc,
            compiled_data,
            model_data,
            compilation_report,
        )
        failure_kind = (
            "structural" if model_data is None else _validation_failure_kind(exc)
        )
        _record_validation_failure(metrics, failure_kind, last_error, last_issues)
        compiler_issues = [
            issue for issue in last_issues if issue.get("repair_owner") == "compiler"
        ]
        if compiler_issues:
            host_error = DesignDnaExtractionError(
                "确定性编译后仍存在机械一致性错误，请检查宿主编译器：\n"
                f"{exc}"
            )
            raise persist_failure(host_error) from exc

    if full_result_path is None and model_data is not None:
        for _attempt in range(MAX_PATCH_REPAIR_ATTEMPTS):
            metrics["semantic_patch_attempt_count"] += 1
            _emit_progress(
                progress_callback,
                ExtractionStage.REPAIRING,
                "发现需要视觉或语义判断的问题，正在请求局部修复",
                87,
                ProgressEventLevel.WARNING,
            )
            semantic_issues = [
                issue
                for issue in last_issues
                if issue.get("repair_owner") == "model"
            ]
            patch_messages = [
                *result.get("messages", messages),
                {
                    "role": "user",
                    "content": (
                        "宿主已完成统计、排序、静态元数据和可推导证据的确定性整理，"
                        "但仍有必须由视觉或语义判断修复的错误。只返回局部 JSON 补丁，"
                        "不要重复完整结果。格式为 "
                        '{"updates":[{"op":"add|replace|remove",'
                        '"path":"/JSON/Pointer","value":...}]}。'
                        "remove 操作省略 value；数组可用数字下标或 add 到 /-。"
                        "补丁 path 必须使用错误对象中的 source_pointer，它对应模型精简观察；"
                        "禁止使用 final_path 或 design_elements 等编译后路径。"
                        "无法安全补证时，可 remove 对应的低置信 design_observations 记录。"
                        "错误如下：\n"
                        f"{json.dumps(semantic_issues, ensure_ascii=False)[:12000]}"
                    ),
                },
            ]
            select_model_phase(ExtractionStage.REPAIRING, "局部语义修复", 87)
            patch_result = _invoke_agent(
                agent,
                patch_messages,
                telemetry,
                metrics,
                on_retry=report_retry,
            )
            try:
                repair_data = _parse_json_response(patch_result)
                if isinstance(repair_data.get("updates"), list):
                    repaired_model_data = _apply_json_patch(model_data, repair_data)
                else:
                    # 某些模型可能忽略补丁要求；若返回了完整契约，直接作为兜底候选。
                    repaired_model_data = repair_data
            except DesignDnaExtractionError as repair_error:
                # 修复响应自身无效时保留原始校验问题，供后续保守整理准确定位。
                repair_issues = _validation_issues(
                    repair_error,
                    compilation_report,
                )
                _record_validation_failure(
                    metrics,
                    "semantic",
                    repair_error,
                    repair_issues,
                )
                _emit_progress(
                    progress_callback,
                    ExtractionStage.REPAIRING,
                    "局部补丁无法应用，将保留原问题进行保守整理",
                    88,
                    ProgressEventLevel.WARNING,
                )
                result = patch_result
                continue
            model_data = repaired_model_data
            try:
                full_result_path, compiled_data = compile_and_save(model_data)
                result = patch_result
                break
            except DesignDnaExtractionError as exc:
                last_issues = _validation_issues(exc, compilation_report)
                last_error = _contextualize_validation_error(
                    exc,
                    compiled_data,
                    model_data,
                    compilation_report,
                )
                failure_kind = _validation_failure_kind(exc)
                _record_validation_failure(
                    metrics, failure_kind, last_error, last_issues
                )
                result = patch_result
                compiler_issues = [
                    issue
                    for issue in last_issues
                    if issue.get("repair_owner") == "compiler"
                ]
                if compiler_issues:
                    host_error = DesignDnaExtractionError(
                        "局部修复经确定性编译后仍存在机械一致性错误，请检查宿主编译器：\n"
                        f"{exc}"
                    )
                    raise persist_failure(host_error) from exc

    if full_result_path is None and model_data is not None:
        _emit_progress(
            progress_callback,
            ExtractionStage.COMPILING,
            "局部修复仍未闭合，正在执行不新增视觉事实的保守整理",
            89,
            ProgressEventLevel.WARNING,
        )
        degraded_data, action_count = _safely_degrade_invalid_observations(
            model_data,
            last_issues,
        )
        if action_count:
            metrics["safe_degradation_count"] += action_count
            try:
                model_data = degraded_data
                full_result_path, compiled_data = compile_and_save(model_data)
            except DesignDnaExtractionError as exc:
                last_issues = _validation_issues(exc, compilation_report)
                last_error = _contextualize_validation_error(
                    exc,
                    compiled_data,
                    model_data,
                    compilation_report,
                )
                _record_validation_failure(
                    metrics,
                    _validation_failure_kind(exc),
                    last_error,
                    last_issues,
                )

    if full_result_path is None and model_data is None:
        for _attempt in range(MAX_FULL_FALLBACK_ATTEMPTS):
            metrics["full_fallback_attempt_count"] += 1
            _emit_progress(
                progress_callback,
                ExtractionStage.REPAIRING,
                "模型响应无法解析，正在进行最后一次完整结构修复",
                89,
                ProgressEventLevel.WARNING,
            )
            fallback_messages = [
                *result.get("messages", messages),
                {
                    "role": "user",
                    "content": (
                        "局部补丁未能形成有效结果。最后兜底一次：保留已有图片证据支持的"
                        "视觉事实，返回一份符合精简模型观察 Schema 的完整 JSON。不要输出"
                        "静态元数据、统计、排序、候选镜像或组合预设。仍需修复的错误如下：\n"
                        f"{str(last_error)[:8000]}"
                    ),
                },
            ]
            select_model_phase(ExtractionStage.REPAIRING, "完整结构修复", 89)
            fallback_result = _invoke_agent(
                agent,
                fallback_messages,
                telemetry,
                metrics,
                on_retry=report_retry,
            )
            try:
                model_data = _parse_json_response(fallback_result)
                full_result_path, compiled_data = compile_and_save(model_data)
                result = fallback_result
                break
            except DesignDnaExtractionError as exc:
                last_issues = _validation_issues(exc, compilation_report)
                last_error = _contextualize_validation_error(
                    exc,
                    compiled_data,
                    model_data,
                    compilation_report,
                )
                _record_validation_failure(
                    metrics,
                    _validation_failure_kind(exc),
                    last_error,
                    last_issues,
                )

    if full_result_path is None or compiled_data is None or model_data is None:
        failure = last_error or DesignDnaExtractionError("设计 DNA 提取失败")
        raise persist_failure(failure)

    _emit_progress(
        progress_callback,
        ExtractionStage.GENERATING_VIEW,
        "最终校验已通过，正在生成业务视图",
        93,
    )
    business_view_path = _create_business_view(full_result_path)
    _emit_progress(
        progress_callback,
        ExtractionStage.FINALIZING,
        "正在保存生成模型、结果缩略图和追溯信息",
        97,
    )
    save_business_view_model(full_result_path.stem, model_id)
    save_result_image(full_result_path.stem, image_path)
    try:
        relative_image_path = str(image_path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        relative_image_path = str(image_path.resolve())
    metrics.update(telemetry.snapshot())
    save_result_trace(
        full_result_path.stem,
        {
            "result_id": full_result_path.stem,
            "input_image": {
                "path": relative_image_path,
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            },
            "model_id": model_id,
            "user_prompt": user_prompt,
            "agent_prompt_version": AGENT_PROMPT_VERSION,
            "skill": BOUND_SKILL_NAME,
            "schema_version": compiled_data.get("schema_version"),
            "model_output_schema_version": model_data.get("schema_version"),
            "knowledge_base_version": compiled_data.get("knowledge_base_version"),
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "full_result_file": full_result_path.name,
            "business_view_file": business_view_path.name,
            "execution_metrics": metrics,
        },
    )
    return ExtractionOutput(full_result_path, business_view_path)
