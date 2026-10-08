"""旧情绪板档案只读与历史协议校验；新原生链见 test_colleague_v2_*。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.agents.moodboard_generator import stage_prompt
from app.schemas.moodboards import MoodboardRequest
from app.services.moodboards.tasks import (
    MoodboardManager, dna_projection, read, resolve_pointer, validate_assignments,
    validate_clusters, validate_clustering,
)


class HistoricalMoodboardValidationTests(unittest.TestCase):
    """纯校验函数继续解释旧冻结 JSON，不创建新任务。"""

    def setUp(self):
        self.directions = [{"id": "D1"}, {"id": "D2"}]
        self.business = {rid: {"key_dna": [{"value": "哑光"}]} for rid in ["R1", "R2", "R3", "R4"]}

    def assignments(self):
        return {"assignments": [
            {"result_id": rid, "direction_id": did, "reason": "依据哑光表面",
             "evidence_paths": ["/key_dna/0/value"]}
            for rid, did in [("R1", "D1"), ("R2", "D1"), ("R3", "D2"), ("R4", None)]
        ]}


    def cluster(self, ids, cid="C1"):
        return {"id": cid, "name": "柔和触感" + cid,
                "description": "共同哑光表面；轮廓差异构成内部变化。", "result_ids": ids}


    def test_assignments_require_exact_partition_known_directions_and_real_evidence(self):
        images = [{"result_id": rid, "dna": dna} for rid, dna in self.business.items()]
        valid = self.assignments()
        self.assertEqual(len(validate_assignments(valid, images, self.directions)), 4)
        invalid = []
        missing = deepcopy(valid)
        missing["assignments"].pop()
        invalid.append(missing)
        duplicate = deepcopy(valid)
        duplicate["assignments"][-1] = deepcopy(duplicate["assignments"][0])
        invalid.append(duplicate)
        for field, value in [("result_id", "foreign"), ("direction_id", "foreign"),
                             ("evidence_paths", ["/key_dna/99/value"]), ("evidence_paths", [])]:
            changed = deepcopy(valid)
            changed["assignments"][0][field] = value
            invalid.append(changed)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_assignments(payload, images, self.directions)


    def test_json_pointer_escaping_arrays_and_empty_evidence(self):
        value = {"a/b": {"~key": ["有效"]}, "empty": [], "blank": "", "null": None}
        self.assertEqual(resolve_pointer(value, "/a~1b/~0key/0"), "有效")
        for pointer in ["", "a/b", "/a~2b", "/a~1b/~0key/-1", "/a~1b/~0key/00",
                        "/a~1b/~0key/1", "/empty", "/blank", "/null", "/missing"]:
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                resolve_pointer(value, pointer)


    def test_clusters_are_one_to_three_nonempty_unique_partitions(self):
        ids = ["R1", "R2", "R3", "R4"]
        for groups in [[ids], [["R1"], ["R2", "R3", "R4"]], [["R1"], ["R2"], ["R3", "R4"]]]:
            clusters = [self.cluster(group, f"C{i}") for i, group in enumerate(groups)]
            self.assertEqual(validate_clusters({"clusters": clusters}, ids), clusters)
        bad_groups = [[], [[]], [[rid] for rid in ids], [["R1", "R2", "R3"]],
                      [["R1", "R2"], ["R2", "R3", "R4"]], [["R1", "R2", "R3", "foreign"]]]
        for groups in bad_groups:
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                validate_clusters({"clusters": [self.cluster(group, f"C{i}")
                                                for i, group in enumerate(groups)]}, ids)
        for field in ["id", "name"]:
            clusters = [self.cluster(ids[:2], "C1"), self.cluster(ids[2:], "C2")]
            clusters[1][field] = clusters[0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_clusters({"clusters": clusters}, ids)


class MoodboardHistoryReadTests(unittest.TestCase):
    """使用既有旧任务文件验证网页历史接口，不经已停用的新建入口造数据。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager = MoodboardManager(self.root)
        self.task_id = "mb_" + "b" * 32
        self.trend_id = "web_" + "a" * 32
        self.request = MoodboardRequest(trend_task_id=self.trend_id, direction_ids=["D1"],
                                       result_ids=["R1", "R2", "R3", "R4"], model_id="gpt-5.6-sol", confirmed=True)
        trend_folder = self.root / "data/result/high_trend" / self.trend_id
        trend_folder.mkdir(parents=True)
        (trend_folder / "web_task.json").write_text(json.dumps({"id": self.trend_id, "status": "completed", "created_at": "2026-09-01T00:00:00Z"}))
        (trend_folder / "high_potential_trends.json").write_text(json.dumps({"trends": [{"id": "D1", "title": "历史方向", "description": "历史冻结语义"}]}))
        patcher = patch("app.api.moodboards.moodboard_manager", self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def saved_task(self, status="completed"):
        folder = self.manager.output / self.task_id
        folder.mkdir(parents=True, exist_ok=True)
        result = {"directions": [{"id": "D1", "title": "历史方向", "description": "", "clusters": [{"id": "C1", "name": "历史四图", "description": "旧 v3 成板口径", "result_ids": ["R1", "R2", "R3", "R4"]}]}],
                  "assignments": [], "images": [], "unmatched_result_ids": [],
                  "trace": {"prompt_version": "moodboard-text-dna-v3", "image_input": False}}
        task = {"id": self.task_id, "status": status, "stage": status, "message": "历史保存状态", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:01Z",
                "request": self.request.model_dump(), "completed_jobs": 2, "total_jobs": 2, "events": [],
                "prompt_version": "moodboard-text-dna-v3", "result": result if status == "completed" else None}
        (folder / "task.json").write_text(json.dumps(task, ensure_ascii=False))
        if status == "completed":
            (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False))
        return task, result

    def test_completed_history_get_list_download_preserve_saved_four_image_result(self):
        task, result = self.saved_task()
        before = {p: p.read_bytes() for p in self.manager.output.rglob("*") if p.is_file()}
        self.assertEqual(self.client.get(f"/api/v1/moodboards/tasks/{self.task_id}").json(), task)
        self.assertEqual(self.client.get(f"/api/v1/moodboards/tasks/{self.task_id}/download").json(), result)
        items = self.client.get("/api/v1/moodboards/tasks").json()
        self.assertEqual(items[0]["prompt_version"], "moodboard-text-dna-v3")
        self.assertIsNone(items[0]["result"])
        self.assertEqual(MoodboardManager(self.root).get(self.task_id), task)
        self.assertEqual(before, {p: p.read_bytes() for p in self.manager.output.rglob("*") if p.is_file()})

    def test_initializing_reader_preserves_queued_running_and_failed_history_bytes(self):
        for status in ["queued", "running", "failed"]:
            with self.subTest(status=status):
                task, _ = self.saved_task(status)
                before = {p: p.read_bytes() for p in self.manager.output.rglob("*") if p.is_file()}
                other = MoodboardManager(self.root)
                self.assertEqual(other.get(self.task_id), task)
                self.assertEqual(before, {p: p.read_bytes() for p in self.manager.output.rglob("*") if p.is_file()})
        self.assertEqual(self.client.get(f"/api/v1/moodboards/tasks/{self.task_id}/download").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/moodboards/tasks/unknown").status_code, 404)

    def test_catalog_retains_latest_identity_deduplication_and_reports_execution_stop(self):
        summaries = [{"id": rid, "created_at": f"2026-09-0{3-n}T00:00:00Z"} for n, rid in enumerate(["R1", "R2", "R3"])]
        traces = {"R1": {"input_image": {"sha256": "same"}}, "R2": {"input_image": {"sha256": "same"}}, "R3": {"input_image": {"sha256": "other"}}}
        with patch("app.services.moodboards.tasks.storage.list_results", return_value=summaries), patch("app.services.moodboards.tasks.storage._trace_data", side_effect=lambda rid: traces[rid]):
            response = self.client.get("/api/v1/moodboards/catalog")
        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual([image["id"] for image in catalog["dna_results"]], ["R1", "R3"])
        self.assertEqual(catalog["trend_tasks"][0]["id"], self.trend_id)
        self.assertFalse(catalog["execution"]["supported"])
        self.assertFalse(self.manager.output.exists())

    def test_disabled_create_resume_run_leave_archive_bytes_unchanged(self):
        self.saved_task("failed")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("app.agents.moodboard_generator.create_chat_model") as model:
            for url, body in [("/api/v1/moodboards/tasks", self.request.model_dump()),
                              (f"/api/v1/moodboards/tasks/{self.task_id}/resume", {"confirmed": True})]:
                response = self.client.post(url, json=body)
                self.assertEqual(response.status_code, 409)
                self.assertIn("旧 DNA 文本", response.json()["detail"])
            with self.assertRaises(RuntimeError):
                self.manager.run(self.task_id)
            model.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_disabled_entry_still_enforces_request_schema_before_any_new_task(self):
        data = self.request.model_dump()
        for body in [{**data, "confirmed": False}, {**data, "direction_ids": ["D1", "D1"]}, {**data, "result_ids": ["R1", "R1"]}]:
            self.assertEqual(self.client.post("/api/v1/moodboards/tasks", json=body).status_code, 422)
        self.assertEqual(self.manager.list(), [])
        self.assertFalse(self.manager.output.exists())


class HistoricalMoodboardCurationTests(unittest.TestCase):
    """仅验证已保存历史 v2/v3 数据口径；不用于新原生情绪板生成。"""

    def setUp(self):
        self.ids = [f"R{i}" for i in range(9)]
        self.cluster = {"id": "C1", "name": "温润极简", "description": "暖浅低对比，轮廓圆润克制",
                        "primary_axis": "圆润极简体量", "required_features": ["暖浅主体", "低反射主表面"],
                        "exclusions": ["硬朗机械外骨架"], "result_ids": self.ids[:6]}
        self.packet = {"clusters": [self.cluster], "excluded": [
            {"result_id": rid, "reason": "同质备选或主结构冲突"} for rid in self.ids[6:]]}

    def test_curated_subset_preserves_every_candidate_and_rejects_accounting_errors(self):
        result = validate_clustering(self.packet, self.ids, "v2")
        self.assertEqual(len(result["clusters"][0]["result_ids"]), 6)
        for mutate in [
            lambda p: p["excluded"].pop(),
            lambda p: p["excluded"].append({"result_id": "R0", "reason": "重复"}),
            lambda p: p["excluded"][0].update(result_id="unknown"),
        ]:
            data = deepcopy(self.packet)
            mutate(data)
            with self.assertRaises(ValueError):
                validate_clustering(data, self.ids, "v2")

    def test_cardinality_and_single_style_name_are_enforced(self):
        for name in ["边界描饰与局部焦点", "织印图式和色彩重组", "纹理/配色", "冷色＋暖色", "木纹、金属", "亮面及哑光"]:
            data = deepcopy(self.packet)
            data["clusters"][0]["name"] = name
            with self.assertRaises(ValueError):
                validate_clustering(data, self.ids, "v2")
        for count in [1, 5, 9]:
            data = deepcopy(self.packet)
            data["clusters"][0]["result_ids"] = self.ids[:count]
            data["excluded"] = [{"result_id": rid, "reason": "备选"} for rid in self.ids[count:]]
            with self.assertRaises(ValueError):
                validate_clustering(data, self.ids, "v2")
        empty = {"clusters": [], "excluded": [{"result_id": "R0", "reason": "不足6张"}]}
        self.assertEqual(validate_clustering(empty, ["R0"], "v2"), empty)

    def test_v3_four_images_form_a_board_without_weakening_v2_history(self):
        four = deepcopy(self.packet)
        four["clusters"][0]["result_ids"] = self.ids[:4]
        four["excluded"] = [{"result_id": rid, "reason": "相近候选未精选"} for rid in self.ids[4:]]
        self.assertEqual(len(validate_clustering(four, self.ids, "v3")["clusters"][0]["result_ids"]), 4)
        with self.assertRaises(ValueError):
            validate_clustering(four, self.ids, "v2")
        eight = deepcopy(self.packet)
        eight["clusters"][0]["result_ids"] = self.ids[:8]
        eight["excluded"] = [{"result_id": "R8", "reason": "相近候选未精选"}]
        self.assertEqual(len(validate_clustering(eight, self.ids, "v3")["clusters"][0]["result_ids"]), 8)
        for count in (3, 9):
            bad = deepcopy(self.packet)
            bad["clusters"][0]["result_ids"] = self.ids[:count]
            bad["excluded"] = [{"result_id": rid, "reason": "备选"} for rid in self.ids[count:]]
            with self.assertRaises(ValueError):
                validate_clustering(bad, self.ids, "v3")

    def test_weak_local_unknown_cannot_be_matched_and_ambiguity_must_be_explicit(self):
        image = {"result_id": "R0", "dna": {"style": "整体粉蜡柔软，局部金属亮饰"}}
        dirs = [{"id": "D1"}, {"id": "D2"}]
        assignment = {"result_id": "R0", "direction_id": "D1", "reason": "整体柔软主导，局部亮饰不支持金属主题",
                      "evidence_paths": ["/style"], "status": "matched", "dominant_style": "柔软当代",
                      "dominance": {"strength": "strong", "scope": "global", "salience": "primary"},
                      "competing_direction_ids": ["D2"]}
        def check(item):
            return validate_assignments({"assignments": [item]}, [image], dirs, "v2")
        check(assignment)
        for field, bad in [("strength", "moderate"), ("scope", "local"), ("scope", "unknown"), ("salience", "secondary")]:
            item = deepcopy(assignment)
            item["dominance"][field] = bad
            with self.assertRaises(ValueError):
                check(item)
        ambiguous = {**assignment, "status": "ambiguous", "direction_id": None, "competing_direction_ids": ["D1", "D2"]}
        check(ambiguous)
        for changed in [{"direction_id": "D1"}, {"competing_direction_ids": ["D1"]},
                        {"competing_direction_ids": ["D1", "D1"]}, {"competing_direction_ids": ["D1", "unknown"]}]:
            with self.assertRaises(ValueError):
                check({**ambiguous, **changed})

    def test_projection_retains_dominance_evidence_without_inventing_measurements(self):
        candidate = {"style_id": "Soft", "rank": 1, "match_score": 88, "main_support": ["粉蜡色覆盖主体"],
                     "main_conflicts": ["亮金仅在端帽"], "regions": ["主体"], "facet_ids": ["soft"]}
        evidence = {"value": "金色", "evidence": "只见于微小端帽", "region": "端帽"}
        projected = dna_projection({"style": {"style_candidates": [candidate]}, "key_dna": [evidence]})
        self.assertEqual(projected["style"]["style_candidates"][0], candidate)
        self.assertEqual(projected["key_dna"][0], evidence)
        self.assertNotIn("coverage_ratio", json.dumps(projected))

    def test_frozen_skill_selects_legacy_or_curated_protocol(self):
        legacy = stage_prompt("clustering", "frozen legacy skill")
        curated = stage_prompt("clustering", "moodboard-curation-v2")
        revised = stage_prompt("clustering", "moodboard-curation-v3")
        self.assertIn("1至3个非空", legacy)
        self.assertNotIn('"excluded"', legacy)
        self.assertIn('"excluded"', curated)
        self.assertIn("6至8张", curated)
        self.assertIn('"excluded"', revised)
        self.assertIn("4至8张", revised)



if __name__ == "__main__":
    unittest.main()
