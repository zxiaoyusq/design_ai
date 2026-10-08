#!/usr/bin/env python3
"""H01 本地契约适配、冻结、取证和发布；语义判断由获授权的宿主完成。"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import trend_assets

SKILL = Path(__file__).resolve().parents[1]
VERSION = "1.2.0-local"
PROPOSAL = "prism.local.h01.proposal.v1"
MODES = {
    "consensus": {"direct_support"},
    "extension": {"direct_support", "anchored_extension"},
    "exploration": {"direct_support", "anchored_extension", "exploratory_hypothesis"},
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    """生成物默认拒绝覆盖，重跑或修正使用新的运行目录。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def index(rows, key):
    need(isinstance(rows, list), f"{key}: 必须为列表")
    result = {}
    for row in rows:
        value = row[key]
        need(isinstance(value, str) and value and value not in result, f"重复或无效 ID: {value}")
        result[value] = row
    return result


def ids(values, allowed, label, nonempty=False):
    need(isinstance(values, list) and all(isinstance(v, str) for v in values), f"{label}: 必须为字符串列表")
    need(len(values) == len(set(values)), f"{label}: 重复 ID")
    need(set(values) <= set(allowed), f"{label}: 未知 ID {set(values) - set(allowed)}")
    need(not nonempty or values, f"{label}: 不得为空")
    return set(values)


def text(value, label):
    need(isinstance(value, str) and value.strip(), f"{label}: 需要非空说明")


def texts(value, label):
    need(isinstance(value, list), f"{label}: 需要字符串列表")
    for item in value:
        text(item, label)


def pick(row, keys):
    return {k: deepcopy(row[k]) for k in keys if k in row}


