"""整体设计情绪的少量离线契约测试；合成解释不代表视觉验收。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import design_emotion as emotion
import observe_sample as observer
import supplement_design_emotion as supplement
from test_observe_subject_contract import unit, selected_unit


def interpretation():
    return {"status": "supported", "axes": {name: "balanced" for name in emotion.EMOTION_AXES},
            "visible_basis": {name: f"合成的{name}可见依据" for name in emotion.EMOTION_BASIS_FIELDS},
            "coordination_reason": "合成的比例与色彩、表面和细节相互配合，仅用于协议测试",
            "expression": "合成整体感受", "limitations": []}


def source():
    return {"observation_ref": {"path": "/synthetic/answer.json", "sha256": "answer"},
            "observation_pointer": "/images/0/design_emotion", "receipt_ref": {"path": "/synthetic/receipt.json", "sha256": "receipt"},
            "prompt_version": "synthetic-emotion-v1"}


def image_fixture():
    member = {**unit(), "unit_id": "i:CMF:1", "image_id": "i", "image_sha256": "sha"}
    image = {"image_id": "i", "sha256": "sha", "local_path": "/synthetic/original.jpg", "status": "observed", "units": [member]}
    return image


class DesignEmotionTests(unittest.TestCase):
    def test_unknown_axes_remain_unknown_without_tone_fallback(self):
        value = interpretation()
        value["status"] = "unresolved"
        value["axes"] = {name: None for name in emotion.EMOTION_AXES}
        value["visible_basis"] = {name: None for name in emotion.EMOTION_BASIS_FIELDS}
        original = deepcopy(value)
        emotion.validate_emotion(value)
        self.assertEqual(value, original)

    def test_emotion_requires_actual_image_subject_and_answer_binding(self):
        image = image_fixture()
        member = image["units"][0]
        member.update(emotion.bind_emotion(interpretation(), image, emotion.primary_subject_binding(image["units"]), source()))
        self.assertTrue(emotion.emotion_binding_matches(member))
        member["design_emotion_provenance"]["image_sha256"] = "another-image"
        self.assertFalse(emotion.emotion_binding_matches(member))

    def test_no_subject_and_existing_emotion_do_not_create_supplement_calls(self):
        image = image_fixture()
        no_subject = {"image_id": "none", "status": "observed", "units": []}
        image["design_emotion"] = interpretation()
        targets, skipped = supplement.select_targets({"images": [image, no_subject]})
        self.assertEqual(targets, [])
        self.assertEqual({row["reason"] for row in skipped}, {"existing_design_emotion_retained", "no_usable_primary_subject"})

    def test_supplement_preserves_all_original_dna_values(self):
        image = image_fixture()
        base = {"images": [image], "units": image["units"]}
        original = deepcopy(base)
        subject = emotion.primary_subject_binding(image["units"])
        entry = {"image_id": "i", "image_sha256": "sha", "primary_subject": subject,
                 "unit_ids": ["i:CMF:1"], **emotion.bind_emotion(interpretation(), image, subject, source())}
        result = supplement.apply_supplement(base, [entry])
        for key, value in original["units"][0].items():
            self.assertEqual(result["units"][0][key], value)
        self.assertEqual(base, original)
        self.assertEqual(result["images"][0]["units"], result["units"])
        self.assertTrue(emotion.emotion_binding_matches(result["units"][0]))
        self.assertEqual(result["images"][0]["design_emotion"], result["units"][0]["design_emotion"])

    def test_v7_image_emotion_shared_but_v6_remains_missing(self):
        image = image_fixture()
        raw_units = [unit(), unit()]
        image_answer = {"image_id": "i", "runway": {"classification": "no", "evidence": "合成"},
                        "limitations": [], "units": raw_units, "design_emotion": interpretation()}
        context = {"prompt_version": "prism-dna-cluster-observation-20261009-v7", "images": [{"image_id": "i",
                   "r5": {"facts": [], "source_ref": None, "original_known_fact_count": 0}}]}
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "answer.json").write_text(json.dumps({"images": [image_answer]}))
            (folder / "receipt.json").write_text(json.dumps({"started_at": "synthetic"}))
            compiled = observer.validate_and_enrich({"images": [image_answer]}, [image], context, folder)[0]
            self.assertEqual(len(compiled["units"]), 2)
            self.assertEqual(compiled["units"][0]["design_emotion"], compiled["units"][1]["design_emotion"])
            self.assertTrue(all(emotion.emotion_binding_matches(member) for member in compiled["units"]))
            context["prompt_version"] = "prism-dna-cluster-observation-20261009-v6"
            del image_answer["design_emotion"]
            legacy = observer.validate_and_enrich({"images": [image_answer]}, [image], context, folder)[0]
            self.assertNotIn("design_emotion", legacy)
            self.assertTrue(all("design_emotion" not in member for member in legacy["units"]))

    def test_v8_peer_objects_bind_separate_context_emotions(self):
        image = image_fixture()
        first, second = selected_unit("ID"), selected_unit(peer=True)
        first["primary_subject"].update(identity="左侧椅子", bbox=[0, 0, 0.5, 1])
        first["bbox"] = first["evidence_bbox"] = first["display_bbox"] = [0.1, 0.3, 0.3, 0.3]
        second["primary_subject"].update(identity="右侧灯具", bbox=[0.5, 0, 0.5, 1])
        second["bbox"] = second["evidence_bbox"] = second["display_bbox"] = [0.6, 0.3, 0.3, 0.3]
        first["design_emotion"] = interpretation()
        second["design_emotion"] = interpretation()
        second["design_emotion"]["expression"] = "另一对象的独立组合"
        answer = {"images": [{"image_id": "i", "runway": {"classification": "no", "evidence": "合成"},
                              "limitations": [], "units": [first, second]}]}
        context = {"prompt_version": observer.PROMPT_VERSION, "images": [{"image_id": "i",
                   "r5": {"facts": [], "source_ref": None, "original_known_fact_count": 0}}]}
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "answer.json").write_text(json.dumps(answer))
            (folder / "receipt.json").write_text(json.dumps({"started_at": "synthetic"}))
            result = observer.validate_and_enrich(answer, [image], context, folder)[0]
        self.assertNotIn("design_emotion", result)
        self.assertEqual(len(emotion.selected_subject_groups(result["units"])), 2)
        self.assertTrue(all(emotion.emotion_binding_matches(member) for member in result["units"]))
        self.assertNotEqual(result["units"][0]["design_emotion"], result["units"][1]["design_emotion"])
        result["units"][1]["design_emotion_provenance"] = deepcopy(result["units"][0]["design_emotion_provenance"])
        self.assertFalse(emotion.emotion_binding_matches(result["units"][1]))

    def test_supplement_groups_one_image_without_cross_object_sharing(self):
        image = image_fixture()
        first = {**selected_unit(), "unit_id": "i:CMF:1", "image_id": "i", "image_sha256": "sha"}
        second = {**selected_unit(peer=True), "unit_id": "i:CMF:2", "image_id": "i", "image_sha256": "sha"}
        first["primary_subject"].update(identity="左椅", bbox=[0, 0, 0.5, 1])
        second["primary_subject"].update(identity="右灯", bbox=[0.5, 0, 0.5, 1])
        image["units"] = [first, second]
        base = {"images": [image], "units": image["units"]}
        targets, skipped = supplement.select_targets(base)
        self.assertEqual(len(targets), 1)
        self.assertEqual(len(targets[0]["subjects"]), 2)
        self.assertEqual(skipped, [])
        entries = [{"image_id": "i", "image_sha256": "sha", **group,
                    **emotion.bind_emotion(interpretation(), image, group["primary_subject"], source())}
                   for group in targets[0]["subjects"]]
        result = supplement.apply_supplement(base, entries)
        self.assertNotIn("design_emotion", result["images"][0])
        self.assertTrue(all(emotion.emotion_binding_matches(member) for member in result["units"]))
        broken = deepcopy(entries)
        broken[1]["primary_subject"] = broken[0]["primary_subject"]
        with self.assertRaisesRegex(ValueError, "冻结主体已经变化"):
            supplement.apply_supplement(base, broken)

    def test_same_object_cannot_receive_different_emotions_per_surface(self):
        first, second = selected_unit(), selected_unit()
        first["design_emotion"] = interpretation()
        second["design_emotion"] = interpretation()
        second["design_emotion"]["expression"] = "假造另一情绪"
        with self.assertRaisesRegex(ValueError, "同一设计情绪"):
            observer.validate_primary_binding([first, second])

    def test_partial_object_emotion_explicitly_conflicts_instead_of_skipping(self):
        image = image_fixture()
        first = {**selected_unit(), "unit_id": "i:CMF:1", "image_id": "i", "image_sha256": "sha"}
        second = {**deepcopy(first), "unit_id": "i:CMF:2"}
        second["primary_subject"]["bbox"][0] += 0.000005
        second.update(emotion.bind_emotion(interpretation(), image, emotion.primary_subject_binding([second]), source()))
        image["units"] = [first, second]
        base = {"images": [image], "units": image["units"]}
        original = deepcopy(base)
        with self.assertRaisesRegex(ValueError, "情绪部分缺失.*整对象失效"):
            supplement.select_targets(base)
        self.assertEqual(base, original)


if __name__ == "__main__":
    unittest.main()
