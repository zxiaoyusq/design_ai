"""模型列表 API 测试。"""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class LLMApiTestCase(unittest.TestCase):
    def test_available_models_endpoint(self) -> None:
        response = TestClient(app).get("/api/v1/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["models"]), 6)
        self.assertEqual(payload["models"][0]["id"], "claude-opus-5-20260820")
        self.assertNotIn("llm_key", response.text.lower())
        self.assertNotIn("llm_url", response.text.lower())


if __name__ == "__main__":
    unittest.main()