def prepare(config_path, root, out):
    """从两份已完成聚类建立可回溯快照，不重新推断聚类或读取图片。"""
    root, out = Path(root).resolve(), Path(out).resolve()
    need(not out.exists(), f"运行目录已存在: {out}")
    config = read(config_path)
    mode = config.get("mode", "extension")
    need(mode in MODES, "未知握手模式")
    minimum = config.get("min_trend_source_groups", 2)
    need(type(minimum) is int and minimum >= 1, "min_trend_source_groups 必须为正整数")
    text(config.get("brief"), "brief")
    research = (root / config["research_final"]).resolve()
    trend = (root / config["trend_final"]).resolve()
    paths = {"research-handshake": research / "handshake.json"}
    handshake = read(paths["research-handshake"])
    need(handshake["schema_version"] == "user_research_design_handshake.v1", "不支持的用研契约")
    need(handshake.get("ready_for_handshake") is True and handshake.get("coverage_status") == "complete", "用研尚未就绪或覆盖不完整")
    for role, field in [("research-sources", "sources_file"), ("research-observations", "observations_file"), ("research-result", "full_result_file")]:
        paths[role] = (research / handshake[field]).resolve()
    paths.update({"trend-clusters": trend / "trend-clusters.json", "trend-catalogue": trend / "trend-catalogue.json"})
    # 局部边界与执行记录有独立价值，缺少时显式留缺口，不从另一轮运行补齐。
    optional = {"trend-proposal": trend / "proposal.json", "trend-execution": trend / "execution.json"}
    paths.update({k: p for k, p in optional.items() if p.is_file()})
    raw = {k: read(p) for k, p in paths.items()}
    full = raw["research-result"]
    need(full.get("status") == "completed", "用研结果尚未完成")
    need(full["directions"] == handshake["directions"], "用研握手方向与完整结果不一致")
    for key in ("research-sources", "research-observations", "research-result"):
        need(raw[key]["input_sha256"] == handshake["input_sha256"], "用研上游 input_sha256 不一致")
    tc = raw["trend-clusters"]
    need(tc["schema_version"] == "prism.trends.semantic_clusters.v0.1", "不支持的趋势聚类契约")
    catalogue = raw["trend-catalogue"]
    need(catalogue["schema_version"] == "prism.trends.text_catalogue.v1", "不支持的趋势证据契约")
    observations = index(raw["research-observations"]["observations"], "id")
    sources = index(raw["research-sources"]["records"], "source_id")
    users = index(raw["research-sources"]["users"], "id")
    research_clusters = index(handshake["directions"], "id")
    trend_clusters = index(tc["clusters"], "cluster_id")
    evidence = index(catalogue["evidence"], "evidence_id")
    articles = index(catalogue["articles"], "source_id")
    images_path = root / config.get("trend_images_file", trend_assets.DEFAULT_IMAGES_FILE)
    image_inventory = trend_assets.freeze_inventory(images_path, root)
    for o in observations.values():
        need(o["source_id"] in sources and o["user_id"] in users, f"用研观察来源断裂: {o['id']}")
        s = sources[o["source_id"]]
        need(o["user_id"] == s["user_id"] and o["evidence_kind"] == s["evidence_kind"], f"用研观察身份不一致: {o['id']}")
        text(o["quote"], "用研引文")
        need(o["quote"] in s["text"], f"用研引文不在来源中: {o['id']}")
    for c in research_clusters.values():
        membership = set()
        for feature in c["features"]:
            membership |= ids(feature["observation_ids"], observations, "用研簇成员")
            for embedded in feature.get("observations", []):
                need(embedded == observations.get(embedded["id"]), f"内嵌观察与来源不一致: {embedded['id']}")
        ids(c.get("context_observation_ids", []), observations, "用研背景")
        c["observation_ids"] = sorted(membership)
    for e in evidence.values():
        need(e["source_id"] in articles, f"趋势来源断裂: {e['evidence_id']}")
        a = articles[e["source_id"]]
        need(e["source_group_id"] == a["source_group_id"], "趋势去重来源组不一致")
    for c in trend_clusters.values():
        ids(c["source_ids"], articles, "趋势簇原文章", nonempty=True)
        for sid in c["source_ids"]:
            oid = trend_assets.original_id(articles[sid], sid)
            need(oid in image_inventory["records"], f"图片清单没有相关原文章: {sid}/{oid}")
        ids(c["evidence_refs"], evidence, "趋势簇引用", nonempty=True)
        for eid in c["evidence_refs"]:
            need(evidence[eid]["source_id"] in c["source_ids"], "趋势簇来源与引用不一致")
    snapshot = {
        "schema_version": "prism.local.h01.snapshot.v1", "config": {**config, "mode": mode, "min_trend_source_groups": minimum},
        "research_clusters": research_clusters, "trend_clusters": trend_clusters,
        "observations": observations, "sources": sources, "users": users,
        "evidence": evidence, "articles": articles,
        "constraint_ids": sorted(o["id"] for o in observations.values() if o["stance"] in {"avoid", "conditional"} or o.get("conditions")),
        "point_scope_limits": raw.get("trend-proposal", {}).get("point_scope_limits", {}),
        "upstream": {"research_execution": full.get("execution"), "research_unclustered": full.get("unclustered", []),
                     "research_semantic_coverage": handshake.get("semantic_coverage"),
                     "trend": pick(tc, ("semantic_coverage", "visual_analysis_performed", "review_status")),
                     "traceability_gaps": [k for k in optional if k not in raw]},
    }
    overview = {
        "brief": config["brief"], "mode": mode, "sample_user_count": len(users),
        "research_clusters": [pick(c, ("id", "name", "design_question", "summary", "users_by_stance")) for c in research_clusters.values()],
        "trend_clusters": [pick(c, ("cluster_id", "title", "definition", "design_question", "boundaries", "unknowns")) for c in trend_clusters.values()],
        "constraint_count": len(snapshot["constraint_ids"]), "upstream": snapshot["upstream"],
        "note": "摘要只供召回；必须回查候选成员、局部边界和全部约束。",
    }
    out.mkdir(parents=True)
    frozen = []
    write(out / trend_assets.INVENTORY_FILE, image_inventory)
    frozen.append({"role": "trend-image-inventory", "path": trend_assets.INVENTORY_FILE,
                   "sha256": sha(out / trend_assets.INVENTORY_FILE)})
    for role, path in paths.items():
        target = out / "frozen" / f"{role}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(path.read_bytes())
        frozen.append({"role": role, "original_path": str(path), "path": str(target.relative_to(out)), "sha256": sha(target)})
    skill_files = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md")), Path(__file__),
                   Path(trend_assets.__file__)]
    for path in skill_files:
        target = out / "frozen" / "skill" / path.relative_to(SKILL)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        frozen.append({"role": "skill", "original_path": str(path), "path": str(target.relative_to(out)), "sha256": sha(target)})
    write(out / "snapshot.json", snapshot)
    write(out / "overview.json", overview)
    for name in ("snapshot.json", "overview.json"):
        frozen.append({"role": name, "path": name, "sha256": sha(out / name)})
    manifest = {"schema_version": "prism.local.h01.manifest.v1", "skill_version": VERSION, "prepared_at": now(),
                "files": frozen, "snapshot_sha256": sha(out / "snapshot.json"),
                "related_assets_required": True,
                "image_inventory_source": {"path": str(images_path.resolve()), "sha256": image_inventory["source_sha256"]},
                "prompt_sha256": sha(SKILL / "references/handshake-prompt.md"),
                "counts": {"research_clusters": len(research_clusters), "trend_clusters": len(trend_clusters), "observations": len(observations), "constraints": len(snapshot["constraint_ids"]), "users": len(users)}}
    write(out / "manifest.json", manifest)
    return manifest["counts"]


