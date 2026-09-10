"""独立验证缓存、早期筛选与源上下文优化；仅使用临时资料和合成模型回复。"""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import unittest

import test_pipeline as fixtures

core, prepare, workflow = fixtures.core, fixtures.prepare, fixtures.workflow
MODEL = "synthetic-test-model"


class OptimizationTests(unittest.TestCase):
    # 组合复用资料搭建方法，不继承测试类，避免重复执行其整套测试。
    save_inputs = fixtures.PipelineTests.save_inputs
    arguments = fixtures.PipelineTests.arguments

    def setUp(self):
        fixtures.PipelineTests.setUp(self)
        self.cache = self.root / "shared-cache"

    def configured(self, name, **overrides):
        values = {"model": MODEL, "model_parameters": '{"temperature":0.1,"reasoning_effort":"high"}',
                  "cache_dir": str(self.cache), "no_cache": False}
        values.update(overrides)
        return self.arguments(name, **values)

    def accept(self, run, job, transform=None, *, with_profile=True):
        response = fixtures.synthetic_response(job)
        if transform:
            response = transform(job, response)
        response_path = run / "responses" / f"{job['id']}.json"
        core.write(response_path, response)
        manifest = core.read(run / "manifest.json")
        execution = {"model_profile": manifest["model_profile"],
                     "messages_sha256": core.digest(core.read(run / "requests" / f"{job['id']}.json")["messages"])} if with_profile else {}
        workflow.receive(run, job["id"], response_path, MODEL, 100, 50, execution=execution)

    def complete(self, run, transform=None):
        seen = set()
        for _ in range(40):
            state = workflow.advance(run, limit=10000)
            if state["complete"]:
                return seen
            pending = {item["job_id"] for item in state["pending"]}
            self.assertTrue(pending)
            for job in core.load_jobs(run):
                if job["id"] in pending:
                    seen.add(job["stage"])
                    self.accept(run, job, transform)
        self.fail("优化后的有限工作流没有完成")

    def prime_cache(self, name="origin"):
        args = self.configured(name)
        manifest = prepare.prepare(args)
        run = Path(args.output)
        for job in core.load_jobs(run):
            self.accept(run, job)
        expected = {rid for rid, record in core.read(run / "records.json").items() if record["kind"] != "trend"}
        self.assertEqual(len(list(self.cache.rglob("*.json"))), len(expected))
        return run, manifest, expected

    def cached_ids(self, run):
        return set(core.read(Path(run) / "cache_report.json")["hits"])

    def test_missing_effective_prompt_hash_disables_cache_and_receipt_metadata_is_protected(self):
        args = self.configured("missing-message-trace")
        manifest = prepare.prepare(args)
        run = Path(args.output)
        job = next(j for j in core.load_jobs(run) if j["payload"]["records"][0]["kind"] != "trend")
        path = run / "reply.json"
        core.write(path, fixtures.synthetic_response(job))
        workflow.receive(run, job["id"], path, MODEL, execution={"model_profile": manifest["model_profile"]})
        self.assertFalse(list(self.cache.rglob("*.json")))
        accepted_path = run / "accepted" / f"{job['id']}.json"
        changed = core.read(accepted_path)
        changed["execution"]["model_profile"]["parameters"]["temperature"] = 0.9
        core.write(accepted_path, changed)
        with self.assertRaisesRegex(ValueError, "接收执行信息被修改"):
            workflow.status(run)

    def test_user_cache_reuses_across_dates_order_and_batching_with_original_execution(self):
        origin, origin_manifest, expected = self.prime_cache()
        self.users["users"].reverse()
        for user in self.users["users"]:
            user.get("aesthetic_research", []).reverse()
        self.save_inputs()
        args = self.configured("reordered-later-date", start_date="2027-01-01", end_date="2027-01-01", batch_records=1)
        manifest = prepare.prepare(args)
        run = Path(args.output)
        self.assertEqual(self.cached_ids(run), expected)
        self.assertEqual(manifest["counts"]["cached_records"], 6)
        self.assertEqual(manifest["counts"]["selected_trends"], 1)
        self.assertNotEqual(manifest["inputs"]["users"]["sha256"], origin_manifest["inputs"]["users"]["sha256"])
        self.assertTrue(all(item["stage"] == "extract" for item in workflow.status(run)["pending"]))
        cached_receipts = [core.accepted(run, job) for job in core.load_jobs(run)
                           if core.accepted(run, job) is not None]
        self.assertEqual(len(cached_receipts), len(expected))
        for receipt in cached_receipts:
            self.assertEqual((receipt["input_tokens"], receipt["output_tokens"]), (0, 0))
            for source in receipt["execution"]["cache_sources"]:
                trace = source["origin"]
                self.assertEqual(trace["run_dir"], str(origin))
                self.assertEqual(trace["model"], MODEL)
                original = core.read(origin / "accepted" / f"{trace['job_id']}.json")
                for key in ("prompt_version", "accepted_at", "request_sha256", "response_sha256", "execution"):
                    self.assertEqual(trace[key], original[key])
        self.complete(run)
        exported = core.read(run / "high_potential_trends.json")
        reused = [entry for entry in exported["execution"] if entry["execution"].get("cache_sources")]
        self.assertEqual(len(reused), len(expected))
        self.assertTrue(all(source["origin"]["run_dir"] == str(origin)
                            for receipt in reused for source in receipt["execution"]["cache_sources"]))

    def test_text_profile_model_or_parameters_change_invalidate_only_affected_content(self):
        _, _, expected = self.prime_cache()
        original_users = copy.deepcopy(self.users)
        self.users["users"][0]["aesthetic_research"][0]["ai_analysis"] += "但仅适用于办公。"
        self.save_inputs()
        args = self.configured("changed-text")
        prepare.prepare(args)
        self.assertEqual(self.cached_ids(args.output), expected - {"user:u1:user_qa:q1"})
        self.users = copy.deepcopy(original_users)
        self.users["users"][0]["profile"]["profession"] = "另一种测试职业"
        self.save_inputs()
        args = self.configured("changed-profile")
        prepare.prepare(args)
        self.assertEqual(self.cached_ids(args.output), {rid for rid in expected if not rid.startswith("user:u1:")})
        self.users = original_users
        self.save_inputs()
        for name, options in (("changed-model", {"model": "synthetic-test-model-new"}),
                              ("changed-parameters", {"model_parameters": '{"temperature":0.2,"reasoning_effort":"high"}'})):
            with self.subTest(name=name):
                args = self.configured(name, **options)
                prepare.prepare(args)
                self.assertEqual(self.cached_ids(args.output), set())

    def test_undeclared_profile_or_explicit_disable_does_not_create_or_use_cache(self):
        args = self.configured("unconfirmed-execution")
        prepare.prepare(args)
        for job in core.load_jobs(args.output):
            self.accept(Path(args.output), job, with_profile=False)
        self.assertEqual(list(self.cache.rglob("*.json")), [])
        self.prime_cache()
        for name, options in (("disabled", {"no_cache": True}), ("unknown-model", {"model": None})):
            with self.subTest(name=name):
                args = self.configured(name, **options)
                prepare.prepare(args)
                report = core.read(Path(args.output) / "cache_report.json")
                self.assertFalse(report["enabled"])
                self.assertEqual(report["hits"], [])

    def test_corrupt_cache_digest_and_false_quote_fall_back_to_pending_extraction(self):
        _, _, expected = self.prime_cache()
        paths = sorted(self.cache.rglob("*.json"))
        first, second = core.read(paths[0]), core.read(paths[1])
        bad_ids = {first["entry"]["record"]["id"], second["entry"]["record"]["id"]}
        first["entry"]["observations"][0]["claim"] = "摘要被损坏"
        core.write(paths[0], first)
        second["entry"]["observations"][0]["quote"] = "原文不存在的缓存引文"
        second["sha256"] = core.digest(second["entry"])
        core.write(paths[1], second)
        args = self.configured("damaged-cache")
        prepare.prepare(args)
        run = Path(args.output)
        report = core.read(run / "cache_report.json")
        self.assertEqual(set(report["hits"]), expected - bad_ids)
        self.assertEqual({entry["record_id"] for entry in report["invalid_entries"]}, bad_ids)
        pending_user_ids = {record["id"] for job in core.load_jobs(run) if core.accepted(run, job) is None
                            for record in job["payload"]["records"] if record["kind"] != "trend"}
        self.assertEqual(pending_user_ids, bad_ids)
        self.complete(run)
        self.assertTrue(core.read(run / "completion.json")["status"] == "complete")

    def test_cache_rebinds_images_and_source_pointers_to_current_input(self):
        origin, _, expected = self.prime_cache()
        moved_root = self.root / "moved-user-source"
        shutil.copytree(self.user_path.parent, moved_root)
        self.user_path = moved_root / "users.json"
        self.users["users"].reverse()
        self.save_inputs()
        args = self.configured("new-source-path")
        manifest = prepare.prepare(args)
        run = Path(args.output)
        self.assertEqual(self.cached_ids(run), expected)
        self.complete(run)
        result = core.read(run / "high_potential_trends.json")
        self.assertTrue(result["trends"])
        current_source = core.read(self.user_path)
        user_evidence = [entry for card in result["trends"] for entry in card["source_evidence"] if entry["kind"] != "trend"]
        self.assertTrue(user_evidence)
        for entry in user_evidence:
            self.assertEqual(entry["source_file"], str(self.user_path))
            self.assertEqual(entry["source_sha256"], manifest["inputs"]["users"]["sha256"])
            parts = entry["json_pointer"].strip("/").split("/")
            current = current_source
            for part in parts:
                current = current[int(part)] if isinstance(current, list) else current[part]
            self.assertIn(entry["quote"], current)
        user_images = [image for card in result["trends"] for image in card["image_refs"] if image["source_record_id"].startswith("user:")]
        self.assertTrue(user_images)
        self.assertTrue(all(Path(image["absolute_path"]).is_relative_to(moved_root) for image in user_images))
        self.assertTrue(all(image["file_exists"] for image in user_images))
        self.assertTrue(any(source["origin"]["run_dir"] == str(origin) for receipt in result["execution"]
                            for source in receipt["execution"].get("cache_sources", [])))

    def test_multidimensional_evidence_deduplicates_users_and_retains_one_full_source_copy(self):
        answer = "喜欢 P20 的哑光表面。也喜欢 P20 的细腻触感。" + "仅在办公室愿意采用，其他场景仍需验证。" * 45
        self.users["users"][0]["aesthetic_research"][0]["ai_analysis"] = answer
        self.save_inputs()
        args = self.configured("multidimensional")
        prepare.prepare(args)
        run = Path(args.output)

        def multidimensional(job, response):
            if job["stage"] == "extract":
                expanded = []
                for observation in response["observations"]:
                    observation["dimensions"] = ["material", "touch"]
                    if observation["record_id"] == "user:u1:user_qa:q1":
                        for quote in ("喜欢 P20 的哑光表面。", "也喜欢 P20 的细腻触感。"):
                            expanded.append({**copy.deepcopy(observation), "quote": quote})
                    else:
                        expanded.append(observation)
                response["observations"] = expanded
            elif job["stage"] in {"theme", "propose"}:
                for item in response["themes" if job["stage"] == "theme" else "candidates"]:
                    item["dimensions"] = ["material", "touch"]
            return response

        self.complete(run, multidimensional)
        output = core.read(run / "high_potential_trends.json")
        stats = output["trends"][0]["support_statistics"]
        self.assertEqual(stats["users_with_relevant_evidence"], 2)
        self.assertEqual(stats["user_ids_by_relation"]["mixed"], ["u1"])
        duplicate_source_seen = False
        for job in core.load_jobs(run):
            if job["stage"] not in {"theme", "screen", "audit", "draft", "review"}:
                continue
            payload = job["payload"]
            source_ids = [item["record_id"] for item in payload["evidence"]]
            self.assertEqual(set(payload["source_records"]), set(source_ids))
            original_records = core.read(run / "records.json")
            for rid, source in payload["source_records"].items():
                self.assertEqual(source["fields"], original_records[rid]["fields"])
                self.assertNotIn("profile", source)
                if "profile" in original_records[rid]:
                    self.assertEqual(payload["profiles"][source["user_id"]], original_records[rid]["profile"])
            if source_ids.count("user:u1:user_qa:q1") > 1:
                duplicate_source_seen = True
                self.assertEqual(payload["source_records"]["user:u1:user_qa:q1"]["fields"]["ai_analysis"], answer)
            self.assertTrue(all("source_fields" not in item for item in payload["evidence"]))
        self.assertTrue(duplicate_source_seen)
        self.assertEqual(len(core.read(run / "evidence.json")), 9)

    def test_screen_rejection_exits_before_merge_and_final_report_contains_no_approved_card(self):
        args = self.configured("screen-rejected")
        prepare.prepare(args)
        run = Path(args.output)

        def reject_screen(job, response):
            if job["stage"] == "screen":
                for decision in response["decisions"]:
                    decision.update(decision="reject", reason="合成测试：制造能力与用户偏好并无共同命题")
            return response

        stages = self.complete(run, reject_screen)
        self.assertEqual(stages, {"extract", "theme", "propose", "screen"})
        self.assertFalse({"merge", "audit", "draft", "review"}.intersection(job["stage"] for job in core.load_jobs(run)))
        self.assertEqual(core.read(run / "high_potential_trends.json")["trends"], [])
        rejected = core.read(run / "validation_report.json")["rejected_candidates"]
        self.assertTrue(rejected)
        self.assertTrue(all(item["decision"] == "reject" for item in rejected))
        self.assertEqual((run / "high_potential_trends.jsonl").read_text(), "")

    def test_comparison_image_does_not_inherit_negative_evidence_attitude(self):
        self.users["users"][0]["aesthetic_research"][2]["ai_analysis"] = "不喜欢 P21 的哑光表面，比较对象是 P20。"
        self.save_inputs()
        args = self.configured("comparison")
        prepare.prepare(args)
        run = Path(args.output)

        def comparison(job, response):
            if job["stage"] == "extract":
                for observation in response["observations"]:
                    if observation["record_id"] == "user:u1:user_qa:q3":
                        observation["image_roles"] = {"P21": "target", "P20": "comparison"}
            return response

        self.complete(run, comparison)
        images = [image for card in core.read(run / "high_potential_trends.json")["trends"]
                  for image in card["image_refs"] if image["source_record_id"] == "user:u1:user_qa:q3"]
        by_code = {image["code"]: image for image in images}
        self.assertEqual(set(by_code), {"P20", "P21"})
        self.assertEqual(by_code["P20"]["role"], "user_comparison")
        self.assertEqual(by_code["P20"]["evidence_relation"], "counter")
        self.assertIsNone(by_code["P20"]["image_attitude_from_text"])
        self.assertEqual(by_code["P21"]["role"], "user_target")
        self.assertNotIn("counterexample", {image["role"] for image in images})

    def test_compact_replies_restore_full_text_images_and_reuse_without_rewriting_receipt(self):
        args = self.configured("compact-origin")
        prepare.prepare(args)
        run = Path(args.output)

        def compact(job, response):
            if job["stage"] == "extract":
                for observation in response["observations"]:
                    for key in ("field", "quote", "image_roles"):
                        observation.pop(key)
            return response

        self.complete(run, compact)
        records = core.read(run / "records.json")
        for item in core.read(run / "evidence.json").values():
            self.assertEqual(item["quote"], records[item["record_id"]]["fields"][item["field"]])
            self.assertEqual(set(item["image_roles"].values()) - {"unclear"}, set())
        qa = next(e for e in core.read(run / "evidence.json").values() if e["record_id"] == "user:u1:user_qa:q1")
        self.assertIn("P20", qa["image_codes"])
        for job in core.load_jobs(run):
            if job["stage"] == "extract":
                response = core.accepted(run, job)["response"]
                self.assertEqual(response["skipped"], [])
                self.assertNotIn("coverage", response)
                self.assertTrue(all("quote" not in observation for observation in response["observations"]))
        images = [image for card in core.read(run / "high_potential_trends.json")["trends"] for image in card["image_refs"]]
        self.assertTrue(any(image["code"] == "P20" and image["role"] == "user_unclear" and image["absolute_path"] for image in images))
        self.assertEqual(core.read(run / "validation_report.json")["record_coverage"], {"extracted": 8})
        reused = self.configured("compact-reuse", batch_records=1)
        result = prepare.prepare(reused)
        self.assertEqual(result["counts"]["cached_records"], 6)
        self.complete(Path(reused.output), compact)

    def test_skipped_record_coverage_and_cache_preserve_explicit_reason(self):
        self.users["users"][0]["aesthetic_research"][0]["ai_analysis"] = "不清楚。"
        self.save_inputs()
        args = self.configured("compact-skipped")
        prepare.prepare(args)
        run = Path(args.output)

        def skip_unknown(job, response):
            if job["stage"] == "extract":
                response["observations"] = [o for o in response["observations"] if o["record_id"] != "user:u1:user_qa:q1"]
                if any(r["id"] == "user:u1:user_qa:q1" for r in job["payload"]["records"]):
                    response["skipped"] = [{"record_id": "user:u1:user_qa:q1", "status": "unclear", "reason": "回答未表达设计偏好"}]
            return response

        self.complete(run, skip_unknown)
        report = core.read(run / "validation_report.json")
        self.assertEqual(report["record_coverage"], {"extracted": 7, "unclear": 1})
        self.assertIn({"record_id": "user:u1:user_qa:q1", "status": "unclear", "reason": "回答未表达设计偏好"}, report["record_dispositions"])
        reused = self.configured("compact-skipped-reuse", batch_records=1)
        prepare.prepare(reused)
        self.complete(Path(reused.output), skip_unknown)
        self.assertEqual(core.read(Path(reused.output) / "validation_report.json")["record_coverage"], report["record_coverage"])


if __name__ == "__main__":
    unittest.main()
