"""用小型冻结产物验证原生结果投影，不调用模型、不写真实审核记录。"""

import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from app.services.high_trends import native_result
from app.services.high_trends.native_result import NativeHighTrendResult, NativeResultError, RUN_RELATIVE_PATH


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def seal(value: dict) -> dict:
    return {**value, "digest": native_result._digest(value)}


@pytest.fixture
def frozen_run(tmp_path):
    run = tmp_path / RUN_RELATIVE_PATH
    images = tmp_path / "data/trend_data/images"
    images.mkdir(parents=True)
    source_images = []
    for index in range(14):
        path = images / f"{index}.png"
        Image.new("RGB", (32, 16), (index, 70, 110)).save(path)
        source_images.append({"image_id": f"A_{index}", "local_path": str(path.relative_to(tmp_path)),
                              "sha256": native_result._sha(path), "width": 32, "height": 16, "url": f"https://example.test/{index}.png"})
    source_images.extend([
        {"image_id": "missing", "local_path": "data/trend_data/images/missing.png"},
        {"image_id": "outside", "local_path": str(tmp_path / "outside.png")},
    ])
    Image.new("RGB", (10, 10), "blue").save(tmp_path / "outside.png")
    directions = []
    for index in range(2):
        directions.append({
            "direction_id": f"H01-{index + 1:02d}", "title": f"方向{index + 1}", "design_question": "如何控制主次？",
            "relation_basis": "direct_support" if index == 0 else "exploratory_hypothesis",
            "shared_design_principle": "控制主次", "extension_explanation": "保持对象边界", "hypotheses": ["待验证假设"],
            "conditions_and_limits": [{"basis_kind": "source_quote", "reference_id": "U1", "text": "太素不喜欢", "implication": "不能过简"}],
            "unresolved_questions": ["何时过简？"], "suggested_branches": ["ID", "CMF"],
            "research_citations": [{"unit_id": "U1", "text": "太素不喜欢", "role": "boundary", "reason": "已有分析边界"}],
            "research_original_evidence": [{"unit_id": "U1", "person_id": "P1", "text": "原始分析全文：太素不喜欢", "source_kind": "reference",
                                             "source_channel": "reference", "source_attitude": "dislike", "source_scope": {"object": "P48手机", "conditions": ["特定对象"]}}],
            "trend_citations": [{"evidence_id": "T:A:summary", "text": "文章释义", "text_kind": "source_paraphrase", "reason": "趋势说明"}],
            "trend_original_evidence": [{"evidence_id": "T:A:summary", "source_id": "T:A", "text": "完整释义", "text_kind": "source_paraphrase"}],
            "negative_scope_audit": [{"unit_id": "U1", "state": "applicable"}, {"unit_id": "U2", "state": "unresolved"}],
            "direct_support_person_ids": [], "people_by_evidence_role": {"boundary": ["P1"]},
        })
    candidates = seal({"directions": directions, "prepared_digest": "prepared"})
    accepted = seal({"workflow_candidates": candidates, "semantic_truth_verified": False})
    confirmation = {"candidate_digest": candidates["digest"], "actor_kind": "user_delegated_ai", "confirmed_at": "2026-10-06T15:00:00Z"}
    selection = seal({"candidate_digest": candidates["digest"], "selection": [{"direction_id": "H01-01", "branches": ["ID"]}], "confirmation": confirmation})
    write_json(run / "h01-run/candidate-directions.json", candidates)
    write_json(run / "h01-run/accepted.json", accepted)
    write_json(run / "h01-run/selection.json", selection)
    write_json(run / "execution-receipt.json", {"semantic_analyst_model_id": "gpt-6.1-sol", "exact_model_version": None,
                                                 "run_started_at": "2026-10-06T14:00:00Z", "completed_at": "2026-10-06T14:30:00Z", "token_usage": None})
    members = [{"direction_id": "H01-01"}, {"direction_id": "H01-02"}]
    write_json(run / "related-trend-articles.json", {
        "accepted_sha256": native_result._sha(run / "h01-run/accepted.json"), "scope_note": "仅同簇关联，未视觉验证",
        "articles": [
            {"source_id": "T:A", "title": "直接文章", "metadata": {"detail_url": "https://example.test/a"}, "direction_membership": members, "images": source_images[:2]},
            {"source_id": "T:B", "title": "关联文章", "metadata": {"detail_url": "https://example.test/b"}, "direction_membership": members, "images": source_images[2:]},
        ],
    })
    decisions = [{"direction_id": row["direction_id"], "reason": "选向理由", "branch_rationale": "分支依据"} for row in directions]
    write_json(run / "direction-selection/decision-log.json", {
        "acceptedFileRef": {"sha256": native_result._sha(run / "h01-run/accepted.json")},
        "candidateFileRef": {"sha256": native_result._sha(run / "h01-run/candidate-directions.json")},
        "selection_ref": {"sha256": native_result._sha(run / "h01-run/selection.json")}, "decisions": decisions,
    })
    (run / "report.md").write_text("# 原始报告\n", encoding="utf-8")
    return NativeHighTrendResult(tmp_path)