def load_run(run):
    """仅校验本轮冻结副本，不要求上游目录永远不发生后续更新。"""
    run = Path(run)
    manifest = read(run / "manifest.json")
    for file in manifest["files"]:
        need(sha(run / file["path"]) == file["sha256"], f"冻结文件已变更: {file['path']}")
    need(sha(run / "snapshot.json") == manifest["snapshot_sha256"], "快照哈希不一致")
    return manifest, read(run / "snapshot.json")


def packet(run, side, cluster_ids, offset, limit):
    """按成员分页，返回完整来源等级及局部边界；不按关键词预先筛掉证据。"""
    manifest, s = load_run(run)
    need(offset >= 0 and 1 <= limit <= 100, "offset >= 0，limit 范围 1–100")
    headers, rows = [], []
    if side in {"research", "trend"}:
        clusters = s[f"{side}_clusters"]
        ids(cluster_ids, clusters, "取证簇", nonempty=True)
        members = set()
        for cid in cluster_ids:
            c = clusters[cid]
            headers.append(pick(c, ("id", "name", "summary", "cluster_id", "title", "definition", "design_question", "boundaries", "differences", "design_implications", "unknowns", "variations")))
            members.update(c["observation_ids"] + c.get("context_observation_ids", []) if side == "research" else c["evidence_refs"])
        keys = sorted(members)
    else:
        need(not cluster_ids, "constraints 不接受簇 ID，必须覆盖全部约束")
        keys = s["constraint_ids"]
    for key in keys[offset:offset + limit]:
        if side != "trend":
            o = s["observations"][key]
            # 来源投影仅含文字和定位信息，不传递图片或完整画像。
            rows.append({"observation": pick(o, ("id", "source_id", "user_id", "evidence_kind", "statement", "dimension", "stance", "object", "context", "conditions", "quote")), "source": pick(s["sources"][o["source_id"]], ("source_id", "user_id", "text", "evidence_kind", "field", "pointer"))})
        else:
            e = s["evidence"][key]
            scopes = []
            for cid in cluster_ids:
                c = s["trend_clusters"][cid]
                for lineage in c.get("lineage", []):
                    matched = [m for m in lineage.get("members", []) if m.get("evidence_id") == key]
                    if matched:
                        scopes.append({"cluster_id": cid, **pick(lineage, ("seed_id", "title", "definition", "boundaries", "unknowns")), "members": [pick(m, ("point_id", "subject", "feature", "dimension", "condition", "evidence_id", "quote", "reason", "effective_feature", "rejected_inference")) for m in matched],
                                       "point_scope_limits": {m["point_id"]: s["point_scope_limits"][m["point_id"]] for m in matched if m["point_id"] in s["point_scope_limits"]}})
            rows.append({"evidence": pick(e, ("evidence_id", "source_id", "field", "text", "text_kind", "original_text_excerpt", "locator", "source_url", "source_group_id", "claim_origin_id")), "article": pick(s["articles"][e["source_id"]], ("source_id", "title", "source_group_id", "claim_origin_id")), "local_scopes": scopes})
    return {"snapshot_sha256": manifest["snapshot_sha256"], "side": side, "cluster_ids": cluster_ids, "headers": headers,
            "offset": offset, "total": len(keys), "next_offset": offset + limit if offset + limit < len(keys) else None, "records": rows}


