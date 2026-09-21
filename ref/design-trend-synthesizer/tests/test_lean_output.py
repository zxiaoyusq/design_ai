"""只用极小离线夹具验证宽松正文、已有来源关联与确定性统计。"""

from pathlib import Path
import json
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from lean_output import parse_notes, publish


class LeanOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "available.jpg").write_bytes(b"fixture; pixels are never read")
        (self.root / "question-only.jpg").write_bytes(b"question-only fixture")
        (self.root / "disliked.jpg").write_bytes(b"disliked fixture")
        self.sources = {
            "T00001": {"id": "trend:one", "kind": "trend", "source_file": "trends",
                       "json_pointer": "/trends/0", "fields": {"summary_zh": "磨砂表面降低反光。"},
                       "image_refs": [self.image("trend-photo", "missing.jpg")]},
            "U000001": self.user("u1", "q1", "P1比P2更低调；P5不符合偏好。", "/users/0/aesthetic_research/0"),
            "U000002": self.user("u1", "q2", "同一用户补充清洁诉求。", "/users/0/aesthetic_research/1"),
            "U000003": self.user("u2", "q1", "希望触感柔和。", "/users/1/aesthetic_research/0"),
        }
        self.sources["U000001"]["fields"]["question"] = "请比较P3。"
        self.sources["U000001"]["image_refs"] = [
            self.image("P1", "available.jpg", "P1"),
            self.image("P2", "available.jpg", "P2"),
            self.image("P3", "question-only.jpg", "P3"),
            self.image("P5", "disliked.jpg", "P5", "DISLIKE"),
        ]
        self.manifest = {"project_root": str(self.root), "selection": {"start_date": "2026-01-01"},
                         "counts": {"users_with_text": 2, "selected_trends": 1},
                         "inputs": {"trends": {"path": str(self.root / "trends.json")},
                                    "users": {"path": str(self.root / "users.json")}}}

    def image(self, identifier, path, code=None, emotion="ENJOY"):
        return {"image_id": identifier, "local_path": path, "source_root": str(self.root),
                "code": code, "status": "available", "emotion_tag": emotion}

    @staticmethod
    def user(uid, question, answer, pointer):
        return {"id": f"user:{uid}:user_qa:{question}", "kind": "user_qa", "user_id": uid,
                "source_file": "users", "json_pointer": pointer,
                "fields": {"ai_analysis": answer}, "profile": {"age": 30}, "image_refs": []}

    def read(self, run, filename="high_potential_trends.json"):
        return json.loads((run / filename).read_text(encoding="utf-8"))

    def test_lenient_markdown_and_unknown_ids_are_isolated(self):
        text = "```markdown\n# 通用方向\n## 柔和触感\n自由写作。[引用 T00001 U000001 U999999]\n### 边界\n保留限定。\n```"
        notes, warnings = parse_notes(text, self.sources)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["source_ids"], ["T00001", "U000001"])
        self.assertIn("### 边界", notes[0]["text"])
        self.assertIn("U999999", notes[0]["text"])
        self.assertIn("U999999", warnings[0])
        self.assertEqual(notes[0]["kind"], "idea")

    def test_missing_headings_and_note_aliases_keep_full_prose(self):
        text = "正文无标题，仍是一份摘要。[N0001] 未关联的U0000019不能借用其他用户。"
        notes, warnings = parse_notes(text, self.sources, {"N0001": ["T00001", "U000001", "U999999"]})
        self.assertEqual(notes[0]["title"], "摘要")
        self.assertEqual(notes[0]["text"], text)
        self.assertEqual(notes[0]["source_ids"], ["T00001", "U000001"])
        self.assertEqual(len(warnings), 2)

    def test_publish_counts_original_answers_and_existing_image_codes(self):
        (self.root / "other-user.jpg").write_bytes(b"another fixture; pixels are never read")
        self.sources["U000004"] = self.user("u2", "q2", "偏好P4的构图。", "/users/1/aesthetic_research/1")
        self.sources["U000004"]["image_refs"] = [self.image("extra-photo", "other-user.jpg", "P4")]
        run = self.root / "result"
        result_sources = {key: value for key, value in self.sources.items() if key != "U000004"}
        summary = publish(run, self.manifest, result_sources,
                          "## 低反光与柔和触感\n设计方向正文。[引用 T00001 U000001 U000002]\n模型提到P3也不补图片。",
                          execution={"model": "offline-fixture", "prompt_version": "test-only"},
                          image_sources=self.sources)
        card = self.read(run)["trends"][0]
        self.assertEqual(summary["status"], "complete")
        self.assertTrue(summary["has_content"])
        self.assertEqual(card["cited_user_ids"], ["u1"])
        self.assertEqual(card["mention_statistics"]["unique_mentioned_users"], 1)
        self.assertEqual(card["source_records"][1]["json_pointer"], "/users/0/aesthetic_research/0")
        self.assertNotIn('original_text', card['source_records'][1])
        self.assertEqual(self.read(run, 'sources.json')['U000001']['fields']['ai_analysis'],
                         self.sources['U000001']['fields']['ai_analysis'])
        self.assertEqual(card["source_records"][1]["source_path"], str(self.root / "users.json"))
        self.assertEqual({ref["code"] for ref in card["image_refs"]}, {None, "P1", "P2"})
        self.assertTrue(all(ref["mention_role"] == "unclear" for ref in card["image_refs"] if ref["code"]))
        missing = next(ref for ref in card["image_refs"] if not ref["file_exists"])
        self.assertIsNone(missing["path"])
        self.assertIsNone(missing["absolute_path"])
        self.assertTrue(summary["warnings"])
        self.assertEqual(len((run / "high_potential_trends.jsonl").read_text().splitlines()), 1)
        self.assertEqual(self.read(run, "validation_report.json")["missing_image_references"], 1)
        self.assertEqual(self.read(run, "validation_report.json")["result_image_paths"], 2)
        self.assertEqual(self.read(run, "validation_report.json")["additional_user_image_paths"], 1)
        image_paths = (run / "image_paths.md").read_text(encoding="utf-8")
        result_section, user_section = image_paths.split("## 其他用户喜欢的关联图片路径")
        self.assertIn("## 与结果相关的所有图片路径", result_section)
        self.assertIn("available.jpg", result_section)
        self.assertIn("missing.jpg", result_section)
        self.assertNotIn("other-user.jpg", result_section)
        self.assertIn("other-user.jpg", user_section)
        self.assertNotIn("available.jpg", user_section)
        self.assertNotIn("question-only.jpg", image_paths)
        self.assertNotIn("disliked.jpg", image_paths)
        self.assertEqual(self.read(run)["user_image_filter"], "like_or_enjoy")
        self.assertEqual(self.read(run)["image_path_report_file"], "image_paths.md")
        self.assertEqual(self.read(run, "completion.json"), summary)

    def test_half_is_not_a_majority_and_old_advice_sections_are_removed(self):
        text = ("# 用研补充\n## 便于清洁\n一人两条回答。[U000001 U000002]\n"
                "### 下一轮验证\n旧建议应该删除。[T00001]\n"
                "## 柔和触感\n两位用户均有引用。[U000001 U000003]\n"
                "### validation_questions\n旧字段内容也应删除。\n")
        run = self.root / "gaps"
        publish(run, self.manifest, self.sources, text)
        document = self.read(run)
        self.assertEqual(len(document["user_research_gaps"]["directions"]), 1)
        self.assertEqual(document["user_research_gaps"]["directions"][0]["cited_user_ids"], ["u1", "u2"])
        self.assertEqual(len(document["diagnostics"]), 1)
        self.assertNotIn("majority", document["diagnostics"][0]["mention_statistics"])
        self.assertEqual(document["diagnostics"][0]["source_ids"], ["U000001", "U000002"])
        for filename in ("high_potential_trends.json", "report.md", "image_paths.md", "completion.json", "validation_report.json"):
            rendered = (run / filename).read_text(encoding="utf-8")
            self.assertNotIn("下一轮验证", rendered)
            self.assertNotIn("validation_questions", rendered)
        self.assertIn("摘要判断", document["user_research_gaps"]["scope_note"])

    def test_unlinked_prose_is_deliverable_but_empty_content_is_not_research(self):
        run = self.root / "freeform"
        summary = publish(run, self.manifest, self.sources, "手工归纳仍可保留，没有完整引用。")
        self.assertEqual(summary["status"], "partial")
        self.assertTrue(summary["has_content"])
        self.assertTrue(summary["partial"])
        self.assertEqual(len(self.read(run)["unlinked_notes"]), 1)
        empty = publish(self.root / "empty", self.manifest, self.sources, "```markdown\n\n``` ")
        self.assertEqual(empty["status"], "empty")
        self.assertFalse(empty["has_content"])
        self.assertTrue(empty["warnings"])
        heading_only = publish(self.root / "heading-only", self.manifest, self.sources, "# 只有标题")
        self.assertFalse(heading_only["has_content"])

    def test_background_does_not_supply_core_images_counts_or_categories(self):
        self.sources["T00001"]["clustering_label"] = "几何图案"
        self.sources["T00002"] = {**self.sources["T00001"], "id": "trend:background",
                                   "clustering_label": "可更换结构", "image_refs": []}
        aliases = {"N0001": ["T00001", "U000001"], "N0002": ["T00002", "U000003"]}
        text = ("## 几何细节\n围绕图案的交集。[N0001]\n"
                "**背景参考：** 可更换结构是另一个设计问题。[N0002]\n"
                "## 可更换偏好\n仅用研明确提出。[U000003]\n背景参考：图案文章不能补齐双侧。[T00001]")
        run = self.root / "background"
        publish(run, self.manifest, self.sources, text, aliases)
        result = self.read(run)
        self.assertEqual(len(result["trends"]), 1)
        card = result["trends"][0]
        self.assertEqual(card["source_ids"], ["T00001", "U000001"])
        self.assertEqual(card["background_source_ids"], ["T00002", "U000003"])
        self.assertEqual(card["clustering_labels"], ["几何图案"])
        self.assertEqual(card["cited_user_ids"], ["u1"])
        self.assertNotIn("N0002", card["description"])
        self.assertEqual({ref["source_record_id"] for ref in card["image_refs"]},
                         {"trend:one", self.sources["U000001"]["id"]})
        self.assertEqual(result["diagnostics"][0]["source_ids"], ["U000003"])
        self.assertFalse(result["diagnostics"][0]["clustering_labels"])
        self.assertIn("背景参考", (run / "report.md").read_text())

    def test_core_wins_overlap_and_unknown_background_does_not_retry(self):
        notes, warnings = parse_notes("## 图案\n已有核心。[T00001 U000001]\n"
                                      "背景参考：重复来源和未知编号。[T00001 U000003 N9999]", self.sources)
        self.assertEqual(notes[0]["background_source_ids"], ["U000003"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("N9999", warnings[0])


if __name__ == "__main__":
    unittest.main()
