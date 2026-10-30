"""DNA-only, deterministic complete-link grouping. No upstream semantic metadata is read."""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict,Counter
import argparse,json,hashlib,re,math
VERSION="prism-dna-pool-v3.0-trial-5"
CMF_WEIGHTS={"OPT-001":3,"OPT-002":2,"OPT-003":1.2,"OPT-004":1,"OPT-006":1,"OPT-007":1,"TEX-001":2,"TEX-002":2,"TEX-005":1,"TEX-007":1.5,"TEX-010":1,"TEX-011":1,"TEX-014":1.5,"TEX-015":1,"TEX-016":1,"TEX-018":.7,"COLOR_FAMILY":2,"COLOR_TONE":1,"TEXTURE_STATE":1}
CMF_WEIGHTS.update({"OPT-005":.7,"OPT-008":1.7,"OPT-009":1.5,"OPT-010":.7,"OPT-011":2,"OPT-012":1.5,"OPT-013":2,"OPT-014":1.5,"COL-001":1,"COL-010":1.2,"COL-012":1,"COL-013":1})
ID_WEIGHTS={"GEO-001":2,"GEO-002":1,"GEO-006":1,"GEO-010":1,"GEO-011":1.5,"GEO-012":2,"GEO-013":1,"STR-001":1.5,"STR-002":1,"STR-003":2,"STR-005":1.5,"STR-007":1,"STR-008":1,"STR-012":1,"STR-018":1.5,"REL-008":1,"REL-009":1,"REL-010":1,"REL-012":1,"REL-013":1,"REL-014":1.5}
ID_WEIGHTS.update({"GEO-003":1,"GEO-005":1.5,"GEO-008":1,"GEO-009":2,"GEO-015":1.5,"GEO-018":1,"GEO-020":1.5,"STR-004":1,"STR-019":1,"REL-007":1,"REL-017":1,"REL-019":1,"REL-022":1})
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def known(v):return v is not None and v not in ["unknown","未知","不确定","待确认","未观察",""]
def color_observation(text):
    if not isinstance(text,str):return {}
    groups=[("achromatic",["黑","白","灰","银"]),("warm-neutral",["米","奶油","象牙","木","棕","褐","沙色","卡其","香槟"]),("red",["红","酒红","朱"]),("pink",["粉","玫瑰"]),("orange",["橙","橘"]),("yellow",["黄","金"]),("green",["绿","青绿"]),("blue",["蓝","青蓝"]),("purple",["紫"])]
    found={k for k,terms in groups if any(t in text for t in terms)}
    if len(found)>1 and any(t in text for t in ["奶油白","米白","象牙白","米灰","暖灰"]):found={"warm-neutral"}
    if len(found)>1 and any(t in text for t in ["粉红","玫瑰红"]):found.discard("red")
    out={}
    if len(found)==1:out["COLOR_FAMILY"]=next(iter(found))
    elif len(found)>1:out["COLOR_FAMILY"]="multi:"+"/".join(sorted(found))
    if any(t in text for t in ["深","黑","暗"]):out["COLOR_TONE"]="dark"
    elif any(t in text for t in ["浅","白","奶油","米色","淡"]):out["COLOR_TONE"]="light"
    # No guessed saturation/numeric Lab values.
    return out
def attribute_map(facts,branch,texture_state=None):
    attrs=defaultdict(set);weights=CMF_WEIGHTS if branch=="CMF" else ID_WEIGHTS
    for f in facts:
        p,v=f.get("p"),f.get("v")
        if p in weights and known(v):attrs[p].add(canonical(v))
    if branch=="CMF":
        colors=[f["v"] for f in facts if f.get("p")=="COL-006"]
        if len(set(canonical(c) for c in colors))==1:
            for p,v in color_observation(colors[0]).items():attrs[p].add(canonical(v))
        if "TEX-001" in attrs:attrs["TEXTURE_STATE"].add(canonical("visible"))
        elif texture_state in ["none","visible"]:attrs["TEXTURE_STATE"].add(canonical(texture_state))
    return {p:sorted(v) for p,v in attrs.items()}
