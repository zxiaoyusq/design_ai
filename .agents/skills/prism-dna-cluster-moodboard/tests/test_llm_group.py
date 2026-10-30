"""关系聚类的小型假模型测试；只验证流程与证据边界，不冒充真实审美准确率。"""

import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/llm_group.py"
spec = importlib.util.spec_from_file_location("prism_llm_group_test", SCRIPT)
group = importlib.util.module_from_spec(spec)
spec.loader.exec_module(group)
FIXTURE_CATEGORIES = ("chairs", "cabinets", "watches", "garments")


def fixture_category(card_id):
    """合成对象各自有明确品类；仅供离线夹具，不是生产同义词映射。"""
    return {"category_key": FIXTURE_CATEGORIES[int(card_id.removeprefix("c")) % len(FIXTURE_CATEGORIES)],
            "status": "known", "basis": "合成冻结对象及视窗的品类标识，非真实图像判断"}


def relation_template(ids):
    return {"title": "合成关系而非审美结论", "common_relations": {name: "具有明确可见关系" for name in group.RELATIONS},
            "allowed_variations": ["品类和实际材料可不同"], "strong_conflicts": ["主导配色冲突不能以相同纹理补偿"],
            "representative_ids": ids[:1], "boundary_ids": ids[-1:]}


def visual_answer(ids):
    selected = list(reversed(ids))[:10]
    groups = []
    if len(selected) > 1:
        groups.append({"title": "由假模型指定的成员", "member_ids": selected,
                       "dominant_relation": "合成块面与连接节律；不是实际审美结论",
                       "common_relations": {name: "离线合成关系" for name in group.RELATIONS},
                       "member_evidence": [{"card_id": i, "support": "合成支持", "strongest_difference": "合成差异",
                                            "why_coordinated": "合成协调说明",
                                            "relation_readability": {"status": "sufficient",
                                                "supported_scope": "合成原图与冻结裁片可读的主导关系",
                                                "unproven_scope": "不证明画外细节和最终交付图位尺度"},
                                            "viewport_competition": {"competing_foci": [],
                                                "effect_on_dominant_relation": "合成冻结视窗没有额外竞争焦点"},
                                            "category_assignment": fixture_category(i)} for i in selected],
                       "hardest_pair": {"card_ids": selected[:2], "comparison": "合成边界对比"},
                       "design_quality_choice": "不是根据代码分数选择"})
    else:
        selected = []
    return {"groups": groups, "not_selected": [{"card_id": i, "reason": "本窗未选"} for i in ids if i not in selected],
            "carry_ids": selected[:8] if len(selected) < 6 else [], "dna_issues": []}


class FakeModel:
    """保存与生产一致的输入/回执边界，回答只为测试预设，不发网络。"""

    def __init__(self, modifier=None):
        self.calls = []
        self.modifier = modifier

    def __call__(self, folder, *, system, payload, images, schema):
        self.calls.append({"payload": copy.deepcopy(payload), "images": images, "system": system,
                           "schema": copy.deepcopy(schema)})
        stage = payload["task"]
        if stage == "discover":
            ids = [row["card_id"] for row in payload["cards"]]
            answer = {"templates": [{**relation_template(ids), "candidate_ids": ids}] if len(ids) > 1 else [],
                      "unassigned": [] if len(ids) > 1 else [{"card_id": i, "reason": "本批孤立"} for i in ids]}
        elif stage == "merge":
            packets = payload["templates"]
            ids = list(dict.fromkeys(row["card_id"] for packet in packets for row in packet["evidence_cards"]))
            answer = {"templates": [{**relation_template(ids), "source_template_ids": [r["template"]["template_id"] for r in packets]}],
                      "merge_reason": "合成跨批组合检查"}
        elif stage == "catalogue":
            answer = {"coverage_summary": "涵盖不同具体关系的目录，不是同一板", "important_differences": ["各子方向仍独立"], "unknowns": []}
        elif stage == "route":
            target = payload["choices"][0]["node_id"]
            answer = {"assignments": [{"card_id": row["card_id"], "target_ids": [payload.get("allowed_target_ids_by_card", {}).get(row["card_id"], [target])[0]], "status": "routed", "reason": "合成组合关系"}
                                      for row in payload["cards"]]}
        elif stage == "select_directions":
            answer = {"decisions": [{"template_id": row["template_id"],
                                     "decision": "selected" if index < payload["selection_limit"] else "deferred",
                                     "reason": "合成方向假设；不提前验收整板"}
                                    for index, row in enumerate(payload["templates"])]}
        elif stage == "nominate":
            ids = [row["card_id"] for row in payload["cards"]]
            nominated = ids[:payload["selection_limit"]]
            answer = {"nominated_ids": nominated, "not_nominated": [{"card_id": i, "reason": "本次比较池预算取舍"} for i in ids if i not in nominated],
                      "selection_reason": "合成关系与设计表达择优，非真实审美结论"}
        else:
            answer = visual_answer([row["card_id"] for row in payload["cards"]])
        if self.modifier:
            answer = self.modifier(stage, payload, answer)
        folder.mkdir(parents=True)
        (folder / "system.txt").write_text(system + "\n")
        group.write_new(folder / "payload.json", payload)
        group.write_new(folder / "schema.json", schema)
        (folder / "prompt.txt").write_text(system + "\n=== ACTUAL PAYLOAD ===\n" + json.dumps(payload, ensure_ascii=False))
        group.write_new(folder / "answer.json", answer)
        metadata = {"status": "completed", "answer_ref": group.reference(folder / "answer.json"),
                    "started_at": "2026-10-10T00:00:00+00:00",
                    "requested_model": "gpt-6.1-sol", "requested_reasoning_effort": "high", "actual_model": "gpt-6.1-sol",
                    "images": images, "schema_ref": group.reference(folder / "schema.json"),
                    "prompt_ref": group.reference(folder / "prompt.txt"), "runtime_ref": group.reference(SCRIPT.with_name("model_runtime.py")),
                    "event_parser_ref": group.reference(group.TRANSPORT)}
        group.write_new(folder / "request.json", metadata)
        group.write_new(folder / "receipt.json", metadata)
        return answer


def cards(root, count=8, branch="CMF"):
    output = []
    for index in range(count):
        path = root / f"image-{index}.png"
        Image.new("RGB", (20, 20), (index, 70, 180)).save(path)
        output.append({"card_id": f"c{index}", "image_id": f"i{index}", "image_sha256": group.digest(path), "local_path": str(path),
                       "branch": branch, "subject": {"identity": "可辨设计对象", "role": "primary", "bbox": [0, 0, 1, 1], "whole_visible": True},
                       "display_bbox": [0, 0, 1, 1], "evidence_bbox": [0, 0, 1, 1], "display_scope": "whole_object",
                       "crop_reason": "冻结整体", "category": fixture_category(f"c{index}")["category_key"],
                       "relations": {name: {"observation": "合成可见关系", "evidence": ["合成证据"], "unknown": False} for name in group.RELATIONS},
                       "design_emotion": {"expression": "合成设计情绪", "coordination_reason": "组合关系", "counter_signals": []},
                       "design_quality": {"level": "distinctive", "evidence": ["合成构造依据"]}, "style_candidates": [], "limitations": [],
                       "runway": "no", "sources": [{"article_id": f"a{index}", "project_id": f"p{index}"}], "provenance": {}})
    return output


def document(rows):
    return {"schema_version": "prism.design_cards.v1", "cards": rows,
            "images": [{"image_id": row["image_id"], "sha256": row["image_sha256"], "status": "observed"} for row in rows]}


class RelationalGroupingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rows = cards(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, fake=None, maximum=60, workers=1):
        return group.ModelCalls(self.root / "run", group.POLICY.read_text(), workers=workers, max_calls=maximum, execute=fake or FakeModel())

    def test_model_decides_members_and_only_visual_groups_become_boards(self):
        fake = FakeModel()
        result = group.run_pipeline(document(self.rows), self.runner(fake))
        stages = [call["payload"]["task"] for call in fake.calls]
        self.assertEqual(stages, ["discover", "route", "nominate", "visual"])
        board = result["boards"]["boards"][0]
        visual = fake.calls[-1]["payload"]
        self.assertEqual(board["unit_ids"], list(reversed([row["card_id"] for row in visual["cards"]])))
        self.assertTrue(board["visual_selection_performed"])
        self.assertFalse(board["independent_review"])
        self.assertEqual(result["clusters"]["summary"]["dna_extraction_calls"], 0)
        self.assertEqual(result["clusters"]["summary"]["independent_review_calls"], 0)
        self.assertEqual(set(result["clusters"]["summary"]["phase_timing"]), {"discover", "merge", "route_including_catalogue", "nominate", "visual"})
        self.assertGreaterEqual(result["clusters"]["summary"]["wall_seconds"], 0)
        self.assertEqual(len(visual["image_bindings"]), 8)
        self.assertTrue(any(image["role"] == "original_context" for image in fake.calls[-1]["images"]))

    def test_early_unassigned_card_still_participates_in_global_route(self):
        def leave_one(stage, payload, answer):
            if stage == "discover":
                ids = [r["card_id"] for r in payload["cards"]]
                selected = ids[:-1]
                answer = {"templates": [{**relation_template(selected), "candidate_ids": selected}],
                          "unassigned": [{"card_id": ids[-1], "reason": "本批缺同伴"}]}
            return answer
        fake = FakeModel(leave_one)
        result = group.run_pipeline(document(self.rows), self.runner(fake), card_batch_size=4)
        routed = {row["card_id"] for call in fake.calls if call["payload"]["task"] == "route" for row in call["payload"]["cards"]}
        self.assertEqual(routed, {row["card_id"] for row in self.rows})
        self.assertIn("merge", [call["payload"]["task"] for call in fake.calls])
        self.assertEqual(result["clusters"]["summary"]["cards_routed_to_leaf"], 8)

    def test_budget_shortfall_is_partial_and_every_residual_is_visible(self):
        result = group.run_pipeline(document(self.rows), self.runner(maximum=1))
        self.assertEqual(result["clusters"]["summary"]["status"], "partial")
        self.assertEqual(result["clusters"]["summary"]["model_calls_started"], 1)
        self.assertEqual(len(result["clusters"]["residual_cards"]), 8)
        self.assertFalse(result["boards"]["boards"])

    def test_missing_route_row_is_not_silent_success(self):
        def omit(stage, payload, answer):
            if stage == "route":
                answer["assignments"].pop()
            return answer
        result = group.run_pipeline(document(self.rows), self.runner(FakeModel(omit)))
        self.assertEqual(result["clusters"]["summary"]["status"], "partial")
        self.assertEqual(len(result["clusters"]["residual_cards"]), 8)

    def test_source_collision_blocks_group_without_replacing_members(self):
        self.rows[1]["sources"] = copy.deepcopy(self.rows[0]["sources"])
        result = group.run_pipeline(document(self.rows), self.runner())
        self.assertFalse(result["boards"]["boards"])
        row = result["clusters"]["clusters"][0]
        self.assertEqual(row["status"], "constraint_blocked")
        self.assertEqual(len(row["unit_ids"]), 8)
        self.assertFalse(row["constraints"]["automatic_member_replacement"])

    def test_unknown_runway_and_project_do_not_become_verified_no(self):
        self.rows[0]["runway"] = "unknown"
        self.rows[0]["sources"] = [{"article_id": "a0"}]
        check = group.constraint_check(self.rows, {row["card_id"]: fixture_category(row["card_id"]) for row in self.rows})
        self.assertEqual(check["runway"]["status"], "unknown")
        self.assertEqual(check["runway"]["unknown"], ["c0"])
        self.assertEqual(check["project_independence"], "unknown")
        self.assertFalse(check["violations"])

    def test_known_runway_limit_and_alias_article_are_enforced(self):
        for row in self.rows[:3]:
            row["runway"] = "yes"
        self.rows[0]["sources"].append({"article_id": "a7"})
        check = group.constraint_check(self.rows)
        self.assertIn("runway_limit_exceeded", check["violations"])
        self.assertIn("same_article_or_project", check["violations"])

    def test_category_limit_integer_boundaries_and_exact_fifty_percent(self):
        rows = cards(self.root, 10)
        for count, maximum in ((6, 3), (7, 3), (8, 4), (9, 4), (10, 5)):
            for extra in (0, 1):
                with self.subTest(count=count, chairs=maximum + extra):
                    assignments = {row["card_id"]: {"status": "known", "basis": "合成对象归一",
                        "category_key": "chairs" if index < maximum + extra else ("cabinets", "watches", "garments")[index % 3]}
                        for index, row in enumerate(rows[:count])}
                    result = group.constraint_check(rows[:count], assignments)
                    category = result["category_limit"]
                    self.assertEqual(category["maximum_per_category"], maximum)
                    self.assertEqual(category["policy_version"], group.CATEGORY_LIMIT_POLICY_VERSION)
                    self.assertEqual(category["comparison"], "category_count*2<=total_images")
                    self.assertEqual(category["total_images"], count)
                    self.assertEqual(category["counts"]["chairs"], maximum + extra)
                    self.assertEqual(category["status"], "passed" if extra == 0 else "exceeded")
                    self.assertEqual("category_limit_exceeded" in result["violations"], bool(extra))
                    self.assertFalse(category["semantic_normalization_verified_by_code"])

    def test_two_categories_at_fifty_percent_can_form_a_board(self):
        """合成各占一半的候选应通过配额门，不额外要求第三品类。"""
        def two_categories(stage, payload, answer):
            if stage == "visual":
                for index, member in enumerate(answer["groups"][0]["member_evidence"]):
                    member["category_assignment"] = {
                        "category_key": "chairs" if index < 4 else "watches",
                        "status": "known", "basis": "合成冻结对象，品类各占一半"}
            return answer

        fake = FakeModel(two_categories)
        result = group.run_pipeline(document(self.rows), self.runner(fake))
        self.assertEqual(len(result["boards"]["boards"]), 1)
        board = result["boards"]["boards"][0]
        self.assertEqual(board["constraints"]["category_limit"]["counts"], {"chairs": 4, "watches": 4})
        self.assertEqual(board["constraints"]["category_limit"]["status"], "passed")
        self.assertFalse(board["independent_review"])

    def test_category_unknown_or_missing_never_becomes_unique_category(self):
        assignments = {row["card_id"]: fixture_category(row["card_id"]) for row in self.rows}
        assignments["c0"] = {"status": "unknown", "category_key": None, "basis": "无法确定冻结对象品类"}
        assignments.pop("c1")
        result = group.constraint_check(self.rows, assignments)
        self.assertEqual(result["category_limit"]["status"], "unknown")
        self.assertEqual(result["category_limit"]["unknown_card_ids"], ["c0", "c1"])
        self.assertEqual(sum(result["category_limit"]["counts"].values()), 6)
        self.assertIn("category_assignment_unverified", result["violations"])
        absent = group.constraint_check(self.rows)
        self.assertEqual(absent["category_limit"]["counts"], {})
        self.assertEqual(len(absent["category_limit"]["unknown_card_ids"]), 8)

    def test_repeated_original_cannot_inflate_category_denominator(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]["image_sha256"] = rows[-2]["image_sha256"]
        result = group.constraint_check(rows, {row["card_id"]: fixture_category(row["card_id"]) for row in rows})
        self.assertIn("duplicate_original", result["violations"])
        self.assertEqual(result["category_limit"]["total_images"], 7)
        self.assertEqual(result["category_limit"]["maximum_per_category"], 3)

    def test_same_category_board_is_blocked_without_filtering_discovery_or_routing(self):
        for category_key in ("chairs", "interior_spaces"):
            with self.subTest(category=category_key):
                rows = copy.deepcopy(self.rows)
                for row in rows:
                    row["category"] = category_key

                def same_category(stage, payload, answer):
                    if stage == "visual":
                        for entry in answer["groups"][0]["member_evidence"]:
                            entry["category_assignment"] = {"status": "known", "category_key": category_key,
                                                              "basis": "合成同类对象，未按材料或房间功能拆类"}
                    return answer

                fake = FakeModel(same_category)
                runner = group.ModelCalls(self.root / category_key, group.POLICY.read_text(), workers=1, max_calls=4, execute=fake)
                result = group.run_pipeline(document(rows), runner)
                self.assertFalse(result["boards"]["boards"])
                selected = result["clusters"]["clusters"][0]
                self.assertEqual(selected["status"], "constraint_blocked")
                self.assertEqual(selected["constraints"]["category_limit"]["counts"], {category_key: 8})
                self.assertEqual(len(selected["unit_ids"]), 8)
                self.assertFalse(selected["constraints"]["automatic_member_replacement"])
                self.assertEqual([call["payload"]["task"] for call in fake.calls], ["discover", "route", "nominate", "visual"])
                for call in fake.calls:
                    self.assertEqual(len(call["payload"]["cards"]), 8)
                self.assertEqual(result["clusters"]["summary"]["dna_extraction_calls"], 0)
                actual = fake.calls[-1]
                self.assertEqual(actual["payload"]["category_assignment_version"], group.CATEGORY_ASSIGNMENT_VERSION)
                self.assertIn(group.TASK_GUIDANCE["visual"], actual["system"])

    def test_small_same_category_group_is_retained_without_claiming_quota_pass(self):
        def same_category(stage, payload, answer):
            if stage == "visual":
                for row in answer["groups"][0]["member_evidence"]:
                    row["category_assignment"] = {"status": "known", "category_key": "chairs", "basis": "合成三把椅子"}
            return answer
        result = group.run_pipeline(document(self.rows[:3]), self.runner(FakeModel(same_category)))
        row = result["clusters"]["clusters"][0]
        self.assertEqual(row["status"], "small_cluster")
        self.assertEqual(row["constraints"]["category_limit"]["status"], "not_formal_size")
        self.assertFalse(row["constraints"]["category_limit"]["formal_board_eligible"])
        self.assertFalse(result["boards"]["boards"])

    def test_visual_category_assignment_is_required_and_rejects_placeholder_keys(self):
        mutations = {
            "missing": lambda entry: entry.pop("category_assignment"),
            "other": lambda entry: entry["category_assignment"].update(category_key="other"),
            "product": lambda entry: entry["category_assignment"].update(category_key="product"),
            "design": lambda entry: entry["category_assignment"].update(category_key="design"),
            "unknown_alias": lambda entry: entry["category_assignment"].update(status="unknown", category_key="unknown_a"),
            "no_basis": lambda entry: entry["category_assignment"].update(basis=" "),
        }
        template = {**relation_template(["c0", "c1"]), "template_id": "category-test", "branch": "CMF"}
        request = group.make_visual_task(template, ["c0", "c1"], {row["card_id"]: row for row in self.rows}, self.root / "crops", 0)
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                def malformed(stage, payload, answer):
                    mutate(answer["groups"][0]["member_evidence"][0])
                    return answer
                fake = FakeModel(malformed)
                runner = group.ModelCalls(self.root / name, group.POLICY.read_text(), workers=1, max_calls=1, execute=fake)
                result = runner.run([request])[0]
                self.assertEqual(result["record"]["status"], "failed_no_retry")
                self.assertIsNone(result["answer"])
                self.assertEqual(len(fake.calls), 1)

    def test_small_cluster_requires_real_visual_selection_and_is_not_padded(self):
        result = group.run_pipeline(document(self.rows[:3]), self.runner())
        self.assertEqual(result["clusters"]["clusters"][0]["status"], "small_cluster")
        self.assertTrue(result["clusters"]["clusters"][0]["visual_selection_performed"])
        self.assertFalse(result["boards"]["boards"])

    def test_visual_evidence_requires_dominant_relation_scope_and_competing_foci(self):
        mutations = {
            "dominant_relation": lambda row: row.pop("dominant_relation"),
            "relation_readability": lambda row: row["member_evidence"][0].pop("relation_readability"),
            "supported_scope": lambda row: row["member_evidence"][0]["relation_readability"].pop("supported_scope"),
            "unproven_scope": lambda row: row["member_evidence"][0]["relation_readability"].pop("unproven_scope"),
            "viewport_competition": lambda row: row["member_evidence"][0].pop("viewport_competition"),
            "competing_foci": lambda row: row["member_evidence"][0]["viewport_competition"].pop("competing_foci"),
            "effect": lambda row: row["member_evidence"][0]["viewport_competition"].pop("effect_on_dominant_relation"),
            "blank_scope": lambda row: row["member_evidence"][0]["relation_readability"].update(supported_scope=" "),
        }
        template = {**relation_template(["c0", "c1"]), "template_id": "readability-test", "branch": "CMF"}
        request = group.make_visual_task(template, ["c0", "c1"], {row["card_id"]: row for row in self.rows}, self.root / "crops", 0)
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                def incomplete(stage, payload, answer):
                    mutate(answer["groups"][0])
                    return answer
                fake = FakeModel(incomplete)
                calls = group.ModelCalls(self.root / name, group.POLICY.read_text(), workers=1, max_calls=1, execute=fake)
                result = calls.run([request])[0]
                self.assertEqual(result["record"]["status"], "failed_no_retry")
                self.assertIsNone(result["answer"])
                self.assertEqual(len(fake.calls), 1)
                # 不通过结构闸门不会自动增补字段或发第二次模型修复原答。
                self.assertEqual(calls.attempted, 1)

    def test_limited_relation_is_retained_with_scope_but_not_delivery_approval(self):
        def limited(stage, payload, answer):
            if stage == "visual":
                row = answer["groups"][0]
                row["dominant_relation"] = "合成高彩厚重体块与繁密连接的共同组织，不是浅色或薄边门槛"
                row["member_evidence"][0]["relation_readability"] = {
                    "status": "limited", "supported_scope": "当前冻结裁片可辨的高彩块面与连接关系",
                    "unproven_scope": "原图不能证明微细表面纹理；没有评估最终HTML图位"}
                row["member_evidence"][0]["viewport_competition"] = {
                    "competing_foci": ["相邻物的高对比轮廓"],
                    "effect_on_dominant_relation": "竞争信息独立记录；不将相邻物颜色借给目标对象"}
            return answer
        fake = FakeModel(limited)
        result = group.run_pipeline(document(self.rows), self.runner(fake))
        board = result["boards"]["boards"][0]
        self.assertEqual(board["member_evidence"][0]["relation_readability"]["status"], "limited")
        self.assertFalse(board["independent_review"])
        visual = next(call for call in fake.calls if call["payload"]["task"] == "visual")
        self.assertEqual(visual["payload"]["visual_evidence_version"], group.VISUAL_EVIDENCE_VERSION)
        self.assertEqual(visual["payload"]["assessed_visual_scope"], "original_and_frozen_crops_not_delivery_layout")
        self.assertIn("繁密连接", board["dominant_relation"])
        self.assertEqual(result["clusters"]["summary"]["dna_extraction_calls"], 0)
        self.assertEqual(result["clusters"]["summary"]["independent_review_calls"], 0)
        self.assertEqual([call["payload"]["task"] for call in fake.calls], ["discover", "route", "nominate", "visual"])

    def test_insufficient_member_cannot_enter_group_or_bypass_gate_with_legacy_marker(self):
        def insufficient(stage, payload, answer):
            answer["groups"][0]["member_evidence"][0]["relation_readability"].update(
                status="insufficient", supported_scope="仅有模糊轮廓，不能支持当前共同关系",
                unproven_scope="主导关系需要的连接与纹理均不可辨，放大不能补出")
            return answer
        template = {**relation_template(["c0", "c1"]), "template_id": "insufficient-test", "branch": "CMF"}
        request = group.make_visual_task(template, ["c0", "c1"], {row["card_id"]: row for row in self.rows}, self.root / "crops", 0)
        request["payload"].pop("visual_evidence_version")
        request["payload"].pop("assessed_visual_scope")
        fake = FakeModel(insufficient)
        result = self.runner(fake).run([request])[0]
        self.assertEqual(result["record"]["status"], "failed_no_retry")
        self.assertIn("不得入组", result["record"]["reason"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["payload"]["visual_evidence_version"], group.VISUAL_EVIDENCE_VERSION)
        raw = json.loads(group.read_reference(group.reference(Path(result["record"]["path"]) / "answer.json")))
        self.assertEqual(raw["groups"][0]["member_ids"], ["c1", "c0"])
        self.assertEqual(raw["groups"][0]["member_evidence"][0]["relation_readability"]["status"], "insufficient")

    def test_limited_surface_can_preserve_visible_microtexture_without_claiming_whole_form(self):
        """合成回答只检查受限范围不被程序改写，不声称实际图片的微纹理已通过。"""
        scope = {"status": "limited", "supported_scope": "代表性表面上的微颗粒及其与边界的组织清楚可见",
                 "unproven_scope": "整体廓形与隐藏接口不在冻结裁片内，未评估最终图位"}

        def surface_answer(stage, payload, answer):
            row = answer["groups"][0]
            row["dominant_relation"] = "合成微颗粒表面与清楚边界的对照"
            for member in row["member_evidence"]:
                member["support"] = scope["supported_scope"]
                member["relation_readability"] = copy.deepcopy(scope)
            return answer

        template = {**relation_template(["c0", "c1"]), "template_id": "surface-scope-test", "branch": "CMF"}
        request = group.make_visual_task(template, ["c0", "c1"], {row["card_id"]: row for row in self.rows},
                                         self.root / "surface-crops", 0)
        fake = FakeModel(surface_answer)
        result = self.runner(fake).run([request])[0]
        self.assertEqual(result["record"]["status"], "completed")
        self.assertEqual(result["answer"]["groups"][0]["member_evidence"][0]["relation_readability"], scope)
        self.assertEqual(len(fake.calls), 1)

    def test_cmf_palette_and_id_form_can_each_be_the_current_group_dominant_relation(self):
        """检查发送的分支和模型字段未被代码改成固定 ID 优先；不证明模型真的判断正确。"""
        for branch, dominant in (("CMF", "合成高彩互补色面的组织与宽高光是主导，外形差异另核"),
                                 ("ID", "合成厚薄体块与折线连接主导，配色差异另核")):
            with self.subTest(branch=branch):
                rows = copy.deepcopy(self.rows[:2])
                for row in rows:
                    row["branch"] = branch
                template = {**relation_template(["c0", "c1"]), "template_id": "branch-test", "branch": branch}
                request = group.make_visual_task(template, ["c0", "c1"], {row["card_id"]: row for row in rows},
                                                 self.root / (branch + "-crops"), 0)

                def branch_answer(stage, payload, answer):
                    answer["groups"][0]["dominant_relation"] = dominant
                    for member in answer["groups"][0]["member_evidence"]:
                        member["support"] = dominant
                    return answer

                fake = FakeModel(branch_answer)
                runner = group.ModelCalls(self.root / (branch + "-run"), group.POLICY.read_text(),
                                          workers=1, max_calls=1, execute=fake)
                result = runner.run([request])[0]
                self.assertEqual(result["record"]["status"], "completed")
                self.assertEqual(result["answer"]["groups"][0]["dominant_relation"], dominant)
                self.assertEqual(fake.calls[0]["payload"]["branch"], branch)
                self.assertIn(group.TASK_GUIDANCE["visual"], fake.calls[0]["system"])
                self.assertNotIn("先比较主要形态、块面和线条组织，再解释辅助色面/光学关系", fake.calls[0]["system"])

    def test_unknown_observation_survives_compaction_and_category_does_not_bucket(self):
        self.rows[0]["relations"]["texture"] = {"observation": "未知不是无纹理", "evidence": [], "unknown": True}
        compact = group.compact_card(self.rows[0])
        self.assertTrue(compact["relations"]["texture"]["unknown"])
        fake = FakeModel()
        group.run_pipeline(document(self.rows), self.runner(fake))
        discovery = fake.calls[0]["payload"]["cards"]
        self.assertEqual({row["category"] for row in discovery}, set(FIXTURE_CATEGORIES))

    def test_success_cache_binds_actual_prompt_schema_images_and_model(self):
        fake = FakeModel()
        request = group.task("discover", {"cards": [group.compact_card(row) for row in self.rows], "branch": "CMF"}, group.DISCOVERY_SCHEMA)
        first = self.runner(fake, maximum=1).run([request])[0]
        self.assertEqual(first["record"]["status"], "completed")
        second = self.runner(fake, maximum=1).run([request])[0]
        self.assertEqual(second["record"]["status"], "cached")
        self.assertEqual(len(fake.calls), 1)
        folder = Path(first["record"]["path"])
        metadata = json.loads((folder / "receipt.json").read_text())
        metadata["actual_model"] = "different-model"
        (folder / "receipt.json").write_text(json.dumps(metadata))
        third = self.runner(fake, maximum=1).run([request])[0]
        self.assertEqual(third["record"]["status"], "failed_existing_no_retry")
        self.assertEqual(len(fake.calls), 1)

    def test_budget_is_total_across_resume_not_reset_by_cache(self):
        fake = FakeModel()
        one = group.task("catalogue", {"children": []}, group.SUMMARY_SCHEMA)
        two = group.task("catalogue", {"children": [], "another": True}, group.SUMMARY_SCHEMA)
        self.runner(fake, maximum=1).run([one])
        results = self.runner(fake, maximum=1).run([one, two])
        self.assertEqual([row["record"]["status"] for row in results], ["cached", "budget_exhausted"])
        self.assertEqual(len(fake.calls), 1)

    def test_provider_failure_stops_queued_and_later_requests(self):
        calls = []
        def fail(folder, **kwargs):
            calls.append(folder)
            raise RuntimeError("HTTP 429 rate_limit_exceeded")
        runner = self.runner(fail, workers=1)
        tasks = [group.task("catalogue", {"children": [], "i": i}, group.SUMMARY_SCHEMA) for i in range(4)]
        results = runner.run(tasks)
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0]["record"]["status"], "failed_no_retry")
        self.assertTrue(all(row["record"]["status"] == "blocked_after_provider_failure" for row in results[1:]))
        self.assertEqual(runner.run([tasks[-1]])[0]["record"]["status"], "blocked_after_provider_failure")

    def test_ordinary_insufficient_evidence_does_not_stop_provider_queue(self):
        self.assertFalse(group.fatal_provider_failure(self.root, "insufficient visual evidence"))
        self.assertTrue(group.fatal_provider_failure(self.root, "insufficient_quota"))

    def test_crop_is_clamped_to_actual_pixels_without_padding(self):
        card = self.rows[0]
        card["display_bbox"] = [0.5, 0.5, 0.5000001, 0.5000001]
        template = {**relation_template(["c0"]), "template_id": "t", "branch": "CMF"}
        request = group.make_visual_task(template, ["c0"], {"c0": card}, self.root / "crop-test", 0)
        binding = request["payload"]["image_bindings"][0]
        self.assertEqual(binding["actual_pixel_bbox_xyxy"], [10, 10, 20, 20])
        crop = next(row for row in request["images"] if row["role"] == "frozen_display_crop")
        with Image.open(crop["path"]) as image:
            self.assertEqual(image.size, (10, 10))
            self.assertEqual(image.getpixel((9, 9)), (0, 70, 180))

    def test_catalogue_bounds_count_only_transmitted_descriptors(self):
        # 每个节点的子树可很大，但下一层只传本节点摘要；旧错误会对隐藏子树误触发单条限额。
        templates = []
        for index in range(80):
            templates.append({**relation_template(["c0", "c1"]), "template_id": f"t{index}", "branch": "CMF"})
        runner = self.runner()
        issues = []
        result = group.build_catalogue(templates, runner, issues)
        self.assertLessEqual(len(result), group.CATALOGUE_WINDOW)
        self.assertFalse(issues)
        for row in runner.records:
            payload = json.loads((Path(row["path"]) / "payload.json").read_text())
            self.assertNotIn("children", payload["children"][0])

    def test_merge_cannot_borrow_representative_from_unclaimed_template(self):
        def borrow(stage, payload, answer):
            if stage == "merge":
                first, second = payload["templates"][:2]
                answer["templates"] = [
                    {**relation_template([second["evidence_cards"][0]["card_id"]]), "source_template_ids": [first["template"]["template_id"]]},
                    {**relation_template([second["evidence_cards"][0]["card_id"]]), "source_template_ids": [second["template"]["template_id"]]},
                ]
            return answer
        runner = self.runner(FakeModel(borrow))
        issues = []
        local = group.discover(self.rows, runner, 4, issues)
        result = group.merge_templates(local, {row["card_id"]: row for row in self.rows}, runner, issues)
        self.assertEqual(len(result), len(local))
        self.assertTrue(any("代表" in issue["reason"] or "representative_ids" in issue["reason"] for issue in issues))

    def test_global_dna_conflict_blocks_other_template_group_without_editing_members(self):
        counter = [0]
        def dispute(stage, payload, answer):
            if stage == "visual":
                counter[0] += 1
                if counter[0] == 2:
                    ids = [row["card_id"] for row in payload["cards"]]
                    return {"groups": [], "not_selected": [{"card_id": i, "reason": "需补证据"} for i in ids],
                            "carry_ids": [], "dna_issues": [{"card_id": "c0", "reason": "原图与冻结观察矛盾"}]}
            return answer
        templates = [{**relation_template(["c0", "c1"]), "template_id": f"t{i}", "branch": "CMF"} for i in range(2)]
        candidates = {row["template_id"]: {c["card_id"] for c in self.rows} for row in templates}
        result, _ = group.visual_group(candidates, templates, self.rows, self.runner(FakeModel(dispute)), 16, [])
        self.assertEqual(result[0]["status"], "dna_evidence_blocked")
        self.assertEqual(len(result[0]["unit_ids"]), 8)
        self.assertEqual(result[0]["unresolved_dna_cards"], ["c0"])

    def test_delivery_binds_exact_compatibility_and_sample_bytes(self):
        result = group.run_pipeline(document(self.rows), self.runner())
        sample_path, card_path = self.root / "sample.json", self.root / "design-cards.json"
        group.write_new(sample_path, {"images": []})
        group.write_new(card_path, document(self.rows))
        prepared = self.root / "prepared-manifest.json"
        group.write_new(prepared, {"sample_ref": group.reference(sample_path), "design_cards_ref": group.reference(card_path)})
        out = self.root / "delivery"
        group.write_outputs(result, out, prepared)
        saved = json.loads((out / "boards.json").read_text())
        self.assertEqual(saved["input_refs"]["sample"], group.reference(sample_path))
        self.assertEqual(saved["input_refs"]["observations"], group.reference(out / "observations.compat.json"))

    def test_ten_workers_are_supported_but_more_are_rejected(self):
        self.assertEqual(self.runner(workers=10).workers, 10)
        with self.assertRaises(ValueError):
            self.runner(workers=11)

    def test_global_nomination_covers_all_cards_and_reduces_to_finite_visual_pool(self):
        rows = cards(self.root, 96)
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        def later_can_replace(stage, payload, answer):
            if stage == "nominate":
                ids = [row["card_id"] for row in payload["cards"]]
                chosen = ids[-payload["selection_limit"]:]
                return {"nominated_ids": chosen, "not_nominated": [{"card_id": i, "reason": "合成预算比较"} for i in ids if i not in chosen],
                        "selection_reason": "重新选择，不保护早批名额"}
            return answer
        fake = FakeModel(later_can_replace)
        issues = []
        pool, audit = group.nominate_candidates({"t": {row["card_id"] for row in rows}}, [template], rows, self.runner(fake), 32, issues)
        first_round = {i for row in audit if row.get("round") == 0 for i in row["candidate_ids"]}
        self.assertEqual(first_round, {row["card_id"] for row in rows})
        self.assertLessEqual(len(pool["t"]), 32)
        self.assertIn("c95", pool["t"])
        self.assertFalse(issues)
        self.assertTrue(all(not call["images"] for call in fake.calls))
        self.assertTrue(all(len(call["payload"]["cards"]) <= 32 for call in fake.calls))

    def test_small_text_batches_do_not_shrink_seven_candidates_below_board_size(self):
        rows = self.rows[:7]
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        fake, issues = FakeModel(), []
        runner = self.runner(fake)
        pool, audit = group.nominate_candidates({"t": {row["card_id"] for row in rows}}, [template], rows, runner, 4, issues)
        self.assertEqual(set(pool["t"]), {row["card_id"] for row in rows})
        self.assertEqual([call["payload"]["selection_limit"] for call in fake.calls], [4, 3])
        self.assertFalse(issues)
        pool_record = next(row for row in audit if row.get("record_type") == "template_nomination_pool")
        self.assertFalse(pool_record["all_pool_dna_compared_in_one_window"])
        groups, _ = group.visual_group(pool, [template], rows, runner, 16, issues)
        self.assertTrue(any(row["status"] == "model_grouped" and len(row["unit_ids"]) == 7 for row in groups))

    def test_long_card_text_packets_do_not_force_pool_to_single_window(self):
        rows = copy.deepcopy(self.rows[:7])
        for row in rows:
            row["relations"]["palette"]["observation"] = "合成证据" * 6500
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        fake, issues = FakeModel(), []
        pool, audit = group.nominate_candidates({"t": {row["card_id"] for row in rows}}, [template], rows, self.runner(fake), 32, issues)
        self.assertEqual(set(pool["t"]), {row["card_id"] for row in rows})
        self.assertEqual(len(fake.calls), 7)
        self.assertTrue(all(call["payload"]["selection_limit"] == 1 for call in fake.calls))
        self.assertFalse(issues)
        self.assertFalse(next(row for row in audit if row.get("record_type") == "template_nomination_pool")["all_pool_dna_compared_in_one_window"])

    def test_small_pool_does_not_force_model_to_keep_members(self):
        def reject(stage, payload, answer):
            return {"nominated_ids": [], "not_nominated": [{"card_id": row["card_id"], "reason": "模型明确不提名"}
                                                          for row in payload["cards"]], "selection_reason": "没有适合成员"}
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        pool, _ = group.nominate_candidates({"t": {row["card_id"] for row in self.rows[:7]}}, [template],
                                            self.rows[:7], self.runner(FakeModel(reject)), 4, [])
        self.assertEqual(pool["t"], [])

    def test_already_selected_board_members_all_reopen_and_can_be_replaced(self):
        rows = cards(self.root, 32)
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        def select_early_then_replace(stage, payload, answer):
            if stage == "visual" and payload["round"] == 0:
                ids = [row["card_id"] for row in payload["cards"]]
                answer = visual_answer(ids[:6])
                answer["not_selected"] = [{"card_id": i, "reason": "初选不入组但后续允许重开"} for i in ids[6:]]
                answer["carry_ids"] = []
            return answer
        fake = FakeModel(select_early_then_replace)
        issues = []
        groups, audit = group.visual_group({"t": {r["card_id"] for r in rows}}, [template], rows, self.runner(fake), 16, issues)
        versions = next(row["versions"] for row in audit if row.get("record_type") == "group_versions")
        provisional_ids = {i for row in versions if row["provisional"] for i in row["unit_ids"]}
        reopened_ids = {row["card_id"] for call in fake.calls if call["payload"]["round"] == 1 for row in call["payload"]["cards"]}
        final_ids = {i for row in groups if row["status"] == "model_grouped" for i in row["unit_ids"]}
        self.assertTrue(provisional_ids <= reopened_ids)
        self.assertTrue(provisional_ids - final_ids)
        self.assertTrue(any(row["status"] == "provisional_superseded" for row in versions))
        self.assertFalse(issues)
        coverage = next(row for row in audit if row.get("record_type") == "template_visual_coverage")
        self.assertTrue(coverage["all_selected_enter_reopen"])
        self.assertFalse(coverage["unreopened_selected_ids"])

    def test_route_beam_is_global_per_depth_not_three_for_every_parent(self):
        templates = [{**relation_template(["c0", "c1"]), "template_id": f"t{i:03}", "branch": "CMF"} for i in range(80)]
        def choose_three(stage, payload, answer):
            if stage == "route":
                for assignment in answer["assignments"]:
                    assignment["target_ids"] = [row["node_id"] for row in payload["choices"][:3]]
            return answer
        fake = FakeModel(choose_three)
        issues = []
        candidates, audit = group.route(self.rows, templates, self.runner(fake), 32, issues)
        self.assertFalse(issues)
        for card in self.rows:
            self.assertEqual(sum(card["card_id"] in ids for ids in candidates.values()), 3)
        route_calls = [call for call in fake.calls if call["payload"]["task"] == "route"]
        self.assertEqual(len(route_calls), 3)
        self.assertEqual(len(route_calls[-1]["payload"]["choices"]), 24)

    def test_cached_template_identity_keeps_downstream_requests_reusable(self):
        fake = FakeModel()
        first = group.run_pipeline(document(self.rows), self.runner(fake), card_batch_size=4)
        total_calls = len(fake.calls)
        second = group.run_pipeline(document(self.rows), self.runner(fake), card_batch_size=4)
        self.assertEqual(len(fake.calls), total_calls)
        self.assertEqual(second["clusters"]["summary"]["model_calls_started"], 0)
        self.assertEqual([row["template_id"] for row in first["templates"]["merged"]],
                         [row["template_id"] for row in second["templates"]["merged"]])

    def test_failed_call_without_call_folder_is_not_retried_after_resume(self):
        count = []
        def failure(folder, **kwargs):
            count.append(folder)
            raise RuntimeError("quota exhausted before request folder exists")
        first = group.task("catalogue", {"children": [], "i": 0}, group.SUMMARY_SCHEMA)
        later = group.task("catalogue", {"children": [], "i": 1}, group.SUMMARY_SCHEMA)
        self.runner(failure).run([first, later])
        fake = FakeModel()
        resumed = self.runner(fake).run([first, later])
        self.assertEqual(resumed[0]["record"]["status"], "failed_existing_no_retry")
        self.assertEqual(resumed[1]["record"]["status"], "completed")
        self.assertEqual(len(count), 1)
        self.assertEqual(len(fake.calls), 1)

    def test_partial_report_resume_archives_output_and_records_budget_increase(self):
        out = self.root / "resume"
        contract = {"max_calls": 10, "input": "frozen"}
        group.prepare_run_directory(out, contract, resume=False)
        group.write_new(out / "clusters.json", {"summary": {"status": "partial"}})
        group.write_new(out / "boards.json", {"boards": []})
        group.prepare_run_directory(out, {**contract, "max_calls": 20}, resume=True)
        self.assertFalse((out / "clusters.json").exists())
        self.assertEqual(len(list((out / "report-history").glob("*/clusters.json"))), 1)
        self.assertEqual(len(list((out / "budget-amendments").glob("*.json"))), 1)
        self.assertEqual(json.loads((out / "run-contract.json").read_text()), contract)
        with self.assertRaises(ValueError):
            group.prepare_run_directory(out, {"max_calls": 20, "input": "changed"}, resume=True)

    def test_reopen_budget_shortfall_does_not_promote_locked_provisional_boards(self):
        rows = cards(self.root, 32)
        template = {**relation_template(["c0", "c1"]), "template_id": "t", "branch": "CMF"}
        issues = []
        groups, audit = group.visual_group({"t": {r["card_id"] for r in rows}}, [template], rows, self.runner(maximum=2), 16, issues)
        self.assertTrue(issues)
        self.assertFalse(any(row["status"] == "model_grouped" for row in groups))
        self.assertTrue(all(row["status"] == "provisional_pending_reopen" for row in groups))
        coverage = next(row for row in audit if row.get("record_type") == "template_visual_coverage")
        self.assertTrue(coverage["unreopened_selected_ids"])

    def test_reference_brief_is_not_transmitted_to_any_production_stage(self):
        """检查真正的发送边界；不以文案含免责声明代替隔离，也不验证假模型审美。"""
        self.rows[0]["relations"]["palette"]["observation"] = "候选自身为鲜红主块、深紫细线；证据必须保留"
        compact = [group.compact_card(row) for row in self.rows[:2]]
        template = {**relation_template([row["card_id"] for row in compact]), "template_id": "fixture-T", "branch": "CMF"}
        selection_schema = group.obj({"decisions": group.arr(group.obj({
            "template_id": group.IDENTIFIER,
            "decision": {"type": "string", "enum": ["selected", "deferred", "not_suitable", "needs_evidence"]},
            "reason": group.TEXT}))})
        requests = [
            group.task("discover", {"cards": compact, "branch": "CMF"}, group.DISCOVERY_SCHEMA),
            group.task("merge", {"templates": [{"template": template, "evidence_cards": compact}]}, group.MERGE_SCHEMA),
            group.task("catalogue", {"children": [{"description": template}]}, group.SUMMARY_SCHEMA),
            group.task("route", {"cards": compact, "choices": [{"node_id": "fixture-T", "description": template}]}, group.ROUTE_SCHEMA),
            group.task("select_directions", {"templates": [{**template, "evidence_cards": compact}], "selection_limit": 1}, selection_schema),
            group.task("nominate", {"cards": compact, "template": template, "selection_limit": 2}, group.NOMINATE_SCHEMA),
            group.make_visual_task(template, [row["card_id"] for row in compact], {r["card_id"]: r for r in self.rows}, self.root / "shared-crops", 0),
        ]
        brief = {"schema_version": "prism.reference_alignment_brief.v1", "references": [
            {"id": f"teaching-only-{i}", "palette": palette, "image_ref": {"path": f"/nonexistent-reference-{i}.png", "sha256": "not-sent"}}
            for i, palette in enumerate(("白", "银", "蓝", "粉彩"))]}
        recolored = copy.deepcopy(brief)
        for row in recolored["references"]:
            row["palette"] = "彩虹黑绿：仅修改参考教材，不修改候选证据"
        reordered = {**brief, "references": list(reversed(brief["references"])),
                     "arbitrary_teaching_field": "教学附录 SENTINEL 应绝不出现在生产请求中"}
        baseline_calls = baseline_keys = None
        for index, variant in enumerate((None, brief, recolored, reordered)):
            fake = FakeModel()
            runner = group.ModelCalls(self.root / f"isolated-{index}", group.POLICY.read_text(), workers=1,
                                      max_calls=7, execute=fake, reference_brief=variant)
            results = runner.run(requests)
            self.assertEqual(set(call["payload"]["task"] for call in fake.calls), set(group.TASK_GUIDANCE))
            self.assertTrue(all(row["record"]["status"] == "completed" for row in results))
            keys = [row["record"]["input_key"] for row in results]
            if baseline_calls is None:
                baseline_calls, baseline_keys = fake.calls, keys
            else:
                self.assertEqual(fake.calls, baseline_calls)
                self.assertEqual(keys, baseline_keys)
            for call in fake.calls:
                self.assertIn(group.GROUPING_PRINCIPLES.read_text(), call["system"])
                self.assertEqual(call["payload"]["grouping_principles"]["sha256"], group.digest(group.GROUPING_PRINCIPLES))
                self.assertNotIn("teaching-only", group.encoded(call))
                self.assertNotIn("SENTINEL", group.encoded(call))
            for call in fake.calls:
                if "cards" in call["payload"]:
                    self.assertEqual(call["payload"]["cards"][0]["relations"]["palette"], compact[0]["relations"]["palette"])
            self.assertTrue(all(image["role"] != "reference_board" for call in fake.calls for image in call["images"]))

    def test_reference_changes_reuse_same_request_but_principles_changes_do_not(self):
        fake = FakeModel()
        request = group.task("catalogue", {"children": []}, group.SUMMARY_SCHEMA)
        principle_path = self.root / "neutral-principles.md"
        principle_path.write_text("# 合成中性规则 v1\n比较实际关系。\n")
        with patch.object(group, "GROUPING_PRINCIPLES", principle_path):
            runner = self.runner(fake)
            first = runner.run([request])[0]
            changed_reference = group.ModelCalls(self.root / "run", group.POLICY.read_text(), workers=1, max_calls=60,
                                                execute=fake, reference_brief={"references": ["任意新颜色和顺序"]})
            second = changed_reference.run([request])[0]
            self.assertEqual(first["record"]["input_key"], second["record"]["input_key"])
            self.assertEqual(second["record"]["status"], "cached")
            self.assertEqual(len(fake.calls), 1)
            principle_path.write_text("# 合成中性规则 v1\n比较实际关系，明确相对最弱成员的反证。\n")
            third = self.runner(fake).run([request])[0]
            self.assertNotEqual(first["record"]["input_key"], third["record"]["input_key"])
            self.assertEqual(third["record"]["status"], "completed")
            self.assertNotEqual(fake.calls[0]["payload"]["grouping_principles"], fake.calls[1]["payload"]["grouping_principles"])
            principle_path.write_text(principle_path.read_text().replace("v1", "v2", 1))
            fourth = self.runner(fake).run([request])[0]
            self.assertNotEqual(third["record"]["input_key"], fourth["record"]["input_key"])
            self.assertEqual(fake.calls[-1]["payload"]["grouping_principles"]["version"], "v2")
            planned = json.loads((runner.out / "requests" / ("catalogue-" + first["record"]["input_key"] + ".json")).read_text())
            self.assertEqual(planned["grouping_principles"], runner.grouping_principles_binding)

    def test_cli_dry_contract_traces_reference_without_authorizing_model_input(self):
        prepared = self.root / "prepared.json"
        brief = self.root / "reference.json"
        group.write_new(prepared, {"synthetic_fixture": True})
        group.write_new(brief, {"schema_version": "prism.reference_alignment_brief.v1", "references": ["教材甲", "教材乙"]})
        output = self.root / "dry-output"
        captured = io.StringIO()
        args = [str(SCRIPT), "--prepared", str(prepared), "--out", str(output), "--reference-brief", str(brief)]
        with patch.object(sys, "argv", args), patch.object(group, "load_prepared", return_value=document(self.rows)), redirect_stdout(captured):
            group.main()
        result = json.loads(captured.getvalue())
        self.assertEqual(result["status"], "dry_run_no_model_calls")
        self.assertEqual(result["contract"]["comparison_mode"], "unified")
        self.assertEqual(result["contract"]["grouping_principles"], group.load_grouping_principles(group.unified_module().POLICY)[1])
        self.assertEqual(result["contract"]["reference_brief_ref"], group.reference(brief))
        self.assertEqual(result["contract"]["reference_brief_usage"], "traceability_only_not_model_input")
        self.assertFalse(output.exists())

    def test_stage_a_request_identity_is_independent_of_grouping_teaching(self):
        """实际构建 A 的请求与复用身份；教材不成为提取缓存的新依赖。"""
        source = group.PREPARATION / "scripts/design_cards.py"
        dna_spec = importlib.util.spec_from_file_location("dna_reference_isolation_test", source)
        dna = importlib.util.module_from_spec(dna_spec)
        dna_spec.loader.exec_module(dna)
        sample, prior = self.root / "sample.json", self.root / "prior.json"
        group.write_new(sample, {"images": [{"image_id": row["image_id"], "sha256": row["image_sha256"],
            "local_path": row["local_path"], "sources": row["sources"], "source_kind": "trend"} for row in self.rows[:2]]})
        group.write_new(prior, {"schema_version": "prism.dna_cluster_observation.v3", "units": []})
        before = dna.make_plan(sample, prior, 1, 1)
        seen, original_read, original_text = [], Path.read_bytes, Path.read_text
        blocked_folder = group.GROUPING_PRINCIPLES.parent

        def tracked_read(path):
            seen.append(path.resolve())
            if path.resolve().is_relative_to(blocked_folder.resolve()):
                raise AssertionError("A 请求不应读取 B 的原则、案例或教学版本")
            return original_read(path)

        def tracked_text(path, *args, **kwargs):
            if path.resolve().is_relative_to(blocked_folder.resolve()):
                raise AssertionError("A 请求不应读取 B 的原则、案例或教学版本")
            seen.append(path.resolve())
            return original_text(path, *args, **kwargs)

        # 改变 B 的规则入口、参考颜色与教学字段，也不向 A 增加任何隐式输入。
        teaching = self.root / "teaching-only.json"
        group.write_new(teaching, {"references": ["四张图重新排序", "新增颜色"], "extra_lesson": "教材变化"})
        with (patch.object(group, "GROUPING_PRINCIPLES", teaching), patch.object(Path, "read_bytes", tracked_read),
              patch.object(Path, "read_text", tracked_text)):
            after = dna.make_plan(sample, prior, 1, 1)
        self.assertEqual(before, after)
        self.assertEqual(len(after[1]), 2)
        self.assertNotIn(teaching.resolve(), seen)

    def test_wire_schema_removes_unique_items_but_local_schema_rejects_duplicates(self):
        fake = FakeModel(lambda stage, payload, answer: {**answer, "nominated_ids": ["c0", "c0"]})
        request = group.task("nominate", {"cards": [group.compact_card(row) for row in self.rows[:2]],
                                          "selection_limit": 2}, group.NOMINATE_SCHEMA)
        result = self.runner(fake).run([request])[0]
        self.assertEqual(result["record"]["status"], "failed_no_retry")
        local = result["task"]["schema"]
        wire = json.loads((Path(result["record"]["path"]) / "schema.json").read_text())
        self.assertTrue(local["properties"]["nominated_ids"]["uniqueItems"])
        self.assertNotIn("uniqueItems", group.encoded(wire))
        self.assertEqual(wire["properties"]["nominated_ids"]["items"]["enum"], ["c0", "c1"])

    def test_first_real_task_failure_prevents_entire_parallel_schema_burst(self):
        started = []
        def incompatible(folder, **kwargs):
            started.append(folder)
            raise RuntimeError("invalid_json_schema: uniqueItems unsupported")
        requests = [group.task("catalogue", {"children": [], "i": i}, group.SUMMARY_SCHEMA) for i in range(44)]
        runner = self.runner(incompatible, workers=10)
        results = runner.run(requests)
        self.assertEqual(len(started), 1)
        self.assertEqual(runner.budget_used, 1)
        self.assertEqual(results[0]["record"]["status"], "failed_no_retry")
        self.assertTrue(all(row["record"]["status"] == "blocked_after_provider_failure" for row in results[1:]))

    def test_schema_first_task_is_not_an_extra_probe_and_success_unblocks_workers(self):
        fake, first_done, lock = FakeModel(), [False], threading.Lock()
        def execute(folder, **kwargs):
            with lock:
                if kwargs["payload"]["i"]:
                    self.assertTrue(first_done[0])
            answer = fake(folder, **kwargs)
            if not kwargs["payload"]["i"]:
                first_done[0] = True
            return answer
        requests = [group.task("catalogue", {"children": [], "i": i}, group.SUMMARY_SCHEMA) for i in range(5)]
        result = self.runner(execute, workers=10).run(requests)
        self.assertEqual(len(fake.calls), 5)
        self.assertTrue(all(row["answer"] for row in result))

    def test_invalid_schema_is_not_retried_indirectly_on_same_version_resume(self):
        def incompatible(folder, **kwargs):
            raise RuntimeError("invalid_json_schema: unsupported schema")
        requests = [group.task("catalogue", {"children": [], "i": i}, group.SUMMARY_SCHEMA) for i in range(3)]
        self.runner(incompatible, workers=10).run(requests)
        fake = FakeModel()
        result = self.runner(fake, workers=10).run(requests)
        self.assertFalse(fake.calls)
        self.assertEqual(result[0]["record"]["status"], "failed_existing_no_retry")
        self.assertTrue(all(row["record"]["status"] == "blocked_after_provider_failure" for row in result[1:]))

    def test_different_frontiers_share_packet_without_borrowing_candidate_authority(self):
        nodes = [{"node_id": f"t{i}", "description": {"relationship": "合成关系"}, "children": []} for i in range(2)]
        requests, plan = group.pack_routing_frontiers([([nodes[0]], self.rows[:1], 2), ([nodes[1]], self.rows[1:2], 2)], "CMF", 32)
        self.assertEqual(len(requests), 1)
        self.assertEqual(plan["original_count_only_packets"], 2)
        self.assertEqual(requests[0]["payload"]["allowed_target_ids_by_card"], {"c0": ["t0"], "c1": ["t1"]})
        def borrow(stage, payload, answer):
            answer["assignments"][0]["target_ids"] = ["t1"]
            return answer
        result = self.runner(FakeModel(borrow)).run(requests)[0]
        self.assertEqual(result["record"]["status"], "failed_no_retry")
        self.assertIn("逐卡授权", result["record"]["reason"])

    def test_routing_budget_includes_union_choices_cards_and_authority_map(self):
        queue = []
        for index, card in enumerate(self.rows):
            node = {"node_id": f"t{index}", "description": {"evidence": "文" * 15000}, "children": []}
            queue.append(([node], [card], 1))
        requests, _ = group.pack_routing_frontiers(queue, "CMF", 32)
        self.assertLess(len(requests), len(queue))
        self.assertTrue(all(len(group.encoded(row["payload"])) <= group.MAX_PAYLOAD_CHARACTERS for row in requests))
        actual = {card_id: ids for row in requests for card_id, ids in row["payload"]["allowed_target_ids_by_card"].items()}
        self.assertEqual(actual, {f"c{i}": [f"t{i}"] for i in range(8)})

    def test_partial_catalogue_failure_preserves_all_original_leaves(self):
        fake, counter = FakeModel(), [0]
        def fail_one(folder, **kwargs):
            counter[0] += 1
            if counter[0] == 2:
                raise RuntimeError("ordinary upstream interruption")
            return fake(folder, **kwargs)
        templates = [{**relation_template(["c0", "c1"]), "template_id": f"t{i}", "branch": "CMF"} for i in range(16)]
        issues = []
        nodes = group.build_catalogue(templates, self.runner(fail_one), issues)
        def leaves(items):
            return {value for node in items for value in (leaves(node["children"]) if node["children"] else {node["node_id"]})}
        self.assertEqual(leaves(nodes), {row["template_id"] for row in templates})
        self.assertTrue(issues)

    def test_priority_mode_directly_compares_all_branch_cards_and_does_not_claim_approval(self):
        fake = FakeModel()
        result = group.run_pipeline(document(self.rows), self.runner(fake), card_batch_size=4,
                                    mode="priority_boards", target_boards=1, direction_limit=2)
        stages = [call["payload"]["task"] for call in fake.calls]
        self.assertIn("select_directions", stages)
        self.assertNotIn("catalogue", stages)
        routed = {row["card_id"] for call in fake.calls if call["payload"]["task"] == "route" for row in call["payload"]["cards"]}
        self.assertEqual(routed, {row["card_id"] for row in self.rows})
        summary = result["clusters"]["summary"]
        self.assertFalse(summary["priority_goal"]["target_achievement_verified"])
        self.assertIsNone(summary["priority_goal"]["aligned_board_count"])
        viewed = {row["card_id"] for call in fake.calls if call["payload"]["task"] == "visual" for row in call["payload"]["cards"]}
        self.assertEqual(summary["branch_coverage"]["CMF"]["actually_visually_compared"], len(viewed))
        self.assertTrue(result["execution-plan"]["plans"])

    def test_priority_global_consolidation_keeps_actual_representative_and_boundary_dna(self):
        templates = [{**relation_template(["c0", "c1"]), "candidate_ids": ["c0", "c1"],
                      "template_id": f"t{i}", "branch": "CMF"} for i in range(12)]
        fake, issues = FakeModel(), []
        selected, audit = group.select_directions(templates, {row["card_id"]: row for row in self.rows},
                                                  self.runner(fake), 2, 1, issues)
        self.assertFalse(issues)
        self.assertEqual(len(selected), 2)
        self.assertEqual(audit[-1]["phase"], "global_consolidation")
        self.assertGreater(len(fake.calls), 1)
        for call in fake.calls:
            for template in call["payload"]["templates"]:
                self.assertEqual({row["card_id"] for row in template["evidence_cards"]}, {"c0", "c1"})
                self.assertEqual(template["evidence_cards"][0]["relations"], group.compact_card(self.rows[0])["relations"])

    def test_priority_missing_evidence_is_rejected_before_model(self):
        template = {**relation_template(["absent", "c1"]), "candidate_ids": ["absent", "c1"], "template_id": "t", "branch": "CMF"}
        fake, issues = FakeModel(), []
        chosen, _ = group.select_directions([template], {row["card_id"]: row for row in self.rows}, self.runner(fake), 1, 1, issues)
        self.assertFalse(chosen)
        self.assertFalse(fake.calls)
        self.assertEqual(issues[0]["status"], "missing_selection_evidence_before_call")

    def test_priority_requires_explicit_target_and_capacity(self):
        with self.assertRaises(ValueError):
            group.run_pipeline(document(self.rows), self.runner(), mode="priority_boards")

    def test_reuse_templates_binds_actual_historical_answer_and_same_prepared(self):
        fake, runner = FakeModel(), self.runner()
        issues = []
        templates = group.discover(self.rows, runner, 32, issues)
        prepared = self.root / "prepared.json"
        group.write_new(prepared, {"synthetic": True})
        source = self.root / "snapshot.json"
        snapshot = {"prepared_ref": group.reference(prepared), "templates": templates}
        group.write_new(source, snapshot)
        catalogue = group.load_template_catalogue(source, prepared, document(self.rows))
        result = group.run_pipeline(document(self.rows), self.runner(fake), mode="priority_boards", target_boards=1,
                                    direction_limit=2, template_catalogue=catalogue)
        self.assertNotIn("discover", [row["payload"]["task"] for row in fake.calls])
        self.assertNotIn("merge", [row["payload"]["task"] for row in fake.calls])
        self.assertEqual(result["clusters"]["summary"]["reused_template_catalogue_ref"], group.reference(source))
        history = result["clusters"]["summary"]["historical_template_context"]
        self.assertEqual(history["current_principles_recalibration"], "historical_unrecalibrated")
        self.assertFalse(history["historical_templates_are_current_principles_approved"])
        snapshot["templates"][0]["common_relations"]["palette"] = "被篡改"
        tampered = self.root / "tampered.json"
        group.write_new(tampered, snapshot)
        with self.assertRaises(ValueError):
            group.load_template_catalogue(tampered, prepared, document(self.rows))
        other_prepared = self.root / "other-prepared.json"
        group.write_new(other_prepared, {"synthetic": "different"})
        with self.assertRaises(ValueError):
            group.load_template_catalogue(source, other_prepared, document(self.rows))

    def test_reuse_template_identity_covers_derived_candidates_and_template_id(self):
        issues, runner = [], self.runner()
        local = group.discover(self.rows, runner, 4, issues)
        merged = group.merge_templates(local, {row["card_id"]: row for row in self.rows}, runner, issues)
        prepared = self.root / "prepared.json"
        group.write_new(prepared, {"synthetic": True})
        folder = self.root / "old-grouping"
        group.write_new(folder / "run-contract.json", {"prepared_ref": group.reference(prepared)})
        group.write_new(folder / "templates.json", {"local": local, "merged": merged})
        loaded = group.load_template_catalogue(folder, prepared, document(self.rows))
        self.assertEqual(len(loaded["merged"]), len(merged))
        tampered = copy.deepcopy(merged)
        # candidate_ids不是merge原答字段，仍必须由历史模板身份绑定，不能静默删改。
        removable = next(i for i in tampered[0]["candidate_ids"] if i not in tampered[0]["representative_ids"] + tampered[0]["boundary_ids"])
        tampered[0]["candidate_ids"].remove(removable)
        source = self.root / "wrong-candidates.json"
        group.write_new(source, {"prepared_ref": group.reference(prepared), "templates": tampered})
        with self.assertRaisesRegex(ValueError, "历史模板身份"):
            group.load_template_catalogue(source, prepared, document(self.rows))

    def test_unselected_branch_is_explicit_not_failed_dna(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["branch"] = "ID"
        def no_directions(stage, payload, answer):
            if stage == "select_directions":
                for row in answer["decisions"]:
                    row["decision"] = "deferred"
            return answer
        result = group.run_pipeline(document(rows), self.runner(FakeModel(no_directions)),
                                    mode="priority_boards", target_boards=1, direction_limit=2)
        self.assertEqual(result["clusters"]["summary"]["branch_coverage"]["ID"]["not_selected_direction"], 1)
        self.assertTrue(all(row["status"] == "no_selected_direction" for row in result["clusters"]["residual_cards"]))


if __name__ == "__main__":
    unittest.main()