def coverage(rows, clusters, used):
    mapping = index(rows, "cluster_id")
    need(set(mapping) == set(clusters), "聚类去向未完整覆盖")
    for cid, row in mapping.items():
        need(row["disposition"] in {"used", "not_selected", "insufficient", "conflict"}, "未知聚类去向")
        need((row["disposition"] == "used") == (cid in used), f"聚类 used 标记与候选不一致: {cid}")
        text(row["reason"], "聚类去向原因")


def validate(proposal, manifest, s):
    """验证引用、归属、模式和逐方向约束覆盖；不冒充语义评估。"""
    need(proposal["schema_version"] == PROPOSAL, "不支持的提案契约")
    need(proposal["snapshot_sha256"] == manifest["snapshot_sha256"], "提案对应错误输入快照")
    execution = proposal["execution"]
    text(execution["model_id"], "实际 model_id")
    need(execution["model_version"] is None or isinstance(execution["model_version"], str), "model_version 必须为字符串或 null")
    for key in ("started_at", "completed_at"):
        dt = datetime.fromisoformat(execution[key])
        need(dt.tzinfo is not None, f"{key}: 需要时区")
    need(datetime.fromisoformat(execution["completed_at"]) >= datetime.fromisoformat(execution["started_at"]), "执行时间倒置")
    need(execution["prompt_sha256"] == manifest["prompt_sha256"], "执行提示哈希不一致")
    texts(execution["traceability_gaps"], "追溯缺口")
    if execution["model_version"] is None:
        need("model_version" in execution["traceability_gaps"], "未知模型版本需记入缺口")
    directions = index(proposal["directions"], "direction_id")
    used_r, used_t, compiled = set(), set(), []
    for d in directions.values():
        for field in ("title", "design_question", "shared_design_principle", "why_high_potential", "validation_next_step"):
            text(d[field], field)
        for field in ("conditions_and_limits", "user_differences", "unresolved_questions"):
            texts(d[field], field)
        basis, decision = d["relation_basis"], d["decision"]
        need(basis in MODES[s["config"]["mode"]], "当前模式不允许此延展类型")
        need(decision in {"high_potential", "exploration", "conflict", "insufficient"}, "未知方向状态")
        if basis != "direct_support":
            text(d["extension_explanation"], "延展解释")
        if basis == "exploratory_hypothesis":
            need(decision != "high_potential", "探索假设不能升级为高潜")
        rids = ids(d["research_cluster_ids"], s["research_clusters"], "用研簇", True)
        tids = ids(d["trend_cluster_ids"], s["trend_clusters"], "趋势簇", True)
        used_r |= rids
        used_t |= tids
        rcites = index(d["research_citations"], "observation_id")
        tcites = index(d["trend_citations"], "evidence_id")
        need(rcites and tcites, "每个方向需要双边证据")
        positive_users, groups, cited_sources = set(), set(), set()
        attached_r, attached_t = set(), set()
        resolved_r, resolved_t = [], []
        for oid, cite in rcites.items():
            need(oid in s["observations"], f"未知观察 ID: {oid}")
            o = s["observations"][oid]
            need(cite["quote"] == o["quote"], f"用研引文被修改: {oid}")
            need(cite["role"] in {"support", "boundary", "context"}, "未知用研证据角色")
            text(cite["reason"], "引用理由")
            belongs = {rid for rid in rids if oid in s["research_clusters"][rid]["observation_ids"]}
            if cite["role"] == "support":
                need(belongs, "支持项不属于所选用研簇")
                need(o["stance"] in {"prefer", "conditional"} and o["evidence_kind"] != "profile_value", "负向或背景不能作为正向支持")
                positive_users.add(o["user_id"])
            attached_r |= belongs
            resolved_r.append({**cite, "observation": o, "source_locator": pick(s["sources"][o["source_id"]], ("pointer", "field", "evidence_kind"))})
        for eid, cite in tcites.items():
            need(eid in s["evidence"], f"未知趋势引用: {eid}")
            e = s["evidence"][eid]
            need(cite["quote"] and cite["quote"] in e["text"], f"趋势引文不在来源中: {eid}")
            need(cite["text_kind"] == e["text_kind"], "趋势来源等级被修改")
            text(cite["reason"], "引用理由")
            text(cite["scope_note"], "趋势局部条件说明")
            belongs = {tid for tid in tids if eid in s["trend_clusters"][tid]["evidence_refs"]}
            need(belongs, "趋势引用不属于所选簇")
            attached_t |= belongs
            groups.add(e["source_group_id"])
            cited_sources.add(e["source_id"])
            resolved_t.append({**cite, "evidence": e})
        need(attached_r == rids and attached_t == tids, "所选聚类存在没有成员引用的空挂靠")
        audited = set()
        unresolved = False
        for row in d["constraint_audit"]:
            oids = ids(row["observation_ids"], s["constraint_ids"], "约束审查", True)
            need(not audited & oids, "约束项重复审查")
            audited |= oids
            need(row["state"] in {"applicable", "not_applicable", "unresolved"}, "未知约束适用性")
            text(row["reason"], "约束审查理由")
            text(row["implication"], "约束对设计的影响")
            unresolved |= row["state"] == "unresolved"
        need(audited == set(s["constraint_ids"]), "必须审查全部反向/条件项，包括未入簇项")
        if decision == "high_potential":
            need(positive_users, "高潜方向没有正向用户锚点")
            need(len(groups) >= s["config"]["min_trend_source_groups"], "高潜方向去重趋势来源组不足")
            need(not unresolved, "反证适用性未解决，不能标为高潜")
        compiled.append({**d, "research_citations": resolved_r, "trend_citations": resolved_t,
                         "support_user_ids": sorted(positive_users), "support_user_count": len(positive_users),
                         "sample_user_count": len(s["users"]), "trend_source_ids": sorted(cited_sources), "trend_source_group_count": len(groups)})
    coverage(proposal["research_cluster_coverage"], s["research_clusters"], used_r)
    coverage(proposal["trend_cluster_coverage"], s["trend_clusters"], used_t)
    texts(proposal["overall_evidence_gaps"], "总体证据缺口")
    return compiled


