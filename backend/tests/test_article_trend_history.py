"""以两簇合成历史档验证展示投影；不运行模型或改写真实历史结果。"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from openpyxl import Workbook

from app.api import article_trends as api
from app.services.article_trends.catalog import ArticleCatalog
from app.services.article_trends.history import HISTORY_ID, HISTORY_PATH, HistoricalTrendResults


@pytest.fixture
def history(tmp_path):
    directory = tmp_path / HISTORY_PATH
    directory.mkdir(parents=True)
    points = [{"point_id": f"P{i}", "evidence_id": f"T:{i}:summary_zh", "quote": f"准确引文{i}", "reason": "原归并理由"} for i in range(1, 11)]
    # 同文第二个点及一个未选入本簇的旧父簇成员，都不能挤占代表文章位置。
    duplicate = {**points[0], "point_id": "P11"}
    excluded = {"point_id": "EXCLUDED", "evidence_id": "T:2:summary_zh", "quote": "不属本簇"}
    cluster = {"cluster_id": "Z", "title": "原第一名", "definition": "共同关系", "design_question": "如何表达",
               "boundaries": {"excludes": ["排除泛词"]}, "source_group_count": 7, "source_article_count": 10,
               "point_ids": [point["point_id"] for point in points] + ["P11"],
               "lineage": [{"members": [excluded, points[0], duplicate, *points[1:]]}]}
    files = {
        "summary.json": {"articles": 10, "main_trends": 2, "max_trends": 100, "review_status": "pending_human_review", "min_source_groups": 3},
        "execution.json": {"compiled_at": "2026-10-01T05:18:00+00:00", "version": "3.0.0", "selection_analysis": {"model_id": "gpt-6-astra"}},
        "trend-clusters.json": {"schema_version": "legacy", "clusters": [cluster, {**cluster, "cluster_id": "A", "title": "原第二名"}],
                                "review_status": "pending_human_review", "visual_analysis_performed": False},
        "trend-catalogue.json": {"articles": [{"source_id": f"T:{i}", "original_id": str(i), "title": f"文章{i}", "source_group_id": f"G{i}"} for i in range(1, 11)]},
        "evidence-pool.json": {"points": [{**points[0], "feature": "弱线索", "deferred_reason": "支撑不足"}]},
        "coverage.json": [{"source_id": f"T:{i}", "status": "clustered" if i < 10 else "deferred"} for i in range(1, 11)],
    }
    for name, content in files.items():
        (directory / name).write_text(json.dumps(content, ensure_ascii=False))
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["id", "title_zh", "summary_zh"])
    for i in range(1, 11):
        sheet.append([str(i), f"文章{i}", f"摘要{i}"])
    excel = tmp_path / "ref/趋势信息0930.xlsx"
    excel.parent.mkdir(parents=True)
    workbook.save(excel)
    workbook.close()
    catalog = ArticleCatalog(tmp_path)
    catalog.image_index.parent.mkdir(parents=True)
    catalog.image_index.write_text('{"trends": []}')
    return HistoricalTrendResults(tmp_path, catalog=catalog)


def test_history_metadata_and_projection_preserve_legacy_semantics(history):
    metadata = history.list()[0]
    assert "result" not in metadata
    assert metadata["kind"] == "historical" and metadata["calls"] is None
    assert metadata["created_at"] == "2026-10-01T05:18:00+00:00"
    assert metadata["skill_version"] == "legacy-consensus-3.0.0"
    result = history.get(HISTORY_ID)["result"]
    assert [trend["theme_id"] for trend in result["trends"]] == ["Z", "A"]
    assert [trend["priority_rank"] for trend in result["trends"]] == [1, 2]
    trend = result["trends"][0]
    assert trend["source_group_count"] == 7 and trend["article_count"] == 10
    assert trend["images"] == []
    assert "primary_article_count" not in trend and "eligible" not in trend
    assert trend["members_displayed"] == 8 and trend["evidence_point_count"] == 11 and trend["evidence_truncated"]
    assert [member["article_id"] for member in trend["members"]] == [str(i) for i in range(1, 9)]
    assert trend["members"][0]["anchor"] == "准确引文1"
    assert trend["members"][0]["reason"] == "原归并理由"
    assert trend["members"][0]["source_group_id"] == "G1"
    assert "status" not in trend["members"][0]
    assert result["evidence_pool"][0]["title"] == "弱线索"
    assert result["evidence_pool"][0]["article_id"] == "1"
    assert result["coverage"]["legacy_status_counts"] == {"clustered": 9, "deferred": 1}


def test_read_only_cache_and_missing_history(history, tmp_path):
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in history.directory.iterdir()}
    history.list()
    first = history.get(HISTORY_ID)
    second = history.get(HISTORY_ID)
    assert first == second
    assert history.download_path(HISTORY_ID).name == "trend-clusters.json"
    assert before == {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in history.directory.iterdir()}
    assert HistoricalTrendResults(tmp_path / "absent").list() == []
    for invalid in ("unknown", "../astra_consensus_20261001", "/etc/passwd"):
        with pytest.raises(FileNotFoundError):
            history.get(invalid)
        with pytest.raises(FileNotFoundError):
            history.download_path(invalid)


def test_history_routes_download_original_and_never_run_model(history, monkeypatch):
    monkeypatch.setattr(api, "historical_results", history)
    def forbidden(*args, **kwargs):
        raise AssertionError("历史展示不能调用当前聚类任务")
    monkeypatch.setattr(api.cluster_manager, "run", forbidden)
    monkeypatch.setattr(api.cluster_manager, "create", forbidden)
    application = FastAPI()
    application.include_router(api.router, prefix="/api/v1")
    client = TestClient(application)
    base = "/api/v1/article-trends/history"
    assert client.get(base).json()[0]["id"] == HISTORY_ID
    assert client.get(f"{base}/{HISTORY_ID}").json()["result"]["review_status"] == "pending_human_review"
    download = client.get(f"{base}/{HISTORY_ID}/download")
    assert download.status_code == 200
    assert download.content == history.download_path(HISTORY_ID).read_bytes()
    assert download.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"{base}/unknown").status_code == 404
    assert client.get(f"{base}/unknown/download").status_code == 404
    assert client.post(f"{base}/{HISTORY_ID}/resume", json={"max_calls": 10}).status_code == 404


def test_cache_refreshes_if_registered_source_changes(history):
    assert history.get(HISTORY_ID)["result"]["trends"][0]["title"] == "原第一名"
    path = history.directory / "trend-clusters.json"
    data = json.loads(path.read_text())
    data["clusters"][0]["title"] = "外部维护后的标题"
    path.write_text(json.dumps(data))
    assert history.get(HISTORY_ID)["result"]["trends"][0]["title"] == "外部维护后的标题"


def test_images_use_complete_members_safe_local_files_and_distinct_sources(history):
    catalog = history.catalog
    catalog.images_root.mkdir(parents=True)

    def image(name, url, **extra):
        (catalog.images_root / name).write_bytes(b"already-downloaded")
        return {"image_id": name, "url": url, "status": "downloaded", "local_path": f"../images/{name}", **extra}

    outside = catalog.root / "outside.png"
    outside.write_bytes(b"must-not-be-served")
    index = {"trends": [
        {"id": "1", "images": [{"image_id": "unsafe", "status": "downloaded", "local_path": "../../../outside.png"}]},
        {"id": "2", "images": [{"image_id": "missing", "status": "downloaded", "local_path": "../images/missing.png"}]},
        {"id": "3", "images": [image("3a.png", "https://img.example/shared"), image("3b.png", "https://img.example/3b")]},
        {"id": "4", "images": [image("4.png", "https://img.example/shared")]},
        # 两篇有图文章位于文字证据截断之后，仍须在趋势图库出现。
        {"id": "9", "images": [image("9.png", "https://img.example/9", sha256="same-file")]},
        {"id": "10", "images": [image("10a.png", "https://img.example/other-url", sha256="same-file"),
                                  image("10b.png", "https://img.example/10b")]},
    ]}
    catalog.image_index.write_text(json.dumps(index))
    trend = history.get(HISTORY_ID)["result"]["trends"][0]
    assert [entry["article_id"] for entry in trend["images"]] == ["3", "9", "10", "3"]
    assert [entry["image_id"] for entry in trend["images"]] == ["3a.png", "9.png", "10b.png", "3b.png"]
    assert trend["images"][1] == {
        "article_id": "9", "article_title": "文章9", "image_id": "9.png",
        "url": "/api/v1/article-trends/articles/9/images/0",
    }
    assert "9" not in {member["article_id"] for member in trend["members"]}
    assert catalog.article("1")["images"] == []
    assert catalog.article("2")["images"] == []


def test_image_projection_refreshes_index_and_local_availability(history):
    assert history.get(HISTORY_ID)["result"]["trends"][0]["images"] == []
    catalog = history.catalog
    catalog.images_root.mkdir(parents=True)
    path = catalog.images_root / "late.png"
    path.write_bytes(b"already-downloaded")
    catalog.image_index.write_text(json.dumps({"trends": [{"id": "10", "images": [{
        "image_id": "late", "url": "https://img.example/late", "status": "downloaded",
        "local_path": "../images/late.png",
    }]}]}))
    assert history.get(HISTORY_ID)["result"]["trends"][0]["images"][0]["article_id"] == "10"
    # 不改索引，模拟下载文件被移走或恢复，已有文字缓存也应立即反映实际可用性。
    path.unlink()
    assert history.get(HISTORY_ID)["result"]["trends"][0]["images"] == []
    path.write_bytes(b"restored")
    assert history.get(HISTORY_ID)["result"]["trends"][0]["images"][0]["image_id"] == "late"
