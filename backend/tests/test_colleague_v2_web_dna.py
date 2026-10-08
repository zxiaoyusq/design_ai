"""冻结提取路由和网页薄适配的离线边界；不发送模型请求。"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.services.dna import prism_r5
from app.services.visual_workflow import web_adapter
from app.services.moodboards.tasks import MoodboardManager


class FrozenR5WebTests(unittest.TestCase):
    def test_rejects_model_and_prompt_overrides(self):
        prism_r5.validate_r5_request("gpt-6-sol", "")
        for model, prompt, effort in [("gemini-3.8-flash", "", "low"), ("gpt-6-sol", "额外关注点", "low"), ("gpt-6-sol", "", "medium")]:
            with self.assertRaises(ValueError):
                prism_r5.validate_r5_request(model, prompt, effort)

    def test_pause_stops_before_any_cli_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            boundary = root / "data/result/visual_workflow/h01_all13_20261005_expanded/execution-boundary.json"
            boundary.parent.mkdir(parents=True)
            boundary.write_text('{"all_model_calls_paused":true}')
            with patch.object(prism_r5, "PROJECT_ROOT", root), patch.object(prism_r5.subprocess, "run") as cli:
                with self.assertRaisesRegex(RuntimeError, "已暂停"):
                    prism_r5.run_prism_r5_extraction(image_path=root / "missing.png", content_type="image/png", model_id="gpt-6-sol", user_prompt="")
                cli.assert_not_called()

    def test_calls_original_cli_and_preserves_partial_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "image.png"
            image.write_bytes(b"offline fixture only")
            outputs = root / "results"
            runs = outputs / "d02/r5_runs"
            portable = SimpleNamespace(read=lambda path: json.loads(path.read_text()))
            def fake_cli(argv, **options):
                run = Path(argv[argv.index("--out") + 1])
                image_id = argv[argv.index("--image-id") + 1]
                run.mkdir(parents=True)
                final = {"image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "model": "gpt-6-sol", "status": "partial", "pending_count": 1, "invalid": [], "features": [], "local_features": []}
                (run / "result.json").write_text(json.dumps(final))
                (run / "call-ledger.json").write_text('{"limit":2,"calls":[{"call_id":"primary"}]}')
                call = run / "calls" / ("P-" + image_id)
                call.mkdir(parents=True)
                (call / "receipt.json").write_text('{"schema_valid":true,"usage":null}')
                (call / "answer.json").write_text('{"raw":"fixture"}')
                return SimpleNamespace(returncode=0, stdout="fixture stdout", stderr="")
            with patch.multiple(prism_r5, PROJECT_ROOT=root, RESULTS_DIR=outputs, RESULT_DIR=outputs / "d02", RUN_DIR=runs), patch.object(prism_r5, "_portable", return_value=(portable, SimpleNamespace(VERSION="frozen"))), patch.object(prism_r5, "verify_chatgpt_auth"), patch.object(prism_r5, "save_result_image"), patch.object(prism_r5.subprocess, "run", side_effect=fake_cli) as cli:
                output = prism_r5.run_prism_r5_extraction(image_path=image, content_type="image/png", model_id="gpt-6-sol", user_prompt="")
                value = json.loads((outputs / "d02" / f"{output.result_id}.json").read_text())
                self.assertEqual(value["execution"]["native_status"], "partial")
                self.assertFalse(value["execution"]["prompt_wrapped"])
                self.assertEqual(value["execution"]["adapter"], "codex_cli_frozen_r5")
                self.assertTrue(str(cli.call_args.args[0][4]).endswith("scripts/cli.py"))
                self.assertNotIn("input", cli.call_args.kwargs)
                self.assertFalse(value["validation"]["full_216_visual_qualified"])


class NativeWebTests(unittest.TestCase):
    def test_preview_replays_actual_gate_and_keeps_synthetic_unaccepted(self):
        from backend.tests import test_colleague_v2_workflow as fixtures
        fixture = fixtures.ColleagueWorkflowTests()
        fixture.setUp()
        try:
            _, _, board_path, review_path = fixture.board_fixture()
            manifest = {"board_ref": {"path": str(board_path), "sha256": hashlib.sha256(board_path.read_bytes()).hexdigest()},
                        "review_ref": {"path": str(review_path), "sha256": hashlib.sha256(review_path.read_bytes()).hexdigest()}}
            (fixture.folder / "web-handoff.json").write_text(json.dumps(manifest))
            with patch.object(web_adapter, "VISUAL_RESULT_ROOT", fixture.folder.parent):
                result = web_adapter.preview_handoff(fixture.folder.name)
            self.assertEqual(result["directions"][0]["clusters"], [])
            self.assertEqual(result["trace"]["native_gate"]["status"], "blocked")
            self.assertEqual(result["trace"]["new_model_calls"], 0)
            self.assertEqual(len(result["assignments"]), 10)
            self.assertEqual(result["assignments"][0]["evidence"][0]["value"]["image_id"], "fixture-0")
        finally:
            fixture.tearDown()

    def test_unfinished_board_never_becomes_formal_cluster(self):
        board = {"title": "fixture", "tiles": [{"image_id": "one", "scope": "fixture"}]}
        result = web_adapter.project_board(board, {"status": "unfinished", "eligible_to_report_visual_result": False}, run_path="fixture")
        self.assertEqual(result["directions"][0]["clusters"], [])
        self.assertEqual(result["unmatched_result_ids"], ["one"])
        self.assertFalse(result["trace"]["user_acceptance_confirmed"])

    def test_run_path_cannot_escape_result_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "results"
            root.mkdir()
            with self.assertRaises(ValueError):
                web_adapter.load_handoff("..", root=root)

    def test_original_ref_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "board.json"
            file.write_text('{}')
            with self.assertRaises(ValueError):
                web_adapter._read_ref({"path": str(file), "sha256": "0" * 64})

    def test_legacy_text_generator_cannot_create_resume_or_run(self):
        # 不建生产任务目录，直接调用方法可证实在任何模型/存储动作之前停止。
        manager = object.__new__(MoodboardManager)
        for method, argument in [(manager.create, None), (manager.resume, "fixture"), (manager.run, "fixture")]:
            with self.assertRaisesRegex(RuntimeError, "旧 DNA 文本"):
                method(argument)


class V2ApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import dna_v2, moodboards
        app = FastAPI()
        app.include_router(dna_v2.router)
        app.include_router(moodboards.router)
        self.client = TestClient(app)

    def test_dna_fixed_model_pause_and_history_are_separate(self):
        from app.api import dna_v2
        body = {"image_ids": ["fixture"], "model_id": "gemini-3.8-flash", "prompt": ""}
        self.assertEqual(self.client.post("/dna-v2/extractions", json=body).status_code, 400)
        body["model_id"] = "gpt-6-sol"
        with patch.object(dna_v2, "ensure_r5_execution_allowed", side_effect=RuntimeError("已暂停")), patch.object(dna_v2.prism_task_manager, "create") as create:
            self.assertEqual(self.client.post("/dna-v2/extractions", json=body).status_code, 409)
            create.assert_not_called()
        with patch.object(dna_v2, "load_prism_result", return_value={"id": "fixture", "schema_version": "prism_d02_candidate_v1"}):
            self.assertEqual(self.client.get("/dna-v2/results/fixture").status_code, 200)

    def test_legacy_create_and_resume_return_explicit_conflict(self):
        body = {"trend_task_id": "fixture", "direction_ids": ["direction"], "result_ids": ["result"], "model_id": "fixture", "confirmed": True}
        for url, request in [("/moodboards/tasks", body), ("/moodboards/tasks/fixture/resume", {"confirmed": True})]:
            response = self.client.post(url, json=request)
            self.assertEqual(response.status_code, 409)
            self.assertIn("旧 DNA 文本", response.json()["detail"])

    def test_native_preview_rejects_client_pass_and_has_no_background_model_task(self):
        from app.api import moodboards
        with patch.object(moodboards, "preview_handoff", return_value={"trace": {"new_model_calls": 0}}) as preview:
            response = self.client.post("/moodboards/native-results/preview", json={"run_path": "fixture", "passed": True})
            self.assertEqual(response.status_code, 422)
            preview.assert_not_called()
            response = self.client.post("/moodboards/native-results/preview", json={"run_path": "fixture"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["trace"]["new_model_calls"], 0)
            preview.assert_called_once_with("fixture")

    def test_malformed_board_returns_400_without_changing_saved_bytes(self):
        mutations = {
            "missing_image_id": lambda value: value["tiles"][0].pop("image_id"),
            "duplicate_image_id": lambda value: value["tiles"][1].update(image_id=value["tiles"][0]["image_id"]),
            "tiles_not_list": lambda value: value.update(tiles={"image_id": "fixture"}),
            "tile_not_object": lambda value: value["tiles"].__setitem__(0, "fixture"),
            "view_ref_not_object": lambda value: value["tiles"][0].update(view_ref="fixture"),
        }
        self._assert_bad_handoff("board", mutations)

    def test_malformed_review_returns_400_without_changing_saved_bytes(self):
        mutations = {
            "missing_image_id": lambda value: value["slots"][0].pop("image_id"),
            "duplicate_image_id": lambda value: value["slots"][1].update(image_id=value["slots"][0]["image_id"]),
            "slots_not_list": lambda value: value.update(slots="fixture"),
            "slot_not_object": lambda value: value["slots"].__setitem__(0, None),
        }
        self._assert_bad_handoff("review", mutations)

    def _assert_bad_handoff(self, changed_file, mutations):
        from backend.tests import test_colleague_v2_workflow as fixtures
        from app.services.visual_workflow import colleague_v2
        fixture = fixtures.ColleagueWorkflowTests()
        fixture.setUp()
        try:
            board, review, board_path, review_path = fixture.board_fixture()
            for name, mutation in mutations.items():
                with self.subTest(name=name):
                    bad_board, bad_review = deepcopy(board), deepcopy(review)
                    mutation(bad_board if changed_file == "board" else bad_review)
                    board_ref = fixtures.write_ref(fixture.folder, board_path.name, bad_board)
                    review_ref = fixtures.write_ref(fixture.folder, review_path.name, bad_review)
                    fixtures.write_ref(fixture.folder, "web-handoff.json", {"board_ref": board_ref, "review_ref": review_ref})
                    originals = {path: path.read_bytes() for path in fixture.folder.iterdir() if path.is_file()}
                    with patch.object(web_adapter, "VISUAL_RESULT_ROOT", fixture.folder.parent), patch.object(colleague_v2, "evaluate_board") as gate:
                        response = self.client.post("/moodboards/native-results/preview", json={"run_path": fixture.folder.name})
                        self.assertEqual(response.status_code, 400)
                        gate.assert_not_called()
                    self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        finally:
            fixture.tearDown()
