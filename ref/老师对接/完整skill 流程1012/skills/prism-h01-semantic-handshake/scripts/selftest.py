"""Behavior tests of H01 provenance, role and selection boundaries. Offline synthetic only."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import shutil
import handshake as h
from h01_core.common import read,write,digest
from h01_core import h01

def run(output):
    root=h.fresh(output);base=Path(__file__).resolve().parent.parent/'examples'
    # Exercise data/code boundary using a hostile supplied method directory.
    shutil.copytree(base,root/'input')
    injected=root/'input/research/dataset/_methods';injected.mkdir()
    (injected/'compile.py').write_text('raise RuntimeError("UNTRUSTED CODE EXECUTED")',encoding='utf-8')
    h.prepare(root/'input/config.synthetic.json',root/'run')
    prepared=read(root/'run/prepared.json')
    reply=read(base/'proposal.synthetic.template.json');reply['request_snapshot']=prepared['request']['request_snapshot']
    checks=[{'name':'dataset_embedded_python_not_executed','passed':True}]
    def reject(name,mutate):
        value=deepcopy(reply);mutate(value);path=root/(name+'.json');write(path,value)
        try:h01.accept_h01(prepared,path)
        except (ValueError,KeyError,TypeError):checks.append({'name':name,'passed':True});return
        raise AssertionError('unexpected acceptance: '+name)
    reject('missing_negative_row_rejected',lambda v:v['negative_audit'].pop())
    reject('missing_negative_direction_cell_rejected',lambda v:v['negative_audit'][0].update(impacts=[]))
    reject('duplicated_negative_direction_rejected',lambda v:v['negative_audit'][0]['impacts'].append({'state':'unresolved','direction_ids':['D1'],'reason':'duplicate'}))
    reject('rewritten_research_quote_rejected',lambda v:v['directions'][0]['research_citations'][0].update(text='受访者没有说过的金色'))
    reject('negative_to_direct_support_rejected',lambda v:v['directions'][0]['research_citations'][2].update(role='direct_support'))
    def brand(v):
        v['directions'][0]['research_cluster_ids'].append('RC4')
        v['directions'][0]['research_citations'].append({'unit_id':'U5','text':'这个虚构品牌给我可靠、耐用的印象。','role':'direct_support','reason':'incorrect'})
    reject('brand_is_not_direct_design_preference',brand)
    reject('trend_text_kind_relabelling_rejected',lambda v:v['directions'][0]['trend_citations'][0].update(text_kind='source_paraphrase'))
    reject('invented_boundary_rejected',lambda v:v['directions'][0]['conditions_and_limits'][0].update(basis_kind='research_cluster_boundary',reference_id='RC1',text='没有在原边界出现的句子'))
    reject('hidden_extension_under_direct_support_rejected',lambda v:v['directions'][0]['hypotheses'].append('跨产品假设'))
    def extension(v):v['directions'][0].update(relation_basis='anchored_extension',hypotheses=['跨产品'],extension_explanation='explicit')
    reject('consensus_mode_does_not_allow_extension',extension)
    reject('missing_cluster_outcome_rejected',lambda v:v['research_cluster_coverage'].pop())
    reject('stale_request_snapshot_rejected',lambda v:v.update(request_snapshot='wrong'))
    path=root/'proposal.json';write(path,reply);h.accept(root/'run',path);h.verify_run(root/'run')
    checks.append({'name':'complete_bound_result_replays','passed':True})
    assert prepared['options']['requested_selection_count']==1
    payload=json.loads(prepared['request']['messages'][1]['content'])
    assert payload['requested_selection_count_later']==1 and prepared['DNA_jobs_before_selection']==0 and prepared['quality_jobs_before_selection']==0
    checks.append({'name':'configurable_count_and_no_preselection_image_jobs','passed':True})
    # A research negative with unknown object remains unresolved in the accepted matrix.
    accepted=read(root/'run/accepted.json')
    assert accepted['response']['negative_audit'][1]['impacts'][0]['state']=='unresolved'
    checks.append({'name':'unknown_negative_not_silently_not_applicable','passed':True})
    choices=read(base/'choices.synthetic.json')
    conf={'status':'pending','actor_kind':'human_designer','actor_id':'test','source_ref':'synthetic:receipt',
        'candidate_digest':accepted['workflow_candidates']['digest'],'selection_digest':digest(choices)}
    try:h01.select(prepared,accepted,choices,conf)
    except ValueError:checks.append({'name':'pending_is_not_confirmation','passed':True})
    else:raise AssertionError('pending accepted')
    conf.update(status='confirmed',actor_kind='user_delegated_ai')
    try:h01.select(prepared,accepted,choices,conf)
    except ValueError:checks.append({'name':'AI_selection_requires_current_scope_delegation','passed':True})
    else:raise AssertionError('AI invented delegation accepted')
    conf.update(actor_kind='synthetic_fixture');h01.select(prepared,accepted,choices,conf)
    checks.append({'name':'explicit_synthetic_selection_works_only_as_fixture','passed':True})
    # Seal checks catch change to a frozen text source after preparation.
    target=root/'run/inputs/trends/trend_catalogue_path.json'
    target.write_text(target.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    try:h.verify_run(root/'run')
    except ValueError:checks.append({'name':'frozen_input_change_rejected','passed':True})
    else:raise AssertionError('source change accepted')
    report={'status':'passed','passed':len(checks),'checks':checks,'model_calls':0,'semantic_accuracy_proven':False}
    write(root/'test-results.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    print(json.dumps(run(a.out),ensure_ascii=False,indent=2))
