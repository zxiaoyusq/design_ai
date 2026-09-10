"""仅压缩提取任务的传输结构；原文、语义契约和正式来源 ID 保持不变。"""

from __future__ import annotations

from copy import deepcopy
import json

from contracts import default_extract_field


TRANSPORT_VERSION = "extract_table_v1"
RECORD_COLUMNS = ["id", "context", "answer"]
WIRE_INSTRUCTIONS = (
    "提取输入采用表格：records 每行按 record_columns 排列，context 是 contexts 的零基下标。"
    "contexts 每行按 context_columns 的[区域,字段名]排列：record 是记录信息，fields 是原字段，"
    "meta.answer_field 指定 answer 对应的原回答字段，meta.profile 是 profiles 的零基下标。"
    "context_missing 标记原本不存在的列，其他 null 均为原值；meta.fields_absent 表示原 fields 不存在。"
    "行缺少 answer 表示原字段不存在，null 表示原值为 null；不得用问题代替回答。"
    "画像只属于该项 user_id。"
    "输出 record_id 使用行中的短 ID；图片编码仍使用原文编码，绝不可当成记录 ID 转换。"
)


def _key(value):
    """用 JSON 类型和值共同去重，避免把用户 1 与用户 \"1\" 合并。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def record_aliases(job: dict) -> dict[str, str]:
    """按原记录顺序分配短 ID，并跳过所有可能与正式来源 ID 冲突的名字。"""
    if job.get("stage") != "extract":
        return {}
    identifiers = [record["id"] for record in job["payload"]["records"]]
    if any(not isinstance(value, str) or not value for value in identifiers):
        raise ValueError("提取来源 ID 必须为非空字符串")
    reserved = set(identifiers)
    if len(reserved) != len(identifiers):
        raise ValueError("提取来源 ID 重复，无法建立无歧义的传输映射")
    if "transport_aliases" in job:
        frozen = job["transport_aliases"]
        if (not isinstance(frozen, dict)
                or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                       for key, value in frozen.items())
                or len(set(frozen.values())) != len(frozen)
                or set(frozen) & (set(frozen.values()) | reserved)):
            raise ValueError("冻结的传输 ID 映射无效或与正式来源 ID 冲突")
        reverse = {value: key for key, value in frozen.items()}
        if not reserved.issubset(reverse):
            raise ValueError("冻结的传输 ID 映射未覆盖当前记录")
        return {reverse[identifier]: identifier for identifier in identifiers}
    aliases, number = {}, 1
    for identifier in identifiers:
        while f"r{number}" in reserved:
            number += 1
        aliases[f"r{number}"] = identifier
        number += 1
    return aliases


def _pack_contexts(contexts: list[dict]) -> tuple[list, list, dict]:
    """上下文字段名全批仅发送一次；单独记录缺失列，不能将缺失偷偷变成 null。"""
    columns, column_index, flattened = [], {}, []
    for context in contexts:
        values = {("record", key): value for key, value in context["record"].items() if key != "fields"}
        values.update({("fields", key): value for key, value in context["record"].get("fields", {}).items()})
        values[("meta", "answer_field")] = context["answer_field"]
        if "profile" in context:
            values[("meta", "profile")] = context["profile"]
        if "fields" not in context["record"]:
            values[("meta", "fields_absent")] = True
        for column in sorted(values):
            if column not in column_index:
                column_index[column] = len(columns)
                columns.append(column)
        flattened.append(values)
    rows, missing = [], {}
    for index, values in enumerate(flattened):
        rows.append([deepcopy(values.get(column)) for column in columns])
        absent = [index for index, column in enumerate(columns) if column not in values]
        if absent:
            missing[str(index)] = absent
    return [list(column) for column in columns], rows, missing


def _unpack_context(payload: dict, index: int) -> dict:
    missing = set(payload.get("context_missing", {}).get(str(index), []))
    record, metadata = {"fields": {}}, {}
    for position, (column, value) in enumerate(zip(payload["context_columns"], payload["contexts"][index], strict=True)):
        if position in missing:
            continue
        scope, name = column
        if scope == "record":
            record[name] = deepcopy(value)
        elif scope == "fields":
            record["fields"][name] = deepcopy(value)
        elif scope == "meta":
            metadata[name] = deepcopy(value)
        else:
            raise ValueError("未知上下文字段区域")
    if metadata.pop("fields_absent", False):
        del record["fields"]
    return {"record": record, **metadata}


def pack_job(job: dict) -> dict:
    """回答逐行保留，共享上下文和每用户画像只发送一次；不删改任何记录字段。"""
    if job.get("stage") != "extract":
        return deepcopy(job)
    contexts, context_index, profiles, profile_index, rows = [], {}, [], {}, []
    aliases = record_aliases(job)
    for alias, record in zip(aliases, job["payload"]["records"], strict=True):
        template = deepcopy(record)
        del template["id"]
        field = default_extract_field(record)
        context = {"record": template, "answer_field": field}
        fields = template.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError(f"记录 {record['id']} 的 fields 必须为对象")
        has_answer = field in fields
        answer = fields.pop(field) if has_answer else None

        if "profile" in template:
            if "user_id" not in template or template["user_id"] is None:
                raise ValueError(f"记录 {record['id']} 有画像但没有 user_id")
            profile = template.pop("profile")
            user_key = _key(template["user_id"])
            if user_key in profile_index:
                index = profile_index[user_key]
                if _key(profiles[index]["profile"]) != _key(profile):
                    raise ValueError(f"用户 {template['user_id']} 在同一任务中的画像不一致")
            else:
                index = len(profiles)
                profile_index[user_key] = index
                profiles.append({"user_id": deepcopy(template["user_id"]), "profile": profile})
            context["profile"] = index

        context_key = _key(context)
        if context_key not in context_index:
            context_index[context_key] = len(contexts)
            contexts.append(context)
        row = [alias, context_index[context_key]]
        if has_answer:
            row.append(answer)
        rows.append(row)

    columns, context_rows, missing = _pack_contexts(contexts)
    payload = {"record_columns": list(RECORD_COLUMNS), "records": rows,
               "context_columns": columns, "contexts": context_rows, "profiles": profiles}
    if missing:
        payload["context_missing"] = missing
    # 非 records 的附加输入独立存放，避免与压缩格式的 contexts 等保留名冲突。
    extra = {key: deepcopy(value) for key, value in job["payload"].items() if key != "records"}
    if extra:
        payload["extra"] = extra
    return {"id": job["id"], "stage": job["stage"], "limits": deepcopy(job.get("limits", {})),
            "transport_version": TRANSPORT_VERSION, "payload": payload}


def unpack_job(wire_job: dict) -> dict:
    """恢复供离线核对/假适配器使用的常规视图；记录 ID 仍是模型实际看到的短 ID。"""
    if "transport_version" not in wire_job:
        return deepcopy(wire_job)
    if wire_job["transport_version"] != TRANSPORT_VERSION:
        raise ValueError("未知提取传输版本")
    payload = wire_job["payload"]
    if payload["record_columns"] != RECORD_COLUMNS:
        raise ValueError("提取传输列定义不匹配")
    records = []
    for row in payload["records"]:
        if not isinstance(row, list) or len(row) not in {2, 3}:
            raise ValueError("提取传输行必须包含 ID、上下文下标及可选回答")
        context = _unpack_context(payload, row[1])
        record = deepcopy(context["record"])
        record["id"] = row[0]
        if len(row) == 3:
            record.setdefault("fields", {})[context["answer_field"]] = deepcopy(row[2])
        if "profile" in context:
            profile = payload["profiles"][context["profile"]]
            if _key(record.get("user_id")) != _key(profile["user_id"]):
                raise ValueError("画像归属与当前记录的用户不一致")
            record["profile"] = deepcopy(profile["profile"])
        records.append(record)
    result_payload = deepcopy(payload.get("extra", {}))
    result_payload["records"] = records
    return {"id": wire_job["id"], "stage": wire_job["stage"],
            "limits": deepcopy(wire_job["limits"]), "payload": result_payload}


def decode_response(job: dict, response) -> tuple[object, list[dict]]:
    """只还原已知短来源 ID；局部坏项原样保留，交后续严格校验和整记录复用处理。"""
    decoded, changes = deepcopy(response), []
    if job.get("stage") != "extract" or not isinstance(decoded, dict):
        return decoded, changes
    aliases = record_aliases(job)
    for collection in ("observations", "skipped"):
        items = decoded.get(collection)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            identifier = item.get("record_id")
            if not isinstance(identifier, str) or identifier not in aliases:
                continue
            original = aliases[identifier]
            item["record_id"] = original
            changes.append({"index": index, "field": f"{collection}.record_id", "record_id": original,
                            "before": identifier, "after": original,
                            "reason": "根据当前任务的确定性映射还原短来源 ID，不修改图片编码或证据文本"})
    return decoded, changes