def report(result):
    lines = ["# 用研 × 趋势：高潜方向候选", "", "状态：待人工确认。高潜只代表当前文本证据支持的设计机会，不是市场预测。", "",
             f"候选 {len(result['directions'])} 条；高潜 {sum(d['decision'] == 'high_potential' for d in result['directions'])} 条。", ""]
    if result.get("related_trend_assets"):
        stats = result["related_trend_assets"]["stats"]
        lines += [f"[全部关联文章与图片路径]({trend_assets.INDEX_FILE})：{stats['related_articles']} 篇文章、"
                  f"{stats['image_references']} 条图片引用，{stats['local_image_references']} 条有本地文件，"
                  f"{stats['unresolved_image_references']} 条待补齐。", ""]
    for d in result["directions"]:
        lines += [f"## {d['direction_id']} · {d['title']}", "", f"状态：{d['decision']}；关系：{d['relation_basis']}", "",
                  f"设计问题：{d['design_question']}", "", f"共同机制：{d['shared_design_principle']}", "", d["why_high_potential"], "",
                  f"支持用户：{d['support_user_count']}/{d['sample_user_count']}；引用趋势来源组：{d['trend_source_group_count']}。", ""]
        if d.get("related_trend_assets"):
            a = d["related_trend_assets"]
            lines += [f"相关簇成员：{a['article_count']} 篇文章、{a['image_reference_count']} 条图片引用；"
                      f"路径见 [{trend_assets.INDEX_FILE}]({trend_assets.INDEX_FILE})，按方向 {d['direction_id']} 查询。", ""]
        for key, title in (("conditions_and_limits", "适用条件"), ("user_differences", "用户差异"), ("unresolved_questions", "待验证问题")):
            lines += [f"### {title}", "", *[f"- {v}" for v in d[key]], ""]
        lines += ["### 双边证据", ""]
        for c in d["research_citations"]:
            o = c["observation"]
            lines.append(f"- 用研 {o['id']} / 用户 {o['user_id']} / {o['evidence_kind']} / {o['stance']}：{c['quote']}；{c['reason']}")
        for c in d["trend_citations"]:
            lines.append(f"- 趋势 {c['evidence_id']} / {c['text_kind']}：{c['quote']}；{c['scope_note']}；{c['reason']}")
        lines += ["", f"延展说明：{d['extension_explanation']}", "", f"下一步：{d['validation_next_step']}", ""]
    lines += ["## 聚类去向", ""]
    for side in ("research", "trend"):
        lines += [f"- {side} / {r['cluster_id']}：{r['disposition']}；{r['reason']}" for r in result[f"{side}_cluster_coverage"]]
    lines += ["", "## 总体证据缺口", "", *[f"- {v}" for v in result["overall_evidence_gaps"]], "",
              "完整约束审查、逐条引用定位、上游状态和执行追溯见 result.json。程序校验不代表语义正确，图片未参与本轮判断。", ""]
    return "\n".join(lines)


