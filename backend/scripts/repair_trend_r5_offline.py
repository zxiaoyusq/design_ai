"""离线恢复已保存R5失败回复；不提供模型执行入口，不覆盖原批次与原回执。"""

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.dna.prism_r5 import _portable, _answer
from app.services.dna.r5_primary_repair import VERSION, recover_primary, original_paths
from app.services.dna.r5_focus_repair import recover_focus
from app.services.dna.storage import _atomic_write

DEFAULT_BATCH = ROOT / 'data/result/trend_dna/batches/handshake_pass_first1000_gemini38_r5_20261004'
RUNS = ROOT / 'data/result/d02/r5_runs'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def now():
    return datetime.now(UTC).isoformat()


def recover_entry(entry, portable, engine, *, expected_model='gemini-3.8-flash'):
    """主提取失败仅恢复现有字段；没有现成复核回执的困难项全部保持pending。"""
    run = RUNS / entry['trace_id']
    prepared = read(run / 'prepared.json')
    if prepared['image_sha256'] != entry['sha256'] or prepared['model_id'] != expected_model:
        raise ValueError('原回复绑定图片与批次不同')
    primary_dir = run / 'calls/primary'
    if not (primary_dir / 'answer.raw.txt').is_file():
        return {'status': 'unrecoverable', 'reason': '无完整初提原回复，代码不能补造DNA'}
    request = read(primary_dir / 'request.json')
    if request['image_sha256'] != entry['sha256'] or request['model_id'] != expected_model:
        raise ValueError('调用回执的图片或模型身份不符')
    if request['schema_sha256'] != sha(primary_dir / 'schema.json') or read(primary_dir / 'schema.json') != engine.schema():
        raise ValueError('回执Schema不等于当前冻结R5规则')
    raw = (primary_dir / 'answer.raw.txt').read_text()
    recovered = recover_primary(raw, portable, engine)
    image_id = prepared['image_id']
    unpacked = portable.primary(engine, recovered['answer'], image_id)
    # 证据JSON路径指回原始答复，防止隔离条目后下标改变导致追溯错位。
    unpacked = original_paths(unpacked, recovered['source_paths'])
    focus = None
    focus_repair = None
    focus_repair_error = None
    focus_dir = run / 'calls/focus'
    focus_raw = focus_dir / 'answer.raw.txt'
    if focus_raw.is_file():
        focus_request = read(focus_dir / 'request.json')
        focus_schema = engine.focus_schema(unpacked['issues'])
        if (focus_request['image_sha256'] != entry['sha256']
                or focus_request['model_id'] != expected_model
                or focus_request['schema_sha256'] != sha(focus_dir / 'schema.json')
                or read(focus_dir / 'schema.json') != focus_schema):
            raise ValueError('复核清单与恢复后的困难项不匹配，不能错配复核答案')
        # 初提已有效的partial批次才有focus；核验原unpacked防止索引错配。
        saved_unpacked = read(run / 'unpacked.json')
        original_issues = json.dumps(saved_unpacked['issues'], ensure_ascii=False, sort_keys=True)
        current_issues = json.dumps(portable.primary(engine, recovered['answer'], image_id)['issues'], ensure_ascii=False, sort_keys=True)
        if original_issues != current_issues:
            raise ValueError('复核问题序号发生变化，拒绝复用')
        try:
            focus_repair = recover_focus(focus_raw.read_text(), focus_schema, portable, engine)
            focus = focus_repair['answer']
        except ValueError as exc:
            # 复核仍无法安全恢复时，已有初提继续可用，不能再次报废整图。
            focus_repair_error = str(exc)
    final = portable.finish(engine, unpacked, focus, image_id)
    blocked = {(row['at'], row['p']) for row in recovered['blocked_fields']}
    local = [fact for fact in final['local_features'] if (fact['at'], fact['p']) not in blocked]
    quarantined = recovered['quarantined'] + (focus_repair['quarantined'] if focus_repair else [])
    offline_pending = [{'kind': 'offline_quarantined', 'source': 'host_offline_repair',
                        'host_generated': True, 'requires_human_review': True, 'detail': row}
                       for row in quarantined]
    invalid = final['invalid'] + offline_pending
    pending = final['pending'] + offline_pending
    final = portable.summarize(engine, image_id, local, pending, invalid, final['decisions'], final['admission_adjustments'])
    if focus_repair:
        generated = set(focus_repair['host_generated_check_ids'])
        for index, decision in enumerate(final['decisions']):
            if str(index) in generated:
                decision['host_generated_result'] = True
        for item in final['pending']:
            if isinstance(item, dict) and (item.get('result') or {}).get('evidence') == '离线恢复：原回复缺失或不合规，待人工复核':
                item['host_generated_result'] = True
    usable = bool(final['local_features'])
    stage_complete = (not unpacked['issues']) or (focus_repair is not None and focus_repair['complete'])
    status = ('recovered_complete' if stage_complete and not quarantined else 'recovered_partial') if usable else 'unrecoverable'
    if entry['status'] == 'partial' and (focus_repair is None or not focus_repair['usable_checks']):
        status = 'unchanged_partial'
    return {'status': status, 'r5_result': final, 'primary_projection': recovered['answer'],
            'primary_repair': {key: value for key, value in recovered.items() if key != 'answer'},
            'focus_repair': focus_repair, 'focus_repair_error': focus_repair_error,
            'validation': {'primary_projection_schema_valid': True,
                'focus_complete': stage_complete, 'quarantined_count': len(quarantined),
                'pending_count': final['pending_count'], 'full_216_visual_qualified': False,
                'human_gold_accuracy_established': False, 'production_admission': False},
            'original_artifacts': {str(path.relative_to(ROOT)): sha(path) for path in (
                run / 'prepared.json', primary_dir / 'request.json', primary_dir / 'schema.json',
                primary_dir / 'answer.raw.txt', primary_dir / 'receipt.json',
                *([focus_dir / 'request.json', focus_raw, focus_dir / 'receipt.json'] if focus_raw.is_file() else []))}}


