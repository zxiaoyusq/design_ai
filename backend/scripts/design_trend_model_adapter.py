"""项目模型服务到趋势 Skill runner 的文本适配器；不执行重试或修复 JSON。"""

from __future__ import annotations

import argparse
import copy
from datetime import timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote, urlsplit

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from langchain_core.callbacks import BaseCallbackHandler

from app.services.llm.client import create_chat_model, get_llm_settings


# 仅允许影响生成内容的显式选项，拒绝 model_kwargs/extra_body 等绕过连接约束的容器。
OUTPUT_PARAMETERS = frozenset({
    "max_tokens", "temperature", "top_p", "top_k", "frequency_penalty", "presence_penalty",
    "seed", "stop", "reasoning_effort", "reasoning", "thinking", "verbosity",
    "response_format", "logprobs", "top_logprobs",
})
ADAPTER_TIMEOUT_SECONDS = 150


def _parse_model_json(raw: str) -> dict[str, Any] | None:
    """只解析，不补围栏、标点或字段；不合法原文交给 runner 进行内容校验。"""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("重复 JSON 键")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("非标准 JSON 常数")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError:
        return None
    return result if isinstance(result, dict) else None


def validate_request(request: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """验证纯文本消息与生成参数；未提供 max_tokens 时沿用服务默认值，不主动补限额。"""
    if not isinstance(request, dict):
        raise ValueError("请求必须为 JSON 对象")
    profile = request.get("model_profile")
    if (not isinstance(profile, dict) or set(profile) != {"model", "parameters"}
            or not isinstance(profile["model"], str) or not profile["model"].strip()
            or not isinstance(profile["parameters"], dict)):
        raise ValueError("model_profile 必须明确包含 model 字符串和 parameters 对象")
    parameters = profile["parameters"]
    if set(parameters) - OUTPUT_PARAMETERS:
        raise ValueError("parameters 含未支持的生成选项或禁止覆盖的连接/传输选项")
    if "max_tokens" in parameters and (type(parameters["max_tokens"]) is not int or parameters["max_tokens"] <= 0):
        raise ValueError("max_tokens 如提供须为正整数")
    json.dumps(profile, allow_nan=False)
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 必须为非空文本消息数组")
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] not in {"system", "user", "assistant"}
                or not isinstance(message["content"], str)):
            raise ValueError("仅支持 system/user/assistant 的纯文本消息，不支持图片或工具消息")
    return copy.deepcopy(profile), copy.deepcopy(messages)


def parse_retry_after(value: Any, *, now: float | None = None) -> float | None:
    """Retry-After 同时支持秒数与 HTTP 日期，过去的日期视为无需额外等待。"""
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(str(value))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, when.timestamp() - (time.time() if now is None else now))
    except (TypeError, ValueError, OverflowError):
        return None


def _status_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    body = getattr(error, "body", None)
    values = [getattr(error, "status_code", None), getattr(response, "status_code", None)]
    if isinstance(body, dict):
        values.append(body.get("status"))
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 100 <= number <= 599:
            return number
    return None


def redact_error(error: Exception, sensitive_values: tuple[str, ...] = ()) -> str:
    """先替换已知连接秘密，再去掉 URL 和认证片段；不输出客户端配置对象。"""
    message = f"{type(error).__name__}: {error}"
    secrets = set(sensitive_values)
    for value in sensitive_values:
        if value:
            secrets.add(quote(value, safe=""))
            if value.startswith(("https://", "http://")):
                hostname = urlsplit(value).hostname
                if hostname:
                    secrets.add(hostname)
    for value in sorted((item for item in secrets if item), key=len, reverse=True):
        message = message.replace(value, "[REDACTED]")
    message = re.sub(r"https?://[^\s\"'<>]+", "[URL REDACTED]", message)
    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", message)
    message = re.sub(r"(?i)\b(?:authorization|api[_-]?key)\b\s*[:=]\s*[^,;\n]+", "credential=[REDACTED]", message)
    return message[:2000]


