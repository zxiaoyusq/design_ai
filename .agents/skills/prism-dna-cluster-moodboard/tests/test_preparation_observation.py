"""Prompt升版只增强关系描述，旧v8事实和对象情绪绑定不能被重标或丢弃。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_design_emotion import interpretation, image_fixture
from test_observe_subject_contract import selected_unit, unit as legacy_subject_unit
import observe_sample as observer
import design_emotion as emotion


class PreparationObservationTests(unittest.TestCase):
    def test_multi_image_batch_does_not_overwrite_image_index_with_emotion_provenance(self):
        for version in ("prism-dna-cluster-observation-20261009-v7",
                        "prism-dna-cluster-observation-20261009-v8", observer.PROMPT_VERSION):
            with self.subTest(version=version), TemporaryDirectory() as directory:
                folder = Path(directory)
                rows, images = [], []
                for index in range(2):
                    row = {"image_id": f"i{index}", "sha256": f"sha{index}", "local_path": f"/synthetic/{index}.jpg"}
                    member = legacy_subject_unit() if version in observer.EMOTION_PROMPT_VERSIONS else selected_unit(peer=True)
                    raw = {"image_id": row["image_id"], "runway": {"classification": "no", "evidence": "合成"},
                           "limitations": [], "units": [member]}
                    if version in observer.EMOTION_PROMPT_VERSIONS:
                        raw["design_emotion"] = interpretation()
                    else:
                        member["design_emotion"] = interpretation()
                    rows.append(row)
                    images.append(raw)
                answer = {"images": images}
                (folder / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
                (folder / "receipt.json").write_text(json.dumps({"started_at": "synthetic"}), encoding="utf-8")
                context = {"prompt_version": version, "images": [{"image_id": row["image_id"], "r5": {
                    "facts": [], "source_ref": None, "original_known_fact_count": 0}} for row in rows]}
                direct = observer.validate_and_enrich(answer, rows, context, folder)
                compiled = observer.compile_answer_rows(answer, rows, context, folder)
                self.assertEqual(compiled, direct)
                self.assertEqual([record["status"] for record in compiled], ["observed", "observed"])
                self.assertEqual([record["units"][0]["observation_pointer"] for record in compiled],
                                 ["/images/0/units/0", "/images/1/units/0"])
                self.assertTrue(all(emotion.emotion_binding_matches(record["units"][0]) for record in compiled))
                self.assertEqual(list(folder.glob("compile-failures.*.json")), [])

    def test_old_and_new_prompt_keep_actual_version_and_local_peer_scope(self):
        for version in ("prism-dna-cluster-observation-20261009-v8", observer.PROMPT_VERSION):
            with self.subTest(version=version), TemporaryDirectory() as directory:
                folder = Path(directory)
                member = selected_unit("ID", peer=True, detail=True)
                member["design_emotion"] = interpretation()
                member["whole_appearance"]["evidence"] = "浅暖主体，深色连接为辅助，非测量比例"
                answer = {"images": [{"image_id": "i", "runway": {"classification": "no", "evidence": "合成"},
                                      "limitations": [], "units": [member]}]}
                (folder / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
                (folder / "receipt.json").write_text(json.dumps({"started_at": "synthetic"}), encoding="utf-8")
                context = {"prompt_version": version, "images": [{"image_id": "i", "r5": {
                    "facts": [], "source_ref": None, "original_known_fact_count": 0}}]}
                result = observer.validate_and_enrich(answer, [image_fixture()], context, folder)[0]
                unit = result["units"][0]
                self.assertEqual(result["observation_prompt_version"], version)
                self.assertEqual(unit["design_emotion_provenance"]["prompt_version"], version)
                self.assertEqual(unit["feature_definition_version"], observer.VERSION)
                self.assertEqual(unit["whole_appearance"], member["whole_appearance"])
                self.assertEqual(unit["features"], member["features"])
                self.assertEqual(unit["target_role"], "peer_object")
                self.assertEqual(unit["display_scope"], "representative_detail")
                self.assertTrue(emotion.emotion_binding_matches(unit))


if __name__ == "__main__":
    unittest.main()
