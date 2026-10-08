"""显式执行全部剩余通过趋势图：GPT-6 Sol low，10路，每图至多初提和必要复核。"""

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
from pathlib import Path
import re
import shutil
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from PIL import Image
from app.agents.dna_deep_agent import _model_options
from app.agents.prism_dna_sol_r5 import primary_system_prompt, PROMPT_VERSION
from app.services.dna.prism_r5 import run_prism_r5_extraction, _portable, _safe_exception, RESULT_DIR, RUN_DIR
from app.services.dna.storage import ALLOWED_FORMATS, _atomic_write
from scripts.run_trend_r5_batch import runtime_files, now, read, save, sha, outcome_for_result
from scripts.run_d02_ppt_enjoy_r5_batch import _quota_or_auth_error
from scripts.repair_trend_r5_offline import recover_entry

BATCH_ID = 'handshake_remaining7503_gpt6sol_low_r5_10_20261004'
FOLDER = ROOT / 'data/result/trend_dna/batches' / BATCH_ID
PREVIOUS = ROOT / 'data/result/trend_dna/batches/handshake_pass_first1000_gemini38_r5_20261004'
REVIEW = ROOT / 'data/result/trend_quality/manual_review/handshake-astra-20261001'
MODEL = 'gpt-6-sol'
WORKERS = 10
TRACE = re.compile(r'运行记录 ([a-f0-9]{32})')


def select_remaining(catalog, state, previous):
    """只取人工PASS或模型PASS并集中的未提交原图；旧失败与中断也排除，避免重试。"""
    excluded = {row['sha256'] for row in previous['entries'] if row['status'] != 'pending'}
    labels = state['labels']
    manual = [row for row in catalog['images'] if labels.get(row['id'], {}).get('decision') == 'PASS']
    model = [row for row in catalog['images'] if row['model_category'] == 'PASS']
    union = {row['id']: row for row in [*manual, *model]}
    return [row for key, row in union.items() if key not in excluded], excluded, len(union)


def code_hashes():
    hashes = runtime_files()
    for name in ('backend/scripts/run_trend_r5_remaining.py', 'backend/scripts/repair_trend_r5_offline.py',
                 'backend/app/services/dna/r5_primary_repair.py', 'backend/app/services/dna/r5_focus_repair.py'):
        hashes[name] = sha(ROOT / name)
    return hashes


def prepare():
    _portable()
    if (FOLDER / 'manifest.json').exists():
        manifest = read(FOLDER / 'manifest.json')
        if manifest['runtime_sha256'] != code_hashes() or manifest['model_options'] != _model_options(MODEL):
            raise ValueError('代码或模型配置与冻结批次不一致，拒绝混用')
        for name, digest in manifest['frozen_files'].items():
            if sha(FOLDER / name) != digest:
                raise ValueError('冻结来源或Prompt被修改')
        return manifest
    previous = read(PREVIOUS / 'manifest.json')
    if previous['status'] != 'superseded' or not read(PREVIOUS / 'handoff_gpt6sol_low_10/handoff.json')['old_process_terminated']:
        raise ValueError('旧批次还未完成交接')
    catalog_bytes = (REVIEW / 'catalog.json').read_bytes()
    state_bytes = (REVIEW / 'selections.json').read_bytes()
    catalog, state = json.loads(catalog_bytes), json.loads(state_bytes)
    import hashlib
    if state['catalog_sha256'] != hashlib.sha256(catalog_bytes).hexdigest():
        raise ValueError('人工选择与目录指纹不匹配')
    selected, excluded, population = select_remaining(catalog, state, previous)
    if not selected:
        raise ValueError('没有剩余未提交通过图')
    FOLDER.mkdir(parents=True, exist_ok=False)
    for name in ('inputs', 'entries', 'offline_repair'):
        (FOLDER / name).mkdir()
    _atomic_write(FOLDER / 'catalog.snapshot.json', catalog_bytes)
    _atomic_write(FOLDER / 'selections.snapshot.json', state_bytes)
    save(FOLDER / 'previous.snapshot.json', previous)
    _atomic_write(FOLDER / 'primary.system.prompt.txt', primary_system_prompt().encode())
    entries, lineage = [], []
    for index, image in enumerate(selected, 1):
        row = {'entry_id': f'I{index:05d}', 'image_id': image['image_id'], 'sha256': image['id'],
               'source_path': image['source_path'], 'status': 'pending', 'trace_id': None,
               'result_id': None, 'error': None, 'started_at': None, 'finished_at': None,
               'attempted_calls': 0}
        try:
            source = (ROOT / image['source_path']).resolve()
            if not source.is_relative_to(ROOT / 'data/trend_data/images') or sha(source) != image['id']:
                raise ValueError('原图目录或哈希不匹配')
            with Image.open(source) as im:
                suffix, mime = ALLOWED_FORMATS[im.format]
                im.verify()
            path = FOLDER / 'inputs' / (row['entry_id'] + '_' + image['id'][:16] + suffix)
            shutil.copyfile(source, path)
            if sha(path) != image['id']:
                raise ValueError('原图冻结校验失败')
            row.update(snapshot=str(path.relative_to(FOLDER)), content_type=mime, original_size=path.stat().st_size)
        except Exception as exc:
            row.update(status='failed', error='输入失败：' + _safe_exception(exc), finished_at=now(), raw_status='failed')
        entries.append(row)
        lineage.append(dict(image, manual_decision=state['labels'].get(image['id'], {}).get('decision')))
    save(FOLDER / 'selection.json', {'selection_rule': 'human_PASS OR model_PASS', 'manual_revision': state['revision'],
                                   'excluded_submitted_hashes': sorted(excluded), 'images': lineage})
    hashes = code_hashes()
    for name in hashes:
        target = FOLDER / 'runtime_snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    manifest = {'schema_version': 'prism.trend_r5_remaining.v1', 'batch_id': BATCH_ID,
                'created_at': now(), 'model_id': MODEL, 'reasoning_effort': 'low', 'max_concurrency': WORKERS,
                'selected_count': len(entries), 'eligible_count': population, 'excluded_submitted_count': len(excluded),
                'selection_rule': 'human_PASS OR model_PASS', 'manual_revision': state['revision'],
                'model_options': _model_options(MODEL), 'prompt_version': PROMPT_VERSION,
                'automatic_retries': False, 'single_request_per_stage': True, 'max_calls_per_image': 2,
                'local_repair': 'existing_raw_replies_only_no_new_model_calls', 'production_admission': False,
                'runtime_sha256': hashes, 'frozen_files': {name: sha(FOLDER / name) for name in (
                    'catalog.snapshot.json', 'selections.snapshot.json', 'previous.snapshot.json',
                    'selection.json', 'primary.system.prompt.txt')}, 'entries': entries}
    save(FOLDER / 'manifest.json', manifest)
    progress(manifest, entries, status='prepared')
    return manifest


