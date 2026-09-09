"""确定性生成计数、可追溯图片关联与最终 Markdown/JSON。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from core import accepted, atomic_text, encode, load_jobs, read, timestamp, write


def source_category_scope(evidence_items, records):
    """只回填被引用来源的明确一级类别，用户问题、场景和模型解释不作为品类。"""
    categories, unknown = set(), []
    for record_id in sorted({item["record_id"] for item in evidence_items}):
        category = records[record_id].get("fields", {}).get("primary_category")
        if isinstance(category, str) and category.strip():
            categories.add(category.strip())
        else:
            unknown.append(record_id)
    return {
        "source_categories": sorted(categories),
        "source_category_unknown_record_ids": unknown,
        "source_category_scope": "仅统计本卡引用来源明确提供的 primary_category；未提供者品类未知，不从问题类型、场景或模型提取结果推断。",
    }


def resolve_images(evidence_items, records, project_root):
    """文章图只能是文章级关联；用户图片须在具体引用片段内明确提及编码。"""
    images = {}
    for evidence in evidence_items:
        record = records[evidence["record_id"]]
        codes = evidence.get("image_codes", [])
        refs = record.get("image_refs", [])
        if evidence["kind"] != "trend":
            refs = [ref for ref in refs if ref.get("code") in codes]
        matched_codes = {ref.get("code") for ref in refs}
        code_images = {}
        for ref in refs:
            code_images.setdefault(ref.get("code"), set()).add(ref.get("image_id"))
        if evidence["kind"] != "trend":
            refs = refs + [{"image_id": None, "code": code, "local_path": None,
                            "source_root": str(project_root), "source_record_id": record["id"], "status": "unmatched"}
                           for code in codes if code not in matched_codes]
        for ref in refs:
            path = (Path(ref["source_root"]) / ref["local_path"]).resolve() if ref.get("local_path") else None
            mention_role = evidence.get("image_roles", {}).get(ref.get("code"), "unclear")
            key = (record["id"], ref.get("image_id"), ref.get("code"), evidence["relation"], mention_role)
            if key in images:
                if evidence["id"] not in images[key]["evidence_ids"]:
                    images[key]["evidence_ids"].append(evidence["id"])
                continue
            path_text = str(path.relative_to(project_root)) if path and path.is_relative_to(project_root) else str(path) if path else None
            images[key] = {
                "image_id": ref.get("image_id"), "path": path_text, "absolute_path": str(path) if path else None,
                "source_record_id": record["id"], "evidence_ids": [evidence["id"]], "code": ref.get("code"),
                # 整条证据的反对关系不等于对比较图片的否定，图片只输出文本中的对象角色。
                "role": "trend_reference" if evidence["kind"] == "trend" else "user_" + mention_role,
                "mention_role": None if evidence["kind"] == "trend" else mention_role,
                "evidence_relation": evidence["relation"], "image_attitude_from_text": None,
                "association_level": "article" if evidence["kind"] == "trend" else "explicit_code_in_excerpt",
                "match_status": "ambiguous" if evidence["kind"] != "trend" and len(code_images.get(ref.get("code"), set())) > 1 else ref.get("status", "available"),
                "file_exists": path.is_file() if path else False,
                "emotion_tag": ref.get("emotion_tag"), "visual_verified": False,
            }
    return list(images.values())


def finalize(run, manifest, records, evidence, candidates, assessments, state):
    """仅收录审核通过或已修订的卡片；图片不足和用户分歧如实输出。"""
    from workflow import statistics
    indexed = {candidate["id"]: candidate for candidate in candidates}
    cards, rejected = [], list(state.get("insufficient_candidates", [])) + list(state.get("screen_rejected", []))
    project_root = Path(manifest["project_root"]).resolve()
    for job in load_jobs(run):
        if job["stage"] != "review":
            continue
        result = accepted(run, job)["response"]
        cid = job["payload"]["candidate"]["id"]
        if result["decision"] == "reject":
            rejected.append({"id": cid, "reason": result["issues"]})
            continue
        card = dict(result["card"] if result["decision"] == "revise" else job["payload"]["card"])
        stats = statistics(indexed[cid], assessments[cid], evidence, manifest["as_of"])
        positive_users = stats["user_counts"]["support"] + stats["user_counts"]["conditional_only"] + stats["user_counts"]["mixed"]
        priority = card["priority"]
        adjustment_reasons = []
        if positive_users < 3:
            adjustment_reasons.append("可归属的支持或条件/混合用户少于 3 人")
        if stats["trend_record_count"] < 2:
            adjustment_reasons.append("支持的趋势记录少于 2 条，且项目独立性尚未核实")
        if stats["recent_trend_record_count"] == 0:
            adjustment_reasons.append("缺少基准日前 730 天内的趋势依据")
        if positive_users < 3 or stats["trend_record_count"] < 2 or stats["recent_trend_record_count"] == 0:
            priority = "exploratory"
        elif stats["user_counts"]["mixed"] or stats["user_counts"]["counter"] or stats["user_counts"]["conditional_only"]:
            priority = "contextual" if priority == "priority_validation" else priority
            adjustment_reasons.append("存在反对、混合或条件表达，需保留细分情境")
        cited = set(card["supporting_evidence_ids"] + card["counter_evidence_ids"])
        for entry in card["claims"] + card["opportunities"] + card["boundaries"]:
            cited.update(entry["evidence_ids"])
        referenced = [{**evidence[eid], "relation": assessments[cid][eid]["relation"]} for eid in sorted(cited)]
        cards.append({**card, "id": cid, "priority": priority, "model_proposed_priority": card["priority"],
                      "priority_constraints": adjustment_reasons,
                      "support_statistics": stats, "evidence_strength": "limited",
                      "evidence_strength_reason": "基于已有分析文本；原始访谈、市场代表性与项目来源独立性未核实。",
                      "evidence_scope": {"dimensions": indexed[cid]["dimensions"], **source_category_scope(referenced, records),
                                         "cross_category_applications": "hypotheses_to_validate", "counter_search_scope": "all_evidence_in_candidate_dimensions"},
                      "source_evidence": referenced, "image_refs": resolve_images(referenced, records, project_root),
                      "review_status": "model_reviewed", "human_review_status": "pending", "review_issues": result["issues"]})
    order = {"priority_validation": 0, "contextual": 1, "exploratory": 2}
    cards.sort(key=lambda card: (order[card["priority"]], -card["support_statistics"]["users_with_relevant_evidence"], card["id"]))
    sources = []
    for job in load_jobs(run):
        result = accepted(run, job)
        sources.append({key: result[key] for key in ("job_id", "model", "prompt_version", "accepted_at", "request_sha256", "response_sha256", "receipt_sha256", "input_tokens", "output_tokens", "execution")})
    coverage = Counter()
    record_dispositions = []
    from contracts import normalize_extract
    for job in load_jobs(run):
        if job["stage"] == "extract":
            normalized = normalize_extract(job, accepted(run, job)["response"])
            coverage.update(item["status"] for item in normalized["coverage"])
            record_dispositions.extend(normalized["coverage"])
    excluded = []
    for job in load_jobs(run):
        if job["stage"] in {"theme", "propose", "merge"}:
            excluded.extend({"job_id": job["id"], **entry} for entry in accepted(run, job)["response"]["deferred"])
    proposed_evidence = {item["id"] for job in load_jobs(run) if job["stage"] == "propose" for item in job["payload"]["evidence"]}
    retrieval = read(run / "retrieval_report.json")
    validation = {"all_jobs_accepted": True, "record_coverage": dict(coverage), "record_dispositions": record_dispositions,
                  "evidence_count": len(evidence),
                  "unpaired_evidence_ids": sorted(set(retrieval["unpaired_evidence_ids"]) | {eid for eid, e in evidence.items() if e["kind"] == "trend" and eid not in proposed_evidence}),
                  "unpaired_reason": "缺少可配对主题或可归属用户，或被主题步骤暂缓；不表示没有价值。未被选为代表的主题成员单独记录。",
                  "retrieval": retrieval,
                  "cache": read(run / "cache_report.json"),
                  "trend_count": len(cards), "rejected_candidates": rejected, "deferred_items": excluded,
                  "missing_image_references": sum(not image["file_exists"] for card in cards for image in card["image_refs"]),
                  "semantic_review": "completed_by_host_models" if sources else "not_needed", "human_review": "pending",
                  "text_only_requests": all(all(isinstance(m["content"], str) for m in read(run / "requests" / f"{j['id']}.json")["messages"]) for j in load_jobs(run))}
    from user_gaps import compile_findings, markdown, pending_section, scope_for_run
    population = scope_for_run(run, records)
    findings_path = run / "user_gap_findings.json"
    gaps = (compile_findings(read(findings_path), evidence, records, population, project_root)
            if findings_path.exists() else pending_section(population))
    validation["user_research_gaps"] = {"status": gaps["status"], "direction_count": len(gaps["directions"])}
    validation["missing_image_references"] += sum(not image["file_exists"] for d in gaps["directions"] for image in d["image_refs"])
    document = {"schema_version": "design_trend_insights_v2", "generated_at": timestamp(), "selection": manifest["selection"],
                "input_counts": manifest["counts"], "source_inputs": manifest["inputs"], "as_of": manifest["as_of"],
                "trends": cards, "user_research_gaps": gaps, "execution": sources, "model_profile": manifest.get("model_profile"),
                "scope_note": "文本归纳的设计验证机会；不代表市场增长预测，未进行本轮视觉核验。"}
    write(run / "high_potential_trends.json", document)
    atomic_text(run / "high_potential_trends.jsonl", "".join(encode(card) + "\n" for card in cards))
    write(run / "validation_report.json", validation)
    lines = ["# 通用设计趋势洞察", "", document["scope_note"], "",
             f"趋势日期范围：{manifest['selection']['start_date'] or '不限'} 至 {manifest['selection']['end_date'] or '不限'}（包含边界当天）；未知日期：{manifest['selection']['undated_policy']}。",
             f"纳入 {manifest['counts']['selected_trends']} 条趋势；有文本的用户 {manifest['counts']['users_with_text']} 人；输出 {len(cards)} 个待人工评审方向。", ""]
    if not cards:
        lines.append("本轮未形成通过审核的双侧交集；这不表示用户没有相关需求，详细范围与暂缓原因见 validation_report.json。")
    labels = {"priority_validation": "优先验证", "contextual": "细分情境机会", "exploratory": "探索观察"}
    for index, card in enumerate(cards, 1):
        lines += [f"## {index}. {card['title']}", "", card["thesis"], "", f"优先级：{labels[card['priority']]}；证据：有限；人工评审：待进行。", "",
                  f"用户矛盾：{card['user_tension']}", "", f"设计原则：{card['design_principle']}", "", f"判断理由：{card['rationale']}", "",
                  f"程序核对的限制：{'；'.join(card['priority_constraints']) or '未触发数量或时效降级，仍需人工评审'}。", "",
                  f"反证搜索范围：候选设计维度 {', '.join(card['evidence_scope']['dimensions'])} 的全部已提取文本；其他维度及外部资料未作完整反证检查。", "",
                  f"程序统计：{encode(card['support_statistics'])}", "", "资料支持的发现：", ""]
        lines.extend(f"- {entry['text']}〔{', '.join(entry['evidence_ids'])}〕" for entry in card["claims"])
        lines += ["", "跨品类探索假设：", ""]
        lines.extend(f"- {entry['category']}：{entry['proposal']}〔{', '.join(entry['evidence_ids'])}〕" for entry in card["opportunities"])
        lines += ["", "边界与反例：", ""]
        lines.extend(f"- {entry['text']}〔{', '.join(entry['evidence_ids'])}〕" for entry in card["boundaries"])
        lines += ["", "来源字段片段（并非本轮核对过的访谈原话）：", ""]
        lines.extend(f"- `{e['id']}` / `{e['record_id']}` / `{e['json_pointer']}`：{e['quote']}" for e in card["source_evidence"])
        lines += ["", "来源关联图片（未做视觉核验）：", ""]
        if not card["image_refs"]:
            lines.append("- 当前文本证据没有可确认的图片关联。")
        for ref in card["image_refs"]:
            label = f"{ref['image_id'] or ref['code'] or '缺失图片'} / {ref['role']} / {ref['association_level']}"
            if ref["file_exists"]:
                lines.append(f"- [{label}](<{ref['absolute_path']}>)")
            elif ref["absolute_path"]:
                lines.append(f"- {label}：文件不存在，原路径 `{ref['absolute_path']}`。")
            else:
                lines.append(f"- {label}：编码未匹配，路径为空。")
        lines.append("")
    lines.append(markdown(gaps))
    atomic_text(run / "report.md", "\n".join(lines) + "\n")
    # 完成标记最后写，宿主只使用带有此标记的完整输出。
    write(run / "completion.json", {"completed_at": timestamp(), "trends": len(cards), "status": "complete",
                                    "user_research_gaps_status": gaps["status"]})
