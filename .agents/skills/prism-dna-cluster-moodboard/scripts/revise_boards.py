"""按真实板审做簇内替换、减图或取景修订；不改 DNA、簇归属或审阅结论。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from cluster_sample import bbox_contains, file_ref, mechanical_checks, read_json, valid_bbox, write_new
from design_emotion import SELECTED_OBJECT_VERSION, validate_display_contract
from finalize_boards import VIEW_REVIEW_POLICY_VERSION, RELATION_REVIEW_POLICY_VERSION, requires_relation_review


REVIEW_POLICY_VERSION = RELATION_REVIEW_POLICY_VERSION


def revise(boards: dict, reviews: dict, plan: dict) -> dict:
    result = deepcopy(boards)
    index = {b["board_id"]: b for b in result["boards"]}
    reviewed = {r["board_id"]: r for r in reviews["reviews"]}
    seen = set()
    for change in plan["changes"]:
        board_id = change["board_id"]
        if board_id in seen or board_id not in reviewed:
            raise ValueError("每板仅能有一条计划，且必须已有当前板实审")
        seen.add(board_id)
        board = index[board_id]
        review = reviewed[board_id]
        original = {m["unit_id"]: m for m in board["members"]}
        alternatives = {m["unit_id"]: m for m in board.get("alternates", [])}
        decisions = {m["unit_id"]: m for m in review["members"]}
        if set(original) != set(decisions):
            raise ValueError("审阅成员与修订前板不同")
        if len(board.get("revision_history", [])) >= 3:
            raise ValueError("当前板已达三次有界修订上限")
        touched = set()
        removed = []
        added = set()
        for action in change["actions"]:
            unit_id = action["unit_id"]
            if unit_id not in original or unit_id in touched or not action.get("reason", "").strip():
                raise ValueError("动作需对应当前唯一成员并说明实审依据")
            touched.add(unit_id)
            member = original[unit_id]
            decision = decisions[unit_id]
            position = next(i for i, m in enumerate(board["members"]) if m["unit_id"] == unit_id)
            kind = action["kind"]
            if kind == "roi":
                roi = action["roi"]
                # 这里只落地独立审阅者的建议，仍是待复核显示框，不能继承原通过状态。
                readable_window_issue = (not decision["keep"] and decision["image_quality"] in {"weak", "unreadable"})
                if roi != decision.get("suggested_roi") or (decision["scope_correct"] and not readable_window_issue):
                    raise ValueError("取景动作必须绑定当前实审明确提出的范围或可读性修正")
                # 第二信号可能正是错误框纳入的纽扣/背景；明确建议可作为待审修框，不能预授通过。
                if not decision["relation_supported"]:
                    raise ValueError("共同关系错误不能只靠取景动作修补，应先复核 DNA 或换图")
                if any(action.get(key, member.get(key)) != member.get(key)
                       for key in ("display_scope", "crop_reason", "evidence_bbox", "primary_subject", "target_role")):
                    raise ValueError("取景修订不能改变对象、事实或范围定义；须先做定点观察补查")
                if len(roi) != 4 or any(not isinstance(v, (int, float)) for v in roi):
                    raise ValueError("ROI 必须为归一化 x,y,w,h")
                x, y, width, height = roi
                if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1.000001 or y + height > 1.000001:
                    raise ValueError("ROI 超出原图")
                if member.get("display_bbox") is not None:
                    primary = member.get("primary_subject", {}).get("bbox")
                    evidence = member.get("evidence_bbox")
                    if not all(valid_bbox(box) for box in (roi, primary, evidence)):
                        raise ValueError("新版取景修订需有合法主体框和事实框")
                    if member.get("feature_definition_version") == SELECTED_OBJECT_VERSION:
                        # 调整已经观察过的代表性局部，不把整物 DNA 事后改称局部 DNA。
                        recorded_policy = review.get("provenance", {}).get("review_policy_version")
                        allowed = {RELATION_REVIEW_POLICY_VERSION} if requires_relation_review(board, review) else {
                            VIEW_REVIEW_POLICY_VERSION, RELATION_REVIEW_POLICY_VERSION}
                        if (recorded_policy not in allowed
                                or reviews.get("review_policy_version") not in {None, recorded_policy}):
                            raise ValueError("新版取景修订须绑定当前版本的选中对象与代表性裁片独立实审")
                        required = ("primary_subject_supported", "whole_subject_compatible", "crop_context_faithful")
                        expression_supported = decision.get("display_expression_supported") is True or readable_window_issue
                        if (not all(decision.get(key) is True for key in required) or not expression_supported
                                or not decision.get("reason", "").strip()):
                            raise ValueError("取景修订须有对象、原图情绪、局部表达及未掩盖冲突的明确实审依据")
                        revised_scope = {**member, "bbox": evidence, "display_bbox": roi, "usable": True}
                        validate_display_contract(revised_scope)
                    elif not bbox_contains(roi, primary) or not bbox_contains(roi, evidence):
                        raise ValueError("旧观察展示框不得裁掉主物品或排除事实框；代表性局部须先定点补查新范围")
                    member["prior_display_bbox"] = deepcopy(member["display_bbox"])
                    member["display_bbox"] = deepcopy(roi)
                member.setdefault("observation_roi", member["roi"])
                member["roi"] = roi
                member["display_revision_reason"] = action["reason"]
            elif kind in {"replace", "drop"}:
                # 保留原失败单元与完整簇，替换只能来自已冻结的同簇候选。
                rejected = deepcopy(member)
                rejected["display_exclusion_reason"] = action["reason"]
                removed.append(rejected)
                if kind == "replace":
                    replacement_id = action["replacement_unit_id"]
                    if replacement_id not in alternatives or replacement_id in added:
                        raise ValueError("替换图须为本板未选中的同簇候选且不能重复")
                    added.add(replacement_id)
                    board["members"][position] = deepcopy(alternatives[replacement_id])
                else:
                    del board["members"][position]
            else:
                raise ValueError(f"不支持动作 {kind}")
        checks = mechanical_checks(board["members"])
        if not checks["quantity_pass"] or checks["unique_original_count"] != len(board["members"]):
            raise ValueError("修订后须保留 6–10 个不同原图")
        if not all(checks[k] for k in ("source_articles_unique", "known_source_groups_unique", "known_projects_unique")):
            raise ValueError("修订不能引入已知重复来源／项目")
        if checks["runway_known_count"] > checks["runway_maximum"]:
            raise ValueError("修订后已知秀场比例超出合同")
        board["alternates"] = [m for m in board.get("alternates", []) if m["unit_id"] not in added] + removed
        board.setdefault("revision_history", []).append({"actions": deepcopy(change["actions"]),
                                                         "prior_visual_verdict": review["visual_verdict"]})
        board.update(status="revised_pending_review", mechanical_checks=checks,
                     visual_review_status="not_performed", view_review_status="needs_current_view_review",
                     designer_approved=False)
        # 原板可以使用其历史实审定位问题；新修订一律成为当前 v5 待审候选。
        board.update(requires_concrete_relation_review=True, concrete_relation_status="requires_concrete_relation_review")
        for key in ("validation", "review_provenance", "common_relation", "common_design_emotion",
                    "emotion_combination_evidence", "shared_design_relation", "pair_checks", "least_consistent_unit_id"):
            board.pop(key, None)
        for member in board["members"]:
            member.pop("current_target_review", None)
            member.update(needs_current_view_review=True, target_quality_status="requires_current_target_review")
    result["revision_plan"] = deepcopy(plan)
    result["revision_policy_version"] = REVIEW_POLICY_VERSION
    result["new_visual_review_performed"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reviews, plan = read_json(args.reviews), read_json(args.plan)
    if reviews["boards_ref"]["sha256"] != file_ref(args.boards)["sha256"]:
        raise ValueError("实审必须针对当前修订前板")
    result = revise(read_json(args.boards), reviews, plan)
    result["revision_inputs"] = {"boards": file_ref(args.boards), "reviews": file_ref(args.reviews),
                                 "plan": file_ref(args.plan), "script": file_ref(Path(__file__))}
    write_new(args.out, result)
    print(json.dumps({"revised_boards": len(plan["changes"]), "new_model_calls": 0}))


if __name__ == "__main__":
    main()
