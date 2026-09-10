"""验证首次提取的输入去重和动态预算；不调用模型，也不删减原始记录。"""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import core
import lean
import pipeline
import prepare
import test_pipeline as fixtures


def record(index, text="喜欢柔和颜色。", user_id="u1"):
    return {"id": f"user:{user_id}:user_qa:{index:03}", "kind": "user_qa", "user_id": user_id,
            "profile": {"profession": "画像唯一文本-工业设计师", "age": "30"},
            "fields": {"question": "哪个颜色适合办公？", "ai_analysis": text,
                       "answer_type": "偏好", "scenario_type": "办公", "question_type": "审美"}}


class BatchingTests(unittest.TestCase):
    def test_short_records_use_full_record_capacity(self):
        records = [record(i) for i in range(65)]
        packs = prepare.extraction_packs(records, 32, 100000)
        self.assertEqual([len(pack) for pack in packs], [32, 32, 1])
        self.assertEqual([row for pack in packs for row in pack], records)

    def test_long_records_reserve_output_without_truncation(self):
        records = [record(i, "长" * 641) for i in range(3)]
        packs = prepare.extraction_packs(records, 32, 100000, max_observations=8)
        self.assertEqual([len(pack) for pack in packs], [1, 1, 1])
        self.assertEqual([row for pack in packs for row in pack], records)
        huge = record(8, "完整" * 5000)
        self.assertEqual(prepare.extraction_packs([huge], 32, 50000, max_observations=3), [[huge]])

    def test_output_estimate_boundaries_and_cached_actual_count(self):
        self.assertEqual([prepare.observation_weight(record(i, "文" * size), 64)
                          for i, size in enumerate((0, 1, 160, 161, 320, 321))], [1, 1, 1, 2, 2, 3])
        records = [record(i) for i in range(3)]
        cache = {item["id"]: {"observations": [None] * count}
                 for item, count in zip(records, (5, 4, 0))}
        packs = prepare.extraction_packs(records, 32, 100000, cache, max_observations=8)
        self.assertEqual([len(pack) for pack in packs], [1, 2])
        with self.assertRaisesRegex(ValueError, "缓存观察数"):
            prepare.extraction_packs(records, 32, 100000, cache, max_observations=4)

    def test_optional_trend_text_reserves_capacity_and_missing_summary_uses_title(self):
        trend = {"id": "trend:t1", "kind": "trend", "fields": {"title_zh": "标题" * 81}}
        self.assertEqual(prepare.observation_weight(trend, 64), 2)
        trend["fields"] = {"summary_zh": "短摘要", "local_vl_info": "已有分析" * 400}
        self.assertEqual(prepare.observation_weight(trend, 64), 11)
        records = [{**trend, "id": f"trend:t{i}"} for i in range(6)]
        self.assertEqual([len(pack) for pack in prepare.extraction_packs(records, 32, 100000)], [5, 1])

    def test_actual_message_budget_includes_system_template_and_limits(self):
        records = [record(i) for i in range(5)]
        budget = prepare.extraction_chars(records[:2], 64)
        packs = prepare.extraction_packs(records, 32, budget)
        self.assertEqual([len(pack) for pack in packs], [2, 2, 1])
        with tempfile.TemporaryDirectory() as temporary:
            for index, pack in enumerate(packs):
                jid = core.make_job(temporary, "extract", index, {"records": pack}, {"max_observations": 64})
                request = core.read(Path(temporary) / "requests" / f"{jid}.json")
                actual = sum(len(message["content"]) for message in request["messages"])
                self.assertEqual(actual, prepare.extraction_chars(pack, 64))
                self.assertLessEqual(actual, budget)
                self.assertGreater(actual, len(json.dumps(core.model_job(core.read(Path(temporary) / "jobs" / f"{jid}.json"))["payload"], ensure_ascii=False)))

    def test_oversized_single_record_errors_instead_of_truncating(self):
        item = record(0, "全文" * 500)
        budget = prepare.extraction_chars([item], 64)
        with self.assertRaisesRegex(ValueError, "提示词和模板后超过字符预算"):
            prepare.extraction_packs([item], 32, budget - 1)
        self.assertEqual(prepare.extraction_packs([item], 32, budget), [[item]])

    def test_model_input_deduplicates_profiles_and_keeps_source_job_complete(self):
        records = [record(i) for i in range(3)]
        job = core.build_job("extract", 0, {"records": records}, {"max_observations": 64})
        original = copy.deepcopy(job)
        view = core.model_job(job)
        self.assertEqual(job, original)
        self.assertEqual(view["payload"]["profiles"], {"u1": records[0]["profile"]})
        for actual, source in zip(view["payload"]["records"], records):
            self.assertEqual(actual, {key: value for key, value in source.items() if key != "profile"})
        message = core.build_request_messages(job)[1]["content"]
        self.assertEqual(message.count("画像唯一文本-工业设计师"), 1)
        from extract_transport import unpack_job, record_aliases
        restored = unpack_job(json.loads(message)["job"])
        aliases = record_aliases(job)
        for actual, source in zip(restored["payload"]["records"], records):
            self.assertEqual({**actual, "id": aliases[actual["id"]]}, source)
        self.assertNotIn('", "', message)
        self.assertEqual(core.model_job({"stage": "audit", "payload": {"evidence": []}}),
                         {"stage": "audit", "payload": {"evidence": []}})

    def test_conflicting_profiles_fail_explicitly(self):
        records = [record(0), record(1)]
        records[1]["profile"] = {"profession": "不同画像"}
        with self.assertRaisesRegex(ValueError, "画像不一致"):
            core.model_job(core.build_job("extract", 0, {"records": records}))

    def test_public_evidence_omits_only_redundant_normalized_fields(self):
        evidence = {"id": "e1", "quote": "原文", "claim": "原文", "category": "", "context": "",
                    "user_value": "", "image_refs": ["内部路径"], "stance": "support"}
        self.assertEqual(core.public_evidence(evidence), {"id": "e1", "quote": "原文", "stance": "support"})
        evidence.update(claim="不同表述", context="原文条件", category="手机", user_value="明确诉求")
        for key in ("claim", "context", "category", "user_value"):
            self.assertEqual(core.public_evidence(evidence)[key], evidence[key])

    def test_cli_defaults_route_to_lean_prepare(self):
        # 默认入口已路由至 Lean 流程，测试需覆盖实际生效的预算，而非已废弃的观察数参数。
        with patch.object(lean, "prepare", return_value={}) as execute, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(pipeline.main(["prepare", "--dry-run"]), 0)
            args = execute.call_args.args[0]
            self.assertEqual(
                (args.batch_chars, args.max_calls, args.map_output_tokens, args.final_output_tokens),
                (48000, 24, None, None),
            )