def test_native_cards_preserve_selection_evidence_and_complete_associations(frozen_run):
    task = frozen_run.get()
    assert task["kind"] == "native_h01"
    assert task["direction_count"] == 2 and task["selected_count"] == task["exploratory_count"] == 1
    assert task["provenance"]["selection_actor"] == "user_delegated_ai"
    assert task["provenance"]["exact_model_version"] is None and task["provenance"]["token_usage"] is None
    assert "result" not in frozen_run.metadata()
    first, second = task["result"]["trends"]
    detail = first["native_detail"]
    assert detail["selected"] and not second["native_detail"]["selected"]
    assert detail["selected_branches"] == ["ID"] and detail["suggested_branches"] == ["ID", "CMF"]
    assert detail["research_citations"][0]["role"] == "boundary"
    assert detail["research_citations"][0]["source_kind"] == "reference"
    assert detail["research_citations"][0]["object_scope"] == {"object": "P48手机", "conditions": ["特定对象"]}
    assert detail["trend_citations"][0]["text_kind"] == "source_paraphrase"
    assert detail["conditions"] == [{"basis_kind": "source_quote", "reference_id": "U1", "text": "太素不喜欢", "implication": "不能过简"}]
    assert detail["unresolved_questions"] == ["何时过简？"]
    assert detail["negative_counts"] == {"applicable": 1, "unresolved": 1, "not_applicable": 0}
    assert detail["total_image_count"] == 16 and len(detail["preview_images"]) == 12
    assert detail["missing_image_count"] == 2
    assert detail["source_article_count"] == 2 and detail["direct_article_count"] == 1
    assert first["mention_statistics"]["unique_mentioned_users"] == 0
    assert frozen_run.images("H01-01", 1, 12)["total"] == 16
    tail = frozen_run.images("H01-01", 2, 12)
    assert len(tail["items"]) == 4
    assert frozen_run.images("H01-01", 1, 100, "cited")["total"] == 2
    assert frozen_run.images("H01-01", 1, 100, "associated")["total"] == 14
    first_image = detail["preview_images"][0]
    assert first_image["association_type"] == "cited"
    assert first_image["direction_ids"] == ["H01-01", "H01-02"]
    assert first_image["article_title"] == "直接文章"
    assert first_image["url"].endswith("?thumbnail=true")
    assert "?" not in first_image["original_url"]


def test_image_identity_thumbnail_cache_and_denied_paths(frozen_run, monkeypatch):
    page = frozen_run.images("H01-01", 1, 100)
    key = page["items"][0]["native_image_key"]
    real_sha = native_result._sha
    hashes = []

    def count_sha(path):
        hashes.append(path)
        return real_sha(path)

    monkeypatch.setattr(native_result, "_sha", count_sha)
    original = frozen_run.image(key)
    before = original.read_bytes()
    thumb = frozen_run.image(key, True)
    thumb_stat = thumb.stat().st_mtime_ns
    assert frozen_run.image(key, True) == thumb
    assert thumb.stat().st_mtime_ns == thumb_stat
    assert hashes == [original]
    assert original.read_bytes() == before
    with Image.open(thumb) as preview:
        assert preview.width <= 640 and preview.height <= 640
    for item in page["items"][-2:]:
        assert not item["file_exists"] and item["url"] is None
        with pytest.raises(NativeResultError, match="不存在或路径"):
            frozen_run.image(item["native_image_key"])
    original.write_bytes(before + b"changed")
    with pytest.raises(NativeResultError, match="SHA"):
        frozen_run.image(key)


@pytest.mark.parametrize("field", ["accepted_sha256", "candidate_digest"])
def test_rejects_mismatched_frozen_bindings(frozen_run, field):
    path = frozen_run.run / ("related-trend-articles.json" if field == "accepted_sha256" else "h01-run/selection.json")
    data = json.loads(path.read_text())
    data[field] = "0" * 64
    if field == "candidate_digest":
        data = seal({key: value for key, value in data.items() if key != "digest"})
    write_json(path, data)
    with pytest.raises(NativeResultError, match="不匹配"):
        frozen_run.get()


def test_downloads_original_files_and_missing_inputs_fail_closed(frozen_run):
    assert frozen_run.download("json") == frozen_run.run / "h01-run/accepted.json"
    assert frozen_run.download("sources") == frozen_run.run / "related-trend-articles.json"
    assert frozen_run.download("selection") == frozen_run.run / "h01-run/selection.json"
    assert frozen_run.download("markdown").read_text() == "# 原始报告\n"
    with pytest.raises(NativeResultError):
        frozen_run.images("other")
    with pytest.raises(NativeResultError):
        frozen_run.images("H01-01", 0)
    with pytest.raises(NativeResultError):
        frozen_run.images("H01-01", scope="unsafe")
    (frozen_run.run / "h01-run/selection.json").unlink()
    with pytest.raises(NativeResultError, match="不存在"):
        frozen_run.get()
