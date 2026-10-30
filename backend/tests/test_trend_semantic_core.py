"""synthetic_fixture：只验证纯文本契约，不代表真实语义准确率。"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".agents/skills/prism-trend-semantic-clustering/scripts/semantic.py"
SPEC = importlib.util.spec_from_file_location("trend_semantic_core_test", SCRIPT)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def theme(theme_id):
    return {"theme_id": theme_id, "title": "测试主题" + theme_id,
            "definition": "多文共同表达柔和形态", "boundary": "不包含营销判断", "design_question": "如何表达柔和感"}


def fixture():
    records = core.normalize_records([
        {"article_id": name, "title": name, "summary": "柔和轮廓与细腻表面",
         "source_group_id": "duplicate" if name in "ab" else name,
         "image_urls": ["https://private.invalid/image"], "local_vl_info": "禁止进入请求",
         "tags": ["禁止标签"], "dna": {"style": "禁止 DNA"}}
        for name in "abcdefg"
    ])
    proposal = {"analysis_context_id": "actual-analysis", "themes": [theme(t) for t in ("T1", "T2", "T3")],
                "assignments": [
                    {"article_id": name, "theme_id": "T1" if name in "abc" else "T2" if name in "def" else None,
                     "anchor": "柔和轮廓", "reason": "合成测试依据"}
                    for name in "abcdefg"],
                "secondary_assignments": [
                    {"article_id": aid, "theme_id": tid, "anchor": "细腻表面", "reason": "合成次级依据"}
                    for aid, tid in (("c", "T2"), ("d", "T1"), ("a", "T3"))]}
    return records, proposal, make_reviews(records, proposal)


def make_reviews(records, proposal):
    return [{"article_id": p["article_id"], "theme_id": p["theme_id"], "role": p["role"],
             "binding_hash": p["binding_hash"], "status": "supported",
             "anchor": p["assignment"]["anchor"], "reason": "合成复核支持",
             "review_context_id": "actual-fresh-review"}
            for batch in core.review_packets(records, proposal) for p in batch]


def test_multisource_priority_secondary_and_weak_pool():
    records, proposal, reviews = fixture()
    result = core.compile_result(records, proposal, reviews)
    assert [t["theme_id"] for t in result["themes"]] == ["T2", "T1"]
    assert result["themes"][0]["source_group_count"] == 4
    assert result["themes"][1]["source_group_count"] == 3
    assert result["themes"][1]["article_count"] == 4
    assert result["themes"][1]["primary_source_group_count"] == 2
    assert result["candidate_pool"][0]["theme_id"] == "T3"
    assert result["coverage"]["unassigned"][0]["article_id"] == "g"
    assert result["coverage"]["reviewed_relation_count"] == 9


def test_only_text_enters_model_packets():
    records, proposal, _ = fixture()
    records[0]["image_urls"] = ["INJECTED_IMAGE"]
    packets = core.pack_records(records) + core.review_packets(records, proposal)
    serialized = json.dumps(packets)
    assert all(word not in serialized for word in ("image_urls", "local_vl_info", "tags", "dna", "INJECTED_IMAGE"))
    assert "source_url" not in serialized


def test_source_dedup_is_transitive_and_preserves_story_identity():
    records = core.normalize_records([
        {"id": "a", "title": "A", "summary": "甲", "source_url": "https://x.test/report#story-1"},
        {"id": "b", "title": "B", "summary": "乙", "source_url": "https://x.test/report#story-2"},
        {"id": "c", "title": "C", "summary": "丙", "source_url": "https://x.test/report?utm_source=x#story-1"},
        {"id": "d", "title": "C", "summary": "丙", "source_url": "https://another.test/copy"},
    ])
    groups = {row["article_id"]: row["source_group_id"] for row in records}
    assert groups["a"] == groups["c"] == groups["d"]
    assert groups["a"] != groups["b"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "same_context", "unknown", "bad_anchor", "stale_hash", "wrong_role"])
def test_invalid_reviews_rejected(mutation):
    records, proposal, reviews = fixture()
    if mutation == "missing":
        reviews.pop()
    elif mutation == "duplicate":
        reviews.append(copy.deepcopy(reviews[0]))
    elif mutation == "same_context":
        reviews[0]["review_context_id"] = proposal["analysis_context_id"]
    elif mutation == "unknown":
        reviews[0]["article_id"] = "unknown"
    elif mutation == "bad_anchor":
        reviews[0]["anchor"] = "不存在的原话"
    elif mutation == "stale_hash":
        reviews[0]["binding_hash"] = "old"
    else:
        reviews[0]["role"] = "secondary"
    with pytest.raises(ValueError):
        core.compile_result(records, proposal, reviews)


@pytest.mark.parametrize("mutation", ["definition", "text", "reason"])
def test_changed_evidence_invalidates_only_bound_reviews(mutation):
    records, proposal, reviews = fixture()
    if mutation == "definition":
        proposal["themes"][0]["definition"] += "变更"
    elif mutation == "text":
        records[0]["text"] += "变更"
    else:
        proposal["assignments"][0]["reason"] += "变更"
    with pytest.raises(ValueError, match="绑定失效"):
        core.compile_result(records, proposal, reviews)


@pytest.mark.parametrize("mutation", ["missing_primary", "duplicate_primary", "duplicate_secondary", "copied_primary", "invented_anchor"])
def test_invalid_proposals_rejected(mutation):
    records, proposal, _ = fixture()
    if mutation == "missing_primary":
        proposal["assignments"].pop()
    elif mutation == "duplicate_primary":
        proposal["assignments"].append(copy.deepcopy(proposal["assignments"][0]))
    elif mutation == "duplicate_secondary":
        proposal["secondary_assignments"].append(copy.deepcopy(proposal["secondary_assignments"][0]))
    elif mutation == "copied_primary":
        proposal["secondary_assignments"].append(copy.deepcopy(proposal["assignments"][0]))
    else:
        proposal["assignments"][0]["anchor"] = "不存在的原话"
    with pytest.raises(ValueError):
        core.validate_proposal(records, proposal)


def test_uncertain_and_unsupported_remain_visible_not_counted():
    records, proposal, reviews = fixture()
    reviews[0]["status"] = "unsupported"
    reviews[-2]["status"] = "uncertain"
    result = core.compile_result(records, proposal, reviews)
    assert len(result["coverage"]["uncertain"]) == 1
    assert len(result["coverage"]["unsupported"]) == 1
    assert [t["theme_id"] for t in result["themes"]] == ["T2"]
    assert {t["theme_id"] for t in result["candidate_pool"]} == {"T1", "T3"}


def test_packet_budget_and_no_truncation():
    records, _, _ = fixture()
    packets = core.pack_records(records, max_chars=600)
    assert len(packets) > 1
    assert sum(map(len, packets)) == len(records)
    assert all(len(core._json(packet)) <= 600 for packet in packets)
    with pytest.raises(ValueError, match="不能静默截断"):
        core.pack_records(records, max_chars=128)


def test_no_hundred_theme_limit_without_model_replay():
    # 仅 202 个极短结构记录，证明不存在 100 截断；不执行大模型。
    rows, assignments = [], []
    for number in range(101):
        tid = f"T{number:03d}"
        for member in range(2):
            aid = f"{tid}-{member}"
            rows.append({"id": aid, "title": aid, "summary": "柔和"})
            assignments.append({"article_id": aid, "theme_id": tid, "anchor": "柔和", "reason": "结构边界验证"})
    records = core.normalize_records(rows)
    proposal = {"analysis_context_id": "synthetic-context", "themes": [theme(f"T{i:03d}") for i in range(101)],
                "assignments": assignments, "secondary_assignments": []}
    result = core.compile_result(records, proposal, make_reviews(records, proposal), min_source_groups=2)
    assert len(result["themes"]) == 101
    assert result["themes"][-1]["priority_rank"] == 101
    with pytest.raises(ValueError, match="至少 2"):
        core.compile_result(records, proposal, [], min_source_groups=1)


@pytest.mark.parametrize("rows", [[{"id": "a"}, {"id": "a"}], [{"id": None}], [{}]])
def test_duplicate_or_missing_article_id_rejected(rows):
    with pytest.raises(ValueError, match="ID 缺失或重复"):
        core.normalize_records(rows)
