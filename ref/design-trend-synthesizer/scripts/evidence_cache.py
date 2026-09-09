"""按用户原记录复用提取结果；文件路径、日期筛选和批次编号不参与内容键。"""

from __future__ import annotations

from pathlib import Path

from core import VERSION, digest, public_record, read, timestamp, write

# 2.2 只改最终成卡和用研补充，提取契约未变；保留 2.1 内容键，避免输出字段变动触发重复提取。
EXTRACTION_VERSION = "2.1.0"


def valid_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def record_key(record, profile):
    from contracts import instruction, response_template
    return digest({"version": EXTRACTION_VERSION, "record": public_record(record), "model_profile": profile,
                   "rules": instruction("extract"), "template": response_template("extract"),
                   "response_contract": "compact_extract_v1"})


def lookup(record, settings):
    """缓存只是候选回复；摘要和逐字引用均须重新校验，损坏条目回退到正常提取。"""
    from contracts import validate_response
    if not settings.get("enabled") or record["kind"] == "trend":
        return None, None
    key = record_key(record, settings["model_profile"])
    path = Path(settings["directory"]) / key[:2] / f"{key}.json"
    if not path.exists():
        return None, None
    try:
        entry = read(path)
        body = entry["entry"]
        if digest(body) != entry["sha256"] or body["key"] != key:
            raise ValueError("缓存内容摘要不一致")
        if body["record"] != public_record(record) or body["model_profile"] != settings["model_profile"]:
            raise ValueError("缓存输入或模型配置不一致")
        if not isinstance(body["origin"], dict) or not isinstance(body["origin"].get("model"), str) or not body["origin"]["model"].strip() or not body["origin"].get("request_sha256"):
            raise ValueError("缓存缺少原始调用来源")
        execution = body["origin"].get("execution", {})
        if not isinstance(execution, dict) or execution.get("model_profile") != settings["model_profile"] or not valid_hash(execution.get("messages_sha256")):
            raise ValueError("缓存缺少匹配的模型配置或有效消息摘要")
        job = {"id": "cache-check", "stage": "extract", "skill_version": VERSION,
               "payload": {"records": [public_record(record)]}, "limits": {"max_observations": 128}}
        response = {"job_id": job["id"], "skipped": body["skipped"], "observations": body["observations"]}
        validate_response(job, response)
        return body, None
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return None, {"record_id": record["id"], "cache_file": str(path), "reason": str(exc)}


def save_records(run, manifest, job, receipt):
    """只缓存调用方明确声明了相同模型配置的结果，不猜测参数或给未知模型建立缓存。"""
    settings = manifest.get("cache", {})
    execution = receipt.get("execution") or {}
    message_hash = execution.get("messages_sha256", "")
    if (job["stage"] != "extract" or not settings.get("enabled")
            or execution.get("model_profile") != settings.get("model_profile")
            or execution.get("cache_sources") or not valid_hash(message_hash)):
        return
    response = receipt["response"]
    for record in job["payload"]["records"]:
        if record["kind"] == "trend":
            continue
        key = record_key(record, settings["model_profile"])
        body = {"key": key, "record": public_record(record), "model_profile": settings["model_profile"],
                "skipped": [item for item in response["skipped"] if item["record_id"] == record["id"]],
                "observations": [o for o in response["observations"] if o["record_id"] == record["id"]],
                "origin": {"run_dir": str(run), **{name: receipt[name] for name in (
                    "job_id", "model", "prompt_version", "accepted_at", "request_sha256", "response_sha256", "receipt_sha256")},
                           "execution": execution}, "saved_at": timestamp()}
        path = Path(settings["directory"]) / key[:2] / f"{key}.json"
        # 首次有效结果稳定复用，后续同键调用不覆盖原始追溯。
        if path.exists():
            previous, _ = lookup(record, settings)
            if previous is not None:
                continue
        write(path, {"entry": body, "sha256": digest(body)})


def apply_cached(run, jobs):
    from workflow import receive
    for job, entries in jobs:
        response = {"job_id": job["id"],
                    "skipped": [item for entry in entries for item in entry["skipped"]],
                    "observations": [item for entry in entries for item in entry["observations"]]}
        response_path = Path(run) / "responses" / f"{job['id']}.json"
        write(response_path, response)
        profile = entries[0]["model_profile"]
        execution = {"model_profile": profile, "cache_sources": [
            {"record_id": entry["record"]["id"], "key": entry["key"], "origin": entry["origin"]}
            for entry in entries]}
        receive(run, job["id"], response_path, entries[0]["origin"]["model"], 0, 0, execution=execution)
