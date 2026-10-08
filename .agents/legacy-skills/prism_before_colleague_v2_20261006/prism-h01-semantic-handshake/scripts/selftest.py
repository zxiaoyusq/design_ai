"""微型离线契约验证：不访问网络、不调用模型、不修改真实聚类结果。"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

import handshake as h


class HandshakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        observations = [
            {"id": "O1", "source_id": "S1", "user_id": "U1", "evidence_kind": "existing_analysis", "statement": "喜欢柔和浅彩", "dimension": "color", "stance": "prefer", "object": "手机", "context": "日常", "conditions": [], "quote": "喜欢柔和浅彩"},
            {"id": "O2", "source_id": "S2", "user_id": "U1", "evidence_kind": "ppt_transcribed_text", "statement": "不要大片高饱和色", "dimension": "color", "stance": "avoid", "object": "手机", "context": "日常", "conditions": [], "quote": "不要大片高饱和色"},
            {"id": "O3", "source_id": "S3", "user_id": "U2", "evidence_kind": "demand_text", "statement": "工作时只用黑色", "dimension": "color", "stance": "conditional", "object": "手机", "context": "工作", "conditions": ["工作时"], "quote": "工作时只用黑色"},
        ]
        sources = [{"source_id": o["source_id"], "user_id": o["user_id"], "evidence_kind": o["evidence_kind"], "text": o["quote"], "pointer": f"/users/{o['user_id']}"} for o in observations]
        direction = {"id": "R1", "name": "柔和色感", "summary": "日常喜好浅彩", "design_question": "如何组织浅彩？", "features": [{"observation_ids": ["O1", "O2"], "observations": observations[:2]}], "context_observation_ids": []}
        research = {"schema_version": "user_research_design_handshake.v1", "input_sha256": "synthetic", "coverage_status": "complete", "ready_for_handshake": True, "directions": [direction], "sources_file": "../sources.json", "observations_file": "../observations.json", "full_result_file": "result.json"}
        h.write(self.root / "research/final/handshake.json", research)
        h.write(self.root / "research/final/result.json", {"status": "completed", "input_sha256": "synthetic", "directions": [direction], "unclustered": ["O3"]})
        h.write(self.root / "research/sources.json", {"input_sha256": "synthetic", "records": sources, "users": [{"id": "U1"}, {"id": "U2"}]})
        h.write(self.root / "research/observations.json", {"input_sha256": "synthetic", "observations": observations})
        evidence = [{"evidence_id": f"E{i}", "source_id": f"T{i}", "source_group_id": "G2" if i == 2 else "G1", "text": f"案例{i}通过低饱和浅彩构成柔和视觉", "text_kind": "source_paraphrase", "image_url": "must_not_enter_packet"} for i in range(1, 4)]
        articles = [{"source_id": e["source_id"], "original_id": f"original-{i}", "source_group_id": e["source_group_id"], "title": "浅彩案例"} for i, e in enumerate(evidence, 1)]
        h.write(self.root / "trend/trend-catalogue.json", {"schema_version": "prism.trends.text_catalogue.v1", "evidence": evidence, "articles": articles})
        h.write(self.root / "trend/trend-clusters.json", {"schema_version": "prism.trends.semantic_clusters.v0.1", "clusters": [{"cluster_id": "T1", "title": "浅彩组织", "definition": "浅彩构成柔和视觉", "evidence_refs": ["E1", "E2", "E3"], "source_ids": ["T1", "T2", "T3"], "lineage": [{"members": [{"point_id": "P1", "evidence_id": "E1", "condition": "局部表面"}]}]}], "review_status": "pending_human_review"})
        h.write(self.root / "trend/proposal.json", {"point_scope_limits": {"P1": "不能推为整机"}})
        # 两篇文章复用其他目录同一原图，第三篇未被直接引用且含失败图片。
        (self.root / "assets").mkdir()
        (self.root / "assets/shared.jpg").write_bytes(b"offline-path-fixture")
        image_rows = []
        for i in range(1, 4):
            image_rows.append({"id": f"original-{i}", "images": [{
                "image_id": f"original-{i}_001", "trend_id": f"original-{i}", "index": 1,
                "url": "https://example.test/shared.jpg" if i < 3 else "https://example.test/failed.jpg",
                "status": "downloaded" if i < 3 else "failed",
                "local_path": "../assets/shared.jpg" if i < 3 else None,
                "error": None if i < 3 else "fixture HTTP 404",
            }]})
        (self.root / "trend/images.jsonl").write_text("\n".join(json.dumps(r) for r in image_rows) + "\n", encoding="utf-8")
        self.config = self.root / "config.json"
        h.write(self.config, {"research_final": "research/final", "trend_final": "trend", "trend_images_file": "trend/images.jsonl", "mode": "extension", "brief": "测试用例", "min_trend_source_groups": 2})
        self.run = self.root / "run"
        h.prepare(self.config, self.root, self.run)
        self.manifest, self.snapshot = h.load_run(self.run)
        self.proposal = {
            "schema_version": h.PROPOSAL, "snapshot_sha256": self.manifest["snapshot_sha256"],
            "execution": {"model_id": "offline-fixture-no-model", "model_version": None, "started_at": "2026-10-01T00:00:00+00:00", "completed_at": "2026-10-01T00:00:01+00:00", "prompt_sha256": self.manifest["prompt_sha256"], "traceability_gaps": ["model_version"]},
            "directions": [{"direction_id": "H1", "title": "柔和浅彩", "design_question": "如何在日常手机中组织低饱和浅彩？", "shared_design_principle": "低饱和浅彩形成柔和关系", "why_high_potential": "存在用户正向偏好与两个来源组的具体机制", "validation_next_step": "制作局部配色样板验证", "decision": "high_potential", "relation_basis": "direct_support", "research_cluster_ids": ["R1"], "trend_cluster_ids": ["T1"], "conditions_and_limits": ["仅日常对象，保持局部范围"], "user_differences": ["U2 工作情境只用黑色，不纳入浅彩支持用户"], "unresolved_questions": ["视觉效果待验证"], "extension_explanation": "", "research_citations": [{"observation_id": "O1", "quote": "喜欢柔和浅彩", "role": "support", "reason": "直接支持日常浅彩"}], "trend_citations": [{"evidence_id": e["evidence_id"], "quote": e["text"], "text_kind": e["text_kind"], "reason": "支持低饱和色关系", "scope_note": "局部范围，不推为整机"} for e in evidence[:2]], "constraint_audit": [{"observation_ids": ["O2"], "state": "applicable", "reason": "同对象避免高饱和", "implication": "控制饱和度"}, {"observation_ids": ["O3"], "state": "applicable", "reason": "工作场景有颜色限制", "implication": "不覆盖 U2 的工作需求"}]}],
            "research_cluster_coverage": [{"cluster_id": "R1", "disposition": "used", "reason": "支持 H1"}],
            "trend_cluster_coverage": [{"cluster_id": "T1", "disposition": "used", "reason": "支持 H1"}],
            "overall_evidence_gaps": ["纯合成离线测试，无模型分析"]}

    def validate(self, proposal=None):
        return h.validate(proposal or self.proposal, self.manifest, self.snapshot)

    def publish(self):
        path = self.run / "proposal.json"
        h.write(path, self.proposal)
        h.accept(self.run, path)

    def test_roundtrip_and_selection(self):
        self.publish()
        result = h.read(self.run / "result.json")
        self.assertEqual(result["directions"][0]["support_user_count"], 1)
        self.assertEqual(result["directions"][0]["sample_user_count"], 2)
        choices = h.read(self.run / "selection-template.json")
        choices.update(selected_direction_ids=["H1"], actor_name="fixture-human", authorization="测试授权", reason="测试选择", confirmed_at="2026-10-01T00:01:00+00:00")
        path = self.root / "choices.json"
        h.write(path, choices)
        h.select(self.run, path)
        self.assertTrue(h.verify(self.run)["valid"])
        self.assertEqual(h.read(self.run / "result.json")["review_status"], "pending_human_review")
        with self.assertRaises(FileExistsError):
            h.select(self.run, path)

    def test_packet_pagination_and_local_limits(self):
        first = h.packet(self.run, "trend", ["T1"], 0, 1)
        self.assertEqual(first["next_offset"], 1)
        self.assertEqual(first["records"][0]["local_scopes"][0]["point_scope_limits"], {"P1": "不能推为整机"})
        self.assertNotIn("image_url", first["records"][0]["evidence"])
        self.assertIsNone(h.packet(self.run, "trend", ["T1"], 2, 1)["next_offset"])
        constraints = h.packet(self.run, "constraints", [], 0, 10)
        self.assertEqual({r["observation"]["id"] for r in constraints["records"]}, {"O2", "O3"})

    def test_assets_include_uncited_articles_and_shared_original_path(self):
        self.publish()
        result = h.read(self.run / "result.json")
        assets = h.read(self.run / "related-trend-articles.json")
        self.assertEqual(assets["stats"]["related_articles"], 3)
        self.assertEqual(assets["stats"]["directly_cited_articles"], 2)
        self.assertEqual(assets["stats"]["image_references"], 3)
        self.assertEqual(assets["stats"]["local_image_references"], 2)
        self.assertEqual(assets["stats"]["unresolved_image_references"], 1)
        self.assertEqual(assets["articles"][0]["images"][0]["absolute_local_path"], str(self.root / "assets/shared.jpg"))
        self.assertEqual(assets["articles"][0]["images"][0]["local_path"], assets["articles"][1]["images"][0]["local_path"])
        self.assertEqual(assets["articles"][2]["images"][0]["error"], "fixture HTTP 404")
        self.assertEqual(result["directions"][0]["related_trend_assets"]["article_source_ids"], ["T1", "T2", "T3"])
        self.assertIn("related-trend-articles.json", (self.run / "report.md").read_text())

    def test_missing_file_is_recorded_and_later_deletion_detected(self):
        self.publish()
        (self.root / "assets/shared.jpg").unlink()
        with self.assertRaisesRegex(ValueError, "本地文件状态"):
            h.verify(self.run)

    def test_preexisting_missing_file_keeps_reference_and_reason(self):
        (self.root / "assets/shared.jpg").unlink()
        self.publish()
        assets = h.read(self.run / "related-trend-articles.json")
        image = assets["articles"][0]["images"][0]
        self.assertEqual(image["status"], "downloaded")
        self.assertEqual(image["availability"], "missing_local_file")
        self.assertIn("文件不存在", image["availability_reason"])
        self.assertEqual(image["local_path"], "assets/shared.jpg")
        self.assertEqual(assets["stats"]["local_image_references"], 0)
        self.assertTrue(h.verify(self.run)["valid"])

    def test_assets_tampering_detected(self):
        self.publish()
        with (self.run / "related-trend-articles.json").open("a") as stream:
            stream.write("tampered")
        with self.assertRaisesRegex(ValueError, "图片索引已被修改"):
            h.verify(self.run)

    def test_unclustered_condition_cannot_disappear(self):
        self.proposal["directions"][0]["constraint_audit"].pop()
        with self.assertRaisesRegex(ValueError, "全部反向"):
            self.validate()

    def test_duplicate_source_groups_not_double_counted(self):
        cite = self.proposal["directions"][0]["trend_citations"][1]
        cite.update(evidence_id="E3", quote=self.snapshot["evidence"]["E3"]["text"])
        with self.assertRaisesRegex(ValueError, "来源组不足"):
            self.validate()

    def test_bad_quote_and_provenance_upgrade_rejected(self):
        for key, value in (("quote", "虚构引用"), ("text_kind", "original_text")):
            with self.subTest(key=key):
                p = deepcopy(self.proposal)
                p["directions"][0]["trend_citations"][0][key] = value
                with self.assertRaises(ValueError):
                    self.validate(p)

    def test_negative_cannot_be_positive_support(self):
        c = self.proposal["directions"][0]["research_citations"][0]
        c.update(observation_id="O2", quote="不要大片高饱和色")
        with self.assertRaisesRegex(ValueError, "负向或背景"):
            self.validate()

    def test_unresolved_and_exploratory_not_high_potential(self):
        p = deepcopy(self.proposal)
        p["directions"][0]["constraint_audit"][0]["state"] = "unresolved"
        with self.assertRaisesRegex(ValueError, "适用性未解决"):
            self.validate(p)
        self.snapshot["config"]["mode"] = "exploration"
        self.proposal["directions"][0].update(relation_basis="exploratory_hypothesis", extension_explanation="尚无迁移证据")
        with self.assertRaisesRegex(ValueError, "探索假设"):
            self.validate()

    def test_zero_direction_is_valid_with_coverage(self):
        self.proposal["directions"] = []
        for side in ("research", "trend"):
            self.proposal[f"{side}_cluster_coverage"][0].update(disposition="insufficient", reason="不能形成充分关系")
        self.assertEqual(self.validate(), [])
        self.proposal["trend_cluster_coverage"] = []
        with self.assertRaisesRegex(ValueError, "覆盖"):
            self.validate()

    def test_tampering_detected(self):
        self.publish()
        with (self.run / "report.md").open("a") as stream:
            stream.write("tampered")
        with self.assertRaisesRegex(ValueError, "发布产物"):
            h.verify(self.run)

    def test_upstream_mixed_run_rejected(self):
        path = self.root / "research/observations.json"
        value = h.read(path)
        value["input_sha256"] = "another-run"
        path.unlink()
        h.write(path, value)
        with self.assertRaisesRegex(ValueError, "input_sha256"):
            h.prepare(self.config, self.root, self.root / "bad-run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
