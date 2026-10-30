"""用真实 DeepAgents 图验证阶段预算与权限，不调用外部模型服务。"""

import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.exceptions import ContextOverflowError
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from app.agents.bounded import create_bounded_agent
from app.agents.design_dna_extractor import create_design_dna_agent, create_style_semantic_review_agent
from app.agents.design_trend_synthesizer import agent_messages, create_trend_agent
from app.agents.moodboard_generator import run_moodboard_step, stage_prompt
from app.services.llm.telemetry import ModelCallTelemetry


class RecordingModel(FakeMessagesListChatModel):
    """记录实际收到的消息及绑定工具，检测中间件意外改写或额外调用。"""

    received: list = Field(default_factory=list)
    bound_tools: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tools.append([item.name for item in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class OverflowModel(RecordingModel):
    def _generate(self, messages, **kwargs):
        self.received.append(messages)
        raise ContextOverflowError("context length exceeded")


def tool_reply(name="lookup", call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


class BoundedAgentTests(TestCase):
    def test_agent_is_reusable_and_preserves_large_frozen_input(self):
        model = RecordingModel(responses=[AIMessage(content="完成")])
        agent = create_bounded_agent(model=model, system_prompt="冻结 Skill", name="offline")
        # 超过默认文件转存阈值的单条文本，必须完整进入模型。
        content = "evidence " * 30_000
        for _ in range(2):
            telemetry = ModelCallTelemetry()
            result = agent.invoke({"messages": [HumanMessage(content)]},
                                  config={"callbacks": [telemetry]})
            self.assertEqual(result["messages"][-1].content, "完成")
            self.assertEqual(telemetry.snapshot()["llm_request_count"], 1)
        self.assertEqual(len(model.received), 2)
        self.assertFalse(model.bound_tools)
        for messages in model.received:
            self.assertEqual(messages[0].content, "冻结 Skill")
            self.assertEqual(messages[-1].content, content)

    def test_context_overflow_does_not_summarize_or_retry(self):
        model = OverflowModel(responses=[AIMessage(content="不应返回")])
        agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline")
        with self.assertRaises(ContextOverflowError):
            agent.invoke({"messages": [HumanMessage("原始证据")]})
        self.assertEqual(len(model.received), 1)

    def test_unexpected_tools_fail_before_any_tool_execution(self):
        for name in ("task", "read_file", "write_file", "write_todos", "unknown"):
            with self.subTest(tool=name):
                model = RecordingModel(responses=[tool_reply(name)])
                agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline")
                with self.assertRaisesRegex(RuntimeError, "禁止调用工具或子代理"):
                    agent.invoke({"messages": [HumanMessage("测试")]})
                self.assertEqual(len(model.received), 1)

    def test_real_field_lookup_and_final_answer_use_only_declared_tool(self):
        model = RecordingModel(responses=[AIMessage(content="", tool_calls=[{
            "name": "resolve_applicable_design_fields", "id": "fields",
            "args": {"target_view": "front", "active_profiles": ["core"]},
        }]), AIMessage(content="{}")])
        with patch("app.agents.design_dna_extractor.create_chat_model", return_value=model):
            agent = create_design_dna_agent("gemini-3.8-flash")
            result = agent.invoke({"messages": [HumanMessage("单图离线夹具")]})
        self.assertEqual(len(model.received), 2)
        self.assertEqual(model.bound_tools, [["resolve_applicable_design_fields"]] * 2)
        self.assertEqual(result["messages"][-1].content, "{}")
        self.assertTrue(any(isinstance(m, ToolMessage) and "CMP-13" in m.content
                            for m in result["messages"]))
        self.assertNotIn("available_skills", model.received[0][0].content)

    def test_style_review_has_no_tools_or_additional_skill_catalog(self):
        model = RecordingModel(responses=[AIMessage(content='{"decisions":[]}')])
        with patch("app.agents.design_dna_extractor.create_chat_model", return_value=model):
            agent = create_style_semantic_review_agent("gemini-3.8-flash")
            agent.invoke({"messages": [HumanMessage("复核冻结字段")]})
        self.assertEqual(len(model.received), 1)
        self.assertFalse(model.bound_tools)

    def test_mixed_allowed_and_forbidden_calls_do_not_execute_allowed_tool(self):
        calls = []

        @tool
        def lookup() -> str:
            """只记录调用，用于验证混合工具回复不会部分执行。"""
            calls.append("lookup")
            return "field"

        reply = AIMessage(content="", tool_calls=[
            {"name": "lookup", "id": "allowed", "args": {}},
            {"name": "task", "id": "forbidden", "args": {}},
        ])
        model = RecordingModel(responses=[reply])
        agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline",
                                     tools=[lookup], model_call_limit=2)
        with self.assertRaisesRegex(RuntimeError, "禁止调用工具或子代理"):
            agent.invoke({"messages": [HumanMessage("测试")]})
        self.assertEqual(calls, [])

    def test_official_model_and_tool_budgets_stop_loops(self):
        for limit, error_type in ((1, ModelCallLimitExceededError), (2, ToolCallLimitExceededError)):
            with self.subTest(model_limit=limit):
                calls = []

                @tool
                def lookup() -> str:
                    """返回本地字段，不访问外部服务。"""
                    calls.append("lookup")
                    return "field"

                model = RecordingModel(responses=[tool_reply(), tool_reply(call_id="call-2")])
                agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline",
                                             tools=[lookup], model_call_limit=limit)
                with self.assertRaises(error_type):
                    agent.invoke({"messages": [HumanMessage("测试")]})
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(model.received), limit)

    def test_trend_budget_rejects_before_model_and_can_run_again(self):
        job = {"messages": [{"role": "system", "content": "阶段"},
                            {"role": "user", "content": "资料"}]}
        model = RecordingModel(responses=[AIMessage(content="结果")])
        with patch("app.agents.design_trend_synthesizer.create_chat_model", return_value=model):
            agent = create_trend_agent("gpt-6-sol", job, "冻结规则")
        with self.assertRaisesRegex(ValueError, "字符预算"):
            agent.invoke({"messages": [HumanMessage("x" * 48_001)]})
        self.assertFalse(model.received)
        for _ in range(2):
            agent.invoke({"messages": agent_messages(job, "冻结规则")[1:]})
        self.assertEqual(len(model.received), 2)
        self.assertEqual(model.received[0][0].content, agent_messages(job, "冻结规则")[0]["content"])

    def test_moodboard_keeps_frozen_prompt_without_skill_catalog(self):
        model = RecordingModel(responses=[AIMessage(content='{"clusters":[]}')])
        with patch("app.agents.moodboard_generator.create_chat_model", return_value=model):
            result = run_moodboard_step("gpt-6-sol", "cluster", {"images": []}, "冻结规则")
        self.assertEqual(result["telemetry"]["llm_request_count"], 1)
        self.assertEqual(model.received[0][0].content, stage_prompt("cluster", "冻结规则"))


class AsyncBoundedAgentTests(IsolatedAsyncioTestCase):
    async def test_concurrent_runs_do_not_share_call_budget(self):
        model = FakeMessagesListChatModel(responses=[AIMessage(content="完成")])
        agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline")
        counters = [ModelCallTelemetry(), ModelCallTelemetry()]
        results = await asyncio.gather(*[
            agent.ainvoke({"messages": [HumanMessage("测试")]}, config={"callbacks": [counter]})
            for counter in counters
        ])
        self.assertTrue(all(result["messages"][-1].content == "完成" for result in results))
        self.assertEqual([c.snapshot()["llm_request_count"] for c in counters], [1, 1])

    async def test_async_unexpected_tool_is_blocked_after_one_request(self):
        model = FakeMessagesListChatModel(responses=[tool_reply("task")])
        telemetry = ModelCallTelemetry()
        agent = create_bounded_agent(model=model, system_prompt="冻结", name="offline")
        with self.assertRaisesRegex(RuntimeError, "禁止调用工具或子代理"):
            await agent.ainvoke({"messages": [HumanMessage("测试")]},
                                config={"callbacks": [telemetry]})
        self.assertEqual(telemetry.snapshot()["llm_request_count"], 1)