class PrepareBatchingTests(unittest.TestCase):
    save_inputs = fixtures.PipelineTests.save_inputs
    arguments = fixtures.PipelineTests.arguments

    def setUp(self):
        fixtures.PipelineTests.setUp(self)

    def test_prepare_partitions_users_and_reports_verifiable_totals(self):
        for index, user in enumerate(self.users["users"][:2]):
            user["aesthetic_research"] = [{"id": f"q{n}", "question": "审美偏好？", "ai_analysis": "喜欢柔和的色彩。"}
                                          for n in range(35)]
        self.save_inputs()
        args = self.arguments(batch_records=32, extraction_observations=64)
        manifest = prepare.prepare(args)
        jobs = core.load_jobs(args.output)
        for job in jobs:
            self.assertLessEqual(len({r["user_id"] for r in job["payload"]["records"] if "user_id" in r}), 1)
        preview = manifest["extraction_batch_preview"]
        actual = sum(sum(len(message["content"]) for message in core.read(Path(args.output) / "requests" / f"{job['id']}.json")["messages"])
                     for job in jobs)
        self.assertEqual(preview["total_message_chars"], actual)
        self.assertEqual(preview["model_message_chars"], actual)
        self.assertEqual(preview["records_per_batch"]["max"], 32)
        self.assertEqual(sum(row["records"] for row in preview["batches"]), manifest["counts"]["source_records"])
        self.assertTrue(all(row["message_chars"] <= args.batch_chars for row in preview["batches"]))
        records = core.read(Path(args.output) / "records.json")
        for job in jobs:
            for item in job["payload"]["records"]:
                self.assertEqual(item, core.public_record(records[item["id"]]))

    def test_invalid_observation_budget_rejected(self):
        for value in (0, -1, 129, True, "64"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "extraction-observations"):
                prepare.prepare(self.arguments(extraction_observations=value, dry_run=True))


if __name__ == "__main__":
    unittest.main()
