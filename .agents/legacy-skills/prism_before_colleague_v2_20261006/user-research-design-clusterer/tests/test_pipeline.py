"""使用两位虚构用户验证全文覆盖和引用约束，不请求真实模型。"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pipeline as p


def fixture() -> dict:
    return {"users": [
        {"id": "75", "name": "用户甲", "profile": {"country": "Indonesia", "age": 16, "roles": ["学生", "兼职"]},
         "aesthetic_research": [
             {"id": "ppt-s03", "question": "喜欢什么外观？", "ai_analysis": "喜欢哑光。不要灯线。", "source_type": "ppt_supplement", "ref_pic_links": [{"local_paths": ["secret-image.png"], "description_zh": "图片推测金属"}]},
             {"id": "q2", "question": "材质和颜色？", "ai_analysis": "未提及材质；喜欢蓝色。"},
             {"id": "q3", "question": "选图片", "ai_analysis": "喜欢 P1、P2。"},
             {"id": "q4", "question": "再次确认", "ai_analysis": "喜欢哑光。"},
         ],
         "demand_research": [{"id": "d1", "scenario": "户外使用", "ai_index": "单手握持时不要太滑。"}],
         "image_preferences": [{"local_path": "never-read.png", "emotion_tag": "ENJOY"}],
         "ppt_images": [{"description_zh": "不应进入分析的图片描述"}]},
        {"id": "52", "name": "用户乙", "profile": {"country": "Pakistan", "age": 20},
         "aesthetic_research": [{"id": "ppt-s03", "question": "喜欢什么表面？", "ai_analysis": "喜欢亮面。"}, {"id": "q-empty", "ai_analysis": None}],
         "demand_research": []},
    ]}


def execution(built: dict) -> dict:
    return {"model_id": "offline-fixture", "model_version": "fixture-v1", "executed_at": "2026-09-29T10:00:00+08:00", "prompt_sha256": built["prompt_sha256"]}


def observation(quote: str, dimension: str, stance: str, conditions: list | None = None) -> dict:
    return {"statement": quote, "dimension": dimension, "stance": stance, "object": "手机", "context": "选购", "conditions": conditions or [], "quote": quote}


def segment(text: str, claims: list | None = None, reason: str = "context_only") -> dict:
    return {"text": text, "observations": claims or [], "retention": None if claims else {"reason": reason, "note": "微型夹具保留源文本"}}


def extraction(built: dict) -> dict:
    payload = json.loads(built["messages"][1]["content"])
    records = []
    for row in payload["records"]:
        text = row["text"]
        if text == "喜欢哑光。不要灯线。":
            segments = [segment(text, [observation("喜欢哑光", "finish", "prefer"), observation("不要灯线", "detail", "avoid")])]
        elif text == "未提及材质；喜欢蓝色。":
            segments = [segment("未提及材质；", reason="no_answer"), segment("喜欢蓝色。", [observation("喜欢蓝色", "color", "prefer")])]
        elif text == "喜欢 P1、P2。":
            segments = [segment(text, reason="image_reference_only")]
        elif text in {"喜欢哑光。", "喜欢亮面。"}:
            segments = [segment(text, [observation(text, "finish", "prefer")])]
        elif text == "单手握持时不要太滑。":
            segments = [segment(text, [observation(text, "sensory", "conditional", ["单手握持"])])]
        else:
            segments = [segment(text, reason="no_answer" if not text else "context_only")]
        records.append({"source_id": row["source_id"], "segments": segments})
    return {"batch_id": built["batch_id"], "execution": execution(built), "records": records}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "users.json"
        self.run = self.root / "run"
        p.write_json(self.source, fixture())
        p.prepare(self.source, self.run)

    def collect(self):
        for path in (self.run / "requests").glob("B*.json"):
            built = p.read_json(path)
            p.write_json(self.run / "extractions" / path.name, extraction(built))
        p.collect(self.run)

    def plan(self) -> dict:
        corpus = p.read_json(self.run / "observations.json")
        sources = p.read_json(self.run / "sources.json")
        dimensions = sorted({row["dimension"] for row in corpus["observations"]})
        directions = []
        for index, dimension in enumerate(dimensions):
            atoms = [row for row in corpus["observations"] if row["dimension"] == dimension]
            directions.append({"id": f"D{index + 1:03d}", "name": dimension + "微型方向", "design_question": "验证具体设计特征的来源", "summary": "只供离线流程测试", "features": [{"dimension": dimension, "stance": row["stance"], "statement": row["statement"], "observation_ids": [row["id"]]} for row in atoms], "context_observation_ids": [], "differences": [], "design_implications": []})
        return {"execution": execution(p.read_json(self.run / "cluster-request.json")), "directions": directions, "user_positioning": [{"user_id": user["id"], "summary": "源画像保留", "source_ids": [row["source_id"] for row in sources["records"] if row["user_id"] == user["id"] and row["kind"] == "profile"], "observation_ids": []} for user in sources["users"]], "unclustered": []}

    def compile(self, plan: dict) -> dict:
        return p.compile_clusters(plan, p.read_json(self.run / "sources.json"), p.read_json(self.run / "observations.json"), p.read_json(self.run / "cluster-request.json")["prompt_sha256"])

    def test_inventory_preserves_all_text_without_image_metadata(self):
        sources = p.read_json(self.run / "sources.json")
        self.assertEqual(Counter(row["kind"] for row in sources["records"]), {"profile": 6, "question": 6, "demand": 1})
        self.assertIn("未提及材质；喜欢蓝色。", [row["text"] for row in sources["records"]])
        self.assertIn("", [row["text"] for row in sources["records"]])
        self.assertNotIn("secret-image", p.dump(sources))
        self.assertNotIn("图片描述", p.dump(sources))
        repeated = [row for row in sources["records"] if row["original_id"] == "ppt-s03"]
        self.assertEqual(len({row["source_id"] for row in repeated}), 2)

    def test_unknown_text_field_and_duplicate_user_are_not_silently_dropped(self):
        for mutate in (lambda data: data["users"][0].update({"extra_interview": "新内容"}), lambda data: data["users"][1].update({"id": "75"})):
            data = fixture()
            mutate(data)
            p.write_json(self.source, data)
            with self.assertRaises(ValueError):
                p.inventory(self.source)

    def test_missing_batch_and_frozen_prompt_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "缺少"):
            p.collect(self.run)
        (self.run / "prompts/extraction.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "冻结 Prompt"):
            p.load_run(self.run)

    def test_source_omission_truncated_segment_and_false_quote_are_rejected(self):
        built = p.read_json(self.run / "requests/B0001.json")
        source_map = {row["source_id"]: row for row in p.read_json(self.run / "sources.json")["records"]}
        response = extraction(built)
        with self.assertRaisesRegex(ValueError, "source_id"):
            p.extract_response({**response, "records": response["records"][:-1]}, built, source_map)
        bad = copy.deepcopy(response)
        row = next(row for row in bad["records"] if row["segments"][0]["observations"])
        row["segments"][0]["text"] = "喜欢哑光。"
        with self.assertRaisesRegex(ValueError, "源全文"):
            p.extract_response(bad, built, source_map)
        bad = copy.deepcopy(response)
        row = next(row for row in bad["records"] if row["segments"][0]["observations"])
        row["segments"][0]["observations"][0]["quote"] = "源文本并未如此描述"
        with self.assertRaisesRegex(ValueError, "引文"):
            p.extract_response(bad, built, source_map)

    def test_oversized_record_never_truncates(self):
        data = fixture()
        data["users"][0]["aesthetic_research"][0]["ai_analysis"] = "完整回答" * 800
        p.write_json(self.source, data)
        prompt = (p.SKILL_DIR / "references/extraction.md").read_text()
        with self.assertRaisesRegex(ValueError, "单条完整文本超出"):
            p.prepare(self.source, None, max_chars=len(prompt) + 1500, dry_run=True)

    def test_unknown_object_is_preserved_and_bad_fields_locate_source(self):
        built = p.read_json(self.run / "requests/B0001.json")
        source_map = {row["source_id"]: row for row in p.read_json(self.run / "sources.json")["records"]}
        response = extraction(built)
        row = next(row for row in response["records"] if row["segments"][0]["observations"])
        claim = row["segments"][0]["observations"][0]
        claim["object"] = ""
        atoms, _, _, _ = p.extract_response(response, built, source_map)
        self.assertEqual(next(atom for atom in atoms if atom["source_id"] == row["source_id"])["object"], "")
        claim["object"] = None
        with self.assertRaises(ValueError) as raised:
            p.extract_response(response, built, source_map)
        self.assertIn(f"B0001.{row['source_id']}.segments[0].observations[0].object", str(raised.exception))

    def test_no_design_evidence_keeps_sources_and_returns_empty_directions(self):
        data = fixture()
        for user in data["users"]:
            user["aesthetic_research"] = [row for row in user["aesthetic_research"] if row.get("ai_analysis") in (None, "喜欢 P1、P2。")]
            user["demand_research"] = []
        p.write_json(self.source, data)
        self.run = self.root / "no-design-run"
        p.prepare(self.source, self.run)
        self.collect()
        p.write_json(self.run / "clusters.json", self.plan())
        self.assertEqual(p.finalize(self.run, self.run / "clusters.json")["status"], "no_design_evidence")
        self.assertFalse(p.read_json(self.run / "final/handshake.json")["ready_for_handshake"])
        self.assertEqual(p.read_json(self.run / "coverage.json")["handled_records"], 8)

    def test_negative_cannot_become_positive_and_design_cannot_be_lost(self):
        self.collect()
        plan = self.plan()
        feature = next(feature for direction in plan["directions"] for feature in direction["features"] if feature["stance"] == "avoid")
        feature["stance"] = "prefer"
        with self.assertRaisesRegex(ValueError, "态度|avoid"):
            self.compile(plan)
        plan = self.plan()
        dropped = plan["directions"].pop()["features"][0]["observation_ids"][0]
        plan["user_positioning"][0]["observation_ids"].append(dropped)
        with self.assertRaisesRegex(ValueError, "设计观点未进入"):
            self.compile(plan)

    def test_foreign_user_positioning_and_missing_user_are_rejected(self):
        self.collect()
        plan = self.plan()
        plan["user_positioning"][0]["source_ids"] = plan["user_positioning"][1]["source_ids"]
        with self.assertRaisesRegex(ValueError, "其他用户"):
            self.compile(plan)
        plan = self.plan()
        plan["user_positioning"].pop()
        with self.assertRaisesRegex(ValueError, "缺少用户定位"):
            self.compile(plan)

    def test_provenance_unknowns_are_disclosed_and_stale_request_rejected(self):
        self.collect()
        plan = self.plan()
        plan["execution"]["model_version"] = None
        self.assertEqual(self.compile(plan)["execution"]["traceability_gaps"], ["model_version"])
        plan["execution"]["prompt_sha256"] = "old-request"
        with self.assertRaisesRegex(ValueError, "prompt_sha256"):
            self.compile(plan)

    def test_complete_pipeline_preserves_conditions_and_counts_users_once(self):
        self.collect()
        plan = self.plan()
        p.write_json(self.run / "clusters.json", plan)
        result = p.finalize(self.run, self.run / "clusters.json")
        self.assertEqual(result["status"], "completed")
        handshake = p.read_json(self.run / "final/handshake.json")
        finish = next(row for row in handshake["directions"] if row["features"][0]["dimension"] == "finish")
        self.assertEqual(finish["users_by_stance"]["prefer"], ["52", "75"])
        self.assertEqual(len(finish["features"]), 3)
        conditional = next(atom for direction in handshake["directions"] for feature in direction["features"] for atom in feature["observations"] if atom["stance"] == "conditional")
        self.assertEqual(conditional["conditions"], ["单手握持"])
        corpus = p.read_json(self.run / "observations.json")
        self.assertTrue(any(row["reason"] == "image_reference_only" for row in corpus["retained_segments"]))
        self.assertFalse(handshake["image_analysis_performed"])
        with self.assertRaisesRegex(ValueError, "final 已存在"):
            p.finalize(self.run, self.run / "clusters.json")


if __name__ == "__main__":
    unittest.main()
