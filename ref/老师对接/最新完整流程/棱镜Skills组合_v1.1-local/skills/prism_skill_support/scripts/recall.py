"""Historical literal recall shape, configurable to the new visual brief. No model."""
from pathlib import Path
from collections import defaultdict,Counter
import argparse,json
from io_utils import read,write,ref

def recall(records,config):
    groups=config['term_groups']
    if not groups or any(not g for g in groups):raise ValueError('Nonempty visible-relation term groups required')
    weights=config.get('field_weights',{'title':3,'summary':1,'tags':1.5,'imported_visual_description_raw':.25})
    rows=[]
    for r in records:
        if r.get('excluded_reason') or not r.get('image_urls'):continue
        hits=[];score=0
        for terms in groups:
            found=[]
            for term in terms:
                values=[weight for field,weight in weights.items() if term.casefold() in str(r.get(field,'')).casefold()]
                if values:found.append(term);score+=max(values)
            hits.append(found)
        if any(not g for g in hits):continue
        if r.get('primary_theme_id') in config.get('selected_theme_ids',[]):score+=config.get('theme_bonus',2)
        rows.append({**r,'literal_recall_score':score,'recall_hits':hits,'reference_role':'post_H01_visual_reference_candidate','original_semantic_membership_changed':False,'visual_qualification':False})
    rows.sort(key=lambda r:(-r['literal_recall_score'],str(r['article_id'])))
    limit=int(config.get('maximum_text_candidates',90));head=min(int(config.get('head_count',45)),limit);chosen=rows[:head];buckets=defaultdict(list)
    for r in rows[head:]:buckets[str(r.get('category_original','unknown'))].append(r)
    while len(chosen)<limit and any(buckets.values()):
        for key in sorted(buckets,key=lambda k:-(buckets[k][0]['literal_recall_score'] if buckets[k] else float('-inf'))):
            if buckets[key] and len(chosen)<limit:chosen.append(buckets[key].pop(0))
    return {'total_recalled':len(rows),'selected':chosen,'distribution':dict(Counter(str(r.get('category_original','unknown')) for r in chosen)),'method':'literal fields + coverage balancing; neither semantic support nor image coherence','all_recall':rows}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--corpus',required=True);p.add_argument('--config',required=True);p.add_argument('--out',required=True);a=p.parse_args();data=read(a.corpus);records=data if isinstance(data,list) else data['records'];result=recall(records,read(a.config));result['source_refs']=[ref(a.corpus),ref(a.config)];write(a.out,result);print(json.dumps({'selected':len(result['selected']),'recalled':result['total_recalled'],'model_calls':0}))
