"""整记录历史复用与补齐编译；不调用模型、写入文件或接受正式结果。"""

from copy import deepcopy
from pathlib import Path
import sys
import unittest


SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from contracts import validate_response
from core import digest
from record_repair import collect_reusable_records, compile_response


def fixture(count=3):
    return {"id": "extract-original", "stage": "extract", "limits": {"max_observations": 64},
            "payload": {"records": [{"id": f"r{index + 1}", "kind": "user_qa", "user_id": "u1",
                                     "profile": {"profession": "设计师"}, "fields": {
                                         "ai_analysis": f"仅在室内喜欢 P{index + 1} 的细腻表面。", "question": "适用什么条件？",
                                     }} for index in range(count)]}}


def observation(identifier, **overrides):
    return {"record_id": identifier, "dimensions": ["touch"], "stance": "conditional", **overrides}


def response(job, observations=(), skipped=()):
    return {"job_id": job["id"], "observations": deepcopy(list(observations)), "skipped": deepcopy(list(skipped))}


def attempt(value, number=1):
    return {"response": deepcopy(value), "provenance": {"attempt_id": f"attempt-{number}", "source_file_sha256": "a" * 64}}


class RecordRepairTests(unittest.TestCase):
    def test_latest_complete_group_replaces_whole_old_group_and_retains_provenance(self):
        job = fixture(2)
        first = response(job, [observation("r1", stance="support")])
        latest = response(job, [observation("r1", stance="conditional"), observation("r1", stance="counter"), observation("r2")])
        attempts = [attempt(first), attempt(latest, 2)]
        result = collect_reusable_records(job, attempts)
        self.assertEqual(result["counts"], {"total": 2, "retained": 2, "pending": 0})
        self.assertEqual(result["pending_records"], [])
        entry = result["retained"]["r1"]
        self.assertEqual(entry["response"]["observations"], latest["observations"][:2])
        self.assertEqual(entry["provenance"], attempts[1]["provenance"])
        self.assertEqual(entry["attempt_response_sha256"], digest(latest))
        self.assertEqual(entry["record_sha256"], digest(job["payload"]["records"][0]))
        self.assertEqual(entry["job_sha256"], digest(job))
        self.assertEqual(entry["response_sha256"], digest(entry["response"]))
        compiled = compile_response(job, result["retained"])
        self.assertEqual(compiled, latest)
        validate_response(job, compiled)

    def test_later_missing_or_invalid_group_does_not_erase_earlier_legal_group(self):
        job = fixture()
        older = response(job, [observation("r1"), observation("r2")])
        newer = response(job, [observation("r2", quote="完全虚构的偏好"), observation("r3")])
        result = collect_reusable_records(job, [attempt(older), attempt(newer, 2)])
        self.assertEqual({identifier: entry["provenance"]["attempt_id"] for identifier, entry in result["retained"].items()},
                         {"r1": "attempt-1", "r2": "attempt-1", "r3": "attempt-2"})
        latest_checks = {item["record_id"]: item["status"] for item in result["diagnostics"][1]["records"]}
        self.assertEqual(latest_checks, {"r1": "missing", "r2": "invalid", "r3": "valid"})
        self.assertEqual(len(compile_response(job, result["retained"])["observations"]), 3)

    def test_bad_observation_in_same_record_cannot_be_dropped_to_make_a_valid_group(self):
        job = fixture(2)
        value = response(job, [observation("r1"), observation("r1", quote="原文不存在的观点"), observation("r2")])
        result = collect_reusable_records(job, [attempt(value)])
        self.assertEqual(set(result["retained"]), {"r2"})
        self.assertEqual(result["pending_records"], job["payload"]["records"][:1])
        diagnostic = result["diagnostics"][0]["records"][0]
        self.assertEqual(diagnostic["observation_count"], 2)
        self.assertIn("连续原文", diagnostic["error"])

    def test_observation_and_skipped_conflict_is_not_silently_removed(self):
        job = fixture(1)
        value = response(job, [observation("r1")], [{"record_id": "r1", "status": "unclear", "reason": "同时跳过"}])
        result = collect_reusable_records(job, [attempt(value)])
        self.assertEqual(result["retained"], {})
        self.assertEqual(result["counts"]["pending"], 1)
        self.assertIn("重复", result["diagnostics"][0]["records"][0]["error"])

    def test_normalization_keeps_original_group_and_only_applies_existing_rules(self):
        job = fixture(2)
        value = response(job, [observation("r1", dimensions=["touch", "touch"], image_roles={"P999": "target"})], [
            {"record_id": "r2", "status": "unclear", "reason": "没有明确判断"},
            {"record_id": "r2", "status": "unclear", "reason": "没有明确判断"},
        ])
        result = collect_reusable_records(job, [attempt(value)])
        self.assertEqual(result["counts"]["pending"], 0)
        entry = result["retained"]["r1"]
        self.assertEqual(entry["original_response"]["observations"], value["observations"])
        self.assertEqual(entry["response"]["observations"][0]["image_roles"], {})
        self.assertEqual(entry["response"]["observations"][0]["dimensions"], ["touch"])
        self.assertEqual(len(entry["normalization"]["changes"]), 2)
        self.assertEqual(len(result["retained"]["r2"]["response"]["skipped"]), 1)
        validate_response(job, compile_response(job, result["retained"]))

    def test_unknown_unassigned_or_wrong_envelope_rejects_whole_attempt(self):
        for mutation in ("unknown", "unassigned", "malformed_item", "extra_top", "wrong_id", "missing_skipped", "bad_array"):
            with self.subTest(mutation=mutation):
                job = fixture(1)
                value = response(job, [observation("r1")])
                if mutation == "unknown":
                    value["observations"].append(observation("outside"))
                elif mutation == "unassigned":
                    value["observations"].append({"dimensions": ["form"], "stance": "support"})
                elif mutation == "malformed_item":
                    value["skipped"].append("没有归属")
                elif mutation == "extra_top":
                    value["invented"] = []
                elif mutation == "wrong_id":
                    value["job_id"] = "other-job"
                elif mutation == "missing_skipped":
                    value.pop("skipped")
                else:
                    value["skipped"] = None
                result = collect_reusable_records(job, [attempt(value)])
                self.assertEqual(result["retained"], {})
                self.assertEqual(result["diagnostics"][0]["status"], "rejected_attempt")
                self.assertTrue(result["diagnostics"][0]["error"])

    def test_identical_record_groups_require_provenance_and_keep_input_immutable(self):
        job = fixture(1)
        value = response(job, [observation("r1")])
        attempts = [attempt(value)]
        before_job, before_attempts = deepcopy(job), deepcopy(attempts)
        result = collect_reusable_records(job, attempts)
        compiled = compile_response(job, result["retained"])
        compiled["observations"][0]["dimensions"].clear()
        result["retained"]["r1"]["record"]["profile"]["profession"] = "改变副本"
        result["retained"]["r1"]["original_response"]["observations"][0]["stance"] = "support"
        result["retained"]["r1"]["provenance"].clear()
        self.assertEqual(job, before_job)
        self.assertEqual(attempts, before_attempts)
        for malformed in (None, {"response": value}, {"response": value, "provenance": {}}, {"response": value, "provenance": "unknown"}):
            result = collect_reusable_records(job, [malformed])
            self.assertEqual(result["retained"], {})
            self.assertEqual(result["diagnostics"][0]["status"], "rejected_attempt")

    def test_compile_accepts_exact_missing_subset_and_preserves_all_groups(self):
        job = fixture()
        retained = collect_reusable_records(job, [attempt(response(job, [observation("r2")]))])["retained"]
        subset_job = {**deepcopy(job), "id": "extract-subset", "payload": {
            "records": [deepcopy(job["payload"]["records"][2]), deepcopy(job["payload"]["records"][0])],
        }}
        subset = response(subset_job, [observation("r3")], [{"record_id": "r1", "status": "unclear", "reason": "无明确判断"}])
        before = deepcopy((job, retained, subset_job, subset))
        compiled = compile_response(job, retained, subset_job, subset)
        self.assertEqual(compiled["job_id"], job["id"])
        self.assertEqual([item["record_id"] for item in compiled["observations"]], ["r2", "r3"])
        self.assertEqual(compiled["skipped"], subset["skipped"])
        validate_response(job, compiled)
        self.assertEqual((job, retained, subset_job, subset), before)

    def test_compile_rejects_missing_overlap_changed_source_and_invalid_subset(self):
        for mutation in ("no_subset", "missing", "overlap", "changed_source", "fabricated_quote", "unknown_response_record"):
            with self.subTest(mutation=mutation):
                job = fixture(2)
                retained = collect_reusable_records(job, [attempt(response(job, [observation("r1")]))])["retained"]
                subset_job = {**deepcopy(job), "id": "subset", "payload": {"records": [deepcopy(job["payload"]["records"][1])]}}
                subset = response(subset_job, [observation("r2")])
                if mutation == "no_subset":
                    subset_job, subset = None, None
                elif mutation == "missing":
                    subset_job["payload"]["records"] = []
                elif mutation == "overlap":
                    subset_job["payload"]["records"].append(deepcopy(job["payload"]["records"][0]))
                elif mutation == "changed_source":
                    subset_job["payload"]["records"][0]["fields"]["ai_analysis"] = "新编写的来源"
                elif mutation == "fabricated_quote":
                    subset["observations"][0]["quote"] = "改写原文"
                else:
                    subset["observations"].append(observation("unknown"))
                with self.assertRaises(ValueError):
                    compile_response(job, retained, subset_job, subset)

    def test_compilation_rechecks_original_total_observation_budget(self):
        job = fixture(2)
        job["limits"]["max_observations"] = 1
        value = response(job, [observation("r1"), observation("r2")])
        retained = collect_reusable_records(job, [attempt(value)])["retained"]
        self.assertEqual(len(retained), 2)
        with self.assertRaisesRegex(ValueError, "最多允许 1 项"):
            compile_response(job, retained)

    def test_retained_groups_cannot_be_rebound_or_modified_before_compilation(self):
        for mutation in ("record", "response", "original", "normalization", "unknown_id", "other_job"):
            with self.subTest(mutation=mutation):
                job = fixture(1)
                retained = collect_reusable_records(job, [attempt(response(job, [observation("r1")]))])["retained"]
                if mutation == "record":
                    retained["r1"]["record"]["fields"]["ai_analysis"] = "改写"
                elif mutation == "response":
                    retained["r1"]["response"]["observations"][0]["stance"] = "support"
                elif mutation == "original":
                    retained["r1"]["original_response"]["observations"][0]["stance"] = "support"
                elif mutation == "normalization":
                    retained["r1"]["normalization"]["changes"].append({"invented": True})
                elif mutation == "unknown_id":
                    retained["unknown"] = retained.pop("r1")
                else:
                    job["id"] = "another-job"
                with self.assertRaises(ValueError):
                    compile_response(job, retained)

    def test_wrong_job_duplicate_sources_and_nonlist_attempts_are_rejected(self):
        for mutation in ("stage", "version", "duplicate", "malformed_record", "records_type"):
            with self.subTest(mutation=mutation):
                job = fixture(1)
                if mutation == "stage":
                    job["stage"] = "theme"
                elif mutation == "version":
                    job["skill_version"] = "1.0.0"
                elif mutation == "duplicate":
                    job["payload"]["records"].append(deepcopy(job["payload"]["records"][0]))
                elif mutation == "malformed_record":
                    job["payload"]["records"] = [None]
                else:
                    job["payload"]["records"] = None
                with self.assertRaises(ValueError):
                    collect_reusable_records(job, [])
        with self.assertRaises(ValueError):
            collect_reusable_records(fixture(), None)

    def test_no_pending_records_rejects_unnecessary_subset(self):
        job = fixture(1)
        retained = collect_reusable_records(job, [attempt(response(job, [observation("r1")]))])["retained"]
        with self.assertRaisesRegex(ValueError, "已无待补记录"):
            compile_response(job, retained, job, response(job, [observation("r1")]))


if __name__ == "__main__":
    unittest.main()
