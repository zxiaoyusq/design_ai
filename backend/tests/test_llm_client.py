"""统一大模型客户端测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.llm.client import (
    _normalize_anthropic_stream_event,
    create_chat_model,
    invoke_model,
    stream_model,
)
from app.services.llm.settings import LLMSettings


class LLMClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = LLMSettings(
            llm_key="test-key",
            llm_url="https://gateway.example.com",
        )

    @patch("app.services.llm.client.GatewayCompatibleChatAnthropic")
    def test_anthropic_model_uses_anthropic_provider_options(self, factory: Mock) -> None:
        create_chat_model(
            "claude-opus-5-20260820",
            settings=self.settings,
            temperature=0,
        )

        factory.assert_called_once_with(
            model="claude-opus-5-20260820",
            base_url="https://gateway.example.com",
            api_key="test-key",
            temperature=0,
        )

    @patch("app.services.llm.client.langchain_init_chat_model")
    def test_openai_compatible_model_uses_openai_provider_options(self, factory: Mock) -> None:
        create_chat_model("MiniMax-M3", settings=self.settings)

        factory.assert_called_once_with(
            model="MiniMax-M3",
            model_provider="openai",
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
        )

    @patch("app.services.llm.client.langchain_init_chat_model")
    def test_openai_base_url_does_not_duplicate_v1(self, factory: Mock) -> None:
        settings = LLMSettings(
            llm_key="test-key",
            llm_url="https://gateway.example.com/v1/",
        )

        create_chat_model("qwen3.7-max", settings=settings)

        self.assertEqual(factory.call_args.kwargs["base_url"], "https://gateway.example.com/v1")

    def test_connection_options_cannot_be_overridden(self) -> None:
        with self.assertRaisesRegex(ValueError, "不允许覆盖"):
            create_chat_model(
                "qwen3.7-max",
                settings=self.settings,
                base_url="https://untrusted.example.com",
            )

    def test_anthropic_dict_context_event_is_normalized(self) -> None:
        event = Mock()
        event.context_management = {"applied_edits": []}
        event.model_copy.return_value = SimpleNamespace(
            context_management=event.context_management
        )
        event.model_copy.side_effect = lambda *, update: SimpleNamespace(**update)

        normalized = _normalize_anthropic_stream_event(event)

        self.assertEqual(
            normalized.context_management.model_dump(),
            {"applied_edits": []},
        )

    @patch("app.services.llm.client.create_chat_model")
    def test_invoke_and_stream_use_the_unified_factory(self, factory: Mock) -> None:
        chat_model = Mock()
        chat_model.invoke.return_value = Mock()
        chat_model.stream.return_value = iter([Mock(), Mock()])
        factory.return_value = chat_model

        invoke_model("gpt-5.6-sol-20260820", "你好", settings=self.settings)
        chunks = list(
            stream_model("gpt-5.6-sol-20260820", "你好", settings=self.settings)
        )

        self.assertEqual(factory.call_count, 2)
        chat_model.invoke.assert_called_once_with("你好")
        chat_model.stream.assert_called_once_with("你好")
        self.assertEqual(len(chunks), 2)


if __name__ == "__main__":
    unittest.main()
