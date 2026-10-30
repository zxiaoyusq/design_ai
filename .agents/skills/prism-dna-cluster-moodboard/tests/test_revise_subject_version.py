"""离线核对定点修订的新旧观察版本，避免把主体字段误标为旧协议。"""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import observe_sample as observer
import render_delivery
import revise_boards
import revise_units
import supplement_design_emotion
from design_emotion import bind_emotion, primary_subject_binding
from test_design_emotion import interpretation, source
from test_observe_subject_contract import unit, selected_unit


def revision_fixture():
    old = {**unit(legacy=True), "unit_id": "i:CMF:1", "image_id": "i", "image_sha256": "sha",
           "feature_definition_version": observer.LEGACY_VERSION}
    new = {**old, **selected_unit(), "feature_definition_version": observer.VERSION}
    base = {"units": [old], "images": [{"image_id": "i", "units": [old]}]}
    patch = {"revisions": [{"previous": old, "revised": new}],
             "model_answer_ref": {"path": "/synthetic/answer.json", "sha256": "answer"},
             "independent_review_ref": {"path": "/synthetic/review.json", "sha256": "review"}}
    return base, patch


class RevisionVersionTests(unittest.TestCase):
    def test_new_subject_observation_cannot_keep_old_version(self):
        base, patch = revision_fixture()
        patch["revisions"][0]["revised"]["feature_definition_version"] = observer.LEGACY_VERSION
        with self.assertRaisesRegex(ValueError, "feature_definition_version不一致"):
            revise_units.apply_revisions(base, patch)

    def test_new_observation_version_is_preserved_in_both_indices(self):
        base, patch = revision_fixture()
        original = deepcopy(base)
        result = revise_units.apply_revisions(base, patch)
        self.assertEqual(result["units"][0]["feature_definition_version"], observer.VERSION)
        self.assertEqual(result["images"][0]["units"], result["units"])
        self.assertEqual(base, original)
        self.assertNotIn("primary_subject", base["units"][0])

    def test_old_offline_patch_remains_legacy_without_backfilling(self):
        base, patch = revision_fixture()
        patch["revisions"][0]["revised"] = {**base["units"][0], "evidence": "原协议修订依据"}
        result = revise_units.apply_revisions(base, patch)
        self.assertEqual(result["units"][0]["feature_definition_version"], observer.LEGACY_VERSION)
        self.assertNotIn("primary_subject", result["units"][0])

    def test_unit_revision_invalidates_shared_image_emotion_and_preserves_history(self):
        base, patch = revision_fixture()
        previous = patch["revisions"][0]["revised"]
        previous.update(design_emotion=interpretation(), design_emotion_provenance=source())
        sibling = {**deepcopy(previous), "unit_id": "i:CMF:2"}
        base = {"units": [previous, sibling], "images": [{"image_id": "i", "sha256": "sha", "status": "observed",
                "units": [previous, sibling], "design_emotion": interpretation(), "design_emotion_provenance": source()}]}
        original = deepcopy(base)
        patch["revisions"] = [{"previous": deepcopy(previous), "revised": {**deepcopy(previous), "evidence": "新的事实依据"}}]
        result = revise_units.apply_revisions(base, patch)
        self.assertTrue(all(member["design_emotion"] is None for member in result["units"]))
        self.assertEqual(result["images"][0]["design_emotion_status"], "needs_recheck")
        self.assertEqual(result["unit_revision_history"][-1]["invalidated_design_emotions"][0]["previous_image_emotion"], interpretation())
        self.assertEqual(len(supplement_design_emotion.select_targets(result)[0]), 1)
        self.assertEqual(base, original)

    def test_v3_revision_keeps_other_peer_object_emotion(self):
        base, patch = revision_fixture()
        first = deepcopy(patch["revisions"][0]["revised"])
        second = {**deepcopy(first), "unit_id": "i:CMF:2", "target_role": "peer_object_surface"}
        second["primary_subject"].update(identity="右侧另一设计对象", bbox=[0.7, 0.1, 0.2, 0.3])
        image = {"image_id": "i", "sha256": "sha", "status": "observed", "units": [first, second]}
        for member in image["units"]:
            member.update(bind_emotion(interpretation(), image, primary_subject_binding([member]), source()))
        base = {"images": [image], "units": image["units"]}
        peer_before = deepcopy(second)
        patch["revisions"] = [{"previous": deepcopy(first), "revised": {**deepcopy(first), "evidence": "新事实依据"}}]
        result = revise_units.apply_revisions(base, patch)
        self.assertIsNone(result["units"][0]["design_emotion"])
        self.assertEqual(result["units"][1], peer_before)
        targets, _ = supplement_design_emotion.select_targets(result)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["subjects"][0]["unit_ids"], [first["unit_id"]])

    def test_v3_same_object_coordinate_tail_invalidates_all_members_and_can_supplement(self):
        _, patch = revision_fixture()
        first = deepcopy(patch["revisions"][0]["revised"])
        sibling = {**deepcopy(first), "unit_id": "i:CMF:2"}
        sibling["primary_subject"]["bbox"][0] += 0.000005
        image = {"image_id": "i", "sha256": "sha", "status": "observed", "units": [first, sibling]}
        for member in image["units"]:
            member.update(bind_emotion(interpretation(), image, primary_subject_binding([member]), source()))
        observer.validate_primary_binding(image["units"])
        base = {"images": [image], "units": image["units"]}
        original = deepcopy(base)
        patch["revisions"] = [{"previous": deepcopy(first), "revised": {**deepcopy(first), "evidence": "当前连接事实修订"}}]
        result = revise_units.apply_revisions(base, patch)
        self.assertTrue(all(member["design_emotion"] is None for member in result["units"]))
        self.assertEqual(base, original)
        history = result["unit_revision_history"][-1]["invalidated_design_emotions"][0]
        self.assertEqual(len(history["previous_unit_emotions"]), 2)
        targets, skipped = supplement_design_emotion.select_targets(result)
        self.assertEqual(skipped, [])
        self.assertEqual(len(targets), 1)
        group = targets[0]["subjects"][0]
        self.assertEqual(set(group["unit_ids"]), {first["unit_id"], sibling["unit_id"]})
        entry = {"image_id": "i", "image_sha256": "sha", **group,
                 **bind_emotion(interpretation(), image, group["primary_subject"], source())}
        restored = supplement_design_emotion.apply_supplement(result, [entry])
        self.assertTrue(all(member["design_emotion"] is not None for member in restored["units"]))

    def test_revision_cannot_silently_switch_to_another_same_image_object(self):
        _, patch = revision_fixture()
        old = deepcopy(patch["revisions"][0]["revised"])
        old["primary_subject"].update(identity="左侧单椅", bbox=[0.05, 0.1, 0.4, 0.7])
        base = {"images": [{"image_id": "i", "units": [old]}], "units": [old]}
        for identity in ("右侧茶几", "左侧单椅"):
            revised = deepcopy(old)
            revised["primary_subject"].update(identity=identity, bbox=[0.6, 0.1, 0.3, 0.7])
            patch["revisions"] = [{"previous": old, "revised": revised}]
            with self.assertRaisesRegex(ValueError, "另一个对象须建立新观察单元"):
                revise_units.apply_revisions(base, patch)
        corrected = deepcopy(old)
        corrected["primary_subject"]["bbox"] = [0.04, 0.09, 0.42, 0.72]
        patch["revisions"] = [{"previous": old, "revised": corrected}]
        result = revise_units.apply_revisions(base, patch)
        self.assertEqual(result["units"][0]["primary_subject"], corrected["primary_subject"])


