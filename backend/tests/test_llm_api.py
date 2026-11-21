"""模型列表 API 测试。"""

import unittest

from tests.auth_helpers import authenticated_client


class LLMApiTestCase(unittest.TestCase):
    def test_available_models_endpoint(self) -> None:
        response = authenticated_client().get("/api/v1/llm/models")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["models"]), 8)
        self.assertEqual(payload["models"][0]["id"], "claude-opus-5-20260820")
        self.assertNotIn("llm_key", response.text.lower())
        self.assertNotIn("llm_url", response.text.lower())

    def test_arbitrary_cloudflare_quick_tunnel_origin_is_not_trusted(self) -> None:
        response = authenticated_client().options(
            "/api/v1/llm/models",
            headers={
                "Origin": "https://design-ai-example.trycloudflare.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_fixed_public_domain_http_origin_is_allowed(self) -> None:
        response = authenticated_client().options(
            "/api/v1/llm/models",
            headers={
                "Origin": "http://gamedevcenter.ahagamecenter.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://gamedevcenter.ahagamecenter.com",
        )


if __name__ == "__main__":
    unittest.main()
