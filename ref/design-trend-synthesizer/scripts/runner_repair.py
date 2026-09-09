"""提取失败时复用完整记录组，仅请求缺口；原始任务、模型回复和调用计数不改写。"""

from __future__ import annotations

from copy import deepcopy
import hashlib

import core
from contracts import validate_response


REPAIR_VERSION = "record_repair_v1"


def collect_plan(runner, job):
    """仅从同模型配置、同原任务的可核验实际尝试收集整记录结果。"""
    from json_repair import parse_model_json
    from record_repair import collect_reusable_records
    attempts = []
    source = core.read(runner.run / "requests" / f"{job['id']}.json")
    for folder in sorted((runner.root / "attempts" / job["id"]).glob("[0-9]*")):
        if not (folder / "outcome.json").exists():
            continue
        request, outcome = core.read(folder / "request.json"), core.read(folder / "outcome.json")
        if outcome.get("kind") not in {"validation", "valid"}:
            continue
        if (request.get("job_sha256") != core.digest(job)
                or request.get("request_sha256") != core.digest(source)
                or request.get("model_profile") != runner.profile
                or request.get("messages_sha256") != core.digest(request.get("messages"))):
            raise ValueError("逐记录复用的原始请求或模型配置摘要不一致")
        envelope = core.read(folder / "result.raw.json")
        if envelope.get("status") != "ok" or envelope.get("model_profile") != runner.profile:
            raise ValueError("逐记录复用缺少匹配的模型原始结果")
        raw = envelope.get("raw_response")
        if raw is None and isinstance(envelope.get("response"), dict):
            raw = core.encode(envelope["response"])
        try:
            parsed, syntax_changes = parse_model_json(raw)
        except (ValueError, TypeError):
            continue
        if envelope.get("response") is not None and envelope["response"] != parsed:
            continue
        # 补齐调用只能贡献其实际请求过的记录，不能把模型多写的别处记录纳入历史。
        effective = effective_job(runner, job, request)
        from extract_transport import TRANSPORT_VERSION, decode_response, record_aliases
        parsed, transport_changes = decode_response(effective, parsed)
        allowed = {record["id"] for record in effective["payload"]["records"]}
        if isinstance(parsed, dict):
            items = [item for key in ("observations", "skipped") if isinstance(parsed.get(key), list)
                     for item in parsed[key]]
            if any(isinstance(item, dict) and item.get("record_id") not in allowed for item in items):
                continue
        provenance = {"attempt_file": str((folder / "request.json").relative_to(runner.run)),
                      "request_sha256": core.digest(request), "messages_sha256": request["messages_sha256"],
                      "raw_result_file": str((folder / "result.raw.json").relative_to(runner.run)),
                      "raw_result_sha256": core.digest(envelope), "model": outcome.get("model"),
                      "raw_response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                      "model_profile": runner.profile, "started_at": request["started_at"],
                      "finished_at": outcome["finished_at"], "syntax_changes": syntax_changes,
                      "transport": {"version": TRANSPORT_VERSION, "changes": transport_changes,
                                    "aliases_sha256": core.digest(record_aliases(effective)),
                                    "decoded_response_sha256": core.digest(parsed)}}
        attempts.append({"response": parsed, "provenance": provenance})
    return collect_reusable_records(job, attempts)


def can_repair(runner, job):
    state = runner.job_state(job)
    return (job["stage"] == "extract" and runner.record_repair_rounds > 0
            and state.get("record_repair_rounds", 0) < runner.record_repair_rounds
            and state["transport_failures"] < 3
            and state["status"] in {"pending", "blocked"}
            and bool(state.get("last_validation_raw")))


def request_patch(runner, job):
    """返回原始记录子集的请求；服务重试复用已经冻结的同一请求，不消耗新补齐轮次。"""
    state = runner.job_state(job)
    if job["stage"] != "extract" or not state.get("last_validation_raw"):
        return None
    previous_path = state.get("last_outcome_file")
    if previous_path:
        previous = core.read(runner.run / previous_path)
        previous_request = core.read((runner.run / previous_path).parent / "request.json")
        if previous["kind"] in {"overload", "rate_limit", "timeout", "transport"}:
            if previous_request.get("record_repair"):
                return {"messages": previous_request["messages"],
                        "record_repair": previous_request["record_repair"]}
            return None
    if not can_repair(runner, job):
        return None
    plan = collect_plan(runner, job)
    # 全批没有合法记录时，不借此开启另一套整批重试额度。
    if not plan["retained"] or not plan["pending_records"]:
        return None
    remaining = job["limits"]["max_observations"] - sum(
        len(item["response"]["observations"]) for item in plan["retained"].values())
    if remaining < 1:
        return None
    subset = {**deepcopy(job), "payload": {"records": deepcopy(plan["pending_records"])},
              "limits": {**job["limits"], "max_observations": remaining}}
    from extract_transport import record_aliases
    subset["transport_aliases"] = deepcopy(job.get("transport_aliases", record_aliases(job)))
    validate_source_subset(job, subset)
    folder = runner.root / "record_repairs" / job["id"] / core.digest(plan)[:20]
    plan_path = folder / "plan.json"
    core.write(plan_path, plan)
    round_number = state.get("record_repair_rounds", 0) + 1
    return {"messages": core.build_request_messages(subset),
            "record_repair": {"version": REPAIR_VERSION, "round": round_number,
                              "plan_file": str(plan_path.relative_to(runner.run)), "plan_sha256": core.digest(plan),
                              "job": subset, "job_sha256": core.digest(subset),
                              "retained_records": len(plan["retained"]),
                              "requested_records": len(plan["pending_records"])}}


