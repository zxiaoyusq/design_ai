"""把指定日期范围内的趋势与用户文本变成有来源索引的小任务。"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
from statistics import median
from uuid import uuid4

from core import (VERSION, build_job, digest, encode, extraction_payload, make_job,
                  public_record, read, release_date, request_message_chars, timestamp, write)
from contracts import image_code_in_text
from evidence_cache import apply_cached, lookup


def text_value(value):
    return value if isinstance(value, str) else encode(value)


def required_id(row):
    value = str(row.get("id", "")).strip()
    if not value or value == "None":
        raise ValueError("记录缺少 id")
    return value


def image_ref(row, root, source_id, code=None, emotion=None):
    local = row.get("local_path")
    if local:
        path = (root / local).resolve()
        if Path(local).is_absolute() or not path.is_relative_to(root.resolve()):
            raise ValueError(f"图片路径必须位于来源数据目录内：{local}")
    else:
        path = None
    return {"image_id": row.get("image_id", row.get("id")), "source_root": str(root.resolve()),
            "local_path": local, "source_record_id": source_id, "code": code,
            "emotion_tag": emotion, "status": row.get("status", "available" if local else "missing")}


def observation_weight(record, max_observations, cached=None):
    """只估计输出容量，不预判观点或筛除短回答；缓存按实际观察数计。"""
    if cached is not None:
        return len(cached[record["id"]]["observations"])
    from contracts import default_extract_field
    field = default_extract_field(record)
    length = len(record["fields"].get(field, ""))
    if record["kind"] == "trend":
        # 显式启用的既有视觉分析文字同样可能产生观察，不能只按短摘要预留输出容量。
        length += len(record["fields"].get("local_vl_info", ""))
    return min(max_observations, max(1, (length + 159) // 160))


def extraction_chars(records, max_observations):
    # 内容寻址 ID 长度固定；预览的 key 不影响实际请求字符数。
    job = build_job("extract", 0, extraction_payload(records), {"max_observations": max_observations})
    return request_message_chars(job)


def extraction_packs(records, max_records, max_chars, cached=None, max_observations=64):
    """按记录数、完整请求字符和预计观察数合批；任何来源都不截断或静默丢弃。"""
    result, current, cost = [], [], 0
    for record in records:
        weight = observation_weight(record, max_observations, cached)
        if weight > max_observations:
            raise ValueError(f"单记录 {record['id']} 的缓存观察数超过预算；增大 --extraction-observations")
        candidate = current + [record]
        if current and (len(current) >= max_records or cost + weight > max_observations
                        or extraction_chars(candidate, max_observations) > max_chars):
            result.append(current)
            current, cost = [], 0
        if not current and extraction_chars([record], max_observations) > max_chars:
            raise ValueError(f"单记录 {record['id']} 加上提示词和模板后超过字符预算；增大 --batch-chars，不截断原文")
        current.append(record)
        cost += weight
    if current:
        result.append(current)
    return result


def batch_preview(packs, hits, max_observations):
    """准备阶段提供可复核成本基线；字符统计不冒充模型实际 token 用量。"""
    rows = [{"records": len(pack), "message_chars": extraction_chars(pack, max_observations),
             "estimated_observations": sum(observation_weight(record, max_observations,
                                                               hits if pack[0]["id"] in hits else None)
                                           for record in pack),
             "cached": pack[0]["id"] in hits} for pack in packs]
    return {"measurement": "完整 system 和 user 消息正文的 Unicode 字符数；不是 token 数",
            "total_message_chars": sum(row["message_chars"] for row in rows),
            "model_message_chars": sum(row["message_chars"] for row in rows if not row["cached"]),
            "records_per_batch": {"median": median([row["records"] for row in rows]) if rows else 0,
                                  "max": max((row["records"] for row in rows), default=0)},
            "estimated_observations": {"total": sum(row["estimated_observations"] for row in rows),
                                       "max_per_batch": max((row["estimated_observations"] for row in rows), default=0),
                                       "limit_per_batch": max_observations},
            "batches": rows}


def prepare(args):
    """日期上下界包含当天；用户调研没有日期字段，因此仅筛趋势侧。"""
    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else None
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期")
    if args.batch_records < 1 or args.batch_chars < 1000 or not 1 <= args.max_trends <= 12:
        raise ValueError("batch-records 必须为正，batch-chars 至少 1000，max-trends 为 1–12")
    max_observations = getattr(args, "extraction_observations", 64)
    if type(max_observations) is not int or not 1 <= max_observations <= 128:
        raise ValueError("extraction-observations 必须为 1–128 的整数")
    trend_path, user_path = Path(args.trends).resolve(), Path(args.users).resolve()
    trend_bytes, user_bytes = trend_path.read_bytes(), user_path.read_bytes()
    import json
    trends, users = json.loads(trend_bytes), json.loads(user_bytes)
    records, seen, selected, excluded, undated = {}, set(), [], Counter(), 0

    def add(record):
        if record["id"] in records:
            raise ValueError(f"重复记录 ID：{record['id']}")
        records[record["id"]] = record

    for index, row in enumerate(trends["trends"]):
        identifier = required_id(row)
        if identifier in seen:
            raise ValueError(f"重复趋势 ID：{identifier}")
        seen.add(identifier)
        try:
            day = release_date(row.get("release_time"))
        except ValueError as exc:
            raise ValueError(f"趋势 {identifier} 的发布日期非法") from exc
        if day is None:
            undated += 1
            if args.undated == "exclude":
                excluded["undated"] += 1
                continue
        elif (start and day < start) or (end and day > end):
            excluded["outside_range"] += 1
            continue
        rid = f"trend:{identifier}"
        fields = {key: text_value(row[key]) for key in ("title_zh", "summary_zh", "primary_category", "subcategory", "tags")
                  if row.get(key) is not None}
        if args.include_vl_text and row.get("local_vl_info") is not None:
            fields["local_vl_info"] = text_value(row["local_vl_info"])
        add({"id": rid, "kind": "trend", "source_id": identifier, "fields": fields,
             "source_file": "trends", "json_pointer": f"/trends/{index}",
             "release_time": day.isoformat() if day else None,
             "image_refs": [image_ref(image, trend_path.parent, rid) for image in row.get("images", [])]})
        selected.append(rid)

    user_ids, text_users, skipped = set(), set(), 0
    for index, row in enumerate(users["users"]):
        uid = required_id(row)
        if uid in user_ids:
            raise ValueError(f"重复用户 ID：{uid}")
        user_ids.add(uid)
        preferences = {}
        for pref in row.get("image_preferences", []):
            code = pref.get("ref_pic_code")
            if code:
                preferences.setdefault(code, []).append(image_ref(pref, user_path.parent, f"user:{uid}", code, pref.get("emotion_tag")))
        for key, kind, fields_to_keep in (
            ("aesthetic_research", "user_qa", ("question", "ai_analysis", "answer_type", "scenario_type", "question_type")),
            ("demand_research", "user_demand", ("ai_index", "scenario", "ref_pic")),
        ):
            for child_index, child in enumerate(row.get(key, [])):
                cid = required_id(child)
                if kind == "user_qa" and "未提及" in text_value(child.get("ai_analysis")):
                    skipped += 1
                    continue
                rid = f"user:{uid}:{kind}:{cid}"
                fields = {name: text_value(child[name]) for name in fields_to_keep if child.get(name) is not None}
                images = []
                if kind == "user_demand":
                    for link in child.get("ref_pic_links", []):
                        if len(link.get("image_ids", [])) != len(link.get("local_paths", [])):
                            raise ValueError(f"需求 {rid} 的图片 ID 与路径数量不一致")
                        for image_id, local in zip(link.get("image_ids", []), link.get("local_paths", [])):
                            images.append(image_ref({"image_id": image_id, "local_path": local}, user_path.parent, rid, link.get("code")))
                else:
                    # 只索引回答中出现的编码，避免为每条问答重复复制整个人的图库。
                    analysis_text = fields.get("ai_analysis", "")
                    images = [ref for code, group in preferences.items() if image_code_in_text(code, analysis_text) for ref in group]
                add({"id": rid, "kind": kind, "source_id": cid, "user_id": uid,
                     "profile": row.get("profile", {}), "fields": fields,
                     "source_file": "users", "json_pointer": f"/users/{index}/{key}/{child_index}",
                     "image_refs": images})
                text_users.add(uid)
    for index, row in enumerate(users.get("unlinked_demand_research", [])):
        identifier = required_id(row)
        add({"id": f"orphan_demand:{identifier}", "kind": "orphan_demand", "source_id": identifier,
             "fields": {name: text_value(row[name]) for name in ("ai_index", "scenario", "ref_pic") if row.get(name) is not None},
             "source_file": "users", "json_pointer": f"/unlinked_demand_research/{index}", "image_refs": []})

    project_root = Path(args.project_root).resolve()
    parameters = json.loads(getattr(args, "model_parameters", "{}"))
    if not isinstance(parameters, dict):
        raise ValueError("model-parameters 必须为 JSON 对象")
    encode(parameters)
    model_name = getattr(args, "model", None)
    if model_name is not None and (not isinstance(model_name, str) or not model_name.strip()):
        raise ValueError("model 必须为非空模型标识")
    profile = {"model": model_name, "parameters": parameters} if model_name else None
    cache = {"enabled": bool(profile) and not getattr(args, "no_cache", False),
             "directory": str(Path(getattr(args, "cache_dir", None) or project_root / "data/result/high_trend/_cache").resolve()),
             "model_profile": profile}
    hits, invalid = {}, []
    if selected:
        for record in records.values():
            found, error = lookup(record, cache)
            if found is not None:
                hits[record["id"]] = found
            if error:
                invalid.append(error)
    # 不混批不同用户或不同实际模型；缓存命中与待调用记录分开，保持逐记录覆盖。
    partitions = {}
    for record in records.values():
        hit = hits.get(record["id"])
        key = ("trends" if record["kind"] == "trend" else record.get("user_id", "orphans"),
               hit["origin"]["model"] if hit else None)
        partitions.setdefault(key, []).append(public_record(record))
    packs = [pack for (_, cached_model), group in partitions.items()
             for pack in extraction_packs(group, args.batch_records, args.batch_chars,
                                          hits if cached_model else None, max_observations)] if selected else []
    # 默认结果跟随目标项目，不跟随 Skill 安装位置；时间和随机后缀隔离重复运行。
    if args.output is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
        run = project_root / "data" / "result" / "high_trend" / run_id
    else:
        run = Path(args.output).resolve()
    manifest = {
        "skill_version": VERSION, "created_at": timestamp(), "as_of": args.as_of or date.today().isoformat(),
        "project_root": str(project_root), "run_dir": str(run), "model_profile": profile, "cache": cache,
        "inputs": {"trends": {"path": str(trend_path), "sha256": hashlib.sha256(trend_bytes).hexdigest()},
                   "users": {"path": str(user_path), "sha256": hashlib.sha256(user_bytes).hexdigest()}},
        "selection": {"start_date": args.start_date, "end_date": args.end_date, "inclusive": True,
                      "undated_policy": args.undated, "undated_in_source": undated, "excluded": dict(excluded)},
        "counts": {"source_trends": len(trends["trends"]), "selected_trends": len(selected),
                   "users": len(user_ids), "users_with_text": len(text_users), "source_records": len(records),
                   "excluded_unmentioned_qa": skipped, "extraction_jobs": len(packs),
                   "cached_records": len(hits), "model_extraction_jobs": sum(pack[0]["id"] not in hits for pack in packs)},
        "settings": {"batch_records": args.batch_records, "batch_chars": args.batch_chars,
                     "extraction_observations": max_observations,
                     "max_trends": args.max_trends, "include_vl_text": args.include_vl_text},
        "extraction_batch_preview": batch_preview(packs, hits, max_observations),
        "scope_note": "用户文本不按日期过滤；未知日期即使纳入也不充当近期证据。",
    }
    date.fromisoformat(manifest["as_of"])
    if args.dry_run:
        return manifest
    if run.exists() and any(run.iterdir()):
        raise ValueError("输出目录非空；请用新的运行目录，或对现有目录执行 next/status 续跑")
    run.mkdir(parents=True, exist_ok=True)
    write(run / "records.json", records)
    manifest["records_sha256"] = digest(records)
    cached_jobs = []
    for index, pack in enumerate(packs):
        jid = make_job(run, "extract", index, extraction_payload(pack), {"max_observations": max_observations})
        if pack[0]["id"] in hits:
            cached_jobs.append((read(run / "jobs" / f"{jid}.json"), [hits[r["id"]] for r in pack]))
    write(run / "manifest.json", manifest)
    write(run / "cache_report.json", {"enabled": cache["enabled"], "hits": sorted(hits), "invalid_entries": invalid,
                                      "not_used_reason": None if cache["enabled"] else "未声明模型配置或显式关闭缓存"})
    apply_cached(run, cached_jobs)
    return manifest
