"""确定性整理与宿主恢复的集成回归；使用真实接收凭证及假模型，不访问网络。"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import core
import workflow
from runner import Runner


class ExtractOnlyWorkflow:
    """仅隔离后续阶段调度；实际接收和已接收凭证校验使用生产实现。"""

    receive = staticmethod(workflow.receive)

    @staticmethod
    def advance(run, limit=5):
        pending = [{"job_id": job["id"]} for job in core.load_jobs(run) if not core.accepted(run, job)]
        return {"pending": pending[:limit], "complete": not pending}

    @staticmethod
    def status(run, limit=5):
        jobs = core.load_jobs(run)
        done = sum(core.accepted(run, job) is not None for job in jobs)
        return {"accepted": {"extract": done}, "pending_count": len(jobs) - done}


class EnvelopeAdapter:
    def __init__(self, response, *, forbidden=False):
        self.response = deepcopy(response)
        self.forbidden = forbidden
        self.calls = []
        # 特意保留独立于对象规范序列化的格式，用字节断言证明原始文本未重写。
        self.raw = json.dumps(self.response, ensure_ascii=False, indent=3) + "\n"

    def __call__(self, command, request_path, result_path):
        self.calls.append(core.read(request_path))
        if self.forbidden:
            raise AssertionError("恢复已经落盘的回复不得再次调用模型")
        envelope = {
            "status": "ok", "response": deepcopy(self.response), "raw_response": self.raw,
            "model": "synthetic-normalization-model", "model_profile": self.calls[-1]["model_profile"],
            "input_tokens": 101, "output_tokens": 43,
        }
        core.write(result_path, envelope)


class NormalizationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="normalization-integration-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def fixture(self, name="run"):
        run = self.root / name
        record = {"id": "r1", "kind": "user_qa", "fields": {
            "ai_analysis": "camera above 305 looks smaller than P303", "question": "Which layout is preferred?",
        }}
        records = {record["id"]: record}
        core.write(run / "records.json", records)
        core.write(run / "manifest.json", {
            "skill_version": core.VERSION, "records_sha256": core.digest(records),
            "model_profile": {"model": "synthetic-normalization-model", "parameters": {"temperature": 0}},
            "cache": {"enabled": False},
        })
        identifier = core.make_job(run, "extract", "one", {"records": [record]})
        job = core.read(run / "jobs" / f"{identifier}.json")
        response = {"job_id": identifier, "observations": [{
            "record_id": "r1", "dimensions": ["form", "form"], "stance": "conditional",
            "image_roles": {"P305": "target", "P303": "comparison"},
        }], "skipped": []}
        return run, job, response

    def runner(self, run, adapter):
        return Runner(run, ["synthetic-adapter-no-process"], concurrency=1,
                      adapter=adapter, workflow_api=ExtractOnlyWorkflow(), jitter=lambda: 0)

    def execute(self, runner):
        with redirect_stdout(io.StringIO()):
            return runner.execute()

    def make_legacy_blocked(self, run, job, response):
        adapter = EnvelopeAdapter(response)
        # 模拟尚未引入确定性整理的历史宿主，保留真实两次失败及原始输出。
        with patch.object(workflow, "normalize_with_trace", side_effect=lambda current_job, value: (deepcopy(value), None)), \
                patch("runner_repair.recover_records"):
            original_runner = self.runner(run, adapter)
            self.assertEqual(self.execute(original_runner), 2)
        self.assertEqual(len(adapter.calls), 2)
        state = core.read(run / "runner/state.json")["jobs"][job["id"]]
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["validation_failures"], 2)
        original_files = {
            path.relative_to(run): path.read_bytes()
            for path in (run / "runner/attempts").rglob("*") if path.is_file()
        }
        return adapter, state, original_files

    def test_runner_normalizes_once_and_accepts_without_rewriting_provider_response(self):
        run, job, response = self.fixture()
        adapter = EnvelopeAdapter(response)
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual(len(adapter.calls), 1)
        receipt = core.accepted(run, job)
        self.assertEqual(receipt["response"]["observations"][0]["image_roles"], {"P303": "comparison"})
        self.assertEqual(receipt["response"]["observations"][0]["dimensions"], ["form"])
        self.assertEqual(adapter.response, response)
        trace = receipt["execution"]["normalization"]
        self.assertEqual(trace["original_response_sha256"], core.digest(response))
        self.assertEqual(trace["normalized_response_sha256"], core.digest(receipt["response"]))
        self.assertEqual({change["field"] for change in trace["changes"]}, {"image_roles", "dimensions"})
        self.assertEqual((run / trace["original_raw_file"]).read_bytes(), adapter.raw.encode("utf-8"))
        folder = run / "runner/attempts" / job["id"] / "0001"
        self.assertEqual(core.read(folder / "result.raw.json")["response"], response)
        self.assertEqual(core.read(folder / "result.raw.json")["raw_response"], adapter.raw)
        self.assertEqual(core.read(folder / "outcome.json")["kind"], "valid")
        state = runner.state["jobs"][job["id"]]
        self.assertEqual((state["processed_attempts"], state["validation_failures"]), (1, 0))
        self.assertEqual(core.read(run / "runner/summary.json")["usage"],
                         {"input_tokens": 101, "output_tokens": 43, "missing_usage_attempts": 0})

    def test_blocked_recovery_uses_zero_calls_keeps_history_and_counts_usage_once(self):
        run, job, response = self.fixture()
        adapter, before_state, original_files = self.make_legacy_blocked(run, job, response)
        unused = EnvelopeAdapter(response, forbidden=True)
        resumed = self.runner(run, unused)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(unused.calls, [])
        after = resumed.state["jobs"][job["id"]]
        self.assertEqual(after["status"], "accepted")
        for name in ("validation_failures", "transport_failures", "processed_attempts", "last_outcome_file"):
            self.assertEqual(after[name], before_state[name])
        for relative, original_bytes in original_files.items():
            self.assertEqual((run / relative).read_bytes(), original_bytes, str(relative))
        self.assertEqual(len(list((run / "runner/attempts" / job["id"]).iterdir())), 2)
        recovery = core.read(run / after["normalization_recovery_file"])
        self.assertEqual(recovery["recovery"]["additional_model_calls"], 0)
        original_outcome = core.read(run / before_state["last_outcome_file"])
        self.assertEqual(recovery["recovery"]["original_outcome_sha256"], core.digest(original_outcome))
        self.assertEqual(recovery["finished_at"], original_outcome["finished_at"])
        receipt = core.accepted(run, job)
        self.assertEqual(receipt["execution"]["recovery"], recovery["recovery"])
        self.assertEqual((run / receipt["execution"]["normalization"]["original_raw_file"]).read_bytes(), adapter.raw.encode("utf-8"))
        summary = core.read(run / "runner/summary.json")
        self.assertEqual(summary["code_recovered_jobs"], 1)
        self.assertEqual(summary["usage"], {"input_tokens": 202, "output_tokens": 86, "missing_usage_attempts": 0})
        performance = core.read(run / "performance_report.json")["totals"]
        self.assertEqual((performance["attempt_count"], performance["failure_count"]), (2, 2))
        self.assertEqual((performance["input_tokens_known"], performance["output_tokens_known"]), (202, 86))
        receipt_bytes = (run / "accepted" / f"{job['id']}.json").read_bytes()
        self.assertEqual(self.execute(self.runner(run, unused)), 0)
        self.assertEqual(unused.calls, [])
        self.assertEqual((run / "accepted" / f"{job['id']}.json").read_bytes(), receipt_bytes)

    def test_four_dimensions_and_fabricated_quotes_are_not_recovered(self):
        for mutation in ("four_dimensions", "fabricated_quote"):
            with self.subTest(mutation=mutation):
                run, job, response = self.fixture(mutation)
                observation = response["observations"][0]
                if mutation == "four_dimensions":
                    observation["dimensions"] = ["form", "material", "color", "touch"]
                else:
                    observation["quote"] = "用户明确喜爱更大的摄像头"
                _, before_state, original_files = self.make_legacy_blocked(run, job, response)
                unused = EnvelopeAdapter(response, forbidden=True)
                resumed = self.runner(run, unused)
                self.assertEqual(self.execute(resumed), 2)
                self.assertEqual(unused.calls, [])
                self.assertEqual(resumed.state["jobs"][job["id"]]["status"], "blocked")
                self.assertEqual(resumed.state["jobs"][job["id"]]["validation_failures"], before_state["validation_failures"])
                self.assertIsNone(core.accepted(run, job))
                self.assertFalse((run / "runner/recoveries" / job["id"]).exists())
                for relative, original_bytes in original_files.items():
                    self.assertEqual((run / relative).read_bytes(), original_bytes, str(relative))

    def test_direct_receive_keeps_original_object_trace_and_input_file_immutable(self):
        run, job, response = self.fixture()
        path = run / "responses/original.json"
        raw = json.dumps(response, ensure_ascii=False, indent=5) + "\n"
        core.atomic_text(path, raw)
        execution = {"adapter": "synthetic-direct-host"}
        before_execution = deepcopy(execution)
        self.assertEqual(workflow.receive(run, job["id"], path, "synthetic-model", 11, 7,
                                          execution=execution)["status"], "accepted")
        receipt = core.accepted(run, job)
        self.assertEqual(receipt["original_response"], response)
        self.assertEqual(path.read_bytes(), raw.encode("utf-8"))
        self.assertEqual(execution, before_execution)
        trace = receipt["execution"]["normalization"]
        self.assertEqual(trace["original_response_sha256"], core.digest(response))
        self.assertEqual(trace["normalized_response_sha256"], receipt["response_sha256"])
        self.assertEqual(len(trace["changes"]), 2)
        self.assertEqual(receipt["receipt_sha256"], core.digest({key: value for key, value in receipt.items() if key != "receipt_sha256"}))
        receipt_path = run / "accepted" / f"{job['id']}.json"
        before_receipt = receipt_path.read_bytes()
        self.assertEqual(workflow.receive(run, job["id"], path, "synthetic-model")["status"], "already_accepted")
        self.assertEqual(receipt_path.read_bytes(), before_receipt)

    def test_receipt_protects_original_response_and_normalization_trace(self):
        for mutation in ("original", "trace", "normalized"):
            with self.subTest(mutation=mutation):
                run, job, response = self.fixture(mutation)
                path = run / "responses/original.json"
                core.write(path, response)
                workflow.receive(run, job["id"], path, "synthetic-model")
                receipt_path = run / "accepted" / f"{job['id']}.json"
                receipt = core.read(receipt_path)
                if mutation == "original":
                    receipt["original_response"]["observations"][0]["stance"] = "support"
                elif mutation == "trace":
                    receipt["execution"]["normalization"]["changes"][0]["before"] = {}
                else:
                    receipt["response"]["observations"][0]["stance"] = "support"
                core.write(receipt_path, receipt)
                with self.assertRaisesRegex(ValueError, "被修改"):
                    core.accepted(run, job)


if __name__ == "__main__":
    unittest.main()
