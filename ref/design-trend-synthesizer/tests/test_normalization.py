"""仅对可逐字核实的提取元数据做机械整理，测试不调用模型。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest


SCRIPTS = str(Path(__file__).parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from contracts import validate_response
from normalization import NORMALIZATION_VERSION, normalize_response


def fixture(text: str = "camera above 305 looks smaller than 303") -> tuple[dict, dict]:
    job = {
        "id": "job1", "stage": "extract", "payload": {"records": [{
            "id": "u1", "kind": "user_qa", "fields": {"ai_analysis": text, "question": "Which camera layout?"},
        }]},
    }
    response = {"job_id": "job1", "observations": [{
        "record_id": "u1", "dimensions": ["form"], "stance": "conditional",
        "image_roles": {"P305": "target", "P303": "comparison"},
    }], "skipped": []}
    return job, response


class NormalizationTests(unittest.TestCase):
    def test_absent_prefixed_codes_are_removed_without_guessing_numeric_codes(self):
        job, response = fixture()
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["image_roles"], {})
        self.assertNotIn("quote", normalized["observations"][0])
        self.assertNotIn("field", normalized["observations"][0])
        self.assertEqual(changes, [{
            "index": 0, "record_id": "u1", "field": "image_roles", "source_field": "ai_analysis",
            "before": {"P305": "target", "P303": "comparison"}, "after": {},
            "reason": "移除当前有效引文中未完整出现的图片编码，不猜测或补写编码",
        }])
        validate_response(job, normalized)
        self.assertEqual(NORMALIZATION_VERSION, "extract_metadata_v5")

    def test_real_code_and_comparison_role_are_preserved(self):
        job, response = fixture("camera above 305 looks smaller than P303")
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["image_roles"], {"P303": "comparison"})
        self.assertEqual(len(changes), 1)
        validate_response(job, normalized)

    def test_picture_code_must_match_whole_identifier_in_selected_quote(self):
        job, response = fixture("喜欢 P253，不喜欢 P25；P25A、AP25 仅是其他编号")
        observation = response["observations"][0]
        observation.update(quote="喜欢 P253", image_roles={"P25": "target", "P253": "comparison"})
        normalized, _ = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["image_roles"], {"P253": "comparison"})
        for quote in ("P25A", "AP25"):
            observation.update(quote=quote, image_roles={"P25": "target"})
            normalized, _ = normalize_response(job, response)
            self.assertEqual(normalized["observations"][0]["image_roles"], {})
        observation.update(quote="不喜欢 P25", image_roles={"P25": "target"})
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized, response)
        self.assertEqual(changes, [])

    def test_invalid_source_or_quote_is_not_cleaned(self):
        for mutation in ("unknown_record", "missing_field", "question", "wrong_quote", "empty_quote", "long_quote", "nontext_source", "duplicate_record", "invalid_kind"):
            with self.subTest(mutation=mutation):
                job, response = fixture()
                record = job["payload"]["records"][0]
                observation = response["observations"][0]
                observation["dimensions"] = ["form", "form"]
                if mutation == "unknown_record":
                    observation["record_id"] = "unknown"
                elif mutation == "missing_field":
                    observation["field"] = "missing"
                elif mutation == "question":
                    observation["field"] = "question"
                elif mutation == "wrong_quote":
                    observation["quote"] = "The user likes a larger camera."
                elif mutation == "empty_quote":
                    observation["quote"] = " "
                elif mutation == "long_quote":
                    record["fields"]["ai_analysis"] = "长" * 601
                elif mutation == "nontext_source":
                    record["fields"]["ai_analysis"] = None
                elif mutation == "duplicate_record":
                    job["payload"]["records"].append(deepcopy(record))
                else:
                    record["kind"] = "unknown"
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)

    def test_explicit_valid_quote_can_select_part_of_long_source(self):
        job, response = fixture("长" * 601 + "喜欢 P303")
        response["observations"][0]["quote"] = "喜欢 P303"
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["image_roles"], {"P303": "comparison"})
        self.assertEqual(normalized["observations"][0]["quote"], "喜欢 P303")
        self.assertEqual(len(changes), 1)
        validate_response(job, normalized)

    def test_illegal_role_for_a_present_code_remains_rejected(self):
        job, response = fixture("喜欢 P303")
        response["observations"][0]["image_roles"] = {"P303": "positive"}
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized, response)
        self.assertEqual(changes, [])
        with self.assertRaises(ValueError):
            validate_response(job, normalized)

    def test_dimensions_deduplicate_only_exact_legal_values_stably(self):
        job, response = fixture("喜欢细腻的暖色表面")
        response["observations"][0].update(image_roles={}, dimensions=["touch", "color", "touch", "material", "color"])
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["dimensions"], ["touch", "color", "material"])
        self.assertEqual(changes[0]["field"], "dimensions")
        self.assertEqual(changes[0]["before"], ["touch", "color", "touch", "material", "color"])
        self.assertEqual(changes[0]["after"], ["touch", "color", "material"])
        validate_response(job, normalized)

    def test_four_distinct_dimensions_and_illegal_labels_are_not_discarded(self):
        for dimensions in (["color", "material", "form", "touch"],
                           ["color", "material", "form", "touch", "color"],
                           ["color", "colour", "color"], ["form", None, "form"], "form"):
            with self.subTest(dimensions=dimensions):
                job, response = fixture()
                response["observations"][0].update(image_roles={}, dimensions=dimensions)
                normalized, _ = normalize_response(job, response)
                if isinstance(dimensions, list) and all(isinstance(value, str) for value in dimensions) and "colour" not in dimensions:
                    self.assertEqual(len(normalized["observations"][0]["dimensions"]), 4)
                else:
                    self.assertEqual(normalized["observations"][0]["dimensions"], dimensions)
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)

    def test_job_reply_and_change_values_have_no_shared_mutable_state(self):
        job, response = fixture()
        response["observations"][0]["dimensions"] = ["form", "form"]
        original_job, original_response = deepcopy(job), deepcopy(response)
        normalized, changes = normalize_response(job, response)
        self.assertEqual(len(changes), 2)
        normalized["observations"][0]["image_roles"]["P1"] = "target"
        normalized["observations"][0]["dimensions"].append("color")
        self.assertEqual(changes[0]["after"], {})
        self.assertEqual(changes[1]["after"], ["form"])
        changes[0]["before"].clear()
        changes[1]["before"].clear()
        self.assertEqual(job, original_job)
        self.assertEqual(response, original_response)

    def test_nonextract_and_malformed_envelopes_are_deepcopied_without_changes(self):
        job, response = fixture()
        for other in (dict(job, stage="theme"), dict(job, stage="propose"), None):
            normalized, changes = normalize_response(other, response)
            self.assertEqual(normalized, response)
            self.assertIsNot(normalized, response)
            normalized["observations"][0]["dimensions"].append("color")
            self.assertEqual(response["observations"][0]["dimensions"], ["form"])
            self.assertEqual(changes, [])
        for malformed in (None, "not parsed JSON", [], {"observations": "bad"}, {"observations": [None]}):
            normalized, changes = normalize_response(job, malformed)
            self.assertEqual(normalized, malformed)
            self.assertEqual(changes, [])

    def numbered_fixture(self, source, quote):
        job, response = fixture(source)
        response["observations"][0].update(quote=quote, image_roles={})
        return job, response

    def test_numbered_quote_restores_only_missing_markers_and_keeps_original_object(self):
        source = "1. 喜欢手机演示。2. 用遥控器翻页。3. 仅适用于课堂。"
        quote = "喜欢手机演示。用遥控器翻页。"
        job, response = self.numbered_fixture(source, quote)
        before_job, before_response = deepcopy(job), deepcopy(response)
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["quote"], "喜欢手机演示。2. 用遥控器翻页。")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["index"], 0)
        self.assertEqual(changes[0]["record_id"], "u1")
        self.assertEqual(changes[0]["field"], "quote")
        self.assertEqual(changes[0]["source_field"], "ai_analysis")
        self.assertEqual(changes[0]["before"], quote)
        self.assertEqual(changes[0]["after"], normalized["observations"][0]["quote"])
        self.assertEqual(job, before_job)
        self.assertEqual(response, before_response)
        validate_response(job, normalized)
        self.assertEqual(normalize_response(job, normalized), (normalized, []))

    def test_numbered_quote_preserves_newlines_indentation_and_allowed_separators(self):
        for source, quote, expected in (
            ("1、喜欢蓝色！2、 喜欢细腻表面？3、仅在家里。", "喜欢蓝色！喜欢细腻表面？", "喜欢蓝色！2、 喜欢细腻表面？"),
            ("1.甲\n  2. 乙", "甲\n  乙", "甲\n  2. 乙"),
            ("前言。1. 甲。2. 乙。", "甲。乙。", "甲。2. 乙。"),
        ):
            with self.subTest(source=source):
                job, response = self.numbered_fixture(source, quote)
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized["observations"][0]["quote"], expected)
                self.assertEqual(len(changes), 1)
                validate_response(job, normalized)
        job, response = self.numbered_fixture("1.甲\n  2. 乙", "甲乙")
        self.assertEqual(normalize_response(job, response), (response, []))

    def test_numbered_quote_does_not_restore_unconfirmed_or_noncontinuous_numbering(self):
        for source in (
            "甲。乙。", "2. 甲。3. 乙。", "1. 甲。3. 乙。", "1. 甲。2. 乙。2. 丙。",
            "0. 前文。1. 甲。2. 乙。", "01. 甲。2. 乙。", "1. 甲；2. 乙。", "1. 甲.2. 乙。",
        ):
            with self.subTest(source=source):
                job, response = self.numbered_fixture(source, "甲。乙。")
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])

    def test_numbered_quote_does_not_drop_negation_body_or_change_punctuation(self):
        source = "1. 不喜欢玻璃。2. 喜欢细腻表面，但要求耐磨。3. 仅适用于室内。"
        for quote in (
            "喜欢玻璃。喜欢细腻表面，但要求耐磨。",
            "不喜欢玻璃。仅适用于室内。",
            "不喜欢玻璃。喜欢细腻表面，但要求耐用。",
            "不喜欢玻璃。喜欢细腻表面,但要求耐磨。",
        ):
            with self.subTest(quote=quote):
                job, response = self.numbered_fixture(source, quote)
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)

    def test_numbered_quote_requires_full_items_and_preserves_internal_negation(self):
        cases = [
            ("1. 不喜欢玻璃。2. 不接受透明效果。3. 可以用金属。", "不喜欢玻璃。接受透明效果。"),
            ("1. 喜欢金属，但只有室内。2. 必须耐磨，仅限办公。", "只有室内。必须耐磨，仅限办公。"),
            ("1. 喜欢金属。2. 必须耐磨。仅限办公。", "喜欢金属。必须耐磨。"),
        ]
        for source, quote in cases:
            with self.subTest(source=source, quote=quote):
                job, response = self.numbered_fixture(source, quote)
                self.assertEqual(normalize_response(job, response), (response, []))
        source = "1. 用手机演示。2. 不接受透明效果。3. 可以用金属。"
        quote = "用手机演示。不接受透明效果。"
        job, response = self.numbered_fixture(source, quote)
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["quote"], "用手机演示。2. 不接受透明效果。")
        self.assertEqual(len(changes), 1)
        validate_response(job, normalized)

    def test_numbered_quote_preserves_decimal_prices_and_model_identifiers(self):
        source = "1. 价格1.5元，厚度0.5mm。2. 型号P303，数量2个。"
        quote = "价格1.5元，厚度0.5mm。型号P303，数量2个。"
        job, response = self.numbered_fixture(source, quote)
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["observations"][0]["quote"], "价格1.5元，厚度0.5mm。2. 型号P303，数量2个。")
        self.assertEqual(len(changes), 1)
        for altered in (quote.replace("1.5", "5"), quote.replace("0.5", "5"), quote.replace("P303", "303"), quote.replace("2个", "个")):
            job, response = self.numbered_fixture(source, altered)
            self.assertEqual(normalize_response(job, response), (response, []))
        job, response = self.numbered_fixture("1.5元。2. 其他价格。", "5元。其他价格。")
        self.assertEqual(normalize_response(job, response), (response, []))

    def test_numbered_quote_rejects_ambiguous_match_and_restored_span_over_600(self):
        job, response = self.numbered_fixture("1. 相同。2. 内容。3. 相同。4. 内容。", "相同。内容。")
        self.assertEqual(normalize_response(job, response), (response, []))
        for second_length, should_restore in ((297, True), (298, False)):
            first, second = "甲" * 298 + "。", "乙" * second_length + "。"
            job, response = self.numbered_fixture("1. " + first + "2. " + second, first + second)
            normalized, changes = normalize_response(job, response)
            if should_restore:
                self.assertEqual(len(normalized["observations"][0]["quote"]), 600)
                self.assertEqual(len(changes), 1)
                validate_response(job, normalized)
            else:
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])

    def test_numbered_quote_requires_valid_known_answer_field(self):
        for mutation in ("unknown_record", "question", "missing_field", "null_source", "unknown_kind", "missing_quote", "empty_quote"):
            with self.subTest(mutation=mutation):
                job, response = self.numbered_fixture("1. 甲。2. 乙。", "甲。乙。")
                observation = response["observations"][0]
                if mutation == "unknown_record":
                    observation["record_id"] = "unknown"
                elif mutation == "question":
                    job["payload"]["records"][0]["fields"]["question"] = "1. 甲。2. 乙。"
                    observation["field"] = "question"
                elif mutation == "missing_field":
                    observation["field"] = "missing"
                elif mutation == "null_source":
                    job["payload"]["records"][0]["fields"]["ai_analysis"] = None
                elif mutation == "unknown_kind":
                    job["payload"]["records"][0]["kind"] = "unknown"
                elif mutation == "missing_quote":
                    observation.pop("quote")
                else:
                    observation["quote"] = " "
                self.assertEqual(normalize_response(job, response), (response, []))

    def test_numbered_quote_changes_precede_metadata_then_empty_answer_moves(self):
        job, response = self.numbered_fixture("1. 喜欢P303。2. 适用于课堂。", "喜欢P303。适用于课堂。")
        response["observations"][0].update(dimensions=["form", "form"], image_roles={"P999": "target", "P303": "comparison"})
        job["payload"]["records"].append({"id": "u2", "kind": "user_qa", "fields": {"ai_analysis": ""}})
        response["observations"].append({"record_id": "u2", "dimensions": ["other"], "stance": "unclear"})
        normalized, changes = normalize_response(job, response)
        self.assertEqual([item["field"] for item in changes], ["quote", "image_roles", "dimensions", "observations/skipped"])
        self.assertEqual([item["index"] for item in changes], [0, 0, 0, 1])
        self.assertEqual(normalized["observations"][0]["image_roles"], {"P303": "comparison"})
        self.assertEqual(normalized["observations"][0]["dimensions"], ["form"])
        self.assertEqual(normalized["skipped"][0]["record_id"], "u2")
        validate_response(job, normalized)

    def skipped_fixture(self):
        job, response = fixture("没有明确设计信息。")
        job["payload"]["records"].append({"id": "u2", "kind": "user_qa", "fields": {"ai_analysis": "没有明确设计信息。"}})
        response["observations"] = []
        first = {"record_id": "u1", "status": "unclear", "reason": "未表达明确偏好"}
        second = {"record_id": "u2", "status": "unclear", "reason": "未表达明确偏好"}
        response["skipped"] = [first, second, deepcopy(first), deepcopy(second), deepcopy(first)]
        return job, response

    def test_identical_skipped_objects_deduplicate_with_original_indices_and_order(self):
        job, response = self.skipped_fixture()
        before_job, before_response = deepcopy(job), deepcopy(response)
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["skipped"], response["skipped"][:2])
        self.assertEqual(normalized["observations"], response["observations"])
        self.assertEqual([(item["index"], item["retained_index"]) for item in changes], [(2, 0), (3, 1), (4, 0)])
        self.assertEqual(len(changes), 3)
        for item in changes:
            self.assertEqual(item["field"], "skipped")
            self.assertEqual(item["source_field"], "ai_analysis")
            self.assertEqual(item["before"], response["skipped"][item["index"]])
            self.assertIsNone(item["after"])
        validate_response(job, normalized)
        self.assertEqual(normalize_response(job, normalized), (normalized, []))
        normalized["skipped"][0]["reason"] = "改变副本"
        changes[0]["before"]["reason"] = "改变差异记录"
        self.assertEqual(job, before_job)
        self.assertEqual(response, before_response)

    def test_different_skipped_reasons_or_statuses_are_never_partially_deduplicated(self):
        for mutation in ({"reason": "相似但不同的原因"}, {"reason": "未表达明确偏好 "}, {"status": "not_design"}):
            with self.subTest(mutation=mutation):
                job, response = self.skipped_fixture()
                response["skipped"] = [response["skipped"][0], deepcopy(response["skipped"][0]),
                                       dict(response["skipped"][0], **mutation), response["skipped"][1]]
                self.assertEqual(normalize_response(job, response), (response, []))
                with self.assertRaises(ValueError):
                    validate_response(job, response)

    def test_unknown_duplicate_source_and_malformed_skipped_objects_are_not_cleaned(self):
        for mutation in ("unknown", "duplicate_source", "extra_key", "missing_reason", "empty_reason", "wrong_status", "reason_type", "too_long_reason"):
            with self.subTest(mutation=mutation):
                job, response = self.skipped_fixture()
                item = response["skipped"][0]
                if mutation == "unknown":
                    item["record_id"] = "unknown"
                elif mutation == "duplicate_source":
                    job["payload"]["records"].append(deepcopy(job["payload"]["records"][0]))
                elif mutation == "extra_key":
                    item["extra"] = "不能删除未知字段"
                elif mutation == "missing_reason":
                    item.pop("reason")
                elif mutation == "empty_reason":
                    item["reason"] = " "
                elif mutation == "wrong_status":
                    item["status"] = "extracted"
                elif mutation == "reason_type":
                    item["reason"] = None
                else:
                    item["reason"] = "长" * 401
                response["skipped"] = [item, deepcopy(item), response["skipped"][1]]
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)

    def test_skipped_deduplication_does_not_resolve_observation_conflict_or_fill_missing_records(self):
        job, response = self.skipped_fixture()
        response["skipped"] = [response["skipped"][0], deepcopy(response["skipped"][0]), response["skipped"][1]]
        response["observations"] = [{"record_id": "u1", "dimensions": ["other"], "stance": "unclear"}]
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized, response)
        self.assertEqual(changes, [])
        with self.assertRaises(ValueError):
            validate_response(job, normalized)
        response["observations"] = []
        response["skipped"].pop()
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized["skipped"], response["skipped"][:1])
        self.assertEqual(len(changes), 1)
        with self.assertRaisesRegex(ValueError, "遗漏"):
            validate_response(job, normalized)

    def test_skipped_deduplication_precedes_empty_moves_without_losing_original_indices(self):
        job, response = self.skipped_fixture()
        job["payload"]["records"].append({"id": "u3", "kind": "user_demand", "fields": {"ai_index": ""}})
        response["observations"] = [{"record_id": "u3", "dimensions": ["other"], "stance": "unclear"}]
        normalized, changes = normalize_response(job, response)
        self.assertEqual([item["field"] for item in changes], ["skipped", "skipped", "skipped", "observations/skipped"])
        self.assertEqual(changes[-1]["indices"], [0])
        self.assertEqual([item["record_id"] for item in normalized["skipped"]], ["u1", "u2", "u3"])
        self.assertEqual(normalized["observations"], [])
        validate_response(job, normalized)

    def empty_answer_fixture(self, *, kind="user_qa"):
        job, response = fixture(" \n\t")
        field = "ai_analysis" if kind == "user_qa" else "ai_index"
        job["payload"]["records"][0].update(kind=kind, fields={field: " \n\t", "question": "你喜欢哪种布局？"})
        response["observations"] = [{"record_id": "u1", "dimensions": ["other"], "stance": "unclear"}]
        return job, response

    def test_empty_answer_unclear_moves_to_one_skipped_without_question_evidence(self):
        for kind in ("user_qa", "user_demand", "orphan_demand"):
            with self.subTest(kind=kind):
                job, response = self.empty_answer_fixture(kind=kind)
                field = "ai_analysis" if kind == "user_qa" else "ai_index"
                response["observations"].append({
                    "record_id": "u1", "dimensions": ["structure", "structure", "form"],
                    "stance": "unclear", "quote": " \n", "field": field, "image_roles": {},
                })
                before_job, before_response = deepcopy(job), deepcopy(response)
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized["observations"], [])
                self.assertEqual(normalized["skipped"], [{
                    "record_id": "u1", "status": "unclear", "reason": "原始回答为空，仅问题或场景不足以构成用户证据",
                }])
                self.assertEqual(len(changes), 1)
                self.assertEqual(changes[0]["source_field"], field)
                self.assertEqual(changes[0]["indices"], [0, 1])
                self.assertEqual(changes[0]["before"], response["observations"])
                self.assertEqual(changes[0]["after"], normalized["skipped"][0])
                validate_response(job, normalized)
                normalized["skipped"][0]["reason"] = "修改副本"
                changes[0]["before"][0]["dimensions"].clear()
                self.assertEqual(response, before_response)
                self.assertEqual(job, before_job)
                self.assertNotEqual(changes[0]["after"]["reason"], "修改副本")

    def test_empty_answer_with_one_unsafe_observation_is_never_partially_moved(self):
        mutations = [
            {"stance": "support"}, {"stance": "counter"}, {"stance": "conditional"}, {"stance": "example"},
            {"quote": "用户喜欢镜头布局"}, {"quote": None}, {"field": "question"},
            {"field": None}, {"image_roles": {"P305": "target"}}, {"image_roles": None},
            {"dimensions": ["other", "structure", "form", "color"]}, {"dimensions": ["marketing"]},
            {"dimensions": []}, {"dimensions": "other"}, {"claim": "没有回答"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                job, response = self.empty_answer_fixture()
                unsafe = deepcopy(response["observations"][0])
                unsafe.update(mutation)
                response["observations"].append(unsafe)
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)
        job, response = self.empty_answer_fixture()
        response["observations"].append({"record_id": "u1", "stance": "unclear"})
        normalized, changes = normalize_response(job, response)
        self.assertEqual(normalized, response)
        self.assertEqual(changes, [])

    def test_empty_answer_never_overwrites_skipped_or_fills_missing_coverage(self):
        for scenario in ("skipped_conflict", "skipped_missing", "skipped_wrong_type", "omitted_record"):
            with self.subTest(scenario=scenario):
                job, response = self.empty_answer_fixture()
                if scenario == "skipped_conflict":
                    response["skipped"] = [{"record_id": "u1", "status": "not_design", "reason": "已有原始声明"}]
                elif scenario == "skipped_missing":
                    response.pop("skipped")
                elif scenario == "skipped_wrong_type":
                    response["skipped"] = None
                else:
                    response["observations"] = []
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])
                with self.assertRaises(ValueError):
                    validate_response(job, normalized)

    def test_empty_answer_rule_requires_known_user_source_and_string_answer(self):
        for scenario in ("unknown_record", "missing_answer", "null_answer", "nonempty_answer", "trend", "unknown_kind"):
            with self.subTest(scenario=scenario):
                job, response = self.empty_answer_fixture()
                record = job["payload"]["records"][0]
                if scenario == "unknown_record":
                    response["observations"][0]["record_id"] = "unknown"
                elif scenario == "missing_answer":
                    record["fields"].pop("ai_analysis")
                elif scenario == "null_answer":
                    record["fields"]["ai_analysis"] = None
                elif scenario == "nonempty_answer":
                    record["fields"]["ai_analysis"] = "不确定是否适合"
                elif scenario == "trend":
                    record.update(kind="trend", fields={"summary_zh": "", "title_zh": "问题是怎样设计？"})
                else:
                    record["kind"] = "unknown"
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized, response)
                self.assertEqual(changes, [])

    def test_empty_moves_preserve_original_indices_and_other_record_order(self):
        job, response = self.empty_answer_fixture()
        job["payload"]["records"].extend([
            {"id": "u2", "kind": "user_qa", "fields": {"ai_analysis": "喜欢 P303"}},
            {"id": "u3", "kind": "user_demand", "fields": {"ai_index": ""}},
        ])
        response["observations"].insert(0, {
            "record_id": "u2", "dimensions": ["form", "form"], "stance": "support", "image_roles": {"P999": "target"},
        })
        response["observations"].append(deepcopy(response["observations"][1]))
        response["skipped"] = [{"record_id": "u3", "status": "unclear", "reason": "模型已注明为空"}]
        normalized, changes = normalize_response(job, response)
        self.assertEqual([item["record_id"] for item in normalized["observations"]], ["u2"])
        self.assertEqual([item["record_id"] for item in normalized["skipped"]], ["u3", "u1"])
        self.assertEqual([item["field"] for item in changes], ["image_roles", "dimensions", "observations/skipped"])
        self.assertEqual(changes[-1]["indices"], [1, 2])
        self.assertEqual(changes[-1]["index"], 1)
        validate_response(job, normalized)
        second, second_changes = normalize_response(job, normalized)
        self.assertEqual(second, normalized)
        self.assertEqual(second_changes, [])

    def test_trend_fallback_and_demand_defaults_use_only_their_source_fields(self):
        for kind, fields, expected in (("trend", {"title_zh": "305 concept"}, "title_zh"),
                                       ("trend", {"summary_zh": "305 concept", "title_zh": "P303"}, "summary_zh"),
                                       ("user_demand", {"ai_index": "305 camera"}, "ai_index"),
                                       ("orphan_demand", {"ai_index": "305 camera"}, "ai_index")):
            with self.subTest(kind=kind, fields=fields):
                job, response = fixture()
                job["payload"]["records"][0].update(kind=kind, fields=fields)
                if kind == "trend":
                    response["observations"][0]["stance"] = "example"
                normalized, changes = normalize_response(job, response)
                self.assertEqual(normalized["observations"][0]["image_roles"], {})
                self.assertEqual(changes[0]["source_field"], expected)
                validate_response(job, normalized)


class LongQuoteNormalizationTests(unittest.TestCase):
    def long_fixture(self, text=None):
        text = text or ("细腻材质" * 70 + "。\n  " + "需要耐磨" * 85 + "。")
        job, response = fixture(text)
        response["observations"][0].update(quote=text, image_roles={})
        return job, response

    def test_full_sentence_split_keeps_exact_text_attributes_offsets_and_hashes(self):
        job, response = self.long_fixture()
        original = deepcopy(response)
        quote = original["observations"][0]["quote"]
        normalized, changes = normalize_response(job, response)
        parts = normalized["observations"]
        self.assertEqual(len(parts), 2)
        self.assertEqual("".join(part["quote"] for part in parts), quote)
        self.assertTrue(all(0 < len(part["quote"]) <= 600 for part in parts))
        self.assertEqual(response, original)
        self.assertTrue(all(part["stance"] == "conditional" and part["dimensions"] == ["form"] for part in parts))
        self.assertTrue(all("field" not in part for part in parts))
        self.assertEqual(len(changes), 1)
        log = changes[0]
        self.assertEqual(log["operation"], "split_explicit_long_quote")
        self.assertEqual((log["original_index"], log["record_id"], log["source_field"]), (0, "u1", "ai_analysis"))
        self.assertEqual(log["quote_sha256"], hashlib.sha256(quote.encode()).hexdigest())
        self.assertEqual(log["source_sha256"], hashlib.sha256(quote.encode()).hexdigest())
        self.assertEqual(log["before"], original["observations"][0])
        self.assertEqual(log["after"], parts)
        for offset, part in zip(log["fragments"], parts):
            self.assertEqual(quote[offset["start"]:offset["end"]], part["quote"])
        self.assertEqual(log["fragments"][0]["end"], log["fragments"][1]["start"])
        validate_response(job, normalized)
        self.assertEqual(normalize_response(job, normalized), (normalized, []))
        parts[0]["dimensions"].append("color")
        self.assertEqual(parts[1]["dimensions"], ["form"])
        self.assertEqual(log["after"][0]["dimensions"], ["form"])
        self.assertEqual(response, original)

    def test_33_declared_roles_partition_without_dropping_or_guessing(self):
        text = "".join(f"不喜欢 P{index}：" + "表面颜色过于鲜艳" * 2 + "。" for index in range(1, 34))
        job, response = self.long_fixture(text)
        roles = {f"P{index}": "target" for index in range(1, 34)}
        response["observations"][0]["image_roles"] = roles
        normalized, changes = normalize_response(job, response)
        parts = normalized["observations"]
        self.assertEqual(len(parts), 2)
        self.assertEqual([len(part["image_roles"]) for part in parts], [20, 13])
        self.assertEqual("".join(part["quote"] for part in parts), text)
        self.assertEqual({key: value for part in parts for key, value in part["image_roles"].items()}, roles)
        self.assertEqual([offset["image_roles"] for offset in changes[0]["fragments"]],
                         [part["image_roles"] for part in parts])
        validate_response(job, normalized)

    def test_same_existing_role_is_preserved_where_code_occurs_in_each_fragment(self):
        text = "P1：" + "质感" * 180 + "。" + "P1、P2：" + "耐磨" * 180 + "。"
        job, response = self.long_fixture(text)
        response["observations"][0]["image_roles"] = {"P1": "comparison", "P2": "target"}
        normalized, _ = normalize_response(job, response)
        self.assertEqual([part["image_roles"] for part in normalized["observations"]],
                         [{"P1": "comparison"}, {"P1": "comparison", "P2": "target"}])
        validate_response(job, normalized)

    def test_undeclared_roles_remain_omitted(self):
        job, response = self.long_fixture()
        del response["observations"][0]["image_roles"]
        normalized, _ = normalize_response(job, response)
        self.assertTrue(all("image_roles" not in part for part in normalized["observations"]))
        validate_response(job, normalized)

    def test_observation_budget_is_checked_for_all_splits_before_any_mutation(self):
        job, response = self.long_fixture()
        response["observations"].append(deepcopy(response["observations"][0]))
        for budget in (1, 2, 3, 0, True, None):
            with self.subTest(budget=budget):
                job["limits"] = {"max_observations": budget}
                self.assertEqual(normalize_response(job, response), (response, []))
        job["limits"] = {"max_observations": 4}
        normalized, changes = normalize_response(job, response)
        self.assertEqual(len(normalized["observations"]), 4)
        self.assertEqual([item["original_index"] for item in changes], [0, 1])
        self.assertEqual([[part["index"] for part in item["fragments"]] for item in changes], [[0, 1], [2, 3]])
        validate_response(job, normalized)

    def test_unsafe_original_attributes_are_never_hidden_by_split(self):
        mutations = [
            {"record_id": "unknown"}, {"field": "question"}, {"field": "missing"}, {"field": None},
            {"dimensions": ["form", "form"]}, {"dimensions": []}, {"dimensions": ["bad"]},
            {"dimensions": ["color", "material", "form", "touch"]}, {"dimensions": "form"},
            {"stance": "example"}, {"stance": "unknown"}, {"stance": None},
            {"image_roles": None}, {"image_roles": {"absent": "target"}},
            {"image_roles": {"细腻材质": "invalid"}}, {"image_roles": {"": "target"}},
            {"claim": "多余的属性"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                job, response = self.long_fixture()
                response["observations"][0].update(mutation)
                self.assertEqual(normalize_response(job, response), (response, []))
                with self.assertRaises(ValueError):
                    validate_response(job, response)

    def test_wrong_source_or_noncontiguous_quote_is_not_repaired(self):
        for mutation in ("no_quote", "reordered", "nontext", "duplicate_record", "wrong_kind"):
            with self.subTest(mutation=mutation):
                job, response = self.long_fixture()
                record, observation = job["payload"]["records"][0], response["observations"][0]
                if mutation == "no_quote":
                    del observation["quote"]
                elif mutation == "reordered":
                    observation["quote"] = observation["quote"][300:] + observation["quote"][:300]
                elif mutation == "nontext":
                    record["fields"]["ai_analysis"] = None
                elif mutation == "duplicate_record":
                    job["payload"]["records"].append(deepcopy(record))
                else:
                    record["kind"] = "unknown"
                self.assertEqual(normalize_response(job, response), (response, []))

    def test_ambiguous_or_overlong_sentence_is_not_cut_or_truncated(self):
        for text in ("长" * 601 + "。短句。", "长" * 320 + "；" + "短" * 320 + "。",
                     "长" * 320 + "\n" + "短" * 320 + "。", "长" * 320 + ". " + "短" * 320 + "。",
                     "长" * 320 + "。" + "短" * 320, "“" + "长" * 320 + "。" + "短" * 320 + "。",
                     "（" + "长" * 320 + "。" + "短" * 320 + "。）"):
            with self.subTest(text=text[:20]):
                job, response = self.long_fixture(text)
                self.assertEqual(normalize_response(job, response), (response, []))

    def test_sentence_with_more_than_20_roles_is_not_cut_inside_sentence(self):
        text = "、".join(f"P{index}" for index in range(21)) + "。" + "质感" * 290 + "。"
        job, response = self.long_fixture(text)
        response["observations"][0]["image_roles"] = {f"P{index}": "target" for index in range(21)}
        self.assertEqual(normalize_response(job, response), (response, []))

    def test_balanced_closing_quotes_and_whitespace_stay_with_complete_sentence(self):
        text = "“" + "质感" * 180 + "。”\n" + "（" + "耐磨" * 180 + "。）"
        job, response = self.long_fixture(text)
        normalized, _ = normalize_response(job, response)
        self.assertEqual([part["quote"] for part in normalized["observations"]],
                         ["“" + "质感" * 180 + "。”\n", "（" + "耐磨" * 180 + "。）"])
        validate_response(job, normalized)

    def test_wrong_trend_stance_stays_rejected_and_nonextract_is_unchanged(self):
        job, response = self.long_fixture()
        record = job["payload"]["records"][0]
        record.update(kind="trend", fields={"summary_zh": response["observations"][0]["quote"]})
        self.assertEqual(normalize_response(job, response), (response, []))
        response["observations"][0]["stance"] = "example"
        normalized, _ = normalize_response(job, response)
        validate_response(job, normalized)
        self.assertEqual(len(normalized["observations"]), 2)
        job["stage"] = "theme"
        self.assertEqual(normalize_response(job, response), (response, []))


if __name__ == "__main__":
    unittest.main()
