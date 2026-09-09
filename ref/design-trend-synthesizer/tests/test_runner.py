"""假适配器与假时钟验证宿主生命周期；不访问网络或真实模型。"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import core
from runner import Runner, invoke_adapter, run_lock


class Clock:
    def __init__(self):
        self.value = 1000.0
        self.sleeps = []

    def time(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class Workflow:
    def __init__(self, run):
        self.run = run
        self.thread = threading.get_ident()
        self.received = []

    def advance(self, run, limit=5):
        assert threading.get_ident() == self.thread
        pending = [{"job_id": path.stem} for path in sorted((run / "jobs").glob("*.json"))
                   if not (run / "accepted" / path.name).exists()]
        return {"pending": pending[:limit], "complete": not pending}

    def receive(self, run, job_id, response_path, model, input_tokens, output_tokens, *, execution):
        assert threading.get_ident() == self.thread
        self.received.append((job_id, execution))
        core.write(run / "accepted" / f"{job_id}.json", core.read(response_path))

    def status(self, run, limit=5):
        return {"accepted": {"extract": len(list((run / "accepted").glob("*.json")))},
                "pending_count": len(self.advance(run, 100000)["pending"])}


class Adapter:
    def __init__(self, events=None):
        self.events = events or {}
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, command, request_path, result_path):
        request = core.read(request_path)
        with self.lock:
            self.calls.append(request)
            queue = self.events.get(request["job_id"], [])
            event = queue.pop(0) if queue else "valid"
        if isinstance(event, Exception):
            raise event
        if event == "valid":
            response = {"job_id": request["job_id"], "observations": [],
                        "skipped": [{"record_id": "r1", "status": "not_design", "reason": "天气描述不构成设计偏好。"}]}
            envelope = {"status": "ok", "response": response, "model": "actual-model",
                        "model_profile": request["model_profile"], "input_tokens": 10, "output_tokens": 5}
        elif event == "invalid":
            envelope = {"status": "ok", "response": None, "raw_response": "{invalid exact text\n",
                        "model": "actual-model", "model_profile": request["model_profile"]}
        else:
            envelope = event
        core.write(result_path, envelope)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run = Path(self.temporary.name) / "run with spaces"
        self.run.mkdir()
        self.profile = {"model": "requested-model", "parameters": {"temperature": 0}}
        core.write(self.run / "manifest.json", {"skill_version": core.VERSION, "model_profile": self.profile})
        self.clock = Clock()
        self.workflow = Workflow(self.run)

    def tearDown(self):
        self.temporary.cleanup()

    def job(self, identifier="extract-one"):
        job = {"id": identifier, "stage": "extract", "skill_version": core.VERSION,
               "prompt_version": f"{core.VERSION}:extract", "limits": {"max_observations": 24},
               "payload": {"records": [{"id": "r1", "kind": "user_qa", "fields": {"ai_analysis": "天气晴朗。"}}]}}
        core.write(self.run / "jobs" / f"{identifier}.json", job)
        core.write(self.run / "requests" / f"{identifier}.json", {
            "job_sha256": core.digest(job), "messages": [{"role": "user", "content": "输入数据：$(touch SHOULD_NOT_EXIST); `whoami`"}]})
        return job

    def runner(self, adapter, **kwargs):
        return Runner(self.run, ["explicit-adapter"], adapter=adapter, clock=self.clock.time,
                      sleep=self.clock.sleep, jitter=lambda: 0.25, workflow_api=self.workflow, **kwargs)

    def execute(self, runner):
        with redirect_stdout(io.StringIO()):
            return runner.execute()

    def error(self, category, **kwargs):
        return {"status": "error", "category": category, "message": "synthetic error", **kwargs}

    def test_rate_limit_respects_retry_after_and_reduces_concurrency(self):
        self.job()
        adapter = Adapter({"extract-one": [self.error("rate_limit", retry_after_seconds=12), "valid"]})
        runner = self.runner(adapter, concurrency=4)
        self.assertEqual(self.execute(runner), 0)
        self.assertGreaterEqual(sum(self.clock.sleeps), 12)
        self.assertEqual(runner.state["current_concurrency"], 2)
        self.assertEqual(len(adapter.calls), 2)

    def test_transport_and_validation_budgets_are_independent(self):
        self.job()
        adapter = Adapter({"extract-one": [self.error("transport"), "invalid", self.error("timeout"), "valid"]})
        runner = self.runner(adapter)
        self.assertEqual(self.execute(runner), 0)
        state = runner.state["jobs"]["extract-one"]
        self.assertEqual((state["transport_failures"], state["validation_failures"]), (2, 1))
        self.assertEqual(len(adapter.calls), 4)
        # 传输重试复用同一组修正消息，不叠加第二轮“修 JSON”。
        self.assertEqual(adapter.calls[2]["messages"], adapter.calls[3]["messages"])
        self.assertEqual(adapter.calls[2]["messages"][-2], {"role": "assistant", "content": "{invalid exact text\n"})

    def test_two_validation_failures_block_and_resume_does_not_retry(self):
        self.job()
        adapter = Adapter({"extract-one": ["invalid", "invalid"]})
        self.assertEqual(self.execute(self.runner(adapter)), 2)
        self.assertEqual(len(adapter.calls), 2)
        unused = Adapter()
        self.assertEqual(self.execute(self.runner(unused)), 2)
        self.assertEqual(unused.calls, [])

    def test_repair_collects_observation_errors_and_transport_reuses_same_feedback(self):
        job = self.job()
        response = {"job_id": job["id"], "observations": [
            {"record_id": "r1", "dimensions": ["color"], "stance": "support", "quote": "不存在的引用甲"},
            {"record_id": "r1", "dimensions": ["form"], "stance": "counter", "quote": "不存在的引用乙"},
        ], "skipped": []}
        envelope = {"status": "ok", "response": response, "model": "actual-model",
                    "model_profile": self.profile, "input_tokens": 10, "output_tokens": 5}
        adapter = Adapter({job["id"]: [envelope, self.error("transport"), "valid"]})
        runner = self.runner(adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual(len(adapter.calls), 3)
        feedback = adapter.calls[1]["messages"][-1]["content"]
        self.assertIn("observations[0]", feedback)
        self.assertIn("observations[1]", feedback)
        from extract_transport import record_aliases
        self.assertIn(next(iter(record_aliases(job))), feedback)
        self.assertEqual(adapter.calls[1]["messages"], adapter.calls[2]["messages"])
        self.assertEqual(adapter.calls[1]["messages"][-2]["content"], core.encode(response))
        outcome = core.read(self.run / "runner/attempts" / job["id"] / "0001/outcome.json")
        self.assertNotIn("observations[1]", outcome["error"])
        self.assertIn("observations[1]", outcome["repair_feedback"])
        state = runner.state["jobs"][job["id"]]
        self.assertEqual((state["validation_failures"], state["transport_failures"]), (1, 1))

    def test_three_transport_failures_exhaust_budget(self):
        self.job()
        adapter = Adapter({"extract-one": [self.error("transport")] * 3})
        runner = self.runner(adapter)
        self.assertEqual(self.execute(runner), 2)
        self.assertEqual(len(adapter.calls), 3)
        self.assertGreaterEqual(sum(self.clock.sleeps), 2.25 + 4.25)

    def test_three_consecutive_overloads_latch_cooldown_and_stop_dispatch(self):
        self.job("extract-a")
        self.job("extract-b")
        adapter = Adapter({"extract-a": [self.error("overload", retry_after_seconds=40)] * 3})
        runner = self.runner(adapter, concurrency=1, max_jobs=1)
        self.assertEqual(self.execute(runner), 3)
        self.assertEqual(runner.state["status"], "cooldown")
        self.assertGreater(runner.state["cooldown_until"], self.clock.time())
        self.assertEqual({call["job_id"] for call in adapter.calls}, {"extract-a"})
        unused = Adapter()
        self.assertEqual(self.execute(self.runner(unused)), 3)
        self.assertEqual(unused.calls, [])

    def test_permanent_and_unknown_failures_do_not_block_independent_job(self):
        for category in ("permanent", "unknown-provider-error"):
            with self.subTest(category=category):
                self.job("extract-" + category)
        self.job("extract-valid")
        adapter = Adapter({"extract-" + category: [self.error(category)] for category in
                           ("permanent", "unknown-provider-error")})
        self.assertEqual(self.execute(self.runner(adapter)), 2)
        self.assertEqual(len(adapter.calls), 3)
        self.assertTrue((self.run / "accepted/extract-valid.json").exists())

    def test_authentication_stops_new_dispatch(self):
        self.job("extract-a")
        self.job("extract-b")
        adapter = Adapter({"extract-a": [self.error("authentication")]})
        runner = self.runner(adapter, concurrency=1)
        self.assertEqual(self.execute(runner), 2)
        self.assertEqual(runner.state["status"], "authentication_error")
        self.assertEqual(len(adapter.calls), 1)

    def test_unknown_adapter_exception_is_not_retried(self):
        self.job()
        adapter = Adapter({"extract-one": [RuntimeError("unexpected")]})
        self.assertEqual(self.execute(self.runner(adapter)), 2)
        self.assertEqual(len(adapter.calls), 1)

    def test_valid_result_recovery_never_calls_adapter_again(self):
        job = self.job()
        adapter = Adapter()
        runner = self.runner(adapter)
        folder = runner.prepare_attempt(job)
        adapter([], folder / "request.json", folder / "result.raw.json")
        outcome = runner.classify(job, folder)
        core.write(folder / "outcome.json", outcome)
        runner.apply_outcome(job, folder, outcome)
        unused = Adapter()
        self.assertEqual(self.execute(self.runner(unused)), 0)
        self.assertEqual(unused.calls, [])
        self.assertEqual(len(self.workflow.received), 1)

    def test_raw_result_written_before_crash_is_recovered(self):
        job = self.job()
        runner = self.runner(Adapter())
        folder = runner.prepare_attempt(job)
        Adapter()([], folder / "request.json", folder / "result.raw.json")
        unused = Adapter()
        self.assertEqual(self.execute(self.runner(unused)), 0)
        self.assertEqual(unused.calls, [])

    def test_valid_recovery_skips_older_failed_attempt(self):
        job = self.job()
        adapter = Adapter({"extract-one": ["invalid", "valid"]})
        runner = self.runner(adapter)
        folder = runner.prepare_attempt(job)
        adapter([], folder / "request.json", folder / "result.raw.json")
        runner.finish(job, folder)
        folder = runner.prepare_attempt(job)
        adapter([], folder / "request.json", folder / "result.raw.json")
        outcome = runner.classify(job, folder)
        core.write(folder / "outcome.json", outcome)
        runner.apply_outcome(job, folder, outcome)
        unused = Adapter()
        self.assertEqual(self.execute(self.runner(unused)), 0)
        self.assertEqual(unused.calls, [])

    def test_interrupted_attempt_consumes_transport_budget(self):
        job = self.job()
        runner = self.runner(Adapter())
        runner.prepare_attempt(job)
        adapter = Adapter()
        resumed = self.runner(adapter)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(resumed.state["jobs"][job["id"]]["transport_failures"], 1)
        self.assertEqual(len(adapter.calls), 1)

    def test_serial_receive_and_execution_trace(self):
        for index in range(5):
            self.job(f"extract-{index}")
        self.assertEqual(self.execute(self.runner(Adapter(), concurrency=4)), 0)
        self.assertEqual(len(self.workflow.received), 5)
        for job_id, execution in self.workflow.received:
            request = core.read(self.run / execution["attempt_file"])
            self.assertEqual(execution["messages_sha256"], core.digest(request["messages"]))
            self.assertEqual(execution["model_profile"], self.profile)

    def test_max_jobs_and_interrupt_never_report_complete(self):
        self.job("extract-a")
        self.job("extract-b")
        runner = self.runner(Adapter(), max_jobs=1)
        self.assertEqual(self.execute(runner), 3)
        self.assertFalse(core.read(self.run / "runner/summary.json")["complete"])
        runner = self.runner(Adapter())
        runner.stop.set()
        self.assertEqual(self.execute(runner), 3)
        self.assertEqual(runner.state["status"], "interrupted")

    def test_interrupt_saves_in_flight_result_and_skips_new_work(self):
        self.job("extract-a")
        self.job("extract-b")
        adapter = Adapter()
        runner = self.runner(adapter, concurrency=1)

        def stopping_adapter(*args):
            runner.stop.set()
            return adapter(*args)

        runner.adapter = stopping_adapter
        self.assertEqual(self.execute(runner), 3)
        self.assertTrue((self.run / "accepted/extract-a.json").exists())
        self.assertFalse((self.run / "accepted/extract-b.json").exists())
        resumed_adapter = Adapter()
        self.assertEqual(self.execute(self.runner(resumed_adapter)), 0)
        self.assertEqual([c["job_id"] for c in resumed_adapter.calls], ["extract-b"])

    def test_missing_raw_and_model_mismatch_are_not_content_retries(self):
        self.job("extract-missing")
        self.job("extract-profile")
        adapter = Adapter({
            "extract-missing": [{"status": "ok", "response": None, "model": "actual", "model_profile": self.profile}],
            "extract-profile": [{"status": "ok", "response": {}, "model": "actual", "model_profile": {"model": "wrong", "parameters": {}}}],
        })
        self.assertEqual(self.execute(self.runner(adapter)), 2)
        self.assertEqual(len(adapter.calls), 2)

    def test_old_versions_and_absent_profile_are_rejected(self):
        core.write(self.run / "manifest.json", {"skill_version": "1.0.1", "model_profile": self.profile})
        with self.assertRaisesRegex(ValueError, "旧版本"):
            self.runner(Adapter())
        core.write(self.run / "manifest.json", {"skill_version": core.VERSION, "model_profile": None})
        with self.assertRaisesRegex(ValueError, "model_profile"):
            self.runner(Adapter())

    def test_cross_process_lock_rejects_second_writer(self):
        path = self.run / "runner/runner.lock"
        command = [sys.executable, "-B", "-c",
                   "import sys;sys.path.insert(0,sys.argv[1]);from runner import run_lock;"
                   "\nwith run_lock(__import__('pathlib').Path(sys.argv[2])):pass", str(SCRIPTS), str(path)]
        with run_lock(path):
            result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已有 runner", result.stderr)

    def test_subprocess_adapter_argv_is_literal_and_paths_support_spaces(self):
        adapter = self.run / "adapter with spaces.py"
        marker = self.run / "SHOULD_NOT_EXIST"
        adapter.write_text("import argparse,json\nfrom pathlib import Path\np=argparse.ArgumentParser()\np.add_argument('--literal')\np.add_argument('--request')\np.add_argument('--result')\na=p.parse_args()\nr=json.loads(Path(a.request).read_text())\nPath(a.result).write_text(json.dumps({'literal':a.literal,'messages':r['messages']}))\n")
        request, result = self.run / "request with spaces.json", self.run / "result with spaces.json"
        literal = f"$(touch '{marker}'); `echo secret`"
        core.write(request, {"messages": [{"role": "user", "content": literal}]})
        self.assertIsNone(invoke_adapter([sys.executable, str(adapter), "--literal", literal], request, result))
        self.assertFalse(marker.exists())
        self.assertEqual(core.read(result)["literal"], literal)

    def test_real_pipeline_with_subprocess_fake_adapter_and_trace(self):
        # 复用已有合成数据与语义答案，只检验真实流水线协议连接，不调用付费模型。
        from test_pipeline import PipelineTests
        import prepare
        import workflow

        fixture = PipelineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        manifest = prepare.prepare(fixture.arguments("adapter-run", model="synthetic-request", model_parameters="{}"))
        run = Path(manifest["run_dir"])
        adapter = self.run / "pipeline fake adapter.py"
        adapter.write_text(
            "import argparse,json,sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0,{str(Path(__file__).parent)!r})\n"
            "from test_pipeline import synthetic_response\n"
            "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--result');a=p.parse_args()\n"
            "request=json.loads(Path(a.request).read_text())\n"
            "job=json.loads(next(m['content'] for m in request['messages'] if m['role']=='user'))['job']\n"
            "from extract_transport import unpack_job\n"
            "job=unpack_job(job) if job.get('transport_version') else job\n"
            "response=synthetic_response(job)\n"
            "Path(a.result).write_text(json.dumps({'status':'ok','response':response,'model':'synthetic-actual',"
            "'model_profile':request['model_profile'],'input_tokens':100,'output_tokens':50},ensure_ascii=False))\n",
            encoding="utf-8",
        )
        runner = Runner(run, [sys.executable, "-B", str(adapter)], concurrency=2)
        self.assertEqual(self.execute(runner), 0)
        self.assertTrue(workflow.status(run)["complete"])
        self.assertEqual(len(core.read(run / "high_potential_trends.json")["trends"]), 1)
        for path in (run / "accepted").glob("*.json"):
            execution = core.read(path)["execution"]
            self.assertEqual(execution["model_profile"], manifest["model_profile"])
            self.assertTrue(execution["started_at"] and execution["finished_at"])
            self.assertTrue((run / execution["attempt_file"]).is_file())
        unused = Adapter()
        resumed = Runner(run, ["must-not-run"], adapter=unused)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(unused.calls, [])
        cached_manifest = prepare.prepare(fixture.arguments("adapter-cached", model="synthetic-request", model_parameters="{}"))
        self.assertGreater(cached_manifest["counts"]["cached_records"], 0)
        cached_run = Path(cached_manifest["run_dir"])
        self.assertEqual(self.execute(Runner(cached_run, [sys.executable, "-B", str(adapter)])), 0)
        summary = core.read(cached_run / "runner/summary.json")
        self.assertGreater(summary["accepted_jobs"], summary["runner_accepted_jobs"])


if __name__ == "__main__":
    unittest.main()
