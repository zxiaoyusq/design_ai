"""DNA 多标签提取链路的绑定测试。"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agents.design_dna_extractor import BOUND_SKILL_NAME
from app.services.dna.extraction import (
    COMPILE_MODEL_OUTPUT_SCRIPT,
    SAVE_RESULT_SCRIPT,
    DesignDnaExtractionError,
    _apply_json_patch,
    _invoke_agent,
    _task_text,
    _validation_failure_kind,
    run_design_dna_extraction,
)
from app.services.llm.telemetry import ModelCallTelemetry


class DnaExtractionTestCase(unittest.TestCase):
    def test_task_only_requests_multitag_skill_and_model_schema(self) -> None:
        prompt = _task_text("关注色彩与构成")

        self.assertIn(BOUND_SKILL_NAME, prompt)
        self.assertIn("0～3 个同层风格标签", prompt)
        self.assertIn("精简模型观察 Schema", prompt)
        self.assertIn("统计值、排序、候选镜像、证据闭环与组合预设均由宿主编译", prompt)
        self.assertNotIn("multimodal-design-dna-extractor Skill", prompt)

    def test_uses_multitag_skill_save_pipeline(self) -> None:
        self.assertTrue(SAVE_RESULT_SCRIPT.is_file())
        self.assertTrue(COMPILE_MODEL_OUTPUT_SCRIPT.is_file())
        self.assertIn("multimodal-design-dna-multitag-extractor", SAVE_RESULT_SCRIPT.parts)

    def test_json_patch_updates_only_requested_paths(self) -> None:
        data = {"items": [{"value": 1}], "summary": "old"}

        updated = _apply_json_patch(
            data,
            {
                "updates": [
                    {"op": "replace", "path": "/items/0/value", "value": 2},
                    {"op": "add", "path": "/items/-", "value": {"value": 3}},
                    {"op": "remove", "path": "/summary"},
                ]
            },
        )

        self.assertEqual(data["items"][0]["value"], 1)
        self.assertEqual(updated, {"items": [{"value": 2}, {"value": 3}]})

    def test_validation_failure_is_classified_before_model_repair(self) -> None:
        deterministic = DesignDnaExtractionError(
            "结果未通过校验：\n- quality_summary.mean_confidence=0.5, expected about 0.8"
        )
        semantic = DesignDnaExtractionError(
            "结果未通过校验：\n- style_result.style_tags[0]: core field has no usable evidence"
        )

        self.assertEqual(_validation_failure_kind(deterministic), "deterministic")
        self.assertEqual(_validation_failure_kind(semantic), "semantic")

    def test_transient_stream_disconnect_is_retried_once(self) -> None:
        transient_error = type("APIError", (RuntimeError,), {"__module__": "openai"})
        agent = Mock()
        expected = {"messages": []}
        agent.invoke.side_effect = [
            transient_error("stream disconnected before completion"),
            expected,
        ]
        metrics = {
            "agent_invocation_count": 0,
            "application_network_retry_count": 0,
        }

        result = _invoke_agent(agent, [], ModelCallTelemetry(), metrics)

        self.assertIs(result, expected)
        self.assertEqual(agent.invoke.call_count, 2)
        self.assertEqual(metrics["agent_invocation_count"], 2)
        self.assertEqual(metrics["application_network_retry_count"], 1)

    @patch("app.services.dna.extraction.save_result_trace")
    @patch("app.services.dna.extraction.save_result_image")
    @patch("app.services.dna.extraction.save_business_view_model")
    @patch("app.services.dna.extraction._create_business_view")
    @patch("app.services.dna.extraction._save_validated_result")
    @patch("app.services.dna.extraction._compile_model_result")
    @patch("app.services.dna.extraction.create_design_dna_agent")
    def test_semantic_failure_uses_patch_before_full_fallback(
        self,
        create_agent: Mock,
        compile_result: Mock,
        save_result: Mock,
        create_business_view: Mock,
        _save_model: Mock,
        _save_image: Mock,
        save_trace: Mock,
    ) -> None:
        initial = {"schema_version": "design_dna_multitag_observation_v1", "value": "bad"}
        patched = {"schema_version": "design_dna_multitag_observation_v1", "value": "good"}
        agent = Mock()
        agent.invoke.side_effect = [
            {"messages": [SimpleNamespace(content=json.dumps(initial))]},
            {
                "messages": [
                    SimpleNamespace(
                        content=(
                            '{"updates":[{"op":"replace","path":"/value",'
                            '"value":"good"}]}'
                        )
                    )
                ]
            },
        ]
        create_agent.return_value = agent
        compile_result.side_effect = [
            (
                {"schema_version": "compiled", "value": "bad"},
                {"deterministic_correction_count": 1, "changed_paths": ["/x"]},
            ),
            (
                {"schema_version": "compiled", "value": "good"},
                {"deterministic_correction_count": 0, "changed_paths": []},
            ),
        ]

        with TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "image.png"
            image_path.write_bytes(b"image")
            full_path = Path(temporary_directory) / "result.json"
            business_path = Path(temporary_directory) / "result_business_view.json"
            save_result.side_effect = [
                DesignDnaExtractionError("- style tag lacks usable visual evidence"),
                full_path,
            ]
            create_business_view.return_value = business_path

            output = run_design_dna_extraction(
                image_path,
                "image/png",
                "gpt-5.6-terra-20260820",
                "关注构图",
            )

        self.assertEqual(output.full_result_path, full_path)
        self.assertEqual(agent.invoke.call_count, 2)
        self.assertEqual(compile_result.call_args_list[1].args[0], patched)
        trace = save_trace.call_args.args[1]
        self.assertEqual(trace["execution_metrics"]["agent_invocation_count"], 2)
        self.assertEqual(trace["execution_metrics"]["semantic_patch_attempt_count"], 1)
        self.assertEqual(trace["execution_metrics"]["full_fallback_attempt_count"], 0)


if __name__ == "__main__":
    unittest.main()
