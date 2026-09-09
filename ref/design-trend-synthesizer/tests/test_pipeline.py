"""用临时数据和 synthetic-test-model 回复验证工作流；不调用模型、网络或图片解析。"""

from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import core
import prepare
import workflow


MODEL = "synthetic-test-model"


def synthetic_response(job, *, reject_users=False, review_decision="approve"):
    """只在测试中按人工构造文本生成已知答案；不用于真实设计判断。"""
    stage, payload = job["stage"], job["payload"]
    response = {"job_id": job["id"]}
    if stage == "extract":
        observations = []
        for record in payload["records"]:
            field = "summary_zh" if record["kind"] == "trend" else "ai_analysis" if record["kind"] == "user_qa" else "ai_index"
            quote = record["fields"][field]
            stance = "example" if record["kind"] == "trend" else "counter" if "不喜欢" in quote else "conditional" if "仅在" in quote else "support"
            observations.append({
                "record_id": record["id"], "field": field, "quote": quote,
                "dimensions": ["material"], "stance": stance,
                "image_roles": {code: "target" for code in re.findall(r"P\d+", quote)},
            })
        response.update(observations=observations, skipped=[])
    elif stage == "theme":
        response.update(themes=[{"title": "合成材料主题", "summary": "保留支持与反对的材料触感要求",
                                 "dimensions": ["material"], "evidence_ids": [e["id"] for e in payload["evidence"]]}], deferred=[])
    elif stage == "propose":
        trends = [e["id"] for e in payload["evidence"] if e["kind"] == "trend"][:2]
        users = [e["id"] for e in payload["evidence"] if e["kind"] in core.USER_KINDS][:6]
        ids = trends + users
        response.update(candidates=[{
            "title": "合成测试：材料触感", "thesis": "在指定情境中探索低干扰表面", "dimensions": ["material"],
            "evidence_ids": ids, "trend_basis": [{"evidence_id": eid, "reason": "预设材料案例"} for eid in trends],
            "user_basis": [{"evidence_id": eid, "reason": "预设材料要求"} for eid in users],
            "shared_principle": "情境中的材料表面设计", "application_hypothesis": "待验证的迁移",
        }], deferred=[{"evidence_id": e["id"], "reason": "合成测试保留未选引用"} for e in payload["evidence"] if e["id"] not in ids])
    elif stage == "screen":
        response["decisions"] = [{"candidate_id": c["id"], "decision": "accept", "reason": "合成数据预设有效交集"} for c in payload["candidates"]]
    elif stage == "merge":
        response.update(groups=[{
            "title": "合成测试：材料触感", "thesis": "保留反对意见的情境设计命题",
            "candidate_ids": [item["id"] for item in payload["candidates"]],
        }], deferred=[])
    elif stage == "audit":
        assessments = []
        for item in payload["evidence"]:
            relation = "support" if item["kind"] == "trend" else item["stance"]
            if reject_users and item["kind"] != "trend":
                relation = "unrelated"
            if item["kind"] == "orphan_demand":
                relation = "unrelated"
            assessments.append({"evidence_id": item["id"], "relation": relation, "reason": "合成测试中预设的关系"})
        response["assessments"] = assessments
    elif stage == "draft":
        supporters = [item["id"] for item in payload["evidence"] if item["relation"] in {"support", "conditional"}]
        counters = [item["id"] for item in payload["evidence"] if item["relation"] == "counter"]
        response["card"] = {
            "title": "合成测试卡片", "thesis": "保留场景限制的材料设计假设",
            "user_tension": "需要细腻触感，也有人不接受低反射表面", "design_principle": "按使用情境探索表面触感",
            "claims": [{"text": "合成资料具有双侧交集", "evidence_ids": supporters}],
            "opportunities": [{"category": "跨品类探索", "proposal": "制作表面样品验证迁移假设", "evidence_ids": supporters}],
            "boundaries": [{"text": "保留合成反对意见", "evidence_ids": counters}] if counters else [],
            "supporting_evidence_ids": supporters, "counter_evidence_ids": counters,
            "priority": "priority_validation", "rationale": "仅作为测试输出，程序应依据覆盖程度调整优先级",
        }
    elif stage == "review":
        response.update(decision=review_decision, issues=[] if review_decision == "approve" else ["合成审核的修改或拒绝原因"], card=None)
        if review_decision == "revise":
            response["card"] = copy.deepcopy(payload["card"])
            response["card"]["title"] = "合成审核修订卡片"
    else:
        raise AssertionError(stage)
    return response


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="design-trends-offline-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.trend_path = self.root / "data" / "trend_data" / "trends.json"
        self.user_path = self.root / "data" / "userreseach_data" / "users.json"
        for relative in ("data/trend_data/images/shared.jpg", "data/userreseach_data/images/shared.jpg", "data/userreseach_data/images/counter.jpg", "data/userreseach_data/images/other-user.jpg", "data/userreseach_data/images/unmentioned.jpg"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic placeholder: intentionally not an image")
        self.trends = {"trends": [{
            "id": identifier, "title_zh": "合成测试案例", "summary_zh": "采用哑光材料形成细腻触感。",
            "release_time": day, "primary_category": "家具", "tags": ["哑光"],
            "images": [{"image_id": f"trend-image-{identifier}", "local_path": "images/shared.jpg", "status": "downloaded"}],
        } for identifier, day in (("old", "2020-01-01"), ("first", "2025-01-01T23:59:59-12:00"), ("last", "2025-12-31"), ("future", "2027-01-01"), ("unknown", None))]}
        self.users = {"users": [
            {"id": "u1", "profile": {"profession": "测试职业"}, "aesthetic_research": [
                {"id": "q1", "question": "哪个表面更合适？", "ai_analysis": "喜欢 P20 的哑光表面。"},
                {"id": "q2", "question": "是否还有其他原因？", "ai_analysis": "喜欢细腻触感。"},
                {"id": "q3", "question": "有哪些限制？", "ai_analysis": "不喜欢 P21 的哑光表面。"},
                {"id": "q4", "question": "无回答？", "ai_analysis": "未提及任何需求。"},
            ], "demand_research": [{"id": "d1", "ai_index": "仅在办公时喜欢 P20 的哑光表面。", "scenario": "办公", "ref_pic": "P20", "ref_pic_links": [{"code": "P20", "image_ids": ["user-image-u1"], "local_paths": ["images/shared.jpg"]}]}],
             "image_preferences": [
                 {"image_id": "user-image-u1", "ref_pic_code": "P20", "local_path": "images/shared.jpg", "emotion_tag": "ENJOY"},
                 {"image_id": "counter-image-u1", "ref_pic_code": "P21", "local_path": "images/counter.jpg", "emotion_tag": "DISLIKE"},
                 {"image_id": "unmentioned-image", "ref_pic_code": "P99", "local_path": "images/unmentioned.jpg", "emotion_tag": "ENJOY"},
             ]},
            {"id": "u2", "profile": {}, "aesthetic_research": [{"id": "q5", "question": "哪个表面更合适？", "ai_analysis": "喜欢 P20 的哑光表面。"}], "image_preferences": [{"image_id": "user-image-u2", "ref_pic_code": "P20", "local_path": "images/other-user.jpg", "emotion_tag": "ENJOY"}]},
            {"id": "u3", "profile": {}, "aesthetic_research": []},
        ], "unlinked_demand_research": [{"id": "orphan1", "ai_index": "喜欢细腻触感。", "scenario": "未知用户", "ref_pic": "无"}]}
        self.save_inputs()

    def save_inputs(self):
        core.write(self.trend_path, self.trends)
        core.write(self.user_path, self.users)

    def arguments(self, name="run", **overrides):
        values = dict(trends=str(self.trend_path), users=str(self.user_path), output=str(self.root / name), project_root=str(self.root), start_date="2025-01-01", end_date="2025-12-31", undated="exclude", as_of="2026-01-01", batch_records=8, batch_chars=16000, max_trends=4, include_vl_text=False, dry_run=False)
        values.update(overrides)
        return SimpleNamespace(**values)

    def accept(self, run, job, response=None, **options):
        response = synthetic_response(job, **options) if response is None else response
        response_path = run / "responses" / f"{job['id']}.json"
        core.write(response_path, response)
        return workflow.receive(run, job["id"], response_path, MODEL, 100, 50)

    def complete(self, run, **options):
        seen = set()
        for _ in range(30):
            state = workflow.advance(run, limit=10000)
            if state["complete"]:
                return seen
            pending = {entry["job_id"] for entry in state["pending"]}
            self.assertTrue(pending, "未完成的工作流必须暴露可执行任务")
            for job in core.load_jobs(run):
                if job["id"] in pending:
                    seen.add(job["stage"])
                    self.accept(run, job, **options)
        self.fail("八阶段工作流未在有界推进次数内完成")

    def test_six_stages_keep_user_counts_paths_and_traceability(self):
        args = self.arguments()
        manifest = prepare.prepare(args)
        run = Path(args.output)
        self.assertEqual(self.complete(run), {"extract", "theme", "propose", "screen", "merge", "audit", "draft", "review"})
        result = core.read(run / "high_potential_trends.json")
        jsonl = [json.loads(line) for line in (run / "high_potential_trends.jsonl").read_text().splitlines()]
        self.assertEqual(result["trends"], jsonl)
        self.assertEqual(len(result["trends"]), 1)
        card = result["trends"][0]
        self.assertNotIn("validation_questions", card)
        self.assertNotIn("下一轮验证", (run / "report.md").read_text())
        stats = card["support_statistics"]
        self.assertEqual(stats["user_ids_by_relation"], {"support": ["u2"], "counter": [], "mixed": ["u1"], "conditional_only": []})
        self.assertEqual(stats["users_with_relevant_evidence"], 2)
        self.assertEqual(stats["trend_record_count"], 2)
        self.assertEqual(stats["recent_trend_record_count"], 2)
        self.assertIsNone(stats["population_preference_rate"])
        self.assertEqual(card["priority"], "exploratory")
        self.assertEqual(manifest["counts"]["excluded_unmentioned_qa"], 1)
        self.assertTrue(card["counter_evidence_ids"])
        self.assertEqual(card["human_review_status"], "pending")
        images = card["image_refs"]
        self.assertTrue(images)
        self.assertNotIn("unmentioned-image", {image["image_id"] for image in images})
        for image in images:
            self.assertTrue(image["file_exists"])
            self.assertFalse(image["visual_verified"])
            absolute = Path(image["absolute_path"])
            self.assertEqual((self.root / image["path"]).resolve(), absolute)
            if image["source_record_id"].startswith("trend:"):
                self.assertEqual(absolute, self.trend_path.parent / "images/shared.jpg")
                self.assertEqual(image["association_level"], "article")
            elif image["source_record_id"].startswith("user:u2:"):
                self.assertEqual(absolute, self.user_path.parent / "images/other-user.jpg")
            elif image["code"] == "P21":
                self.assertEqual(absolute, self.user_path.parent / "images/counter.jpg")
                self.assertEqual(image["role"], "user_target")
                self.assertIsNone(image["image_attitude_from_text"])
            else:
                self.assertEqual(absolute, self.user_path.parent / "images/shared.jpg")
        report = core.read(run / "validation_report.json")
        self.assertEqual(report["record_coverage"], {"extracted": 8})
        self.assertEqual(report["missing_image_references"], 0)
        self.assertTrue(report["text_only_requests"])
        self.assertTrue(all(item["model"] == MODEL for item in result["execution"]))
        self.assertTrue(all(item["prompt_version"] and item["request_sha256"] and item["response_sha256"] and item["accepted_at"] for item in result["execution"]))
        for request_file in (run / "requests").glob("*.json"):
            request_text = request_file.read_text()
            self.assertNotIn("images/shared.jpg", request_text)
            self.assertNotIn("source_root", request_text)
        records = core.read(run / "records.json")
        for job in core.load_jobs(run):
            if job["stage"] in {"audit", "draft", "review"}:
                for item in job["payload"]["evidence"]:
                    self.assertEqual(job["payload"]["source_records"][item["record_id"]]["fields"], records[item["record_id"]]["fields"])
                    self.assertNotIn("source_fields", item)
            if job["stage"] == "draft":
                self.assertLessEqual(len(core.encode(job["payload"])), manifest["settings"]["batch_chars"])
        self.assertEqual(workflow.advance(run)["complete"], True)

    def test_closed_single_ended_and_unknown_date_selection(self):
        cases = [
            ({}, {"trend:first", "trend:last"}),
            ({"start_date": "2025-12-31", "end_date": None}, {"trend:last", "trend:future"}),
            ({"start_date": None, "end_date": "2025-01-01"}, {"trend:old", "trend:first"}),
            ({"undated": "include"}, {"trend:first", "trend:last", "trend:unknown"}),
            ({"start_date": None, "end_date": None}, {"trend:old", "trend:first", "trend:last", "trend:future"}),
        ]
        for index, (options, expected) in enumerate(cases):
            with self.subTest(options=options):
                args = self.arguments(f"date-{index}", **options)
                prepare.prepare(args)
                records = core.read(Path(args.output) / "records.json")
                self.assertEqual({key for key, value in records.items() if value["kind"] == "trend"}, expected)
                self.assertEqual(records.get("trend:first", {}).get("release_time", "2025-01-01"), "2025-01-01")
        args = self.arguments("unknown-run", undated="include")
        prepare.prepare(args)
        self.complete(Path(args.output))
        stats = core.read(Path(args.output) / "high_potential_trends.json")["trends"][0]["support_statistics"]
        self.assertEqual(stats["trend_record_count"], 3)
        self.assertEqual(stats["recent_trend_record_count"], 2)

    def test_illegal_date_or_reversed_range_does_not_create_run(self):
        for options in ({"start_date": "2025-02-30"}, {"start_date": "2026-01-01", "end_date": "2025-01-01"}):
            args = self.arguments(**options)
            with self.assertRaises(ValueError):
                prepare.prepare(args)
            self.assertFalse(Path(args.output).exists())
        self.trends["trends"][0]["release_time"] = "2020-02-30"
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "发布日期非法"):
            prepare.prepare(self.arguments())
        self.assertFalse((self.root / "run").exists())

    def test_empty_range_finishes_without_calling_any_model(self):
        args = self.arguments(start_date="2030-01-01", end_date="2030-12-31")
        manifest = prepare.prepare(args)
        run = Path(args.output)
        self.assertEqual(manifest["counts"]["selected_trends"], 0)
        self.assertEqual(self.complete(run), set())
        self.assertEqual(core.read(run / "high_potential_trends.json")["trends"], [])
        self.assertEqual((run / "high_potential_trends.jsonl").read_text(), "")
        self.assertEqual(core.read(run / "validation_report.json")["semantic_review"], "not_needed")

    def test_split_after_invalid_truncated_response_keeps_each_record_once(self):
        args = self.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        parent = next(job for job in core.load_jobs(run) if len(job["payload"]["records"]) >= 3)
        truncated = run / "truncated.json"
        truncated.write_text('{"job_id":')
        with self.assertRaises(ValueError):
            workflow.receive(run, parent["id"], truncated, MODEL)
        self.assertFalse((run / "accepted" / f"{parent['id']}.json").exists())
        split = workflow.split_job(run, parent["id"])
        self.assertEqual(len(split["children"]), 2)
        active = core.load_jobs(run)
        self.assertNotIn(parent["id"], {job["id"] for job in active})
        covered = Counter(record["id"] for job in active for record in job["payload"]["records"])
        self.assertEqual(set(covered), set(core.read(run / "records.json")))
        self.assertTrue(all(count == 1 for count in covered.values()))
        with self.assertRaises(ValueError):
            self.accept(run, parent)
        self.complete(run)
        self.assertEqual(core.read(run / "validation_report.json")["record_coverage"], {"extracted": 8})
        self.assertEqual(len(core.read(run / "evidence.json")), 8)

    def test_bad_response_and_corrupt_indexes_or_accepted_records_are_rejected(self):
        args = self.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        first = core.load_jobs(run)[0]
        invalid = synthetic_response(first)
        invalid["observations"][0]["quote"] = "不存在于输入的编造原文"
        before = workflow.status(run)["pending_count"]
        with self.assertRaisesRegex(ValueError, "连续原文"):
            self.accept(run, first, invalid)
        self.assertEqual(workflow.status(run)["pending_count"], before)
        self.accept(run, first)
        self.assertEqual(self.accept(run, first)["status"], "already_accepted")
        records = core.read(run / "records.json")
        corrupted = copy.deepcopy(records)
        next(iter(corrupted.values()))["fields"]["extra"] = "篡改"
        core.write(run / "records.json", corrupted)
        with self.assertRaisesRegex(ValueError, "原始文本索引已改变"):
            workflow.status(run)
        core.write(run / "records.json", records)
        saved_path = run / "accepted" / f"{first['id']}.json"
        saved = core.read(saved_path)
        saved["response"]["observations"][0]["claim"] = "篡改已接收内容"
        core.write(saved_path, saved)
        with self.assertRaisesRegex(ValueError, "已接收回复被修改"):
            workflow.status(run)

    def test_audit_can_remove_user_support_and_prevent_a_card(self):
        args = self.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        stages = self.complete(run, reject_users=True)
        self.assertEqual(stages, {"extract", "theme", "propose", "screen", "merge", "audit"})
        self.assertEqual(core.read(run / "high_potential_trends.json")["trends"], [])
        rejected = core.read(run / "validation_report.json")["rejected_candidates"]
        self.assertEqual(len(rejected), 1)
        self.assertIn("缺少双侧", rejected[0]["reason"])

    def test_no_user_text_is_a_valid_one_sided_empty_result(self):
        self.users = {"users": [], "unlinked_demand_research": []}
        self.save_inputs()
        args = self.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        self.assertEqual(self.complete(run), {"extract"})
        self.assertEqual(core.read(run / "high_potential_trends.json")["trends"], [])

    def test_review_revision_or_rejection_controls_final_output(self):
        for decision in ("revise", "reject"):
            with self.subTest(decision=decision):
                args = self.arguments(decision)
                prepare.prepare(args)
                run = Path(args.output)
                self.complete(run, review_decision=decision)
                cards = core.read(run / "high_potential_trends.json")["trends"]
                if decision == "revise":
                    self.assertEqual(cards[0]["title"], "合成审核修订卡片")
                else:
                    self.assertEqual(cards, [])
                    self.assertEqual(len(core.read(run / "validation_report.json")["rejected_candidates"]), 1)

    def test_many_candidate_batches_converge_through_multiple_merge_rounds(self):
        base_trend = self.trends["trends"][1]
        self.trends = {"trends": [{**copy.deepcopy(base_trend), "id": f"batch-trend-{index}"} for index in range(9)]}
        self.users = {"users": [{"id": f"batch-user-{index}", "profile": {}, "aesthetic_research": [{
            "id": f"q-{index}", "question": "如何看待材料？", "ai_analysis": "喜欢哑光材料的细腻触感。",
        }]} for index in range(25)]}
        self.save_inputs()
        args = self.arguments(max_trends=2)
        prepare.prepare(args)
        run = Path(args.output)
        merge_waves, deferred_once = 0, False
        for _ in range(40):
            current = workflow.advance(run, limit=10000)
            if current["complete"]:
                break
            pending_ids = {entry["job_id"] for entry in current["pending"]}
            jobs = [job for job in core.load_jobs(run) if job["id"] in pending_ids]
            self.assertTrue(jobs)
            if jobs[0]["stage"] == "merge":
                merge_waves += 1
            for job in jobs:
                response = synthetic_response(job)
                if job["stage"] == "propose":
                    # 模拟每次提出四个细分命题，使真实调度器面对多轮合并需求。
                    seed = response["candidates"][0]
                    response["candidates"] = [{**copy.deepcopy(seed), "title": f"合成细分命题 {index}"} for index in range(4)]
                elif job["stage"] == "merge":
                    ids = [candidate["id"] for candidate in job["payload"]["candidates"]]
                    deferred = []
                    if not deferred_once and len(ids) > 2:
                        deferred = [{"candidate_id": ids.pop(), "reason": "合成测试：暂缓并保留可追溯理由"}]
                        deferred_once = True
                    count = min(job["limits"]["max_groups"], len(ids))
                    response["groups"] = [{
                        "title": f"合成归并方向 {index}", "thesis": "需要逐层归并的材料设计命题",
                        "candidate_ids": ids[index::count],
                    } for index in range(count)]
                    response["deferred"] = deferred
                self.accept(run, job, response)
        else:
            self.fail("多批合并未有界收敛")
        self.assertGreaterEqual(merge_waves, 2)
        result = core.read(run / "high_potential_trends.json")
        self.assertGreater(len(result["trends"]), 0)
        self.assertLessEqual(len(result["trends"]), 2)
        deferred = core.read(run / "validation_report.json")["deferred_items"]
        merge_deferred = [item for item in deferred if "candidate_id" in item]
        self.assertEqual(len(merge_deferred), 1)
        self.assertEqual(merge_deferred[0]["reason"], "合成测试：暂缓并保留可追溯理由")
        self.assertTrue(all(card["support_statistics"]["users_with_relevant_evidence"] == 25 for card in result["trends"]))

    def test_proposal_and_audit_splits_resume_without_double_counting(self):
        args = self.arguments()
        prepare.prepare(args)
        run = Path(args.output)
        split_stages = set()
        for _ in range(25):
            current = workflow.advance(run, limit=10000)
            if current["complete"]:
                break
            pending_ids = {entry["job_id"] for entry in current["pending"]}
            jobs = [job for job in core.load_jobs(run) if job["id"] in pending_ids]
            self.assertTrue(jobs)
            for job in jobs:
                if job["stage"] in {"propose", "audit"} and job["stage"] not in split_stages:
                    children = workflow.split_job(run, job["id"])["children"]
                    self.assertEqual(len(children), 2)
                    split_stages.add(job["stage"])
                    break
            else:
                for job in jobs:
                    self.accept(run, job)
        else:
            self.fail("拆分后的候选/反证任务未完成")
        self.assertEqual(split_stages, {"propose", "audit"})
        audit_pairs = Counter(
            (job["payload"]["candidate"]["id"], item["id"])
            for job in core.load_jobs(run) if job["stage"] == "audit"
            for item in job["payload"]["evidence"]
        )
        self.assertTrue(audit_pairs)
        self.assertTrue(all(count == 1 for count in audit_pairs.values()))
        result = core.read(run / "high_potential_trends.json")
        self.assertEqual(len(result["trends"]), 1)
        stats = result["trends"][0]["support_statistics"]
        self.assertEqual(stats["users_with_relevant_evidence"], 2)
        self.assertEqual(stats["trend_record_count"], 2)
        self.assertEqual(stats["user_ids_by_relation"]["mixed"], ["u1"])
        self.assertEqual(core.read(run / "validation_report.json")["record_coverage"], {"extracted": 8})

    def test_default_output_cli_follows_project_root_and_preserves_previous_run(self):
        caller = self.root / "another-working-directory"
        caller.mkdir()
        command = [sys.executable, str(SCRIPTS / "pipeline.py"), "legacy", "prepare",
                   "--trends", str(self.trend_path), "--users", str(self.user_path),
                   "--project-root", str(self.root), "--start-date", "2025-01-01",
                   "--end-date", "2025-12-31"]
        completed = subprocess.run(command, cwd=caller, capture_output=True, text=True, check=True)
        manifest = json.loads(completed.stdout)
        run = Path(manifest["run_dir"])
        self.assertEqual(run.parent, self.root / "data/result/high_trend")
        self.assertFalse((caller / "data").exists())
        self.assertEqual(core.read(run / "manifest.json"), manifest)
        self.assertEqual(workflow.status(run)["run_dir"], str(run))
        self.complete(run)
        for filename in ("high_potential_trends.json", "high_potential_trends.jsonl",
                         "report.md", "validation_report.json", "completion.json"):
            self.assertTrue((run / filename).is_file(), filename)
        previous_result = (run / "high_potential_trends.json").read_bytes()
        repeated = subprocess.run(command, cwd=caller, capture_output=True, text=True, check=True)
        second_run = Path(json.loads(repeated.stdout)["run_dir"])
        self.assertNotEqual(run, second_run)
        self.assertEqual(second_run.parent, run.parent)
        self.assertTrue((second_run / "manifest.json").is_file())
        self.assertEqual((run / "high_potential_trends.json").read_bytes(), previous_result)
        with self.assertRaisesRegex(ValueError, "输出目录非空"):
            prepare.prepare(self.arguments(output=str(run)))
        state = workflow.advance(run)
        self.assertTrue(state["complete"])
        self.assertEqual(state["run_dir"], str(run))

    def test_default_output_dry_run_uses_current_project_without_creating_directories(self):
        command = [sys.executable, str(SCRIPTS / "pipeline.py"), "legacy", "prepare", "--dry-run"]
        completed = subprocess.run(command, cwd=self.root, capture_output=True, text=True, check=True)
        manifest = json.loads(completed.stdout)
        self.assertEqual(Path(manifest["run_dir"]).parent, self.root / "data/result/high_trend")
        self.assertEqual(manifest["counts"]["selected_trends"], 4)
        self.assertFalse((self.root / "data/result").exists())

    def test_dry_run_cli_creates_nothing_and_source_path_escape_fails(self):
        command = [sys.executable, str(SCRIPTS / "pipeline.py"), "legacy", "prepare", "--trends", str(self.trend_path), "--users", str(self.user_path), "--output", str(self.root / "dry"), "--project-root", str(self.root), "--start-date", "2025-01-01", "--end-date", "2025-12-31", "--dry-run"]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout)["counts"]["selected_trends"], 2)
        self.assertFalse((self.root / "dry").exists())
        self.trends["trends"][1]["images"][0]["local_path"] = "../../outside.jpg"
        self.save_inputs()
        with self.assertRaisesRegex(ValueError, "来源数据目录"):
            prepare.prepare(self.arguments())


if __name__ == "__main__":
    unittest.main()
