"""Validate analyst semantic decisions, preserve source scope, and compile auditable clusters."""
from copy import deepcopy
from collections import Counter,defaultdict
import argparse
from pathlib import Path
import json
from prepare import VERSION, bind, read, lines, write, digest

DIRECT={"selected_board_reason","selected_style_word","phone_preference_reason","explicit_cmf_caption"}
POSITIVE={"like","preferred_word_selection","document_recorded_favorite_context"}
RELATIONS={"support","boundary","alternative","context","illustration","mention"}
KINDS={"shared_theme","exploratory_signal","design_issue","background_theme"}
DISPOSITIONS={"clustered","partially_clustered","reference_only","insufficient_specificity","unclustered_boundary","context_only"}
def require(ok,message):
    if not ok:raise ValueError(message)
def jsonl(path,rows):
    Path(path).write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")
def source_channel(u):
    k=u["kind"]
    if k in DIRECT:return "direct_design_expression"
    if k=="brand_preference_or_impression":
        return "entity_reference" if "Brand :" in u["source_text"] else "brand_impression"
    if k=="personal_identity_goal":return "personal_goal"
    if k=="character_association":return "character_impression"
    if k=="elicited_concept_image_example":return "concept_example"
    return "reference"

def validate_and_compile(dataset,proposal):
    dataset=Path(dataset);binding=bind(dataset)
    require(proposal.get("schema_version")==VERSION,"wrong semantic proposal version")
    require(proposal.get("input_binding")==binding,"source changed since semantic analysis")
    us=lines(dataset/"semantic-units.jsonl");units={u["semantic_unit_id"]:u for u in us}
    people=read(dataset/"people.json");pidx={p["person_id"]:p for p in people}
    raw={e["evidence_id"]:e for e in lines(dataset/"raw-evidence.jsonl")}
    occurrences={i["occurrence_id"]:i for i in lines(dataset/"picture-contexts.jsonl")}
    clusters=proposal.get("clusters",[])
    require(clusters and len({c["cluster_id"] for c in clusters})==len(clusters),"unique nonempty clusters required")
    coverage=proposal.get("coverage",[])
    require(len(coverage)==len(units) and {c["unit_id"] for c in coverage}==set(units),"every original unit needs exactly one coverage outcome")
    assignment_map=defaultdict(set);membership_rows=[];compiled=[]
    for c in clusters:
        for key in ("title","definition","common_meaning","handshake_question"):
            require(isinstance(c.get(key),str) and c[key].strip(),f"missing cluster {key}")
        require(c.get("kind") in KINDS,"unknown cluster kind")
        require(isinstance(c.get("boundaries"),list) and c["boundaries"],"cluster boundaries required")
        require(c.get("members"),"empty semantic cluster")
        members=[];seen=set();images={};facets=defaultdict(list)
        direct=set();brand=set();boundary=set();alternative=set();context=set();illustration=set();mention=set()
        persons=defaultdict(lambda:defaultdict(list))
        for number,m in enumerate(c["members"],1):
            require(m.get("unit_id") in units,"unknown semantic unit")
            u=units[m["unit_id"]];q=m.get("quote")
            require(isinstance(q,str) and q.strip() and q in u["source_text"],"membership quote not exact source substring")
            require(m.get("relation") in RELATIONS,"invalid relation")
            for k in ("facet","rationale","limits"):require(isinstance(m.get(k),str) and m[k].strip(),f"membership needs {k}")
            key=(m["unit_id"],m["relation"],q)
            require(key not in seen,"duplicate member within cluster");seen.add(key)
            channel=source_channel(u);rel=m["relation"];person=u["person_id"]
            require(person in pidx,"unknown source person")
            for quote in u["quotes"]:
                e=raw.get(quote["evidence_id"])
                require(e and quote["text"]==e["text"] and e["person_id"]==person and e["source_id"]==u["source_id"],"unit quote/source binding failed")
            if rel=="support":
                require(u["attitude"] in POSITIVE,"negative/association/aspiration cannot become positive support")
                require(channel in {"direct_design_expression","brand_impression"},"entity or context cannot vote as design support")
            if rel=="boundary":require(u["attitude"]=="dislike","boundary polarity must retain original negative")
            if rel=="alternative":require(u["attitude"] in POSITIVE and channel=="direct_design_expression","alternative needs actual positive design expression")
            if rel=="illustration":require(channel=="concept_example","illustration must retain original concept-example role")
            if channel in {"personal_goal","character_impression"}:require(rel=="context","personal/character statements stay contextual")
            if channel=="concept_example":require(rel=="illustration","prompted example cannot change role")
            if c["kind"]=="background_theme":require(rel=="context","background clusters cannot acquire direct design support")
            mid=f"{c['cluster_id']}-M{number:03d}"
            membership={**deepcopy(m),"membership_id":mid,"cluster_id":c["cluster_id"],
                "person_id":person,"person_name":pidx[person]["display_name"],"source_channel":channel,
                "source_attitude":u["attitude"],"whole_source_unit":u["source_text"],
                "source_kind":u["kind"],"source_id":u["source_id"],"source_unit_digest":digest(u),
                "source_page":u["page"],"source_slide_id":u["slide_id"],"source_scope":u.get("scope"),
                "source_entity":u.get("target_entity_label"),"evidence_quotes":deepcopy(u["quotes"]),
                "contrast_or_limit_markers":deepcopy(u["contrast_or_limit_markers"]),
                "image_links":deepcopy(u["image_links"]),"source_page_image_ids":deepcopy(u["source_page_image_occurrence_ids"]),
                "input_interpretation_status":u["independent_review_status"],
                "direct_support_vote":rel=="support" and channel=="direct_design_expression"}
            if membership["direct_support_vote"]:direct.add(person);persons[person]["direct_support"].append(mid)
            elif rel=="support":brand.add(person);persons[person]["brand_impression"].append(mid)
            elif rel=="boundary":boundary.add(person);persons[person]["boundary"].append(mid)
            elif rel=="alternative":alternative.add(person);persons[person]["alternative"].append(mid)
            elif rel=="illustration":illustration.add(person);persons[person]["illustration"].append(mid)
            elif rel=="mention":mention.add(person);persons[person]["mention"].append(mid)
            else:context.add(person);persons[person]["context"].append(mid)
            for link in u["image_links"]:
                oid=link["occurrence_id"];o=occurrences.get(oid)
                require(o and o["person_id"]==person and o["slide_id"]==u["slide_id"],"image link crosses person/source page")
                image=images.setdefault(oid,{"occurrence_id":oid,"person_id":person,"source_slide_id":u["slide_id"],
                    "source_page":u["page"],"asset_id":o.get("asset_id"),"membership_ids":[],"relations":[],
                    "source_units":[],"association_status":link["confidence"],
                    "source_relation":link["relation"],"is_preference_of_all_image_features":False})
                image["membership_ids"].append(mid)
                if rel not in image["relations"]:image["relations"].append(rel)
                if u["semantic_unit_id"] not in image["source_units"]:image["source_units"].append(u["semantic_unit_id"])
            assignment_map[m["unit_id"]].add(c["cluster_id"])
            members.append(membership);membership_rows.append(membership);facets[m["facet"]].append(mid)
        if c["kind"]=="shared_theme":require(len(direct)>=2,"shared theme needs at least two direct source people")
        if c["kind"]=="exploratory_signal":require(len(direct)==1,"single-person signal must stay explicitly single-person")
        result={k:deepcopy(v) for k,v in c.items() if k!="members"}
        result.update({"members":members,"facets":dict(facets),"person_evidence_matrix":dict(persons),
            "statistics":{"direct_design_support_people":sorted(direct),"direct_design_support_count":len(direct),
               "support_people_by_source_kind":{k:sorted({m["person_id"] for m in members
                    if m["direct_support_vote"] and m["source_kind"]==k})
                    for k in sorted({m["source_kind"] for m in members if m["direct_support_vote"]})},
               "direct_support_is_only_word_selection":bool(direct) and all(
                    m["source_kind"]=="selected_style_word" for m in members if m["direct_support_vote"]),
               "brand_impression_people":sorted(brand),"brand_impression_count":len(brand),
               "boundary_people":sorted(boundary),"boundary_count":len(boundary),
               "alternative_people":sorted(alternative),"context_people":sorted(context),"illustration_people":sorted(illustration),
               "mention_people":sorted(mention),"distinct_people_any_role":len(persons),
               "membership_count":len(members),"distinct_source_units":len({m["unit_id"] for m in members}),
               "linked_image_occurrence_count":len(images),"cohort_people":len(people),
               "not_a_population_preference_rate":True},
            "images":list(images.values()),"summary_status":"analyst_semantic_synthesis_not_independently_reviewed",
            "source_association_status":"inherits_first_pass_image_links_no_upgrade",
            "elicitation_note":"Some records are prompted vocabulary choices or prompted selection reasons; counts do not establish unprompted preference or population prevalence.",
            "country_generalization":False,"trend_rank":None,"DNA_parameter_mapping":None})
        compiled.append(result)
    full_coverage=[]
    for row in coverage:
        uid=row["unit_id"];u=units[uid]
        require(row.get("disposition") in DISPOSITIONS,"unknown coverage disposition")
        require(row.get("reason"),"coverage reason required")
        require(set(row.get("cluster_ids",[]))==assignment_map[uid],"coverage/cluster membership disagreement")
        if row["disposition"]=="reference_only":require(not assignment_map[uid],"reference-only entry cannot secretly be clustered")
        if u["attitude"]=="dislike" and not assignment_map[uid]:
            require(row["disposition"]=="unclustered_boundary","negative evidence cannot disappear into generic references")
        full_coverage.append({**deepcopy(row),"person_id":u["person_id"],"source_kind":u["kind"],
            "source_attitude":u["attitude"],"whole_source_unit":u["source_text"],
            "evidence_quotes":deepcopy(u["quotes"]),"image_links":deepcopy(u["image_links"]),
            "source_page":u["page"],"source_slide_id":u["slide_id"],"source_entity":u.get("target_entity_label"),
            "source_unit_digest":digest(u)})
    neg={u["semantic_unit_id"] for u in us if u["attitude"]=="dislike"}
    summary={"input_units":len(us),"people":len(people),"cluster_count":len(compiled),
        "clusters_by_kind":dict(Counter(c["kind"] for c in compiled)),
        "membership_count":len(membership_rows),"units_with_cluster_membership":sum(bool(v) for v in assignment_map.values()),
        "coverage_dispositions":dict(Counter(c["disposition"] for c in full_coverage)),
        "all_units_have_explicit_outcome":True,"original_negative_units":len(neg),
        "negative_units_retained":len(neg.intersection({r["unit_id"] for r in full_coverage})),
        "source_unchanged":True,"external_model_API_calls":0,"cross_person_semantic_clustering_performed":True,
        "image_reclustering_performed":False,"independent_semantic_review_performed":False}
    return {"schema_version":VERSION,"input_binding":binding,"proposal_digest":digest(proposal),
        "analyst":deepcopy(proposal["analyst"]),"summary":summary,"people":people,"clusters":compiled,
        "coverage":full_coverage,"membership_rows":membership_rows,"case_notes":proposal.get("case_notes",[])}

