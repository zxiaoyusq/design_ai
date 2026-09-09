"""失败回复的有界逐观察诊断；只生成修复提示，不修改、接收或保存模型结果。"""

from __future__ import annotations

from copy import deepcopy
import json

from contracts import EVIDENCE_FIELDS, default_extract_field, validate_response


MAX_ISSUES = 8
MAX_CHARACTERS = 4000


def _known_records(job):
    payload = job.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return None
    records, repeated = {}, set()
    for record in payload["records"]:
        if not isinstance(record, dict):
            continue
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        if identifier in records:
            repeated.add(identifier)
        records[identifier] = record
    return {identifier: record for identifier, record in records.items() if identifier not in repeated}


def _source_description(record, observation):
    """只透露字段名与字符数，不把来源内容或其中的指令注入重试提示。"""
    fields, kind = record.get("fields"), record.get("kind")
    if not isinstance(fields, dict) or not isinstance(kind, str) or kind not in EVIDENCE_FIELDS:
        return "未知", "未知"
    field = observation.get("field", default_extract_field(record))
    if not isinstance(field, str) or field not in EVIDENCE_FIELDS[kind]:
        return "无合法字段", "未知"
    source = fields.get(field)
    return field, str(len(source)) if isinstance(source, str) else "未知"


def build_feedback(job: dict, response: dict, primary_error: str) -> str:
    """保留主错误，并为完整 extract 回复附加最多 8 处观察诊断，总长不超过 4000 字符。

    临时单记录任务仅用于调用同一校验器定位错误，不会成为正式任务、覆盖状态或接收结果。
    无法诊断的输入直接返回原主错误；全局覆盖与未知记录问题仍以原严格校验为准。
    """
    if (not isinstance(job, dict) or job.get("stage") != "extract"
            or not isinstance(response, dict) or not isinstance(primary_error, str)
            or set(response) != {"job_id", "observations", "skipped"}
            or response.get("job_id") != job.get("id")
            or not isinstance(response.get("observations"), list)
            or not isinstance(response.get("skipped"), list)):
        return primary_error
    records = _known_records(job)
    if records is None:
        return primary_error
    # 非 extract 的安全回退始终保留原错误；可诊断回复的异常长主错误按明确预算截断。
    truncation = "\n（主错误过长，已按诊断字符预算截断。）"
    if len(primary_error) > MAX_CHARACTERS:
        return primary_error[:MAX_CHARACTERS - len(truncation)] + truncation
    details = []
    needs_quote_guidance = False
    for index, observation in enumerate(response["observations"]):
        if not isinstance(observation, dict):
            continue
        identifier = observation.get("record_id")
        if not isinstance(identifier, str) or identifier not in records:
            continue
        record = records[identifier]
        # 仅隔离当前观察，保留实际版本和限额；该 skipped=[] 只存在于诊断内存。
        temporary_job = {**{key: deepcopy(value) for key, value in job.items() if key != "payload"},
                         "payload": {"records": [deepcopy(record)]}}
        temporary_response = {
            "job_id": response["job_id"], "observations": [deepcopy(observation)], "skipped": [],
        }
        try:
            validate_response(temporary_job, temporary_response)
        except (ValueError, TypeError, KeyError) as exc:
            message = str(exc)
            # 只追加观察字段的问题，作业版本、限额、来源索引等全局问题不重复包装。
            if not message.startswith("observations[0]"):
                continue
            message = message.replace("observations[0]", f"observations[{index}]", 1)
            field, length = _source_description(record, observation)
            # JSON 引号将换行等控制字符显示为字面量，超长 ID 不挤占其他问题的预算。
            display_id = json.dumps(identifier, ensure_ascii=False)
            if len(display_id) > 180:
                display_id = display_id[:177] + "…\""
            details.append(f"- {message}；record_id={display_id}；field={field}；原文字符数={length}")
            needs_quote_guidance |= "连续原文" in message or "连续引用" in message or "超过 600" in message
            if len(details) >= MAX_ISSUES:
                break
    if not details:
        return primary_error
    header = "\n\n逐观察诊断（仅用于修复提示，最多列 8 处；不代表全局覆盖校验通过）：\n"
    guidance = (
        "\n引文须逐字连续引用所选原文字段，不改写、拼接或删减语义；全文不超过 600 字可省略 quote，由代码恢复全文。"
        "长文须显式选择不超过 600 字的连续引用并保留关键条件。"
    ) if needs_quote_guidance else ""
    text = primary_error
    available = MAX_CHARACTERS - len(text) - len(header) - len(guidance)
    selected = []
    for detail in details:
        if len(detail) + (1 if selected else 0) > available:
            break
        selected.append(detail)
        available -= len(detail) + (1 if len(selected) > 1 else 0)
    if selected:
        text += header + "\n".join(selected) + guidance
    return text
