"""执行 DeepAgent 多模态推理，并由应用层统一校验与落盘。"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.design_dna_extractor import (
    AGENT_PROMPT_VERSION,
    BOUND_SKILL_NAME,
    PRELOADED_CONTEXT_VERSION,
    create_design_dna_agent,
    preloaded_skill_context_size,
)
from app.services.dna.storage import (
    save_business_view_model,
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
)


class DesignDnaExtractionError(RuntimeError):
    """单图 DNA 提取无法完成。"""


@dataclass(frozen=True, slots=True)
class ExtractionOutput:
    """校验并落盘后的两个结果文件。"""

    full_result_path: Path
    business_view_path: Path

    @property
    def result_id(self) -> str:
        return self.full_result_path.stem


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
        "最终只返回符合精简模型观察 Schema 的 JSON；字段和风格静态元数据、模块清单、"
        "统计值、排序、候选镜像、证据闭环与组合预设均由宿主编译，不要重复输出。\n\n"
        f"用户业务备注：\n{notes}"
    )


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


def _contextualize_validation_error(
    error: DesignDnaExtractionError,
    compiled: dict[str, Any] | None,
    model_data: dict[str, Any] | None,
) -> DesignDnaExtractionError:
    """为编译后数组路径补充对应的精简观察 JSON Pointer。"""

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
                compiled_path = (
                    "design_elements.extended_dna_modules."
                    f"{module_index}.elements.{element_index}"
                )
                if compiled_path not in error_text:
                    continue
                mappings.append(
                    f"{compiled_path} -> "
                    f"/design_observations/{candidates[0]} ({field_id}@{region})"
                )

    for index, item in enumerate(uncertainties):
        if isinstance(item, dict) and f"uncertain_fields.{index}" in error_text:
            mappings.append(
                f"uncertain_fields.{index} -> /uncertainties/{index} "
                f"({item.get('field_id')}@{item.get('region')})"
            )

    confirmed_tags = style_observations.get("confirmed_tags")
    if isinstance(confirmed_tags, list):
        for index, item in enumerate(confirmed_tags):
            if isinstance(item, dict) and f"style_result.style_tags.{index}" in error_text:
                mappings.append(
                    f"style_result.style_tags.{index} -> "
                    f"/style_observations/confirmed_tags/{index} ({item.get('style_id')})"
                )
    pairwise = style_observations.get("pairwise_reasoning")
    if isinstance(pairwise, list):
        for index, item in enumerate(pairwise):
            if (
                isinstance(item, dict)
                and f"style_result.pairwise_arbitrations.{index}" in error_text
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


def _merge_compilation_metrics(
    metrics: dict[str, Any], report: dict[str, Any]
) -> None:
    metrics["deterministic_compilation_count"] += 1
    metrics["deterministic_correction_count"] += int(
        report.get("deterministic_correction_count") or 0
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


def _invoke_agent(
    agent: Any,
    messages: list[Any],
    telemetry: ModelCallTelemetry,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    for network_attempt in range(MAX_AGENT_NETWORK_RETRIES + 1):
        metrics["agent_invocation_count"] += 1
        try:
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 120, "callbacks": [telemetry]},
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
) -> ExtractionOutput:
    """运行单图 Skill，并优先用确定性编译和局部补丁完成修复。"""

    started_at = datetime.now(UTC)
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
    telemetry = ModelCallTelemetry()
    metrics: dict[str, Any] = {
        "agent_invocation_count": 0,
        "deterministic_compilation_count": 0,
        "deterministic_correction_count": 0,
        "deterministic_corrections_by_area": {},
        "deterministic_changed_path_samples": [],
        "semantic_patch_attempt_count": 0,
        "full_fallback_attempt_count": 0,
        "validation_failure_kinds": [],
        "validation_failure_summaries": [],
        "application_network_retry_count": 0,
        # provider SDK 内部重试仍不可观测；流式断连由上面的应用层计数覆盖。
        "provider_internal_retry_count_observable": False,
        "preloaded_context_version": PRELOADED_CONTEXT_VERSION,
        "preloaded_context_chars": preloaded_skill_context_size(),
    }
    result = _invoke_agent(agent, messages, telemetry, metrics)
    model_data: dict[str, Any] | None = None
    last_error: DesignDnaExtractionError | None = None
    full_result_path: Path | None = None
    compiled_data: dict[str, Any] | None = None

    def compile_and_save(candidate: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        nonlocal compiled_data
        compiled_data = None
        compiled, report = _compile_model_result(candidate)
        compiled_data = compiled
        _merge_compilation_metrics(metrics, report)
        return _save_validated_result(image_path, compiled), compiled

    try:
        model_data = _parse_json_response(result)
        full_result_path, compiled_data = compile_and_save(model_data)
    except DesignDnaExtractionError as exc:
        last_error = _contextualize_validation_error(exc, compiled_data, model_data)
        failure_kind = (
            "structural" if model_data is None else _validation_failure_kind(exc)
        )
        _record_validation_failure(metrics, failure_kind, last_error)
        if failure_kind == "deterministic":
            raise DesignDnaExtractionError(
                "确定性编译后仍存在机械一致性错误，请检查宿主编译器：\n"
                f"{exc}"
            ) from exc

    if full_result_path is None and model_data is not None:
        for _attempt in range(MAX_PATCH_REPAIR_ATTEMPTS):
            metrics["semantic_patch_attempt_count"] += 1
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
                        "remove 操作省略 value；数组可用数字下标或 add 到 /-。错误如下：\n"
                        f"{str(last_error)[:8000]}"
                    ),
                },
            ]
            patch_result = _invoke_agent(agent, patch_messages, telemetry, metrics)
            try:
                repair_data = _parse_json_response(patch_result)
                if isinstance(repair_data.get("updates"), list):
                    model_data = _apply_json_patch(model_data, repair_data)
                else:
                    # 某些模型可能忽略补丁要求；若返回了完整契约，直接作为兜底候选。
                    model_data = repair_data
                full_result_path, compiled_data = compile_and_save(model_data)
                result = patch_result
                break
            except DesignDnaExtractionError as exc:
                last_error = _contextualize_validation_error(
                    exc, compiled_data, model_data
                )
                failure_kind = _validation_failure_kind(exc)
                _record_validation_failure(metrics, failure_kind, last_error)
                result = patch_result
                if failure_kind == "deterministic":
                    raise DesignDnaExtractionError(
                        "局部修复经确定性编译后仍存在机械一致性错误，请检查宿主编译器：\n"
                        f"{exc}"
                    ) from exc

    if full_result_path is None:
        for _attempt in range(MAX_FULL_FALLBACK_ATTEMPTS):
            metrics["full_fallback_attempt_count"] += 1
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
            fallback_result = _invoke_agent(agent, fallback_messages, telemetry, metrics)
            try:
                model_data = _parse_json_response(fallback_result)
                full_result_path, compiled_data = compile_and_save(model_data)
                result = fallback_result
                break
            except DesignDnaExtractionError as exc:
                last_error = _contextualize_validation_error(
                    exc, compiled_data, model_data
                )
                _record_validation_failure(
                    metrics,
                    _validation_failure_kind(exc),
                    last_error,
                )

    if full_result_path is None or compiled_data is None or model_data is None:
        raise last_error or DesignDnaExtractionError("设计 DNA 提取失败")

    business_view_path = _create_business_view(full_result_path)
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
