"""握手趋势通过图的首批 R5 DNA：冻结1000张、Gemini五路、失败不重试。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from PIL import Image
from app.agents.prism_dna_sol_r5 import SKILL_ROOT, PROMPT_VERSION, primary_system_prompt
from app.agents.dna_deep_agent import _model_options
from app.services.dna.prism_r5 import RESULT_DIR, RUN_DIR, _safe_exception, _portable, run_prism_r5_extraction
from app.services.dna.storage import _atomic_write, ALLOWED_FORMATS
from app.services.llm.catalog import get_model
from scripts.run_d02_ppt_enjoy_r5_batch import _quota_or_auth_error

BATCH_ID = 'handshake_pass_first1000_gemini38_r5_20261004'
FOLDER = ROOT / 'data/result/trend_dna/batches' / BATCH_ID
REVIEW = ROOT / 'data/result/trend_quality/manual_review/handshake-astra-20261001'
MODEL = 'gemini-3.8-flash'
CONCURRENCY = 5
LIMIT = 1000
TRACE = re.compile(r'运行记录 ([a-f0-9]{32})')


def now():
    return datetime.now(UTC).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    _atomic_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def select_images(catalog, state, limit=None):
    """用户明确采用或关系：人工FAIL不否决模型PASS；人工PASS优先且按原图去重。"""
    limit = LIMIT if limit is None else limit
    if not 1 <= limit <= LIMIT:
        raise ValueError('本批仅允许1–1000张')
    labels = state['labels']
    manual = [image for image in catalog['images'] if labels.get(image['id'], {}).get('decision') == 'PASS']
    model = [image for image in catalog['images'] if image['model_category'] == 'PASS']
    unique = {}
    for image in [*manual, *model]:
        unique.setdefault(image['id'], image)
    return list(unique.values())[:limit], len(unique)


def runtime_files():
    """执行依赖纳入快照哈希；恢复时不能将当前新规则套到旧批次。"""
    paths = [p for p in SKILL_ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    paths += [ROOT / value for value in (
        'backend/scripts/run_trend_r5_batch.py',
        'backend/scripts/run_d02_ppt_enjoy_r5_batch.py',
        'backend/app/services/dna/prism_r5.py', 'backend/app/services/dna/storage.py',
        'backend/app/agents/prism_dna_sol_r5.py', 'backend/app/agents/dna_deep_agent.py',
        'backend/app/services/llm/catalog.py', 'backend/app/services/llm/client.py',
        'backend/app/services/llm/settings.py', 'backend/app/services/llm/telemetry.py',
    )]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def persist(manifest):
    manifest['updated_at'] = now()
    counts = Counter(entry['status'] for entry in manifest['entries'])
    manifest['counts'] = {key: counts[key] for key in ('pending', 'running', 'completed', 'partial', 'failed')}
    save(FOLDER / 'manifest.json', manifest)
    save(FOLDER / 'progress.json', {key: manifest[key] for key in (
        'batch_id', 'status', 'model_id', 'max_concurrency', 'selected_count',
        'created_at', 'updated_at', 'counts', 'stopped_reason')})
    save(FOLDER / 'failures.json', {'batch_id': BATCH_ID,
         'entries': [entry for entry in manifest['entries'] if entry['status'] in ('failed', 'partial')]})


def prepare():
    get_model(MODEL)
    _portable()  # 离线核验Skill冻结引擎，不发送视觉请求。
    if (FOLDER / 'manifest.json').exists():
        manifest = read(FOLDER / 'manifest.json')
        if (manifest['runtime_sha256'] != runtime_files() or manifest['model_options'] != _model_options(MODEL)
                or manifest['model_id'] != MODEL or manifest['max_concurrency'] != CONCURRENCY):
            raise ValueError('运行规则或模型配置已变化，拒绝继续旧批次')
        for name, digest in manifest['frozen_files'].items():
            if sha(FOLDER / name) != digest:
                raise ValueError('冻结选择或Prompt发生变化')
        return manifest
    catalog_bytes = (REVIEW / 'catalog.json').read_bytes()
    state_bytes = (REVIEW / 'selections.json').read_bytes()
    catalog, state = json.loads(catalog_bytes), json.loads(state_bytes)
    if state['catalog_sha256'] != hashlib.sha256(catalog_bytes).hexdigest():
        raise ValueError('人工状态与图库指纹不匹配')
    selected, population = select_images(catalog, state)
    if len(selected) != LIMIT:
        raise ValueError('通过图片不足1000张')
    FOLDER.mkdir(parents=True, exist_ok=False)
    (FOLDER / 'inputs').mkdir()
    _atomic_write(FOLDER / 'catalog.snapshot.json', catalog_bytes)
    _atomic_write(FOLDER / 'selections.snapshot.json', state_bytes)
    _atomic_write(FOLDER / 'primary.system.prompt.txt', primary_system_prompt().encode())
    selection, entries = [], []
    for index, image in enumerate(selected, 1):
        source = (ROOT / image['source_path']).resolve()
        if not source.is_relative_to(ROOT / 'data/trend_data/images') or sha(source) != image['id']:
            raise ValueError('原图不在趋势图库或原图哈希变化：' + image['image_id'])
        with Image.open(source) as im:
            suffix, mime = ALLOWED_FORMATS[im.format]
            im.verify()
        filename = f'I{index:04d}_{image["id"][:16]}{suffix}'
        snapshot = FOLDER / 'inputs' / filename
        shutil.copyfile(source, snapshot)
        if sha(snapshot) != image['id']:
            raise ValueError('冻结原图复制校验失败')
        decision = state['labels'].get(image['id'], {}).get('decision')
        selection.append(dict(image, manual_decision=decision,
                              admitted_by=[key for key, passed in (('human', decision == 'PASS'),
                                           ('model', image['model_category'] == 'PASS')) if passed]))
        entries.append({'entry_id': f'I{index:04d}', 'image_id': image['image_id'], 'sha256': image['id'],
                        'source_path': image['source_path'], 'snapshot': 'inputs/' + filename,
                        'content_type': mime, 'original_size': snapshot.stat().st_size,
                        'manual_decision': decision, 'model_decision': image['model_decision'],
                        'status': 'pending', 'result_id': None, 'trace_id': None, 'error': None,
                        'started_at': None, 'finished_at': None, 'attempted_calls': 0})
    save(FOLDER / 'selection.json', {'selection_rule': 'human_PASS OR model_PASS',
        'order': '人工PASS优先，其余按冻结图库顺序；原图SHA256去重', 'eligible_count': population,
        'manual_revision': state['revision'], 'images': selection})
    hashes = runtime_files()
    for name in hashes:
        destination = FOLDER / 'runtime_snapshot' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    manifest = {'schema_version': 'prism.trend_r5_batch.v1', 'batch_id': BATCH_ID, 'status': 'prepared',
        'model_id': MODEL, 'reasoning_effort': 'low', 'model_options': _model_options(MODEL),
        'max_concurrency': CONCURRENCY, 'selected_count': len(entries), 'eligible_count': population,
        'selection_rule': 'human_PASS OR model_PASS', 'manual_revision': state['revision'],
        'prompt_version': PROMPT_VERSION, 'automatic_retries': False, 'max_calls_per_image': 2,
        'max_internal_model_calls_per_stage': 1, 'tools_and_subagents_allowed': False,
        'image_preprocessing': '原图完整字节；不缩图、不裁切', 'production_admission': False,
        'result_directory': str(RESULT_DIR.relative_to(ROOT)), 'runtime_sha256': hashes,
        'frozen_files': {name: sha(FOLDER / name) for name in (
            'catalog.snapshot.json', 'selections.snapshot.json', 'selection.json', 'primary.system.prompt.txt')},
        'created_at': now(), 'updated_at': now(), 'stopped_reason': None, 'entries': entries}
    persist(manifest)
    return manifest


def outcome_for_result(result_id):
    result = read(RESULT_DIR / (result_id + '.json'))
    complete = result['validation']['focus_complete']
    return {'status': 'completed' if complete else 'partial', 'result_id': result_id, 'trace_id': result_id,
            'error': None if complete else '定点复核失败，保留初提与未决项：' + str(result['execution']['focus_error']),
            'attempted_calls': result['execution']['attempted_calls'],
            'duration_seconds': result['execution']['duration_seconds']}


def run_one(entry, lineage):
    timer = monotonic()
    try:
        path = FOLDER / entry['snapshot']
        if sha(path) != entry['sha256']:
            raise ValueError('冻结原图内容已变化')
        output = run_prism_r5_extraction(image_path=path, content_type=entry['content_type'],
            model_id=MODEL, reasoning_effort='low', user_prompt='', single_request=True, source_record={
                'source_kind': 'trend', 'batch_id': BATCH_ID, 'source_path': entry['source_path'],
                'image_id': entry['image_id'], 'selection_rule': 'human_PASS OR model_PASS',
                'selection_sha256': sha(FOLDER / 'selection.json'), 'quality_lineage': lineage,
            })
        return outcome_for_result(output.result_id)
    except Exception as exc:
        error = _safe_exception(exc)
        match = TRACE.search(error)
        trace = match.group(1) if match else None
        try:
            calls = read(RUN_DIR / trace / 'call-ledger.json')['calls'] if trace else []
            attempts = len(calls)
        except (OSError, ValueError, KeyError):
            attempts = None  # 回执缺失时用未知，不能冒充零次模型调用。
        return {'status': 'failed', 'result_id': None, 'trace_id': trace, 'error': error,
                'duration_seconds': round(monotonic() - timer, 3), 'attempted_calls': attempts}


def recover(manifest):
    """中断时仅认落盘结果，在途任务无输出则跳过；绝不重发曾提交图片。"""
    running = {entry['sha256']: entry for entry in manifest['entries'] if entry['status'] == 'running'}
    if not running:
        return
    for path in RESULT_DIR.glob('*.json'):
        try:
            result = read(path)
            source = result['source']
            if (source.get('research') or {}).get('batch_id') == BATCH_ID and source['image_sha256'] in running:
                running.pop(source['image_sha256']).update(outcome_for_result(result['id']), finished_at=now())
        except (OSError, KeyError, ValueError):
            continue
    for entry in running.values():
        entry.update(status='failed', error='进程中断且结果未落盘，按失败不重试规则跳过', finished_at=now())


def execute():
    FOLDER.parent.mkdir(parents=True, exist_ok=True)
    with (FOLDER.parent / (FOLDER.name + '.run.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare()
        if manifest['stopped_reason']:
            raise ValueError('批次已因额度或鉴权错误停止，不能自动重新提交')
        recover(manifest)
        selection = {image['id']: image for image in read(FOLDER / 'selection.json')['images']}
        pending = iter(entry for entry in manifest['entries'] if entry['status'] == 'pending')
        manifest['status'] = 'running'
        persist(manifest)
        active = {}
        with ThreadPoolExecutor(max_workers=CONCURRENCY, thread_name_prefix='trend-r5') as pool:
            def submit_next():
                entry = next(pending, None)
                if entry is None:
                    return
                entry.update(status='running', started_at=now())
                persist(manifest)  # 提交前先持久化，崩溃恢复不会重复收费。
                active[pool.submit(run_one, dict(entry), selection[entry['sha256']])] = entry
            for _ in range(CONCURRENCY):
                submit_next()
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    entry = active.pop(future)
                    outcome = future.result()
                    entry.update(outcome, finished_at=now())
                    if _quota_or_auth_error(outcome['error']):
                        manifest['stopped_reason'] = 'model_quota_or_auth_error'
                    persist(manifest)
                    print(json.dumps({'at': now(), 'image_id': entry['image_id'], 'status': entry['status'],
                                      'counts': manifest['counts']}, ensure_ascii=False), flush=True)
                    if not manifest['stopped_reason']:
                        submit_next()
        manifest['status'] = 'blocked' if manifest['stopped_reason'] else 'completed'
        manifest['finished_at'] = now()
        persist(manifest)
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'status'))
    args = parser.parse_args()
    manifest = prepare() if args.command == 'prepare' else execute() if args.command == 'run' else read(FOLDER / 'manifest.json')
    print(json.dumps({key: manifest[key] for key in ('batch_id', 'status', 'eligible_count',
        'selected_count', 'model_id', 'max_concurrency', 'counts', 'stopped_reason')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
