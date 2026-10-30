"""Canonical admission of explicit model values; retain raw stage artifacts.
For an initially missing value, 'present + value' is an explicit positive answer,
not a value contradiction. This adapter fixes that status-only protocol trap.
"""
import copy
import re
import algorithm as a
from algorithm import ROOT,c

def finalize(cid):
    f=c.read(ROOT/'final'/(cid+'.json'));local=copy.deepcopy(f['local_features']);pending=copy.deepcopy(f['pending']);changes=[]
    for decision in f['decisions']:
        issue,result=decision['issue'],decision['result']
        if issue['kind']=='missing' and result and result['decision']=='present' and result['value'] is not None:
            ok,_=a.valid_value(issue['fact']['p'],result['value'])
            if ok:
                fact={**issue['fact'],'v':a.r3.unwrap(result['value']),'source':'F-'+cid,'evidence':result['evidence']}
                local.append(fact);changes.append({'kind':'explicit_positive_for_missing_field','fact':fact,'host_value_inference':False})
                pending=[x for x in pending if x.get('issue',{}).get('fact',{}).get('path')!=issue['fact']['path']]
    extra=ROOT/'refined'/(cid+'.json')
    if extra.exists():
        r=c.read(extra)
        if r['answer'] is not None:
            if cid=='HP01':
                source_raw=c.read(ROOT/'calls/P-HP01/answer.json')
                names={source_raw['areas'][int(i)]['name'] for i in r['selected_indices']}
                local=[x for x in local if not (x['source']=='P-HP01' and x['at'] in names)]
                for key,group in r['answer']['groups'].items():
                    raw={'areas':group['areas'],'overall':[],'uncertain':[]}
                    u=a.unpack(raw,'H-HP01')
                    for x in u['direct']:
                        x['path']='/groups/'+key+x['path'];x['evidence']=group['evidence']
                    local+=u['direct'];pending+=u['issues']+u['overflow']
                changes.append({'kind':'replaced_mixed_areas','indices':r['selected_indices'],'appended_old_and_new':False})
            else:
                keys={c.canonical([x['at'],x['p']]) for x in r['targets']}
                local=[x for x in local if c.canonical([x['at'],x['p']]) not in keys]
                for i,target in enumerate(r['targets']):
                    result=r['answer']['checks'][str(i)]
                    if result['decision']=='supported' and result['value'] is not None and a.valid_value(target['p'],result['value'])[0]:
                        local.append({**target,'v':a.r3.unwrap(result['value']),'source':'H-MC01','evidence':result['evidence']})
                    else:pending.append({'issue':target,'result':result})
                changes.append({'kind':'optical_checks_replaced','targets':len(r['targets'])})
        f['processing_seconds']=round(f['processing_seconds']+r['seconds'],4)
        f['model_seconds']=round(f['model_seconds']+r['receipt']['wall_seconds'],4)
        f['token_cost_estimate_usd']=round(f['token_cost_estimate_usd']+(r['cost'] or 0),6)
    unique={c.canonical([x['at'],x['p'],x['v']]):x for x in local};local=list(unique.values())
    ix,_=a.r3.normalize([{'feature':x,'source':x['source']} for x in local])
    f.update(local_features=local,features=ix,pending=pending,pending_count=len(pending),admission_adjustments=changes,
        final_local_features=len(local),final_local_CMF=sum(x['p'] in a.CMF for x in local),
        image_unique_features=len(ix),image_unique_CMF=sum(x['parameter_id'] in a.CMF for x in ix),
        ID_unique=sum('ID' in x['views'] for x in ix),CMF_unique=sum('CMF' in x['views'] for x in ix),
        shared_unique=sum(len(x['views'])==2 for x in ix),original_stage_final_ref=str(ROOT/'final'/(cid+'.json')))
    out=ROOT/'accepted'/(cid+'.json');out.parent.mkdir(exist_ok=True)
    out.write_text(c.canonical(f)+'\n',encoding='utf-8')
    print(c.canonical({k:f[k] for k in ['image_id','final_local_features','final_local_CMF','image_unique_features','image_unique_CMF','pending_count','processing_seconds','token_cost_estimate_usd']}),flush=True)
    return f

if __name__=='__main__':
    for path in sorted((ROOT/'final').glob('*.json')):finalize(path.stem)
