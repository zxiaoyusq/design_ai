"""执行 DeepAgent 多模态推理、校验及 Skill 规定的落盘流程。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.design_dna_extractor import (
    AGENT_PROMPT_VERSION,
    create_design_dna_agent,
)
from app.services.dna.storage import (
    save_business_view_model,
    save_result_image,
    save_result_trace,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SAVE_RESULT_SCRIPT = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-extractor"
    / "scripts"
    / "save_result.py"
)
BUSINESS_VIEW_SCRIPT = PROJECT_ROOT / "extract_design_dna_business_view.py"
KNOWLEDGE_BASE_PATH = (
    PROJECT_ROOT
    / "ref"
    / "multimodal-design-dna-extractor"
    / "references"
    / "design-dna-knowledge-base.zh-CN.md"
)
MAX_REPAIR_ATTEMPTS = 1


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
        "请使用 multimodal-design-dna-extractor Skill 分析随消息提供的单张图片。"
        "严格完成主物品锁定、品类适用性、风格硬规则、设计 DNA、证据、"
        "不确定字段和新 DNA 检查，最终只返回符合 Schema 的 JSON。\n\n"
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


def _recalculate_quality_summary(data: dict[str, Any]) -> None:
    """重算可由设计元素确定的统计值，避免模型手工计数误差。"""

    design_elements = data.get("design_elements")
    quality_summary = data.get("quality_summary")
    if not isinstance(design_elements, dict) or not isinstance(
        quality_summary, dict
    ):
        return

    elements: list[dict[str, Any]] = []
    for dimension in design_elements.get("original_md_dimensions", []):
        if isinstance(dimension, dict):
            elements.extend(
                item
                for item in dimension.get("elements", [])
                if isinstance(item, dict)
            )
    for module in design_elements.get("extended_dna_modules", []):
        if isinstance(module, dict):
            elements.extend(
                item
                for item in module.get("elements", [])
                if isinstance(item, dict)
            )

    quality_summary["low_confidence_field_count"] = sum(
        1
        for item in elements
        if isinstance(item.get("confidence"), (int, float))
        and item["confidence"] < 0.75
    )


def _normalized_style_name(value: str) -> str:
    return re.sub(r"[\s_\-—–|/（）()，,。.：:]+", "", value).lower()


def _canonicalize_style_names(data: dict[str, Any]) -> None:
    """把标点不同但语义相同的风格名还原为知识库标题原名。"""

    try:
        knowledge_base = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    level_1_names: dict[str, str] = {}
    level_2_names: dict[str, str] = {}
    in_style_section = False
    for line in knowledge_base.splitlines():
        if line.startswith("# 工作表：设计风格"):
            in_style_section = True
            continue
        if line.startswith("# 工作表：设计元素"):
            in_style_section = False
        if not in_style_section:
            continue
        if line.startswith("## 一级风格："):
            name = line.split("：", 1)[1].strip()
            level_1_names[_normalized_style_name(name)] = name
        elif line.startswith("### "):
            name = line[4:].strip()
            level_2_names[_normalized_style_name(name)] = name

    style_result = data.get("style_result")
    if not isinstance(style_result, dict):
        return
    assessments: list[dict[str, Any]] = []
    primary = style_result.get("primary_style")
    if isinstance(primary, dict):
        assessments.append(primary)
    assessments.extend(
        item
        for item in style_result.get("secondary_styles", [])
        if isinstance(item, dict)
    )
    assessments.extend(
        item
        for item in style_result.get("candidate_ranking", [])
        if isinstance(item, dict)
    )
    for assessment in assessments:
        for field, canonical_names in (
            ("level_1", level_1_names),
            ("level_2", level_2_names),
        ):
            value = assessment.get(field)
            if isinstance(value, str):
                assessment[field] = canonical_names.get(
                    _normalized_style_name(value),
                    value,
                )


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
    """对一张图片运行 Skill；校验失败时带错误信息修复一次。"""

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
    last_error: DesignDnaExtractionError | None = None

    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        result = agent.invoke(
            {"messages": messages},
            config={"recursion_limit": 120},
        )
        try:
            data = _parse_json_response(result)
            _canonicalize_style_names(data)
            _recalculate_quality_summary(data)
            full_result_path = _save_validated_result(image_path, data)
            business_view_path = _create_business_view(full_result_path)
            save_business_view_model(full_result_path.stem, model_id)
            save_result_image(full_result_path.stem, image_path)
            try:
                relative_image_path = str(image_path.resolve().relative_to(PROJECT_ROOT))
            except ValueError:
                relative_image_path = str(image_path.resolve())
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
                    "skill": "multimodal-design-dna-extractor",
                    "schema_version": data.get("schema_version"),
                    "knowledge_base_version": data.get("knowledge_base_version"),
                    "started_at": started_at.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "full_result_file": full_result_path.name,
                    "business_view_file": business_view_path.name,
                },
            )
            return ExtractionOutput(full_result_path, business_view_path)
        except DesignDnaExtractionError as exc:
            last_error = exc
            if attempt >= MAX_REPAIR_ATTEMPTS:
                break
            messages = [
                *result.get("messages", messages),
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过确定性校验。请保留有图片证据支持的事实，"
                        "只修复下列 JSON 结构或语义错误，并重新输出完整 JSON：\n"
                        f"{str(exc)[:8000]}"
                    ),
                },
            ]

    raise last_error or DesignDnaExtractionError("设计 DNA 提取失败")
