"""DeepAgent 与设计 DNA Skill 接入测试。"""

import unittest
from unittest.mock import Mock, patch

from deepagents.middleware.filesystem import FilesystemPermission

from app.agents.design_dna_extractor import (
    SKILLS_SOURCE,
    create_design_dna_agent,
)


class DesignDnaAgentTestCase(unittest.TestCase):
    @patch("app.agents.design_dna_extractor.create_deep_agent")
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
            max_retries=1,
        )
        self.assertEqual(agent_factory.call_args.kwargs["model"], model)
        self.assertEqual(agent_factory.call_args.kwargs["skills"], [SKILLS_SOURCE])
        permissions = agent_factory.call_args.kwargs["permissions"]
        self.assertTrue(
            all(isinstance(rule, FilesystemPermission) for rule in permissions)
        )
        self.assertEqual([rule.mode for rule in permissions], ["deny", "deny"])

    @patch("app.agents.design_dna_extractor.create_deep_agent")
    @patch("app.agents.design_dna_extractor.create_chat_model")
    def test_non_anthropic_model_does_not_set_max_tokens(
        self,
        model_factory: Mock,
        _agent_factory: Mock,
    ) -> None:
        create_design_dna_agent("gpt-5.6-sol-20260820")

        self.assertNotIn("max_tokens", model_factory.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
