"""趋势模型适配器的离线协议、异常分类和凭据保护测试。"""

import copy
from datetime import datetime, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from scripts import design_trend_model_adapter as adapter


class ServiceError(Exception):
    def __init__(self, message, status=None, headers=None, body=None):
        super().__init__(message)
        self.status_code = status
        self.response = SimpleNamespace(status_code=status, headers=headers or {})
        self.body = body


class FakeStreamChatModel(BaseChatModel):
    """走已安装 LangChain 的 invoke 聚合路径，但不创建网络客户端。"""

    streaming: bool = True
    events: list[tuple[float, AIMessageChunk]]
    clock: list[float]
    end_at: float
    stream_error: Exception | None = None

    @property
    def _llm_type(self):
        return "offline-observability-test"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("假流模型必须走 streaming 路径")

    def _stream(self, messages, stop=None, **kwargs):
        for observed_at, message in self.events:
            self.clock[0] = observed_at
            yield ChatGenerationChunk(message=message)
        self.clock[0] = self.end_at
        if self.stream_error is not None:
            raise self.stream_error


class DesignTrendModelAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(api_key="secret-test-key", base_url="https://private-gateway.example/v1")
        self.request = {
            "model_profile": {"model": "gpt-5.6-sol-20260820", "parameters": {"max_tokens": 12000, "temperature": 0, "reasoning_effort": "high"}},
            "messages": [{"role": "system", "content": "仅分析文本"}, {"role": "user", "content": "source text"}],
        }

    def invoke(self, response=None, error=None):
        model = Mock()
        model.invoke.return_value = response or SimpleNamespace(content='{"result":true}', response_metadata={}, usage_metadata=None)
        model.invoke.side_effect = error
        with patch.object(adapter, "get_llm_settings", return_value=self.settings), patch.object(adapter, "create_chat_model", return_value=model) as factory:
            result = adapter.run_request(self.request)
        return result, factory, model

    def test_success_preserves_explicit_parameters_text_and_reported_model(self):
        original = copy.deepcopy(self.request)
        raw = ' {"result": true}\n'
        response = SimpleNamespace(content=raw, response_metadata={"model_name": "provider-model-revision", "finish_reason": "stop"},
                                   usage_metadata={"input_tokens": 17, "output_tokens": 9})
        result, factory, model = self.invoke(response)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["raw_response"], raw)
        self.assertEqual(result["response"], {"result": True})
        self.assertEqual(result["model"], "provider-model-revision")
        self.assertTrue(result["model_reported_by_provider"])
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (17, 9))
        self.assertEqual(result["model_profile"], original["model_profile"])
        factory.assert_called_once_with(original["model_profile"]["model"], settings=self.settings,
                                       **original["model_profile"]["parameters"], streaming=True, max_retries=0, timeout=150)
        model.invoke.assert_called_once()
        self.assertEqual(model.invoke.call_args.args, (original["messages"],))
        self.assertEqual(set(model.invoke.call_args.kwargs), {"config"})
        callbacks = model.invoke.call_args.kwargs["config"]["callbacks"]
        self.assertEqual(len(callbacks), 1)
        self.assertIsInstance(callbacks[0], adapter._StreamTiming)
        self.assertEqual(self.request, original)

    def test_unreported_model_is_explicit_and_missing_usage_stays_unknown(self):
        result, _, _ = self.invoke()
        self.assertEqual(result["model"], self.request["model_profile"]["model"])
        self.assertFalse(result["model_reported_by_provider"])
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["output_tokens"])

    def test_invalid_model_json_is_not_repaired_or_network_error(self):
        for raw in ('```json\n{"a":1}\n```', '{"a":1,"a":2}', '{"value":NaN}', '{broken', '[]'):
            with self.subTest(raw=raw):
                result, _, model = self.invoke(SimpleNamespace(content=raw, response_metadata={}, usage_metadata={}))
                self.assertEqual(result["status"], "ok")
                self.assertIsNone(result["response"])
                self.assertEqual(result["raw_response"], raw)
                self.assertEqual(model.invoke.call_count, 1)

    def test_text_blocks_and_legacy_usage_are_supported(self):
        response = SimpleNamespace(content=[{"type": "text", "text": '{"ok":'}, {"type": "text", "text": "true}"}],
                                   response_metadata={"token_usage": {"prompt_tokens": 4, "completion_tokens": 2}}, usage_metadata=None)
        result, _, _ = self.invoke(response)
        self.assertEqual(result["response"], {"ok": True})
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (4, 2))

    def invoke_stream(self, events, *, error=None, end_at=110.0):
        model = FakeStreamChatModel(streaming=True, events=events, clock=[100.0],
                                    end_at=end_at, stream_error=error)
        with patch.object(adapter, "get_llm_settings", return_value=self.settings), \
                patch.object(adapter, "create_chat_model", return_value=model), \
                patch.object(adapter.time, "perf_counter", side_effect=lambda: model.clock[0]):
            return adapter.run_request(self.request)

    def test_real_langchain_fake_stream_measures_events_and_preserves_response(self):
        result = self.invoke_stream([
            (102.0, AIMessageChunk(content="")),
            (103.0, AIMessageChunk(content=" ")),
            (105.0, AIMessageChunk(content='{"ok":')),
            (108.0, AIMessageChunk(content="true}",
                                 response_metadata={"model_name": "provider-revision", "finish_reason": "stop"},
                                 usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                                                 "input_token_details": {"cache_read": 5},
                                                 "output_token_details": {"reasoning": 3}})),
        ])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["raw_response"], ' {"ok":true}')
        self.assertEqual(result["response"], {"ok": True})
        self.assertEqual(result["model"], "provider-revision")
        self.assertEqual(result["finish_reason"], "stop")
        # 细分只能解释总量，缓存和推理不能额外加到 input/output 上。
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (20, 10))
        observations = result["observability"]
        self.assertEqual(observations["schema_version"], 1)
        self.assertIn("not_raw_sse_or_per_token", observations["timing_scope"])
        self.assertEqual(observations["stream_timing_seconds"], {
            "first_stream_event": 2.0, "first_visible_text": 5.0, "call_end": 10.0,
        })
        self.assertEqual(observations["usage_details"], {
            "cached_input_tokens": 5, "reasoning_output_tokens": 3,
            "audio_input_tokens": None, "audio_output_tokens": None,
        })

    def test_callback_ignores_reasoning_tool_and_whitespace_until_visible_text(self):
        with patch.object(adapter.time, "perf_counter", side_effect=[100, 101, 102, 103, 104, 107]):
            timing = adapter._StreamTiming()
            for content in ([{"type": "thinking", "thinking": "hidden"}],
                            [{"type": "reasoning", "text": "hidden"}],
                            [{"type": "tool_use", "text": "hidden"}, {"type": "text", "text": " \n"}],
                            [{"type": "text", "text": "visible"}]):
                timing.on_llm_new_token("misleading token", chunk=SimpleNamespace(message=SimpleNamespace(content=content)))
            timing.finish()
        self.assertEqual(timing.snapshot()["stream_timing_seconds"], {
            "first_stream_event": 1, "first_visible_text": 4, "call_end": 7,
        })

    def test_no_callbacks_does_not_infer_first_text_time_from_final_response(self):
        with patch.object(adapter.time, "perf_counter", side_effect=[100, 179]):
            result, _, _ = self.invoke()
        observations = result["observability"]
        self.assertEqual(observations["stream_timing_seconds"], {
            "first_stream_event": None, "first_visible_text": None, "call_end": 79,
        })
        self.assertTrue(all(value is None for value in observations["usage_details"].values()))

    def test_fake_stream_errors_preserve_observed_timing_and_error_category(self):
        for events, first_event, first_text in (
            ([], None, None),
            ([(102.0, AIMessageChunk(content=""))], 2.0, None),
            ([(102.0, AIMessageChunk(content="")), (104.0, AIMessageChunk(content="partial"))], 2.0, 4.0),
        ):
            with self.subTest(first_event=first_event, first_text=first_text):
                result = self.invoke_stream(events, error=TimeoutError("expired"), end_at=106.0)
                self.assertEqual(result["category"], "timeout")
                self.assertEqual(result["observability"]["stream_timing_seconds"], {
                    "first_stream_event": first_event, "first_visible_text": first_text, "call_end": 6.0,
                })
                self.assertNotIn("raw_response", result)

    def test_reported_usage_details_support_legacy_responses_and_anthropic_shapes(self):
        cases = [
            {"token_usage": {"prompt_tokens_details": {"cached_tokens": 4, "audio_tokens": 2},
                             "completion_tokens_details": {"reasoning_tokens": 3, "audio_tokens": 1}}},
            {"token_usage": {"input_tokens_details": {"cached_tokens": 4, "audio_tokens": 2},
                             "output_tokens_details": {"reasoning_tokens": 3, "audio_tokens": 1}}},
            {"usage": {"cache_read_input_tokens": 4, "output_tokens_details": {"thinking_tokens": 3}}},
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                response = SimpleNamespace(content='{"ok":true}', response_metadata=metadata,
                                           usage_metadata={"input_tokens": 20, "output_tokens": 10})
                result, _, _ = self.invoke(response)
                details = result["observability"]["usage_details"]
                self.assertEqual((details["cached_input_tokens"], details["reasoning_output_tokens"]), (4, 3))
                if "token_usage" in metadata:
                    self.assertEqual((details["audio_input_tokens"], details["audio_output_tokens"]), (2, 1))
                self.assertEqual((result["input_tokens"], result["output_tokens"]), (20, 10))

    def test_usage_details_preserve_zero_and_ignore_invalid_counts_without_summing(self):
        for prefix in ("", "priority_", "flex_"):
            details = adapter._usage_details({
                "input_token_details": {prefix + "cache_read": 0},
                "output_token_details": {prefix + "reasoning": 7},
            }, {"token_usage": {"prompt_tokens_details": {"cached_tokens": 9}}})
            self.assertEqual(details["cached_input_tokens"], 0)
            self.assertEqual(details["reasoning_output_tokens"], 7)
        for invalid in (None, -1, True, "5", 2.5, {}, []):
            with self.subTest(invalid=invalid):
                details = adapter._usage_details({
                    "input_token_details": {"cache_read": invalid},
                    "output_token_details": {"reasoning": invalid},
                }, {})
                self.assertIsNone(details["cached_input_tokens"])
                self.assertIsNone(details["reasoning_output_tokens"])
        self.assertTrue(all(value is None for value in adapter._usage_details({}, {"usage": "malformed"}).values()))

    def test_max_tokens_is_required_and_not_silently_added(self):
        for value in (None, 0, -1, True, "12000"):
            with self.subTest(value=value):
                request = copy.deepcopy(self.request)
                if value is None:
                    del request["model_profile"]["parameters"]["max_tokens"]
                else:
                    request["model_profile"]["parameters"]["max_tokens"] = value
                with patch.object(adapter, "create_chat_model") as factory:
                    self.assertEqual(adapter.run_request(request)["category"], "permanent")
                factory.assert_not_called()

    def test_connection_transport_and_bypass_parameters_are_rejected(self):
        for name in ("model", "model_provider", "api_key", "key", "base_url", "http_client", "default_headers",
                     "timeout", "request_timeout", "max_retries", "streaming", "model_kwargs", "extra_body"):
            with self.subTest(name=name):
                request = copy.deepcopy(self.request)
                request["model_profile"]["parameters"][name] = "forbidden"
                with patch.object(adapter, "create_chat_model") as factory:
                    self.assertEqual(adapter.run_request(request)["category"], "permanent")
                factory.assert_not_called()

    def test_multimodal_or_tool_messages_are_rejected_before_model_call(self):
        for message in ({"role": "user", "content": [{"type": "image_url", "image_url": "http://example.test/image"}]},
                        {"role": "tool", "content": "text"}, {"role": "assistant", "content": "text", "tool_calls": []}):
            request = copy.deepcopy(self.request)
            request["messages"] = [message]
            with patch.object(adapter, "create_chat_model") as factory:
                self.assertEqual(adapter.run_request(request)["category"], "permanent")
            factory.assert_not_called()

    def test_status_codes_override_ambiguous_error_body(self):
        expected = {400: "permanent", 401: "authentication", 403: "authentication", 429: "rate_limit", 408: "timeout", 504: "timeout", 524: "timeout", 503: "overload", 502: "transport"}
        for status, category in expected.items():
            error = ServiceError("Server overloaded; stream_read_error; try reconnecting", status, body={"error": {"type": "overloaded_error"}})
            self.assertEqual(adapter.classify_error(error)["category"], category)

    def test_explicit_transport_types_and_unknown_errors(self):
        # 实际网关使用复数及 currently，不能漏分成永久错误。
        self.assertEqual(adapter.classify_error(RuntimeError("Our servers are currently overloaded. Please try again later."))["category"], "overload")
        examples = [
            (ServiceError("overloaded"), "overload"),
            (ServiceError("explicit error", body={"error": {"type": "overloaded_error"}}), "overload"),
            (ServiceError("stream_read_error"), "transport"),
            (ServiceError("Upstream HTTP/2 stream failed"), "transport"),
            (ConnectionResetError("connection reset"), "transport"),
            (TimeoutError("expired"), "timeout"),
            (RuntimeError("unexpected internal problem"), "permanent"),
        ]
        for error, category in examples:
            self.assertEqual(adapter.classify_error(error)["category"], category)

    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(adapter.parse_retry_after("12.5"), 12.5)
        now = datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()
        future = format_datetime(datetime.fromtimestamp(now + 90, timezone.utc), usegmt=True)
        self.assertEqual(adapter.parse_retry_after(future, now=now), 90)
        self.assertEqual(adapter.parse_retry_after(future, now=now + 200), 0)
        self.assertIsNone(adapter.parse_retry_after("invalid"))
        self.assertIsNone(adapter.parse_retry_after("NaN"))
        error = ServiceError("limited", 429, headers={"Retry-After": "17"})
        self.assertEqual(adapter.classify_error(error)["retry_after_seconds"], 17)

    def test_model_errors_redact_secrets_url_and_hostname(self):
        error = ServiceError("failed secret-test-key https://private-gateway.example/v1 zone private-gateway.example Authorization: Bearer other-secret", 524)
        result, _, model = self.invoke(error=error)
        serialized = json.dumps(result)
        for secret in ("secret-test-key", "private-gateway.example", "other-secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(result["category"], "timeout")
        self.assertEqual(model.invoke.call_count, 1)

    def test_configuration_failure_never_outputs_input_values(self):
        with patch.object(adapter, "get_llm_settings", side_effect=ValueError("input_value=very-secret-key")), patch.object(adapter, "create_chat_model") as factory:
            result = adapter.run_request(self.request)
        self.assertEqual(result["category"], "authentication")
        self.assertNotIn("very-secret-key", json.dumps(result))
        factory.assert_not_called()

    def test_main_writes_error_envelope_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            request, result = Path(folder) / "request.json", Path(folder) / "result.json"
            request.write_text(json.dumps(self.request))
            with patch.object(adapter, "run_request", return_value={"status": "error", "category": "rate_limit", "message": "test"}):
                self.assertEqual(adapter.main(["--request", str(request), "--result", str(result)]), 0)
            self.assertEqual(json.loads(result.read_text())["category"], "rate_limit")


if __name__ == "__main__":
    unittest.main()