def classify_error(error: Exception, sensitive_values: tuple[str, ...] = ()) -> dict[str, Any]:
    """HTTP 状态优先于正文关键词，避免把 524 提示中的 overloaded 误判为过载。"""
    status = _status_code(error)
    if status in {401, 403}:
        category = "authentication"
    elif status == 429:
        category = "rate_limit"
    elif status in {408, 504, 524}:
        category = "timeout"
    elif status == 503:
        category = "overload"
    elif status == 502:
        category = "transport"
    elif status is not None and 400 <= status < 500:
        category = "permanent"
    else:
        name = type(error).__name__.lower()
        body = getattr(error, "body", None)
        codes = [getattr(error, "code", None)]
        if isinstance(body, dict):
            codes.extend((body.get("type"), body.get("code")))
            nested = body.get("error")
            if isinstance(nested, dict):
                codes.extend((nested.get("type"), nested.get("code")))
        labels = {str(code).lower() for code in codes if code is not None}
        text = str(error).lower()
        if name in {"authenticationerror", "permissiondeniederror"}:
            category = "authentication"
        elif isinstance(error, TimeoutError) or name in {"apitimeouterror", "readtimeout", "connecttimeout", "writetimeout", "pooltimeout"}:
            category = "timeout"
        elif (labels & {"overloaded", "overloaded_error", "server_overloaded"}
              or text.strip() == "overloaded"
              or re.search(r"\boverloaded_error\b|\b(?:servers?|services?|upstream|model)\s+(?:(?:is|are)\s+)?(?:currently\s+)?overloaded\b", text)):
            category = "overload"
        elif (isinstance(error, ConnectionError)
              or name in {"apiconnectionerror", "connecterror", "readerror", "remoteprotocolerror"}
              or labels & {"stream_read_error", "connection_error"}
              or re.search(r"\bstream_read_error\b|\bhttp/2 stream failed\b|\bconnection (?:reset|refused|closed)\b", text)):
            category = "transport"
        else:
            category = "permanent"
    envelope = {"status": "error", "category": category, "message": redact_error(error, sensitive_values)}
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None) or {}
    retry_value = next((value for key, value in headers.items() if str(key).lower() == "retry-after"), None)
    delay = parse_retry_after(retry_value)
    if delay is not None:
        envelope["retry_after_seconds"] = delay
    return envelope


def _has_visible_text(content: Any) -> bool:
    """仅把非空白文本计为可见输出，排除 thinking/reasoning 和工具块。"""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            (isinstance(part, str) and bool(part.strip()))
            or (isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str) and bool(part["text"].strip()))
            for part in content
        )
    return False


class _StreamTiming(BaseCallbackHandler):
    """旁路观测 invoke 的流回调，不改变请求、聚合文本或错误处理。"""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.first_stream_event: float | None = None
        self.first_visible_text: float | None = None
        self.call_end: float | None = None

    def on_llm_new_token(self, token: Any, *, chunk: Any = None, **kwargs: Any) -> None:
        elapsed = time.perf_counter() - self.started
        if self.first_stream_event is None:
            self.first_stream_event = elapsed
        # callback 的 token 名称不代表单个 token；有块时以块类型识别可见内容。
        content = getattr(getattr(chunk, "message", None), "content", token)
        if self.first_visible_text is None and _has_visible_text(content):
            self.first_visible_text = elapsed

    def finish(self) -> None:
        self.call_end = time.perf_counter() - self.started

    def snapshot(self) -> dict[str, Any]:
        # 仅能观测 LangChain 交付的块，无法还原原始 SSE、逐 token 或服务端推理时间。
        # 首段可见文本之前包含连接、排队、输入处理和上游缓冲，不能直接认定为排队时间；
        # first_visible_text 到 call_end 也只是客户端可见输出阶段，并非纯模型生成耗时。
        return {
            "schema_version": 1,
            "timing_scope": "client_langchain_callbacks_since_invoke_start_not_raw_sse_or_per_token",
            "stream_timing_seconds": {
                "first_stream_event": self.first_stream_event,
                "first_visible_text": self.first_visible_text,
                "call_end": self.call_end,
            },
        }


