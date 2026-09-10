"""提取失败后的整记录复用与补齐编译；只计算结果，不调用模型或读写运行。"""

from __future__ import annotations

from copy import deepcopy

from contracts import validate_response
from core import digest
from normalization import NORMALIZATION_VERSION, normalize_response


def _records(job: dict) -> dict[str, dict]:
    if not isinstance(job, dict) or job.get("stage") != "extract":
        raise ValueError("逐记录修复仅适用于 extract 作业")
    payload = job.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("作业必须提供完整 payload.records")
    # 空记录校验仅核对作业版本、ID 与限额，不生成正式覆盖声明。
    validate_response({**job, "payload": {"records": []}}, {
        "job_id": job.get("id"), "observations": [], "skipped": [],
    })
    records = {}
    for record in payload["records"]:
        identifier = record.get("id") if isinstance(record, dict) else None
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 300:
            raise ValueError("原始记录必须具有合法 ID")
        if identifier in records:
            raise ValueError(f"原始记录 ID 重复：{identifier}")
        records[identifier] = record
    return records


def _group_response(response: dict, identifier: str) -> dict:
    """同一记录的全部观察和跳过声明始终一起移动，不能丢掉坏项来凑合法组。"""
    return {"job_id": response["job_id"], **{
        key: [deepcopy(item) for item in response[key] if item["record_id"] == identifier]
        for key in ("observations", "skipped")
    }}


def _check_envelope(job: dict, response: dict, records: dict[str, dict]) -> None:
    if not isinstance(response, dict) or set(response) != {"job_id", "observations", "skipped"}:
        raise ValueError("历史回复顶层结构不完整或包含未知字段")
    if response["job_id"] != job["id"]:
        raise ValueError("历史回复 job_id 与原作业不一致")
    for key in ("observations", "skipped"):
        if not isinstance(response[key], list):
            raise ValueError(f"历史回复 {key} 必须为数组")
        for index, item in enumerate(response[key]):
            identifier = item.get("record_id") if isinstance(item, dict) else None
            if not isinstance(identifier, str) or identifier not in records:
                # 无归属或未知来源不能分配到某组，整次尝试拒绝参与复用并返回诊断。
                raise ValueError(f"历史回复 {key}[{index}] 无法归属到原作业的已知记录")


def collect_reusable_records(job: dict, attempts: list[dict]) -> dict:
    """从按旧到新排列的 {response, provenance} 历史尝试选择最新完整合法记录组。

    返回 retained（按来源 ID 索引）、pending_records（完整原记录）与逐尝试/逐记录诊断。
    provenance 是宿主提供的非空对象，原样保留；本函数不会把外部文件哈希当作已核验事实。
    """
    records = _records(job)
    if not isinstance(attempts, list):
        raise ValueError("attempts 必须按时间从旧到新提供为数组")
    retained, diagnostics = {}, []
    for attempt_index, attempt in enumerate(attempts):
        provenance = attempt.get("provenance") if isinstance(attempt, dict) else None
        diagnostic = {"attempt_index": attempt_index, "provenance": deepcopy(provenance), "records": []}
        try:
            if not isinstance(attempt, dict) or not isinstance(provenance, dict) or not provenance:
                raise ValueError("每次历史尝试必须提供 response 与非空 provenance 对象")
            response = attempt.get("response")
            _check_envelope(job, response, records)
            # 摘要同时检验输入为可序列化的标准 JSON；不修复语法或未知对象。
            attempt_hash = digest(response)
            digest(provenance)
        except (ValueError, TypeError, KeyError) as error:
            diagnostic.update(status="rejected_attempt", error=str(error))
            diagnostics.append(diagnostic)
            continue
        diagnostic["status"] = "inspected"
        for identifier, record in records.items():
            original = _group_response(response, identifier)
            single_job = {**job, "payload": {"records": [record]}}
            normalized, changes = normalize_response(single_job, original)
            item = {"record_id": identifier, "observation_count": len(original["observations"]),
                    "skipped_count": len(original["skipped"]), "normalization_changes": changes}
            try:
                validate_response(single_job, normalized)
            except (ValueError, TypeError, KeyError) as error:
                item.update(status="missing" if not original["observations"] and not original["skipped"] else "invalid",
                            error=str(error))
            else:
                item["status"] = "valid"
                # 新的合法整组整体替换旧组；较新的失败不会清除旧的合法组。
                retained[identifier] = {
                    "record": deepcopy(record), "record_sha256": digest(record), "job_sha256": digest(job),
                    "response": deepcopy(normalized), "response_sha256": digest(normalized),
                    "original_response": deepcopy(original), "original_response_sha256": digest(original),
                    "attempt_response_sha256": attempt_hash, "provenance": deepcopy(provenance),
                    "normalization": {"version": NORMALIZATION_VERSION, "changes": deepcopy(changes)},
                }
            diagnostic["records"].append(item)
        diagnostics.append(diagnostic)
    return {"retained": retained, "pending_records": [deepcopy(record) for identifier, record in records.items() if identifier not in retained],
            "diagnostics": diagnostics, "counts": {"total": len(records), "retained": len(retained), "pending": len(records) - len(retained)}}


