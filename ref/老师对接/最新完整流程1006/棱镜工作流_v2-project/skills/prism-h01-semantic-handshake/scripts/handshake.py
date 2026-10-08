"""Freeze, prepare, validate and select H01 semantic candidates. No image/model execution."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from h01_core import h01
from h01_core.common import read, write, need, identity, digest, verify as verify_seal

HERE=Path(__file__).resolve().parent
RESEARCH_FILES=['semantic-units.jsonl','people.json','raw-evidence.jsonl','picture-contexts.jsonl',
    'image-display-views.jsonl','selection-groups.jsonl','concept-example-links.jsonl','data-contract.json']

def fresh(path):
    path=Path(path).resolve()
    need(not path.exists(),'Use a new artifact directory: '+str(path))
    path.mkdir(parents=True)
    return path

def check_dependencies():
    try:
        import jsonschema
    except ImportError as e:
        raise ValueError('Install requirements.txt using this Python interpreter before preparing H01.') from e

def prepare(config_path, output):
    check_dependencies()
    config_path=Path(config_path).resolve()
    config=read(config_path)
    out=fresh(output)
    resolved={}
    for key in ['research_dataset_path','research_run_path','trend_clusters_path','trend_catalogue_path','trend_associations_path']:
        if not config.get(key):continue
        source=Path(config[key])
        if not source.is_absolute():source=config_path.parent/source
        resolved[key]=source.resolve()
    provenance=[]
    def copy(src,dest):
        dest.parent.mkdir(parents=True,exist_ok=True)
        ref=identity(src)
        shutil.copyfile(src,dest)
        need(identity(src)==ref and identity(dest)['sha256']==ref['sha256'],'Source changed while freezing')
        provenance.append({'original':ref,'frozen':str(dest.relative_to(out)).replace('\\','/'),'sha256':ref['sha256']})
    for name in RESEARCH_FILES:copy(resolved['research_dataset_path']/name,out/'inputs/research/dataset'/name)
    for name in ['clusters.json','handshake-input.json','analyst-proposal.json','handoff.json']:
        copy(resolved['research_run_path']/name,out/'inputs/research/run'/name)
    config['research_dataset_path']=str(out/'inputs/research/dataset')
    config['research_run_path']=str(out/'inputs/research/run')
    for key in ['trend_clusters_path','trend_catalogue_path','trend_associations_path']:
        if key in resolved:
            dest=out/'inputs/trends'/(key+'.json')
            copy(resolved[key],dest)
            config[key]=str(dest)
    prepared=h01.prepare_h01(config)
    write(out/'prepared.json',prepared)
    write(out/'config.frozen.json',config)
    write(out/'input-freeze.json',{'files':provenance,'model_calls':0})
    request=prepared['request']
    write(out/'messages.json',request['messages'])
    write(out/'response-schema.json',request['response_schema'])
    write(out/'response-schema.wire.json',request['wire_response_schema'])
    write(out/'schema-transport-audit.json',request['schema_transport_audit'])
    write(out/'acceptance-scope.json',{'status':'awaiting_semantic_model_proposal','schema_version':request['schema_version'],
        'modalities':['text'],'DNA_jobs':0,'quality_jobs':0,'selection_made':False,
        'semantic_accuracy_proven':False,'model_calls_by_scripts':0})
    return {'status':'ready_for_semantic_proposal','request_snapshot':request['request_snapshot'],
        'trend_clusters':len(prepared['trends']['clusters']),'research_clusters':len(prepared['research']['clusters']),
        'negative_units':len(prepared['research']['negative_unit_ids']),'run':str(out),'image_calls':0}

def accept(run, proposal):
    run=Path(run).resolve()
    need(not (run/'accepted.json').exists(),'accepted.json exists; use a new run for revisions')
    prepared=read(run/'prepared.json')
    # Validate original first, then preserve an immutable copy bound to this run.
    h01.accept_h01(prepared,proposal)
    write(run/'response.json',read(proposal))
    accepted=h01.accept_h01(prepared,run/'response.json')
    write(run/'accepted.json',accepted)
    write(run/'candidate-directions.json',accepted['workflow_candidates'])
    return {'status':accepted['status'],'directions':len(accepted['response']['directions']),
        'negative_audit_cells':len(accepted['response']['directions'])*len(prepared['research']['negative_unit_ids']),
        'semantic_accuracy_proven':False,'selection_made':False,'model_calls_by_scripts':0}

def verify_run(run):
    run=Path(run).resolve()
    prepared,accepted=read(run/'prepared.json'),read(run/'accepted.json')
    verify_seal(accepted)
    need(accepted==h01.accept_h01(prepared,accepted['response_identity']['path']),'acceptance does not replay')
    need(read(run/'candidate-directions.json')==accepted['workflow_candidates'],'candidate export changed')
    return {'status':'verified','directions':len(accepted['response']['directions']),
        'semantic_accuracy_proven':False,'model_calls_by_scripts':0}

def select(run, choices_path, confirmation_path):
    verify_run(run)
    run=Path(run).resolve()
    choices,confirmation=read(choices_path),read(confirmation_path)
    result=h01.select(read(run/'prepared.json'),read(run/'accepted.json'),choices,confirmation)
    write(run/'selection.json',result)
    return {'status':'selection_recorded','selected_count':len(result['selection']),
        'actor_kind':confirmation['actor_kind'],'image_jobs_started':0,'identity_authentication':'trusted_caller_responsibility'}

def selection_template(run, choices_path, output):
    verify_run(run)
    run=Path(run).resolve()
    choices=read(choices_path)
    # This receipt has no approval. A real reviewer must supply attributable confirmation.
    template={'status':'pending','actor_kind':None,'actor_id':None,'source_ref':None,
        'candidate_digest':read(run/'accepted.json')['workflow_candidates']['digest'],
        'selection_digest':digest(choices),'current_scope_delegation_ref':None}
    write(output,template)
    return {'status':'pending_selection_confirmation','output':str(output),'approval_created':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    q=sub.add_parser('prepare');q.add_argument('--config',required=True);q.add_argument('--out',required=True)
    q=sub.add_parser('accept');q.add_argument('--run',required=True);q.add_argument('--proposal',required=True)
    q=sub.add_parser('verify');q.add_argument('--run',required=True)
    q=sub.add_parser('select');q.add_argument('--run',required=True);q.add_argument('--choices',required=True);q.add_argument('--confirmation',required=True)
    q=sub.add_parser('selection-template');q.add_argument('--run',required=True);q.add_argument('--choices',required=True);q.add_argument('--out',required=True)
    a=parser.parse_args()
    try:
        if a.command=='prepare':result=prepare(a.config,a.out)
        elif a.command=='accept':result=accept(a.run,a.proposal)
        elif a.command=='verify':result=verify_run(a.run)
        elif a.command=='selection-template':result=selection_template(a.run,a.choices,a.out)
        else:result=select(a.run,a.choices,a.confirmation)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError,TypeError) as e:
        print(json.dumps({'status':'rejected','reason':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':sys.exit(main())
