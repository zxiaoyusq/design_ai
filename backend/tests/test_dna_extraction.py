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
    _safely_degrade_invalid_observations,
    _task_text,
    _validation_failure_kind,
    _validation_issues,
    run_design_dna_extraction,
)
from app.services.llm.telemetry import ModelCallTelemetry


class DnaExtractionTestCase(unittest.TestCase):
    def test_task_only_requests_multitag_skill_and_model_schema(self) -> None:
        prompt = _task_text("关注色彩与构成")

        self.assertIn(BOUND_SKILL_NAME, prompt)
        self.assertIn("0～5 个真实同层风格候选", prompt)
        self.assertIn("精简模型观察 Schema", prompt)
        self.assertIn("统计值、排序与组合预设均由宿主编译", prompt)
        self.assertIn("不输出确认、未分类", prompt)
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

    def test_validation_issue_uses_compiler_source_map(self) -> None:
        error = DesignDnaExtractionError(
            "结果未通过校验：\n"
            "- style_result.style_candidates[0]: candidate requires at least one visible support item"
        )

        issues = _validation_issues(
            error,
            {
                "source_map": {
                    "style_result.style_candidates[0]": {
                        "source_pointer": "/style_observations/candidate_tags/1",
                        "style_id": "NeoRetro",
                    }
                }
            },
        )

        self.assertEqual(issues[0]["code"], "SEMANTIC_VALIDATION_FAILED")
        self.assertEqual(issues[0]["repair_owner"], "model")
        self.assertEqual(
            issues[0]["source_pointer"],
            "/style_observations/candidate_tags/1",
        )
        self.assertEqual(issues[0]["style_id"], "NeoRetro")

    def test_evidence_region_issue_has_compact_path_and_source(self) -> None:
        error = DesignDnaExtractionError(
            "结果未通过校验：\n"
            "- evidence[2].region='wheel_contact' is outside "
            "target_object.visible_regions"
        )

        issues = _validation_issues(
            error,
            {
                "source_map": {
                    "evidence[2]": {
                        "source_pointer": "/evidence/2",
                        "evidence_id": "EV-03",
                        "region": "wheel_contact",
                    }
                }
            },
        )

        self.assertEqual(issues[0]["code"], "REGION_NOT_DECLARED")
        self.assertEqual(issues[0]["final_path"], "evidence[2].region")
        self.assertEqual(issues[0]["source_pointer"], "/evidence/2")
        self.assertEqual(issues[0]["evidence_id"], "EV-03")

    def test_nested_schema_issue_maps_to_lean_observation(self) -> None:
        error = DesignDnaExtractionError(
            "结果未通过校验：\n"
            "- schema design_elements.extended_dna_modules.9.elements.0."
            "evidence_refs: ['EV-06'] is too short"
        )

        issues = _validation_issues(
            error,
            {
                "source_map": {
                    "design_elements.extended_dna_modules.9.elements.0": {
                        "source_pointer": "/design_observations/38",
                        "field_id": "IMG-08",
                        "region": "whole_object",
                    }
                }
            },
        )

        self.assertEqual(issues[0]["code"], "FINAL_SCHEMA_INVALID")
        self.assertEqual(
            issues[0]["final_path"],
            "design_elements.extended_dna_modules.9.elements.0.evidence_refs",
        )
        self.assertEqual(issues[0]["source_pointer"], "/design_observations/38")
        self.assertEqual(issues[0]["field_id"], "IMG-08")

    def test_safe_degradation_removes_field_and_invalid_candidate(self) -> None:
        observation = {
            "design_observations": [{"field_id": "PRT-08"}],
            "uncertainties": [],
            "style_observations": {
                "candidate_tags": [
                    {
                        "style_id": "NeoRetro",
                        "match_score": 80,
                        "confidence": 0.82,
                        "regions": ["whole_object"],
                        "main_support": ["复古组件与配色可见"],
                        "main_conflicts": [],
                    }
                ],
                "composition_summary": "复古构成。",
            },
        }
        issues = [
            {
                "source_pointer": "/design_observations/0",
                "message": "字段值域不明确",
            },
            {
                "source_pointer": "/style_observations/candidate_tags/0",
                "message": "风格候选缺少有效支持",
            },
        ]

        degraded, count = _safely_degrade_invalid_observations(observation, issues)

        self.assertEqual(count, 2)
        self.assertEqual(degraded["design_observations"], [])
        style = degraded["style_observations"]
        self.assertEqual(style["candidate_tags"], [])

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

    @patch("app.services.dna.extraction.save_result_trace")
    @patch("app.services.dna.extraction.save_result_image")
    @patch("app.services.dna.extraction.save_business_view_model")
    @patch("app.services.dna.extraction._create_business_view")
    @patch("app.services.dna.extraction._save_validated_result")
    @patch("app.services.dna.extraction._compile_model_result")
    @patch("app.services.dna.extraction.create_design_dna_agent")
    def test_invalid_patch_path_keeps_original_issue_for_safe_degradation(
        self,
        create_agent: Mock,
        compile_result: Mock,
        save_result: Mock,
        create_business_view: Mock,
        _save_model: Mock,
        _save_image: Mock,
        save_trace: Mock,
    ) -> None:
        observation = {
            "schema_version": "design_dna_multitag_observation_v1",
            "design_observations": [
                {
                    "field_id": "IMG-08",
                    "confidence": 0.65,
                    "evidence_refs": ["EV-06"],
                }
            ],
            "uncertainties": [],
        }
        invalid_final_path = (
            "/design_elements/extended_dna_modules/9/elements/0/evidence_refs"
        )
        agent = Mock()
        agent.invoke.side_effect = [
            {"messages": [SimpleNamespace(content=json.dumps(observation))]},
            {
                "messages": [
                    SimpleNamespace(
                        content=json.dumps(
                            {
                                "updates": [
                                    {
                                        "op": "replace",
                                        "path": invalid_final_path,
                                        "value": ["EV-06", "EV-05"],
                                    }
                                ]
                            }
                        )
                    )
                ]
            },
        ]
        create_agent.return_value = agent
        source_map = {
            "design_elements.extended_dna_modules.9.elements.0": {
                "source_pointer": "/design_observations/0",
                "field_id": "IMG-08",
                "region": "whole_object",
            }
        }
        compiled_invalid = {
            "schema_version": "compiled",
            "design_elements": {
                "extended_dna_modules": [
                    {
                        "module_id": "DNA-M14",
                        "elements": [{"field_id": "IMG-08"}],
                    }
                ]
            },
        }
        compiled_valid = {
            "schema_version": "compiled",
            "design_elements": {"extended_dna_modules": []},
        }
        compile_result.side_effect = [
            (
                compiled_invalid,
                {
                    "deterministic_correction_count": 1,
                    "changed_paths": ["/design_elements"],
                    "source_map": source_map,
                },
            ),
            (
                compiled_valid,
                {
                    "deterministic_correction_count": 1,
                    "changed_paths": ["/design_elements"],
                    "source_map": {},
                },
            ),
        ]

        with TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "image.png"
            image_path.write_bytes(b"image")
            full_path = Path(temporary_directory) / "result.json"
            business_path = Path(temporary_directory) / "result_business_view.json"
            save_result.side_effect = [
                DesignDnaExtractionError(
                    "结果未通过校验：\n"
                    "- schema design_elements.extended_dna_modules.9.elements.0."
                    "evidence_refs: ['EV-06'] is too short"
                ),
                full_path,
            ]
            create_business_view.return_value = business_path

            output = run_design_dna_extraction(
                image_path,
                "image/png",
                "claude-opus-5-20260820",
                "",
            )

        self.assertEqual(output.full_result_path, full_path)
        self.assertEqual(agent.invoke.call_count, 2)
        second_prompt = agent.invoke.call_args_list[1].args[0]["messages"][-1][
            "content"
        ]
        self.assertIn('"source_pointer": "/design_observations/0"', second_prompt)
        self.assertIn("禁止使用 final_path", second_prompt)
        self.assertEqual(
            compile_result.call_args_list[1].args[0]["design_observations"],
            [],
        )
        trace = save_trace.call_args.args[1]
        self.assertEqual(trace["execution_metrics"]["safe_degradation_count"], 1)
        self.assertIn(
            "修复补丁路径不存在",
            trace["execution_metrics"]["validation_failure_summaries"][1],
        )

    @patch("app.services.dna.extraction.save_result_trace")
    @patch("app.services.dna.extraction.save_result_image")
    @patch("app.services.dna.extraction.save_business_view_model")
    @patch("app.services.dna.extraction._create_business_view")
    @patch("app.services.dna.extraction._save_validated_result")
    @patch("app.services.dna.extraction._compile_model_result")
    @patch("app.services.dna.extraction.create_style_semantic_review_agent")
    @patch("app.services.dna.extraction.create_design_dna_agent")
    def test_candidate_flow_does_not_run_confirmed_style_review(
        self,
        create_agent: Mock,
        create_review_agent: Mock,
        compile_result: Mock,
        save_result: Mock,
        create_business_view: Mock,
        _save_model: Mock,
        _save_image: Mock,
        save_trace: Mock,
    ) -> None:
        observation = {
            "schema_version": "design_dna_multitag_observation_v2",
            "style_observations": {
                "candidate_tags": [
                    {
                        "style_id": "RefinedMinimalism",
                        "match_score": 82,
                        "confidence": 0.84,
                        "regions": ["whole_object"],
                        "main_support": ["规整留白与克制细节"],
                        "main_conflicts": [],
                    }
                ],
                "composition_summary": "规整留白形成克制候选。",
            },
        }
        review_request = {
            "style_id": "RefinedMinimalism",
            "missing_roles": ["auxiliary", "core"],
            "current_core_field_ids": [],
            "current_auxiliary_field_ids": [],
            "roles": {
                "core": [
                    {
                        "field_id": "DEV-03",
                        "field_name": "镜头排列",
                        "decision_use": "hard",
                        "value": "纵",
                        "raw_visual_description": "镜头纵向规整排列。",
                        "region": "camera_island",
                        "confidence": 0.9,
                        "evidence_refs": ["EV-01"],
                    }
                ],
                "auxiliary": [
                    {
                        "field_id": "CMP-09",
                        "field_name": "留白比例",
                        "decision_use": "hard",
                        "value": 0.64,
                        "raw_visual_description": "主体表面保留大面积留白。",
                        "region": "whole_object",
                        "confidence": 0.86,
                        "evidence_refs": ["EV-02"],
                    }
                ],
            },
            "downgrade_reasons": ["缺少决定与辅助证据"],
        }
        main_agent = Mock()
        main_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content=json.dumps(observation))]
        }
        review_agent = Mock()
        review_agent.invoke.return_value = {
            "messages": [
                SimpleNamespace(
                    content=json.dumps(
                        {
                            "decisions": [
                                {
                                    "style_id": "RefinedMinimalism",
                                    "role": "core",
                                    "field_ids": ["DEV-03"],
                                    "supports": True,
                                    "confidence": 0.9,
                                    "reason": "支持受控精致增量。",
                                },
                                {
                                    "style_id": "RefinedMinimalism",
                                    "role": "auxiliary",
                                    "field_ids": ["CMP-09"],
                                    "supports": True,
                                    "confidence": 0.88,
                                    "reason": "支持低信息构图。",
                                },
                            ]
                        }
                    )
                )
            ]
        }
        create_agent.return_value = main_agent
        create_review_agent.return_value = review_agent
        compile_result.side_effect = [
            (
                {
                    "schema_version": "compiled",
                    "style_result": {"style_candidates": []},
                },
                {
                    "deterministic_correction_count": 1,
                    "changed_paths": ["/style_result"],
                    "semantic_review_requests": [review_request],
                },
            ),
            (
                {
                    "schema_version": "compiled",
                    "style_result": {
                        "style_tags": [{"style_id": "RefinedMinimalism"}]
                    },
                },
                {"deterministic_correction_count": 0, "changed_paths": []},
            ),
        ]

        with TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "image.png"
            image_path.write_bytes(b"image")
            full_path = Path(temporary_directory) / "result.json"
            business_path = Path(temporary_directory) / "result_business_view.json"
            save_result.return_value = full_path
            create_business_view.return_value = business_path

            progress_events = []
            output = run_design_dna_extraction(
                image_path,
                "image/png",
                "gpt-5.6-terra-20260820",
                "关注构图",
                progress_callback=lambda stage, message, progress, level: (
                    progress_events.append((stage, message, progress, level))
                ),
            )

        self.assertEqual(output.full_result_path, full_path)
        self.assertEqual(main_agent.invoke.call_count, 1)
        self.assertEqual(review_agent.invoke.call_count, 0)
        self.assertEqual(compile_result.call_count, 1)
        metrics = save_trace.call_args.args[1]["execution_metrics"]
        self.assertEqual(metrics["agent_invocation_count"], 1)
        self.assertEqual(metrics["style_semantic_review_agent_invocation_count"], 0)
        self.assertEqual(metrics["style_semantic_review_accepted_count"], 0)
        self.assertEqual(metrics["style_semantic_review_recovered_style_count"], 0)
        stages = [event[0].value for event in progress_events]
        self.assertIn("model_analysis", stages)
        self.assertIn("compiling", stages)
        self.assertNotIn("semantic_review", stages)
        self.assertIn("validating", stages)
        self.assertIn("generating_view", stages)
        self.assertIn("finalizing", stages)


if __name__ == "__main__":
    unittest.main()