def accept(run, proposal_path):
    run = Path(run)
    for name in ("result.json", "report.md", "selection-template.json", "receipt.json", trend_assets.INDEX_FILE):
        need(not (run / name).exists(), f"已有产物 {name}，修改需新建运行")
    manifest, s = load_run(run)
    proposal = read(proposal_path)
    compiled = validate(proposal, manifest, s)
    assets = trend_assets.build_index(s, compiled, read(run / trend_assets.INVENTORY_FILE), manifest["snapshot_sha256"])
    compiled = trend_assets.attach_direction_assets(compiled, assets)
    result = {**proposal, "schema_version": "prism.local.h01.result.v1", "directions": compiled,
              "review_status": "pending_human_review", "semantic_coverage": "model_assessed", "visual_analysis_performed": False,
              "compiled_at": now(), "upstream": s["upstream"], "skill_version": manifest["skill_version"]}
    result["related_trend_assets"] = {"index_file": trend_assets.INDEX_FILE, "stats": assets["stats"]}
    # 宿主可以直接把提案放在运行目录；相同文件无需再次写入。
    if Path(proposal_path).resolve() != (run / "proposal.json").resolve():
        write(run / "proposal.json", proposal)
    write(run / "result.json", result)
    write(run / trend_assets.INDEX_FILE, assets)
    (run / "report.md").write_text(report(result), encoding="utf-8")
    template = {"result_sha256": sha(run / "result.json"), "selected_direction_ids": [], "actor": "human", "actor_name": "",
                "authorization": "", "reason": "", "confirmed_at": None}
    write(run / "selection-template.json", template)
    write(run / "receipt.json", {"manifest_sha256": sha(run / "manifest.json"), "proposal_sha256": sha(run / "proposal.json"),
                                  "result_sha256": sha(run / "result.json"), "report_sha256": sha(run / "report.md"),
                                  "related_trend_articles_sha256": sha(run / trend_assets.INDEX_FILE)})
    return {"directions": len(compiled), "review_status": "pending_human_review"}