def entry_path(entry):
    return FOLDER / 'entries' / (entry['entry_id'] + '.json')


def load_entries(manifest):
    """每图独立账本为权威状态；无需每张图重复写7503项完整清单。"""
    return [read(entry_path(row)) if entry_path(row).exists() else dict(row) for row in manifest['entries']]


def progress(manifest, entries, *, status, elapsed=0, ended_in_run=0, stopped_reason=None):
    counts = Counter(row['status'] for row in entries)
    raw = Counter(row.get('raw_status', row['status']) for row in entries if row['status'] in ('completed', 'partial', 'failed'))
    finished = counts['completed'] + counts['partial'] + counts['failed']
    summary = {'batch_id': BATCH_ID, 'status': status, 'updated_at': now(), 'model_id': MODEL,
               'reasoning_effort': 'low', 'max_concurrency': WORKERS, 'selected_count': manifest['selected_count'],
               'counts': {key: counts[key] for key in ('pending', 'running', 'completed', 'partial', 'failed')},
               'finished': finished, 'raw_counts': dict(raw),
               'raw_failure_rate': raw['failed'] / finished if finished else None,
               'effective_failure_rate': counts['failed'] / finished if finished else None,
               'local_repaired_count': sum(bool(row.get('repair_applied')) for row in entries),
               'elapsed_seconds_this_run': round(elapsed, 3),
               'images_per_minute_this_run': round(ended_in_run * 60 / elapsed, 3) if elapsed else None,
               'stopped_reason': stopped_reason}
    save(FOLDER / 'progress.json', summary)
    return summary


def repair_outcome(entry, outcome):
    """只消费已保存原回复；原始失败与修复后状态并列保留，绝不追加模型调用。"""
    outcome['raw_status'] = outcome['status']
    outcome['raw_error'] = outcome.get('error')
    if outcome['status'] not in ('failed', 'partial') or not outcome.get('trace_id'):
        return outcome
    try:
        portable, engine = _portable()
        repaired = recover_entry({**entry, **outcome}, portable, engine, expected_model=MODEL)
        destination = FOLDER / 'offline_repair' / (entry['entry_id'] + '.json')
        save(destination, {'batch_id': BATCH_ID, 'entry_id': entry['entry_id'], 'image_id': entry['image_id'],
                           'model_id': MODEL, 'new_model_calls': 0, 'new_model_tokens': 0,
                           'created_at': now(), 'raw_status': outcome['raw_status'], **repaired})
        outcome['repair_result_path'] = str(destination.relative_to(ROOT))
        if repaired['status'] in ('recovered_complete', 'recovered_partial'):
            outcome.update(status='completed' if repaired['status'] == 'recovered_complete' else 'partial',
                           repair_applied=True, quarantined_count=repaired['validation']['quarantined_count'],
                           pending_count=repaired['validation']['pending_count'],
                           error=None if repaired['status'] == 'recovered_complete' else '离线保留有效字段；困难项或非法字段待复核')
    except Exception as exc:
        outcome['repair_error'] = _safe_exception(exc)
    return outcome


