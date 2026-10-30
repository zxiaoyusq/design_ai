"""工程 SDK 传输的真实 DeepAgents 图验证；全程使用离线模型。"""

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agents import design_dna_preparation as adapter
from backend.tests.test_dna_preparation_web import RecordingModel


class FailureModel(RecordingModel):
    def _generate(self, messages, **kwargs):
        self.received.append(messages)
        raise ValueError("invalid header: Authorization Bearer private-test-key")


class PreparationAgentTests(TestCase):
    def _run(self, root, model):
        image = root / "original.png"
        image.write_bytes(b"original-image-bytes")
        images = [{"path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                   "candidate_id": "one", "role": "original_image"}]
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
        with patch.object(adapter, "create_chat_model", return_value=model) as create:
            try:
                answer = adapter.execute_structured(root / "call", system="冻结规则", payload={"image_id": "one"},
                    images=images, schema=schema, model_id="gemini-3.8-flash")
                self.assertEqual(answer, {"ok": True})
            finally:
                create.assert_called_once_with("gemini-3.8-flash", streaming=True, timeout=600, max_retries=0, temperature=0)

    def test_missing_model_metadata_and_usage_stay_unknown(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            model = RecordingModel(responses=[AIMessage(content='{"ok":true}')])
            self._run(root, model)
            receipt = json.loads((root / "call/receipt.json").read_bytes())
            self.assertEqual(len(model.received), 1)
            self.assertIsNone(receipt["actual_model"])
            self.assertIsNone(receipt["requested_reasoning_effort"])
            self.assertFalse(receipt["usage"]["usage_complete"])
            sent = model.received[0][-1].content
            self.assertEqual(base64.b64decode(sent[1]["base64"]), b"original-image-bytes")
            self.assertIn("OUTPUT JSON SCHEMA", sent[0]["text"])

    def test_failure_is_not_retried_and_unknown_usage_is_not_complete(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            model = FailureModel(responses=[AIMessage(content="unused")])
            with self.assertRaisesRegex(RuntimeError, "头部明细已隐藏"):
                self._run(root, model)
            receipt_text = (root / "call/receipt.json").read_text()
            receipt = json.loads(receipt_text)
            self.assertNotIn("private-test-key", receipt_text)
            self.assertEqual(len(model.received), 1)
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["usage"]["llm_request_count"], 1)
            self.assertFalse(receipt["usage"]["usage_complete"])

    def test_forbidden_tool_is_archived_without_another_model_request(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            model = RecordingModel(responses=[AIMessage(content="", tool_calls=[{"name": "read_file", "id": "x", "args": {}}])])
            with self.assertRaisesRegex(RuntimeError, "禁止调用工具"):
                self._run(root, model)
            receipt = json.loads((root / "call/receipt.json").read_bytes())
            self.assertEqual(len(model.received), 1)
            self.assertEqual(receipt["status"], "failed")
            response = json.loads((root / "call/response.json").read_bytes())
            self.assertEqual(response[0]["tool_calls"][0]["name"], "read_file")

    def test_response_headers_are_redacted_and_reported_model_preserved(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            model = RecordingModel(responses=[AIMessage(content='{"ok":true}', response_metadata={
                "model_name": "actual-provider-model", "http_headers": {"authorization": "Bearer private-test-key"}})])
            self._run(root, model)
            for name in ("response.json", "receipt.json"):
                self.assertNotIn("private-test-key", (root / "call" / name).read_text())
            receipt = json.loads((root / "call/receipt.json").read_bytes())
            self.assertEqual(receipt["actual_model"], "actual-provider-model")
