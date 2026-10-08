"""Portable IO around frozen original R3/R5 pure algorithm functions."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import ast
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def loads(text):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key)
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('Nonfinite number: ' + value)
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            invalid(value)
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)


def read(path):
    return loads(Path(path).read_text(encoding='utf-8-sig'))


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value, *, text=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(value if text else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def load_original():
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError('Install this skill requirements.txt in your Python environment first.') from e
    manifest = read(ROOT / 'assets/source-manifest.json')
    for path, row in manifest.items():
        if file_hash(ROOT / path) != row['sha256']:
            raise ValueError('Frozen source changed: ' + path)
    context = read(ROOT / 'assets/context.json')
    dictionary = read(ROOT / 'assets/dictionary.json')
    common = SimpleNamespace(canonical=canonical, jsonschema=jsonschema,
                             DICTIONARY=ROOT / 'assets/dictionary.json', file_hash=file_hash)
    ns3 = {'copy': __import__('copy'), 'c': common, 'DICTIONARY': dictionary,
           'PARAMS': {p['parameter_id']: p for p in dictionary['parameters']},
           'ACTIVE': context['ACTIVE'], 'SHARED': set(context['SHARED']), 'NON_FEATURE': set(context['NON_FEATURE'])}
    tree = ast.parse((ROOT / 'assets/source-r3.py').read_text(encoding='utf-8-sig'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<frozen-R3-functions>', 'exec'), ns3)
    r3 = SimpleNamespace(**ns3)
    ns5 = {'copy': __import__('copy'), 'c': common, 'r3': r3, 'PARAMS': ns3['PARAMS'],
           'ACTIVE': context['ACTIVE'], 'NON_FEATURE': ns3['NON_FEATURE'], 'obj': ns3['obj'],
           **{k: context[k] for k in ['VERSION', 'CORE', 'TEX', 'CMF', 'OTHER', 'PROMPT']}, 'HARD': set(context['HARD'])}
    tree = ast.parse((ROOT / 'assets/source-r5.py').read_text(encoding='utf-8-sig'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), '<frozen-R5-functions>', 'exec'), ns5)
    engine = SimpleNamespace(**ns5)
    if engine.prompt() != (ROOT / 'assets/primary.prompt.txt').read_text(encoding='utf-8'):
        raise ValueError('Portable loader changed the frozen primary prompt')
    if engine.schema() != read(ROOT / 'assets/primary.schema.json'):
        raise ValueError('Portable loader changed the frozen primary schema')
    return engine


def validate(engine, schema, answer):
    errors = sorted(engine.c.jsonschema.Draft202012Validator(schema).iter_errors(answer), key=lambda e: str(e.path))
    if errors:
        raise ValueError('; '.join(str(e.path) + ': ' + e.message for e in errors[:8]))


def primary(engine, answer, image_id):
    validate(engine, engine.schema(), answer)
    return engine.unpack(answer, 'P-' + image_id)


def finish(engine, unpacked, focus, image_id):
    if focus is not None:
        validate(engine, engine.focus_schema(unpacked['issues']), focus)
    merged = engine.merge_focus(unpacked, focus, 'F-' + image_id)
    local, pending = deepcopy(merged['accepted']), deepcopy(merged['pending'])
    adjustments = []
    # Exact status-only admission fix from the owner's finalize.py.
    for entry in merged['decisions']:
        issue, result = entry['issue'], entry['result']
        if issue['kind'] == 'missing' and result and result['decision'] == 'present' and result['value'] is not None:
            if engine.valid_value(issue['fact']['p'], result['value'])[0]:
                fact = {**issue['fact'], 'v': engine.r3.unwrap(result['value']), 'source': 'F-' + image_id, 'evidence': result['evidence']}
                local.append(fact)
                adjustments.append({'kind': 'explicit_positive_for_missing_field', 'fact': fact, 'host_value_inference': False})
                pending = [x for x in pending if x.get('issue', {}).get('fact', {}).get('path') != issue['fact']['path']]
    return summarize(engine, image_id, local, pending, unpacked['invalid'], merged['decisions'], adjustments)


def summarize(engine, image_id, local, pending, invalid, decisions, adjustments):
    local = list({canonical([f['at'], f['p'], f['v']]): f for f in local}.values())
    index, excluded = engine.r3.normalize([{'feature': f, 'source': f['source']} for f in local])
    if excluded:
        raise ValueError('Invalid non-feature made it into the accepted ledger')
    return {'schema_version': 'prism.sol_r5.portable_result.v1', 'algorithm_version': engine.VERSION,
            'image_id': image_id, 'features': index, 'local_features': local, 'pending': pending,
            'invalid': invalid, 'decisions': decisions, 'admission_adjustments': adjustments,
            'final_local_features': len(local), 'final_local_CMF': sum(f['p'] in engine.CMF for f in local),
            'image_unique_features': len(index), 'image_unique_CMF': sum(f['parameter_id'] in engine.CMF for f in index),
            'ID_unique': sum('ID' in f['views'] for f in index), 'CMF_unique': sum('CMF' in f['views'] for f in index),
            'shared_unique': sum(len(f['views']) == 2 for f in index), 'pending_count': len(pending),
            'full_216_visual_qualified': False, 'human_gold_accuracy_established': False,
            'source_binding': 'named_flat_locations_no_boxes_or_object_tree'}


def refinement_job(engine, mode, primary_answer, final):
    """Reuse the owner's exact refinement builders; remove case/transport side effects."""
    tree = ast.parse((ROOT / 'assets/source-refine.py').read_text(encoding='utf-8-sig'))
    fn_name = 'hp' if mode == 'mixed-areas' else 'mc'
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    statements = []
    for node in fn.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'start' for t in node.targets):
            break
        statements.append(node)
    common = SimpleNamespace(canonical=canonical, read=lambda p: deepcopy(primary_answer if mode == 'mixed-areas' else final))
    ns = {'a': engine, 'c': common, 'ROOT': Path('.'), 'copy': __import__('copy')}
    exec(compile(ast.Module(body=statements, type_ignores=[]), '<frozen-refinement-preparation>', 'exec'), ns)
    targets = ns['chosen'] if mode == 'mixed-areas' else ns['target']
    return {'mode': mode, 'prompt': ns['prompt'], 'schema': ns['reply'], 'target_count': len(targets),
            'selected_indices': list(ns['chosen']) if mode == 'mixed-areas' else None,
            'targets': None if mode == 'mixed-areas' else ns['target']}


