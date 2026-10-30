"""将真实板审绑定到同一成员与取景，分列视觉、来源、数量和秀场结果。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from design_emotion import SELECTED_OBJECT_VERSION


VIEW_REVIEW_POLICY_VERSION = "selected-object-representative-view.v4"
RELATION_REVIEW_POLICY_VERSION = "blind-concrete-design-relation.v5"
VIEW_MEMBER_FIELDS = ("unit_id", "image_id", "sha256", "roi", "display_bbox", "evidence_bbox",
                      "primary_subject", "target_role", "display_scope", "crop_reason")


def reviewed_view_snapshot(board: dict) -> dict:
    """绑定审阅当时的原图、对象和有序取景；深拷贝避免后续改框同步改掉旧证据。"""
    return {"board_id": board["board_id"], "branch": board["branch"],
            "members": [{key: deepcopy(member.get(key)) for key in VIEW_MEMBER_FIELDS}
                        for member in board["members"]]}


def requires_relation_review(board: dict, review: dict | None = None) -> bool:
    """新候选或新盲审都须走具体关系门，历史 v3/v4 不被悄悄改写。"""
    return (board.get("requires_concrete_relation_review") is True
            or board.get("review_provenance", {}).get("review_policy_version") == RELATION_REVIEW_POLICY_VERSION
            or (review or {}).get("provenance", {}).get("review_policy_version") == RELATION_REVIEW_POLICY_VERSION)


def reviewed_view_matches(board: dict, review: dict | None) -> bool:
    """没有独立reviews文件时也要核内嵌实审范围，不凭相同unit_id迁移旧PASS。"""
    if not requires_view_review(board) and not requires_relation_review(board, review):
        return True
    provenance = review.get("provenance", {}) if review else board.get("review_provenance", {})
    return provenance.get("reviewed_view") == reviewed_view_snapshot(board)


def requires_view_review(board: dict) -> bool:
    """显式新取景契约才启用新门槛；不篡改历史整物板的旧审状态。"""
    return (requires_relation_review(board)
            or board.get("review_provenance", {}).get("review_policy_version") == VIEW_REVIEW_POLICY_VERSION
            or any(bool(member.get("display_scope"))
               or member.get("target_role") in {"peer_object", "peer_object_surface"}
               or member.get("feature_definition_version") == SELECTED_OBJECT_VERSION
               for member in board["members"]))


def view_review_policy_matches(board: dict, review: dict | None, document_policy: str | None = None) -> bool:
    require_relation = requires_relation_review(board, review)
    if not requires_view_review(board) and not require_relation:
        return True
    recorded = (review or {}).get("provenance", {}).get("review_policy_version")
    if recorded is None and review is None:
        recorded = board.get("review_provenance", {}).get("review_policy_version")
    permitted = {RELATION_REVIEW_POLICY_VERSION} if require_relation else {VIEW_REVIEW_POLICY_VERSION, RELATION_REVIEW_POLICY_VERSION}
    return recorded in permitted and document_policy in {None, recorded}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def member_visual_supported(member: dict, require_subject_review: bool = False,
                            require_view_review: bool = False, require_relation_review: bool = False) -> bool:
    """新取景需另核裁片表达与上下文忠实性；历史字段名不再要求整物展示。"""
    fields = ("scope_correct", "relation_supported", "second_signal_compatible", "keep")
    supported = all(member.get(field) is True for field in fields) and member.get("image_quality") in {"usable", "weak"}
    if require_subject_review or require_view_review:
        supported = (supported and member.get("primary_subject_supported") is True
                     and member.get("whole_subject_compatible") is True
                     and member.get("emotion_combination_supported") is True
                     and bool(str(member.get("emotion_reason") or "").strip())
                     and member.get("design_merit") in {"distinctive", "considered", "ordinary"}
                     and bool(str(member.get("design_evidence") or "").strip()))
    if require_view_review:
        supported = (supported and member.get("display_expression_supported") is True
                     and member.get("crop_context_faithful") is True
                     and bool(str(member.get("reason") or "").strip()))
    if require_relation_review:
        supported = supported and relation_evidence_supported(member.get("relation_evidence"), "visible_support")
    return supported


def nonempty_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def relation_evidence_supported(evidence: dict | None, support_field: str) -> bool:
    """只做记录和反证门：字段齐全不代表机器已证明审美判断正确。"""
    if not isinstance(evidence, dict):
        return False
    support = evidence.get(support_field)
    return (isinstance(support, list) and bool(support) and all(nonempty_text(row) for row in support)
            and evidence.get("difference_assessment") == "coordinated"
            and nonempty_text(evidence.get("strongest_difference"))
            and nonempty_text(evidence.get("coordination_reason")))


def concrete_relation_review_supported(board: dict, review: dict | None = None) -> bool:
    """核对逐项正向证据和有界反例对照；coherent 不能盖过任一冲突／未决。"""
    checked = review or board
    provenance = review.get("provenance", {}) if review else board.get("review_provenance", {})
    if (provenance.get("blind_visual_review") is not True
            or provenance.get("upstream_explanations_sent") is not False):
        return False
    relation = checked.get("shared_design_relation")
    if not isinstance(relation, dict) or not nonempty_text(relation.get("statement")):
        return False
    anchors = relation.get("visible_anchors")
    dimensions = {"form", "proportion", "color", "material_texture", "detail_language"}
    if (not isinstance(anchors, list) or not anchors
            or any(not isinstance(row, dict) or row.get("dimension") not in dimensions
                   or not nonempty_text(row.get("visible_relation")) for row in anchors)):
        return False
    current_ids = {member["unit_id"] for member in board["members"]}
    members = checked.get("members", []) if review else [member.get("current_target_review", {}) for member in board["members"]]
    if ({member.get("unit_id") for member in members} != current_ids or len(members) != len(current_ids)
            or not all(relation_evidence_supported(member.get("relation_evidence"), "visible_support") for member in members)):
        return False
    weakest = checked.get("least_consistent_unit_id")
    pairs = checked.get("pair_checks")
    if weakest not in current_ids or not isinstance(pairs, list) or not 1 <= len(pairs) <= 3:
        return False
    seen = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            return False
        left, right = pair.get("unit_id_a"), pair.get("unit_id_b")
        if left not in current_ids or right not in current_ids or left == right:
            return False
        key = tuple(sorted((left, right)))
        if key in seen or not relation_evidence_supported(pair, "shared_visible_support"):
            return False
        seen.add(key)
    return any(weakest in pair for pair in seen)


def board_emotion_evidence_recorded(review: dict) -> bool:
    """只检查组合审阅记录完整；未知维度可空，不用文字或字段数授予审美通过。"""
    evidence = review.get("emotion_combination_evidence")
    fields = ("form", "proportion", "color", "material_texture", "detail_language")
    return (bool(str(review.get("common_design_emotion") or "").strip())
            and isinstance(evidence, dict) and all(field in evidence for field in fields)
            and any(isinstance(evidence[field], str) and evidence[field].strip() for field in fields)
            and bool(str(evidence.get("overall_relation") or "").strip()))


def finalize(boards: dict, reviews: dict) -> dict:
    result = deepcopy(boards)
    review_index = {x["board_id"]: x for x in reviews["reviews"]}
    for board in result["boards"]:
        review = review_index.get(board["board_id"])
        board["designer_approved"] = False
        if review is None:
            board["status"] = "review_not_completed"
            continue
        current = {(m["unit_id"], m["image_id"]) for m in board["members"]}
        reviewed = {(m["unit_id"], m["image_id"]) for m in review["members"]}
        if current != reviewed or len(current) != len(review["members"]):
            raise ValueError(f"审阅成员未与当前板一一对应: {board['board_id']}")
        # 视觉通过还需逐成员陈述一致，不能只消费作者/模型顶层的coherent。
        require_relation_review = requires_relation_review(board, review)
        require_view_review = requires_view_review(board) or require_relation_review
        require_subject_review = require_view_review or any(m.get("display_bbox") is not None for m in board["members"])
        policy_matches = (view_review_policy_matches(board, review, reviews.get("review_policy_version"))
                          and reviewed_view_matches(board, review))
        visual_supported = review["visual_verdict"] == "coherent" and all(
            member_visual_supported(m, require_subject_review, require_view_review, require_relation_review) for m in review["members"])
        visual_supported = visual_supported and policy_matches
        if require_subject_review:
            visual_supported = visual_supported and board_emotion_evidence_recorded(review)
        if require_relation_review:
            visual_supported = visual_supported and concrete_relation_review_supported(board, review)
        source_index = {s["image_id"]: s for s in review["source_identity_checks"]}
        visual_index = {m["unit_id"]: m for m in review["members"]}
        projects, articles, originals = [], [], []
        runway_count = unknown_runway = unresolved_projects = 0
        for member in board["members"]:
            source = source_index[member["image_id"]]
            # 首个pilot旧协议只含image_id，已由当前板唯一成员回查；新协议明确绑定unit_id。
            if source.get("unit_id", member["unit_id"]) != member["unit_id"]:
                raise ValueError(f"来源判断指向另一目标: {member['unit_id']}")
            supported = source["project_state"] == "source_supported" and bool(
                source["project_name"].strip() and source["project_key"].strip() and source["reason"].strip())
            member.update(project_state="source_supported" if supported else "unknown",
                          project_key=source["project_key"] if supported else None,
                          project_name=source["project_name"] if supported else None,
                          project_identity_evidence=source["reason"], runway_state=source["runway_state"],
                          runway_evidence=source["runway_reason"], project_identity_scope="unit",
                          project_identity_binding=member["unit_id"])
            checked = visual_index[member["unit_id"]]
            current_view_supported = (policy_matches
                                      and member_visual_supported(checked, require_subject_review, require_view_review,
                                                                  require_relation_review))
            # 历史视窗问题仍留档；当前已经实审，不再把它写成“尚待第一次复核”。
            member.update(current_target_review=checked, needs_current_view_review=False,
                          target_quality_status="reviewed_usable" if current_view_supported else "reviewed_needs_revision")
            if supported:
                projects.append(source["project_key"].casefold().strip())
            else:
                unresolved_projects += 1
            runway_count += source["runway_state"] == "yes"
            unknown_runway += source["runway_state"] == "unknown"
            originals.append(member.get("sha256", member["image_id"]))
            article_set = {str(x["article_id"]) for x in member.get("source_refs", [])
                           if isinstance(x, dict) and x.get("article_id")}
            articles.append(article_set)
        count = len(board["members"])
        no_article_overlap = all(not articles[i] & articles[j] for i in range(count) for j in range(i))
        # 先前程序保留同源组判定；这里的新证据只补当前项目和秀场，不推翻旧重复检查。
        previous = board.get("mechanical_checks", {})
        quantity_ok = 6 <= count <= 10 and len(set(originals)) == count
        source_ok = (not unresolved_projects and len(set(projects)) == count and no_article_overlap
                     and previous.get("source_articles_unique", True))
        maximum_runway = count * 30 // 100
        quota_ok = runway_count + unknown_runway <= maximum_runway
        board["mechanical_checks"] = {**previous, "quantity": count, "quantity_pass": quantity_ok, "image_count": count,
                                      "source_articles_unique": no_article_overlap,
                                      "known_projects_unique": len(set(projects)) == len(projects),
                                      "independent_project_count": len(set(projects)),
                                      "project_identity_complete": unresolved_projects == 0,
                                      "runway_known_count": runway_count, "runway_unknown_count": unknown_runway,
                                      "runway_maximum": maximum_runway, "runway_conservative_pass": quota_ok}
        board.update(title=review["title"], common_relation=review["common_relation"],
                     common_design_emotion=review.get("common_design_emotion"),
                     emotion_combination_evidence=review.get("emotion_combination_evidence"),
                     visual_review_status=review["visual_verdict"],
                     validation={"visual": visual_supported, "quantity": quantity_ok,
                                 "source": source_ok, "runway": quota_ok, "designer_approved": False},
                     review_provenance=deepcopy(review.get("provenance", {})),
                     status="ready_for_designer_feedback" if all((visual_supported, quantity_ok, source_ok, quota_ok))
                     else "needs_revision" if not visual_supported or not quantity_ok else "visual_ready_source_pending")
        if require_relation_review:
            board.update(requires_concrete_relation_review=True,
                         shared_design_relation=deepcopy(review.get("shared_design_relation")),
                         pair_checks=deepcopy(review.get("pair_checks")),
                         least_consistent_unit_id=review.get("least_consistent_unit_id"),
                         concrete_relation_status="supported" if visual_supported else "needs_revision")
    result["counts"] = {"boards": len(result["boards"]),
                        "visually_supported": sum(b.get("validation", {}).get("visual", False) for b in result["boards"]),
                        "ready_for_designer_feedback": sum(b["status"] == "ready_for_designer_feedback" for b in result["boards"]),
                        "designer_approved": 0}
    return result


def reuse_unchanged_reviews(boards: dict, reviews: dict, previous_paths: list[Path]) -> dict:
    """仅复用整条候选板完全未变的实审；修订成员、ROI、特征或范围都会阻止复用。"""
    merged = deepcopy(reviews)
    current = {b["board_id"]: b for b in boards["boards"]}
    existing = {r["board_id"] for r in merged["reviews"]}
    merged["unchanged_board_review_reuse"] = []
    for path in previous_paths:
        previous = read(path)
        if previous.get("review_policy_version") != reviews.get("review_policy_version"):
            raise ValueError("独立审阅规则已改变，不能以旧设计情绪判据复用通过结论")
        if previous.get("source_articles_ref", {}).get("sha256") != reviews.get("source_articles_ref", {}).get("sha256"):
            raise ValueError("来源证据版本不同，不能复用旧来源判断")
        old_reference = previous["boards_ref"]
        old_path = Path(old_reference["path"])
        if file_ref(old_path)["sha256"] != old_reference["sha256"]:
            raise ValueError("拟复用审阅的原板输入已改变")
        old_boards = {b["board_id"]: b for b in read(old_path)["boards"]}
        for reviewed in previous["reviews"]:
            board_id = reviewed["board_id"]
            if board_id in existing or board_id not in current:
                continue
            if current[board_id] != old_boards.get(board_id):
                continue
            copy = deepcopy(reviewed)
            copy.setdefault("provenance", {})["unchanged_board_reuse_from"] = file_ref(path)
            merged["reviews"].append(copy)
            existing.add(board_id)
            merged["unchanged_board_review_reuse"].append({"board_id": board_id, "reviews_ref": file_ref(path)})
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-reviews", nargs="*", type=Path, default=[])
    parser.add_argument("--merged-reviews-out", type=Path, help="为展示另存复用后的审阅索引，原回执保持原样")
    args = parser.parse_args()
    reviews = read(args.reviews)
    if reviews.get("boards_ref", {}).get("sha256") != file_ref(args.boards)["sha256"]:
        raise ValueError("审阅并非针对当前 boards.json，不得复用旧结果")
    boards = read(args.boards)
    reviews = reuse_unchanged_reviews(boards, reviews, args.reuse_reviews)
    if args.merged_reviews_out:
        args.merged_reviews_out.parent.mkdir(parents=True, exist_ok=True)
        with args.merged_reviews_out.open("x", encoding="utf-8") as stream:
            json.dump(reviews, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    result = finalize(boards, reviews)
    # 渲染器消费实际合并后的审阅，不能把12条新审的SHA误作全部46条审阅的绑定。
    effective_reviews_path = args.merged_reviews_out or args.reviews
    result["finalization_inputs"] = {"boards": file_ref(args.boards), "reviews": file_ref(effective_reviews_path),
                                      "new_reviews": file_ref(args.reviews),
                                      "script": file_ref(Path(__file__)),
                                      "unchanged_review_sources": [file_ref(p) for p in args.reuse_reviews]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
