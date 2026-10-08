"""有界主趋势收敛：只负责证据冻结和结构验收，绝不自动做语义分类。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pipeline as p

VERSION = "3.1.0"
REASONS = {"single_source", "weak_support", "outside_top_trends", "redundant_detail", "ambiguous"}
THEME_KEYS = ("cluster_id", "title", "definition", "design_question", "dimensions", "boundaries", "hypotheses", "unknowns")


def unique(rows, key):
    """索引前拒绝重复，避免字典覆盖掩盖证据丢失。"""
    p.need(isinstance(rows, list), f"{key} 集合必须是数组")
    result = {}
    for row in rows:
        p.need(isinstance(row, dict), f"{key} 行必须是对象")
        value = p.string(row.get(key), key)
        p.need(value not in result, f"{key} 重复：{value}")
        result[value] = row
    return result


def limits_from(document):
    limits = document.get("point_interpretation_limits", {}) if isinstance(document, dict) else {}
    p.need(isinstance(limits, dict), "point_interpretation_limits 必须是 point_id 映射")
    return limits


def indexes(catalogue, points, coverage):
    articles = unique(catalogue["articles"], "source_id")
    evidence = unique(catalogue["evidence"], "evidence_id")
    by_point = unique(points, "point_id")
    by_source = unique(coverage, "source_id")
    p.need(set(by_source) == set(articles), "coverage 必须恰好覆盖全部文章")
    for row in evidence.values():
        p.need(row.get("source_id") in articles, "证据指向未知文章")
        p.need(row.get("field") in p.TEXT_FIELDS, "证据只允许标题与摘要")
        p.string(row.get("text"), "evidence.text")
        for key in ("source_group_id", "claim_origin_id"):
            p.string(row.get(key), key)
            p.need(row[key] == articles[row["source_id"]].get(key), f"证据与文章 {key} 不一致")
    cited = set()
    for point in points:
        for key in ("subject", "feature", "reason", "seed_id"):
            p.string(point.get(key), key)
        p.need(point.get("dimension") in p.DIMENSIONS, "要点 dimension 无效")
        p.need("condition" in point and (point["condition"] is None or isinstance(point["condition"], str) and bool(point["condition"].strip())), "condition 必须明确或 null")
        eid = point.get("evidence_id")
        p.need(eid in evidence, f"未知证据：{eid}")
        p.need(p.string(point.get("quote"), "quote") in evidence[eid]["text"], f"非精确引文：{eid}")
        cited.add(evidence[eid]["source_id"])
    for sid, row in by_source.items():
        status = row.get("extraction_status", row.get("status"))
        p.need(status in p.STATUSES, "原提取状态无效")
        p.need((status == "clustered") == (sid in cited), f"提取状态与要点不一致：{sid}")
        p.string(row.get("reason"), "coverage.reason")
        p.strings(row.get("residuals"), "coverage.residuals")
    return articles, evidence, by_point


def support(members, evidence):
    eids = sorted({m["evidence_id"] for m in members})
    result = {"evidence_refs": eids}
    for dest, source in (("source_ids", "source_id"), ("source_group_ids", "source_group_id"), ("claim_origin_ids", "claim_origin_id")):
        result[dest] = sorted({evidence[eid][source] for eid in eids})
    result["source_group_count"] = len(result["source_group_ids"])
    result["source_article_count"] = len(result["source_ids"])
    return result


def prepare(out, *, from_final=None, from_run=None, max_trends=100, min_source_groups=3, max_chars=28000, corrections=None):
    """全部 seed 均进入摘要包；单例不得在人工跨包归并之前被预筛掉。"""
    out = Path(out)
    p.need(bool(from_final) != bool(from_run), "必须且只能选择一个输入")
    p.need(type(max_trends) is int and 1 <= max_trends <= 100, "max-trends 必须为 1..100")
    p.need(type(min_source_groups) is int and min_source_groups >= 2, "min-source-groups 必须 >=2")
    p.need(max_chars > 0, "max-chars 必须为正")
    p.need(not out.exists(), "输出目录已存在，请另选目录")
    input_hashes = {}
    carried_limits = {}
    if from_final:
        source = Path(from_final)
        names = ("trend-clusters.json", "trend-catalogue.json", "coverage.json", "execution.json")
        values = {name: p.read(source / name) for name in names}
        input_hashes = {name: p.digest(source / name) for name in names}
        old = values["trend-clusters.json"]
        p.need(old.get("schema_version") == "prism.trends.semantic_clusters.v0.1", "不支持的最终格式")
        catalogue, coverage, prior = values["trend-catalogue.json"], values["coverage.json"], values["execution.json"]
        raw_seeds = old["clusters"]
        for document in (prior, old):
            carried_limits.update(limits_from(document))
        prior_corrections = source / "corrections.json"
        if prior_corrections.exists():
            input_hashes["corrections.json"] = p.digest(prior_corrections)
            carried_limits.update(limits_from(p.read(prior_corrections)))
        # 若上轮产物已经包含证据池，也必须继续携带，不能在再次收敛时丢点。
        pool_path = source / "evidence-pool.json"
        if pool_path.exists():
            pool = p.read(pool_path)
            input_hashes["evidence-pool.json"] = p.digest(pool_path)
            p.need(not pool.get("points"), "该 final 已做过收敛且含证据池，请改用原始 final 或首轮 run")
    else:
        source = Path(from_run)
        manifest, catalogue, collection = p.gather(source)
        raw_seeds, coverage = collection["candidates"], collection["coverage"]
        prior = {"manifest": manifest, "batch_analyses": collection["analyses"], "accepted_sha256": collection["accepted_sha256"]}
        input_hashes = {"manifest.json": p.digest(source / "manifest.json"), "catalogue.json": p.digest(source / "catalogue.json"),
                        **{f"batches/{bid}/accepted.json": digest for bid, digest in collection["accepted_sha256"].items()}}
    correction_document = p.read(corrections) if corrections else None
    if corrections:
        input_hashes["corrections_input"] = p.digest(corrections)
        carried_limits.update(limits_from(correction_document))
    seeds, points = [], []
    unique(raw_seeds, "cluster_id")
    for raw in raw_seeds:
        p.validate_theme(raw)
        seed_id = raw["cluster_id"]
        members = [m for child in raw.get("lineage", []) for m in child["members"]] if from_final else raw["members"]
        p.need(bool(members), f"seed 无要点：{seed_id}")
        seed = {key: raw[key] for key in THEME_KEYS}
        seed.update(seed_id=seed_id, point_ids=[m["point_id"] for m in members])
        if from_final:
            seed["prior_lineage"] = raw["lineage"]
        for member in members:
            point = {**member, "seed_id": seed_id}
            if "effective_feature" in member:
                point["original_feature"] = member.get("original_feature", member["feature"])
            limit = carried_limits.get(member["point_id"])
            if limit:
                p.need(isinstance(limit, dict), "修正必须是对象")
                point["original_feature"] = member.get("original_feature", member["feature"])
                for key in ("effective_feature", "rejected_inference"):
                    point[key] = p.string(limit.get(key), key)
            if "effective_feature" in point:
                # 下游通常直接读取 feature；将有效解释作为规范值，旧判断仅留审计字段。
                point["feature"] = p.string(point["effective_feature"], "effective_feature")
            points.append(point)
        seeds.append(seed)
    _, evidence, by_point = indexes(catalogue, points, coverage)
    article_ids = {row["source_id"] for row in catalogue["articles"]}
    for raw in raw_seeds:
        if "source_ids" in raw:
            p.need(set(p.strings(raw["source_ids"], "seed.source_ids")) <= article_ids, "seed 引用未知 source_id")
    p.need(set(carried_limits) <= set(by_point), "修正引用未知 point_id")
    for seed in seeds:
        seed.update(support([by_point[pid] for pid in seed["point_ids"]], evidence))
    prompt_path = p.SKILL / "references" / "selection.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    summaries = []
    for seed in seeds:
        # 这是显式的摘要视图，不截断某一字段；大边界整项留在冻结 seeds 供定点回查。
        bounds = seed["boundaries"]
        compact_bounds = bounds if len(p.dump(bounds)) <= 2000 else {"shared_design_mechanism": bounds["shared_design_mechanism"]}
        examples = p.representative_points([by_point[pid] for pid in seed["point_ids"]], evidence, limit=2)
        summaries.append({"seed_id": seed["seed_id"], "title": seed["title"], "definition": seed["definition"], "boundaries": compact_bounds,
                          "boundaries_abbreviated": compact_bounds != bounds, "full_boundaries_ref": f"seeds.json#{seed['seed_id']}",
                          "unknowns": seed["unknowns"], "point_count": len(seed["point_ids"]), "source_group_count": seed["source_group_count"],
                          "source_article_count": seed["source_article_count"],
                          "example_points": [{k: v for k, v in m.items() if k != "context"} for m in examples],
                          "interpretation_limits": [{"point_id": pid, "original_feature": by_point[pid].get("original_feature", by_point[pid]["feature"]),
                                                     "effective_feature": by_point[pid]["effective_feature"], "rejected_inference": by_point[pid].get("rejected_inference")}
                                                    for pid in seed["point_ids"] if "effective_feature" in by_point[pid]],
                          "full_points_ref": "points.json", "full_context_ref": "catalogue.json"})
    groups = p.pack(summaries, prompt, "seeds", max_chars)
    packets = []
    for number, group in enumerate(groups, 1):
        messages = p.packet(prompt, group, "seeds")
        packets.append({"packet_id": f"S{number:04d}", "seed_ids": [s["seed_id"] for s in group], "messages": messages,
                        "characters": sum(len(m["content"]) for m in messages)})
    # 所有结构和预算检查先通过，再创建新目录，绝不覆盖历史产物。
    out.mkdir(parents=True)
    documents = {"catalogue.json": catalogue, "points.json": points, "seeds.json": seeds, "coverage-input.json": coverage,
                 "prior-execution.json": prior, "selection-prompt.json": {"system": prompt},
                 "selection-packets.json": {"packet_count": len(packets), "input_characters": sum(x["characters"] for x in packets), "packets": packets}}
    if correction_document is not None or carried_limits:
        documents["corrections.json"] = {**(correction_document or {}), "point_interpretation_limits": carried_limits}
    for name, value in documents.items():
        p.write(out / name, value)
    manifest = {"version": VERSION, "created_at": p.now(), "input_kind": "final" if from_final else "run", "input_path": str(source.resolve()),
                "input_sha256": input_hashes, "engine_sha256": p.digest(__file__), "pipeline_sha256": p.digest(p.__file__),
                "max_trends": max_trends, "min_source_groups": min_source_groups, "max_chars": max_chars,
                "point_count": len(points), "seed_count": len(seeds), "frozen": {name: p.digest(out / name) for name in documents}}
    p.write(out / "manifest.json", manifest)
    return {"seeds": len(seeds), "points": len(points), "packets": len(packets), "selection_manifest_sha256": p.digest(out / "manifest.json")}


def load(run):
    run = Path(run)
    manifest = p.read(run / "manifest.json")
    p.need(manifest.get("version") == VERSION and manifest.get("engine_sha256") == p.digest(__file__) and manifest.get("pipeline_sha256") == p.digest(p.__file__), "运行脚本绑定已变化")
    p.need(1 <= manifest["max_trends"] <= 100 and manifest["min_source_groups"] >= 2, "运行阈值无效")
    required = {"catalogue.json", "points.json", "seeds.json", "coverage-input.json", "prior-execution.json", "selection-prompt.json", "selection-packets.json"}
    p.need(required <= set(manifest["frozen"]), "冻结清单不完整")
    for name, digest in manifest["frozen"].items():
        p.need(Path(name).name == name, "冻结文件名不合法")
        p.need(p.digest(run / name) == digest, f"冻结输入被修改：{name}")
    catalogue, points, seeds, coverage = [p.read(run / name) for name in ("catalogue.json", "points.json", "seeds.json", "coverage-input.json")]
    indexes(catalogue, points, coverage)
    return manifest, catalogue, points, seeds, coverage


def check(run, plan_path):
    """主趋势与降权证据池必须显式、互斥、完整覆盖输入点集。"""
    manifest, catalogue, points, seeds, coverage = load(run)
    plan = p.read(plan_path)
    p.need(plan.get("selection_manifest_sha256") == p.digest(Path(run) / "manifest.json"), "plan 与冻结输入不匹配")
    p.validate_analysis(plan.get("analysis"))
    themes = plan.get("clusters")
    p.need(isinstance(themes, list) and len(themes) <= manifest["max_trends"], "主趋势超过上限或 clusters 非数组；请先语义归并再筛选")
    unique(themes, "cluster_id")
    evidence = unique(catalogue["evidence"], "evidence_id")
    by_point, by_seed = unique(points, "point_id"), unique(seeds, "seed_id")
    used, clusters, deferred = set(), [], []

    def consume(ids):
        selected = p.strings(ids, "point_ids", nonempty=True)
        p.need(set(selected) <= set(by_point) and not used.intersection(selected), "未知或重复使用的 point_id")
        used.update(selected)
        return [by_point[pid] for pid in selected]

    for theme in themes:
        p.validate_theme(theme)
        p.strings(theme.get("variations"), "variations")
        members = consume(theme.get("point_ids"))
        refs = support(members, evidence)
        p.need(refs["source_group_count"] >= manifest["min_source_groups"] and refs["source_article_count"] >= manifest["min_source_groups"], f"主趋势支持不足：{theme['cluster_id']}")
        lineage = []
        for seed_id in sorted({m["seed_id"] for m in members}):
            selected = [m for m in members if m["seed_id"] == seed_id]
            # 上轮完整 seed 单独冻结；当前 lineage 只保留本趋势实际消费的点。
            lineage.append({**{k: v for k, v in by_seed[seed_id].items() if k not in {"prior_lineage", "point_ids", "evidence_refs", "source_ids", "source_group_ids", "claim_origin_ids", "source_group_count", "source_article_count"}},
                            "point_ids": [m["point_id"] for m in selected], "members": selected})
        compiled = {**{key: theme[key] for key in THEME_KEYS}, "variations": theme["variations"], "point_ids": sorted(m["point_id"] for m in members),
                    "lineage": lineage, **refs, "signal_type": "multi_source_theme",
                    "route_relevance": {"ID": bool(set(theme["dimensions"]) & {"form", "composition", "detail", "style", "atmosphere"}),
                                        "CMF": bool(set(theme["dimensions"]) & {"color", "material_expression", "surface", "detail", "style", "atmosphere"})}}
        clusters.append(compiled)
    p.need(isinstance(plan.get("deferred_points"), list), "deferred_points 必须显式提供")
    for row in plan["deferred_points"]:
        p.need(row.get("reason_code") in REASONS, "降权 reason_code 无效")
        p.string(row.get("reason"), "降权理由")
        for member in consume(row.get("point_ids")):
            deferred.append({**member, "reason_code": row["reason_code"], "deferred_reason": row["reason"]})
    p.need(used == set(by_point), "plan 遗漏要点，不允许默认未入选")
    clusters.sort(key=lambda c: (-c["source_group_count"], -c["source_article_count"], c["cluster_id"]))
    return manifest, catalogue, points, seeds, coverage, plan, clusters, deferred


def finalize(run, plan_path, out):
    out, run = Path(out), Path(run)
    p.need(not out.exists(), "输出目录已存在，请另选目录")
    manifest, catalogue, points, seeds, original_coverage, plan, clusters, deferred = check(run, plan_path)
    evidence = unique(catalogue["evidence"], "evidence_id")
    selected = {pid: c["cluster_id"] for c in clusters for pid in c["point_ids"]}
    deferred_by_id = {m["point_id"]: m for m in deferred}
    coverage = []
    for row in original_coverage:
        sid = row["source_id"]
        cids = [c["cluster_id"] for c in clusters if sid in c["source_ids"]]
        extraction = row.get("extraction_status", row["status"])
        coverage.append({**row, "extraction_status": extraction, "status": "clustered" if cids else "evidence_only" if extraction == "clustered" else extraction,
                         "cluster_ids": cids, "deferred_point_ids": [m["point_id"] for m in deferred if evidence[m["evidence_id"]]["source_id"] == sid]})
    dispositions = [{"point_id": m["point_id"], "seed_id": m["seed_id"], "source_id": evidence[m["evidence_id"]]["source_id"],
                     **({"status": "selected", "cluster_id": selected[m["point_id"]]} if m["point_id"] in selected else
                        {"status": "deferred", "reason_code": deferred_by_id[m["point_id"]]["reason_code"], "reason": deferred_by_id[m["point_id"]]["deferred_reason"]})} for m in points]
    flags = {"semantic_coverage": "model_assessed", "visual_analysis_performed": False, "review_status": "pending_human_review"}
    summary = {"articles": len(coverage), "input_seeds": len(seeds), "input_points": len(points), "main_trends": len(clusters),
               "selected_points": len(selected), "deferred_points": len(deferred), "max_trends": manifest["max_trends"], "min_source_groups": manifest["min_source_groups"],
               "selection_manifest_sha256": p.digest(run / "manifest.json"), "input_sha256": manifest["input_sha256"], **flags}
    execution = {"version": VERSION, "compiled_at": p.now(), "manifest": manifest, "selection_manifest_sha256": summary["selection_manifest_sha256"],
                 "proposal_sha256": p.digest(plan_path), "prior_execution": p.read(run / "prior-execution.json"), "selection_analysis": plan["analysis"], **flags}
    out.mkdir(parents=True)
    documents = {"trend-clusters.json": {"schema_version": "prism.trends.semantic_clusters.v0.1", "clusters": clusters, **flags},
                 "trend-catalogue.json": catalogue, "coverage.json": coverage, "evidence-pool.json": {"points": deferred, **flags},
                 "point-dispositions.json": dispositions, "summary.json": summary, "execution.json": execution, "seeds.json": seeds}
    if (run / "corrections.json").exists():
        documents["corrections.json"] = p.read(run / "corrections.json")
    for name, value in documents.items():
        p.write(out / name, value)
    (out / "proposal.json").write_bytes(Path(plan_path).read_bytes())
    report = ["# 多来源共同审美趋势", "", f"文章 {len(coverage)}；主趋势 {len(clusters)}；入选要点 {len(selected)}；证据池要点 {len(deferred)}。",
              "仅文本归纳，待人工确认；来源支持数不代表热度、置信度或独立事实验证。证据池不列入主趋势正文。", ""]
    for cluster in clusters:
        report.extend([f"## {cluster['cluster_id']} · {cluster['title']}", "", cluster["definition"],
                       f"来源组 {cluster['source_group_count']}；文章 {cluster['source_article_count']}", f"设计问题：{cluster['design_question']}",
                       f"机制：{cluster['boundaries']['shared_design_mechanism']}", f"纳入：{'；'.join(cluster['boundaries']['includes'])}",
                       f"排除：{'；'.join(cluster['boundaries']['excludes'])}", f"实施差异：{'；'.join(cluster['variations'])}",
                       f"假设：{'；'.join(cluster['hypotheses'])}", f"未知：{'；'.join(cluster['unknowns'])}", ""])
        members = [m for child in cluster["lineage"] for m in child["members"]]
        for member in p.representative_points(members, evidence, limit=3):
            report.append(f"- {member['evidence_id']}：{member['quote']}（条件：{member['condition']}；解释：{member.get('effective_feature', member['feature'])}）")
        report.append("")
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    origin = prep.add_mutually_exclusive_group(required=True)
    origin.add_argument("--from-final", type=Path)
    origin.add_argument("--from-run", type=Path)
    prep.add_argument("--out", required=True, type=Path)
    prep.add_argument("--max-trends", type=int, default=100)
    prep.add_argument("--min-source-groups", type=int, default=3)
    prep.add_argument("--max-chars", type=int, default=28000)
    prep.add_argument("--corrections", type=Path)
    for name in ("check", "finalize"):
        command = sub.add_parser(name)
        command.add_argument("--run", required=True, type=Path)
        command.add_argument("--plan", required=True, type=Path)
        if name == "finalize":
            command.add_argument("--out", required=True, type=Path)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "prepare":
        result = prepare(**args)
    else:
        args["plan_path"] = args.pop("plan")
        if command == "check":
            *_, clusters, deferred = check(**args)
            result = {"valid": True, "main_trends": len(clusters), "deferred_points": len(deferred)}
        else:
            result = finalize(**args)
    print(p.dump(result))


if __name__ == "__main__":
    main()