def make_units(record):
    """Input keys used: image_id, known_facts, raw_texture_states. Anything else is ignored."""
    image_id=record["image_id"];facts=record["known_facts"];groups=defaultdict(list)
    for i,f in enumerate(facts):
        if f.get("at"):groups[f["at"]].append((i,f))
    states=record.get("effective_texture_states",record.get("raw_texture_states",{}));units=[];missing=[]
    for at,indexed in sorted(groups.items()):
        fs=[f for _,f in indexed];attrs=attribute_map(fs,"CMF",states.get(at))
        # Evidence anchors must be known; a bare common colour cannot define a CMF unit.
        required=["OPT-001","OPT-002"]
        if all(x in attrs for x in required) and len(attrs)>=4:
            identity={"image_id":image_id,"scope":at,"branch":"CMF","indices":[i for i,_ in indexed]}
            axes="known_optics_and_texture" if "TEXTURE_STATE" in attrs else "known_optics_texture_unresolved"
            units.append({**identity,"unit_id":"U"+digest(identity)[:18],"attributes":attrs,"fact_indices":identity["indices"],"comparison_axes":axes})
        elif any(f.get("p") in ["COL-006","OPT-001","TEX-001"] for f in fs):
            missing.append({"scope":at,"branch":"CMF","missing":[x for x in required if x not in attrs]})
    # Object compilation only assigns existing DNA indices; it cannot introduce facts.
    for ob in record.get("id_objects",[]):
        if not ob.get("whole_object_supported_by_DNA"):continue
        ids=sorted(set(ob.get("object_fact_indices",[])))
        gl=sorted(set(ob.get("global_shape_fact_indices",[])))
        if any(type(i) is not int or not 0<=i<len(facts) for i in ids) or not set(gl)<=set(ids):
            missing.append({"scope":ob.get("scope_label","unknown"),"branch":"ID","missing":["invalid_object_fact_binding"]});continue
        attrs=attribute_map([facts[i] for i in ids],"ID")
        global_attrs=attribute_map([facts[i] for i in gl],"ID")
        # Local wheel circles or screw counts are not global shape/complexity evidence.
        for key in ["GEO-001","GEO-002","GEO-003","GEO-005","GEO-008","GEO-009","GEO-012","GEO-015","STR-002","STR-003"]:
            if key in global_attrs:attrs[key]=global_attrs[key]
            else:attrs.pop(key,None)
        if len(attrs)<3 or not any(p in global_attrs for p in ["GEO-001","GEO-012"]):
            missing.append({"scope":ob.get("scope_label","unknown"),"branch":"ID","missing":["insufficient_global_ID_DNA"]});continue
        identity={"image_id":image_id,"scope":ob["scope_label"],"branch":"ID","indices":ids,"object_id":ob["object_id"]}
        units.append({**identity,"unit_id":"U"+digest(identity)[:18],"attributes":attrs,"fact_indices":ids,"global_shape_fact_indices":gl,"scope_binding":"DNA_only_object_compilation_candidate_requires_original_review"})
    if "id_objects" not in record:
        missing.append({"scope":"whole_object","branch":"ID","missing":["DNA_object_compilation_required_no_prefix_guessing"]})
    return units,missing
def decoded(attrs,p):
    v=attrs.get(p,[])
    return json.loads(v[0]) if len(v)==1 else None
def hard_conflict(a,b,branch):
    strict=["OPT-001","OPT-007","TEXTURE_STATE","TEX-001","TEX-002","TEX-007","TEX-014","TEX-015","COLOR_FAMILY","COLOR_TONE"] if branch=="CMF" else ["GEO-001","GEO-002","GEO-012"]
    for p in strict:
        if p in a and p in b and not (set(a[p]) & set(b[p])):return p
    if branch=="ID":
        for p in ["STR-002","STR-003"]:
            x,y=decoded(a,p),decoded(b,p)
            if isinstance(x,(int,float)) and isinstance(y,(int,float)) and min(x,y)>0 and max(x,y)/min(x,y)>2.5:return p
    return None
def distance(a,b,branch):
    weights=CMF_WEIGHTS if branch=="CMF" else ID_WEIGHTS
    if hard_conflict(a,b,branch):return 1.0
    union=set(a)|set(b);shared=set(a)&set(b)
    shared_weight=sum(weights.get(p,1) for p in shared)
    if len(shared)<3 or shared_weight<(7 if branch=="CMF" else 4):return 1.0
    # Missing observations affect certainty/coverage, not the observed visual difference.
    total=shared_weight;cost=0
    for p in shared:
        w=weights.get(p,1)
        sa,sb=set(a[p]),set(b[p])
        x,y=decoded(a,p),decoded(b,p)
        if type(x) in [int,float] and type(y) in [int,float] and x>0 and y>0:
            component=min(1.0,abs(math.log(x/y))/math.log(2.5))
        else:component=1-len(sa&sb)/len(sa|sb)
        cost+=w*component
    return cost/total if total else 1.0
