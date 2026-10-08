"""Publish auditable offline examples; never disguise calibration as trend."""
from pathlib import Path
import json
from .adapter import adapt_file

WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT = WORKSPACE/'outputs/prism-algorithm-loop-20260926/modules/quality'
EXPERIMENTS = WORKSPACE/'outputs/prism-quality-pilot-20260926'

def dump(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(v,ensure_ascii=False,indent=2)+'\n'
    if p.exists() and p.read_text(encoding='utf-8') != encoded:
        raise RuntimeError('Example changed; use a new output version rather than overwrite')
    if not p.exists():p.write_text(encoded,encoding='utf-8')

def main():
    examples=[]
    plans=[
        ('current-calibration-pass','B08-T04','calibration',EXPERIMENTS/'designer-boards-round2-v06/resolved/B08-T04.json',True),
        ('original-calibration-fail','B08-T04','calibration',EXPERIMENTS/'designer-boards-round2/runs/B08-T04/result.json',True),
        ('original-invalid-output','B07-T04','calibration',EXPERIMENTS/'designer-boards-round2/runs/B07-T04/result.json',True),
        ('old-calibration-pass','u001','calibration',EXPERIMENTS/'ee1-cmf-calibration-v052/runs/u001/result.json',True),
        ('research-bypass','research-example','research',OUTPUT/'intentionally-not-present.json',False),
        ('generated-bypass','generated-example','generated',OUTPUT/'intentionally-not-present.json',False),
        ('unknown-bypass','unknown-example','unknown',OUTPUT/'intentionally-not-present.json',False),
    ]
    for d in ['PASS','FAIL']:
        name='synthetic-trend-'+d.lower();iid=name
        raw={'image_id':iid,'version':'synthetic-interface-fixture-v1','valid':True,'validation_errors':[],
             'http_status':200,'output':{'decision':d,'reason':'Synthetic contract fixture; not a real visual judgement.',
                                      'positive_evidence':[],'negative_evidence':[]},
             'provenance':{'mode':'synthetic'}}
        raw_path=OUTPUT/'fixtures'/(name+'-raw.json');dump(raw_path,raw)
        plans.append((name,iid,'trend',raw_path,False))
    for name,iid,kind,result_path,calibration in plans:
        image={'schema_version':'prism.image_dna.v0.1','image_id':iid,'source_kind':kind,
               'image_path':None,'source_ref':str(result_path),'observations':[],
               'provenance':{'mode':'synthetic' if name.startswith('synthetic') or kind in ['research','generated','unknown'] else 'existing_model_output',
                             'parser_version':'not_invoked_for_quality_adapter_example'},
               'quality_example_note':'Identity and provenance subset only; not a DNA parsing result.'}
        if kind=='calibration':
            image['provenance']['source_kind_authority']='User-approved calibration experiment; not production trend ingestion.'
        ip=OUTPUT/'examples'/(name+'-input.json');op=OUTPUT/'examples'/(name+'-output.json')
        dump(ip,image)
        result=adapt_file(image,result_path,calibration_only=calibration)
        dump(op,result)
        examples.append({'name':name,'input':str(ip),'existing_result':str(result_path),'output':str(op),
                         'calibration_only':calibration,'status':result['status'],
                         'decision':result['decision'],'source_kind':kind,'new_paid_calls':0})
    dump(OUTPUT/'examples-index.json',examples)
    print(json.dumps({'examples':len(examples),'new_paid_calls':0}))

if __name__=='__main__':main()
