"""单板反馈分流与版面身份的合成验证；零真实模型、零真实交付。"""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import llm_group as group
import revise_llm_boards as revise
import render_delivery as delivery
from test_llm_group import FakeModel, cards, document, relation_template, visual_answer


class TargetedRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prism-revision-synthetic-")
        self.root = Path(self.tmp.name)
        self.rows = cards(self.root, 14)
        self.document = document(self.rows)
        self.source = self.root / "source"
        self.source.mkdir()
        self.prepared = self.root / "prepared.json"
        self.sample = self.root / "sample.json"
        self.cards_path = self.root / "design-cards.json"
        self.save(self.cards_path, self.document)
        self.save(self.sample, {"images": [{**row, "sha256": row["image_sha256"]} for row in self.rows]})
        self.save(self.prepared, {"schema_version": "prism.design_cards_prepared.v1", "synthetic_fixture": True,
                                 "design_cards_ref": group.reference(self.cards_path), "sample_ref": group.reference(self.sample)})
        templates = [{**relation_template([r["card_id"] for r in rows]), "branch": "CMF", "template_id": identity}
                     for identity, rows in (("T-A", self.rows[:8]), ("T-B", self.rows[8:]))]
        pools = {template["template_id"]: [r["card_id"] for r in rows] for template, rows in zip(templates, (self.rows[:8], self.rows[8:]))}
        calls = group.ModelCalls(self.source, group.POLICY.read_text(), workers=1, max_calls=2, execute=FakeModel())
        issues = []
        selected, audit = group.visual_group(pools, templates, self.rows, calls, 16, issues)
        self.assertFalse(issues)
        by_id = {row["card_id"]: row for row in self.rows}
        boards = []
        for row in selected:
            members = [{"unit_id": i, "image_id": by_id[i]["image_id"], "sha256": by_id[i]["image_sha256"],
                        "branch": "CMF", "roi": by_id[i]["display_bbox"], "display_bbox": by_id[i]["display_bbox"],
                        "evidence_bbox": by_id[i]["evidence_bbox"]} for i in row["unit_ids"]]
            boards.append({**row, "board_id": "BOARD-" + row["cluster_id"], "members": members})
        self.board, self.other = boards
        group.write_outputs({"boards": {"boards": boards}, "clusters": {"clusters": selected, "residual_cards": []},
                             "observations.compat": group.compatibility(self.document), "visual-selection": {"audit": audit}},
                            self.source, self.prepared)
        self.feedback_path = self.root / "feedback.json"
        self.save(self.feedback_path, {"issue": "合成反馈：界面不清楚，意见不自动成为 DNA 事实"})
        self.plan_path = self.root / "plan.json"
        self.loader = patch.object(group, "load_prepared", return_value=self.document)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.plan = self.make_plan("relationship")

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))

    def make_plan(self, kind):
        value = {"schema_version": revise.PLAN_VERSION, "board_id": self.board["board_id"],
                 "issue_key": "synthetic-object-question", "issue_kind": kind, "reason": "合成有界修订，不是真实审美结论",
                 "feedback_ref": group.reference(self.feedback_path), "feedback_pointer": "/issue",
                 "source_refs": {"prepared": group.reference(self.prepared), "boards": group.reference(self.source / "boards.json"),
                                 "clusters": group.reference(self.source / "clusters.json")}, "exclude_card_ids": [], "layout_overrides": {}}
        if kind == "display":
            value["layout_overrides"] = {self.board["unit_ids"][0]: {"columns": 4, "height": 460, "mobile_height": 300}}
        self.save(self.plan_path, value)
        return value

    def run_revision(self, execute=False, fake=None, out="revision"):
        self.save(self.plan_path, self.plan)
        return revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path, self.root / out,
                          execute=execute, executor=fake or FakeModel())

    def test_dry_plan_is_readonly_and_keeps_original_candidate_pool(self):
        fake = FakeModel()
        result = self.run_revision(fake=fake)
        self.assertEqual(set(result["candidate_ids"]), {r["card_id"] for r in self.rows[:8]})
        self.assertEqual(result["planned_visual_calls"], 1)
        self.assertFalse(fake.calls)
        self.assertFalse((self.root / "revision").exists())

    def test_unified_revision_requires_its_actual_issue_not_an_empty_registry(self):
        for kind in ("relationship", "display", "fact"):
            self.plan = self.make_plan(kind)
            registry = {"schema_version": group.unified_module().feedback_module().VERSION,
                        "prepared_ref": group.reference(self.prepared), "issues": []}
            path = self.root / "registry.json"
            self.save(path, registry)
            with self.assertRaisesRegex(ValueError, "当前问题"):
                revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path,
                           self.root / "unified-revision", comparison_mode="unified", feedback_path=path)
            registry["issues"] = [{"issue_id": self.plan["issue_key"], "feedback_ref": self.plan["feedback_ref"],
                "feedback_pointer": "/issue", "affected_card_ids": [self.board["unit_ids"][0]],
                "context_card_ids": self.board["unit_ids"][1:], "issue_kind": kind,
                "observation": "当前合成问题", "resolution_condition": "人工确认前不销项"}]
            self.save(path, registry)
            result = revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path,
                                self.root / "unified-revision", comparison_mode="unified", feedback_path=path)
            self.assertEqual(result["status"], "dry_run_no_model_calls")

    def registered_feedback(self, affected=None):
        issue = {"issue_id": self.plan["issue_key"], "feedback_ref": self.plan["feedback_ref"],
                 "feedback_pointer": self.plan["feedback_pointer"],
                 "affected_card_ids": affected or [self.board["unit_ids"][0]],
                 "context_card_ids": self.board["unit_ids"][1:], "issue_kind": self.plan["issue_kind"],
                 "observation": "当前登记的具体关系反馈", "resolution_condition": "仍待设计师确认"}
        path = self.root / "registry.json"
        self.save(path, {"schema_version": group.unified_module().feedback_module().VERSION,
                         "prepared_ref": group.reference(self.prepared), "issues": [issue]})
        return path

    def html_plan(self):
        source = self.root / "feedback.html"
        source.write_text('<article id="board-1">源反馈</article><aside>HTML_WHOLE_PAGE_SENTINEL</aside>')
        self.plan.update(feedback_ref=group.reference(source), feedback_pointer="#board-1")
        self.save(self.plan_path, self.plan)
        return source

    def test_html_revision_sends_registered_observation_not_whole_page(self):
        self.html_plan()
        registry = self.registered_feedback()

        def answer_with_feedback(stage, payload, answer):
            from test_unified_selection import unified_answer
            answer = unified_answer([row["card_id"] for row in payload["cards"]])
            answer["feedback_decisions"] = [{"issue_id": issue["issue_id"],
                "affected_card_ids": issue["current_affected_card_ids"], "decision": "retained_with_evidence",
                "evidence": {"observation": "合成实际组比较", "compared_card_ids": answer["groups"][0]["member_ids"],
                             "context_change": "", "remaining_uncertainty": "等待人工确认"}}
                for issue in payload["active_feedback"]]
            return answer

        fake = FakeModel(answer_with_feedback)
        summary = revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path,
                             self.root / "html-revision", comparison_mode="unified", feedback_path=registry,
                             execute=True, executor=fake)
        self.assertEqual(summary["model_calls_this_execution"], 1)
        self.assertEqual(summary["status"], "revision_pending_review")
        payload = fake.calls[0]["payload"]
        self.assertNotIn("HTML_WHOLE_PAGE_SENTINEL", group.encoded(fake.calls[0]))
        observation = payload["revision_context"]["feedback_as_observation_not_new_dna"]
        self.assertEqual(observation[0]["observation"], "当前登记的具体关系反馈")
        self.assertEqual(observation[0]["affected_card_ids"], [self.board["unit_ids"][0]])

    def test_html_without_registry_or_legacy_mode_fails_clearly_before_call(self):
        self.html_plan()
        fake = FakeModel()
        for mode, error in (("unified", "当前问题"), ("legacy_branches", "HTML 反馈需统一模式")):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, error):
                revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path,
                           self.root / "html-revision", comparison_mode=mode, execute=True, executor=fake)
        self.assertFalse(fake.calls)
        self.assertFalse((self.root / "html-revision").exists())

    def test_html_anchor_and_source_hash_are_verified_before_revision(self):
        source = self.html_plan()
        self.plan["feedback_pointer"] = "#missing"
        self.save(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, "anchor"):
            revise.prepare(self.prepared, self.source, self.board["board_id"], self.plan_path)
        self.plan["feedback_pointer"] = "#board-1"
        self.save(self.plan_path, self.plan)
        source.write_text('<article id="board-1">修改后的反馈</article>')
        with self.assertRaisesRegex(ValueError, "SHA"):
            revise.prepare(self.prepared, self.source, self.board["board_id"], self.plan_path)

    def test_registered_exact_object_alias_matches_current_board_member(self):
        current = next(row for row in self.rows if row["card_id"] == self.board["unit_ids"][0])
        current["bbox_format"] = "normalized_xywh"
        alias = {**deepcopy(current), "card_id": "same-object-id-card", "branch": "ID"}
        self.rows.append(alias)
        self.save(self.cards_path, self.document)
        prepared = revise.read(self.prepared)
        prepared["design_cards_ref"] = group.reference(self.cards_path)
        self.save(self.prepared, prepared)
        for name in ("boards", "clusters"):
            path = self.source / f"{name}.json"
            original = revise.read(path)
            original["input_refs"].update(prepared=group.reference(self.prepared),
                                          design_cards=group.reference(self.cards_path))
            self.save(path, original)
        self.plan = self.make_plan("relationship")
        registry = self.registered_feedback([alias["card_id"]])
        summary = revise.run(self.prepared, self.source, self.board["board_id"], self.plan_path,
                             self.root / "alias-revision", comparison_mode="unified", feedback_path=registry)
        self.assertEqual(summary["status"], "dry_run_no_model_calls")

    def rebuild_large_visual_pool(self, count, executor=None):
        self.rows = cards(self.root, count)
        self.document = document(self.rows)
        group.load_prepared.return_value = self.document
        self.save(self.cards_path, self.document)
        self.save(self.sample, {"images": [{**row, "sha256": row["image_sha256"]} for row in self.rows]})
        self.save(self.prepared, {"design_cards_ref": group.reference(self.cards_path), "sample_ref": group.reference(self.sample)})
        self.source = self.root / "large-source"
        self.source.mkdir()
        ids = [row["card_id"] for row in self.rows]
        template = {**relation_template(ids), "template_id": "T-large", "branch": "CMF"}
        calls = group.ModelCalls(self.source, group.POLICY.read_text(), workers=1, max_calls=1, execute=executor or FakeModel())
        groups, audit = group.visual_group({"T-large": ids}, [template], self.rows, calls, count, [])
        by_id = {row["card_id"]: row for row in self.rows}
        chosen = groups[0]
        members = [{"unit_id": i, "image_id": by_id[i]["image_id"], "sha256": by_id[i]["image_sha256"],
                    "branch": "CMF", "roi": by_id[i]["display_bbox"], "display_bbox": by_id[i]["display_bbox"],
                    "evidence_bbox": by_id[i]["evidence_bbox"]} for i in chosen["unit_ids"]]
        self.board = {**chosen, "board_id": "BOARD-" + chosen["cluster_id"], "members": members}
        group.write_outputs({"boards": {"boards": [self.board]}, "clusters": {"clusters": groups},
                             "observations.compat": group.compatibility(self.document), "visual-selection": {"audit": audit}},
                            self.source, self.prepared)
        self.plan = self.make_plan("relationship")

    def test_existing_large_visual_window_uses_one_call(self):
        self.rebuild_large_visual_pool(24)
        fake = FakeModel()
        summary = self.run_revision(True, fake)
        self.assertEqual(summary["model_calls_this_execution"], 1)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(fake.calls[0]["payload"]["cards"]), 24)

    def test_over_large_window_is_rejected_before_call(self):
        self.rebuild_large_visual_pool(25)
        fake = FakeModel()
        with self.assertRaisesRegex(ValueError, "2–24"):
            self.run_revision(True, fake)
        self.assertFalse(fake.calls)
        self.assertFalse((self.root / "revision").exists())

    def test_relationship_uses_model_once_and_preserves_other_board(self):
        self.plan["exclude_card_ids"] = [self.board["unit_ids"][0]]
        fake = FakeModel()
        self.run_revision(True, fake)
        self.assertEqual([row["payload"]["task"] for row in fake.calls], ["visual"])
        principles, binding = group.load_grouping_principles()
        self.assertIn(principles, fake.calls[0]["system"])
        self.assertEqual(fake.calls[0]["payload"]["grouping_principles"],
                         {"version": binding["version"], "sha256": binding["ref"]["sha256"]})
        self.assertEqual(revise.read(self.root / "revision/run-contract.json")["grouping_principles"], binding)
        new = revise.read(self.root / "revision/boards.json")
        other = next(row for row in new["boards"] if row["board_id"] == self.other["board_id"])
        self.assertEqual(other, self.other)
        changed = next(row for row in new["boards"] if row["board_id"] != self.other["board_id"])
        self.assertEqual(changed["unit_ids"], list(reversed([r["card_id"] for r in fake.calls[0]["payload"]["cards"]])))
        self.assertNotIn(self.plan["exclude_card_ids"][0], changed["unit_ids"])
        self.assertFalse(changed["independent_review"])
        self.assertIsNone(changed["validation"]["visual"])
        for member in changed["members"]:
            self.assertEqual(member["roi"], next(row["display_bbox"] for row in self.rows if row["card_id"] == member["unit_id"]))
        self.assertEqual(revise.read(self.root / "revision/revision-report.json")["superseded_board"], self.board)

    def test_fact_only_records_pending_A_and_never_calls_model(self):
        self.plan = self.make_plan("fact")
        fake = FakeModel()
        summary = self.run_revision(True, fake)
        self.assertEqual(summary["status"], "pending_A")
        self.assertFalse(fake.calls)
        boards = revise.read(self.root / "revision/boards.json")["boards"]
        self.assertEqual(boards[0]["members"], self.board["members"])
        self.assertEqual(boards[1], self.other)
        self.assertEqual(boards[0]["status"], "pending_A")

    def test_old_reference_biased_selection_reasons_do_not_enter_new_revision_request(self):
        """旧 v3 的参考颜色偏好只留出处；候选、当前用户问题和待核事实不丢失。"""
        sentinel = "HISTORICAL_REFERENCE_COLOR_SENTINEL_只选银白粉彩"

        def historical_answer(stage, payload, answer):
            answer = visual_answer([row["card_id"] for row in payload["cards"] if row["card_id"] != "c0"])
            answer["not_selected"].append({"card_id": "c0", "reason": "历史疑义"})
            for row in answer["not_selected"]:
                row["reason"] = "旧参考相似度不足：" + sentinel
            answer["dna_issues"] = [{"card_id": "c0", "reason": "历史声称相邻对象归属不清，尚未核实"}]
            return answer

        old_fake = FakeModel(historical_answer)

        def old_v3_executor(folder, **kwargs):
            kwargs["payload"] = deepcopy(kwargs["payload"])
            kwargs["payload"]["prompt_version"] = "prism-relational-grouping-20261010-v3"
            kwargs["system"] += "\n旧参考偏好：" + sentinel
            return old_fake(folder, **kwargs)

        self.rebuild_large_visual_pool(12, old_v3_executor)
        self.assertEqual(old_fake.calls[0]["payload"]["prompt_version"], "prism-relational-grouping-20261010-v3")
        self.save(self.feedback_path, {"issue": "本次真实反馈：红色块与细线的主次需要核对，不要求模仿参考配色"})
        self.plan = self.make_plan("relationship")
        self.plan["exclude_card_ids"] = ["c0"]
        old_answer_ref = deepcopy(self.board["provenance"]["answer_ref"])
        self.assertIn(sentinel, group.read_reference(old_answer_ref).decode())

        fake = FakeModel()
        self.run_revision(True, fake)
        self.assertEqual(len(fake.calls), 1)
        current = fake.calls[0]
        self.assertNotIn(sentinel, group.encoded(current))
        context = current["payload"]["revision_context"]
        self.assertNotIn("prior_not_selected", context)
        self.assertNotIn("previous_member_ids", context)
        self.assertEqual(context["feedback_as_observation_not_new_dna"], revise.read(self.feedback_path)["issue"])
        self.assertEqual(context["reason"], self.plan["reason"])
        self.assertEqual(context["historical_dna_issues_pending_A"], [{
            "card_id": "c0", "reported_issue": "历史声称相邻对象归属不清，尚未核实", "status": "unverified_pending_A"}])
        self.assertEqual({row["card_id"] for row in current["payload"]["cards"]}, {f"c{i}" for i in range(1, 12)})
        self.assertEqual(context["excluded_ids"], ["c0"])
        contract = revise.read(self.root / "revision/run-contract.json")
        self.assertIn(old_answer_ref, contract["evidence_refs"])
        self.assertIn(sentinel, group.read_reference(old_answer_ref).decode())

    def test_display_only_preserves_members_and_invalidates_review(self):
        self.plan = self.make_plan("display")
        fake = FakeModel()
        self.run_revision(True, fake)
        self.assertFalse(fake.calls)
        current = revise.read(self.root / "revision/boards.json")["boards"]
        self.assertEqual(current[0]["members"], self.board["members"])
        self.assertEqual(current[1], self.other)
        self.assertTrue(current[0]["review_invalidation"]["current_review_required"])
        self.assertEqual(revise.read(self.root / "revision/layout-overrides.json"), self.plan["layout_overrides"])

    def test_prior_other_board_layout_is_carried_without_change(self):
        prior = {self.other["unit_ids"][0]: {"height": 350}}
        self.save(self.source / "layout-overrides.json", prior)
        self.plan = self.make_plan("display")
        self.run_revision(True)
        self.assertEqual(revise.read(self.root / "revision/layout-overrides.json"), {**prior, **self.plan["layout_overrides"]})

    def test_input_hash_target_and_candidate_errors_do_not_call(self):
        mutations = [lambda p: p.update(board_id="another-board"),
                     lambda p: p["source_refs"]["boards"].update(sha256="wrong"),
                     lambda p: p.update(exclude_card_ids=["outside-pool"]),
                     lambda p: p.update(layout_overrides={self.board["unit_ids"][0]: {"roi": [0, 0, 1, 1]}})]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.plan = self.make_plan("relationship")
                mutate(self.plan)
                fake = FakeModel()
                with self.assertRaises(ValueError):
                    self.run_revision(True, fake)
                self.assertFalse(fake.calls)
                self.assertFalse((self.root / "revision").exists())

    def test_raw_answer_and_frozen_dna_cannot_be_relabelled(self):
        path = Path(self.board["provenance"]["answer_ref"]["path"])
        self.save(path, {"forged": True})
        with self.assertRaisesRegex(ValueError, "SHA"):
            self.run_revision(True)
        self.assertFalse((self.root / "revision").exists())

    def test_legacy_v3_answer_is_restored_with_its_schema_then_reselected_with_new_evidence(self):
        """只在合成夹具构造旧契约；真实历史记录绝不补字段或重标成新版通过。"""
        folder = Path(self.board["provenance"]["path"])
        answer = revise.read(folder / "answer.json")
        payload = revise.read(folder / "payload.json")
        schema = revise.read(folder / "schema.json")

        def without_new_evidence(row):
            row.pop("dominant_relation")
            for member in row["member_evidence"]:
                member.pop("relation_readability")
                member.pop("viewport_competition")
                member.pop("category_assignment")

        for row in answer["groups"]:
            without_new_evidence(row)
        group_schema = schema["properties"]["groups"]["items"]
        group_schema["properties"].pop("dominant_relation")
        group_schema["required"].remove("dominant_relation")
        member_schema = group_schema["properties"]["member_evidence"]["items"]
        for field in ("relation_readability", "viewport_competition", "category_assignment"):
            member_schema["properties"].pop(field)
            member_schema["required"].remove(field)
        payload["prompt_version"] = "prism-relational-grouping-20261010-v3"
        payload.pop("visual_evidence_version")
        payload.pop("assessed_visual_scope")
        payload.pop("category_assignment_version")
        self.save(folder / "answer.json", answer)
        self.save(folder / "schema.json", schema)
        self.save(folder / "payload.json", payload)
        (folder / "prompt.txt").write_text("合成历史请求\n=== ACTUAL PAYLOAD ===\n" + json.dumps(payload, ensure_ascii=False))
        old_answer_ref = group.reference(folder / "answer.json")
        for name in ("request", "receipt"):
            metadata = revise.read(folder / (name + ".json"))
            metadata.update(answer_ref=old_answer_ref, schema_ref=group.reference(folder / "schema.json"),
                            prompt_ref=group.reference(folder / "prompt.txt"))
            self.save(folder / (name + ".json"), metadata)
        for name, key in (("boards", "boards"), ("clusters", "clusters")):
            data = revise.read(self.source / (name + ".json"))
            row = next(row for row in data[key] if row["cluster_id"] == self.board["cluster_id"])
            without_new_evidence(row)
            row["provenance"]["answer_ref"] = old_answer_ref
            self.save(self.source / (name + ".json"), data)
        self.board = next(row for row in revise.read(self.source / "boards.json")["boards"]
                          if row["board_id"] == self.board["board_id"])
        self.plan = self.make_plan("relationship")
        fake = FakeModel()
        result = self.run_revision(True, fake)
        self.assertEqual(result["model_calls_this_execution"], 1)
        current = fake.calls[0]["payload"]
        self.assertEqual(current["prompt_version"], group.PROMPT_VERSION)
        self.assertEqual(current["visual_evidence_version"], group.VISUAL_EVIDENCE_VERSION)
        self.assertEqual({row["card_id"] for row in current["cards"]}, {row["card_id"] for row in payload["cards"]})
        new_board = next(row for row in revise.read(self.root / "revision/boards.json")["boards"]
                         if row["board_id"] != self.other["board_id"])
        self.assertIn("dominant_relation", new_board)
        self.assertIn("relation_readability", new_board["member_evidence"][0])
        self.assertNotIn("dominant_relation", json.loads(group.read_reference(old_answer_ref))["groups"][0])
        self.assertIn(old_answer_ref, revise.read(self.root / "revision/run-contract.json")["evidence_refs"])

    def test_legacy_readability_v2_keeps_own_schema_and_display_does_not_invent_category_pass(self):
        folder = Path(self.board["provenance"]["path"])
        answer, payload, schema = (revise.read(folder / name) for name in ("answer.json", "payload.json", "schema.json"))
        for row in answer["groups"]:
            for member in row["member_evidence"]:
                member.pop("category_assignment")
        member_schema = schema["properties"]["groups"]["items"]["properties"]["member_evidence"]["items"]
        member_schema["properties"].pop("category_assignment")
        member_schema["required"].remove("category_assignment")
        payload.pop("category_assignment_version")
        payload["prompt_version"] = "prism-relational-grouping-20261010-v5"
        self.assertEqual(payload["visual_evidence_version"], group.VISUAL_EVIDENCE_VERSION)
        for name, data in (("answer.json", answer), ("payload.json", payload), ("schema.json", schema)):
            self.save(folder / name, data)
        (folder / "prompt.txt").write_text("合成历史 v4 请求\n=== ACTUAL PAYLOAD ===\n" + json.dumps(payload, ensure_ascii=False))
        old_answer_ref = group.reference(folder / "answer.json")
        for name in ("request", "receipt"):
            metadata = revise.read(folder / (name + ".json"))
            metadata.update(answer_ref=old_answer_ref, schema_ref=group.reference(folder / "schema.json"),
                            prompt_ref=group.reference(folder / "prompt.txt"))
            self.save(folder / (name + ".json"), metadata)
        for name in ("boards", "clusters"):
            data = revise.read(self.source / (name + ".json"))
            row = next(row for row in data[name] if row["cluster_id"] == self.board["cluster_id"])
            for member in row["member_evidence"]:
                member.pop("category_assignment")
            row["constraints"].pop("category_limit")
            row["provenance"]["answer_ref"] = old_answer_ref
            self.save(self.source / (name + ".json"), data)
        self.board = next(row for row in revise.read(self.source / "boards.json")["boards"]
                          if row["board_id"] == self.board["board_id"])
        self.plan = self.make_plan("display")
        fake = FakeModel()
        displayed = self.run_revision(True, fake, out="display-legacy")
        self.assertEqual(displayed["category_limit_this_execution"], "not_evaluated_no_member_reselection")
        self.assertFalse(fake.calls)
        old_board = next(row for row in revise.read(self.root / "display-legacy/boards.json")["boards"]
                         if row["board_id"] == self.board["board_id"])
        self.assertNotIn("category_limit", old_board["constraints"])
        self.plan = self.make_plan("relationship")
        result = self.run_revision(True, fake)
        self.assertEqual(result["category_limit_this_execution"], "checked_on_new_model_groups")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["payload"]["category_assignment_version"], group.CATEGORY_ASSIGNMENT_VERSION)
        current = next(row for row in revise.read(self.root / "revision/boards.json")["boards"]
                       if row["board_id"] != self.other["board_id"])
        self.assertEqual(current["constraints"]["category_limit"]["status"], "passed")
        self.assertNotIn("category_assignment", json.loads(group.read_reference(old_answer_ref))["groups"][0]["member_evidence"][0])

    def test_new_issue_name_does_not_reset_same_feedback_limit(self):
        issue = revise.fingerprint([self.plan["feedback_ref"]["sha256"], "/issue"])
        history = [{"issue_key": "old-name", "issue_fingerprint": issue} for _ in range(3)]
        for name in ("boards", "clusters"):
            path = self.source / (name + ".json")
            value = revise.read(path)
            value["revision_history"] = history
            self.save(path, value)
        self.plan = self.make_plan("display")
        with self.assertRaisesRegex(ValueError, "三轮"):
            self.run_revision(True)
        self.assertFalse((self.root / "revision").exists())

    def test_model_failure_retains_diagnostic_board_and_terminal_history(self):
        def fail(*args, **kwargs):
            raise ValueError("synthetic failure")
        result = self.run_revision(True, fail)
        self.assertEqual(result["status"], "revision_incomplete")
        current = revise.read(self.root / "revision/boards.json")["boards"]
        self.assertEqual(current[0]["members"], self.board["members"])
        self.assertEqual(current[1], self.other)
        self.assertEqual(revise.read(self.root / "revision/call-ledger.json")["calls"][0]["status"], "failed_no_retry")
        with self.assertRaisesRegex(ValueError, "全新目录"):
            self.run_revision(True)

    def render_fixture(self, overrides=True):
        layout = self.root / "layout.json"
        self.save(layout, self.make_plan("display")["layout_overrides"])
        args = argparse.Namespace(run_dir=self.source, out=self.root / "delivery", sample=self.sample,
            observations=self.source / "observations.compat.json", clusters=None, boards=None, reviews=None,
            history_delivery=[], layout_overrides=layout if overrides else None)
        delivery.render(args)
        return args.out

    def test_render_binds_layout_and_preserves_original_bytes(self):
        out = self.render_fixture()
        manifest = revise.read(out / "delivery-manifest.json")
        board = manifest["boards"][0]
        self.assertTrue(board["layout_binding"]["overrides"])
        self.assertEqual([m["roi"] for m in board["members"]], [m["roi"] for m in self.board["members"]])
        self.assertEqual(board["validation_display"][0]["state"], "pending")
        self.assertTrue(all(group.digest(out / asset["path"]) == asset["sha256"] for asset in manifest["assets"]))
        html = (out / board["path"]).read_text()
        self.assertIn(board["layout_identity"], html)
        self.assertIn("--tile-height:460px", html)
        self.assertFalse(delivery.review_matches_layout({"visual_verdict": "coherent"}, board["layout_binding"]))

    def test_layout_identity_changes_with_scale_and_old_capture_is_rejected(self):
        first = delivery.layout_binding(self.board, {self.board["unit_ids"][0]: {"height": 400}})
        second = delivery.layout_binding(self.board, {self.board["unit_ids"][0]: {"height": 500}})
        self.assertNotEqual(first["identity"], second["identity"])
        capture = self.root / "capture.json"
        self.save(capture, {"layout_identity": first["identity"]})
        review = {"provenance": {"capture_record_ref": group.reference(capture)}}
        self.assertTrue(delivery.review_matches_layout(review, first))
        self.assertFalse(delivery.review_matches_layout(review, second))

    def test_removing_override_cannot_inherit_its_old_layout_review(self):
        old_binding = delivery.layout_binding(self.board, {self.board["unit_ids"][0]: {"height": 500}})
        capture = self.root / "old-capture.json"
        self.save(capture, {"layout_identity": old_binding["identity"]})
        boards_path = self.source / "boards.json"
        document = revise.read(boards_path)
        document["boards"][0]["review_provenance"] = {"capture_record_ref": group.reference(capture)}
        document["boards"][0]["validation"] = {"visual": True}
        self.save(boards_path, document)
        out = self.render_fixture(overrides=False)
        manifest = revise.read(out / "delivery-manifest.json")
        current = manifest["boards"][0]
        self.assertEqual(current["layout_binding"]["overrides"], {})
        self.assertEqual(current["validation_display"][0]["state"], "pending")
        self.assertIn('"current_layout_review_pending":true', (out / current["path"]).read_text())

    def test_priority_scope_uses_requested_goal_and_separates_ID_coverage(self):
        rendered = delivery.grouping_scope_html({"mode": "priority_boards", "priority_goal": {"target_boards": 3},
            "branch_coverage": {"ID": {"input_cards": 10, "route_compared_cards": 0,
                "actually_visually_compared": 0, "not_selected_direction": 10}}})
        self.assertIn("目标 3 张", rendered)
        self.assertIn("ID：输入 10 卡，DNA 路由比较 0 卡", rendered)
        self.assertIn("不代表所有方向已评估", rendered)
        self.assertIn("CMF 结果不替 ID 作证", rendered)

    @unittest.skipUnless(os.environ.get("PRISM_BROWSER_TEST") == "1", "显式启用极小离线浏览器验证")
    def test_narrow_screen_and_original_modal(self):
        out = self.render_fixture()
        subprocess.run(["node", str(SCRIPTS / "capture_boards.cjs"), "--delivery", str(out),
                        "--out", str(self.root / "captures")], check=True)
        captures = revise.read(self.root / "captures/capture-manifest.json")
        self.assertEqual(captures["status"], "passed")
        current = revise.read(self.root / "captures" / (self.board["board_id"] + ".png.json"))
        self.assertFalse(current["mobile"]["overflow"])
        self.assertTrue(current["layout_identity"])
        # 平板三列与桌面四列的边界同样不能被 span=4 撑出隐式列。
        script = """const {chromium}=require('/tmp/bubble-ui-check/node_modules/playwright');
        (async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
        try{const page=await browser.newPage({viewport:{width:850,height:1000}});
        await page.goto(process.argv[1]);await page.waitForFunction(()=>window.__prismReady);
        if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('tablet overflow');
        const columns=await page.locator('#board-grid').evaluate(n=>getComputedStyle(n).gridTemplateColumns.split(' ').length);
        if(columns!==3)throw Error('implicit tablet column');}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});"""
        subprocess.run(["node", "-e", script, (out / "boards" / (self.board["board_id"] + ".html")).as_uri()], check=True)


if __name__ == "__main__":
    unittest.main()
