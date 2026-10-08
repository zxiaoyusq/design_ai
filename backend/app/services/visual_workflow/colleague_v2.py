"""同事 v2 的项目执行合同和离线原生门重放；不调模型、不改历史结论。

实际视觉结论来自带证据的独立阅读上下文。这里仅核当前身份、数量和
声明一致性，并调用同事原生验证器；JSON 完整或程序通过都不等于看过图。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

STRATEGY_VERSION = "prism-workflow-skills-v2.0.0-project-20261006"
SUPPORT_DIR = Path(__file__).resolve().parents[4] / ".agents/skills/prism_skill_support"
STAGES = (
    "semantic_clustering", "semantic_handshake", "direction_selection",
    "visual_translation", "material_preview", "freeze_material_brief",
    "bounded_candidate_pool", "frozen_r5", "target_binding", "target_quality",
    "actual_crop_review", "native_h2_grouping", "independent_board_review",
    "targeted_revision", "delivery",
)
R5_MODEL_POLICY = {"model": "gpt-6-sol", "reasoning_effort": "low",
                   "service_tier_requested": "default", "fast_mode": False}


def default_project_policy(candidate_pool_policy: dict, execution_budget: dict) -> dict:
    """本次用户明确要求 10 图/10 项目；候选容量和费用预算另行登记。

    此配置仅准备任务，不继承旧授权、60/12/2 限额或历史代审许可。
    """
    if type(candidate_pool_policy.get("target")) is not int or candidate_pool_policy["target"] < 1:
        raise ValueError("必须明确登记候选池容量，不能沿用最终板数量作为候选截断")
    if not isinstance(execution_budget, dict) or any(type(v) is not int or v < 0 for v in execution_budget.values()):
        raise ValueError("预算须显式登记非负整数；空预算表示尚未配置")
    return {"strategy_version": STRATEGY_VERSION, "run_mode": "end_to_end",
            "quantity_policy": {"target": 10, "native_minimum": 10, "maximum": 10},
            "source_policy": {"independent_projects": 10, "identity_evidence_required": True,
                              "maximum_per_article": 1, "maximum_per_known_project": 1},
            "candidate_pool_policy": deepcopy(candidate_pool_policy),
            "execution_budget": deepcopy(execution_budget), "model_policy": dict(R5_MODEL_POLICY),
            "execution_authorization": {"allowed": False, "maximum_attempts_per_request": 1},
            "model_calls_paused": True, "maximum_targeted_revisions_per_issue": 3,
            "historical_proxy_permissions_inherited": False, "stages": list(STAGES)}


def validate_visual_family(brief: dict) -> dict:
    """视觉转译须可检验且先冻结；槽纹/低彩度仅属于具体板，不作通用条件。"""
    errors = []
    branch, unit = brief.get("branch"), brief.get("comparison_unit")
    if branch not in ("ID", "CMF") or unit not in (
        ("whole_object",) if branch == "ID" else ("surface", "same_object_interface")
    ):
        errors.append("branch_comparison_unit_mismatch")
    for key in ("direction_id", "primary_relation", "semantic_to_visual_translation"):
        if not isinstance(brief.get(key), str) or not brief[key].strip():
            errors.append("missing_" + key)
    for key in ("required_evidence", "allowed_variation", "confounders", "scope_limits"):
        if not isinstance(brief.get(key), list) or not brief[key]:
            errors.append("missing_" + key)
    for key in ("negative_audit", "deferred_obligations"):
        if not isinstance(brief.get(key), list):
            errors.append("missing_original_" + key)
    if brief.get("frozen_before_final_selection") is not True:
        errors.append("family_not_frozen_before_final_selection")
    if any(brief.get("count_policy", {}).get(key) != 10 for key in ("target", "minimum", "maximum")):
        errors.append("current_project_requires_exactly_10")
    pool = brief.get("candidate_pool_policy", {})
    if type(pool.get("target")) is not int or pool["target"] < 1:
        errors.append("candidate_pool_must_be_explicit_and_separate")
    return {"valid": not errors, "errors": errors, "visual_pass_awarded": False,
            "new_model_calls": 0}


def checked_file_ref(reference: dict, *, as_json: bool = False) -> Any:
    """核对真实本机字节；不把不同 URL/文件名当独立项目证据。"""
    path = Path(reference["path"])
    if not path.is_absolute() or not path.is_file():
        raise ValueError("本机绝对路径不存在")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise ValueError("FileRef 字节哈希不匹配")
    return json.loads(content) if as_json else content


def replay_native(module: str, method: str, arguments: dict, *, support_dir: Path | None = None) -> dict:
    """在独立 Python 进程复用同事白名单验证器；入口不包含模型执行方法。

    完整 prepared/grouping/execution 是原生门的输入，不能传一个 cached PASS。
    """
    allowed = {"r5": {"load_record"}, "alias-r5": {"load_record"}, "quality": {"accept"},
               **{name: {"prepare_board_review", "accept_board_review"}
                  for name in ("id", "cmf", "alias-id", "alias-cmf", "future-id", "future-cmf")}}
    if method not in allowed.get(module, set()):
        raise ValueError("仅允许离线原生验证，禁止模型执行或非白名单方法")
    script = (support_dir or SUPPORT_DIR) / "scripts/native_api.py"
    with tempfile.TemporaryDirectory(prefix="prism-v2-offline-") as folder:
        args_path, out_path = Path(folder) / "arguments.json", Path(folder) / "result.json"
        args = deepcopy(arguments)
        future_ref = args.pop("future_reference_ref", None)
        args_path.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, "-B", str(script), "call", "--module", module,
                   "--method", method, "--args", str(args_path), "--out", str(out_path)]
        if module.startswith("future-"):
            checked_file_ref(future_ref)
            command += ["--future-reference", future_ref["path"]]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        except subprocess.TimeoutExpired as error:
            raise ValueError("离线原生验证超时；未启动模型") from error
        if result.returncode:
            raise ValueError("原生验证拒绝：" + result.stderr[-3000:])
        return json.loads(out_path.read_text(encoding="utf-8"))


def validate_target_material(material: dict, brief: dict, *, support_dir: Path | None = None) -> dict:
    """重放原 R5/当前目标品质，并验证实际裁片阅读链；不保留本地宽松品质门。

    R5 flat at 不创造物体树，当前物体/界面归属必须由真实阅读绑定。
    原生 basic 只可进入定点确认，不能被本地 boolean 提升为通过。
    """
    errors = list(validate_visual_family(brief)["errors"])
    record, quality = None, None
    try:
        original = material["original_ref"]
        checked_file_ref(original)
        checked_file_ref(material["actual_view_ref"])
        trace = checked_file_ref(material["view_review_ref"], as_json=True)
        if (trace.get("original_ref") != original or trace.get("actual_view_ref") != material["actual_view_ref"]
                or trace.get("brief_ref") != material["brief_ref"]):
            errors.append("actual_crop_review_identity_changed")
        if checked_file_ref(material["brief_ref"], as_json=True) != brief:
            errors.append("frozen_brief_changed")
        if trace.get("review_kind") not in ("human", "ai_independent_context") or not trace.get("reviewer_actor"):
            errors.append("actual_independent_reading_required")
        for key in ("original_image_seen", "actual_view_seen", "primary_relation_prominent", "confounders_controlled"):
            if trace.get(key) is not True:
                errors.append("crop_" + key + "_not_confirmed")
        record = replay_native(material.get("r5_module", "r5"), "load_record",
                               material["r5_arguments"], support_dir=support_dir)
        if record["image_sha256"] != original["sha256"]:
            errors.append("r5_original_identity_mismatch")
        known = {row["observation_id"]: row for row in record["observations"]}
        bindings = material.get("observation_bindings", [])
        if not bindings:
            errors.append("current_scope_dna_missing")
        for binding in bindings:
            row = known.get(binding.get("observation_id"))
            if not row or any(binding.get(key) != row.get(key) for key in ("value", "at", "source")):
                errors.append("binding_not_original_known_observation")
        if brief["branch"] == "CMF":
            if trace.get("same_surface_or_same_object_interface") is not True:
                errors.append("native_cmf_same_object_scope_required")
        elif trace.get("whole_target_visible") is not True:
            errors.append("native_id_whole_object_required")
        quality = replay_native("quality", "accept", material["quality_arguments"], support_dir=support_dir)
        if quality.get("admissible") is not True:
            errors.append("native_selected_target_quality_not_admissible")
        target = quality.get("validated_target") or {}
        if (target.get("image_ref") != original
                or target.get("target_digest") != material.get("quality_target_digest")):
            errors.append("quality_cannot_be_borrowed_from_other_target")
        if trace.get("evidence_derived_from_enhancement") is not False:
            errors.append("display_enhancement_cannot_prove_original_evidence")
    except (KeyError, TypeError, ValueError, OSError) as error:
        errors.append(str(error))
    return {"valid": not errors, "errors": errors, "native_r5": record,
            "native_quality": quality, "visual_pass_awarded": False, "new_model_calls": 0}



def verify_project_identity(board: dict) -> dict:
    """核十个项目的真实来源核实记录，不把不同 ID 或引用完整当独立事实。

    identity_basis 只是机器引用完整性。独立项目须另外绑定实际来源审阅的
    原回答、读源上下文和当前图/文章；同一证据同一句话不证明十个项目。
    """
    errors = []
    tiles = board.get("tiles", [])
    try:
        review = checked_file_ref(board["project_identity_review_ref"], as_json=True)
        trace = checked_file_ref(review["review_trace_ref"], as_json=True)
        raw = checked_file_ref(review["raw_output_ref"], as_json=True)
        context = ("review_kind", "reviewer_actor", "context_id")
        if review.get("review_kind") not in ("human", "ai_independent_context", "synthetic_fixture"):
            errors.append("actual_source_identity_reviewer_kind_required")
        if not all(isinstance(review.get(k), str) and review[k].strip() for k in context):
            errors.append("source_identity_reading_context_required")
        if any(trace.get(k) != review.get(k) or raw.get(k) != review.get(k) for k in context):
            errors.append("source_identity_trace_context_mismatch")
        if trace.get("sources_actually_read") is not True or not trace.get("executed_at"):
            errors.append("actual_source_reading_trace_required")
        rows = review.get("members", [])
        if raw.get("members") != rows:
            errors.append("identity_review_not_original_source_reply")
        mapping = {row["image_id"]: row for row in rows}
        if len(mapping) != len(rows) or set(mapping) != {tile["image_id"] for tile in tiles}:
            errors.append("project_identity_review_must_cover_current_members")
        source_refs = trace.get("source_refs", [])
        source_identities = {(ref["path"], ref["sha256"]) for ref in source_refs}
        for ref in source_refs:
            checked_file_ref(ref)
        identities, proof_spans = [], []
        for tile in tiles:
            row = mapping.get(tile["image_id"], {})
            for key in ("image_id", "article_id", "source_group_id", "source_project_id", "original_ref", "identity_basis"):
                if row.get(key) != tile.get(key):
                    errors.append("project_identity_member_binding_changed:" + tile["image_id"] + ":" + key)
            if row.get("verdict") != "distinct_project_verified" or not row.get("reason"):
                errors.append("independent_project_not_verified:" + tile["image_id"])
            proof = row.get("project_identity_evidence", {})
            source = proof.get("evidence_ref")
            quote, project_name, identity_key = proof.get("quote"), proof.get("project_name"), proof.get("project_identity_key")
            if not all(isinstance(value, str) and value.strip() for value in (quote, project_name, identity_key)):
                errors.append("specific_project_source_fact_required:" + tile["image_id"])
                continue
            text = checked_file_ref(source).decode("utf-8")
            if quote not in text or project_name not in quote:
                errors.append("project_name_not_in_actual_source_quote:" + tile["image_id"])
            basis_source = tile["identity_basis"]["evidence_ref"]
            if any((ref["path"], ref["sha256"]) not in source_identities for ref in (source, basis_source)):
                errors.append("project_source_not_actually_reviewed:" + tile["image_id"])
            identities.append(identity_key.strip().casefold())
            proof_spans.append((source["sha256"], quote.strip()))
        if len(identities) != 10 or len(set(identities)) != 10:
            errors.append("ten_distinct_verified_project_identities_required")
        if len(proof_spans) != 10 or len(set(proof_spans)) != 10:
            errors.append("same_source_quote_cannot_prove_distinct_projects")
        synthetic = (board.get("dataset_mode") == "synthetic_fixture"
                     or review.get("review_kind") == "synthetic_fixture")
    except (KeyError, TypeError, ValueError, OSError) as error:
        errors.append("project_identity_review_missing_or_invalid:" + str(error))
        synthetic = board.get("dataset_mode") == "synthetic_fixture"
    return {"machine_contract_check": "valid" if not errors else "invalid", "errors": errors,
            "verified_independent_projects": not errors and not synthetic,
            "synthetic_fixture": synthetic, "new_source_review_performed": False,
            "new_model_calls": 0}


def evaluate_board(board_path: Path, review_path: Path, *, native_module: str | None = None,
                   native_arguments: dict | None = None, support_dir: Path | None = None,
                   budget_exhausted: bool = False) -> dict:
    """整板否决单图即阻断；替换/新裁片后须重放绑定该版本的独立板审。

    10 图/10 可证独立项目是本次硬门。预算耗尽仍未通过时记 unfinished；
    不能减少数量或一致性要求，也不把局部视觉结果写成全链或用户认可。
    """
    board = json.loads(Path(board_path).read_text(encoding="utf-8"))
    issues, gate, native = [], None, None
    tiles = board.get("tiles", [])
    quantity = len(tiles) == 10
    if not quantity:
        issues.append("requires_10_final_images")
    projects = []
    for tile in tiles:
        project_id = tile.get("source_project_id")
        basis = tile.get("identity_basis")
        if not project_id or not isinstance(basis, dict) or not basis.get("reason"):
            issues.append("independent_project_identity_unproven:" + str(tile.get("image_id")))
            continue
        try:
            identity_source = checked_file_ref(basis["evidence_ref"]).decode("utf-8")
            quote = basis.get("quote")
            if not isinstance(quote, str) or not quote.strip() or quote not in identity_source:
                raise ValueError("项目身份依据须逐字引用可核对来源，而非 URL/文件名猜测")
            projects.append(project_id)
        except (KeyError, ValueError, OSError) as error:
            issues.append("project_identity_evidence_invalid:" + str(error))
    identity_check = verify_project_identity(board)
    issues += identity_check["errors"]
    evidence = (len(projects) == 10 and len(set(projects)) == 10
                and identity_check["verified_independent_projects"])
    if not evidence:
        issues.append("requires_10_evidenced_independent_projects")
    try:
        support = support_dir or SUPPORT_DIR
        frozen_brief = checked_file_ref(board["brief_ref"], as_json=True)
        if any(frozen_brief.get("count_policy", {}).get(key) != 10 for key in ("target", "minimum", "maximum")):
            issues.append("frozen_board_policy_is_not_current_exactly_10")
        result = subprocess.run([sys.executable, "-B", str(support / "scripts/review_gate.py"),
                                 "--board", str(Path(board_path).resolve()), "--review", str(Path(review_path).resolve())],
                                capture_output=True, text=True, timeout=90, check=False)
        if result.returncode:
            raise ValueError(result.stderr[-3000:])
        gate = json.loads(result.stdout)
        issues += gate["provenance_and_quantity_issues"]
        if gate["provenance_and_quantity_issues"]:
            evidence = False
        if not gate["eligible_to_report_scoped_AI_or_human_visual_result"]:
            issues.append("independent_board_visual_result_not_accepted")
        if native_module not in ("id", "cmf", "alias-id", "alias-cmf", "future-id", "future-cmf") or native_arguments is None:
            issues.append("native_h2_gate_not_executed")
        else:
            grouping, request = native_arguments["grouping"], native_arguments["request"]
            if board.get("branch") not in ("ID", "CMF") or native_module.split("-")[-1] != board["branch"].lower():
                raise ValueError("native_module_branch_mismatch")
            if request["rendered_board_ref"] != board["rendered_board_ref"]:
                raise ValueError("native_board_pixels_differ_from_current_board")
            if grouping["prepared_snapshot"]["inputs"]["brief_ref"] != board["brief_ref"]:
                raise ValueError("native_brief_differs_from_current_board")
            native_tiles = {(t["image_ref"]["sha256"], t["actual_view_ref"]["sha256"]) for t in request["tiles"]}
            actual_tiles = {(t["original_ref"]["sha256"], t["view_ref"]["sha256"]) for t in tiles}
            if native_tiles != actual_tiles or len(request["tiles"]) != len(tiles):
                raise ValueError("native_members_differ_from_current_board")
            native = replay_native(native_module, "accept_board_review", native_arguments, support_dir=support)
            if native.get("dataset_mode") != "real" or native.get("visual_review_accepted") is not True:
                issues.append("native_h2_current_board_not_accepted")
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
        issues.append("board_contract_rejected:" + str(error))
    eligible = not issues
    return {"strategy_version": STRATEGY_VERSION,
            "status": "ready_for_user_feedback" if eligible else ("unfinished" if budget_exhausted else "blocked"),
            "eligible_to_report_visual_result": eligible, "blockers": issues,
            "dimensions": {"quantity": "pass" if quantity else "fail", "evidence": "pass" if evidence else "unknown",
                           "visual": gate["reported_visual_judgment"] if gate else "unknown",
                           "native_gate": "pass" if native and native.get("visual_review_accepted") else "not_accepted",
                           "semantic": "not_evaluated_here", "user_feedback": "not_confirmed"},
            "native_acceptance": native, "machine_contract_check": gate,
            "project_identity_check": identity_check,
            "new_visual_review_performed": False, "new_model_calls": 0,
            "whole_workflow_complete": False, "user_approved": False}


def record_revision(issue: dict, attempt: dict) -> dict:
    """同一问题最多三轮定点修订，不改 issue 名称循环、也不自动重发失败请求。"""
    if not issue.get("issue_id") or not issue.get("frozen_brief_ref"):
        raise ValueError("问题需稳定身份和原冻结标准")
    rounds = issue.get("revision_attempts", [])
    if len(rounds) >= 3:
        raise ValueError("同一问题已达三轮，必须方法变更或新决策")
    if attempt.get("frozen_brief_ref") != issue["frozen_brief_ref"]:
        raise ValueError("不能修改冻结标准来保留被否决成员")
    for key in ("previous_failure_ref", "changed_material_refs", "recheck_ref", "reason"):
        if not attempt.get(key):
            raise ValueError("定点修订需保留旧失败、实际改动和复验记录：" + key)
    return {**deepcopy(issue), "revision_attempts": deepcopy(rounds) + [deepcopy(attempt)],
            "automatic_failed_request_retry": False}
