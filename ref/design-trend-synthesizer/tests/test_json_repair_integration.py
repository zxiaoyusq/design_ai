"""完整模型原文的语法整理与手动/自动接收边界，不访问网络。"""

import hashlib
import json
import unittest
from unittest.mock import patch

import test_normalization_integration as fixtures
import core
import workflow
from runner import strict_json


class JSONRepairIntegrationTests(unittest.TestCase):
    setUp = fixtures.NormalizationIntegrationTests.setUp
    fixture = fixtures.NormalizationIntegrationTests.fixture
    runner = fixtures.NormalizationIntegrationTests.runner
    execute = fixtures.NormalizationIntegrationTests.execute
    def syntax_adapter(self, value, wrapper):
        calls = []
        raw = wrapper(json.dumps(value, ensure_ascii=False))

        def adapter(command, request_path, result_path):
            request = core.read(request_path)
            calls.append(request)
            core.write(result_path, {"status": "ok", "response": None, "raw_response": raw,
                                    "model": "synthetic-json-model", "model_profile": request["model_profile"],
                                    "input_tokens": 11, "output_tokens": 7})
        return adapter, calls, raw

    def plain_response(self, job):
        return {"job_id": job["id"], "observations": [
            {"record_id": "r1", "dimensions": ["form"], "stance": "conditional"}], "skipped": []}

    def test_runner_repairs_complete_fence_preserves_raw_and_uses_one_call(self):
        run, job, _ = self.fixture()
        adapter, calls, raw = self.syntax_adapter(self.plain_response(job), lambda text: "```json\n" + text + "\n```")
        self.assertEqual(self.execute(self.runner(run, adapter)), 0)
        self.assertEqual(len(calls), 1)
        receipt = core.accepted(run, job)
        trace = receipt["execution"]["json_syntax"]
        self.assertEqual((run / trace["original_raw_file"]).read_text(), raw)
        self.assertEqual(trace["original_raw_sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(core.read(run / "performance_report.json")["totals"]["attempt_count"], 1)

    def test_manual_receive_repairs_trailing_comma_but_keeps_original_text(self):
        run, job, _ = self.fixture()
        response = self.plain_response(job)
        raw = json.dumps(response, ensure_ascii=False)[:-1] + ",}"
        path = run / "manual.txt"
        path.write_text(raw)
        self.assertEqual(workflow.receive(run, job["id"], path, "manual-model")["status"], "accepted")
        receipt = core.accepted(run, job)
        self.assertEqual(receipt["response"], response)
        self.assertEqual((run / receipt["execution"]["json_syntax"]["original_raw_file"]).read_text(), raw)

    def test_manual_duplicate_key_is_rejected_without_receipt(self):
        run, job, _ = self.fixture()
        raw = json.dumps(self.plain_response(job))[:-1] + ',"skipped":[]}'
        path = run / "manual.txt"
        path.write_text(raw)
        with self.assertRaises(ValueError):
            workflow.receive(run, job["id"], path, "manual-model")
        self.assertIsNone(core.accepted(run, job))

    def test_historical_syntax_failure_recovers_without_new_model_call(self):
        run, job, _ = self.fixture()
        adapter, calls, raw = self.syntax_adapter(self.plain_response(job), lambda text: "```json\n" + text + "\n```")
        with patch("json_repair.parse_model_json", side_effect=lambda text: (strict_json(text), [])), \
                patch("runner_repair.recover_records"):
            self.assertEqual(self.execute(self.runner(run, adapter)), 2)
        before = {path: path.read_bytes() for path in (run / "runner/attempts").rglob("*") if path.is_file()}
        self.assertEqual(self.execute(self.runner(run, adapter)), 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        state = core.read(run / "runner/state.json")["jobs"][job["id"]]
        self.assertEqual(state["validation_failures"], 2)
