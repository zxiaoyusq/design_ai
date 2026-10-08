"""Sol R5 的模型路由不改变其他 DNA 模型的调用协议。"""

from unittest import TestCase

from app.agents.dna_deep_agent import _model_options
from app.services.llm.catalog import list_models
from app.services.dna.prism_r5 import _safe_exception


class PrismR5AgentTestCase(TestCase):
    def test_gpt_6_sol_uses_responses_with_low_reasoning(self) -> None:
        options = _model_options("gpt-6-sol")
        self.assertTrue(options["use_responses_api"])
        self.assertEqual(options["reasoning"], {"effort": "low"})
        self.assertNotIn("temperature", options)
        self.assertEqual(options["max_retries"], 0)

    def test_gpt_6_sol_batch_can_request_medium_without_changing_default(self) -> None:
        self.assertEqual(
            _model_options("gpt-6-sol", reasoning_effort="medium")["reasoning"],
            {"effort": "medium"},
        )
        self.assertEqual(_model_options("gpt-6-sol")["reasoning"], {"effort": "low"})

    def test_other_models_keep_existing_options(self) -> None:
        for definition in list_models():
            if definition.id == "gpt-6-sol":
                continue
            with self.subTest(model_id=definition.id):
                options = _model_options(definition.id)
                self.assertEqual(options["temperature"], 0)
                self.assertNotIn("use_responses_api", options)
                self.assertNotIn("reasoning", options)

    def test_unknown_model_remains_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _model_options("unknown")
        with self.assertRaises(ValueError):
            _model_options("gemini-3.8-flash", reasoning_effort="medium")

    def test_gateway_header_failure_is_redacted_before_persistence(self) -> None:
        encoded_headers = "a" * 300
        message = _safe_exception(ValueError("invalid header:" + encoded_headers))
        self.assertIn("头部明细已隐藏", message)
        self.assertNotIn(encoded_headers, message)

    def test_batch_single_request_exposes_no_builtin_tools(self) -> None:
        from unittest.mock import patch
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, HumanMessage
        from app.agents.dna_deep_agent import create_dna_agent
        model = FakeMessagesListChatModel(responses=[AIMessage(content='{}')])
        with patch('app.agents.dna_deep_agent.create_chat_model', return_value=model):
            agent = create_dna_agent('gemini-3.8-flash', '分析附图', 'offline-test', single_request=True)
            reply = agent.invoke({'messages': [HumanMessage(content='测试')]})
        # 假模型不支持bind_tools；成功返回证明内建工具未绑定到实际请求。
        self.assertEqual(reply['messages'][-1].content, '{}')

    def test_batch_rejects_unexpected_subagent_tool_before_execution(self) -> None:
        from unittest.mock import patch
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, HumanMessage
        from app.agents.dna_deep_agent import create_dna_agent
        model = FakeMessagesListChatModel(responses=[AIMessage(content='', tool_calls=[{
            'name': 'task', 'id': 'unexpected-task',
            'args': {'subagent_type': 'general-purpose', 'description': '不要执行'},
        }])])
        with patch('app.agents.dna_deep_agent.create_chat_model', return_value=model):
            agent = create_dna_agent('gemini-3.8-flash', '分析附图', 'offline-test', single_request=True)
            with self.assertRaisesRegex(RuntimeError, '禁止调用工具或子代理'):
                agent.invoke({'messages': [HumanMessage(content='测试')]})
