"""模型目录测试。"""

import unittest

from app.services.llm.catalog import ModelProvider, get_model, list_models


class ModelCatalogTestCase(unittest.TestCase):
    def test_catalog_contains_all_configured_models(self) -> None:
        self.assertEqual(
            [model.id for model in list_models()],
            [
                "claude-opus-5-20260820",
                "claude-fable-5-20260820",
                "gpt-5.6-terra-20260820",
                "gpt-5.6-sol-20260820",
                "MiniMax-M3",
                "qwen3.7-max",
            ],
        )

    def test_provider_mapping_is_explicit(self) -> None:
        self.assertIs(
            get_model("claude-opus-5-20260820").model_provider,
            ModelProvider.ANTHROPIC,
        )
        self.assertIs(
            get_model("qwen3.7-max").model_provider,
            ModelProvider.OPENAI,
        )

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持模型"):
            get_model("unknown-model")


if __name__ == "__main__":
    unittest.main()
