"""DeepAgent 与设计 DNA Skill 接入测试。"""

import unittest
from unittest.mock import Mock, patch

from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agents.design_dna_extractor import (
    AGENT_SYSTEM_PROMPT,
    BOUND_SKILL_NAME,
    create_design_dna_agent,
    preloaded_skill_context,
    resolve_applicable_design_fields,
)


class DesignDnaAgentTestCase(unittest.TestCase):
    @patch("app.agents.design_dna_extractor.create_bounded_agent")
    @patch("app.agents.design_dna_extractor.create_chat_model")
    def test_agent_uses_selected_model_and_project_skill(
        self,
        model_factory: Mock,
        agent_factory: Mock,
    ) -> None:
        model = Mock()
        model_factory.return_value = model

        create_design_dna_agent("claude-opus-5-20260820")

        model_factory.assert_called_once_with(
            "claude-opus-5-20260820",
            temperature=0,
            max_tokens=128_000,
            streaming=True,
            timeout=300,
            max_retries=0,
        )
        self.assertEqual(agent_factory.call_args.kwargs["model"], model)
        self.assertEqual(
            agent_factory.call_args.kwargs["tools"],
            [resolve_applicable_design_fields],
        )
        self.assertIn(BOUND_SKILL_NAME, AGENT_SYSTEM_PROMPT)
        self.assertIn("design_dna_multitag_observation_v3", AGENT_SYSTEM_PROMPT)
        self.assertIn("静态元数据、模块清单、统计值、排序", AGENT_SYSTEM_PROMPT)
        self.assertEqual(
            agent_factory.call_args.kwargs["name"],
            "design-dna-multitag-extractor",
        )
        system_prompt = agent_factory.call_args.kwargs["system_prompt"]
        self.assertIn("<PRELOADED_SKILL_CONTEXT", system_prompt)
        self.assertIn('name="MODEL_REFERENCE_BUNDLE"', system_prompt)
        self.assertIn('name="MODEL_OUTPUT_SCHEMA"', system_prompt)
        self.assertIn("直接使用该快照完成任务", system_prompt)

    def test_field_tool_properties_have_explicit_schema_types(self) -> None:
        schema = convert_to_openai_tool(resolve_applicable_design_fields)["function"]["parameters"]
        for property_name, property_schema in schema["properties"].items():
            with self.subTest(property=property_name):
                self.assertIn("type", property_schema)

    @patch("app.agents.design_dna_extractor.create_bounded_agent")
    @patch("app.agents.design_dna_extractor.create_chat_model")
    def test_non_anthropic_model_does_not_set_max_tokens(
        self,
        model_factory: Mock,
        _agent_factory: Mock,
    ) -> None:
        create_design_dna_agent("gpt-6-sol")

        self.assertNotIn("max_tokens", model_factory.call_args.kwargs)

    def test_preloaded_context_contains_field_types_and_all_style_candidates(self) -> None:
        context = preloaded_skill_context()

        self.assertIn('"field_id":"GEO-01"', context)
        self.assertIn('"value_type":"float"', context)
        self.assertIn('"style_id":"NordicCalm"', context)
        self.assertIn("design_dna_multitag_observation_v3", context)

    def test_field_gate_filters_view_and_profile_specific_fields(self) -> None:
        result = resolve_applicable_design_fields.invoke(
            {"target_view": "front", "active_profiles": ["core"]}
        )
        field_ids = {
            item["field_id"]
            for key in ("direct_fields", "computed_fields")
            for item in result[key]
        }

        self.assertNotIn("FORM-05", field_ids)
        self.assertNotIn("TEX-08", field_ids)
        self.assertNotIn("HUM-03", field_ids)
        self.assertIn("CMP-13", field_ids)


if __name__ == "__main__":
    unittest.main()