def verify(run):
    run = Path(run)
    manifest, s = load_run(run)
    if (run / "result.json").exists():
        receipt = read(run / "receipt.json")
        for name in ("manifest", "proposal", "result", "report"):
            path = run / (f"{name}.md" if name == "report" else f"{name}.json")
            need(sha(path) == receipt[f"{name}_sha256"], f"发布产物已被修改: {path.name}")
        compiled = validate(read(run / "proposal.json"), manifest, s)
        result = read(run / "result.json")
        if manifest.get("related_assets_required"):
            need(sha(run / trend_assets.INDEX_FILE) == receipt["related_trend_articles_sha256"], "文章图片索引已被修改")
            assets = trend_assets.build_index(s, compiled, read(run / trend_assets.INVENTORY_FILE), manifest["snapshot_sha256"])
            need(assets == read(run / trend_assets.INDEX_FILE), "文章图片映射或本地文件状态已变更")
            need(result.get("related_trend_assets") == {"index_file": trend_assets.INDEX_FILE, "stats": assets["stats"]}, "主结果缺少正确的图片索引入口")
            compiled = trend_assets.attach_direction_assets(compiled, assets)
        need(compiled == result["directions"], "结果无法从提案重放")
        if (run / "selection.json").exists():
            check_selection(read(run / "selection.json"), run)
            selection_receipt = read(run / "selection-receipt.json")
            need(sha(run / "selection.json") == selection_receipt["selection_sha256"], "选择记录已被修改")
    return {"valid": True, "scope": "structure_citations_coverage_hashes_only"}


def check_selection(choices, run):
    need(choices["result_sha256"] == sha(Path(run) / "result.json"), "选择对应错误结果版本")
    result = read(Path(run) / "result.json")
    allowed = {d["direction_id"] for d in result["directions"] if d["decision"] == "high_potential"}
    ids(choices["selected_direction_ids"], allowed, "确认方向")
    need(choices["actor"] in {"human", "delegated_ai"}, "未知选择角色")
    for k in ("actor_name", "authorization", "reason"):
        text(choices[k], k)
    need(datetime.fromisoformat(choices["confirmed_at"]).tzinfo is not None, "确认时间需要时区")


def select(run, choices_path):
    """只记录明确选择，不自动把模型候选升级为人工确认。"""
    verify(run)
    choices = read(choices_path)
    check_selection(choices, run)
    write(Path(run) / "selection.json", choices)
    write(Path(run) / "selection-receipt.json", {"selection_sha256": sha(Path(run) / "selection.json"), "recorded_at": now()})
    return {"selected_direction_ids": choices["selected_direction_ids"], "actor": choices["actor"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--config", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p = commands.add_parser("packet")
    p.add_argument("--run", required=True)
    p.add_argument("--side", choices=["research", "trend", "constraints"], required=True)
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out", required=True)
    for name in ("accept", "verify", "select"):
        p = commands.add_parser(name)
        p.add_argument("--run", required=True)
        if name != "verify":
            p.add_argument("--proposal" if name == "accept" else "--choices", required=True)
    a = parser.parse_args()
    try:
        if a.command == "prepare":
            value = prepare(a.config, a.root, a.out)
        elif a.command == "packet":
            value = packet(a.run, a.side, a.ids, a.offset, a.limit)
            write(a.out, value)
            value = {k: value[k] for k in ("total", "offset", "next_offset")}
        elif a.command == "accept":
            value = accept(a.run, a.proposal)
        elif a.command == "verify":
            value = verify(a.run)
        else:
            value = select(a.run, a.choices)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"H01 错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