def board_fixture(*, legacy=False):
    members = [{"unit_id": f"u{i}", "image_id": f"i{i}", "sha256": f"sha{i}",
                "roi": [0, 0, 1, 1], "source_article_keys": [f"a{i}"],
                "project_key": f"p{i}", "project_state": "source_supported", "runway_state": "no"}
               for i in range(6)]
    if not legacy:
        for member in members:
            member.update({"display_bbox": [0, 0, 1, 1], "evidence_bbox": [0.2, 0.2, 0.5, 0.5],
                           "primary_subject": {"bbox": [0.1, 0.1, 0.8, 0.8]}})
    boards = {"boards": [{"board_id": "B", "members": members, "alternates": []}]}
    reviews = {"reviews": [{"board_id": "B", "visual_verdict": "needs_revision", "members": [
        {"unit_id": member["unit_id"], "scope_correct": False, "keep": False,
         "relation_supported": True, "image_quality": "usable", "suggested_roi": [0.05, 0.05, 0.9, 0.9]}
        for member in members]}]}
    plan = {"changes": [{"board_id": "B", "actions": [{"unit_id": "u0", "kind": "roi",
             "roi": [0.05, 0.05, 0.9, 0.9], "reason": "合成实审建议，仅调整主体周围留白"}]}]}
    return boards, reviews, plan


