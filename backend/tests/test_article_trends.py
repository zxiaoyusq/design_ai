"""七篇 synthetic_fixture + 假模型验证任务，不请求供应商，不回放全量资料。"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from app.api import article_trends as api
from app.schemas.article_trends import ArticleFilters, ClusterCreateRequest, ClusterRequest
from app.services.article_trends.catalog import ArticleCatalog
from app.services.article_trends import tasks


@pytest.fixture
def library(tmp_path):
    (tmp_path / "ref").mkdir()
    book = Workbook()
    sheet = book.active
    sheet.title = "导出结果"
    sheet.append(["id", "title_zh", "summary_zh", "release_time", "detail_url", "source_url", "primary_category", "local_vl_info"])
    for index in range(1, 8):
        # 文章 4 是文章 1 的同文 URL 转载；5、6形成另一个弱主题；7不能入簇。
        sheet.append([str(index), f"合成文章{index}", "圆润轮廓" if index < 5 else "冷色透明" if index < 7 else "公司公布财报",
                      f"2026-09-0{index}", f"https://example.org/{1 if index == 4 else index}",
                      "https://example.org/", "synthetic_fixture", "绝不能进入模型的DNA"])
    book.save(tmp_path / "ref/趋势信息0930.xlsx")
    index_dir = tmp_path / "data/trend_data/trend_info_0930"
    index_dir.mkdir(parents=True)
    image = tmp_path / "data/trend_data/images/1/a.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"synthetic fixture image")
    (index_dir / "trends.json").write_text(json.dumps({"trends": [
        {"id": "1", "images": [{"image_id": "i1", "status": "downloaded", "local_path": "../images/1/a.png"}]},
        {"id": "2", "images": [{"status": "downloaded", "local_path": "../../../ref/趋势信息0930.xlsx"}]},
    ]}))
    return ArticleCatalog(tmp_path)


class FixtureRunner:
    def __init__(self):
        self.requests = []
        self.invalid_review = False

    def __call__(self, model, system, body):
        self.requests.append((system, body))
        data = json.loads(body)
        if system.endswith(tasks.DISCOVER):
            assignments, present = [], set()
            for row in data:
                tid = "round" if "圆润轮廓" in row["text"] else "cool" if "冷色透明" in row["text"] else None
                anchor = "圆润轮廓" if tid == "round" else "冷色透明" if tid == "cool" else ""
                assignments.append({"article_id": row["article_id"], "theme_id": tid, "anchor": anchor, "reason": "synthetic_fixture"})
                if tid:
                    present.add(tid)
            value = {"themes": [{"theme_id": tid, "title": tid, "definition": tid, "boundary": "只按明确审美", "design_question": "怎样实现"} for tid in sorted(present)],
                     "assignments": assignments, "secondary_assignments": [], "analysis_context_ids": ["forged"]}
        elif system.endswith(tasks.ALIGN):
            value = {"matches": [{"source_theme_id": row["theme_id"], "target_theme_id": next(
                (t["theme_id"] for t in data["catalogue"] if t["definition"] == row["definition"]), None),
                "reason": "synthetic_fixture相同定义"} for row in data["incoming"]]}
        else:
            assert system.endswith(tasks.REVIEW)
            value = {"reviews": [{k: row[k] for k in ("article_id", "theme_id", "role", "binding_hash")} |
                     {"status": "supported", "anchor": row["assignment"]["anchor"], "reason": "synthetic_fixture",
                      "review_context_id": "forged"} for row in data]}
            if self.invalid_review:
                value["reviews"][0]["anchor"] = "不存在的引文"
        return {"text": json.dumps(value, ensure_ascii=False), "telemetry": {"llm_request_count": 1, "input_tokens": 10, "output_tokens": 20, "requests_with_usage": 1}}


def request(**kwargs):
    return ClusterRequest(model_id="gpt-6-sol", **kwargs)


def create(manager, req=None):
    req = req or request()
    preview = manager.preview(req)
    return manager.create(ClusterCreateRequest(**req.model_dump(), selection_digest=preview["selection_digest"], confirm=True))


def test_catalog_filters_selection_and_safe_images(library):
    assert library.facets("3")["total"] == 7
    page = library.listing(ArticleFilters(q="圆润"), page=2, page_size=2)
    assert page["total"] == 4
    assert [a["article_id"] for a in page["items"]] == ["2", "1"]
    assert library.image("1", 0).name == "a.png"
    with pytest.raises(FileNotFoundError):
        library.image("2", 0)
    chosen = library.selected(request(filters=ArticleFilters(q="财报"), article_ids=["1", "3"]))
    assert {a["article_id"] for a in chosen} == {"1", "3"}
    with pytest.raises(ValueError):
        library.selected(request(article_ids=["missing"]))
    assert "local_vl_info" not in json.dumps(library.semantic_records(chosen))


def test_preview_confirmation_digest_no_model(library):
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    req = request()
    preview = manager.preview(req)
    assert preview["article_count"] == 7 and preview["source_group_count"] == 6
    assert not runner.requests and not manager.output.exists()
    with pytest.raises(ValueError, match="确认"):
        manager.create(ClusterCreateRequest(**req.model_dump(), selection_digest=preview["selection_digest"]))
    with pytest.raises(ValueError, match="重新预估"):
        manager.create(ClusterCreateRequest(**request(limit=2).model_dump(), selection_digest=preview["selection_digest"], confirm=True))


def test_date_range_applies_to_manual_scope_before_latest_limit(library):
    filters = ArticleFilters(q="财报", date_from="2026-09-02", date_to="2026-09-03")
    selected = library.selected(request(filters=filters, article_ids=["1", "2", "3", "7"]))
    assert [row["article_id"] for row in selected] == ["3", "2"]
    latest = library.selected(request(filters=filters, article_ids=["1", "2", "3", "7"], limit=1))
    assert [row["article_id"] for row in latest] == ["3"]
    library.records()[0]["published_at"] = None
    assert not library.selected(request(filters=filters, article_ids=["7"]))
    assert len(library.selected(request(article_ids=["7"]))) == 1


def test_date_scope_preview_and_freeze_without_model(library):
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    req = request(filters=ArticleFilters(date_from="2026-09-02", date_to="2026-09-03"), article_ids=["1", "2", "3"])
    preview = manager.preview(req)
    assert preview["article_count"] == 2 and not runner.requests
    req.filters.date_to = req.filters.date_from
    with pytest.raises(ValueError, match="重新预估"):
        manager.create(ClusterCreateRequest(**req.model_dump(), selection_digest=preview["selection_digest"], confirm=True))


def test_pipeline_ranking_evidence_and_fresh_contexts(library):
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager)
    manager.run(task["id"])
    done = manager.get(task["id"])
    assert done["status"] == "completed", done["error"]
    assert done["calls"] == 2
    result = done["result"]
    assert len(result["trends"]) == 1 and len(result["evidence_pool"]) == 1
    trend = result["trends"][0]
    assert (trend["source_group_count"], trend["article_count"], trend["priority_rank"]) == (3, 4, 1)
    assert len(result["coverage"]["unassigned"]) == 1
    contexts = result["proposal"]["analysis_context_ids"]
    assert "forged" not in contexts
    assert all(r["review_context_id"] not in contexts for r in trend["reviews"])
    assert result["execution"]["visual_analysis_performed"] is False
    assert done["usage"]["requests"] == 2
    for _, body in runner.requests:
        assert "https://" not in body and "local_path" not in body and "DNA" not in body
    manager.run(task["id"])
    assert len(runner.requests) == 2


def test_budget_resume_reuses_discovery_and_restart_requires_action(library, monkeypatch):
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager, request(max_calls=1))
    manager.run(task["id"])
    failed = manager.get(task["id"])
    assert failed["status"] == "interrupted" and failed["calls"] == 1
    assert "上限" in failed["error"]
    restarted = tasks.ClusterManager(library.root, library, runner)
    restarted.resume(task["id"], 3)
    third = tasks.ClusterManager(library.root, library, runner)
    assert third.get(task["id"])["status"] == "queued"  # 同一存活进程不能被误当重启。
    monkeypatch.setattr(tasks, "owner_alive", lambda task: False)
    assert third.get(task["id"])["status"] == "interrupted"
    assert len(runner.requests) == 1
    third.resume(task["id"], 3)
    third.run(task["id"])
    done = third.get(task["id"])
    assert done["status"] == "completed", done["error"]
    assert done["calls"] == 2 and len(runner.requests) == 2


def test_invalid_review_not_cached_and_frozen_input_guard(library):
    runner = FixtureRunner()
    runner.invalid_review = True
    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager)
    manager.run(task["id"])
    failed = manager.get(task["id"])
    assert failed["status"] == "failed" and "引文" in failed["error"]
    assert not (manager.output / task["id"] / "steps/review-0000/accepted.json").exists()
    runner.invalid_review = False
    manager.resume(task["id"], 5)
    manager.run(task["id"])
    assert manager.get(task["id"])["status"] == "completed"
    assert len(runner.requests) == 3
    second = create(manager)
    tasks.write(manager.output / second["id"] / "records.json", [])
    manager.run(second["id"])
    assert manager.get(second["id"])["status"] == "failed"
    assert len(runner.requests) == 3


def test_multi_batch_alignment_freezes_complete_contexts(library, monkeypatch):
    monkeypatch.setattr(tasks, "PAYLOAD_CHARS", 1600)
    # 增长非语义编号，确保分包但单条复核仍在预算内。
    library.records()
    for row in library._records:
        row["summary"] += "。" + row["article_id"] * 160
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager)
    manager.run(task["id"])
    done = manager.get(task["id"])
    assert done["status"] == "completed", done["error"]
    assert any(system.endswith(tasks.ALIGN) for system, _ in runner.requests)
    assert len(done["result"]["trends"]) == 1
    assert len(done["result"]["proposal"]["analysis_context_ids"]) > 2


def test_api_browse_preview_and_explicit_start(library, monkeypatch):
    runner = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, runner)
    monkeypatch.setattr(api, "cluster_manager", manager)
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    assert client.get("/article-trends/catalog").json()["total"] == 7
    response = client.get("/article-trends/articles", params={"page": 2, "page_size": 2, "q": "圆润"})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["article_id"] == "2"
    assert client.get("/article-trends/articles/1/images/0").status_code == 200
    assert client.get("/article-trends/articles/2/images/0").status_code == 404
    assert client.get("/article-trends/articles", params={"date_from": "2026-10-01", "date_to": "2026-01-01"}).status_code == 422
    preview = client.post("/article-trends/preview", json=request().model_dump(mode="json"))
    assert preview.status_code == 200 and not runner.requests
    payload = request().model_dump(mode="json") | {"selection_digest": preview.json()["selection_digest"], "confirm": True}
    response = client.post("/article-trends/tasks", json=payload)
    assert response.status_code == 202, response.text
    tid = response.json()["id"]
    assert client.get(f"/article-trends/tasks/{tid}").json()["status"] == "completed"
    assert client.get(f"/article-trends/tasks/{tid}/download").status_code == 200


@pytest.mark.parametrize("bad_reason", [{"unexpected": "object"}, "   "])
def test_bad_review_never_enters_accepted_cache(library, bad_reason):
    fixture = FixtureRunner()

    def runner(model, system, body):
        response = fixture(model, system, body)
        if system.endswith(tasks.REVIEW):
            value = json.loads(response["text"])
            value["reviews"][0]["reason"] = bad_reason
            response["text"] = json.dumps(value)
        return response

    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager)
    manager.run(task["id"])
    assert manager.get(task["id"])["status"] == "failed"
    assert not (manager.output / task["id"] / "steps/review-0000/accepted.json").exists()
    manager.runner = fixture
    manager.resume(task["id"], 5)
    manager.run(task["id"])
    assert manager.get(task["id"])["status"] == "completed"


def test_recovery_recounts_durable_receipts_and_preserves_live_owner(library):
    fixture = FixtureRunner()
    manager = tasks.ClusterManager(library.root, library, fixture)
    task = create(manager, request(max_calls=1))
    other_worker = tasks.ClusterManager(library.root, library, fixture)
    assert other_worker.get(task["id"])["status"] == "queued"
    with pytest.raises(RuntimeError):
        create(other_worker, request(limit=2))
    manager.run(task["id"])
    path = manager.output / task["id"] / "task.json"
    stale = tasks.read(path)
    stale["usage"] = {key: 0 for key in stale["usage"]}
    stale["completed_steps"] = 0
    tasks.write(path, stale)
    manager.resume(task["id"], 3)
    manager.run(task["id"])
    done = manager.get(task["id"])
    assert done["usage"]["requests"] == 2 and done["completed_steps"] == 2
    assert done["usage"]["input_tokens"] == 20


def test_model_json_duplicate_fields_rejected(library):
    def runner(*args):
        return {"text": '{"themes": [], "themes": []}', "telemetry": {}}
    manager = tasks.ClusterManager(library.root, library, runner)
    task = create(manager)
    manager.run(task["id"])
    assert manager.get(task["id"])["status"] == "failed"
    assert not (manager.output / task["id"] / "steps/discover-0000/accepted.json").exists()
