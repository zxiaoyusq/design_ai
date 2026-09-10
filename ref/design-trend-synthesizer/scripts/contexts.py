"""按任务去重源记录并计算完整文本预算，避免同一长回答随多条观察重复发送。"""

from core import encode, public_evidence, public_record


def attach_sources(payload, records):
    evidence = payload.get("evidence", [])
    sources = {rid: public_record(records[rid]) for rid in sorted({item["record_id"] for item in evidence})}
    profiles = {}
    for record in sources.values():
        if "profile" in record:
            uid = record.get("user_id")
            if uid is None or (uid in profiles and profiles[uid] != record["profile"]):
                raise ValueError("源上下文的用户画像缺少归属或互相冲突")
            profiles[uid] = record.pop("profile")
    # 全文按来源去重，画像按用户去重；二者通过 user_id 连接，不牺牲短回答的提问语境。
    return {**payload, "source_records": sources, "profiles": profiles}


def evidence_batches(items, base, records, max_records, max_chars):
    result, batch = [], []
    for item in items:
        trial = attach_sources({**base, "evidence": batch + [public_evidence(item)]}, records)
        if batch and (len(batch) >= max_records or len(encode(trial)) > max_chars):
            result.append(attach_sources({**base, "evidence": batch}, records))
            batch = []
            trial = attach_sources({**base, "evidence": [public_evidence(item)]}, records)
        if len(encode(trial)) > max_chars:
            raise ValueError(f"单条证据及完整源上下文 {item['id']} 超过字符预算；增加 --batch-chars，不截断原文")
        batch.append(public_evidence(item))
    if batch:
        result.append(attach_sources({**base, "evidence": batch}, records))
    return result
