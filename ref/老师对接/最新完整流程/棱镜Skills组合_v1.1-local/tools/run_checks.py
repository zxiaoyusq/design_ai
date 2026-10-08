"""Offline portable smoke/regression runner. Does not call a model or network."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]

def run(out,native=False):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);tmp=out/'tmp';tmp.mkdir()
    skills=ROOT/'skills';env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';env['PRISM_TEST_ROOT']=str(out);env['TEMP']=str(tmp);env['TMP']=str(tmp)
    env['PYTHONPATH']=str(skills/'prism_skill_support/runtime')+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    jobs=[('native-doctor',[str(skills/'prism_skill_support/scripts/native_api.py'),'doctor']),('R5-replay',[str(skills/'prism-dna-sol-r5/scripts/cli.py'),'self-test']),('research-boundaries',[str(skills/'prism-research-semantic-clustering/scripts/selftest.py'),'--out',str(out/'research')]),('H01-boundaries',[str(skills/'prism-h01-semantic-handshake/scripts/selftest.py'),'--out',str(out/'H01')]),('portable-glue',[str(ROOT/'tools/checks/test_helpers.py')])]
    if native:jobs.append(('native-ID-CMF-alias',['-m','unittest','prism_runtime.clustering.id_reference_board_v5.tests','prism_runtime.clustering.cmf_reference_board_v4.tests','prism_runtime.clustering.r5_exact_byte_alias_v1.tests']))
    results=[]
    for name,args in jobs:
        start=time.monotonic();r=subprocess.run([sys.executable,'-B','-X','utf8',*args],capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,cwd=out,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/(name+'.stdout.txt')).write_text(r.stdout,encoding='utf-8');(out/(name+'.stderr.txt')).write_text(r.stderr,encoding='utf-8');results.append({'check':name,'exit_code':r.returncode,'wall_seconds':round(time.monotonic()-start,3),'stdout':name+'.stdout.txt','stderr':name+'.stderr.txt'});print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    report={'status':'passed' if all(r['exit_code']==0 for r in results) else 'failed','results':results,'new_model_calls':0,'semantic_or_visual_accuracy_proven':False,'recorded_at':datetime.now(timezone.utc).isoformat()};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--native',action='store_true');a=p.parse_args();r=run(a.out,a.native);sys.exit(0 if r['status']=='passed' else 2)