def blocking_key(u):
    a=u["attributes"]
    fields=["OPT-001","OPT-002"] if u["branch"]=="CMF" else []
    return tuple((p,tuple(a.get(p,[]))) for p in fields)
def cluster_units(units,threshold_cmf=.20,threshold_id=.24):
    buckets=defaultdict(list)
    for u in units:buckets[(u["branch"],blocking_key(u))].append(u)
    clusters=[]
    for (branch,key),rows in sorted(buckets.items(),key=lambda kv:canonical(kv[0])):
        # First collapse identical DNA vectors; repeated photo aliases do not affect grouping decisions.
        prototypes=defaultdict(list)
        for r in rows:prototypes[digest(r["attributes"])].append(r)
        leaders=[]
        for proto,member in sorted(prototypes.items(),key=lambda kv:(-len(kv[1][0]["attributes"]),kv[0])):
            attrs=member[0]["attributes"];threshold=threshold_cmf if branch=="CMF" else threshold_id
            feasible=[]
            for i,g in enumerate(leaders):
                ds=[distance(attrs,x,branch) for x in g["prototypes"]]
                worst=max(ds)
                if worst<=threshold:feasible.append((worst,i))
            if feasible:
                _,i=min(feasible);leaders[i]["members"]+=member;leaders[i]["prototypes"].append(attrs)
            else:leaders.append({"members":list(member),"prototypes":[attrs]})
        for g in leaders:
            members=sorted(g["members"],key=lambda x:x["unit_id"])
            attr_counts=defaultdict(Counter)
            for m in members:
                for p,vals in m["attributes"].items():
                    for v in vals:attr_counts[p][v]+=1
            common={p:[{"value":json.loads(v),"count":n} for v,n in c.most_common(3)] for p,c in attr_counts.items()}
            cid=("C" if branch=="CMF" else "I")+digest([x["unit_id"] for x in members])[:14]
            clusters.append({"cluster_id":cid,"branch":branch,"unit_ids":[x["unit_id"] for x in members],"image_count":len({x["image_id"] for x in members}),"unit_count":len(members),"common_DNA":common,"max_pair_distance":max([distance(a,b,branch) for i,a in enumerate(g["prototypes"]) for b in g["prototypes"][i+1:]] or [0]),"pre_named_family_used":False})
    return sorted(clusters,key=lambda c:(c["branch"],-c["image_count"],c["cluster_id"]))
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--records",required=True);ap.add_argument("--out",required=True);args=ap.parse_args()
    records=[json.loads(x) for x in Path(args.records).read_text(encoding="utf-8").splitlines() if x.strip()]
    units=[];missing=[]
    for r in records:
        u,m=make_units(r);units+=u;missing +=[{"image_id":r["image_id"],**x} for x in m]
    clusters=cluster_units(units)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    for name,value in [("units.json",units),("clusters.json",clusters),("unit-gaps.json",missing),("receipt.json",{"algorithm":VERSION,"records":len(records),"units":len(units),"clusters":len(clusters),"branches":dict(Counter(c["branch"] for c in clusters)),"DNA_input_sha256":hashlib.sha256(Path(args.records).read_bytes()).hexdigest(),"cluster_membership_digest":digest([(c["cluster_id"],c["unit_ids"]) for c in clusters]),"semantic_metadata_consumed":False,"visual_review_performed":False,"unknowns_not_zero":True,"method":"typed DNA anchors + missing-aware weighted distance + deterministic complete-link; trial thresholds, not human-calibrated universal metric","thresholds":{"CMF":.20,"ID":.24}})]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"records":len(records),"units":len(units),"clusters":len(clusters),"largest":[{"id":c["cluster_id"],"branch":c["branch"],"images":c["image_count"]} for c in sorted(clusters,key=lambda x:-x["image_count"])[:12]]},ensure_ascii=False))
if __name__=="__main__":main()

