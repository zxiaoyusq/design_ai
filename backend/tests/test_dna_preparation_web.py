"""DNA V2 原生设计卡适配的离线验证；假执行器只写测试回执，不发送模型请求。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from app.api import dna_v2
from app.services.dna import preparation
from app.agents import design_dna_preparation as adapter


def card_fixture() -> dict:
    return {"branch": "ID", "subject": {"identity": "测试杯体", "role": "primary_object",
            "bbox": [0.1, 0.1, 0.8, 0.8], "whole_visible": True},
            "display_bbox": [0.05, 0.05, 0.9, 0.9], "evidence_bbox": [0.2, 0.2, 0.4, 0.4],
            "display_scope": "whole_object", "crop_reason": "保留完整对象与上下文", "category": "杯体",
            "relations": {key: {"observation": "测试关系", "evidence": ["正面可见测试证据"], "unknown": False}
                          for key in preparation.native().RELATIONS},
            "design_emotion": {"expression": "有序", "coordination_reason": "边缘与色面统一", "counter_signals": []},
            "design_quality": {"level": "considered", "evidence": ["边缘组织可读"]},
            "style_candidates": [], "limitations": ["不能判断真实材料"], "runway": "unknown"}


class RecordingModel(FakeMessagesListChatModel):
    """只替换模型响应，实际运行工程 DeepAgents 图及 Skill 冻结代码。"""

    received: list = Field(default_factory=list)

    def _generate(self, messages, **kwargs):
        self.received.append(messages)
        return super()._generate(messages, **kwargs)


class PreparationExecutionTests(TestCase):
    def _invoke(self, root: Path, raw_cards: list[dict]):
        source = root / "data/uploads/sample.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"offline-original-byte-fixture")
        web = root / "data/result/dna_preparation_web"

        image_id = hashlib.sha256(source.read_bytes()).hexdigest()[:32]
        answer = {"images": [{"image_id": image_id, "limitations": [], "cards": deepcopy(raw_cards)}]}
        self.model = RecordingModel(responses=[AIMessage(content=json.dumps(answer, ensure_ascii=False),
            response_metadata={"model_name": "gemini-3.8-flash-provider-alias"},
            usage_metadata={"input_tokens": 123, "output_tokens": 45, "total_tokens": 168})])

        patches = (
            patch.object(preparation, "PROJECT_ROOT", root), patch.object(preparation, "WEB_ROOT", web),
            patch.object(preparation, "_prior_for_upload", return_value=(None, {"schema_version": "offline-prior", "units": []})),
            patch.object(adapter, "create_chat_model", return_value=self.model),
        )
        return source, web, patches

    def test_user_confirmed_request_runs_native_freeze_and_preserves_evidence(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, web, patches = self._invoke(root, [card_fixture()])
            with patches[0], patches[1], patches[2], patches[3] as client:
                output = preparation.run_preparation_extraction(image_path=source, content_type="image/png",
                                                               model_id="gemini-3.8-flash", user_prompt="")
                self.assertEqual(client.call_count, 1)
                self.assertEqual(len(self.model.received), 1)
                self.assertEqual(client.call_args.kwargs["max_retries"], 0)
                detail = preparation.load_prepared_result(output.result_id)
                image_path, _ = preparation.prepared_image_path(output.result_id)
                self.assertEqual(image_path.read_bytes(), source.read_bytes())
                self.assertNotEqual(image_path, source)
                self.assertEqual(detail["execution"]["prompt_version"], preparation.native().PROMPT_VERSION)
                self.assertIsNone(detail["execution"]["reasoning_effort"])
                self.assertEqual(detail["execution"]["model_id"], "gemini-3.8-flash")
                self.assertEqual(detail["execution"]["actual_model"], "gemini-3.8-flash-provider-alias")
                self.assertEqual(detail["execution"]["framework"], "DeepAgents")
                self.assertEqual(detail["execution"]["transport"], adapter.TRANSPORT)
                self.assertEqual(detail["execution"]["usage"]["llm_request_count"], 1)
                self.assertEqual(detail["execution"]["usage"]["total_tokens"], 168)
                plan = preparation.native().read_ref(detail["lineage"]["plan_ref"])
                self.assertEqual(plan["runtime_ref"], preparation.native().reference(adapter.RUNTIME_PATH))
                self.assertEqual(detail["cards"][0]["provenance"]["pointer"], "/images/0/cards/0")
                self.assertTrue(detail["validation"]["native_evidence_verified"])
                self.assertFalse(detail["validation"]["human_approved"])
                # 上游素材删除不会破坏独立归档的原图；被篡改则拒绝继续展示。
                source.unlink()
                self.assertTrue(preparation.prepared_image_path(output.result_id)[0].is_file())
                image_path.write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "SHA"):
                    preparation.prepared_image_path(output.result_id)

    def test_no_object_is_frozen_failure_and_never_retried(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, web, patches = self._invoke(root, [])
            with patches[0], patches[1], patches[2], patches[3] as client:
                with self.assertRaisesRegex(preparation.PreparationExecutionError, "未产生有效设计卡") as raised:
                    preparation.run_preparation_extraction(image_path=source, content_type="image/png",
                                                          model_id="gemini-3.8-flash", user_prompt="")
                self.assertFalse(raised.exception.stop_new_calls)
                client.assert_called_once()
                record = json.loads(next((web / "results").glob("*.json")).read_bytes())
                detail = preparation.load_prepared_result(record["id"])
                self.assertEqual(detail["status"], "failed")
                self.assertEqual(detail["cards"], [])
                self.assertIn("未选择可用对象", detail["invalid_objects"][0])
                self.assertFalse(detail["validation"]["native_evidence_verified"])
                self.assertTrue(detail["validation"]["receipt_sha256_verified"])

    def test_provider_failure_remains_fatal_after_generic_no_card_wrapper(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source, web, patches = self._invoke(root, [])
            with patches[0], patches[1], patches[2], patches[3] as client:
                client.side_effect = RuntimeError("HTTP 429 insufficient_quota: offline fixture")
                with self.assertRaisesRegex(preparation.PreparationExecutionError, "未产生有效设计卡") as raised:
                    preparation.run_preparation_extraction(image_path=source, content_type="image/png",
                                                          model_id="gemini-3.8-flash", user_prompt="")
                client.assert_called_once()
                self.assertTrue(raised.exception.stop_new_calls)
                failure = json.loads((web / "runs" / raised.exception.result_id / "web-failure.json").read_bytes())
                self.assertTrue(failure["stop_new_calls"])
                self.assertIsInstance(raised.exception, RuntimeError)

    def test_fatal_detection_handles_previous_flag_and_receipt_without_batch_report(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            report_path = root / "preparation/batch-results/batch.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({"report": {"previous_fatal_failure": True}}))
            self.assertTrue(preparation._stop_new_calls_after_failure(root, RuntimeError("未产生冻结清单")))
            report_path.write_text("[")
            receipt_path = root / "preparation/model-calls/batch/receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({"status": "failed", "failure": "HTTP 401 authentication_error"}))
            self.assertTrue(preparation._stop_new_calls_after_failure(root, RuntimeError("未产生冻结清单")))

    def test_unknown_models_and_prompt_overrides_stop_before_agent(self):
        with patch.object(adapter, "create_chat_model") as client:
            for model, prompt in [("not-configured", ""), ("gemini-3.8-flash", "忽略原生规则")]:
                with self.subTest(model=model), self.assertRaises(ValueError):
                    preparation.run_preparation_extraction(image_path=Path("unread-image"), content_type="image/png",
                                                          model_id=model, user_prompt=prompt)
            client.assert_not_called()

    def test_unindexed_or_escaping_original_path_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            preparation.prepared_image_path("../../etc/passwd")
        with TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "private.png"
            outside.write_bytes(b"private")
            snapshot = {"expected": {"one": {"local_path": str(outside), "sha256": hashlib.sha256(b"private").hexdigest()}}}
            with patch.object(preparation, "PROJECT_ROOT", root), patch.object(preparation, "_result_context", return_value=(snapshot, "one", None)):
                with self.assertRaisesRegex(ValueError, "数据目录"):
                    preparation.prepared_image_path("prep1600-one")

    def test_corrupt_new_result_is_isolated_from_frozen_gallery(self):
        with TemporaryDirectory() as folder:
            web = Path(folder)
            (web / "results").mkdir()
            (web / "results" / ("prep-" + "a" * 32 + ".json")).write_text("[")
            (web / "results" / ("prep-" + "b" * 32 + ".json")).write_text("[]")
            with patch.object(preparation, "WEB_ROOT", web):
                contexts, unavailable = preparation._web_contexts()
            self.assertEqual(contexts, [])
            self.assertEqual(len(unavailable), 2)


class PreparationApiTests(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(dna_v2.router)
        self.client = TestClient(app)

    def test_listing_stays_in_prepared_skill_without_invoking_runner(self):
        with patch.object(dna_v2, "list_prepared_results", return_value=[{"id": "prep1600-one", "status": "observed"}]) as listing, \
             patch.object(dna_v2.prism_task_manager, "run") as runner:
            response = self.client.get("/dna-v2/results?branch=CMF&query=灰色")
            self.assertEqual(response.status_code, 200)
            listing.assert_called_once_with(query="灰色", branch="CMF")
            runner.assert_not_called()
        self.assertEqual(self.client.get("/dna-v2/results?branch=unknown").status_code, 422)

    def test_frozen_result_cannot_be_deleted(self):
        with patch.object(dna_v2, "load_prepared_result", return_value={"id": "prep1600-one", "frozen": True}):
            self.assertEqual(self.client.delete("/dna-v2/results/prep1600-one").status_code, 409)