class BoardDisplayRevisionTests(unittest.TestCase):
    def selected_fixture(self):
        boards, reviews, plan = board_fixture()
        for member in boards["boards"][0]["members"]:
            member.update(feature_definition_version=revise_boards.SELECTED_OBJECT_VERSION,
                          branch="CMF", target_role="peer_object_surface", display_scope="representative_detail",
                          crop_reason="合成：同级座椅的连续缝线与配色是可独立阅读的设计表达",
                          whole_object_visible=False)
            member["primary_subject"].update(identity="同级座椅", evidence="合成：并列设计对象", whole_visible=True)
        reviews["review_policy_version"] = revise_boards.REVIEW_POLICY_VERSION
        reviews["reviews"][0]["provenance"] = {"review_policy_version": revise_boards.REVIEW_POLICY_VERSION}
        crop = [0.18, 0.18, 0.54, 0.54]
        reviews["reviews"][0]["members"][0].update(
            suggested_roi=crop, primary_subject_supported=True, whole_subject_compatible=True,
            display_expression_supported=True, crop_context_faithful=True,
            reason="合成：该局部属于同级对象，延续对象整体设计情绪，未裁掉冲突")
        plan["changes"][0]["actions"][0]["roi"] = crop
        return boards, reviews, plan

    def test_current_representative_crop_can_remain_smaller_than_parent(self):
        boards, reviews, plan = self.selected_fixture()
        previous = deepcopy(boards)
        result = revise_boards.revise(boards, reviews, plan)
        member = result["boards"][0]["members"][0]
        self.assertEqual(member["roi"], [0.18, 0.18, 0.54, 0.54])
        self.assertEqual(member["evidence_bbox"], [0.2, 0.2, 0.5, 0.5])
        self.assertEqual(member["display_scope"], "representative_detail")
        self.assertEqual(member["primary_subject"], previous["boards"][0]["members"][0]["primary_subject"])
        self.assertFalse(result["new_visual_review_performed"])
        self.assertFalse(result["boards"][0]["designer_approved"])
        self.assertEqual(boards, previous)

    def test_new_crop_requires_current_object_and_context_review(self):
        for mutation in ("old_review", "unfaithful_crop", "missing_object", "exclude_fact"):
            boards, reviews, plan = self.selected_fixture()
            decision = reviews["reviews"][0]["members"][0]
            if mutation == "old_review":
                reviews["reviews"][0]["provenance"]["review_policy_version"] = "primary-subject-design-emotion.v3"
            elif mutation == "unfaithful_crop":
                decision["crop_context_faithful"] = False
            elif mutation == "missing_object":
                decision["primary_subject_supported"] = False
            else:
                decision["suggested_roi"] = [0.2, 0.2, 0.1, 0.1]
                plan["changes"][0]["actions"][0]["roi"] = decision["suggested_roi"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                revise_boards.revise(boards, reviews, plan)

    def test_roi_change_cannot_relabel_existing_fact_scope(self):
        boards, reviews, plan = self.selected_fixture()
        plan["changes"][0]["actions"][0]["display_scope"] = "whole_object"
        with self.assertRaisesRegex(ValueError, "先做定点观察补查"):
            revise_boards.revise(boards, reviews, plan)

    def test_weak_crop_can_get_a_suggested_bounded_view_without_claiming_pass(self):
        boards, reviews, plan = self.selected_fixture()
        decision = reviews["reviews"][0]["members"][0]
        decision.update(scope_correct=True, image_quality="weak", display_expression_supported=False)
        result = revise_boards.revise(boards, reviews, plan)
        self.assertEqual(result["boards"][0]["visual_review_status"], "not_performed")

    def test_new_roi_preserves_subject_and_remains_renderable(self):
        boards, reviews, plan = board_fixture()
        before = deepcopy(boards)
        result = revise_boards.revise(boards, reviews, plan)
        board = result["boards"][0]
        member = board["members"][0]
        self.assertEqual(member["roi"], member["display_bbox"])
        self.assertEqual(member["prior_display_bbox"], before["boards"][0]["members"][0]["display_bbox"])
        self.assertEqual(member["evidence_bbox"], before["boards"][0]["members"][0]["evidence_bbox"])
        self.assertEqual(member["primary_subject"], before["boards"][0]["members"][0]["primary_subject"])
        render_delivery.validate_display_scope(member, unit())
        self.assertEqual(board["visual_review_status"], "not_performed")
        self.assertEqual(boards, before)

    def test_revised_frame_cannot_shrink_to_local_fact(self):
        boards, reviews, plan = board_fixture()
        crop = [0.2, 0.2, 0.5, 0.5]
        plan["changes"][0]["actions"][0]["roi"] = crop
        reviews["reviews"][0]["members"][0]["suggested_roi"] = crop
        with self.assertRaisesRegex(ValueError, "不得裁掉主物品"):
            revise_boards.revise(boards, reviews, plan)

    def test_legacy_board_revision_does_not_invent_subject_metadata(self):
        boards, reviews, plan = board_fixture(legacy=True)
        result = revise_boards.revise(boards, reviews, plan)
        member = result["boards"][0]["members"][0]
        self.assertNotIn("display_bbox", member)
        self.assertNotIn("primary_subject", member)
        render_delivery.validate_display_scope(member, unit(legacy=True))


if __name__ == "__main__":
    unittest.main()
