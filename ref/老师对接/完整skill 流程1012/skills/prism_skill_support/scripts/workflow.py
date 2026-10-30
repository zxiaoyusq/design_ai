"""Local stage ledger and exact-input reuse decisions. Never dispatches models."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json
from io_utils import read,write,fresh,ref,digest,checked,resolve

STAGES=['research-intake','research-semantics','trend-semantics','H01','selection','visual-family','source-images','DNA','DNA-clustering','style-review','target-view','quality','H2-ID','H2-CMF','view-processing','board-review','delivery']
def cache_key(job):
    if not job.get('algorithm_version') or not job.get('semantic_inputs'):raise ValueError('Cache needs an explicit algorithm version and semantic inputs')
    return digest({k:job.get(k) for k in ('stage','algorithm_version','model_policy','semantic_inputs','processing_config')})
def init(config,out):
    config=Path(config).resolve();cfg=read(config)
    if not isinstance(cfg.get('model_policy',{}),dict):raise ValueError('model_policy must be an explicit object; this ledger does not dispatch models')
    # A frozen config moves directories; rebind only its explicitly declared local inputs.
    # The source copy and base directory remain auditable, and missing paths stay missing.
    source=read(config);bindings=[]
    def bind(value,key):
        if isinstance(value,dict):return {k:bind(v,key+'.'+k) for k,v in value.items()}
        if isinstance(value,list):return [bind(v,key+'['+str(i)+']') for i,v in enumerate(value)]
        if value is None:return None
        if not isinstance(value,str) or not value.strip():raise ValueError('Input paths must be nonempty local paths or explicit URLs')
        if value.startswith(('https://','http://')):
            bindings.append({'key':key,'original':value,'kind':'URL_not_fetched'});return value
        path=resolve(value,config.parent)
        bindings.append({'key':key,'original':value,'resolved':str(path),'exists':path.exists(),'file_ref':ref(path) if path.is_file() else None})
        return str(path)
    if 'input_paths' in cfg:cfg['input_paths']=bind(cfg['input_paths'],'input_paths')
    cfg['input_path_binding']={'source_config_ref':ref(config),'base_directory':str(config.parent),'bindings':bindings,'no_input_was_fetched_or_fabricated':True}
    folder=fresh(out);write(folder/'project.source.json',source);write(folder/'project.frozen.json',cfg)
    write(folder/'state.json',{'project_id':cfg['project_id'],'status':'prepared','stages':{},'issues':{},'models_dispatched_by_this_tool':0,'source_config_ref':ref(folder/'project.source.json'),'config_ref':ref(folder/'project.frozen.json')})
    return {'run':str(folder),'stages':STAGES,'model_calls':0}
def record(run,job,outcome):
    run=Path(run).resolve();j=read(job);o=read(outcome);p=run/'state.json';s=read(p)
    if j['stage'] not in STAGES:raise ValueError('Unknown stage')
    if o.get('status') not in ('complete','failed','partial','prepared','waiting_for_user'):raise ValueError('Explicit stage status required')
    if o['status']=='complete' and not o.get('artifact_refs'):raise ValueError('Complete stage needs actual output artifacts')
    key=cache_key(j)
    for r in o.get('artifact_refs',[]):checked(r,False)
    entry={'cache_key':key,'job_ref':ref(job),'outcome_ref':ref(outcome),'status':o['status'],'artifacts':o.get('artifact_refs',[]),'recorded_at':datetime.now(timezone.utc).isoformat()}
    old=s['stages'].get(j['stage'])
    if old and old['cache_key']==key and old['status']=='complete':
        for r in old['artifacts']:checked(r,False)
        return {'action':'reuse_same_version_and_semantic_input','new_model_calls':0}
    if old:
        version=len(list((run/'history').glob('*.json'))) if (run/'history').exists() else 0
        write(run/'history'/f'{version:04}-{j["stage"]}.json',old)
    s['stages'][j['stage']]=entry
    if o.get('issue_id'):
        issue=s['issues'].setdefault(o['issue_id'],{'attempts':0,'status':'open'});issue['attempts']+=1;issue['status']='needs_method_or_user_decision' if issue['attempts']>=3 else 'open';issue['last_outcome_ref']=ref(outcome)
    # A bounded issue is not authority to terminate or mark the whole objective done.
    s['status']='in_progress';s['updated_at']=datetime.now(timezone.utc).isoformat();p.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'stage_recorded':j['stage'],'issue_status':s['issues'].get(o.get('issue_id')),'project_status':s['status'],'model_calls':0}
if __name__=='__main__':
    p=argparse.ArgumentParser();a=p.add_subparsers(dest='cmd',required=True)
    q=a.add_parser('init');q.add_argument('--config',required=True);q.add_argument('--out',required=True)
    q=a.add_parser('record');q.add_argument('--run',required=True);q.add_argument('--job',required=True);q.add_argument('--outcome',required=True)
    q=a.add_parser('status');q.add_argument('--run',required=True)
    q=a.add_parser('cache-key');q.add_argument('--job',required=True)
    r=p.parse_args();out=init(r.config,r.out) if r.cmd=='init' else record(r.run,r.job,r.outcome) if r.cmd=='record' else read(Path(r.run)/'state.json') if r.cmd=='status' else {'cache_key':cache_key(read(r.job))};print(json.dumps(out,ensure_ascii=False))
