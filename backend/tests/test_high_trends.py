"""微型资料走通网页 API、真实 DeepAgents 图与假模型；不访问模型服务。"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agents.design_trend_synthesizer import create_trend_agent, run_trend_step
from app.main import app
from app.schemas.high_trends import HighTrendRequest, HighTrendResumeRequest
from app.services.high_trends.tasks import HighTrendManager, read

MODEL = "gpt-5.6-sol-20260820"


class TextFixtureModel(FakeMessagesListChatModel):
    """仅补齐 Agent 的工具绑定接口，响应仍来自本地固定消息。"""
    def bind_tools(self, tools, **kwargs):
        if tools:
            raise AssertionError("模型不应收到文件或委派工具")
        return self


class HighTrendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.request = HighTrendRequest(start_date="2026-07-01", end_date="2026-09-09", model_id=MODEL)
        image = self.root / "data/userreseach_data/images/P1.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"fixture-image")
        self.write("data/trend_data/trends.json", {"trends": [
            {"id": 1, "title_zh": "柔和触感", "summary_zh": "低反光表面和柔和触感。", "release_time": "2026-09-01", "images": []},
            {"id": 2, "title_zh": "旧趋势", "summary_zh": "旧内容", "release_time": "2026-01-01", "images": []}]})
        self.write("data/userreseach_data/users.json", {"users": [
            {"id": 1, "profile": {"profession": "设计师"},
             "image_preferences": [{"ref_pic_code": "P1", "image_id": 1, "local_path": "images/P1.png"}],
             "aesthetic_research": [{"id": 11, "question": "喜欢哪种表面？", "ai_analysis": "P1 的柔和哑光表面很好。"}],
             "demand_research": []},
            {"id": 2, "profile": {}, "aesthetic_research": [
                {"id": 21, "question": "表面？", "ai_analysis": "喜欢哑光。"},
                {"id": 22, "ai_analysis": "未提及"}, {"id": 23, "ai_analysis": ""}], "demand_research": []}]})
        self.manager = HighTrendManager(self.root)

    def write(self, path, data):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))

    def model(self, text=None):
        return TextFixtureModel(responses=[AIMessage(
            content=text or "# 设计趋势\n## 柔和哑光\n可以探索低反光和柔和触感。[T00001 U000001 U000002]",
            usage_metadata={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125})])

    def test_api_full_flow_with_real_graph_fake_model_and_images(self):
        self.request.prompt = "重点关注材质与触感，写出具体设计启发。"
        with patch("app.api.high_trends.high_trend_manager", self.manager), patch(
            "app.agents.design_trend_synthesizer.create_chat_model", return_value=self.model()
        ) as factory:
            client = TestClient(app)
            preview = client.post("/api/v1/high-trends/preview", json=self.request.model_dump(mode="json"))
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["counts"]["selected_trends"], 1)
            self.assertEqual(preview.json()["counts"]["user_records"], 2)
            self.assertFalse(self.manager.output.exists())
            response = client.post("/api/v1/high-trends/tasks", json=self.request.model_dump(mode="json"))
            self.assertEqual(response.status_code, 202, response.text)
            task_id = response.json()["id"]
            result = client.get(f"/api/v1/high-trends/tasks/{task_id}")
            task = result.json()
            self.assertEqual(task["status"], "completed", task)
            self.assertEqual(task["request"]["prompt"], self.request.prompt)
            trace = read(self.manager.output/task_id/"requests/synthesize-001.agent.json")
            self.assertIn(self.request.prompt, trace["messages"][1]["content"])
            self.assertLessEqual(sum(len(m["content"]) for m in trace["messages"]), 48000)
            self.assertEqual(task["result"]["execution"]["user_prompt"], self.request.prompt)
            card = task["result"]["trends"][0]
            self.assertEqual(card["mention_statistics"]["unique_mentioned_users"], 2)
            self.assertIn("哑光", card["source_records"][1]["excerpt"])
            self.assertEqual(client.get(card["image_refs"][0]["url"]).status_code, 200)
            self.assertEqual(client.get(f"/api/v1/high-trends/tasks/{task_id}/download?format=markdown").status_code, 200)
            self.assertEqual(task["performance"]["actual_model_calls"], 1)
            self.assertEqual(task["performance"]["input_tokens_known"], 100)
            self.assertIn("publishing", [x["stage"] for x in task["events"]])
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
            self.assertNotIn("max_tokens", factory.call_args.kwargs)
            self.assertNotIn("max_tokens", trace["model_profile"]["parameters"])
            self.assertIsNone(preview.json()["plan"]["planned_output_token_cap"])
            restarted = HighTrendManager(self.root)
            self.assertEqual(restarted.get(task_id)["status"], "completed")

    def test_range_validation_empty_range_and_unknown_model(self):
        with patch("app.api.high_trends.high_trend_manager", self.manager), patch(
            "app.services.high_trends.tasks.run_trend_step"
        ) as model:
            client = TestClient(app)
            data = self.request.model_dump(mode="json")
            self.assertEqual(client.post("/api/v1/high-trends/preview", json={**data, "end_date": "2025-01-01"}).status_code, 422)
            self.assertEqual(client.post("/api/v1/high-trends/preview", json={**data, "model_id": "unknown"}).status_code, 400)
            response = client.post("/api/v1/high-trends/tasks", json={**data, "start_date": "2030-01-01", "end_date": "2030-01-02"})
            task = self.manager.get(response.json()["id"])
            self.assertEqual(task["status"], "empty")
            model.assert_not_called()

    def test_active_guard_and_restart_marks_interrupted(self):
        task = self.manager.create(self.request)
        with self.assertRaisesRegex(RuntimeError, "正在运行"):
            self.manager.create(self.request)
        restarted = HighTrendManager(self.root)
        self.assertEqual(restarted.get(task["id"])["stage"], "interrupted")

    def test_failure_stops_calls_and_missing_usage_is_unknown(self):
        task = self.manager.create(self.request)
        with patch("app.services.high_trends.tasks.run_trend_step", side_effect=RuntimeError("fixture offline")) as model:
            self.manager.run(task["id"])
        result = self.manager.get(task["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["performance"]["missing_usage_calls"], 1)
        model.assert_called_once()

    def test_unknown_refs_truncation_and_image_path_escape(self):
        task = self.manager.create(self.request)
        with patch("app.services.high_trends.tasks.run_trend_step", return_value={
            "text": "## 哑光\n可以探索触感。[T00001 U000001 U999999]", "seconds": 0.01,
            "input_tokens": None, "output_tokens": None, "truncated": True,
        }):
            self.manager.run(task["id"])
        result = self.manager.get(task["id"])
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["result"]["warnings"])
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")
        link = self.root / "data/userreseach_data/images/escape.png"
        link.symlink_to(outside)
        self.assertIsNone(self.manager._safe_image(str(link)))
        self.assertIsNone(self.manager._safe_image(str(outside)))
        with self.assertRaises(FileNotFoundError):
            self.manager.image(task["id"], -1)

    def test_tiny_multi_pack_flow_and_preflight_budget(self):
        self.request.prompt = "着重说明表面的触感。"
        from app.services.high_trends.skill import prepare as real_prepare
        trend_path = self.root / "data/trend_data/trends.json"
        trends = read(trend_path)
        for row in trends["trends"]:
            row.update(release_time="2026-09-01", summary_zh="柔和触感，兼顾表面耐用。" * 65)
        self.write("data/trend_data/trends.json", trends)

        def tiny_budget(*args, **kwargs):
            kwargs["overhead"] = 46000
            return real_prepare(*args, **kwargs)

        def fake_step(model, job, skill_text):
            self.assertEqual(job["user_prompt"], self.request.prompt)
            self.assertNotIn("max_tokens", job["model_profile"]["parameters"])
            refs = list(job["aliases"]) if job["aliases"] else job["source_ids"]
            return {"text": "## 柔和表面\n可以探索触感和耐用之间的平衡。["+" ".join(refs)+"]",
                    "seconds": .01, "input_tokens": 10, "output_tokens": 5, "truncated": False,
                    "telemetry": {"llm_request_count": 1}}

        with patch("app.services.high_trends.tasks.prepare", side_effect=tiny_budget):
            with self.assertRaisesRegex(ValueError, "超过max-calls"):
                self.manager.create(self.request.model_copy(update={"max_calls": 1}))
            self.assertFalse(self.manager.output.exists())
            task = self.manager.create(self.request)
        self.assertGreater(task["total_jobs"], 1)
        invoked = []
        def fail_second(model, job, skill_text):
            invoked.append(job["job_id"])
            if len(invoked) == 2:
                raise RuntimeError("stream_read_error token=secret-fixture")
            return fake_step(model, job, skill_text)

        with patch("app.services.high_trends.tasks.run_trend_step", side_effect=fail_second):
            self.manager.run(task["id"])
        failed = self.manager.get(task["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_detail"]["code"], "stream_read_error")
        self.assertNotIn("secret-fixture", json.dumps(failed))
        first = self.manager.output/task["id"]/"accepted/digest-001.json"
        first_bytes = first.read_bytes()
        with patch("app.api.high_trends.high_trend_manager", self.manager), patch(
            "app.services.high_trends.tasks.run_trend_step", side_effect=fake_step
        ) as model:
            client = TestClient(app)
            endpoint = f"/api/v1/high-trends/tasks/{task['id']}/resume"
            self.assertEqual(client.post(endpoint, json={"max_calls": 2}).status_code, 400)
            model.assert_not_called()
            self.assertEqual(client.post(endpoint, json={"max_calls": 24}).status_code, 202)
            self.assertEqual(client.post(endpoint, json={"max_calls": 24}).status_code, 409)
            self.assertEqual(model.call_count, task["total_jobs"]-1)
        result = self.manager.get(task["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(first_bytes, first.read_bytes())
        self.assertEqual(result["performance"]["stage_attempts"], task["total_jobs"]+1)
        self.assertEqual(len(result["error_history"]), 1)
        folder = self.manager.output/task["id"]
        self.assertTrue((folder/"requests/digest-002.attempt-2.agent.json").exists())
        final = read(self.manager.output/task["id"]/"requests/synthesize-001.json")
        self.assertIn('"notes"', final["messages"][1]["content"])
        self.assertNotIn("P1 的柔和哑光表面很好", final["messages"][1]["content"])

    def test_user_prompt_budget_and_length_validation(self):
        before = self.manager.preview(self.request)
        self.request.prompt = "关注色彩与情绪体验。"
        after = self.manager.preview(self.request)
        self.assertLess(after["settings"]["batch_chars"], before["settings"]["batch_chars"])
        with patch("app.api.high_trends.high_trend_manager", self.manager):
            response = TestClient(app).post("/api/v1/high-trends/preview", json={
                **self.request.model_dump(mode="json"), "prompt": "字" * 4001})
        self.assertEqual(response.status_code, 422)

    def test_user_scope_filters_before_model_and_freezes_selection(self):
        self.request.prompt = "只选择前一位用户，关注触感。"
        with patch("app.api.high_trends.high_trend_manager", self.manager), patch(
            "app.agents.design_trend_synthesizer.create_chat_model", return_value=self.model(
                "## 柔和表面\n低反光和触感的结合。[T00001 U000001]"
            )
        ) as model:
            client = TestClient(app)
            data = self.request.model_dump(mode="json")
            preview = client.post("/api/v1/high-trends/preview", json=data).json()
            self.assertEqual(preview["scope"]["user_limit"], 1)
            self.assertEqual(preview["scope"]["origin"], "prompt")
            self.assertEqual(preview["counts"]["selected_users"], 1)
            model.assert_not_called()
            response = client.post("/api/v1/high-trends/tasks", json=data)
            self.assertEqual(response.status_code, 202, response.text)
            task = self.manager.get(response.json()["id"])
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["scope"], preview["scope"])
            self.assertEqual(task["selection"], preview["selection"])
            self.assertEqual(task["counts"], preview["counts"])
            folder = self.manager.output/task["id"]
            sources = read(folder/"sources.json")
            self.assertFalse(any(str(row.get("user_id")) == "2" for row in sources.values()))
            trace = read(folder/"requests/synthesize-001.agent.json")
            self.assertNotIn("喜欢哑光。", json.dumps(trace, ensure_ascii=False))
            self.assertEqual(read(folder/"manifest.json")["selection"]["user_limit"], 1)
            model.assert_called_once()

    def test_scope_options_conflicts_and_source_order(self):
        from app.services.high_trends.scope import resolve_user_scope
        for text in ("只选择前 20 个用户", "前二十位用户", "仅用前20名用户"):
            with self.subTest(text=text):
                self.assertEqual(resolve_user_scope(self.request.model_copy(update={"prompt": text}))["user_limit"], 20)
        explicit = self.request.model_copy(update={"user_scope": "first", "user_limit": 1})
        self.assertEqual(self.manager.preview(explicit)["counts"]["selected_users"], 1)
        self.assertEqual(resolve_user_scope(self.request)["origin"], "default")
        self.assertIsNone(resolve_user_scope(self.request.model_copy(update={"prompt": "使用全部用户"}))["user_limit"])
        for changes in ({"prompt": "前0个用户"}, {"prompt": "不要选前20个用户"},
                        {"prompt": "前1位用户和前2位用户"},
                        {"prompt": "前2位用户", "user_scope": "first", "user_limit": 1},
                        {"prompt": "前2位用户", "user_scope": "all"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.manager.preview(self.request.model_copy(update=changes))
        with patch("app.api.high_trends.high_trend_manager", self.manager), patch(
            "app.services.high_trends.tasks.run_trend_step"
        ) as model:
            client = TestClient(app)
            for endpoint in ("preview", "tasks"):
                response = client.post(f"/api/v1/high-trends/{endpoint}", json={
                    **self.request.model_dump(mode="json"), "user_scope": "all", "prompt": "前1位用户"})
                self.assertEqual(response.status_code, 400)
            for changes in ({"user_scope": "first"}, {"user_scope": "first", "user_limit": 0},
                            {"user_scope": "first", "user_limit": 1.5}):
                self.assertEqual(client.post("/api/v1/high-trends/preview", json={
                    **self.request.model_dump(mode="json"), **changes}).status_code, 422)
            model.assert_not_called()
        self.assertFalse(self.manager.output.exists())
        # 前一位没有有效回答时不能偷偷补第二位；超过总数则返回实际数量。
        users = read(self.root/"data/userreseach_data/users.json")
        users["users"][0]["aesthetic_research"] = [{"id": 11, "ai_analysis": "未提及"}]
        self.write("data/userreseach_data/users.json", users)
        counts = self.manager.preview(explicit)["counts"]
        self.assertEqual(counts["selected_users"], 1)
        self.assertEqual(counts["users_with_text"], 0)
        counts = self.manager.preview(explicit.model_copy(update={"user_limit": 20}))["counts"]
        self.assertEqual(counts["selected_users"], 2)
        self.assertEqual(counts["users_with_text"], 1)

    def test_error_detail_redacts_unknown_error_and_resume_active_guard(self):
        from app.services.high_trends.errors import error_detail
        detail = error_detail(ValueError("api_key=secret-fixture https://private-gateway"))
        self.assertNotIn("secret-fixture", json.dumps(detail))
        self.assertNotIn("private-gateway", json.dumps(detail))
        task = self.manager.create(self.request)
        with self.assertRaisesRegex(RuntimeError, "正在运行"):
            self.manager.resume(task["id"], HighTrendResumeRequest())
        restarted = HighTrendManager(self.root)
        queued = restarted.resume(task["id"], HighTrendResumeRequest())
        self.assertEqual(queued["status"], "queued")


if __name__ == "__main__":
    unittest.main()
