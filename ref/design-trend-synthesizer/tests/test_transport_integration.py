"""压缩传输与真实接收、缓存及补齐链路的集成回归；假适配器只读取实际消息。"""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import core
import evidence_cache
import workflow
from extract_transport import decode_response, record_aliases, unpack_job
from runner_repair import validate_source_subset
import test_runner_record_repair as fixtures


class WireAdapter:
    """模型只能看到消息中的短 ID；事件以正式 ID 指定故障，便于核对各轮真实来源。"""

    def __init__(self, job, events):
        self.job = job
        self.events = deepcopy(events)
        self.calls = []
        self.responses = []

    def __call__(self, command, request_path, result_path):
        request = core.read(request_path)
        self.calls.append(request)
        if not self.events:
            raise AssertionError("没有预设的额外假模型调用")
        event = self.events.pop(0)
        if "error" in event:
            core.write(result_path, {"status": "error", "category": event["error"],
                                     "message": "synthetic wire transport error"})
            return
        effective = request.get("record_repair", {}).get("job", self.job)
        aliases = record_aliases(effective)
        wire = json.loads(request["messages"][1]["content"])["job"]
        records = unpack_job(wire)["payload"]["records"]
        observations = []
        for record in records:
            item = {"record_id": record["id"], "dimensions": ["touch"], "stance": "conditional"}
            if aliases[record["id"]] in event.get("bad", []):
                item["quote"] = "模型改写的虚构引文"
            observations.append(item)
        if "extra_alias" in event:
            observations.append({"record_id": event["extra_alias"], "dimensions": ["color"],
                                 "stance": "support"})
        response = {"job_id": request["job_id"], "observations": observations, "skipped": []}
        self.responses.append(deepcopy(response))
        raw = json.dumps(response, ensure_ascii=False, indent=3) + "\n"
        core.write(result_path, {"status": "ok", "response": response, "raw_response": raw,
                                 "model": "synthetic-record-model", "model_profile": request["model_profile"],
                                 "input_tokens": 17, "output_tokens": 11})


