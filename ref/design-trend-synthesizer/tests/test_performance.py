"""用手工计时样本验证性能统计，不调用模型或访问网络。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("trend_performance", SCRIPTS / "performance.py")
performance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(performance)


def moment(seconds):
    return (datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="trend-performance-offline-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name).resolve()

    def write(self, relative, value):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def old(self, job, attempt, stage, seconds, *, start=0, status="valid", **extra):
        value = {"job_id": job, "stage": stage, "status": status, "started_at": moment(start),
                 "finished_at": moment(start + seconds), "elapsed_seconds": seconds,
                 "model": "synthetic-test-model", "usage": {"input_tokens": 100, "output_tokens": 10}, **extra}
        return self.write(f"host/attempts/{job}/attempt-{attempt:02d}/result.json", value)

    def new(self, job, attempt, stage, start, finish, *, kind="valid", **extra):
        self.write(f"jobs/{job}.json", {"id": job, "stage": stage})
        self.write(f"runner/attempts/{job}/{attempt:04d}/request.json", {
            "job_id": job, "started_at": moment(start),
            "model_profile": {"model": "synthetic-test-model", "parameters": {}},
        })
        value = {"kind": kind, "finished_at": moment(finish), "input_tokens": 200,
                 "output_tokens": 20, "model": "synthetic-test-model", **extra}
        return self.write(f"runner/attempts/{job}/{attempt:04d}/outcome.json", value)

    def test_parallel_calls_retries_percentiles_and_distinct_rankings(self):
        # 四个并发提取调用耗时 10/20/30/40 秒，共 100 秒；单次候选 60 秒。
        for index, duration in enumerate((10, 20, 30, 40), 1):
            self.old("extract-shared-job", index, "extract", duration,
                     status="failed" if duration == 40 else "valid")
        self.new("propose-a", 1, "propose", 5, 65, kind="timeout")
        self.write("accepted/cached-job.json", {"model": "synthetic-test-model", "execution": {"cache_sources": [{"key": "cached"}]}})
        self.write("jobs/not-called.json", {"id": "not-called", "stage": "draft"})
        report = performance.summarize_performance(self.run)
        totals, extract, propose = report["totals"], report["stages"]["extract"], report["stages"]["propose"]
        self.assertEqual(totals["attempt_count"], 5)
        self.assertEqual((totals["valid_count"], totals["failure_count"]), (3, 2))
        self.assertEqual(extract["attempt_count"], 4)
        self.assertEqual(extract["p50_seconds"], 25)
        self.assertAlmostEqual(extract["p95_seconds"], 38.5)
        self.assertEqual(extract["mean_seconds"], 25)
        self.assertEqual(extract["max_seconds"], 40)
        self.assertEqual(propose["p50_seconds"], 60)
        self.assertEqual(report["slowest_single_call_stage"], "propose")
        self.assertEqual(report["largest_total_call_stage"], "extract")
        self.assertEqual(totals["sum_call_seconds"], 160)
        self.assertEqual(totals["failed_call_seconds"], 100)
        self.assertEqual(report["observed_wall_span_seconds"], 65)
        self.assertEqual((totals["input_tokens_known"], totals["output_tokens_known"]), (600, 60))
        self.assertEqual(totals["missing_usage_count"], 0)
        self.assertNotIn("draft", report["stages"])

    def test_incomplete_and_missing_duration_are_separate_not_zero_filled(self):
        self.old("known-time", 1, "extract", 20, elapsed_seconds=None,
                 usage={"input_tokens": 0, "output_tokens": 0})
        self.old("missing-time", 1, "extract", 1, started_at=None, finished_at=None,
                 elapsed_seconds=None, usage={})
        self.old("reversed-time", 1, "extract", 1, started_at=moment(4), finished_at=moment(3),
                 elapsed_seconds=-1, status="failed", usage={"input_tokens": None, "output_tokens": None})
        self.old("in-flight-old", 1, "extract", 100, status="running", finished_at=None)
        self.write("jobs/in-flight-new.json", {"id": "in-flight-new", "stage": "extract"})
        self.write("runner/attempts/in-flight-new/0001/request.json", {"started_at": moment(5)})
        stage = performance.summarize_performance(self.run)["stages"]["extract"]
        self.assertEqual(stage["attempt_count"], 3)
        self.assertEqual(stage["incomplete_count"], 2)
        self.assertEqual(stage["missing_duration_count"], 2)
        self.assertEqual(stage["missing_timestamp_count"], 2)
        self.assertEqual(stage["duration_sample_count"], 1)
        self.assertEqual((stage["p50_seconds"], stage["p95_seconds"], stage["mean_seconds"]), (20, 20, 20))
        self.assertEqual(stage["sum_call_seconds"], 20)
        self.assertIsNone(stage["failed_call_seconds"])
        self.assertEqual(stage["missing_usage_count"], 2)
        self.assertEqual((stage["input_tokens_known"], stage["input_usage_count"]), (0, 1))

    def test_entirely_missing_time_does_not_enter_slowest_rankings(self):
        self.old("missing", 1, "audit", 1, started_at=None, finished_at=None, elapsed_seconds=None)
        report = performance.summarize_performance(self.run)
        self.assertEqual(report["totals"]["attempt_count"], 1)
        self.assertIsNone(report["totals"]["sum_call_seconds"])
        self.assertIsNone(report["slowest_single_call_stage"])
        self.assertIsNone(report["largest_total_call_stage"])
        self.assertIsNone(report["observed_wall_span_seconds"])

    def test_elapsed_measurement_and_wall_clock_pause_are_not_confused(self):
        self.old("first", 1, "extract", 10, finished_at=moment(50))
        self.new("after-pause", 1, "draft", 3600, 3620)
        report = performance.summarize_performance(self.run)
        self.assertEqual(report["totals"]["sum_call_seconds"], 30)
        self.assertEqual(report["observed_wall_span_seconds"], 3620)
        self.assertEqual(report["stages"]["extract"]["observed_wall_span_seconds"], 50)

    def test_524_error_body_does_not_turn_into_overload_classification(self):
        self.old("old-timeout", 1, "propose", 30, status="failed",
                 error="HTTP 524 origin timeout: overloaded appears only inside the provider response body")
        self.new("new-timeout", 1, "propose", 0, 20, kind="timeout",
                 error="HTTP 524 payload includes overloaded")
        stage = performance.summarize_performance(self.run)["stages"]["propose"]
        self.assertEqual(stage["failure_count"], 2)
        self.assertEqual(stage["failure_kinds"], {"failed": 1, "timeout": 1})
        self.assertNotIn("overload", stage["failure_kinds"])

    def test_malformed_log_is_diagnostic_and_does_not_claim_zero_second_failure(self):
        path = self.write("runner/attempts/broken/0001/outcome.json", {})
        path.write_text('{"kind":')
        self.write("jobs/broken.json", {"stage": "review"})
        report = performance.summarize_performance(self.run)
        self.assertEqual(report["totals"]["attempt_count"], 0)
        self.assertEqual(report["totals"]["incomplete_count"], 1)
        self.assertEqual(len(report["diagnostics"]), 1)
        self.assertEqual(report["totals"]["failure_count"], 0)
        self.assertIsNone(report["stages"]["review"]["mean_seconds"])

    def test_readonly_function_and_explicit_cli_write(self):
        self.old("one-call", 1, "extract", 12)
        before = {str(path.relative_to(self.run)): path.read_bytes() for path in self.run.rglob("*") if path.is_file()}
        report = performance.summarize_performance(self.run)
        after = {str(path.relative_to(self.run)): path.read_bytes() for path in self.run.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.run / "performance_report.json").exists())
        completed = subprocess.run([sys.executable, str(SCRIPTS / "performance.py"), "--run", str(self.run)], capture_output=True, text=True, check=True)
        written = json.loads((self.run / "performance_report.json").read_text())
        self.assertEqual(written["totals"], report["totals"])
        self.assertEqual(json.loads(completed.stdout)["report_file"], str(self.run / "performance_report.json"))

    def test_empty_run_has_no_called_stage(self):
        report = performance.summarize_performance(self.run)
        self.assertEqual(report["stages"], {})
        self.assertEqual(report["totals"]["attempt_count"], 0)
        self.assertEqual(report["totals"]["sum_call_seconds"], 0)
        self.assertIsNone(report["observed_wall_span_seconds"])


if __name__ == "__main__":
    unittest.main()
