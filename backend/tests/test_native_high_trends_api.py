"""只读原生结果路由的登记范围、分页参数与原文件交付验证。"""
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.main import app

BASE = "/api/v1/high-trends/native-results/sol61-native-v2-20261006"


def test_registered_result_and_pagination_contract():
    service = Mock()
    service.get.return_value = {"id": "sol61-native-v2-20261006", "kind": "native_h01"}
    service.images.return_value = {"items": [], "total": 0, "page": 2, "page_size": 12}
    with patch("app.api.high_trends.native_result", service):
        client = TestClient(app)
        assert client.get(BASE).json()["kind"] == "native_h01"
        assert client.get("/api/v1/high-trends/native-results/not-registered").status_code == 404
        assert service.get.call_count == 1
        response = client.get(BASE + "/directions/H01-01/images", params={"page": 2, "scope": "associated"})
        assert response.status_code == 200
        service.images.assert_called_once_with("H01-01", 2, 12, "associated")
        for params in ({"page": 0}, {"page_size": 49}, {"scope": "unknown"}):
            assert client.get(BASE + "/directions/H01-01/images", params=params).status_code == 422
        assert service.images.call_count == 1


def test_original_image_and_download_are_existing_files(tmp_path):
    image = tmp_path / "original.png"
    image.write_bytes(b"original-file-bytes")
    selection = tmp_path / "selection.json"
    selection.write_text('{"selection":[]}')
    service = Mock()
    service.image.return_value = image
    service.download.return_value = selection
    with patch("app.api.high_trends.native_result", service):
        client = TestClient(app)
        assert client.get(BASE + "/images/stable-key?thumbnail=true").content == image.read_bytes()
        service.image.assert_called_once_with("stable-key", True)
        response = client.get(BASE + "/download?format=selection")
        assert response.content == selection.read_bytes()
        assert "selection.json" in response.headers["content-disposition"]
        assert client.get(BASE + "/download?format=arbitrary-path").status_code == 422
        service.download.assert_called_once_with("selection")
