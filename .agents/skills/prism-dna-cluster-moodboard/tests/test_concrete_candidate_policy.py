"""候选 v5 的小量离线诊断；数值差异、合成样本均不充当实际视觉验收。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_cluster_sample import cluster, cmf, id_unit, observations


class ConcreteCandidateTests(unittest.TestCase):
    def test_zero_emotion_distance_does_not_erase_concrete_color_and_surface_differences(self):
        left, right = cmf(), cmf(1)
        right["features"]["color"].update(hue="green", chroma="high")
        right["features"]["material"].update(gloss="mirror", reflection="mirror")
        self.assertEqual(cluster.pair_difference(left, right).distance, 0)
        result = cluster.concrete_pair_evidence(left, right)
        self.assertGreater(result["equal_block_mean_difference"], 0)
        self.assertTrue(result["requires_concrete_relation_review"])
        self.assertEqual(result["semantic_relation_status"], "not_established_by_numeric_comparison")
        self.assertIn("detail.color.hue", [row["field"] for row in result["differing_fields"]])
        # 多项差异依旧不能单凭数值硬拒；它只改变候选代表性并交给独立实板审阅。
        groups, _, _ = cluster.cluster_units([left, right])
        self.assertEqual(len(groups[0]), 2)

    def test_material_names_and_functional_component_count_do_not_change_ranking_evidence(self):
        left, right = cmf(), cmf(1)
        baseline = cluster.concrete_pair_evidence(left, right)
        right["features"]["material"]["appearance"] = "textile"
        right["category"] = "furniture"
        self.assertEqual(cluster.concrete_pair_evidence(left, right), baseline)
        left, right = id_unit(0, "few"), id_unit(1, "many")
        self.assertEqual(cluster.concrete_pair_evidence(left, right)["equal_block_mean_difference"], 0)

    def test_missing_or_mixed_is_not_similarity_and_absent_texture_is_not_missing(self):
        left, right = cmf(), cmf(1)
        left["features"]["color"]["hue"] = right["features"]["color"]["hue"] = "mixed"
        pair = cluster.concrete_pair_evidence(left, right)
        self.assertIn("hue", pair["blocks"]["detail.color"]["unresolved_fields"])
        pending = cluster.pending_evidence([left], [])
        self.assertIn("detail.color.hue", pending[0]["unresolved_concrete_fields"])
        self.assertNotIn("detail.texture.scale", pending[0]["unresolved_concrete_fields"])
        self.assertEqual(left["features"]["texture"]["scale"], None)

    def test_concrete_representativeness_precedes_design_quality(self):
        data = observations(9)
        outlier = data["units"][0]
        outlier["design_quality"] = {"level": "distinctive", "evidence": "合成强设计感不覆盖关系差异"}
        outlier["features"]["color"].update(hue="green", chroma="high", contrast="high")
        _, boards = cluster.build_outputs(data)
        board = boards["boards"][0]
        self.assertNotIn("u00", [row["unit_id"] for row in board["members"]])
        self.assertTrue(board["requires_concrete_relation_review"])
        self.assertEqual(len(board["concrete_pair_diagnostics"]), 28)
        self.assertFalse(board["designer_approved"])
        self.assertEqual(boards["new_model_calls"], 0)

    def test_default_waits_for_terminal_images_while_failed_stays_visible(self):
        data = observations(2)
        data["images"][1]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "DNA_extraction_not_terminal"):
            cluster.build_outputs(data)
        clusters, _ = cluster.build_outputs(data, allow_partial=True)
        self.assertEqual(clusters["extraction_state"]["phase"], "partial_pilot")
        self.assertFalse(clusters["summary"]["all_sample_images_terminal"])
        self.assertEqual(clusters["summary"]["eligible_units"], 1)
        data["images"][1]["status"] = "failed"
        data["units"] = data["units"][:1]
        clusters, _ = cluster.build_outputs(data)
        self.assertTrue(clusters["summary"]["all_sample_images_terminal"])
        self.assertFalse(clusters["summary"]["all_sample_images_observed"])
        self.assertEqual(clusters["summary"]["image_status_counts"]["failed"], 1)

    def test_prepared_reader_checks_SHA_scope_and_terminal_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = observations(2)
            cluster.write_new(root / "observations.json", data)
            cluster.write_new(root / "sample.json", {"images": data["images"]})
            manifest = {"schema_version": "prism.design_dna_prepared.v1",
                        "observations_ref": cluster.file_ref(root / "observations.json"),
                        "sample_ref": cluster.file_ref(root / "sample.json"),
                        "terminal_counts": {"images": 2, "observed": 2, "failed": 0, "pending": 0}}
            cluster.write_new(root / "prepared.json", manifest)
            self.assertEqual(cluster.read_prepared(root / "prepared.json")[0], data)
            bad = copy.deepcopy(manifest)
            bad["terminal_counts"]["observed"] = 1
            cluster.write_new(root / "bad.json", bad)
            with self.assertRaisesRegex(ValueError, "prepared_terminal_counts"):
                cluster.read_prepared(root / "bad.json")
            bad = copy.deepcopy(manifest)
            bad["observations_ref"]["sha256"] = "0" * 64
            cluster.write_new(root / "wrong-sha.json", bad)
            with self.assertRaisesRegex(ValueError, "frozen_reference_SHA_mismatch"):
                cluster.read_prepared(root / "wrong-sha.json")
            with self.assertRaisesRegex(ValueError, "do_not_match_frozen_sample"):
                cluster.validate_sample_scope(data, {"images": data["images"][:1]})
            output = root / "output"
            run = subprocess.run([sys.executable, str(cluster.__file__), "--prepared", str(root / "prepared.json"),
                                  "--out-dir", str(output)], text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads((output / "clusters.json").read_text())
            self.assertEqual(result["input_scope"], "frozen_sample_manifest")
            self.assertEqual(result["new_model_calls"], 0)
            self.assertIn("prepared_manifest", result["input_refs"])

    def test_user_feedback_pairs_keep_concrete_differences_when_axes_are_identical(self):
        """仅读取两张历史板的 16 个单元；没有全量聚类或新的视觉/模型结论。"""
        repo = Path(__file__).resolve().parents[4]
        path = repo / "data/result/dna_cluster_moodboard/sample500_subject_v2_20261009/offline-design-emotion-v3/boards.final.json"
        if not path.is_file():
            self.skipTest("local historical feedback fixture not available")
        boards = {row["board_id"]: row for row in json.loads(path.read_text())["boards"]}
        for board_id, pairs in {
            "BOARD-CMF-4a6f81923de2": [(0, 2)],
            "BOARD-ID-6e0b592ef38e": [(1, 4), (1, 5)],
        }.items():
            board = boards[board_id]
            members = [{**row, "branch": board["branch"]} for row in board["members"]]
            self.assertEqual(len(cluster.concrete_member_profile(members)), 8)
            for left_index, right_index in pairs:
                with self.subTest(board=board_id, positions=(left_index + 1, right_index + 1)):
                    left, right = members[left_index], members[right_index]
                    self.assertEqual(cluster.pair_difference(left, right).distance, 0)
                    concrete = cluster.concrete_pair_evidence(left, right)
                    self.assertGreater(concrete["equal_block_mean_difference"], 0)
                    self.assertTrue(concrete["differing_fields"])
                    self.assertTrue(concrete["requires_concrete_relation_review"])


if __name__ == "__main__":
    unittest.main()
