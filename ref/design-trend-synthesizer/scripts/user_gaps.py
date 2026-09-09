"""编译用研多数人提及、但本轮趋势未覆盖的方向；语义核对由宿主完成，计数不交给模型。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from core import USER_KINDS, atomic_text, digest, encode, read, timestamp, write


HEADING = "## 用研多数人提及、但本轮趋势未覆盖的设计方向"
START = "<!-- user-research-gaps:start -->"
END = "<!-- user-research-gaps:end -->"


def scope_for_run(run, records):
    """正式运行使用全部有文本用户；部分预览只使用明示的已处理用户，不缩小为命中用户。"""
    path = run / "scope.json"
    scope = read(path) if path.exists() else {}
    all_users = {r["user_id"] for r in records.values() if r["kind"] in USER_KINDS and r.get("user_id")}
    users = set(scope.get("accepted_user_ids", all_users))
    if not users.issubset(all_users):
        raise ValueError("统计分母含输入中不存在的用户")
    return sorted(users)


def prepare_context(evidence, records, population):
    """仅作宽召回，未与趋势匹配的维度也保留；不能以关键词或维度缺失宣告语义缺口。"""
    grouped = defaultdict(list)
    for item in evidence.values():
        if item["kind"] in USER_KINDS and item.get("user_id") in population:
            for dimension in item["dimensions"]:
                grouped[dimension].append(item["id"])
    return {
        "snapshot": {"evidence_sha256": digest(evidence), "records_sha256": digest(records)},
        "population_user_ids": sorted(population), "population_count": len(population),
        "majority_rule": "unique_mentioned_users > population_count / 2",
        "trend_records": [{"id": rid, "fields": r["fields"]} for rid, r in records.items() if r["kind"] == "trend"],
        "recall": [{"dimension": d, "evidence_ids": ids,
                    "unique_mentioned_users": len({evidence[eid]["user_id"] for eid in ids})}
                   for d, ids in sorted(grouped.items())],
        "note": "维度人数只是召回线索。读取对应完整问答，语义归纳后写 findings；问题不作回答证据，提及不等于偏好。",
    }


def pending_section(population):
    return {"status": "pending_semantic_review", "population_count": len(population),
            "population_user_ids": sorted(population), "directions": [],
            "scope_note": "用研补充方向尚待语义核对，不用未入选文章或空列表冒充已完成筛查。"}


def compile_findings(findings, evidence, records, population, project_root):
    """严格核对引用与核查范围，再按去重人数发布；不把语义声明伪装成代码证明。"""
    from reporting import resolve_images
    expected = {"evidence_sha256": digest(evidence), "records_sha256": digest(records)}
    if findings.get("snapshot") != expected:
        raise ValueError("用研归纳的输入摘要不匹配，须回查当前文本")
    trend_ids = {rid for rid, r in records.items() if r["kind"] == "trend"}
    population = set(population)
    directions, excluded, seen = [], [], set()
    for item in findings["directions"]:
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("方向 ID 为空或重复")
        seen.add(identifier)
        for key in ("title", "summary"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"方向缺少 {key}")
        ids = item["evidence_ids"]
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
            raise ValueError("方向须引用不重复的已有用户证据")
        refs = []
        for eid in ids:
            e = evidence[eid]
            record = records[e["record_id"]]
            field = "ai_analysis" if record["kind"] == "user_qa" else "ai_index"
            source = record["fields"].get(field)
            if (e["kind"] not in USER_KINDS or e["kind"] != record["kind"]
                    or e.get("user_id") != record.get("user_id") or e.get("user_id") not in population
                    or e["field"] != field or not isinstance(source, str) or not e["quote"] or e["quote"] not in source):
                raise ValueError(f"不是当前分母内可逐字回查的用户回答证据：{eid}")
            refs.append({**e, "relation": "mention"})
        checks = item["trend_coverage"]
        checked_ids = [c["record_id"] for c in checks]
        if len(checked_ids) != len(set(checked_ids)) or set(checked_ids) != trend_ids:
            raise ValueError("必须核对本轮所有选中趋势，不能仅检查主卡使用的趋势")
        if any(c["status"] not in {"unmentioned", "mentioned", "uncertain"}
               or not isinstance(c["reason"], str) or not c["reason"].strip() for c in checks):
            raise ValueError("每条趋势须提供明确覆盖判断和理由")
        if not isinstance(item["boundaries"], list) or not all(isinstance(x, str) and x.strip() for x in item["boundaries"]):
            raise ValueError("方向边界须为文本列表")
        users = sorted({e["user_id"] for e in refs})
        reasons = []
        if len(users) * 2 <= len(population):
            reasons.append("已核对提及人数未超过本次统计分母的一半")
        if any(c["status"] != "unmentioned" for c in checks):
            reasons.append("本轮趋势已有提及或覆盖关系仍不确定")
        if reasons:
            excluded.append({"id": identifier, "reasons": reasons, "unique_mentioned_users": len(users)})
            continue
        directions.append({"id": identifier, "title": item["title"], "summary": item["summary"],
                           "boundaries": item["boundaries"], "evidence_ids": ids,
                           "mention_statistics": {"unique_mentioned_users": len(users), "user_ids": users,
                              "population_count": len(population), "mention_ratio": round(len(users) / len(population), 4),
                              "count_type": "verified_minimum_mentions", "majority": True,
                              "note": "至少这些用户明确提及此议题，含接受、拒绝与条件表达；不是共同偏好率或市场占比。"},
                           "source_evidence": refs, "image_refs": resolve_images(refs, records, project_root),
                           "trend_coverage": {"status": "unmentioned_in_selected_texts", "checks": checks,
                                              "method": "host_semantic_review", "scope": "仅本轮选中趋势文本，不代表市场空白"}})
    directions.sort(key=lambda x: (-x["mention_statistics"]["unique_mentioned_users"], x["id"]))
    return {"status": "reviewed", "population_count": len(population), "population_user_ids": sorted(population),
            "directions": directions, "excluded_findings": excluded, "snapshot": expected,
            "findings_sha256": digest(findings), "compiled_at": timestamp(), "semantic_review": findings.get("review"),
            "scope_note": "以用户回答为主体；仅收录去重提及人数超过本版分母一半、且全部选中趋势经语义核对未提及的方向。"}


def markdown(section):
    lines = [START, HEADING, "", section["scope_note"], ""]
    if not section["directions"]:
        lines.append("本版尚未确认符合上述条件的方向。")
    for item in section["directions"]:
        stats = item["mention_statistics"]
        lines += [f"### {item['title']}", "", item["summary"], "",
                  f"至少 **{stats['unique_mentioned_users']}/{stats['population_count']} 位用户（{stats['mention_ratio']:.1%}）**提及；包含不同态度，不代表相同偏好。", ""]
        lines.extend(f"- {text}" for text in item["boundaries"])
        lines += ["", "本轮选中趋势文本未提及这一具体设计议题；完整用户引用、统计口径和图片路径见 JSON。", ""]
    return "\n".join(lines + [END, ""])


def publish(run, findings):
    """补充正式产物，独立于模型队列；不会启动或改写暂停中的原运行。"""
    records, evidence = read(run / "records.json"), read(run / "evidence.json")
    document = read(run / "high_potential_trends.json")
    manifest = read(run / "manifest.json")
    population = scope_for_run(run, records)
    section = compile_findings(findings, evidence, records, population, Path(manifest["project_root"]).resolve())
    document["user_research_gaps"] = section
    document.pop("not_selected_trends", None)
    for card in document["trends"]:
        card.pop("validation_questions", None)
    report = (run / "report.md").read_text(encoding="utf-8")
    if START in report and END in report:
        before, tail = report.split(START, 1)
        _, after = tail.split(END, 1)
        report = before + markdown(section) + after.lstrip("\n")
    else:
        report += "\n" + markdown(section)
    write(run / "high_potential_trends.json", document)
    atomic_text(run / "high_potential_trends.jsonl", "".join(encode(c) + "\n" for c in document["trends"]))
    write(run / "user_research_gaps.json", section)
    atomic_text(run / "report.md", report)
    validation = read(run / "validation_report.json")
    validation["user_research_gaps"] = {"status": section["status"], "direction_count": len(section["directions"]),
                                       "findings_sha256": section["findings_sha256"]}
    images = [image for item in document["trends"] + section["directions"] for image in item.get("image_refs", [])]
    validation["image_reference_count"] = len(images)
    validation["missing_image_references"] = sum(not image["file_exists"] for image in images)
    write(run / "validation_report.json", validation)
    completion = read(run / "completion.json")
    completion["user_research_gaps_status"] = "reviewed"
    write(run / "completion.json", completion)
    return section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--batch-chars", type=int, default=16000)
    args = parser.parse_args()
    if args.action == "prepare":
        from contexts import evidence_batches
        from core import batches
        evidence, records = read(args.run / "evidence.json"), read(args.run / "records.json")
        population = scope_for_run(args.run, records)
        context = prepare_context(evidence, records, population)
        # 每条用户观察只进入一个包；按完整问答预算分批，避免一次要求模型复述整份用研。
        eligible = [e for e in evidence.values() if e["kind"] in USER_KINDS and e.get("user_id") in population]
        context["user_packet_files"] = []
        for i, packet in enumerate(evidence_batches(eligible, {}, records, 32, args.batch_chars)):
            name = f"user_gap_packets/users-{i:04d}.json"
            write(args.run / name, packet)
            context["user_packet_files"].append(name)
        context["trend_packet_files"] = []
        for i, packet in enumerate(batches(context.pop("trend_records"), 16, args.batch_chars)):
            name = f"user_gap_packets/trends-{i:04d}.json"
            write(args.run / name, packet)
            context["trend_packet_files"].append(name)
        write(args.run / "user_gap_context.json", context)
        print(encode({"context": str(args.run / "user_gap_context.json"), "population_count": context["population_count"]}))
    else:
        if not args.findings:
            parser.error("publish 需要 --findings")
        result = publish(args.run, read(args.findings))
        print(encode({"status": result["status"], "directions": len(result["directions"])}))


if __name__ == "__main__":
    main()
