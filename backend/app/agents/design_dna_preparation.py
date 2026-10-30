"""用工程统一模型配置执行设计卡 Skill，保留单轮 DeepAgents 与完整原始证据。"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
from importlib.metadata import version
import json
import mimetypes
from pathlib import Path
from time import monotonic
from typing import Any

from jsonschema import Draft202012Validator
from langchain_core.messages import HumanMessage

from app.agents.bounded import AGENT_RUNTIME_VERSION, create_bounded_agent
from app.agents import bounded, dna_deep_agent
from app.agents.dna_deep_agent import _model_options
from app.services.llm import catalog, client, settings
from app.services.llm import create_chat_model
from app.services.llm.catalog import get_model
from app.services.llm.telemetry import ModelCallTelemetry
from app.services.dna.prism_r5 import _safe_exception


TRANSPORT = "project_langchain_sdk"
DEFAULT_MODEL = "gemini-3.8-flash"
RUNTIME_PATH = Path(__file__).resolve()


def _reference(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        stream.write("\n")


def execution_config(model_id: str) -> dict:
    """SDK 未显式设置推理强度时记为未知，不套用历史 Sol high 身份。"""
    get_model(model_id)
    return {"model": model_id, "reasoning_effort": "low" if model_id == "gpt-6-sol" else None,
            "runtime_ref": _reference(RUNTIME_PATH), "transport": TRANSPORT,
            "actual_model_policy": "provider_reported", "model_options": _model_options(model_id),
            "configuration_refs": [_reference(Path(module.__file__))
                                   for module in (bounded, dna_deep_agent, catalog, client, settings)]}


def _text(message: Any) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "\n".join(part if isinstance(part, str) else part.get("text", "")
                     for part in content if isinstance(part, (str, dict)))


def _json_answer(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    answer = json.loads(text)
    if not isinstance(answer, dict):
        raise ValueError("设计卡回答必须为 JSON 对象")
    return answer


def _safe_metadata(value: Any) -> Any:
    """供应商扩展元数据保留结构，连接头和鉴权字段不进入可下载的运行证据。"""
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if any(part in key.lower() for part in ("authorization", "api_key", "header"))
                      else _safe_metadata(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    return value


class _TraceTelemetry(ModelCallTelemetry):
    """在阶段权限检查拒绝回答前也保存原始模型消息，不丢失失败证据。"""

    def __init__(self):
        super().__init__()
        self.messages: list[Any] = []

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        for group in getattr(response, "generations", []) or []:
            for generation in group:
                message = getattr(generation, "message", None)
                if message is not None:
                    self.messages.append(message)
        super().on_llm_end(response, **kwargs)


def execute_structured(folder: str | Path, *, system: str, payload: dict,
                       images: list[dict], schema: dict, model_id: str) -> dict:
    """每图一次模型调用，SDK 重试与工具均关闭；原始字节按冻结 SHA 附图。"""
    configuration = execution_config(model_id)
    definition = get_model(model_id)
    options = configuration["model_options"]
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    _write(folder / "system.txt", system)
    _write(folder / "payload.json", payload)
    _write(folder / "schema.json", schema)
    # Schema 属于模型实际输入；保留原生 system 与 payload，避免网关不支持强制格式而改用工具。
    user_text = (json.dumps(payload, ensure_ascii=False) + "\n\n=== OUTPUT JSON SCHEMA ===\n"
                 + json.dumps(schema, ensure_ascii=False) + "\n只返回符合此 Schema 的 JSON 对象。")
    content = [{"type": "text", "text": user_text}]
    for image in images:
        path = Path(image["path"])
        image_bytes = path.read_bytes()
        if hashlib.sha256(image_bytes).hexdigest() != image["sha256"]:
            raise ValueError("附图字节与冻结 SHA 不一致")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content.append({"type": "image", "base64": base64.b64encode(image_bytes).decode("ascii"), "mime_type": mime})
    _write(folder / "prompt.txt", system + "\n=== ACTUAL PAYLOAD ===\n" + user_text)
    _write(folder / "sdk-request.json", {"messages": [{"role": "system", "content": system},
                                                     {"role": "user", "content": content}],
                                          "model_id": model_id, "model_options": options})
    started = datetime.now(UTC).isoformat()
    timer = monotonic()
    metadata = {"framework": "DeepAgents", "agent_runtime_version": AGENT_RUNTIME_VERSION,
                "deepagents_version": version("deepagents"), "transport": TRANSPORT,
                "model_adapter": "project_catalog_chat_model", "requested_model": model_id,
                "requested_reasoning_effort": configuration["reasoning_effort"],
                "actual_model_policy": configuration["actual_model_policy"], "actual_model": None,
                "actual_provider": None, "model_provider": definition.model_provider.value,
                "runtime_ref": configuration["runtime_ref"], "model_options": options,
                "configuration_refs": configuration["configuration_refs"],
                "connection_source": "app.services.llm.settings.get_llm_settings",
                "connection_secrets_recorded": False, "automatic_host_retries": False,
                "started_at": started, "images": images,
                "prompt_ref": _reference(folder / "prompt.txt"), "schema_ref": _reference(folder / "schema.json"),
                "sdk_request_ref": _reference(folder / "sdk-request.json")}
    _write(folder / "request.json", metadata)
    telemetry = _TraceTelemetry()
    receipt = {**metadata, "status": "failed"}
    try:
        model = create_chat_model(model_id, **options)
        agent = create_bounded_agent(model=model, system_prompt=system, name="prism-design-dna-preparation")
        result = agent.invoke({"messages": [HumanMessage(content=content)]},
                              config={"recursion_limit": 40, "callbacks": [telemetry]})
        message = result["messages"][-1]
        raw = _text(message)
        _write(folder / "answer.raw.txt", raw)
        answer = _json_answer(raw)
        Draft202012Validator(schema).validate(answer)
        _write(folder / "answer.json", answer)
        receipt.update(status="completed", answer_ref=_reference(folder / "answer.json"))
        return answer
    except Exception as exc:
        receipt["failure"] = _safe_exception(exc)
        raise RuntimeError(receipt["failure"]) from exc
    finally:
        if telemetry.messages:
            responses = []
            for message in telemetry.messages:
                response = message.model_dump(mode="json")
                response["response_metadata"] = _safe_metadata(response.get("response_metadata", {}))
                responses.append(response)
            _write(folder / "response.json", responses)
            receipt["response_ref"] = _reference(folder / "response.json")
            last = telemetry.messages[-1]
            response_metadata = getattr(last, "response_metadata", {}) or {}
            # 供应商可能返回别名；真实报告原样保留，不把请求 ID 填成实际模型。
            receipt["actual_model"] = response_metadata.get("model_name") or response_metadata.get("model")
            receipt["provider_response_metadata"] = _safe_metadata(response_metadata)
            if not (folder / "answer.raw.txt").exists():
                _write(folder / "answer.raw.txt", _text(last))
        usage = telemetry.snapshot()
        usage["usage_complete"] = bool(usage["llm_request_count"] > 0
                                       and usage["llm_request_count"] == usage["llm_success_count"]
                                       and usage["requests_with_usage"] == usage["llm_success_count"])
        receipt.update(finished_at=datetime.now(UTC).isoformat(), seconds=round(monotonic() - timer, 3), usage=usage)
        _write(folder / "receipt.json", receipt)
