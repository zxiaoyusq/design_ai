"""严格校验模型作业回复，所有测试离线执行。"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "trend_contracts", Path(__file__).parents[1] / "scripts" / "contracts.py"
)
contracts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contracts)


def job(stage: str, payload: dict, **limits: int) -> dict:
    if stage in {"theme", "screen", "audit", "draft", "review"} and "source_records" not in payload:
        payload["source_records"] = {item["record_id"]: {
            "id": item["record_id"], "kind": item["kind"], "profile": {},
            "fields": {item["field"]: item["quote"], "question": "合成问题，仅用于上下文"},
        } for item in payload.get("evidence", [])}
    return {"id": "job-1", "stage": stage, "skill_version": "2.3.0", "payload": payload, "limits": limits}


def evidence_item(identifier: str, kind: str, relation: str) -> dict:
    field = "summary_zh" if kind == "trend" else "ai_analysis" if kind == "user_qa" else "ai_index"
    return {"id": identifier, "kind": kind, "relation": relation, "record_id": f"source-{identifier}",
            "field": field, "quote": f"合成设计证据 {identifier}", "dimensions": ["material"]}


def evidence() -> list[dict]:
    return [
        evidence_item("t1", "trend", "support"),
        evidence_item("u1", "user_qa", "conditional"),
        evidence_item("u2", "user_demand", "counter"),
        evidence_item("o1", "orphan_demand", "unrelated"),
    ]


def card() -> dict:
    return {
        "title": "克制的表面", "thesis": "以细腻触感建立层次", "user_tension": "精致感与干扰之间的取舍",
        "design_principle": "控制装饰密度，保留材质差异",
        "claims": [{"text": "用户有条件地接受低干扰设计", "evidence_ids": ["t1", "u1"]}],
        "opportunities": [{"category": "家居", "proposal": "尝试哑光小样验证迁移假设", "evidence_ids": ["u1"]}],
        "boundaries": [{"text": "部分用户需要明显辨识度", "evidence_ids": ["u2"]}],
        "supporting_evidence_ids": ["t1", "u1"], "counter_evidence_ids": ["u2"],
        "priority": "contextual",
        "rationale": "存在双侧证据，同时受到场景限制",
    }


class ContractTests(unittest.TestCase):
    def extract_fixture(self) -> tuple[dict, dict]:
        records = [
            {"id": "t1", "kind": "trend", "fields": {"summary_zh": "采用哑光表面和温暖的配色。"}},
            {"id": "u1", "kind": "user_qa", "fields": {"ai_analysis": "我喜欢 P20 的哑光表面，但不喜欢 P21 的透明效果。"}},
            {"id": "u2", "kind": "user_demand", "fields": {"ai_index": "没有明确设计信息。"}},
        ]
        observation = {
            "record_id": "u1", "quote": "我喜欢 P20 的哑光表面",
            "dimensions": ["material"], "stance": "support", "image_roles": {"P20": "target"},
        }
        response = {
            "job_id": "job-1", "observations": [observation], "skipped": [
                {"record_id": "t1", "status": "unclear", "reason": "信息不足"},
                {"record_id": "u2", "status": "not_design", "reason": "无明确设计信息"},
            ],
        }
        return job("extract", {"records": records}), response

    def test_extract_valid_and_empty_jobs(self):
        request, response = self.extract_fixture()
        contracts.validate_response(request, response)
        empty = {"job_id": "job-1", "observations": [], "skipped": []}
        contracts.validate_response(job("extract", {"records": []}), empty)
        normalized = contracts.normalize_extract(job("extract", {"records": []}), empty)
        self.assertEqual(normalized, {"job_id": "job-1", "observations": [], "coverage": []})

    def test_compact_short_text_restores_full_source_without_mutating_reply(self):
        request, response = self.extract_fixture()
        source = "我喜欢温暖的哑光配色与细腻触感，室内使用时更合适。"
        request["payload"]["records"][1]["fields"]["ai_analysis"] = source
        response["observations"][0] = {
            "record_id": "u1", "dimensions": ["material", "color", "touch"], "stance": "conditional",
        }
        before_request, before_response = copy.deepcopy(request), copy.deepcopy(response)
        normalized = contracts.normalize_extract(request, response)
        observation = normalized["observations"][0]
        self.assertEqual(observation["field"], "ai_analysis")
        self.assertEqual(observation["quote"], source)
        self.assertEqual(observation["claim"], source)
        self.assertEqual(observation["dimensions"], ["material", "color", "touch"])
        self.assertEqual({name: observation[name] for name in ("category", "context", "user_value")},
                         {"category": "", "context": "", "user_value": ""})
        self.assertEqual(observation["image_codes"], [])
        self.assertEqual(observation["image_roles"], {})
        self.assertEqual([item["record_id"] for item in normalized["coverage"]], ["t1", "u1", "u2"])
        self.assertEqual(normalized["coverage"][1], {"record_id": "u1", "status": "extracted", "reason": ""})
        normalized["observations"][0]["dimensions"].append("form")
        normalized["coverage"][0]["reason"] = "修改副本"
        self.assertEqual(request, before_request)
        self.assertEqual(response, before_response)

    def test_default_fields_and_explicit_trend_field_preserve_original_text(self):
        fixtures = [
            ("trend", {"summary_zh": "这是概念原型。", "title_zh": "概念椅"}, "summary_zh"),
            ("trend", {"title_zh": "概念椅"}, "title_zh"),
            ("user_qa", {"ai_analysis": " 只在室内喜欢。 ", "question": "为什么？"}, "ai_analysis"),
            ("user_demand", {"ai_index": "轻巧但需防滑。"}, "ai_index"),
            ("orphan_demand", {"ai_index": "轻巧但需防滑。"}, "ai_index"),
        ]
        for kind, fields, expected in fixtures:
            with self.subTest(kind=kind, fields=fields):
                record = {"id": "r1", "kind": kind, "fields": fields}
                request = job("extract", {"records": [record]})
                response = {"job_id": "job-1", "observations": [{
                    "record_id": "r1", "dimensions": ["form"],
                    "stance": "example" if kind == "trend" else "conditional",
                }], "skipped": []}
                normalized = contracts.normalize_extract(request, response)["observations"][0]
                self.assertEqual(contracts.default_extract_field(record), expected)
                self.assertEqual(normalized["field"], expected)
                self.assertEqual(normalized["quote"], fields[expected])
        request["payload"]["records"][0] = {
            "id": "r1", "kind": "trend", "fields": {"summary_zh": "", "title_zh": "概念椅"},
        }
        response["observations"][0]["stance"] = "example"
        with self.assertRaisesRegex(ValueError, "不得为空"):
            contracts.validate_response(request, response)
        response["observations"][0]["field"] = "title_zh"
        self.assertEqual(contracts.normalize_extract(request, response)["observations"][0]["quote"], "概念椅")

    def test_long_text_requires_explicit_quote_and_never_truncates(self):
        request, response = self.extract_fixture()
        observation = response["observations"][0]
        observation.pop("quote")
        observation.pop("image_roles")
        request["payload"]["records"][1]["fields"]["ai_analysis"] = "字" * 600
        self.assertEqual(len(contracts.normalize_extract(request, response)["observations"][0]["quote"]), 600)
        request["payload"]["records"][1]["fields"]["ai_analysis"] = "字" * 601 + "，仅适用于室内。"
        with self.assertRaisesRegex(ValueError, "显式提供连续引用"):
            contracts.validate_response(request, response)
        observation["quote"] = "仅适用于室内。"
        self.assertEqual(contracts.normalize_extract(request, response)["observations"][0]["quote"], "仅适用于室内。")
        observation["quote"] = "字" * 601
        with self.assertRaisesRegex(ValueError, "超过 600"):
            contracts.validate_response(request, response)

    def test_image_roles_are_optional_and_do_not_invent_a_target(self):
        request, response = self.extract_fixture()
        observation = response["observations"][0]
        for role in ("target", "comparison", "reference", "unclear"):
            observation["image_roles"] = {"P20": role}
            restored = contracts.normalize_extract(request, response)["observations"][0]
            self.assertEqual(restored["image_codes"], ["P20"])
            self.assertEqual(restored["image_roles"], {"P20": role})
        observation.pop("image_roles")
        restored = contracts.normalize_extract(request, response)["observations"][0]
        self.assertEqual(restored["image_roles"], {})
        self.assertEqual(restored["image_codes"], [])
        observation["image_roles"] = {}
        contracts.validate_response(request, response)

    def test_mixed_attitudes_can_share_one_record_with_separate_quotes_and_roles(self):
        request, response = self.extract_fixture()
        response["observations"].append({
            "record_id": "u1", "quote": "不喜欢 P21 的透明效果",
            "dimensions": ["material", "form"], "stance": "counter", "image_roles": {"P21": "comparison"},
        })
        normalized = contracts.normalize_extract(request, response)
        self.assertEqual(len(normalized["observations"]), 2)
        self.assertEqual(normalized["observations"][1]["image_roles"], {"P21": "comparison"})
        self.assertEqual(sum(item["status"] == "extracted" for item in normalized["coverage"]), 1)

    def test_invalid_dimensions_roles_and_old_observation_fields_are_rejected(self):
        mutations = [
            {"dimensions": []}, {"dimensions": ["material", "material"]},
            {"dimensions": ["material", "color", "touch", "form"]}, {"dimensions": "material"},
            {"image_roles": {"P20": "target", "P21": "comparison"}},
            {"image_roles": {"P20": "positive"}}, {"image_roles": []},
            {"claim": "偏好哑光"}, {"category": "手机"}, {"context": "室内"},
            {"user_value": "舒适"}, {"image_codes": ["P20"]}, {"field": None}, {"quote": None},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                request, response = self.extract_fixture()
                response["observations"][0].update(mutation)
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)
        request, response = self.extract_fixture()
        observation = response["observations"][0]
        observation["dimension"] = observation.pop("dimensions")[0]
        with self.assertRaises(ValueError):
            contracts.validate_response(request, response)

    def test_coverage_error_reports_count_duplicates_and_missing_together(self):
        request, response = self.extract_fixture()
        original = copy.deepcopy(response)
        response["skipped"] = [response["skipped"][0]] * 4
        with self.assertRaises(ValueError) as captured:
            contracts.validate_response(request, response)
        message = str(captured.exception)
        for expected in ("期望 3 项", "实际 5 项", "重复", "t1", "遗漏", "u2"):
            self.assertIn(expected, message)
        self.assertEqual(response["skipped"], [original["skipped"][0]] * 4)

    def test_quote_cannot_be_rewritten_or_borrowed_from_other_record(self):
        for quote in ("我非常喜欢 P20", "采用哑光表面和温暖的配色。"):
            with self.subTest(quote=quote):
                request, response = self.extract_fixture()
                response["observations"][0]["quote"] = quote
                with self.assertRaisesRegex(ValueError, "连续原文"):
                    contracts.validate_response(request, response)

    def test_image_code_must_appear_in_this_quote(self):
        request, response = self.extract_fixture()
        response["observations"][0]["image_roles"] = {"P21": "target"}
        with self.assertRaisesRegex(ValueError, "当前 quote"):
            contracts.validate_response(request, response)

    def test_picture_code_matches_whole_ascii_identifier(self):
        for text in ("喜欢 P253", "喜欢 AP25", "喜欢 P25A"):
            self.assertFalse(contracts.image_code_in_text("P25", text))
        for text in ("喜欢P25哑光", "P25", "(P25)", "P25、P253"):
            self.assertTrue(contracts.image_code_in_text("P25", text))
        request, response = self.extract_fixture()
        request["payload"]["records"][1]["fields"]["ai_analysis"] = "喜欢 P253 的表面"
        response["observations"][0].update(quote="喜欢 P253 的表面", image_roles={"P25": "target"})
        with self.assertRaisesRegex(ValueError, "当前 quote"):
            contracts.validate_response(request, response)

    def test_question_category_missing_and_nontext_fields_are_not_answers(self):
        for field, source, expected_error in (("question", "你喜欢哑光吗？", "问题和类别"),
                                               ("ai_analysis", None, "字符串"),
                                               ("missing", "回答", "不属于当前作业")):
            with self.subTest(field=field):
                request, response = self.extract_fixture()
                if field != "missing":
                    request["payload"]["records"][1]["fields"][field] = source
                response["observations"][0] = {"record_id": "u1", "field": field, "dimensions": ["material"], "stance": "support"}
                with self.assertRaisesRegex(ValueError, expected_error):
                    contracts.validate_response(request, response)
        request, response = self.extract_fixture()
        request["payload"]["records"][1].update(kind="trend", fields={"primary_category": "家具"})
        response["observations"][0] = {"record_id": "u1", "field": "primary_category", "quote": "家具", "stance": "example", "dimensions": ["form"]}
        with self.assertRaisesRegex(ValueError, "问题和类别"):
            contracts.validate_response(request, response)

    def test_extraction_coverage_cannot_omit_repeat_overlap_or_mislabel(self):
        for change in ("missing", "repeated", "overlap", "wrong_status", "empty_reason", "old_coverage"):
            with self.subTest(change=change):
                request, response = self.extract_fixture()
                if change == "missing":
                    response["skipped"].pop()
                elif change == "repeated":
                    response["skipped"].append(copy.deepcopy(response["skipped"][0]))
                elif change == "overlap":
                    response["skipped"].append({"record_id": "u1", "status": "unclear", "reason": "重复"})
                elif change == "wrong_status":
                    response["skipped"][0]["status"] = "extracted"
                elif change == "empty_reason":
                    response["skipped"][0]["reason"] = ""
                else:
                    response["coverage"] = response.pop("skipped")
                with self.assertRaises(ValueError):
                    contracts.normalize_extract(request, response)

    def test_stance_cannot_turn_trend_into_preference_or_user_into_case(self):
        request, response = self.extract_fixture()
        response["observations"][0]["stance"] = "example"
        with self.assertRaisesRegex(ValueError, "用户文本"):
            contracts.validate_response(request, response)
        request["payload"]["records"][1]["kind"] = "trend"
        request["payload"]["records"][1]["fields"]["summary_zh"] = request["payload"]["records"][1]["fields"]["ai_analysis"]
        contracts.validate_response(request, response)
        response["observations"][0]["stance"] = "support"
        with self.assertRaisesRegex(ValueError, "趋势案例"):
            contracts.validate_response(request, response)

    def test_extract_bounds_unknown_fields_and_wrong_normalization_stage(self):
        for change in ("too_many", "unknown", "dimension", "missing_required"):
            with self.subTest(change=change):
                request, response = self.extract_fixture()
                if change == "too_many":
                    request["limits"]["max_observations"] = 1
                    response["observations"] *= 2
                elif change == "unknown":
                    response["observations"][0]["local_path"] = "/invented.png"
                elif change == "missing_required":
                    response["observations"][0].pop("stance")
                else:
                    response["observations"][0]["dimensions"] = ["marketing"]
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)
        request, response = self.extract_fixture()
        request["stage"] = "theme"
        with self.assertRaisesRegex(ValueError, "仅适用于 extract"):
            contracts.normalize_extract(request, response)

    def propose_fixture(self) -> tuple[dict, dict]:
        return job("propose", {"evidence": evidence()}), {
            "job_id": "job-1", "candidates": [{
                "title": "方向", "thesis": "设计命题", "dimensions": ["material"],
                "evidence_ids": ["t1", "u1", "u2"],
                "trend_basis": [{"evidence_id": "t1", "reason": "案例展示所述表面"}],
                "user_basis": [{"evidence_id": "u1", "reason": "用户条件性需求"}, {"evidence_id": "u2", "reason": "用户适用边界"}],
                "shared_principle": "材料表面在具体场景中的层次", "application_hypothesis": "",
            }], "deferred": [{"evidence_id": "o1", "reason": "来源未关联"}],
        }

    def theme_fixture(self) -> tuple[dict, dict]:
        source = evidence()
        source[1]["dimensions"].append("touch")
        return job("theme", {"evidence": source}, max_themes=2), {
            "job_id": "job-1", "themes": [{
                "title": "有条件的表面偏好", "summary": "保留接受条件及反对表达",
                "dimensions": ["material", "touch"], "evidence_ids": ["t1", "u1", "u2"],
            }], "deferred": [{"evidence_id": "o1", "reason": "来源缺少关联"}],
        }

    def test_theme_partitions_all_evidence_and_allows_all_deferred(self):
        request, response = self.theme_fixture()
        contracts.validate_response(request, response)
        response["themes"] = []
        response["deferred"] = [{"evidence_id": item["id"], "reason": "暂不能归纳"} for item in evidence()]
        contracts.validate_response(request, response)

    def test_theme_requires_source_context_for_short_answers(self):
        request, response = self.theme_fixture()
        source_id = request["payload"]["evidence"][1]["record_id"]
        request["payload"]["evidence"][1]["quote"] = "喜欢"
        request["payload"]["source_records"][source_id]["fields"] = {
            "question": "在家居用品中是否喜欢哑光表面？", "ai_analysis": "喜欢",
        }
        contracts.validate_response(request, response)
        request["payload"].pop("source_records")
        with self.assertRaisesRegex(ValueError, "source_records"):
            contracts.validate_response(request, response)

    def test_theme_cannot_share_omit_or_duplicate_evidence(self):
        for change in ("share", "missing", "overlap", "duplicate", "too_many", "unknown"):
            with self.subTest(change=change):
                request, response = self.theme_fixture()
                if change == "share":
                    response["themes"] *= 2
                elif change == "missing":
                    response["deferred"] = []
                elif change == "overlap":
                    response["themes"][0]["evidence_ids"].append("o1")
                elif change == "duplicate":
                    response["deferred"] *= 2
                elif change == "too_many":
                    response["themes"] *= 3
                else:
                    response["themes"][0]["source_fields"] = {}
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)

    def test_candidate_basis_is_kind_specific_and_exactly_covers_citations(self):
        for change in ("wrong_side", "missing", "duplicate", "outside_candidate", "empty_reason", "missing_principle"):
            with self.subTest(change=change):
                request, response = self.propose_fixture()
                candidate = response["candidates"][0]
                if change == "wrong_side":
                    candidate["trend_basis"][0]["evidence_id"] = "u1"
                elif change == "missing":
                    candidate["user_basis"].pop()
                elif change == "duplicate":
                    candidate["user_basis"].append(copy.deepcopy(candidate["user_basis"][0]))
                elif change == "outside_candidate":
                    candidate["evidence_ids"].remove("u2")
                elif change == "empty_reason":
                    candidate["user_basis"][0]["reason"] = " "
                else:
                    candidate["shared_principle"] = ""
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)

    def test_candidate_cannot_cite_theme_summary_or_more_than_eight_evidence(self):
        request, response = self.propose_fixture()
        request["payload"]["user_themes"] = [{"id": "theme1", "summary": "辅助主题，不是原文"}]
        response["candidates"][0]["evidence_ids"].append("theme1")
        with self.assertRaisesRegex(ValueError, "不属于当前作业"):
            contracts.validate_response(request, response)
        request, response = self.propose_fixture()
        extra = [evidence_item(f"more-{index}", "user_qa", "support") for index in range(6)]
        request["payload"]["evidence"].extend(extra)
        response["candidates"][0]["evidence_ids"].extend(item["id"] for item in extra)
        with self.assertRaisesRegex(ValueError, "最多允许 8 项"):
            contracts.validate_response(request, response)

    def test_candidate_limit_matches_actual_job(self):
        request, response = self.propose_fixture()
        request["limits"]["max_candidates"] = 1
        response["candidates"] *= 2
        with self.assertRaisesRegex(ValueError, "最多允许 1 项"):
            contracts.validate_response(request, response)

    def test_theme_and_candidate_dimensions_must_come_from_cited_evidence(self):
        for fixture, key in ((self.theme_fixture, "themes"), (self.propose_fixture, "candidates")):
            with self.subTest(stage=key):
                request, response = fixture()
                response[key][0]["dimensions"] = ["interaction"]
                with self.assertRaisesRegex(ValueError, "不能凭空改维度"):
                    contracts.validate_response(request, response)

    def test_screen_requires_one_independent_decision_for_every_candidate(self):
        request = job("screen", {"candidates": [{"id": "c1"}, {"id": "c2"}], "evidence": evidence()})
        response = {"job_id": "job-1", "decisions": [
            {"candidate_id": "c1", "decision": "accept", "reason": "双方直接支持有限命题"},
            {"candidate_id": "c2", "decision": "reject", "reason": "制造可能性并不证明偏好"},
        ]}
        contracts.validate_response(request, response)
        for change in ("missing", "duplicate", "wrong_decision", "unknown", "empty_reason"):
            with self.subTest(change=change):
                modified = copy.deepcopy(response)
                if change == "missing":
                    modified["decisions"].pop()
                elif change == "duplicate":
                    modified["decisions"][1] = copy.deepcopy(modified["decisions"][0])
                elif change == "wrong_decision":
                    modified["decisions"][0]["decision"] = "approve"
                elif change == "unknown":
                    modified["decisions"][0]["card"] = None
                else:
                    modified["decisions"][0]["reason"] = ""
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, modified)

    def test_propose_allows_shared_evidence_and_all_deferred(self):
        request, response = self.propose_fixture()
        response["candidates"] *= 2
        contracts.validate_response(request, response)
        response["candidates"] = []
        response["deferred"] = [{"evidence_id": item["id"], "reason": "交集不足"} for item in evidence()]
        contracts.validate_response(request, response)

    def test_propose_needs_both_sides_and_orphan_is_not_user_support(self):
        for ids in (["u1", "u2"], ["t1", "o1"]):
            with self.subTest(ids=ids):
                request, response = self.propose_fixture()
                response["candidates"][0]["evidence_ids"] = ids
                with self.assertRaisesRegex(ValueError, "同时包含趋势证据"):
                    contracts.validate_response(request, response)

    def test_propose_rejects_missing_overlap_and_duplicate_deferred(self):
        for change in ("missing", "overlap", "duplicate"):
            with self.subTest(change=change):
                request, response = self.propose_fixture()
                if change == "missing":
                    response["deferred"] = []
                elif change == "overlap":
                    response["deferred"].append({"evidence_id": "u1", "reason": "延后"})
                else:
                    response["deferred"] *= 2
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)

    def test_merge_must_partition_candidates(self):
        request = job("merge", {"candidates": [{"id": "c1"}, {"id": "c2"}]})
        response = {"job_id": "job-1", "groups": [{"title": "标题", "thesis": "命题", "candidate_ids": ["c1"]}], "deferred": [{"candidate_id": "c2", "reason": "不足"}]}
        contracts.validate_response(request, response)
        response["groups"][0]["candidate_ids"].append("c2")
        with self.assertRaisesRegex(ValueError, "只能分配一次"):
            contracts.validate_response(request, response)

    def test_audit_exact_coverage_and_enum(self):
        request = job("audit", {"evidence": evidence()})
        response = {"job_id": "job-1", "assessments": [{"evidence_id": item["id"], "relation": item["relation"], "reason": "独立判断"} for item in evidence()]}
        contracts.validate_response(request, response)
        response["assessments"].pop()
        with self.assertRaisesRegex(ValueError, "遗漏"):
            contracts.validate_response(request, response)
        response["assessments"][0]["relation"] = "example"
        with self.assertRaisesRegex(ValueError, "必须为"):
            contracts.validate_response(request, response)

    def test_draft_valid_and_no_counter_case(self):
        request = job("draft", {"evidence": evidence()})
        response = {"job_id": "job-1", "card": card()}
        contracts.validate_response(request, response)
        request["payload"]["evidence"][2]["relation"] = "unrelated"
        response["card"]["counter_evidence_ids"] = []
        contracts.validate_response(request, response)

    def test_draft_preserves_counter_and_requires_true_support(self):
        for change in ("counter_omitted", "counter_as_support", "false_counter", "orphan_as_support"):
            with self.subTest(change=change):
                request = job("draft", {"evidence": evidence()})
                response = {"job_id": "job-1", "card": card()}
                if change == "counter_omitted":
                    response["card"]["counter_evidence_ids"] = []
                elif change == "counter_as_support":
                    response["card"]["supporting_evidence_ids"] = ["t1", "u2"]
                elif change == "false_counter":
                    response["card"]["counter_evidence_ids"] = ["u1"]
                else:
                    request["payload"]["evidence"][3]["relation"] = "support"
                    response["card"]["supporting_evidence_ids"] = ["t1", "o1"]
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)

    def test_draft_claims_need_real_nonduplicate_refs(self):
        for ids in ([], ["invented"], ["t1", "t1"]):
            with self.subTest(ids=ids):
                response = {"job_id": "job-1", "card": card()}
                response["card"]["claims"][0]["evidence_ids"] = ids
                with self.assertRaises(ValueError):
                    contracts.validate_response(job("draft", {"evidence": evidence()}), response)

    def test_all_counter_evidence_requires_both_index_and_boundary_citations(self):
        source = evidence() + [evidence_item("u3", "user_qa", "counter")]
        request = job("draft", {"evidence": source})
        response = {"job_id": "job-1", "card": card()}
        with self.assertRaises(ValueError):
            contracts.validate_response(request, response)
        response["card"]["counter_evidence_ids"].append("u3")
        with self.assertRaisesRegex(ValueError, "每条反证"):
            contracts.validate_response(request, response)
        response["card"]["boundaries"][0]["evidence_ids"].append("u3")
        contracts.validate_response(request, response)
        response["card"]["boundaries"] = []
        with self.assertRaisesRegex(ValueError, "每条反证"):
            contracts.validate_response(request, response)

    def test_draft_card_limits_and_unknown_fields(self):
        for name, replacement in (("title", "字" * 161), ("thesis", "字" * 801), ("claims", card()["claims"] * 9), ("priority", "high"), ("images", [])):
            with self.subTest(name=name):
                response = {"job_id": "job-1", "card": card()}
                response["card"][name] = replacement
                with self.assertRaises(ValueError):
                    contracts.validate_response(job("draft", {"evidence": evidence()}), response)

    def test_draft_and_revised_cards_reject_removed_validation_questions(self):
        # 成卡和复核修订共享严格字段集；旧字段即使为空也不能重新进入结果。
        for stage in ("draft", "review"):
            for old_value in ([], ["在家居中是否仍然接受？"]):
                with self.subTest(stage=stage, old_value=old_value):
                    request = job(stage, {"evidence": evidence()})
                    response = {"job_id": "job-1", "card": card()}
                    if stage == "review":
                        response.update(decision="revise", issues=["保留场景限制"])
                    contracts.validate_response(request, response)
                    response["card"]["validation_questions"] = old_value
                    with self.assertRaisesRegex(ValueError, "不允许未知字段.*validation_questions"):
                        contracts.validate_response(request, response)

    def test_card_prompts_and_templates_omit_removed_validation_questions(self):
        for stage in ("draft", "review"):
            with self.subTest(stage=stage):
                self.assertNotIn("validation_questions", contracts.instruction(stage))
                self.assertNotIn("validation_questions", contracts.response_template(stage)["card"])

    def test_review_revise_validates_replacement(self):
        request = job("review", {"evidence": evidence(), "card": card()})
        for decision in ("approve", "reject"):
            contracts.validate_response(request, {"job_id": "job-1", "decision": decision, "issues": ["需放弃候选"] if decision == "reject" else [], "card": None})
        response = {"job_id": "job-1", "decision": "revise", "issues": ["需限制适用范围"], "card": card()}
        contracts.validate_response(request, response)
        response["card"]["supporting_evidence_ids"] = ["u1"]
        with self.assertRaises(ValueError):
            contracts.validate_response(request, response)

    def test_review_decision_card_and_issue_consistency(self):
        for decision, replacement, issues in (("approve", card(), []), ("reject", card(), ["不足"]), ("revise", None, ["不足"]), ("reject", None, []), ("revise", card(), [])):
            with self.subTest(decision=decision, replacement=replacement is None, issues=issues):
                with self.assertRaises(ValueError):
                    contracts.validate_response(job("review", {"evidence": evidence()}), {"job_id": "job-1", "decision": decision, "issues": issues, "card": replacement})

    def test_job_ids_input_duplicates_and_wrong_types(self):
        request, response = self.extract_fixture()
        response["job_id"] = "another-job"
        with self.assertRaisesRegex(ValueError, "当前作业"):
            contracts.validate_response(request, response)
        response["job_id"] = "job-1"
        request["payload"]["records"].append(request["payload"]["records"][0])
        with self.assertRaisesRegex(ValueError, "输入 ID 重复"):
            contracts.validate_response(request, response)
        for malformed in (None, [], "{}"):
            with self.assertRaises(ValueError):
                contracts.validate_response(request, malformed)
        request, response = self.extract_fixture()
        request["limits"]["max_observations"] = True
        with self.assertRaisesRegex(ValueError, "正整数"):
            contracts.validate_response(request, response)

    def test_prior_jobs_are_incompatible_and_unspecified_version_is_current(self):
        for version in ("1.0.0", "2.0.0", "2.1.0"):
            request, response = self.extract_fixture()
            request["skill_version"] = version
            with self.assertRaisesRegex(ValueError, "不兼容旧版本"):
                contracts.validate_response(request, response)
        request.pop("skill_version")
        contracts.validate_response(request, response)

    def test_review_stages_require_independent_source_record_dictionary(self):
        responses = {
            "screen": {"decisions": [{"candidate_id": "c1", "decision": "accept", "reason": "原文支持"}]},
            "audit": {"assessments": [{"evidence_id": item["id"], "relation": item["relation"], "reason": "回查完整原文"} for item in evidence()]},
            "draft": {"card": card()},
            "review": {"decision": "approve", "issues": [], "card": None},
        }
        for stage, body in responses.items():
            with self.subTest(stage=stage):
                request = job(stage, {"evidence": evidence(), "candidates": [{"id": "c1", "parent_ids": ["previous-stage"], "shared_principle": "已校验的程序元数据"}]})
                response = {"job_id": "job-1", **body}
                contracts.validate_response(request, response)
                request["payload"].pop("source_records")
                with self.assertRaisesRegex(ValueError, "source_records"):
                    contracts.validate_response(request, response)

    def test_source_dictionary_must_really_support_each_quote(self):
        for change in ("missing_record", "wrong_kind", "invented_quote", "question_only", "old_source_fields"):
            with self.subTest(change=change):
                request = job("audit", {"evidence": evidence()})
                response = {"job_id": "job-1", "assessments": [{"evidence_id": item["id"], "relation": item["relation"], "reason": "审核"} for item in evidence()]}
                item = request["payload"]["evidence"][0]
                if change == "missing_record":
                    request["payload"]["source_records"].pop(item["record_id"])
                elif change == "wrong_kind":
                    request["payload"]["source_records"][item["record_id"]]["kind"] = "user_qa"
                elif change == "invented_quote":
                    item["quote"] = "凭空产生的原文"
                elif change == "question_only":
                    item.update(field="question", quote="合成问题，仅用于上下文")
                else:
                    item["source_fields"] = {"summary_zh": item["quote"]}
                with self.assertRaises(ValueError):
                    contracts.validate_response(request, response)

    def test_dynamic_instructions_use_only_the_actual_stage_limit(self):
        for stage, name, value in (("extract", "max_observations", 17), ("theme", "max_themes", 3), ("propose", "max_candidates", 2), ("merge", "max_groups", 1)):
            with self.subTest(stage=stage):
                request = job(stage, {}, **{name: value})
                text = contracts.instruction(stage, request)
                self.assertIn(f"数量上限为 {value}", text)
                self.assertNotIn("默认", text)
                self.assertEqual(contracts.response_template(stage, request)["job_id"], request["id"])
        self.assertIn("数量上限为 64", contracts.instruction("extract"))
        with self.assertRaises(ValueError):
            contracts.instruction("theme", job("extract", {}))

    def test_compact_template_has_constant_sized_skeleton_and_no_repeated_coverage(self):
        request, _ = self.extract_fixture()
        request["payload"]["records"] = request["payload"]["records"][1:]
        request["limits"]["max_observations"] = 7
        template = contracts.response_template("extract", request)
        self.assertNotIn("coverage", template)
        self.assertEqual(len(template["observations"]), 1)
        self.assertEqual(len(template["skipped"]), 1)
        self.assertNotIn(template["skipped"][0]["status"], {"extracted", "not_design", "unclear"})
        self.assertNotIn("example", template["observations"][0]["stance"])
        self.assertEqual(set(template["observations"][0]), {"record_id", "dimensions", "stance"})
        self.assertIn("2 条输入记录", contracts.instruction("extract", request))
        with self.assertRaises(ValueError):
            contracts.validate_response(request, template)
        request["payload"]["records"] *= 20
        expanded = contracts.response_template("extract", request)
        self.assertEqual(expanded, template)

    def test_instructions_preserve_semantic_boundaries_and_complete_review_schema(self):
        text = contracts.instruction("extract")
        for marker in ("材料微观结构归 material", "制造或定制能力不等于用户交互", "concept/prototype", "未明说的心理动机", "多个诉求", "image_roles"):
            self.assertIn(marker, text)
        for stage in ("screen", "audit", "draft", "review"):
            self.assertIn("payload.source_records[record_id].fields", contracts.instruction(stage))
            self.assertNotIn("evidence.source_fields", contracts.instruction(stage))
        review = contracts.instruction("review")
        self.assertIn("claims 每项", review)
        self.assertIn("必须完整覆盖输入的全部 counter", review)
        self.assertIn("shared_principle", contracts.instruction("screen"))

    def test_all_stage_templates_are_independent_and_document_json(self):
        for stage in ("extract", "theme", "propose", "screen", "merge", "audit", "draft", "review"):
            self.assertIn("job_id", contracts.response_template(stage))
            self.assertIn("JSON", contracts.instruction(stage))
            self.assertIn("数据", contracts.instruction(stage))
        first = contracts.response_template("draft")
        first["card"]["title"] = "更改"
        self.assertNotEqual(first, contracts.response_template("draft"))
        with self.assertRaises(ValueError):
            contracts.instruction("unknown")
        with self.assertRaises(ValueError):
            contracts.response_template("unknown")


if __name__ == "__main__":
    unittest.main()
