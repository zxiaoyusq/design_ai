"""对冻结 LLM 板作一次有界反馈修订；默认只读，事实问题不在聚类阶段补写。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import jsonschema

import llm_group as group
from render_delivery import validate_layout_overrides


VERSION = "prism.llm_board_revision.v5"
PLAN_VERSION = "prism.llm_board_revision_plan.v1"


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def fingerprint(value: object) -> str:
    return hashlib.sha256(group.encoded(value).encode()).hexdigest()


def feedback_value(document: object, pointer: str) -> object:
    """反馈位置绑定原文件；问题改板号或改展示名称不能重置修订次数。"""
    if pointer and not pointer.startswith("/"):
        raise ValueError("feedback_pointer 必须为 JSON Pointer")
    for token in pointer.split("/")[1:] if pointer else []:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def read_plan_feedback(ref: dict, pointer: str) -> tuple[object, bool]:
    """HTML 只核来源与锚点，正文由已登记问题提供，避免整页图片或指令进入请求。"""
    raw = group.read_reference(ref)
    feedback_contract = group.unified_module().feedback_module()
    feedback_contract._check_pointer(raw, ref, pointer)
    if Path(ref["path"]).suffix.lower() in {".html", ".htm"}:
        return None, True
    return feedback_value(json.loads(raw), pointer), False


def original_visual(board: dict, cards: dict) -> tuple[dict, dict, list[dict]]:
    """核旧请求自己的证据闭环，不要求历史执行器等于当前版本，也不改写原答。"""
    provenance = board["provenance"]
    folder = Path(provenance["path"])
    if not folder.is_absolute():
        raise ValueError("视觉出处必须是绝对路径")
    request_path, receipt_path = folder / "request.json", folder / "receipt.json"
    request, receipt = read(request_path), read(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("answer_ref") != provenance.get("answer_ref"):
        raise ValueError("目标板不是可验证的成功视觉原答")
    answer = json.loads(group.read_reference(receipt["answer_ref"]))
    for field in ("prompt_ref", "schema_ref", "images", "requested_model", "requested_reasoning_effort"):
        if request.get(field) != receipt.get(field):
            raise ValueError(f"视觉请求与回执不一致：{field}")
    prompt = group.read_reference(request["prompt_ref"]).decode()
    if "=== ACTUAL PAYLOAD ===" not in prompt:
        raise ValueError("视觉原请求缺实际 payload")
    payload, _ = json.JSONDecoder().raw_decode(prompt.split("=== ACTUAL PAYLOAD ===", 1)[1].lstrip())
    if payload.get("task") != "visual" or payload["template"]["template_id"] != board["template_id"]:
        raise ValueError("目标板不对应原视觉方向")
    jsonschema.Draft202012Validator(json.loads(group.read_reference(request["schema_ref"]))).validate(answer)
    group.validate_task_answer(answer, {"stage": "visual", "payload": payload})
    matches = [row for row in answer["groups"] if row["member_ids"] == board["unit_ids"]]
    if len(matches) != 1 or any(board.get(key) != value for key, value in matches[0].items()):
        raise ValueError("板成员或关系依据与视觉原答不一致")
    candidate_ids = [row["card_id"] for row in payload["cards"]]
    group.checked_ids(candidate_ids, set(cards), "原视觉候选池")
    covered = [i for row in answer["groups"] for i in row["member_ids"]] + [row["card_id"] for row in answer["not_selected"]]
    group.checked_ids(covered, set(candidate_ids), "原答候选覆盖")
    if set(covered) != set(candidate_ids):
        raise ValueError("原视觉回答未完整交代候选池")
    if not set(board["unit_ids"]) <= set(candidate_ids):
        raise ValueError("板成员不在原请求候选池")
    for old in payload["cards"]:
        expected = group.compact_card(cards[old["card_id"]])
        if payload.get("comparison_mode") == "unified":
            expected = group.unified_module().card_projection(expected)
        if old != expected:
            raise ValueError("原请求 DNA 与当前冻结卡不一致")
    images = {row["sha256"]: row for row in request["images"]}
    for image in images.values():
        group.read_reference(image)
    bindings = payload["image_bindings"]
    if {row["card_id"] for row in bindings} != set(candidate_ids) or len(bindings) != len(candidate_ids):
        raise ValueError("原视觉附件未完整对应候选卡")
    for binding in bindings:
        card = cards[binding["card_id"]]
        if (binding["original_sha256"] != card["image_sha256"]
                or binding["display_bbox"] != card["display_bbox"]
                or binding["evidence_bbox"] != card["evidence_bbox"]
                or binding["original_sha256"] not in images
                or binding["display_crop_sha256"] not in images):
            raise ValueError("原视觉附件不是冻结对象/视窗")
    refs = [group.reference(request_path), group.reference(receipt_path), receipt["answer_ref"],
            request["prompt_ref"], request["schema_ref"]]
    return payload, answer, refs


def prepare(prepared: Path, source: Path, board_id: str, plan_path: Path) -> dict:
    paths = {"prepared": prepared, "boards": source / "boards.json", "clusters": source / "clusters.json"}
    plan = read(plan_path)
    allowed_fields = {"schema_version", "board_id", "issue_key", "issue_kind", "reason", "feedback_ref",
                      "feedback_pointer", "source_refs", "exclude_card_ids", "layout_overrides"}
    if not isinstance(plan, dict) or set(plan) - allowed_fields:
        raise ValueError("修订计划包含未知动作；不能静默忽略改 DNA/改框或程序选员要求")
    if plan.get("schema_version") != PLAN_VERSION or plan.get("board_id") != board_id:
        raise ValueError("计划版本或目标 board_id 不符")
    if plan.get("issue_kind") not in {"fact", "relationship", "display"}:
        raise ValueError("issue_kind 必须明确分流 fact / relationship / display")
    if (not isinstance(plan.get("issue_key"), str) or not plan["issue_key"].strip()
            or not isinstance(plan.get("reason"), str) or not plan["reason"].strip()):
        raise ValueError("修订需稳定 issue_key 和具体原因")
    if plan.get("source_refs") != {name: group.reference(path) for name, path in paths.items()}:
        raise ValueError("计划未绑定当前冻结输入 SHA")
    feedback, needs_registered_observation = read_plan_feedback(plan["feedback_ref"], plan.get("feedback_pointer", ""))
    issue_fingerprint = fingerprint([plan["feedback_ref"]["sha256"], plan.get("feedback_pointer", "")])
    boards, clusters = read(paths["boards"]), read(paths["clusters"])
    previous_layout_path = source / "layout-overrides.json"
    previous_layout = validate_layout_overrides(read(previous_layout_path) if previous_layout_path.exists() else {},
        {m["unit_id"] for row in boards["boards"] for m in row["members"]})
    document = group.load_prepared(prepared)
    cards = {row["card_id"]: row for row in document["cards"]}
    if len(cards) != len(document["cards"]):
        raise ValueError("冻结设计卡身份重复")
    for data in (boards, clusters):
        if (data.get("input_refs", {}).get("prepared") != group.reference(prepared)
                or data["input_refs"]["design_cards"] != read(prepared)["design_cards_ref"]):
            raise ValueError("原板/聚类没有绑定本次 prepared")
        for value in data["input_refs"].values():
            group.read_reference(value)
    targets = [row for row in boards["boards"] if row["board_id"] == board_id]
    if len(targets) != 1:
        raise ValueError("目标板不存在或重复")
    board = targets[0]
    old_clusters = [row for row in clusters["clusters"] if row["cluster_id"] == board["cluster_id"]]
    if len(old_clusters) != 1 or old_clusters[0]["unit_ids"] != board["unit_ids"]:
        raise ValueError("板与聚类成员不一致")
    if [row["unit_id"] for row in board["members"]] != board["unit_ids"]:
        raise ValueError("板的展示成员身份/顺序不一致")
    for member in board["members"]:
        card = cards[member["unit_id"]]
        if (member["sha256"] != card["image_sha256"] or member["image_id"] != card["image_id"]
                or member["roi"] != card["display_bbox"] or member["display_bbox"] != card["display_bbox"]
                or member["evidence_bbox"] != card["evidence_bbox"]):
            raise ValueError("板成员没有保留冻结原图/ROI")
    history = deepcopy(boards.get("revision_history", []))
    if history != clusters.get("revision_history", []):
        raise ValueError("板与聚类的修订历史不一致")
    prior = [row for row in history if row["issue_fingerprint"] == issue_fingerprint or row["issue_key"] == plan["issue_key"]]
    if len(prior) >= 3:
        raise ValueError("同一问题已修订三轮；需方法决策，不自动追加")
    overrides = validate_layout_overrides(plan.get("layout_overrides", {}), set(board["unit_ids"]))
    other_members = {m["unit_id"] for other in boards["boards"] if other["board_id"] != board_id for m in other["members"]}
    if set(overrides) & other_members:
        raise ValueError("该布局成员也出现在其它板；单板入口不能顺带改变其它板尺度")
    excluded = plan.get("exclude_card_ids", [])
    if not isinstance(excluded, list):
        raise ValueError("exclude_card_ids 必须是数组")
    if plan["issue_kind"] != "relationship" and excluded:
        raise ValueError("事实或显示分支不允许改成员")
    if plan["issue_kind"] == "fact" and overrides:
        raise ValueError("事实分支只能登记 pending_A，不以布局掩盖事实问题")
    if plan["issue_kind"] == "display" and not overrides:
        raise ValueError("显示修订需明确 layout_overrides")
    payload = answer = None
    evidence_refs, candidates = [], []
    if plan["issue_kind"] == "relationship":
        payload, answer, evidence_refs = original_visual(board, cards)
        original_ids = [row["card_id"] for row in payload["cards"]]
        group.checked_ids(excluded, set(original_ids), "明确排除项")
        if not {row["card_id"] for row in answer["dna_issues"]} <= set(excluded):
            raise ValueError("原视觉 DNA 争议尚未解决；须明确排除并待 A，不可重选成已解决")
        candidates = [identity for identity in original_ids if identity not in excluded]
        if not 2 <= len(candidates) <= group.MERGE_VISUAL_WINDOW:
            raise ValueError(f"一次定点重选须有 2–{group.MERGE_VISUAL_WINDOW} 张原请求候选；不自动扩池或拆成多调用")
        if any(not group.belongs_to_comparison(cards[identity], board["branch"]) for identity in candidates):
            raise ValueError("候选分支与原板不一致")
        # 完整卡、模板和反馈不可为塞进一包而截断；附件索引另留小量余量。
        size = len(group.encoded({"cards": [group.compact_card(cards[i]) for i in candidates],
            "template": payload["template"], "feedback": feedback, "plan": plan,
            "historical_dna_issues_pending_A": answer["dna_issues"]}))
        binding_size = len(group.encoded([row for row in payload["image_bindings"] if row["card_id"] in candidates]))
        if size + binding_size + 2000 > group.MAX_PAYLOAD_CHARACTERS:
            raise ValueError("完整修订证据超过单包预算；需显式调整范围，不截断")
    return {"plan": plan, "document": document, "cards": cards, "boards": boards, "clusters": clusters,
            "board": board, "old_cluster": old_clusters[0], "history": history, "feedback": feedback,
            "feedback_needs_registered_observation": needs_registered_observation,
            "issue_fingerprint": issue_fingerprint, "issue_attempt": len(prior) + 1,
            "layout_overrides": overrides, "previous_layout": previous_layout,
            "candidates": candidates, "payload": payload, "answer": answer,
            "source_refs": {**plan["source_refs"], "plan": group.reference(plan_path),
                            **({"layout": group.reference(previous_layout_path)} if previous_layout_path.exists() else {})},
            "evidence_refs": evidence_refs}


class RevisionCalls(group.ModelCalls):
    """单板只允许一个视觉任务；不能顺带选向、路由、提名或补 DNA。"""

    def __init__(self, out: Path, context: dict, executor=None, *, comparison_mode="legacy_branches",
                 feedback_registry=None, feedback_registry_ref=None):
        super().__init__(out, group.POLICY.read_text(), workers=1, max_calls=1, execute=executor,
                         comparison_mode=comparison_mode, feedback_registry=feedback_registry,
                         feedback_registry_ref=feedback_registry_ref)
        self.context, self.submitted = context, False

    def run(self, tasks: list) -> list:
        if not tasks:
            return []
        if self.submitted or len(tasks) != 1 or tasks[0]["stage"] != "visual":
            raise ValueError("定点修订只允许一次视觉比较")
        self.submitted = True
        item = deepcopy(tasks[0])
        if {row["card_id"] for row in item["payload"]["cards"]} != set(self.context["candidates"]):
            raise ValueError("定点请求改动了已冻结候选池")
        item["payload"]["revision_context"] = {
            "version": VERSION, "previous_board_id": self.context["board"]["board_id"],
            "feedback_as_observation_not_new_dna": self.context["feedback"],
            "reason": self.context["plan"]["reason"],
            # 旧选员理由可能已经受到参考外观诱导；只留在原答审计，不再当本轮反证。
            # 历史 DNA 疑义保留为待核风险，不宣称它已成为当前单图事实。
            "historical_dna_issues_pending_A": [
                {"card_id": row["card_id"], "reported_issue": row["reason"], "status": "unverified_pending_A"}
                for row in self.context["answer"]["dna_issues"]],
            "excluded_ids": self.context["plan"].get("exclude_card_ids", []),
            "instruction": "只重选本板。历史是否入选及原审美理由不作当前优先或否决，按当前冻结DNA、真实候选图和中性规则重新判断；可以无合适板，不补位。本次用户反馈与历史DNA疑义是待解决或待核问题，不是新单图事实；反馈提及参考外观不自动成为相似度加权偏好。归属争议不得强扩框，对象、DNA、ROI不可改；历史疑义仍待A核对，不宣称本轮已解决。当前候选的未解决事实列dna_issues。"}
        return super().run([item])


def invalidate_review(board: dict, reason: str) -> None:
    """保留源文档引用而清除新版的嵌入通过；显示变化同样需要当前板证据。"""
    for key in ("review", "reference_review", "review_provenance", "review_display", "validation_display"):
        board.pop(key, None)
    board["validation"] = {**board.get("validation", {}), "visual": None}
    board.update(independent_review=False, designer_approved=False, designer_confirmed=False,
                 review_invalidation={"reason": reason, "current_review_required": True})


def run(prepared: Path, source: Path, board_id: str, plan_path: Path, out: Path, *, execute=False, executor=None,
        comparison_mode="legacy_branches", feedback_path: Path | None = None) -> dict:
    context = prepare(prepared, source, board_id, plan_path)
    kind = context["plan"]["issue_kind"]
    # 已有注册表沿版本传递，不能因换目录或改板名丢掉未解决反馈。
    feedback, feedback_ref = group.load_run_feedback(feedback_path, source, prepared, context["cards"])
    if comparison_mode == "unified":
        plan = context["plan"]
        feedback_contract = group.unified_module().feedback_module()
        aliases = feedback_contract.build_feedback_aliases(feedback, context["cards"]) if feedback else {}
        active = feedback_contract.relevant_feedback(feedback or {"issues": []},
                                                     context["board"]["unit_ids"], aliases=aliases)
        registered = [issue for issue in active
                      if issue["feedback_ref"] == plan["feedback_ref"]
                      and issue["feedback_pointer"] == plan.get("feedback_pointer", "")
                      and issue["issue_kind"] == kind]
        if not registered:
            raise ValueError("统一修订的当前问题须按来源定位、类型和受影响成员登记在 --feedback；空表或其它问题不能代替")
        if context["feedback_needs_registered_observation"]:
            context["feedback"] = [{"issue_id": issue["issue_id"], "observation": issue["observation"],
                                    "resolution_condition": issue["resolution_condition"],
                                    "affected_card_ids": issue["current_affected_card_ids"]}
                                   for issue in registered]
    elif context["feedback_needs_registered_observation"]:
        raise ValueError("HTML 反馈需统一模式及 --feedback 中已登记的来源锚点与问题观察；不直接解析整页或交给模型")
    summary = {"status": "dry_run_no_model_calls", "issue_kind": kind,
               "category_limit_this_execution": "planned_visual_reselection" if kind == "relationship" else "not_evaluated_no_member_reselection",
               "planned_visual_calls": int(kind == "relationship"), "candidate_ids": context["candidates"],
               "issue_attempt": context["issue_attempt"], "dna_extraction_calls": 0,
               "comparison_mode": comparison_mode, "feedback_registry_ref": feedback_ref,
               "preserved_other_boards": [b["board_id"] for b in context["boards"]["boards"] if b["board_id"] != board_id]}
    if not execute:
        return summary
    if out.exists():
        raise ValueError("修订须写全新目录，不能覆盖旧失败或旧交付")
    out.mkdir(parents=True)
    contract = {"schema_version": VERSION, "implementation_ref": group.reference(Path(__file__)),
                "grouping_ref": group.reference(group.SCRIPT), "source_refs": context["source_refs"],
                "evidence_refs": context["evidence_refs"], "policy_ref": group.reference(group.POLICY),
                "grouping_principles": group.load_grouping_principles()[1], "prompt_version": group.PROMPT_VERSION,
                "category_assignment_version": group.CATEGORY_ASSIGNMENT_VERSION,
                "category_limit_policy_version": group.CATEGORY_LIMIT_POLICY_VERSION,
                "category_limit_this_execution": summary["category_limit_this_execution"],
                "feedback_ref": context["plan"]["feedback_ref"], "plan": context["plan"],
                "max_calls": summary["planned_visual_calls"], "frozen_dna_and_roi_unchanged": True}
    contract.update(comparison_mode=comparison_mode, feedback_registry_ref=feedback_ref)
    if comparison_mode == "unified":
        contract.update(policy_ref=group.reference(group.unified_module().POLICY),
                        grouping_principles=group.load_grouping_principles(group.unified_module().POLICY)[1],
                        prompt_version=group.unified_module().PROMPT_VERSION,
                        unified_dependencies={name: group.reference(group.SCRIPT.with_name(name)) for name in
                                              ("unified_selection.py", "feedback_contract.py")})
    group.write_new(out / "run-contract.json", contract)
    boards, clusters = deepcopy(context["boards"]), deepcopy(context["clusters"])
    target = next(row for row in boards["boards"] if row["board_id"] == board_id)
    issues, audit, records, new_boards = [], [], [], []
    attempted = 0
    if kind == "relationship":
        calls = RevisionCalls(out, context, executor, comparison_mode=comparison_mode,
                              feedback_registry=feedback, feedback_registry_ref=feedback_ref)
        template = {**context["payload"]["template"], "branch": context["board"]["branch"]}
        groups, audit = group.visual_group({template["template_id"]: context["candidates"]}, [template],
                                          context["document"]["cards"], calls, group.MERGE_VISUAL_WINDOW, issues)
        attempted, records = calls.attempted, calls.records
        retained_ids = {row["cluster_id"] for row in clusters["clusters"] if row["cluster_id"] != target["cluster_id"]}
        if any(row["cluster_id"] in retained_ids for row in groups):
            issues.append({"reason": "重选结果与其它保留组身份重叠；不覆盖或重复展示"})
            groups = []
        for selected in groups:
            if selected["status"] != "model_grouped":
                continue
            members = [{"unit_id": i, "image_id": context["cards"][i]["image_id"],
                        "sha256": context["cards"][i]["image_sha256"], "branch": context["cards"][i]["branch"],
                        "roi": context["cards"][i]["display_bbox"], "display_bbox": context["cards"][i]["display_bbox"],
                        "evidence_bbox": context["cards"][i]["evidence_bbox"]} for i in selected["unit_ids"]]
            new_boards.append({**selected, "board_id": "BOARD-" + selected["cluster_id"], "members": members,
                               "llm_selected_members": True, "not_aesthetic_accuracy_measurement": True})
        if groups:
            # 模型可能只返回小组。保留它们，但不能把旧板或小组冒充修订成功的正式板。
            clusters["clusters"] = [r for r in clusters["clusters"] if r["cluster_id"] != target["cluster_id"]] + groups
            boards["boards"] = [r for r in boards["boards"] if r["board_id"] != board_id] + new_boards
        else:
            invalidate_review(target, "定点模型调用未形成可替代板；旧成员仅作诊断保留")
            target["revision_status"] = "revision_incomplete_original_retained"
            target["status"] = "revision_incomplete"
            next(r for r in clusters["clusters"] if r["cluster_id"] == target["cluster_id"])["status"] = "revision_incomplete"
        for board in new_boards:
            invalidate_review(board, "成员重新选择，旧审阅不能授予新版通过")
    else:
        invalidate_review(target, "显示尺度改变" if kind == "display" else "单图事实待 A 阶段核实")
        target["revision_status"] = "display_revision_pending_review" if kind == "display" else "pending_A"
        if kind == "fact":
            target["status"] = "pending_A"
            next(r for r in clusters["clusters"] if r["cluster_id"] == target["cluster_id"])["status"] = "pending_A"
    entry = {"issue_key": context["plan"]["issue_key"], "issue_fingerprint": context["issue_fingerprint"],
             "issue_attempt": context["issue_attempt"], "issue_kind": kind, "target_board_id": board_id,
             "feedback_ref": context["plan"]["feedback_ref"], "plan_ref": context["source_refs"]["plan"],
             "model_calls": attempted, "issues": issues}
    summary.update(status="pending_A" if kind == "fact" else "revision_incomplete" if kind == "relationship" and not new_boards else "revision_pending_review",
                   model_calls_this_execution=attempted, independent_review_calls=0, issues=issues,
                   current_formal_boards=sum(row.get("status") == "model_grouped" for row in boards["boards"]),
                   diagnostic_boards=sum(row.get("status") != "model_grouped" or bool(row.get("revision_status")) for row in boards["boards"]),
                   designer_approval=False, call_count_scope="本次单板修订；历史调用通过 source_revision_refs 保留，不当新调用")
    if kind == "relationship":
        summary["category_limit_this_execution"] = "checked_on_new_model_groups" if groups else "no_valid_new_model_groups"
    for key in ("mode", "priority_goal", "branch_coverage"):
        if key in context["clusters"].get("summary", {}):
            summary[key] = deepcopy(context["clusters"]["summary"][key])
    summary["inherited_source_coverage"] = bool(summary.get("branch_coverage"))
    for document in (boards, clusters):
        document.update(revision_history=context["history"] + [entry], revision_summary=summary,
                        source_revision_refs=context["source_refs"], execution_status=summary["status"])
    # 其它板保持原样；残余只按新成员集合更新，不给未选卡写低质量结论。
    grouped = {i for row in clusters["clusters"] if row["status"] in {"model_grouped", "small_cluster"} for i in row["unit_ids"]}
    old_residual = {row["card_id"]: row for row in clusters.get("residual_cards", [])}
    clusters["residual_cards"] = [old_residual.get(i, {"card_id": i, "image_id": card["image_id"],
        "status": "targeted_revision_not_selected", "next_action": "保留冻结证据；未选不等于低质量"})
        for i, card in context["cards"].items() if i not in grouped]
    summary["residual_cards"] = len(clusters["residual_cards"])
    for current in (boards, clusters):
        current["source_summary"] = current.get("summary", {})
        current["summary"] = {**summary, "formal_candidates": summary["current_formal_boards"],
                              "model_calls_started": attempted}
    visible_ids = {m["unit_id"] for board in boards["boards"] for m in board["members"]}
    merged_layout = {**context["previous_layout"], **context["layout_overrides"]}
    active_layout = {i: value for i, value in merged_layout.items() if i in visible_ids}
    output = {"boards": boards, "clusters": clusters, "observations.compat": group.compatibility(context["document"]),
              "visual-selection": {"audit": audit}, "call-ledger": {"calls": records, "summary": summary},
              "layout-overrides": active_layout,
              "revision-report": {**entry, "superseded_board": context["board"], "superseded_cluster": context["old_cluster"],
                  "new_board_ids": [b["board_id"] for b in new_boards], "source_evidence_refs": context["evidence_refs"],
                  "frozen_dna_and_roi_unchanged": True, "feedback_is_not_new_dna": True,
                  "inactive_layout_ids": sorted(set(merged_layout) - set(active_layout)),
                  "pending_A": context["feedback"] if kind == "fact" else [], "summary": summary}}
    if feedback:
        output["feedback-registry"] = feedback
    group.write_outputs(output, out, prepared)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--comparison-mode", choices=("unified", "legacy_branches"), default="unified")
    parser.add_argument("--feedback", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.prepared.resolve(), args.source.resolve(), args.board_id, args.plan.resolve(),
                         args.out.resolve(), execute=args.execute, comparison_mode=args.comparison_mode,
                         feedback_path=args.feedback.resolve() if args.feedback else None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