def _retained_response(job: dict, identifier: str, record: dict, entry: dict) -> dict:
    """重新校验保留组及原文绑定，避免把其他运行或修改过的片段编入原作业。"""
    if (not isinstance(entry, dict) or entry.get("record") != record
            or entry.get("record_sha256") != digest(record) or entry.get("job_sha256") != digest(job)):
        raise ValueError(f"保留组来源与原作业不一致：{identifier}")
    original, response = entry.get("original_response"), entry.get("response")
    if entry.get("original_response_sha256") != digest(original) or entry.get("response_sha256") != digest(response):
        raise ValueError(f"保留组或原始回复摘要不一致：{identifier}")
    single_job = {**job, "payload": {"records": [record]}}
    _check_envelope(single_job, original, {identifier: record})
    restored, changes = normalize_response(single_job, original)
    if restored != response or entry.get("normalization") != {"version": NORMALIZATION_VERSION, "changes": changes}:
        raise ValueError(f"保留组与原始回复的确定性整理结果不一致：{identifier}")
    validate_response(single_job, response)
    return response


def compile_response(job: dict, retained: dict, subset_job: dict | None = None, subset_response: dict | None = None) -> dict:
    """把保留整组与已经校验的补齐回复编译为原作业回复，并再次严格核对全量覆盖。

    补齐作业必须恰好包含尚未保留的原记录，字段、画像等完整内容不能改变。
    本函数不正规化补齐回复；宿主应先完成正常校验与追溯，再交给本函数重新验证。
    """
    records = _records(job)
    if not isinstance(retained, dict) or set(retained) - set(records):
        raise ValueError("retained 必须按原作业已知 record_id 索引")
    groups = {identifier: _retained_response(job, identifier, records[identifier], entry)
              for identifier, entry in retained.items()}
    pending = {identifier: record for identifier, record in records.items() if identifier not in groups}
    if pending:
        if subset_job is None or subset_response is None:
            raise ValueError(f"仍需补齐记录：{list(pending)}")
        subset_records = _records(subset_job)
        if subset_records != pending:
            raise ValueError("补齐作业必须恰好包含待补原记录，不能遗漏、重叠或修改来源")
        validate_response(subset_job, subset_response)
        _check_envelope(subset_job, subset_response, subset_records)
        for identifier in pending:
            groups[identifier] = _group_response(subset_response, identifier)
    elif subset_job is not None or subset_response is not None:
        raise ValueError("已无待补记录，不接受额外补齐作业或回复")
    result = {"job_id": job["id"], "observations": [], "skipped": []}
    for identifier in records:
        for key in ("observations", "skipped"):
            result[key].extend(deepcopy(groups[identifier][key]))
    # 单组和补齐作业通过，不代表合并后仍满足原任务的观察预算与全量覆盖。
    validate_response(job, result)
    return result
