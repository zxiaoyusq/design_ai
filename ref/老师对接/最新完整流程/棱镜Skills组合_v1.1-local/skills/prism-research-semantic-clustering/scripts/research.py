"""Portable CLI around the source research compiler. No network or LLM transport."""
import argparse
from contextlib import redirect_stdout
from io import StringIO
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE / 'research_core'
sys.path.insert(0, str(CORE))
import prepare as p

spec = importlib.util.spec_from_file_location('research_cluster_compiler', CORE / 'compile.py')
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)

def need(ok, message):
    if not ok: raise ValueError(message)

def unique(rows, key):
    need(isinstance(rows, list), key + ': expected list')
    out = {}
    for row in rows:
        value = row.get(key)
        need(isinstance(value, str) and value.strip() and value not in out, 'missing/duplicate ' + key)
        out[value] = row
    return out

def new_dir(path):
    path = Path(path).resolve()
    need(not path.exists(), 'Use a new output directory: ' + str(path))
    path.mkdir(parents=True)
    return path

def pins():
    return {str(x.relative_to(HERE)).replace('\\', '/'):p.sha(x) for x in HERE.rglob('*')
            if x.is_file() and x.suffix in {'.py','.json','.md'} and '__pycache__' not in x.parts}

def normalize(value, output):
    """One-to-one text adapter. Never infer sentiment, features, people or image links."""
    need(value.get('schema_version') == 'prism.research_semantic_input.v1', 'wrong input version')
    need(value.get('dataset_id'), 'dataset_id required')
    need(value.get('dataset_mode') in {'synthetic_fixture','real_or_public'}, 'label dataset_mode')
    people = unique(value.get('people'), 'person_id')
    sources = unique(value.get('sources'), 'source_id')
    units = unique(value.get('units'), 'unit_id')
    need(people and units and sources, 'nonempty people, units and sources required')
    kinds = compiler.DIRECT | {'brand_preference_or_impression','personal_identity_goal',
        'character_association','elicited_concept_image_example','reference'}
    attitudes = compiler.POSITIVE | {'dislike','neutral','unknown','association','aspiration'}
    raw, rows = [], []
    for u in units.values():
        need(u.get('person_id') in people and u.get('source_id') in sources, 'unknown person/source')
        need(u.get('kind') in kinds and u.get('attitude') in attitudes, 'unsupported kind/attitude; retain unknown rather than guessing')
        need(isinstance(u.get('text'), str) and u['text'].strip(), 'full original text required')
        need(u.get('locator') and 'scope' in u, 'source locator and scope (null when unknown) required')
        need(not u.get('image_links'), 'text import cannot manufacture image associations; use the native dataset for existing verified links')
        for k in ('image_features','dna','quality','embedding','supported'):
            need(k not in u, 'this input is semantic-only: ' + k)
        eid = u['unit_id'] + ':original'
        raw.append({'evidence_id':eid,'person_id':u['person_id'],'source_id':u['source_id'],
            'text':u['text'],'locator':u['locator'],'evidence_kind':sources[u['source_id']]['evidence_kind']})
        rows.append({'semantic_unit_id':u['unit_id'],'person_id':u['person_id'],'source_id':u['source_id'],
            'source_text':u['text'],'kind':u['kind'],'attitude':u['attitude'],'scope':u['scope'],
            'page':u.get('page'),'slide_id':u['locator'],'target_entity_label':u.get('target_entity'),
            'quotes':[{'evidence_id':eid,'text':u['text']}],
            'contrast_or_limit_markers':u.get('contrast_or_limit_markers',[]),
            'image_links':[],'source_page_image_occurrence_ids':[],
            'independent_review_status':'not_performed'})
    for row in people.values(): need(row.get('display_name'), 'person display_name required; pseudonyms allowed')
    for row in sources.values():
        need(row.get('evidence_kind') in {'synthetic_fixture','document_excerpt','transcript_excerpt','public_post','analyst_notes'}, 'explicit evidence kind required')
        need(row.get('label') and row.get('locator'), 'source label/locator required')
    output.mkdir(parents=True, exist_ok=False)
    compiler.jsonl(output/'semantic-units.jsonl', rows)
    compiler.jsonl(output/'raw-evidence.jsonl', raw)
    p.write(output/'people.json', list(people.values()))
    for name in ('picture-contexts.jsonl','image-display-views.jsonl','selection-groups.jsonl','concept-example-links.jsonl'):
        (output/name).write_text('', encoding='utf-8')
    p.write(output/'data-contract.json', {'dataset_id':value['dataset_id'], 'dataset_mode':value['dataset_mode'],
        'sources':list(sources.values()),'source_import':'one_to_one_text_no_OCR_or_document_truth_verification',
        'original_input_digest':p.digest(value),'image_associations':'not_supplied'})

def check_dataset(dataset):
    people = unique(p.read(dataset/'people.json'), 'person_id')
    units = unique(p.lines(dataset/'semantic-units.jsonl'), 'semantic_unit_id')
    raw = unique(p.lines(dataset/'raw-evidence.jsonl'), 'evidence_id')
    unique(p.lines(dataset/'picture-contexts.jsonl'), 'occurrence_id')
    need(units and people, 'empty research dataset')
    for u in units.values():
        need(u.get('person_id') in people and u.get('source_id'), 'unit person/source missing')
        need(u.get('source_text') and u.get('quotes'), 'unit original text/quotes missing')
        # Preserve the source chain for every unit, including unclustered evidence.
        for q in u['quotes']:
            e = raw.get(q['evidence_id'])
            need(e and e['text']==q['text'] and e['person_id']==u['person_id'] and e['source_id']==u['source_id'], 'raw quote binding mismatch')
        need(any(u['source_text'] == q['text'] or u['source_text'] in q['text'] for q in u['quotes']) or
             u.get('kind') in {'selected_board_reason','brand_preference_or_impression','personal_identity_goal','character_association','elicited_concept_image_example','phone_preference_reason','explicit_cmf_caption','selected_style_word','reference'}, 'unsupported source shape')
    return units

