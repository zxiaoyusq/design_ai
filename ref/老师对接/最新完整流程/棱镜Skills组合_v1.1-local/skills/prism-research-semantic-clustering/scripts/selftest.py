"""Offline behavior checks with fictional sources; no model call and no accuracy claim."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import research as r

def run(output):
    root=r.new_dir(output);base=Path(__file__).resolve().parent.parent/'examples'
    r.prepare_run(root/'run',base/'research-input.synthetic.json')
    run=root/'run';proposal=r.p.read(base/'proposal.synthetic.template.json')
    proposal['input_binding']=r.p.bind(run/'dataset')
    checks=[]
    def reject(name,mutate):
        value=deepcopy(proposal);mutate(value)
        try:r.compiler.validate_and_compile(run/'dataset',value)
        except (ValueError,KeyError,TypeError):checks.append({'name':name,'passed':True});return
        raise AssertionError('unexpected acceptance: '+name)
    compiled=r.compiler.validate_and_compile(run/'dataset',proposal)
    assert compiled['clusters'][0]['statistics']['direct_design_support_count']==2
    checks.append({'name':'same_person_repeat_does_not_add_support','passed':True})
    assert compiled['summary']['original_negative_units']==2 and compiled['summary']['negative_units_retained']==2
    checks.append({'name':'unclustered_negative_retained_in_coverage','passed':True})
    assert compiled['clusters'][3]['statistics']['direct_design_support_count']==0 and compiled['clusters'][3]['statistics']['brand_impression_count']==1
    checks.append({'name':'brand_and_example_not_direct_design_votes','passed':True})
    assert '但小边框亮一点可以' in compiled['clusters'][0]['members'][3]['whole_source_unit']
    checks.append({'name':'full_negative_degree_and_exception_survive','passed':True})
    reject('rewritten_quote_rejected',lambda v:v['clusters'][0]['members'][0].update(quote='原文没有的金色偏好'))
    reject('negative_to_positive_rejected',lambda v:v['clusters'][0]['members'][3].update(relation='support'))
    reject('background_to_design_vote_rejected',lambda v:v['clusters'][2]['members'][0].update(relation='support'))
    reject('concept_example_to_support_rejected',lambda v:v['clusters'][3]['members'][1].update(relation='support'))
    reject('missing_unit_coverage_rejected',lambda v:v['coverage'].pop())
    reject('stale_input_binding_rejected',lambda v:v['input_binding'].update(dataset_id='different'))
    reject('coverage_and_membership_disagreement_rejected',lambda v:v['coverage'][0].update(cluster_ids=[]))
    reject('negative_disappears_as_generic_reference_rejected',lambda v:v['coverage'][7].update(disposition='reference_only'))
    reject('duplicate_member_rejected',lambda v:v['clusters'][0]['members'].append(deepcopy(v['clusters'][0]['members'][0])))
    # Duplicate original IDs cannot be hidden by dict construction in the upstream compiler.
    incoming=r.p.read(base/'research-input.synthetic.json');incoming['units'].append(deepcopy(incoming['units'][0]))
    try:r.normalize(incoming,root/'invalid')
    except ValueError:checks.append({'name':'duplicate_source_unit_rejected','passed':True})
    else:raise AssertionError('duplicate source unit accepted')
    r.p.write(root/'proposal.json',proposal);r.accept(run,root/'proposal.json');r.verify(run)
    checks.append({'name':'complete_result_replays','passed':True})
    changed=r.p.read(run/'clusters.json');changed['clusters'][0]['title']='篡改'
    r.p.write(run/'clusters.json',changed)
    try:r.verify(run)
    except ValueError:checks.append({'name':'tampered_result_rejected','passed':True})
    else:raise AssertionError('tampered result accepted')
    report={'status':'passed','checks':checks,'passed':len(checks),'model_calls':0,'semantic_accuracy_proven':False}
    r.p.write(root/'test-results.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    print(json.dumps(run(a.out),ensure_ascii=False,indent=2))
