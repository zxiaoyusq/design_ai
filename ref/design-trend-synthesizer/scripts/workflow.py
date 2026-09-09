"""有限任务队列：提取、主题、候选核对、分轮合并、完整反证与单卡审核。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import hashlib
from pathlib import Path

from core import (VERSION, USER_KINDS, accepted, batches, digest, encode, load_jobs, make_job,
                  public_evidence, read, timestamp, write)
from contexts import attach_sources, evidence_batches
from discovery import materialize_themes, propose_jobs, screen_jobs, theme_jobs


def load_run(run):
    run = Path(run).resolve()
    manifest, records = read(run / "manifest.json"), read(run / "records.json")
    if manifest.get("skill_version") != VERSION:
        raise ValueError(f"运行版本 {manifest.get('skill_version')} 与当前 Skill {VERSION} 不一致；使用原版本续跑或创建新运行，不能混用契约")
    if digest(records) != manifest["records_sha256"]:
        raise ValueError("运行的原始文本索引已改变，不能与已有模型回复混用")
    return run, manifest, records


def normalize_with_trace(job, response):
    """只整理可机械核实的元数据；保留原始对象摘要，不把程序整理伪称为模型回复。"""
    from normalization import NORMALIZATION_VERSION, normalize_response
    from extract_transport import TRANSPORT_VERSION, decode_response, record_aliases
    decoded, transport_changes = decode_response(job, response)
    normalized, changes = normalize_response(job, decoded)
    trace = {"version": NORMALIZATION_VERSION, "changes": changes,
             "original_response_sha256": digest(response), "normalized_response_sha256": digest(normalized)} if changes or transport_changes else None
    if transport_changes:
        trace["transport"] = {"version": TRANSPORT_VERSION, "changes": transport_changes,
                              "aliases_sha256": digest(record_aliases(job)), "decoded_response_sha256": digest(decoded)}
    return normalized, trace


def receive(run, job_id, response_path, model, input_tokens=None, output_tokens=None, execution=None):
    """接收宿主提供的完整回复，先校验再写入；无效结果不会推进任务。"""
    from contracts import validate_response
    run, manifest, _ = load_run(run)
    jobs = {job["id"]: job for job in load_jobs(run)}
    if job_id not in jobs:
        raise ValueError("未知任务 ID")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("必须记录实际调用的模型名")
    if execution is not None and not isinstance(execution, dict):
        raise ValueError("execution 必须为对象")
    for value in (input_tokens, output_tokens):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("token 数必须为非负整数或空值")
    from json_repair import JSON_REPAIR_VERSION, parse_model_json
    original_text = Path(response_path).read_text(encoding="utf-8")
    original, syntax_changes = parse_model_json(original_text)
    job = jobs[job_id]
    response, normalization = normalize_with_trace(job, original)
    validate_response(job, response)
    previous = accepted(run, job)
    if previous:
        if previous["response_sha256"] == digest(response) and previous["model"] == model:
            return {"status": "already_accepted", "job_id": job_id}
        raise ValueError("此任务已经接收另一份结果；请使用新运行，不覆盖原始追溯")
    request = read(run / "requests" / f"{job_id}.json")
    if request["job_sha256"] != digest(job):
        raise ValueError("模型请求与任务内容不一致")
    execution = dict(execution or {})
    if syntax_changes:
        from core import atomic_text
        raw_path = run / "responses" / f"{job_id}-{digest(original_text)[:20]}.raw.txt"
        atomic_text(raw_path, original_text)
        execution["json_syntax"] = {"version": JSON_REPAIR_VERSION, "changes": syntax_changes,
                                    "original_raw_file": str(raw_path.relative_to(run)),
                                    "original_raw_sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(), "parsed_sha256": digest(original)}
    if normalization:
        execution["normalization"] = normalization
    result = {"job_id": job_id, "job_sha256": digest(job), "response_sha256": digest(response),
              "request_sha256": digest(request), "model": model, "accepted_at": timestamp(),
              "prompt_version": job["prompt_version"], "input_tokens": input_tokens,
              "output_tokens": output_tokens, "response": response, "execution": execution}
    if normalization:
        result["original_response"] = original
    result["receipt_sha256"] = digest(result)
    write(run / "accepted" / f"{job_id}.json", result)
    from evidence_cache import save_records
    save_records(run, manifest, job, result)
    return {"status": "accepted", "job_id": job_id}


def status(run, limit=5):
    run, manifest, _ = load_run(run)
    counts, pending, done = Counter(), [], Counter()
    for job in load_jobs(run):
        counts[job["stage"]] += 1
        if accepted(run, job):
            done[job["stage"]] += 1
        else:
            pending.append({"job_id": job["id"], "stage": job["stage"],
                            "request_file": str(run / "requests" / f"{job['id']}.json")})
    completion = read(run / "completion.json") if (run / "completion.json").is_file() else {}
    return {"run_dir": str(run), "selection": manifest["selection"], "counts": manifest["counts"],
            "jobs": dict(counts), "accepted": dict(done), "pending_count": len(pending),
            "pending": pending[:limit], "complete": bool(completion),
            "user_research_gaps_status": completion.get("user_research_gaps_status", "pending_semantic_review"),
            "deliverable_complete": bool(completion) and completion.get("user_research_gaps_status") == "reviewed"}


def stage_results(run, stage):
    from contracts import normalize_extract
    # 消费已校验的回复；代码整理有独立追溯，全文、默认字段和覆盖记录仍从来源恢复。
    results = [(job, accepted(run, job)["response"]) for job in load_jobs(run) if job["stage"] == stage]
    return [(job, normalize_extract(job, response)) for job, response in results] if stage == "extract" else results


def split_job(run, job_id):
    """过大输出只拆未接收任务，保留父请求和替代关系供追溯。"""
    run, _, records = load_run(run)
    jobs = {job["id"]: job for job in load_jobs(run)}
    if job_id not in jobs:
        raise ValueError("未知或已被拆分的任务")
    job = jobs[job_id]
    if accepted(run, job):
        raise ValueError("已接收任务不能拆分")
    payload = job["payload"]
    if job["stage"] in {"extract", "theme", "audit"}:
        key = "records" if job["stage"] == "extract" else "evidence"
        items = payload[key]
        middle = len(items) // 2
        if not middle:
            raise ValueError("只剩一个记录，不能继续拆分；保持上下文并缩短模型输出")
        children = [{**payload, key: half} for half in (items[:middle], items[middle:])]
        if "source_records" in payload:
            children = [attach_sources(child, records) for child in children]
    elif job["stage"] == "propose":
        left = [e for e in payload["evidence"] if e["kind"] == "trend"]
        right = [e for e in payload["evidence"] if e["kind"] != "trend"]
        fixed, divided = (left, right) if len(right) >= len(left) else (right, left)
        middle = len(divided) // 2
        if not middle:
            raise ValueError("两侧各只剩一条证据，无法继续拆分")
        children = []
        for half in (divided[:middle], divided[middle:]):
            child = {**payload, "evidence": fixed + half}
            allowed = {e["id"] for e in child["evidence"]}
            child["user_themes"] = [{**t, "representative_evidence_ids": [eid for eid in t["representative_evidence_ids"] if eid in allowed]}
                                    for t in payload.get("user_themes", [])
                                    if allowed.intersection(t["representative_evidence_ids"])]
            children.append(attach_sources(child, records))
    else:
        raise ValueError("此阶段已使用候选索引或单卡输出，请修正回复而非拆断设计命题")
    child_ids = [make_job(run, job["stage"], [job_id, i], child, job["limits"]) for i, child in enumerate(children)]
    marker = run / "superseded.json"
    superseded = read(marker) if marker.exists() else {}
    superseded[job_id] = child_ids
    write(marker, superseded)
    return {"superseded": job_id, "children": child_ids}


def build_evidence(extracted_results, records, manifest):
    """从已校验的提取结果纯计算证据索引；预览可显式传入已完成子集，不冒充全量覆盖。"""
    from contracts import image_code_in_text
    evidence = {}
    for job, response in extracted_results:
        for observation in response["observations"]:
            record = records[observation["record_id"]]
            # 图片路径不进模型。编码由当前来源和实际引文匹配，未判定的对象角色保持 unclear。
            codes = set(observation["image_codes"]) | {
                ref["code"] for ref in record.get("image_refs", [])
                if ref.get("code") and image_code_in_text(ref["code"], observation["quote"])
            }
            observation = {**observation, "image_codes": sorted(codes),
                           "image_roles": {code: observation["image_roles"].get(code, "unclear") for code in sorted(codes)}}
            identifier = "e-" + digest(observation)[:24]
            field = observation["field"].replace("~", "~0").replace("/", "~1")
            evidence[identifier] = {**observation, "id": identifier, "kind": record["kind"],
                                    "user_id": record.get("user_id"), "source_id": record["source_id"],
                                    "release_time": record.get("release_time"),
                                    "json_pointer": record["json_pointer"] + "/" + field,
                                    "source_file": manifest["inputs"][record["source_file"]]["path"],
                                    "source_sha256": manifest["inputs"][record["source_file"]]["sha256"]}
    return evidence


def materialize_evidence(run, records, manifest):
    evidence = build_evidence(stage_results(run, "extract"), records, manifest)
    write(run / "evidence.json", evidence)
    return evidence


def candidate_from(title, thesis, dimensions, evidence_ids, parents):
    item = {"title": title, "thesis": thesis, "dimensions": sorted(set(dimensions)),
            "evidence_ids": sorted(set(evidence_ids)), "parent_ids": sorted(set(parents))}
    return {"id": "c-" + digest(item)[:24], **item}


def candidate_summary(item, evidence):
    refs = [evidence[eid] for eid in item["evidence_ids"]]
    return {key: item[key] for key in ("id", "title", "thesis", "dimensions")} | {
        "trend_record_count": len({e["record_id"] for e in refs if e["kind"] == "trend"}),
        "user_count": len({e["user_id"] for e in refs if e["kind"] in USER_KINDS}),
        "evidence_count": len(refs),
    }


def statistics(candidate, assessments, evidence, as_of):
    """人数按实际用户去重；条目数不伪称独立项目数，不生成偏好率。"""
    relevant = [evidence[eid] for eid, value in assessments.items() if value["relation"] != "unrelated"]
    relations = defaultdict(set)
    trend_ids, recent, dated = set(), set(), []
    for item in relevant:
        relation = assessments[item["id"]]["relation"]
        if item["kind"] in USER_KINDS:
            relations[item["user_id"]].add(relation)
        if item["kind"] == "trend" and relation in {"support", "conditional"}:
            trend_ids.add(item["record_id"])
            if item.get("release_time"):
                day = date.fromisoformat(item["release_time"])
                dated.append(day.isoformat())
                if 0 <= (date.fromisoformat(as_of) - day).days <= 730:
                    recent.add(item["record_id"])
    grouped = {key: [] for key in ("support", "counter", "mixed", "conditional_only")}
    for uid, values in sorted(relations.items()):
        if "counter" in values and values.intersection({"support", "conditional"}):
            category = "mixed"
        elif "counter" in values:
            category = "counter"
        elif "support" in values:
            category = "support"
        else:
            category = "conditional_only"
        grouped[category].append(uid)
    return {"user_ids_by_relation": grouped, "user_counts": {k: len(v) for k, v in grouped.items()},
            "users_with_relevant_evidence": len(relations), "trend_record_count": len(trend_ids),
            "recent_trend_record_count": len(recent), "date_min": min(dated) if dated else None,
            "date_max": max(dated) if dated else None, "recent_window_days": 730,
            "independent_project_count": None, "population_preference_rate": None,
            "scope_note": "人数仅描述本资料集；同一项目报道独立性未核实，用户来源品类不能直接泛化。"}


def draft_context(candidate, assessments, evidence, as_of, records=None, max_chars=16000):
    selected = []
    # 为支持、条件与反证分别预留位置；优先不同用户和不同趋势条目。
    for relation, cap in (("support", 14), ("conditional", 6), ("counter", 8)):
        pool = [evidence[eid] for eid, a in assessments.items() if a["relation"] == relation]
        pool.sort(key=lambda e: (e["kind"] == "trend" or e["kind"] in USER_KINDS,
                                 e.get("release_time") or "", e["id"]), reverse=True)
        seen, unique, extra = set(), [], []
        for item in pool:
            key = item.get("user_id") or item["record_id"]
            if key in seen:
                extra.append(item)
            else:
                unique.append(item)
                seen.add(key)
        # 趋势和用户都优先有席位，避免文本密集的一侧占满代表证据。
        chosen = []
        for kind in ("trend", "user"):
            matches = [e for e in unique if (e["kind"] == "trend") == (kind == "trend")]
            chosen.extend(matches[:max(1, cap // 2)])
        used = {e["id"] for e in chosen}
        chosen += [e for e in unique + extra if e["id"] not in used][:max(0, cap - len(chosen))]
        selected.extend({**public_evidence(e), "relation": relation,
                         "assessment_reason": assessments[e["id"]]["reason"]} for e in chosen[:cap])
    context = {"candidate": candidate_summary(candidate, evidence), "evidence": [],
               "statistics": statistics(candidate, assessments, evidence, as_of),
               "evidence_scope": "候选设计维度内的全部证据已分批审核；此处提供分立场的代表证据及完整源字段。"}
    # 固定保留双侧支撑及至少一个反证，再按立场轮换补充，防止长上下文挤掉反例。
    required = []
    for predicate in (
        lambda e: e["kind"] == "trend" and e["relation"] in {"support", "conditional"},
        lambda e: e["kind"] in USER_KINDS and e["relation"] in {"support", "conditional"},
        lambda e: e["relation"] == "counter",
    ):
        match = next((item for item in selected if predicate(item)), None)
        if match is not None and match not in required:
            required.append(match)
    context["evidence"] = required
    if records is not None:
        context = attach_sources(context, records)
    if len(encode(context)) > max_chars:
        raise ValueError("单卡必要的双侧证据与原上下文超过字符预算；请在新运行中增大 --batch-chars，不截断原文")
    queues = [[item for item in selected if item["relation"] == relation and item not in required]
              for relation in ("counter", "conditional", "support")]
    while any(queues):
        for queue in queues:
            if queue:
                item = queue.pop(0)
                proposal = {**context, "evidence": context["evidence"] + [item]}
                if records is not None:
                    proposal = attach_sources(proposal, records)
                if len(encode(proposal)) <= max_chars:
                    context = proposal
    return context


def advance(run, limit=5):
    """只有当前任务全部接收后才生成下一阶段；可重复调用进行断点续跑。"""
    run, manifest, records = load_run(run)
    snapshot = status(run, limit)
    if snapshot["pending_count"] or snapshot["complete"]:
        return snapshot
    settings = manifest["settings"]
    state_path = run / "state.json"
    state = read(state_path) if state_path.exists() else {}
    evidence = materialize_evidence(run, records, manifest)
    if "theme_jobs" not in state:
        state["theme_jobs"] = theme_jobs(run, evidence, settings, records)
        write(state_path, state)
        if state["theme_jobs"]:
            return status(run, limit)
    themes = materialize_themes(stage_results(run, "theme"))
    write(run / "themes.json", themes)
    if "propose_jobs" not in state:
        state["propose_jobs"] = propose_jobs(run, evidence, themes, records, settings)
        write(state_path, state)
        if state["propose_jobs"]:
            return status(run, limit)
    if "proposed_candidates" not in state:
        candidates = []
        for job, response in stage_results(run, "propose"):
            for index, item in enumerate(response["candidates"]):
                candidates.append({**item, **candidate_from(item["title"], item["thesis"], item["dimensions"],
                                                 item["evidence_ids"], [f"{job['id']}:{index}"])})
        state["proposed_candidates"] = candidates
        write(state_path, state)
    if "screen_jobs" not in state:
        state["screen_jobs"] = screen_jobs(run, state["proposed_candidates"], evidence, records, settings)
        write(state_path, state)
        if state["screen_jobs"]:
            return status(run, limit)
    if "candidates" not in state:
        decisions = {entry["candidate_id"]: entry for _, response in stage_results(run, "screen") for entry in response["decisions"]}
        state["candidates"] = [c for c in state["proposed_candidates"] if decisions[c["id"]]["decision"] == "accept"]
        state["screen_rejected"] = [entry for entry in decisions.values() if entry["decision"] == "reject"]
        state["merge_round"] = 0
        write(state_path, state)

    if state.get("active_merge_jobs"):
        by_id = {item["id"]: item for item in state["candidates"]}
        merged = []
        for job in load_jobs(run):
            if job["id"] not in state["active_merge_jobs"]:
                continue
            for group in accepted(run, job)["response"]["groups"]:
                parents = [by_id[cid] for cid in group["candidate_ids"]]
                merged.append(candidate_from(group["title"], group["thesis"],
                                             [d for p in parents for d in p["dimensions"]],
                                             [eid for p in parents for eid in p["evidence_ids"]], group["candidate_ids"]))
        state["candidates"] = merged
        state["merge_round"] += 1
        state["active_merge_jobs"] = []
        write(state_path, state)

    current = state["candidates"]
    if current and (state["merge_round"] == 0 or len(current) > settings["max_trends"]):
        summaries = [candidate_summary(item, evidence) for item in sorted(current, key=lambda c: (c["dimensions"], c["title"], c["id"]))]
        groups = batches(summaries, 2 * settings["max_trends"], settings["batch_chars"])
        # 每轮有多批时，每批最多保留一半，保证有界收敛；被暂缓者及理由保留在原回复。
        state["active_merge_jobs"] = [make_job(run, "merge", [state["merge_round"], index],
                                               {"candidates": group},
                                               {"max_groups": min(settings["max_trends"], max(1, len(group) // 2)) if len(groups) > 1 else settings["max_trends"]})
                                      for index, group in enumerate(groups)]
        write(state_path, state)
        return status(run, limit)

    if "audit_jobs" not in state:
        state["audit_jobs"] = []
        for candidate in current:
            related = [e for e in evidence.values()
                       if set(e["dimensions"]).intersection(candidate["dimensions"]) or e["id"] in candidate["evidence_ids"]]
            for index, pack in enumerate(evidence_batches(related, {"candidate": candidate_summary(candidate, evidence)},
                                                         records, 24, settings["batch_chars"])):
                state["audit_jobs"].append(make_job(run, "audit", [candidate["id"], index],
                                                   pack))
        write(state_path, state)
        if state["audit_jobs"]:
            return status(run, limit)

    assessments = defaultdict(dict)
    for job, response in stage_results(run, "audit"):
        cid = job["payload"]["candidate"]["id"]
        assessments[cid].update({a["evidence_id"]: a for a in response["assessments"]})
    write(run / "assessments.json", dict(assessments))
    if "draft_jobs" not in state:
        state["draft_jobs"], state["insufficient_candidates"] = [], []
        for candidate in current:
            context = draft_context(candidate, assessments[candidate["id"]], evidence, manifest["as_of"], records, settings["batch_chars"])
            supported = [e for e in context["evidence"] if e["relation"] in {"support", "conditional"}]
            if not any(e["kind"] == "trend" for e in supported) or not any(e["kind"] in USER_KINDS for e in supported):
                state["insufficient_candidates"].append({"id": candidate["id"], "reason": "反证检查后缺少双侧有效支持"})
                continue
            state["draft_jobs"].append(make_job(run, "draft", candidate["id"], context))
        write(state_path, state)
        if state["draft_jobs"]:
            return status(run, limit)
    if "review_jobs" not in state:
        state["review_jobs"] = [make_job(run, "review", job["id"], {**job["payload"], "card": result["card"]})
                                for job, result in stage_results(run, "draft")]
        write(state_path, state)
        if state["review_jobs"]:
            return status(run, limit)
    from reporting import finalize
    finalize(run, manifest, records, evidence, current, assessments, state)
    return status(run, limit)
