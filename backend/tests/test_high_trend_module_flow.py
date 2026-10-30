"""验证选择上游结果到网页交付的完整链路；模型仅使用本地固定回答。"""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.high_trends import HighTrendRequest
from app.services.high_trends.tasks import HighTrendManager, read
from tests.test_high_trend_upstream import upstream, UID, TID, write


def request(**changes):
    return HighTrendRequest(input_mode="module_outputs", research_output_ids=[UID],
                            trend_result_id="task:" + TID, model_id="gpt-6-sol", **changes)


def local_answer(model, job, skill):
    trend = next(sid for sid in job["source_ids"] if sid.startswith("T"))
    return {"text": f"## 异质表面的克制层次\n依据类型：anchored_extension\n共同原则：用表面差异组织层次。\n"
            f"适用边界：不喜欢强反光，原话只适用于本次受访者。\n反向与未决：跨对象仍需确认。\n"
            f"可探索纹理与低反光表面的组合。[{trend} U000001]",
            "seconds": .01, "input_tokens": 50, "output_tokens": 30, "truncated": False}


def test_preview_digest_rejects_changes_and_requires_explicit_preview(upstream):
    manager = HighTrendManager(upstream)
    original = request()
    preview = manager.preview(original)
    assert preview["scope"]["origin"] == "module_outputs"
    assert len(preview["input_digest"]) == 64
    assert not manager.output.exists()
    with pytest.raises(ValueError, match="先预估"):
        manager.create(original)
    with pytest.raises(ValueError, match="已变化"):
        manager.create(original.model_copy(update={"prompt": "新的设计要求", "input_digest": preview["input_digest"]}))
    path = upstream / "data/result/user_research_intake" / UID[7:] / "user.json"
    changed = read(path)
    changed["records"][0]["answer"] = "我改变了看法。"
    write(path, changed)
    with pytest.raises(ValueError, match="已变化"):
        manager.create(original.model_copy(update={"input_digest": preview["input_digest"]}))
    assert not manager.output.exists()


def test_module_api_freezes_sources_serves_images_and_exports_handoff(upstream):
    manager = HighTrendManager(upstream)
    with patch("app.api.high_trends.high_trend_manager", manager), patch(
        "app.services.high_trends.tasks.run_trend_step", side_effect=local_answer
    ) as runner:
        client = TestClient(app)
        listing = client.get("/api/v1/high-trends/inputs")
        assert listing.status_code == 200
        assert listing.json()["trend_outputs"][0]["selectable"]
        body = request().model_dump(mode="json")
        preview = client.post("/api/v1/high-trends/preview", json=body)
        assert preview.status_code == 200, preview.text
        created = client.post("/api/v1/high-trends/tasks", json={**body, "input_digest": preview.json()["input_digest"]})
        assert created.status_code == 202, created.text
        task_id = created.json()["id"]
        task = client.get(f"/api/v1/high-trends/tasks/{task_id}").json()
        assert task["status"] == "completed", task.get("error")
        assert runner.call_count == 1
        card = task["result"]["trends"][0]
        assert card["relation_basis"] == "anchored_extension"
        assert card["evidence_review_status"] == "not_reviewed"
        assert card["mention_statistics"]["unique_mentioned_users"] == 1
        assert "跨对象" in card["unresolved_questions"]
        assert card["associated_source_records"]
        assert card["associated_image_refs"]
        assert card["image_refs"][0]["url"]
        assert client.get(card["image_refs"][0]["url"]).content == b"yes"
        assert client.get(card["associated_image_refs"][0]["url"]).content == b"trend"
        folder = manager.output / task_id
        manifest = read(folder / "manifest.json")
        for identity in manifest["inputs"].values():
            path = Path(identity["path"])
            assert path.is_relative_to(folder)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
        assert "input_snapshots" not in manifest  # 大型上游原档另存，不重复塞入消息或清单。
        for format in ("json", "markdown", "images_markdown", "handoff", "sources"):
            downloaded = client.get(f"/api/v1/high-trends/tasks/{task_id}/download", params={"format": format})
            assert downloaded.status_code == 200, downloaded.text[:100]
        assert task["upstream_selection"]["trend_output"]["id"] == "task:" + TID
        original_file = upstream / "data/result/user_research_intake" / UID[7:] / "user.json"
        original_file.unlink()
        assert manager.get(task_id)["result"]["trends"][0]["conditions_and_limits"] == card["conditions_and_limits"]


def test_module_request_cannot_mix_raw_scope_or_unconfirmed_outputs(upstream):
    with pytest.raises(ValueError, match="前 N"):
        request(user_scope="first", user_limit=1)
    path = upstream / "data/result/user_research_intake" / UID[7:] / "user.json"
    value = read(path); value["status"] = "needs_review"; write(path, value)
    manager = HighTrendManager(upstream)
    with pytest.raises(ValueError, match="未确认"):
        manager.preview(request())
    outside = upstream / "outside.png"; outside.write_bytes(b"not allowed")
    assert manager._safe_image(str(outside)) is None
