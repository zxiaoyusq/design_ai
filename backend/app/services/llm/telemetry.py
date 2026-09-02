"""LangChain/DeepAgents 模型调用次数与 Token 用量采集。"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


class ModelCallTelemetry(BaseCallbackHandler):
    """采集一次业务执行中所有内部 ChatModel 调用的可用统计。"""

    def __init__(
        self,
        on_event: Callable[[str, int], None] | None = None,
    ) -> None:
        self._lock = Lock()
        self._on_event = on_event
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.requests_with_usage = 0

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, messages, run_id, parent_run_id, kwargs
        with self._lock:
            self.request_count += 1
            request_count = self.request_count
        self._notify("request_started", request_count)

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        del run_id, parent_run_id, kwargs
        usage = self._usage_from_response(response)
        with self._lock:
            self.success_count += 1
            if usage is not None:
                self.requests_with_usage += 1
                self.input_tokens += usage[0]
                self.output_tokens += usage[1]
                self.total_tokens += usage[2]
            request_count = self.request_count
        self._notify("request_completed", request_count)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        del error, run_id, parent_run_id, kwargs
        with self._lock:
            self.error_count += 1
            request_count = self.request_count
        self._notify("request_failed", request_count)

    def _notify(self, event: str, request_count: int) -> None:
        """进度展示异常不能反向中断真实模型调用。"""

        if self._on_event is None:
            return
        try:
            self._on_event(event, request_count)
        except Exception:
            return

    @staticmethod
    def _usage_from_response(response: Any) -> tuple[int, int, int] | None:
        """兼容 AIMessage.usage_metadata 与 provider 的 llm_output 统计格式。"""

        generations = getattr(response, "generations", None)
        if isinstance(generations, list):
            for generation_list in generations:
                if not isinstance(generation_list, list):
                    continue
                for generation in generation_list:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None)
                    normalized = ModelCallTelemetry._normalize_usage(usage)
                    if normalized is not None:
                        return normalized
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            for key in ("token_usage", "usage"):
                normalized = ModelCallTelemetry._normalize_usage(llm_output.get(key))
                if normalized is not None:
                    return normalized
        return None

    @staticmethod
    def _normalize_usage(usage: Any) -> tuple[int, int, int] | None:
        if not isinstance(usage, dict):
            return None
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
        total_tokens = usage.get("total_tokens")
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return None
        if not isinstance(total_tokens, int):
            total_tokens = input_tokens + output_tokens
        return input_tokens, output_tokens, total_tokens

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "llm_request_count": self.request_count,
                "llm_success_count": self.success_count,
                "llm_error_count": self.error_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "requests_with_usage": self.requests_with_usage,
                "usage_complete": self.requests_with_usage == self.success_count,
            }