def run_one(entry, lineage, selection_sha):
    timer = monotonic()
    try:
        path = FOLDER / entry['snapshot']
        if sha(path) != entry['sha256']:
            raise ValueError('冻结原图哈希发生变化')
        output = run_prism_r5_extraction(image_path=path, content_type=entry['content_type'], model_id=MODEL,
            reasoning_effort='low', user_prompt='', single_request=True, source_record={
                'source_kind': 'trend', 'batch_id': BATCH_ID, 'source_path': entry['source_path'],
                'image_id': entry['image_id'], 'selection_sha256': selection_sha, 'quality_lineage': lineage})
        outcome = outcome_for_result(output.result_id)
    except Exception as exc:
        error = _safe_exception(exc)
        match = TRACE.search(error)
        trace = match.group(1) if match else None
        try:
            attempts = len(read(RUN_DIR / trace / 'call-ledger.json')['calls']) if trace else 0
        except (OSError, ValueError, KeyError):
            attempts = None
        outcome = {'status': 'failed', 'error': error, 'trace_id': trace, 'result_id': None, 'attempted_calls': attempts}
    outcome = repair_outcome(entry, outcome)
    outcome['duration_seconds'] = round(monotonic() - timer, 3)
    return outcome


def recover_interrupted(entries):
    """恢复仅回收落盘产物；曾提交图片缺失回执也不会重新调用。"""
    running = {str((FOLDER / row['snapshot']).resolve()): row for row in entries if row['status'] == 'running'}
    if not running:
        return
    for path in RUN_DIR.glob('*/prepared.json'):
        try:
            data = read(path)
        except (OSError, ValueError):
            continue  # 无关历史记录损坏不阻断当前批次恢复。
        if not isinstance(data, dict):
            continue
        row = running.get(data.get('source_path'))
        if row is None or data.get('image_sha256') != row['sha256'] or data.get('model_id') != MODEL:
            continue
        running.pop(data['source_path'])
        trace = path.parent.name
        if (RESULT_DIR / (trace + '.json')).is_file():
            outcome = outcome_for_result(trace)
        else:
            outcome = {'status': 'failed', 'result_id': None, 'trace_id': trace,
                       'error': '进程中断，保留原回复并跳过，不重试', 'attempted_calls': None}
        row.update(repair_outcome(row, outcome), finished_at=now())
        save(entry_path(row), row)
    for row in running.values():
        if row['status'] == 'running':
            row.update(status='failed', raw_status='failed', error='已登记提交但缺失运行回执；不重试', finished_at=now())
            save(entry_path(row), row)


def execute():
    FOLDER.parent.mkdir(parents=True, exist_ok=True)
    with (FOLDER.parent / (BATCH_ID + '.run.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare()
        existing = read(FOLDER / 'progress.json')
        if existing.get('stopped_reason'):
            raise ValueError('批次已停止，需先处理记录的原因')
        entries = load_entries(manifest)
        recover_interrupted(entries)
        lineage = {row['id']: row for row in read(FOLDER / 'selection.json')['images']}
        selected = iter(row for row in entries if row['status'] == 'pending')
        selection_sha = manifest['frozen_files']['selection.json']
        timer = monotonic()
        ended = 0
        stopped = None
        active = {}
        save(FOLDER / 'run.start.json', {'started_at': now(), 'model_id': MODEL, 'concurrency': WORKERS})
        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='trend-gpt-low') as pool:
            def submit_next():
                row = next(selected, None)
                if row is None:
                    return
                row.update(status='running', started_at=now())
                save(entry_path(row), row)
                active[pool.submit(run_one, dict(row), lineage[row['sha256']], selection_sha)] = row
            for _ in range(WORKERS):
                submit_next()
            progress(manifest, entries, status='running')
            while active:
                done, _ = wait(active, timeout=10, return_when=FIRST_COMPLETED)
                for future in done:
                    row = active.pop(future)
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        outcome = {'status': 'failed', 'raw_status': 'failed', 'error': _safe_exception(exc)}
                    row.update(outcome, finished_at=now())
                    save(entry_path(row), row)
                    ended += 1
                    if _quota_or_auth_error(outcome.get('raw_error') or outcome.get('error')):
                        stopped = 'model_quota_or_auth_error'
                    print(json.dumps({'at': now(), 'entry_id': row['entry_id'], 'image_id': row['image_id'],
                                      'status': row['status'], 'raw_status': row.get('raw_status'),
                                      'duration_seconds': row.get('duration_seconds')},ensure_ascii=False),flush=True)
                # 同时完成的一组先识别系统性错误，再决定是否补位。
                if not stopped:
                    for _ in done:
                        submit_next()
                progress(manifest, entries, status='running', elapsed=monotonic()-timer, ended_in_run=ended, stopped_reason=stopped)
        final = progress(manifest, entries, status='blocked' if stopped else 'completed',
                         elapsed=monotonic()-timer, ended_in_run=ended, stopped_reason=stopped)
        save(FOLDER / 'final_entries.json', entries)
        save(FOLDER / 'failures.json', [row for row in entries if row['status'] in ('failed','partial')])
        return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare','run','status'))
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(); output = read(FOLDER / 'progress.json')
    elif args.command == 'run':
        output = execute()
    else:
        output = read(FOLDER / 'progress.json')
    print(json.dumps(output, ensure_ascii=False),flush=True)