def save(dataset,proposal,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    r=validate_and_compile(dataset,proposal)
    write(out/"clusters.json",{k:v for k,v in r.items() if k!="membership_rows"})
    jsonl(out/"memberships.jsonl",r["membership_rows"]);jsonl(out/"coverage-ledger.jsonl",r["coverage"])
    write(out/"summary.json",r["summary"])
    handshakes=[{"cluster_id":c["cluster_id"],"title":c["title"],"kind":c["kind"],"definition":c["definition"],
        "question":c["handshake_question"],"boundaries":c["boundaries"],
        "member_units":list(dict.fromkeys(m["unit_id"] for m in c["members"])),
        "people_by_role":c["statistics"],"evidence_quotes":[q for m in c["members"] for q in m["evidence_quotes"]],
        "image_occurrence_ids":[im["occurrence_id"] for im in c["images"]],
        "image_links_still_candidates":True,"semantic_summary_requires_review":True,
        "eligible_as_direction_candidate":c["kind"] in {"shared_theme","exploratory_signal"},
        "does_not_approve_H01_H02":True} for c in r["clusters"]]
    write(out/"handshake-input.json",{"schema_version":"prism.research_cluster_handoff.v1","input_binding":r["input_binding"],
        "clusters":handshakes,"ranked_against_trends":False,"population_prevalence_estimated":False})
    rows=["# 用研纯语义聚类结果","",
          "本轮通过读取原文做语义归纳，保留多重归属、相反态度、对象和程度。程序负责引用与统计校验，不把关键词规则冒充语义判断。","",
          f"输入{r['summary']['input_units']}条，{r['summary']['people']}人；全部记录已有归属或留存理由。负向记录{r['summary']['original_negative_units']}条完整保留。","",
          "| 类别 | 主题数量 |","| --- | ---: |"]
    names={"shared_theme":"跨人偏好主题","exploratory_signal":"单人探索线索","design_issue":"设计议题／接受边界","background_theme":"背景语义"}
    for k,v in r["summary"]["clusters_by_kind"].items():rows.append(f"| {names[k]} | {v} |")
    for c in r["clusters"]:
        rows+=["",f"## {c['cluster_id']} · {c['title']}","",names[c["kind"]]+"\n",c["definition"],"",c["common_meaning"],"",
            f"直接设计表达：{c['statistics']['direct_design_support_count']}人；品牌印象：{c['statistics']['brand_impression_count']}人；边界记录：{c['statistics']['boundary_count']}人。人数可重叠，未提及不作反对。",
            "","边界："+"；".join(c["boundaries"]),"","趋势对齐问题："+c["handshake_question"],"",
            "| 人物 | 关系 | 原文片段 | 来源 |","| --- | --- | --- | --- |"]
        for m in c["members"]:
            rows.append("| "+m["person_name"]+" | "+m["relation"]+" | "+m["quote"].replace("|","／").replace("\n"," / ")+" | "+m["unit_id"]+f"（第{m['source_page']}页） |")
    rows+=["","## 状态与后续","",
        "这是本批资料的语义分析结果，未进行独立语义复核。图片关联沿用前一阶段的版面候选，不因聚类而升级。未运行趋势排名、DNA或情绪板生成。",
        "未聚类或只作参考的记录详见coverage-ledger.jsonl。当前分析决策不可直接套用到新样本；可复用流程及提示词另有版本化保存。",""]
    (out/"聚类报告.md").write_text("\n".join(rows),encoding="utf-8")
    print(json.dumps(r["summary"],ensure_ascii=False,indent=2))
    return r

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--dataset",required=True);p.add_argument("--proposal",required=True);p.add_argument("--output",required=True)
    a=p.parse_args();save(a.dataset,read(a.proposal),a.output)