def validate_source_subset(job, subset):
    original = {record["id"]: record for record in job["payload"]["records"]}
    identifiers = [record["id"] for record in subset["payload"]["records"]]
    if (subset["id"] != job["id"] or subset["stage"] != "extract"
            or len(set(identifiers)) != len(identifiers)
            or any(original.get(record["id"]) != record for record in subset["payload"]["records"])):
        raise ValueError("补齐请求必须保留原任务 ID 和未改写的原记录子集")
    from extract_transport import record_aliases
    expected = {alias: rid for alias, rid in record_aliases(job).items() if rid in identifiers}
    if record_aliases(subset) != expected:
        raise ValueError("补齐请求不得改变原任务已冻结的短 ID 映射")


def effective_job(runner, job, request):
    repair = request.get("record_repair")
    if not repair:
        return job
    subset = repair["job"]
    validate_source_subset(job, subset)
    if repair["job_sha256"] != core.digest(subset) or request["messages"] != core.build_request_messages(subset):
        raise ValueError("补齐请求内容或模型消息已改变")
    return subset


def compile_subset(runner, job, request, subset_response, folder):
    from record_repair import compile_response
    repair = request["record_repair"]
    plan = core.read(runner.run / repair["plan_file"])
    if core.digest(plan) != repair["plan_sha256"]:
        raise ValueError("补齐计划摘要已改变")
    subset = effective_job(runner, job, request)
    response = compile_response(job, plan["retained"], subset, subset_response)
    core.write(folder / "subset_response.json", subset_response)
    trace = {"version": REPAIR_VERSION, "plan_file": repair["plan_file"], "plan_sha256": repair["plan_sha256"],
             "round": repair["round"], "retained_records": repair["retained_records"],
             "requested_records": repair["requested_records"],
             "subset_response_file": str((folder / "subset_response.json").relative_to(runner.run)),
             "subset_response_sha256": core.digest(subset_response), "compiled_response_sha256": core.digest(response),
             "source_records": {identifier: item["provenance"] for identifier, item in plan["retained"].items()}}
    return response, trace


def receive_compiled(runner, job, response_path, model, trace, last_call=None):
    """编译结果引用全部真实调用；无单次消息摘要，避免把多来源编译伪装成一次调用写缓存。"""
    execution = {"model_profile": runner.profile, "mode": "compiled_record_repair", "record_repair": trace,
                 "compiled_at": core.timestamp(), "usage_scope": "全部实际调用分别计入 runner attempts，不在编译凭证重复累加"}
    if last_call:
        execution["last_call"] = last_call
    runner.workflow.receive(runner.run, job["id"], response_path, model, None, None, execution=execution)
    runner.job_state(job)["status"] = "accepted"
    runner.job_state(job)["record_repair_receipt"] = str(response_path.relative_to(runner.run))
    runner.save()


def recover_records(runner, job):
    """历史整组已能覆盖时零调用编译；否则仅开放有界的缺口补齐，不重置历史失败数。"""
    from record_repair import compile_response
    state = runner.job_state(job)
    if job["stage"] != "extract" or state["status"] not in {"pending", "blocked"} or not state.get("last_validation_raw"):
        return
    plan = collect_plan(runner, job)
    if plan["retained"] and not plan["pending_records"]:
        try:
            response = compile_response(job, plan["retained"])
        except ValueError:
            return
        folder = runner.root / "record_repairs" / job["id"] / core.digest(plan)[:20]
        core.write(folder / "plan.json", plan)
        core.write(folder / "compiled_response.json", response)
        provenance = [item["provenance"] for item in plan["retained"].values()]
        trace = {"version": REPAIR_VERSION, "plan_file": str((folder / "plan.json").relative_to(runner.run)),
                 "plan_sha256": core.digest(plan), "additional_model_calls": 0,
                 "source_records": {identifier: item["provenance"] for identifier, item in plan["retained"].items()},
                 "compiled_response_sha256": core.digest(response)}
        receive_compiled(runner, job, folder / "compiled_response.json", provenance[-1]["model"], trace)
    elif (can_repair(runner, job) and plan["retained"] and state.get("last_outcome_file")
          and core.read(runner.run / state["last_outcome_file"])["kind"] == "validation"):
        state["status"] = "pending"
        runner.save()
