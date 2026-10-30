"""模型调用可观测性采集测试。"""

import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.llm.telemetry import ModelCallTelemetry


class ModelCallTelemetryTestCase(unittest.TestCase):
    def test_counts_requests_and_usage_metadata(self) -> None:
        telemetry = ModelCallTelemetry()
        run_id = uuid4()
        telemetry.on_chat_model_start({}, [[]], run_id=run_id)
        telemetry.on_llm_end(
            SimpleNamespace(
                generations=[
                    [
                        SimpleNamespace(
                            message=SimpleNamespace(
                                usage_metadata={
                                    "input_tokens": 120,
                                    "output_tokens": 30,
                                    "total_tokens": 150,
                                }
                            )
                        )
                    ]
                ],
                llm_output=None,
            ),
            run_id=run_id,
        )

        self.assertEqual(
            telemetry.snapshot(),
            {
                "llm_request_count": 1,
                "llm_success_count": 1,
                "llm_error_count": 0,
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "requests_with_usage": 1,
                "usage_complete": True,
            },
        )

    def test_reports_safe_request_lifecycle_events(self) -> None:
        events: list[tuple[str, int]] = []
        telemetry = ModelCallTelemetry(
            on_event=lambda event, count: events.append((event, count))
        )
        run_id = uuid4()

        telemetry.on_chat_model_start({}, [[]], run_id=run_id)
        telemetry.on_llm_error(RuntimeError("timeout"), run_id=run_id)

        self.assertEqual(
            events,
            [("request_started", 1), ("request_failed", 1)],
        )

    def test_missing_or_invalid_usage_is_not_counted_as_complete_zero(self) -> None:
        for usage in ({}, {"input_tokens": 10}, {"total_tokens": 15},
                      {"input_tokens": -1, "output_tokens": 2},
                      {"input_tokens": True, "output_tokens": 2},
                      {"input_tokens": 1, "output_tokens": 2, "total_tokens": False}):
            with self.subTest(usage=usage):
                telemetry = ModelCallTelemetry()
                telemetry.on_llm_end(SimpleNamespace(llm_output={"usage": usage}), run_id=uuid4())
                self.assertFalse(telemetry.snapshot()["usage_complete"])
                self.assertEqual(telemetry.snapshot()["requests_with_usage"], 0)

    def test_empty_message_usage_falls_back_to_provider_tokens(self) -> None:
        telemetry = ModelCallTelemetry()
        telemetry.on_llm_end(SimpleNamespace(
            generations=[[SimpleNamespace(message=SimpleNamespace(usage_metadata={}))]],
            llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ), run_id=uuid4())
        self.assertEqual(telemetry.snapshot()["total_tokens"], 15)
        self.assertTrue(telemetry.snapshot()["usage_complete"])
        self.assertEqual(ModelCallTelemetry._normalize_usage({"input_tokens": 0, "output_tokens": 0}),
                         (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