def _usage_details(usage: Any, metadata: dict[str, Any]) -> dict[str, int | None]:
    """只读取已报告的细分；缓存属于 input、推理属于 output，不能再次加到总量。"""
    sources = [usage, metadata.get("token_usage"), metadata.get("usage")]
    paths = {
        "cached_input_tokens": (
            ("input_token_details", "cache_read"),
            ("input_token_details", "priority_cache_read"),
            ("input_token_details", "flex_cache_read"),
            ("prompt_tokens_details", "cached_tokens"),
            ("input_tokens_details", "cached_tokens"),
            ("cache_read_input_tokens",),
        ),
        "reasoning_output_tokens": (
            ("output_token_details", "reasoning"),
            ("output_token_details", "priority_reasoning"),
            ("output_token_details", "flex_reasoning"),
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "thinking_tokens"),
        ),
        "audio_input_tokens": (
            ("input_token_details", "audio"),
            ("prompt_tokens_details", "audio_tokens"),
            ("input_tokens_details", "audio_tokens"),
        ),
        "audio_output_tokens": (
            ("output_token_details", "audio"),
            ("completion_tokens_details", "audio_tokens"),
            ("output_tokens_details", "audio_tokens"),
        ),
    }
    details = {}
    for field, candidates in paths.items():
        details[field] = None
        for source in sources:
            for keys in candidates:
                value = source
                for key in keys:
                    value = value.get(key) if isinstance(value, dict) else None
                if type(value) is int and value >= 0:
                    details[field] = value
                    break
            if details[field] is not None:
                break
    return details


def run_request(request: Any) -> dict[str, Any]:
    """调用统一模型工厂一次；完整文本和真实调用元数据交由 runner 校验与留痕。"""
    try:
        profile, messages = validate_request(request)
    except (ValueError, TypeError):
        return {"status": "error", "category": "permanent", "message": "请求无效：需纯文本 messages、合法生成参数，且不得覆盖连接或传输参数"}
    try:
        settings = get_llm_settings()
        secrets = (settings.api_key, settings.base_url)
    except Exception:
        # Pydantic 的错误字符串可能包含原始环境变量值，不能把它写到 envelope。
        return {"status": "error", "category": "authentication", "message": "无法加载模型连接配置，请检查后端统一配置"}
    timing = None
    try:
        model = create_chat_model(profile["model"], settings=settings,
                                  **copy.deepcopy(profile["parameters"]),
                                  streaming=True, max_retries=0, timeout=ADAPTER_TIMEOUT_SECONDS)
        timing = _StreamTiming()
        try:
            response = model.invoke(messages, config={"callbacks": [timing]})
        finally:
            timing.finish()
        content = response.content
        if isinstance(content, str):
            raw = content
        elif (isinstance(content, list) and all(isinstance(part, dict) and part.get("type") == "text"
                                              and isinstance(part.get("text"), str) for part in content)):
            raw = "".join(part["text"] for part in content)
        else:
            raise ValueError("模型返回非文本内容块，不能交给文本趋势流水线")
        metadata = getattr(response, "response_metadata", None) or {}
        usage = getattr(response, "usage_metadata", None) or metadata.get("token_usage", {}) or {}
        reported = metadata.get("model_name") or metadata.get("model")
        if not isinstance(reported, str) or not reported.strip():
            reported = None
        envelope = {"status": "ok", "response": _parse_model_json(raw), "raw_response": raw,
                    "model": reported or profile["model"], "model_reported_by_provider": reported is not None,
                    "model_profile": profile, "finish_reason": metadata.get("finish_reason")}
        for target, fallback in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
            value = usage.get(target, usage.get(fallback))
            envelope[target] = value if type(value) is int and value >= 0 else None
        envelope["observability"] = timing.snapshot()
        envelope["observability"]["usage_details_scope"] = "subsets_of_input_or_output_tokens_do_not_add"
        envelope["observability"]["usage_details"] = _usage_details(usage, metadata)
        return envelope
    except Exception as exc:
        envelope = classify_error(exc, secrets)
        if timing is not None:
            envelope["observability"] = timing.snapshot()
        return envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        envelope = run_request(request)
    except Exception:
        envelope = {"status": "error", "category": "permanent", "message": "无法读取有效请求文件"}
    temporary = None
    try:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.result.parent,
                                         prefix=".adapter-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(envelope, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        temporary.replace(args.result)
    except (OSError, ValueError, TypeError):
        print("无法写入适配器结果文件", file=sys.stderr)
        return 2
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