class TransportIntegrationTests(unittest.TestCase):
    setUp = fixtures.RunnerRecordRepairTests.setUp
    runner = fixtures.RunnerRecordRepairTests.runner
    execute = fixtures.RunnerRecordRepairTests.execute
    requested_ids = fixtures.RunnerRecordRepairTests.requested_ids
    assert_usage = fixtures.RunnerRecordRepairTests.assert_usage

    def fixture(self, count=3, name="run", reverse=False):
        run = self.root / name
        rows = [{"id": f"user:67:user_qa:{2400 + index}", "kind": "user_qa", "user_id": "67",
                 "profile": {"profession": "设计师"},
                 "fields": {"ai_analysis": f"仅在室内喜欢 P{index} 的细腻表面。", "question": "具体适用条件？"}}
                for index in range(1, count + 1)]
        if reverse:
            rows.reverse()
        records = {record["id"]: record for record in rows}
        profile = {"model": "synthetic-record-model", "parameters": {"temperature": 0}}
        core.write(run / "records.json", records)
        core.write(run / "manifest.json", {"skill_version": core.VERSION, "records_sha256": core.digest(records),
                                            "model_profile": profile,
                                            "cache": {"enabled": True, "model_profile": profile,
                                                      "directory": str(self.root / "cache")}})
        identifier = core.make_job(run, "extract", name, {"records": rows}, {"max_observations": 64})
        return run, core.read(run / "jobs" / f"{identifier}.json")

    def response(self, job):
        return {"job_id": job["id"], "observations": [
            {"record_id": alias, "dimensions": ["touch"], "stance": "conditional"}
            for alias in record_aliases(job)], "skipped": []}

    def test_manual_receive_keeps_raw_short_ids_and_canonical_receipt(self):
        run, job = self.fixture()
        response = self.response(job)
        last = response["observations"].pop()
        response["skipped"].append({"record_id": last["record_id"], "status": "unclear", "reason": "依据不足"})
        raw = json.dumps(response, ensure_ascii=False, indent=5) + "\n"
        path = run / "manual-response.json"
        path.write_text(raw, encoding="utf-8")
        result = workflow.receive(run, job["id"], path, "synthetic-record-model")
        self.assertEqual(result["status"], "accepted")
        receipt = core.accepted(run, job)
        canonical, changes = decode_response(job, response)
        self.assertEqual(receipt["response"], canonical)
        self.assertEqual(receipt["original_response"], response)
        self.assertEqual(path.read_bytes(), raw.encode("utf-8"))
        trace = receipt["execution"]["normalization"]
        self.assertEqual(trace["original_response_sha256"], core.digest(response))
        self.assertEqual(trace["normalized_response_sha256"], core.digest(canonical))
        self.assertEqual(trace["transport"]["changes"], changes)
        self.assertEqual(trace["transport"]["aliases_sha256"], core.digest(record_aliases(job)))
        self.assertEqual(len(changes), 3)

    def test_canonical_response_is_idempotent_after_transport_acceptance(self):
        run, job = self.fixture()
        path = run / "manual-response.json"
        core.write(path, self.response(job))
        workflow.receive(run, job["id"], path, "synthetic-record-model")
        receipt_path = run / "accepted" / f"{job['id']}.json"
        before = receipt_path.read_bytes()
        canonical = core.accepted(run, job)["response"]
        self.assertEqual(decode_response(job, canonical), (canonical, []))
        self.assertEqual(workflow.normalize_with_trace(job, canonical), (canonical, None))
        canonical_path = run / "canonical-response.json"
        core.write(canonical_path, canonical)
        self.assertEqual(workflow.receive(run, job["id"], canonical_path,
                                          "synthetic-record-model")["status"], "already_accepted")
        self.assertEqual(receipt_path.read_bytes(), before)

    def test_cache_reordered_batch_reuses_canonical_ids_without_alias_leak(self):
        first_run, first_job = self.fixture(name="first")
        adapter = WireAdapter(first_job, [{}])
        self.assertEqual(self.execute(self.runner(first_run, adapter)), 0)
        cache_files = {path: path.read_bytes() for path in (self.root / "cache").rglob("*.json")}
        self.assertEqual(len(cache_files), 3)
        second_run, second_job = self.fixture(name="second", reverse=True)
        self.assertNotEqual(record_aliases(first_job), record_aliases(second_job))
        settings = core.read(second_run / "manifest.json")["cache"]
        entries = []
        for record in second_job["payload"]["records"]:
            entry, error = evidence_cache.lookup(record, settings)
            self.assertIsNone(error)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["observations"][0]["record_id"], record["id"])
            entries.append(entry)
        evidence_cache.apply_cached(second_run, [(second_job, entries)])
        receipt = core.accepted(second_run, second_job)
        self.assertEqual([item["record_id"] for item in receipt["response"]["observations"]],
                         [record["id"] for record in second_job["payload"]["records"]])
        self.assertEqual((receipt["input_tokens"], receipt["output_tokens"]), (0, 0))
        self.assertNotIn("normalization", receipt["execution"])
        self.assertEqual(len(receipt["execution"]["cache_sources"]), 3)
        self.assertFalse((second_run / "runner/attempts").exists())
        self.assertEqual(cache_files, {path: path.read_bytes() for path in cache_files})

    def test_three_calls_keep_original_aliases_while_subsets_shrink(self):
        run, job = self.fixture()
        identifiers = [record["id"] for record in job["payload"]["records"]]
        adapter = WireAdapter(job, [{"bad": identifiers[1:]}, {"bad": identifiers[2:]}, {}])
        runner = self.runner(run, adapter)
        self.assertEqual(self.execute(runner), 0)
        self.assertEqual([self.requested_ids(request, job) for request in adapter.calls],
                         [identifiers, identifiers[1:], identifiers[2:]])
        original_aliases = record_aliases(job)
        reverse_aliases = {rid: alias for alias, rid in original_aliases.items()}
        for request in adapter.calls:
            expected_ids = self.requested_ids(request, job)
            effective = request.get("record_repair", {}).get("job", job)
            self.assertEqual(record_aliases(effective),
                             {reverse_aliases[rid]: rid for rid in expected_ids})
            wire_job = json.loads(request["messages"][1]["content"])["job"]
            self.assertEqual([row["id"] for row in unpack_job(wire_job)["payload"]["records"]],
                             [reverse_aliases[rid] for rid in expected_ids])
        receipt = core.accepted(run, job)
        self.assertEqual([item["record_id"] for item in receipt["response"]["observations"]], identifiers)
        sources = receipt["execution"]["record_repair"]["source_records"]
        self.assertTrue(sources[identifiers[0]]["attempt_file"].endswith("0001/request.json"))
        self.assertTrue(sources[identifiers[1]]["attempt_file"].endswith("0002/request.json"))
        self.assertTrue(sources[identifiers[1]]["transport"]["changes"])
        last = receipt["execution"]["last_call"]["normalization"]["transport"]
        self.assertEqual(last["aliases_sha256"], core.digest({reverse_aliases[identifiers[2]]: identifiers[2]}))
        self.assert_usage(run, attempts=3, input_tokens=51, output_tokens=33)

    def test_unknown_or_unrequested_alias_excludes_whole_attempt_from_reuse(self):
        for outside in ("unknown", "retained_record"):
            with self.subTest(outside=outside):
                run, job = self.fixture(name=outside)
                identifiers = [record["id"] for record in job["payload"]["records"]]
                original_alias = next(iter(record_aliases(job)))
                extra_alias = "r99999" if outside == "unknown" else original_alias
                adapter = WireAdapter(job, [{"bad": identifiers[1:]}, {"extra_alias": extra_alias}, {}])
                runner = self.runner(run, adapter)
                self.assertEqual(self.execute(runner), 0)
                self.assertEqual([self.requested_ids(request, job) for request in adapter.calls],
                                 [identifiers, identifiers[1:], identifiers[1:]])
                receipt = core.accepted(run, job)
                self.assertEqual(receipt["response"]["observations"][0]["dimensions"], ["touch"])
                source_records = receipt["execution"]["record_repair"]["source_records"]
                self.assertEqual(set(source_records), {identifiers[0]})
                self.assertTrue(source_records[identifiers[0]]["attempt_file"].endswith("0001/request.json"))
                second = run / "runner/attempts" / job["id"] / "0002"
                self.assertEqual(core.read(second / "outcome.json")["kind"], "validation")
                self.assertEqual(core.read(second / "result.raw.json")["response"]["observations"][-1]["record_id"],
                                 extra_alias)

    def test_subset_transport_retry_after_restart_preserves_frozen_wire_and_aliases(self):
        run, job = self.fixture()
        identifiers = [record["id"] for record in job["payload"]["records"]]
        adapter = WireAdapter(job, [{"bad": identifiers[1:]}, {"error": "timeout"}])
        runner = self.runner(run, adapter)
        for _ in range(2):
            folder = runner.prepare_attempt(job)
            adapter([], folder / "request.json", folder / "result.raw.json")
            runner.finish(job, folder)
        frozen = deepcopy(adapter.calls[-1])
        before = {path: path.read_bytes() for path in (run / "runner/attempts").rglob("*") if path.is_file()}
        resumed_adapter = WireAdapter(job, [{}])
        resumed = self.runner(run, resumed_adapter)
        self.assertEqual(self.execute(resumed), 0)
        self.assertEqual(len(resumed_adapter.calls), 1)
        retry = resumed_adapter.calls[0]
        self.assertEqual(retry["messages"], frozen["messages"])
        self.assertEqual(retry["messages_sha256"], frozen["messages_sha256"])
        self.assertEqual(retry["record_repair"], frozen["record_repair"])
        self.assertEqual(resumed.job_state(job)["record_repair_rounds"], 1)
        self.assertEqual(resumed.job_state(job)["transport_failures"], 1)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assert_usage(run, attempts=3, input_tokens=34, output_tokens=22, missing=1)

    def test_subset_cannot_renumber_frozen_original_alias(self):
        _, job = self.fixture()
        subset = deepcopy(job)
        subset["payload"]["records"] = subset["payload"]["records"][1:]
        validate_source_subset(job, subset)
        subset["transport_aliases"] = {
            f"r{index}": record["id"] for index, record in enumerate(subset["payload"]["records"], 1)
        }
        with self.assertRaisesRegex(ValueError, "短 ID"):
            validate_source_subset(job, subset)


if __name__ == "__main__":
    unittest.main()
