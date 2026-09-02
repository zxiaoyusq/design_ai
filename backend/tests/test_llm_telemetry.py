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


if __name__ == "__main__":
    unittest.main()