def prepare_run(out, source=None, native=None):
    out = new_dir(out)
    dataset = out/'dataset'
    if source:
        value = p.read(source)
        normalize(value, dataset)
        shutil.copy2(source, out/'original-input.json')
    else:
        dataset.mkdir()
        for name in p.INPUT_FILES: shutil.copy2(Path(native)/name, dataset/name)
    check_dataset(dataset)
    with redirect_stdout(StringIO()): p.prepare(dataset, out)
    packet = p.read(out/'reading-packet.json')
    packet['dataset_mode'] = p.read(dataset/'data-contract.json').get('dataset_mode','real_or_public')
    packet['analyst_instruction'] = 'Return proposal.json with actual model/analyst metadata. Read every full source unit, not only quoted fragments. Do not reuse synthetic example answers on new data.'
    p.write(out/'reading-packet.json',packet)
    p.write(out/'proposal-template.json',{'schema_version':p.VERSION,'input_binding':p.bind(dataset),
        'analyst':{'actor_kind':'fill_actual_actor','actor_id':'fill_actual_id','model':'record_actual_model_or_unknown','review_status':'not_performed'},
        'clusters':[],'coverage':[{'unit_id':u['semantic_unit_id'],'cluster_ids':[],
            'disposition':'unclustered_boundary' if u['attitude']=='dislike' else 'reference_only',
            'reason':'UNREVIEWED: replace after semantic assessment'} for u in packet['units']]})
    p.write(out/'run-manifest.json', {'package_version':'1.0.0','files':{str(f.relative_to(out)).replace('\\','/'):p.sha(f)
        for f in out.rglob('*') if f.is_file()},'engine_files':pins(),'model_calls_by_scripts':0})
    return {'status':'ready_for_semantic_proposal','run':str(out),'units':len(packet['units'])}

def current(run):
    run = Path(run).resolve()
    m = p.read(run/'run-manifest.json')
    need(m['engine_files']==pins(),'skill engine changed; prepare a new run')
    need(all((run/name).is_file() and p.sha(run/name)==sha for name,sha in m['files'].items()), 'frozen input/packet changed')
    check_dataset(run/'dataset')
    return run

def result_files(run):
    names = ['analyst-proposal.json','clusters.json','memberships.jsonl','coverage-ledger.jsonl',
             'summary.json','handshake-input.json','handoff.json','聚类报告.md']
    return {name:p.sha(run/name) for name in names}

def accept(run, proposal):
    run = current(run)
    need(not (run/'acceptance.json').exists() and not (run/'clusters.json').exists(), 'result exists; keep history and prepare a new run for revision')
    value = p.read(proposal)
    need(isinstance(value.get('analyst'),dict) and value['analyst'].get('actor_kind') and value['analyst'].get('actor_id'), 'attributable analyst metadata required')
    need(not any(str(row.get('reason','')).startswith('UNREVIEWED:') for row in value.get('coverage',[])), 'coverage template is not a semantic assessment')
    with redirect_stdout(StringIO()): result = compiler.save(run/'dataset', value, run)
    p.write(run/'analyst-proposal.json',value)
    p.write(run/'handoff.json',{'schema_version':'prism.research_semantic_handoff.v1','input_binding':result['input_binding'],
        'summary':result['summary'],'negative_unit_ids':sorted(r['unit_id'] for r in result['coverage'] if r['source_attitude']=='dislike'),
        'dataset_directory':'dataset','consumer_requires_full_source_replay':True,
        'semantic_truth_verified':False,'source_quote_verification':'against_imported_evidence_text_not_audio_or_unread_original_documents'})
    receipt = {'status':'structure_and_provenance_accepted','summary':result['summary'],
        'result_files':result_files(run),'semantic_accuracy_proven':False,'model_calls_by_scripts':0}
    p.write(run/'acceptance.json', receipt)
    return receipt

def verify(run):
    run = current(run)
    receipt = p.read(run/'acceptance.json')
    need(result_files(run)==receipt['result_files'],'compiled result/handoff changed')
    result = compiler.validate_and_compile(run/'dataset',p.read(run/'analyst-proposal.json'))
    need(p.read(run/'clusters.json')=={k:v for k,v in result.items() if k!='membership_rows'},'result no longer replays')
    return {'status':'verified','units':result['summary']['input_units'],'clusters':result['summary']['cluster_count'],
        'negative_units':result['summary']['original_negative_units'],'semantic_accuracy_proven':False,'model_calls_by_scripts':0}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    q = sub.add_parser('prepare'); group=q.add_mutually_exclusive_group(required=True)
    group.add_argument('--input');group.add_argument('--dataset');q.add_argument('--out',required=True)
    q=sub.add_parser('accept');q.add_argument('--run',required=True);q.add_argument('--proposal',required=True)
    q=sub.add_parser('verify');q.add_argument('--run',required=True)
    a=parser.parse_args()
    try:
        if a.command=='prepare': result=prepare_run(a.out,a.input,a.dataset)
        elif a.command=='accept': result=accept(a.run,a.proposal)
        else: result=verify(a.run)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError,TypeError) as e:
        print(json.dumps({'status':'rejected','reason':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':sys.exit(main())