def apply_refinement(engine, final, primary_answer, job, answer, image_id):
    validate(engine, job['schema'], answer)
    local, pending, changes = deepcopy(final['local_features']), deepcopy(final['pending']), deepcopy(final['admission_adjustments'])
    if job['mode'] == 'mixed-areas':
        names = {primary_answer['areas'][int(i)]['name'] for i in job['selected_indices']}
        local = [x for x in local if not (x['source'] == 'P-' + image_id and x['at'] in names)]
        for key, group in answer['groups'].items():
            unpacked = engine.unpack({'areas': group['areas'], 'overall': [], 'uncertain': []}, 'H-' + image_id)
            for row in unpacked['direct']:
                row['path'] = '/groups/' + key + row['path']
                row['evidence'] = group['evidence']
            local += unpacked['direct']
            pending += unpacked['issues'] + unpacked['overflow']
        changes.append({'kind': 'replaced_mixed_areas', 'indices': job['selected_indices'], 'appended_old_and_new': False})
    else:
        keys = {canonical([x['at'], x['p']]) for x in job['targets']}
        local = [x for x in local if canonical([x['at'], x['p']]) not in keys]
        for i, target in enumerate(job['targets']):
            result = answer['checks'][str(i)]
            if result['decision'] == 'supported' and result['value'] is not None and engine.valid_value(target['p'], result['value'])[0]:
                local.append({**target, 'v': engine.r3.unwrap(result['value']), 'source': 'H-' + image_id, 'evidence': result['evidence']})
            else:
                pending.append({'issue': target, 'result': result})
        changes.append({'kind': 'optical_checks_replaced', 'targets': len(job['targets'])})
    return summarize(engine, image_id, local, pending, final['invalid'], final['decisions'], changes)


def replay_examples():
    engine = load_original()
    rows = []
    for case in read(ROOT / 'examples/index.json'):
        cid = case['image_id']
        base = ROOT / 'examples' / cid
        answer, focus = read(base / 'primary.json'), read(base / 'focus.json')
        final = finish(engine, primary(engine, answer, cid), focus, cid)
        if case['refinement_mode']:
            job = refinement_job(engine, case['refinement_mode'], answer, final)
            saved = read(base / 'refinement.json')
            final = apply_refinement(engine, final, answer, job, saved['answer'], cid)
        expected = read(base / 'expected.json')
        fields = ['features', 'local_features', 'pending', 'invalid', 'decisions', 'admission_adjustments',
                  'final_local_features', 'final_local_CMF', 'image_unique_features', 'image_unique_CMF',
                  'ID_unique', 'CMF_unique', 'shared_unique', 'pending_count']
        mismatch = [key for key in fields if final[key] != expected[key]]
        rows.append({'image_id': cid, 'passed': not mismatch, 'mismatched_fields': mismatch,
                     'ID_features': final['ID_unique'], 'CMF_features': final['CMF_unique'], 'pending': final['pending_count']})
    return {'passed': all(r['passed'] for r in rows), 'cases': rows, 'new_model_calls': 0,
            'scope': 'saved_response_replay_not_new_visual_accuracy_test'}
