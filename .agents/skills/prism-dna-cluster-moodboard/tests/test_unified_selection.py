"""统一队列和冲突闭环的离线测试；合成结论不充当审美准确率。"""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_llm_group import group, FakeModel, cards, document, relation_template, visual_answer


def unified_answer(ids):
    answer = visual_answer(ids)
    selected = {i for row in answer["groups"] for i in row["member_ids"]}
    answer["relation_hypotheses"] = [{
        "relation_key": "r1", "dominant_relation": answer["groups"][0]["dominant_relation"],
        "must_hold": [{"dimension": "planes", "condition": "合成平面层级必须成立"}],
        "allowed_variations": ["合成不同材料可协调"], "break_conditions": ["合成主导体量冲突"]}]
    answer["candidate_decisions"] = [{"card_id": i, "relation_key": "r1", "decision": "include" if i in selected else "exclude",
                                     "dominant_evidence": "合成可见组织", "strongest_conflict": "合成差异",
                                     "conflict_effect": "compatible_variation", "reason": "假模型判定"} for i in ids]
    for row in answer["groups"]:
        row["relation_key"] = "r1"
        row["hardest_pair"]["verdict"] = "coherent"
        for evidence in row["member_evidence"]:
            evidence["decision_basis"] = evidence.pop("why_coordinated")
    answer["feedback_decisions"] = []
    return answer


def adapt(stage, payload, answer):
    return unified_answer([c["card_id"] for c in payload["cards"]]) if stage == "visual" else answer


class UnifiedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rows = cards(self.root)
        for index, row in enumerate(self.rows):
            row["branch"] = "ID" if index % 2 else "CMF"

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, fake=None):
        return group.ModelCalls(self.root / "run", group.POLICY.read_text(), workers=1, max_calls=40,
                                execute=fake or FakeModel(adapt), comparison_mode="unified")

    def test_mixed_cards_share_discovery_route_and_visual_without_mutating_dna(self):
        original = copy.deepcopy(self.rows)
        fake = FakeModel(adapt)
        result = group.run_pipeline(document(self.rows), self.runner(fake))
        self.assertEqual(self.rows, original)
        for stage in ("discover", "route", "visual"):
            payloads = [c["payload"] for c in fake.calls if c["payload"]["task"] == stage]
            self.assertEqual(len(payloads), 1)
            self.assertEqual({c["branch"] for c in payloads[0]["cards"]}, {"ID", "CMF"})
        self.assertEqual(result["boards"]["boards"][0]["branch"], "DESIGN")
        self.assertTrue(result["boards"]["summary"]["unified_coverage"]["all_cards_routed"])
        for call in fake.calls:
            self.assertNotIn("CMF 主导", call["system"])
            for card in call["payload"].get("cards", []):
                self.assertNotIn("design_emotion", card)
                self.assertNotIn("design_quality", card)
                self.assertIn("single_image_counter_signals", card)
                self.assertEqual(set(card["relations"]), set(group.RELATIONS))

    def test_old_cmf_direction_recalls_id_cards_without_repeating_direction_selection(self):
        fake = FakeModel(adapt)
        template = {**relation_template(["c0", "c2"]), "template_id": "old-cmf-direction", "branch": "CMF",
                    "candidate_ids": ["c0", "c2"], "provenance": {}}
        result = group.run_pipeline(document(self.rows), self.runner(fake), mode="priority_boards", target_boards=3,
                                    direction_limit=1, selected_template_ids=[template["template_id"]],
                                    template_catalogue={"local": [], "merged": [template], "source_ref": {}})
        stages = [c["payload"]["task"] for c in fake.calls]
        self.assertNotIn("select_directions", stages)
        routed = [c for call in fake.calls if call["payload"]["task"] == "route" for c in call["payload"]["cards"]]
        self.assertEqual(len(routed), len(self.rows))
        self.assertEqual(result["boards"]["boards"][0]["branch"], "DESIGN")

    def visual_task(self):
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "DESIGN"}
        raw = group.make_visual_task(template, [r["card_id"] for r in self.rows],
                                     {r["card_id"]: r for r in self.rows}, self.root / "views", 0)
        return self.runner().prepare_task(raw)

    def test_conflict_or_unknown_cannot_be_selected_despite_a_fluent_explanation(self):
        task = self.visual_task()
        for effect in ("dominant_conflict", "uncertain"):
            answer = unified_answer([r["card_id"] for r in self.rows])
            answer["candidate_decisions"][0]["conflict_effect"] = effect
            with self.assertRaises(ValueError):
                group.validate_task_answer(answer, task)

    def test_hardest_pair_conflict_blocks_group(self):
        task = self.visual_task()
        answer = unified_answer([r["card_id"] for r in self.rows])
        answer["groups"][0]["hardest_pair"]["verdict"] = "conflict"
        with self.assertRaisesRegex(ValueError, "最不一致对"):
            group.validate_task_answer(answer, task)

    def test_broadening_relation_after_decision_is_rejected(self):
        task = self.visual_task()
        answer = unified_answer([r["card_id"] for r in self.rows])
        answer["groups"][0]["dominant_relation"] = "改成更宽泛的温和有序"
        with self.assertRaisesRegex(ValueError, "改宽"):
            group.validate_task_answer(answer, task)

    def test_missing_or_invented_candidate_decision_is_rejected(self):
        task = self.visual_task()
        answer = unified_answer([r["card_id"] for r in self.rows])
        answer["candidate_decisions"].pop()
        with self.assertRaisesRegex(ValueError, "覆盖"):
            group.validate_task_answer(answer, task)

    def test_relative_output_still_produces_absolute_image_attachments(self):
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "DESIGN"}
        task = group.make_visual_task(template, [r["card_id"] for r in self.rows],
                                     {r["card_id"]: r for r in self.rows},
                                     Path(os.path.relpath(self.root / "relative-views")), 0)
        self.assertTrue(all(Path(i["path"]).is_absolute() for i in task["images"]))
        task["images"][0]["path"] = "relative-original.png"
        with self.assertRaises(ValueError):
            self.runner().run([task])

    def test_feedback_reaches_visual_request_and_missing_decision_blocks_success(self):
        registry = {"issues": [{"issue_id": "current-issue", "affected_card_ids": ["c0"],
                               "context_card_ids": ["c1"], "issue_kind": "relationship",
                               "observation": "合成主导冲突", "resolution_condition": "仍待人工确认"}]}
        fake = FakeModel(adapt)
        runner = group.ModelCalls(self.root / "feedback-run", "", workers=1, max_calls=1,
                                 execute=fake, comparison_mode="unified", feedback_registry=registry)
        task = runner.prepare_task(self.visual_task())
        self.assertEqual(task["payload"]["active_feedback"][0]["issue_id"], "current-issue")
        result = runner.run([task])[0]
        self.assertEqual(result["record"]["status"], "failed_no_retry")
        self.assertIsNone(result["answer"])
        self.assertEqual(len(fake.calls), 1)

    def test_feedback_inherits_and_cannot_be_dropped_by_replacement(self):
        cards_path = self.root / "cards.json"
        cards_path.write_text(json.dumps({"cards": self.rows}))
        prepared = self.root / "prepared.json"
        prepared.write_text(json.dumps({"schema_version": "prism.design_cards_prepared.v1",
                                        "design_cards_ref": group.reference(cards_path)}))
        source = self.root / "feedback.json"
        source.write_text(json.dumps({"issue": "合成反馈"}))
        registry = {"schema_version": group.unified_module().feedback_module().VERSION,
                    "prepared_ref": group.reference(prepared), "issues": [{
                        "issue_id": "current-issue", "feedback_ref": group.reference(source), "feedback_pointer": "/issue",
                        "affected_card_ids": ["c0"], "context_card_ids": ["c1"], "issue_kind": "relationship",
                        "observation": "合成冲突", "resolution_condition": "仍待确认"}]}
        inherited = self.root / "feedback-registry.json"
        inherited.write_text(json.dumps(registry))
        loaded, ref = group.load_run_feedback(None, self.root, prepared, self.rows)
        self.assertEqual(loaded, registry)
        self.assertEqual(ref, group.reference(inherited))
        replacement = self.root / "replacement.json"
        replacement.write_text(json.dumps({**registry, "issues": []}))
        with self.assertRaisesRegex(ValueError, "静默丢弃"):
            group.load_run_feedback(replacement, self.root, prepared, self.rows)


if __name__ == "__main__":
    unittest.main()