def execute(batch, output):
    manifest = read(batch / 'manifest.json')
    if manifest['status'] != 'paused':
        raise ValueError('请先暂停批次，离线修复只读取稳定回执')
    output.mkdir(parents=True, exist_ok=False)
    portable, engine = _portable()
    selected = [entry for entry in manifest['entries'] if entry['status'] in ('failed', 'partial')]
    save(output / 'source_manifest.snapshot.json', manifest)
    rows = []
    for entry in selected:
        row = {'entry_id': entry['entry_id'], 'image_id': entry['image_id'], 'image_sha256': entry['sha256'],
               'trace_id': entry['trace_id'], 'original_status': entry['status'], 'original_error': entry['error'],
               'schema_version': 'prism.r5.offline_recovery.v1', 'repair_version': VERSION,
               'processed_at': now(), 'new_model_calls': 0, 'new_model_tokens': 0,
               'model_id': manifest['model_id'], 'prompt_version': manifest['prompt_version']}
        try:
            result = recover_entry(entry, portable, engine) if entry['trace_id'] else {'status': 'unrecoverable', 'reason': '没有模型原回复记录'}
            row.update(result)
        except Exception as exc:
            row.update(status='unrecoverable', reason=f'{type(exc).__name__}: {exc}')
        save(output / 'images' / (entry['entry_id'] + '.json'), row)
        rows.append({key: row.get(key) for key in ('entry_id', 'image_id', 'trace_id', 'original_status', 'status', 'reason')}
                    | {'local_features': row.get('r5_result', {}).get('final_local_features', 0),
                       'pending_count': row.get('r5_result', {}).get('pending_count', 0),
                       'quarantined_count': row.get('validation', {}).get('quarantined_count', 0)})
        if len(rows) % 25 == 0:
            print(json.dumps({'processed': len(rows), 'total': len(selected), 'counts': dict(Counter(row['status'] for row in rows))},ensure_ascii=False), flush=True)
    summary = {'schema_version': 'prism.r5.offline_recovery_summary.v1', 'version': VERSION,
               'batch_id': manifest['batch_id'], 'created_at': now(), 'input_count': len(rows),
               'counts': dict(Counter(row['status'] for row in rows)),
               'by_original_status': {state: dict(Counter(row['status'] for row in rows if row['original_status'] == state)) for state in ('failed', 'partial')},
               'total_recovered_local_features': sum(row['local_features'] for row in rows if row['status'].startswith('recovered')),
               'new_model_calls': 0, 'new_model_tokens': 0, 'batch_remains_paused': True,
               'original_manifest_sha256': sha(output / 'source_manifest.snapshot.json'),
               'repair_code_sha256': {str(path.relative_to(ROOT)): sha(path) for path in (
                   Path(__file__).resolve(), ROOT / 'backend/app/services/dna/r5_primary_repair.py',
                   ROOT / 'backend/app/services/dna/r5_focus_repair.py')}, 'entries': rows}
    outcomes = {row['entry_id']: row['status'] for row in rows}
    effective = Counter()
    for entry in manifest['entries']:
        status = outcomes.get(entry['entry_id'])
        effective['completed' if status == 'recovered_complete' else
                  'partial' if status in ('recovered_partial', 'unchanged_partial') else entry['status']] += 1
    summary['effective_counts'] = dict(effective)
    save(output / 'summary.json', summary)
    print(json.dumps({key:value for key,value in summary.items() if key!='entries'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,default=DEFAULT_BATCH)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    execute(args.batch.resolve(), args.output.resolve())
