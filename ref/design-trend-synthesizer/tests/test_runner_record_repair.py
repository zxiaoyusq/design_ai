"""宿主逐记录补齐集成测试；假适配器配真实接收/缓存/统计，仅使用临时运行。"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import core
import workflow
from runner import Runner


class ExtractWorkflow:
    """隔离后续趋势阶段调度；所有接收、哈希保护及缓存写入仍使用真实实现。"""
    receive = staticmethod(workflow.receive)

    @staticmethod
    def advance(run, limit=5):
        pending = [{"job_id": job["id"]} for job in core.load_jobs(run) if core.accepted(run, job) is None]
        return {"pending": pending[:limit], "complete": not pending}

    @staticmethod
    def status(run, limit=5):
        jobs = core.load_jobs(run)
        done = sum(core.accepted(run, job) is not None for job in jobs)
        return {"accepted": {"extract": done}, "pending_count": len(jobs) - done}


class Clock:
    def __init__(self):
        self.value = 1000.0
        self.sleeps = []

    def time(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class Adapter:
    def __init__(self, job, events):
        self.job = job
        self.events = deepcopy(events)
        self.calls = []

    def __call__(self, command, request_path, result_path):
        request = core.read(request_path)
        self.calls.append(request)
        if not self.events:
            raise AssertionError("没有授权的额外假模型调用")
        event = self.events.pop(0)
        if "error" in event:
            core.write(result_path, {"status": "error", "category": event["error"], "message": "synthetic transport error"})
            return
        effective = request.get("record_repair", {}).get("job", self.job)
        observations = []
        for record in effective["payload"]["records"]:
            item = {"record_id": record["id"], "dimensions": ["touch"], "stance": "conditional"}
            if record["id"] in event.get("bad", []):
                item["quote"] = "模型改写的虚构引文"
            observations.append(item)
        response = {"job_id": request["job_id"], "observations": observations, "skipped": []}
        if event.get("outside_subset"):
            response["observations"].append({"record_id": "r1", "dimensions": ["color"], "stance": "support"})
        if event.get("null_observations"):
            response["observations"] = None
        raw = json.dumps(response, ensure_ascii=False, indent=2) + "\n"
        core.write(result_path, {"status": "ok", "response": response, "raw_response": raw,
                                 "model": "synthetic-record-model", "model_profile": request["model_profile"],
                                 "input_tokens": 17, "output_tokens": 11})


class RunnerRecordRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-record-repair-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.clock = Clock()

    def fixture(self, count=2):
        run = self.root / "run"
        records = {f"r{index}": {"id": f"r{index}", "kind": "user_qa", "user_id": "u1", "profile": {},
                                  "fields": {"ai_analysis": f"仅在室内喜欢 P{index} 的细腻表面。", "question": "具体适用条件？"}}
                   for index in range(1, count + 1)}
        profile = {"model": "synthetic-record-model", "parameters": {"temperature": 0}}
        core.write(run / "records.json", records)
        core.write(run / "manifest.json", {"skill_version": core.VERSION, "records_sha256": core.digest(records),
                                            "model_profile": profile, "cache": {"enabled": True, "model_profile": profile,
                                                                                  "directory": str(self.root / "cache")}})
        identifier = core.make_job(run, "extract", "fixture", {"records": list(records.values())}, {"max_observations": 64})
        return run, core.read(run / "jobs" / f"{identifier}.json")

    def runner(self, run, adapter, **kwargs):
        return Runner(run, ["synthetic-no-process"], concurrency=1, adapter=adapter,
                      workflow_api=ExtractWorkflow(), clock=self.clock.time, sleep=self.clock.sleep,
                      jitter=lambda: 0, **kwargs)

    def execute(self, runner):
        with redirect_stdout(io.StringIO()):
            return runner.execute()

    def requested_ids(self, request, original_job):
        return [record["id"] for record in request.get("record_repair", {}).get("job", original_job)["payload"]["records"]]

    def assert_usage(self, run, *, attempts, input_tokens, output_tokens, missing=0):
        summary = core.read(run / "runner/summary.json")
        self.assertEqual(summary["usage"], {"input_tokens": input_tokens, "output_tokens": output_tokens, "missing_usage_attempts": missing})
        performance = core.read(run / "performance_report.json")["totals"]
        self.assertEqual(performance["attempt_count"], attempts)
        self.assertEqual(performance["input_tokens_known"], input_tokens)
        self.assertEqual(performance["output_tokens_known"], output_tokens)

    def test_first_failure_only_requests_bad_record_and_compiles_with_honest_receipt(self):
        run, job = self.fixture()
        adapter = Adapter(job, [{"bad": ["r2"]}, {}])
        runner = self.runner(run, adapter)
        self.assertEqual(runner.record_repair_rounds, 2)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual([self.requested_ids(request, job) for request in adapter.calls], [["r1", "r2"], ["r2"]])
        self.assertEqual(adapter.calls[1]["record_repair"]["round"], 1)
        state = runner.job_state(job)
        self.assertEqual((state["validation_failures"], state["record_repair_rounds"]), (1, 1))
        receipt = core.accepted(run, job)
        self.assertEqual([item["record_id"] for item in receipt["response"]["observations"]], ["r1", "r2"])
        execution = receipt["execution"]
        self.assertEqual(execution["mode"], "compiled_record_repair")
        self.assertNotIn("messages_sha256", execution)
        self.assertIn("messages_sha256", execution["last_call"])
        self.assertIsNone(receipt["input_tokens"])
        self.assertIsNone(receipt["output_tokens"])
        self.assertEqual(set(execution["record_repair"]["source_records"]), {"r1"})
        self.assertEqual(list((self.root / "cache").rglob("*.json")), [])
        self.assert_usage(run, attempts=2, input_tokens=34, output_tokens=22)
        folder = run / "runner/attempts" / job["id"] / "0002"
        self.assertEqual([item["record_id"] for item in core.read(folder / "result.raw.json")["response"]["observations"]], ["r2"])
        self.assertEqual([item["record_id"] for item in core.read(folder / "subset_response.json")["observations"]], ["r2"])

    def test_historical_two_failures_resume_only_gap_and_keep_all_prior_failure_bytes(self):
        run, job = self.fixture()
        legacy = Adapter(job, [{"bad": ["r2"]}, {"bad": ["r2"]}])
        self.assertEqual(self.execute(self.runner(run, legacy, record_repair_rounds=0)), 2)
        original_files = {path: path.read_bytes() for path in (run / "runner/attempts").rglob("*") if path.is_file()}
        adapter = Adapter(job, [{}])
        resumed = self.runner(run, adapter)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(self.requested_ids(adapter.calls[0], job), ["r2"])
        state = resumed.job_state(job)
        self.assertEqual(state["validation_failures"], 2)
        self.assertEqual(state["processed_attempts"], 3)
        self.assertEqual(state["record_repair_rounds"], 1)
        for path, before in original_files.items():
            self.assertEqual(path.read_bytes(), before, str(path))
        self.assert_usage(run, attempts=3, input_tokens=51, output_tokens=33)

    def test_second_subset_error_retains_new_good_groups_and_shrinks_next_request(self):
        run, job = self.fixture(3)
        adapter = Adapter(job, [{"bad": ["r2", "r3"]}, {"bad": ["r3"]}, {}])
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual([self.requested_ids(request, job) for request in adapter.calls], [["r1", "r2", "r3"], ["r2", "r3"], ["r3"]])
        self.assertEqual([request["record_repair"]["round"] for request in adapter.calls[1:]], [1, 2])
        trace = core.accepted(run, job)["execution"]["record_repair"]
        self.assertTrue(trace["source_records"]["r1"]["attempt_file"].endswith("0001/request.json"))
        self.assertTrue(trace["source_records"]["r2"]["attempt_file"].endswith("0002/request.json"))
        self.assertEqual(runner.job_state(job)["validation_failures"], 2)
        self.assert_usage(run, attempts=3, input_tokens=51, output_tokens=33)

    def test_transport_retry_freezes_subset_messages_round_and_total_transport_budget(self):
        run, job = self.fixture()
        adapter = Adapter(job, [{"error": "transport"}, {"bad": ["r2"]}, {"error": "timeout"}, {}])
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual(len(adapter.calls), 4)
        self.assertEqual(adapter.calls[0]["messages"], adapter.calls[1]["messages"])
        self.assertEqual(adapter.calls[2]["messages"], adapter.calls[3]["messages"])
        self.assertEqual(adapter.calls[2]["record_repair"], adapter.calls[3]["record_repair"])
        self.assertEqual(adapter.calls[2]["record_repair"]["round"], 1)
        self.assertEqual(runner.job_state(job)["transport_failures"], 2)
        self.assertEqual(runner.job_state(job)["record_repair_rounds"], 1)
        self.assertGreaterEqual(sum(self.clock.sleeps), 6)
        self.assert_usage(run, attempts=4, input_tokens=34, output_tokens=22, missing=2)

    def test_subset_transport_retry_after_restart_keeps_frozen_request_and_round(self):
        run, job = self.fixture()
        original_adapter = Adapter(job, [{"bad": ["r2"]}, {"error": "timeout"}])
        original_runner = self.runner(run, original_adapter)
        for _ in range(2):
            folder = original_runner.prepare_attempt(job)
            original_adapter([], folder / "request.json", folder / "result.raw.json")
            original_runner.finish(job, folder)
        self.assertEqual(original_runner.job_state(job)["record_repair_rounds"], 1)
        self.assertEqual(original_runner.job_state(job)["transport_failures"], 1)
        previous_request = deepcopy(original_adapter.calls[-1])
        original_files = {path: path.read_bytes() for path in (run / "runner/attempts").rglob("*") if path.is_file()}
        resumed_adapter = Adapter(job, [{}])
        resumed = self.runner(run, resumed_adapter)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(len(resumed_adapter.calls), 1)
        self.assertEqual(resumed_adapter.calls[0]["messages"], previous_request["messages"])
        self.assertEqual(resumed_adapter.calls[0]["record_repair"], previous_request["record_repair"])
        self.assertEqual(resumed.job_state(job)["transport_failures"], 1)
        self.assertEqual(resumed.job_state(job)["record_repair_rounds"], 1)
        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content)
        self.assert_usage(run, attempts=3, input_tokens=34, output_tokens=22, missing=1)

    def test_crash_before_round_state_is_saved_recovers_round_from_frozen_request(self):
        run, job = self.fixture()
        original_adapter = Adapter(job, [{"bad": ["r2"]}, {"bad": ["r2"]}])
        original_runner = self.runner(run, original_adapter)
        first = original_runner.prepare_attempt(job)
        original_adapter([], first / "request.json", first / "result.raw.json")
        original_runner.finish(job, first)
        subset = original_runner.prepare_attempt(job)
        original_adapter([], subset / "request.json", subset / "result.raw.json")
        request_path = subset / "request.json"
        request_bytes = request_path.read_bytes()
        self.assertEqual(core.read(request_path)["record_repair"]["round"], 1)
        self.assertFalse((subset / "outcome.json").exists())
        # 模拟请求已持久化，但轮次状态写入丢失；不得改写已冻结的请求来补状态。
        state_path = run / "runner/state.json"
        saved = core.read(state_path)
        saved["jobs"][job["id"]].pop("record_repair_rounds")
        core.write(state_path, saved)
        resumed_adapter = Adapter(job, [{"bad": ["r2"]}])
        resumed = self.runner(run, resumed_adapter)
        self.assertEqual(self.execute(resumed), 2)
        self.assertEqual(len(resumed_adapter.calls), 1)
        self.assertEqual(resumed_adapter.calls[0]["record_repair"]["round"], 2)
        self.assertEqual(resumed.job_state(job)["record_repair_rounds"], 2)
        self.assertEqual(resumed.job_state(job)["validation_failures"], 3)
        self.assertEqual(resumed.job_state(job)["processed_attempts"], 3)
        self.assertEqual(request_path.read_bytes(), request_bytes)
        self.assertEqual(core.read(subset / "outcome.json")["kind"], "validation")
        unused = Adapter(job, [])
        self.assertEqual(self.execute(self.runner(run, unused)), 2)
        self.assertEqual(unused.calls, [])
        self.assert_usage(run, attempts=3, input_tokens=51, output_tokens=33)

    def test_exhausted_repair_rounds_stay_blocked_across_restart_without_extra_attempt(self):
        run, job = self.fixture()
        adapter = Adapter(job, [{"bad": ["r2"]}] * 3)
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 2)
        self.assertEqual(len(adapter.calls), 3)
        self.assertEqual(runner.job_state(job)["record_repair_rounds"], 2)
        self.assertEqual(runner.job_state(job)["validation_failures"], 3)
        before = {path: path.read_bytes() for path in (run / "runner/attempts").rglob("*") if path.is_file()}
        unused = Adapter(job, [])
        self.assertEqual(self.execute(self.runner(run, unused)), 2)
        self.assertEqual(unused.calls, [])
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertIsNone(core.accepted(run, job))
        self.assert_usage(run, attempts=3, input_tokens=51, output_tokens=33)

    def test_transport_exhaustion_does_not_open_another_record_round(self):
        run, job = self.fixture()
        adapter = Adapter(job, [{"bad": ["r2"]}] + [{"error": "timeout"}] * 3)
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 2)
        self.assertEqual(len(adapter.calls), 4)
        self.assertEqual(runner.job_state(job)["transport_failures"], 3)
        self.assertEqual(runner.job_state(job)["record_repair_rounds"], 1)
        unused = Adapter(job, [])
        self.assertEqual(self.execute(self.runner(run, unused)), 2)
        self.assertEqual(unused.calls, [])
        self.assert_usage(run, attempts=4, input_tokens=17, output_tokens=11, missing=3)

    def test_records_outside_subset_invalidate_attempt_instead_of_overwriting_retained_source(self):
        run, job = self.fixture(3)
        adapter = Adapter(job, [{"bad": ["r2", "r3"]}, {"outside_subset": True}, {}])
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual([self.requested_ids(request, job) for request in adapter.calls], [["r1", "r2", "r3"], ["r2", "r3"], ["r2", "r3"]])
        retained_observation = core.accepted(run, job)["response"]["observations"][0]
        self.assertEqual(retained_observation["record_id"], "r1")
        self.assertEqual(retained_observation["dimensions"], ["touch"])
        self.assertEqual(retained_observation["stance"], "conditional")
        self.assertEqual(runner.job_state(job)["validation_failures"], 2)

    def test_null_observation_array_is_bounded_validation_failure_without_runner_crash(self):
        run, job = self.fixture()
        adapter = Adapter(job, [{"null_observations": True}] * 2)
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 2)
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(runner.job_state(job)["validation_failures"], 2)
        self.assertNotIn("record_repair_rounds", runner.job_state(job))
        self.assertIsNone(core.accepted(run, job))


if __name__ == "__main__":
    unittest.main()
