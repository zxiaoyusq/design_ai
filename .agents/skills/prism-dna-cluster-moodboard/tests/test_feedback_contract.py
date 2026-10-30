"""反馈身份与成员约束的离线测试；不判断合成关系是否具有审美质量。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import feedback_contract as feedback


class FeedbackContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prism-feedback-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cards = [{"card_id": i, "image_sha256": i * 64, "display_bbox": [0, 0, 1, 1],
                       "evidence_bbox": [0, 0, 1, 1], "display_scope": "whole_object",
                       "bbox_format": "xywh_normalized", "subject": {"identity": "对象" + i,
                           "bbox": [0, 0, 1, 1], "role": "primary_object", "whole_visible": True}}
                      for i in ("a", "b", "c", "d")]
        cards_path = self.save("cards.json", {"cards": self.cards})
        self.prepared = self.save("prepared.json", {"schema_version": "prism.design_cards_prepared.v1",
                                                   "design_cards_ref": self.ref(cards_path)})
        self.source = self.save("feedback.json", {"issues": [{"text": "合成对照：厚薄关系未协调"}]})
        self.registry = {"schema_version": feedback.VERSION, "prepared_ref": self.ref(self.prepared), "issues": [{
            "issue_id": "same-object-conflict", "feedback_ref": self.ref(self.source), "feedback_pointer": "/issues/0/text",
            "affected_card_ids": ["a"], "context_card_ids": ["b", "c"], "issue_kind": "relationship",
            "observation": "合成对照：厚薄关系未协调", "resolution_condition": "按实际新组合重新比较，用户问题保持未销项"}]}
        self.path = self.save("registry.json", self.registry)

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def ref(self, path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def load(self):
        self.save("registry.json", self.registry)
        return feedback.load_feedback(self.path, self.prepared, self.cards)

    def payload(self, ids=("a", "b", "c", "d")):
        return {"cards": [row for row in self.cards if row["card_id"] in ids],
                "active_feedback": feedback.relevant_feedback(self.load(), list(ids))}

    def answer(self, members=("a", "b"), decision="retained_with_evidence"):
        return {"groups": [{"member_ids": list(members)}], "feedback_decisions": [{
            "issue_id": "same-object-conflict", "affected_card_ids": ["a"], "decision": decision,
            "evidence": {"observation": "合成成员比较依据", "compared_card_ids": sorted(set(members) | {"a"}),
                         "context_change": "合成新组已改变比较对象", "remaining_uncertainty": "仍等待设计师确认"}}]}

    def add_alias(self, source, alias_id, **changes):
        row = deepcopy(next(card for card in self.cards if card["card_id"] == source))
        row.update(card_id=alias_id, **changes)
        self.cards.append(row)

    def freeze_added_cards(self):
        cards_path = self.save("cards.json", {"cards": self.cards})
        self.save("prepared.json", {"schema_version": "prism.design_cards_prepared.v1",
                                    "design_cards_ref": self.ref(cards_path)})
        self.registry["prepared_ref"] = self.ref(self.prepared)

    def alias_payload(self, ids):
        registry = self.load()
        aliases = feedback.build_feedback_aliases(registry, self.cards)
        return {"cards": [row for row in self.cards if row["card_id"] in ids],
                "active_feedback": feedback.relevant_feedback(registry, ids, aliases=aliases)}

    def test_load_and_projection_preserve_all_original_issues(self):
        loaded = self.load()
        active = feedback.relevant_feedback(loaded, ["a", "d"])
        self.assertEqual(active[0]["affected_card_ids"], ["a"])
        self.assertEqual(active[0]["missing_context_card_ids"], ["b", "c"])
        self.assertFalse(active[0]["context_fully_present"])
        active[0]["observation"] = "修改投影不改注册表"
        self.assertEqual(loaded, self.registry)
        self.assertEqual(feedback.relevant_feedback(loaded, ["d"]), [])

    def test_changed_prepared_rejected(self):
        other = self.save("other-prepared.json", json.loads(self.prepared.read_text()))
        with self.assertRaisesRegex(ValueError, "同一冻结"):
            feedback.load_feedback(self.path, other, self.cards)

    def test_source_changed_rejected(self):
        self.save("feedback.json", {"issues": []})
        with self.assertRaisesRegex(ValueError, "SHA"):
            self.load()

    def test_frozen_card_content_not_just_ids_is_bound(self):
        changed = deepcopy(self.cards)
        changed[0]["display_bbox"] = [0, 0, 0.2, 0.2]
        with self.assertRaisesRegex(ValueError, "冻结卡"):
            feedback.load_feedback(self.path, self.prepared, changed)

    def test_unknown_card_and_missing_pointer_rejected(self):
        for field, value in (("affected_card_ids", ["forged"]), ("feedback_pointer", "/issues/9")):
            with self.subTest(field=field):
                old = self.registry["issues"][0][field]
                self.registry["issues"][0][field] = value
                with self.assertRaises(ValueError):
                    self.load()
                self.registry["issues"][0][field] = old

    def test_html_anchor_and_json_pointer_escaping(self):
        html = self.root / "feedback.html"
        html.write_text('<article id="board-1">真实反馈定位</article>')
        issue = self.registry["issues"][0]
        issue.update(feedback_ref=self.ref(html), feedback_pointer="#board-1")
        self.load()
        issue["feedback_pointer"] = "#missing"
        with self.assertRaises(ValueError):
            self.load()
        escaped = self.save("escaped.json", {"a/b": {"~value": "意见"}})
        issue.update(feedback_ref=self.ref(escaped), feedback_pointer="/a~1b/~0value")
        self.load()
        issue["feedback_pointer"] = "/a~2b"
        with self.assertRaises(ValueError):
            self.load()

    def test_missing_duplicate_and_forged_issue_responses_rejected(self):
        for mode in ("missing", "duplicate", "forged"):
            answer = self.answer()
            if mode == "missing":
                answer["feedback_decisions"] = []
            elif mode == "duplicate":
                answer["feedback_decisions"] *= 2
            else:
                answer["feedback_decisions"][0]["issue_id"] = "another"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                feedback.validate_feedback_decisions(answer, self.payload())

    def test_unresolved_excluded_and_fact_members_cannot_enter_group(self):
        for decision in ("unresolved", "excluded_from_this_group"):
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, "不得入组"):
                feedback.validate_feedback_decisions(self.answer(decision=decision), self.payload())
        self.registry["issues"][0]["issue_kind"] = "fact"
        with self.assertRaisesRegex(ValueError, "不得入组"):
            feedback.validate_feedback_decisions(self.answer(), self.payload())

    def test_same_image_new_context_is_not_permanently_blacklisted(self):
        answer = self.answer(members=("a", "d"), decision="context_changed")
        payload = self.payload(("a", "d"))
        before = deepcopy(payload)
        feedback.validate_feedback_decisions(answer, payload)
        self.assertEqual(payload, before)
        self.assertEqual(self.load(), self.registry)

    def test_title_change_or_part_of_old_context_cannot_release_issue(self):
        answer = self.answer(members=("a", "b", "d"), decision="context_changed")
        answer["groups"][0]["title"] = "新版主题"
        with self.assertRaisesRegex(ValueError, "原问题上下文"):
            feedback.validate_feedback_decisions(answer, self.payload(("a", "b", "d")))

    def test_model_cannot_close_designer_issue(self):
        answer = self.answer()
        answer["feedback_decisions"][0]["resolved_by_designer"] = True
        with self.assertRaisesRegex(ValueError, "销项"):
            feedback.validate_feedback_decisions(answer, self.payload())

    def test_feedback_with_no_selection_can_remain_unresolved(self):
        answer = self.answer(members=("b", "d"), decision="unresolved")
        feedback.validate_feedback_decisions(answer, self.payload())

    def test_comparison_objects_need_not_repeat_explicitly_affected_target(self):
        answer = self.answer(members=("a", "d"))
        answer["feedback_decisions"][0]["evidence"]["compared_card_ids"] = ["d"]
        before = deepcopy(answer)
        feedback.validate_feedback_decisions(answer, self.payload())
        self.assertEqual(answer, before)

    def test_union_scope_still_rejects_missing_target_or_foreign_comparator(self):
        for mode in ("missing_target", "foreign_comparator", "comparator_not_in_group"):
            answer = self.answer(members=("a", "d"))
            response = answer["feedback_decisions"][0]
            response["evidence"]["compared_card_ids"] = ["d"]
            if mode == "missing_target":
                response["affected_card_ids"] = ["b"]
            elif mode == "foreign_comparator":
                response["evidence"]["compared_card_ids"] = ["forged"]
            else:
                response["evidence"]["compared_card_ids"] = ["b"]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                feedback.validate_feedback_decisions(answer, self.payload())

    def test_old_request_does_not_receive_fabricated_feedback(self):
        feedback.validate_feedback_decisions({"groups": []}, {"cards": self.cards})
        with self.assertRaises(ValueError):
            feedback.validate_feedback_decisions(self.answer(), {"cards": self.cards})

    def test_fact_feedback_cannot_be_escaped_with_same_object_id_card(self):
        self.add_alias("a", "a-ID", branch="ID")
        self.freeze_added_cards()
        self.registry["issues"][0]["issue_kind"] = "fact"
        payload = self.alias_payload(["a-ID", "d"])
        issue = payload["active_feedback"][0]
        self.assertEqual(issue["affected_card_ids"], ["a"])
        self.assertEqual(issue["current_affected_card_ids"], ["a-ID"])
        self.assertEqual(issue["source_card_aliases"]["a"], ["a", "a-ID"])
        answer = self.answer(members=("a-ID", "d"))
        answer["feedback_decisions"][0]["affected_card_ids"] = ["a-ID"]
        answer["feedback_decisions"][0]["evidence"]["compared_card_ids"] = ["a-ID", "d"]
        with self.assertRaisesRegex(ValueError, "不得入组"):
            feedback.validate_feedback_decisions(answer, payload)
        self.assertEqual(self.load(), self.registry)

    def test_context_alias_cannot_claim_context_changed(self):
        self.add_alias("b", "b-ID", branch="ID")
        self.freeze_added_cards()
        payload = self.alias_payload(["a", "b-ID", "d"])
        issue = payload["active_feedback"][0]
        self.assertEqual(issue["current_context_card_ids"], ["b-ID"])
        self.assertEqual(issue["missing_context_card_ids"], ["c"])
        answer = self.answer(members=("a", "b-ID", "d"), decision="context_changed")
        with self.assertRaisesRegex(ValueError, "原问题上下文"):
            feedback.validate_feedback_decisions(answer, payload)

    def test_same_image_other_object_crop_or_evidence_scope_does_not_inherit(self):
        subject = deepcopy(self.cards[0]["subject"])
        subject["identity"] = "同图另一个物品"
        changes = [
            {"subject": subject}, {"display_bbox": [0, 0, 0.5, 0.5]},
            {"evidence_bbox": [0, 0, 0.5, 0.5]}, {"display_scope": "representative_detail"},
            {"evidence_scope": "new_scope"}, {"bbox_format": "xyxy_normalized"},
            {"image_sha256": "f" * 64},
        ]
        ids = []
        for index, changed in enumerate(changes):
            identity = "different-" + str(index)
            ids.append(identity)
            self.add_alias("a", identity, **changed)
        self.freeze_added_cards()
        self.assertEqual(self.alias_payload(ids)["active_feedback"], [])

    def test_aliases_require_complete_and_unmodified_frozen_cards(self):
        self.add_alias("a", "a-ID")
        self.freeze_added_cards()
        registry = self.load()
        modified = deepcopy(self.cards)
        modified[-1]["subject"]["identity"] = "调用方私自修改的对象"
        with self.assertRaisesRegex(ValueError, "冻结卡"):
            feedback.build_feedback_aliases(registry, modified)
        with self.assertRaisesRegex(ValueError, "冻结卡"):
            feedback.build_feedback_aliases(registry, self.cards[:1])

    def test_missing_object_identity_is_not_inferred_from_image_sha(self):
        self.add_alias("a", "incomplete")
        del self.cards[0]["subject"]
        del self.cards[-1]["subject"]
        self.freeze_added_cards()
        self.assertEqual(self.alias_payload(["incomplete", "d"])["active_feedback"], [])


if __name__ == "__main__":
    unittest.main()
