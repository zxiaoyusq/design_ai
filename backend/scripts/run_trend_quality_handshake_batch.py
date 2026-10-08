"""握手趋势图批处理：默认最多1000张，显式剩余模式排除旧批次，最多5路并发。"""

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agents import trend_quality as quality
from app.services.dna.prism_r5 import _safe_exception


def now():
    return datetime.now(UTC).isoformat()


def save(path, value):
    """回执与汇总原子替换，进程终止时不留下半份JSON。"""
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def select_images(source, limit, *, excluded_hashes=frozenset()):
    """按清单原顺序、按库存哈希去重；每张图保留全部文章／方向引用。"""
    if limit is None and not excluded_hashes:
        raise ValueError('全部剩余模式必须明确排除已提交批次')
    if limit is not None and not 1 <= limit <= 1000:
        raise ValueError('本入口每批只允许1–1000张，不自动扩展任务范围')
    raw = source.read_bytes()
    data = json.loads(raw)
    source_digest = sha256(raw).hexdigest()
    if data.get('schema_version') != 'prism.h01.related_trend_articles.v1':
        raise ValueError('不是握手关联文章契约')
    groups, counts = {}, Counter()
    for article in data['articles']:
        for image in article.get('images', []):
            counts['image_references'] += 1
            digest = image.get('sha256') or ''
            if (image.get('status') != 'downloaded' or not image.get('local_path')
                    or not re.fullmatch('[0-9a-f]{64}', digest)):
                counts['unavailable_references'] += 1
                continue
            path = (ROOT / image['local_path']).resolve()
            if not path.is_relative_to(ROOT / 'data/trend_data/images'):
                raise ValueError('来源路径越出趋势图库：' + image['local_path'])
            reference = {'image_id': image['image_id'], 'source_path': image['local_path'],
                         'source_id': article['source_id'], 'article_id': article['original_id'],
                         'article_title': article['title'], 'article_url': article.get('source_url'),
                         'image_url': image.get('source_url'),
                         'directions': article.get('direction_membership', [])}
            if digest not in groups:
                groups[digest] = {'image_id': image['image_id'], 'source_path': str(path),
                                  'image_sha256': digest, 'source_kind': 'trend',
                                  'references': []}
            groups[digest]['references'].append(reference)
    counts['unique_downloaded_images'] = len(groups)
    remaining = [item for digest, item in groups.items() if digest not in excluded_hashes]
    counts['excluded_unique_images'] = len(groups) - len(remaining)
    selected = remaining if limit is None else remaining[:limit]
    for index, item in enumerate(selected, 1):
        item['entry_id'] = f'I{index:04d}'
        item['provenance'] = {'verified': True, 'source_kind': 'trend',
                              'source_ref': str(source), 'source_sha256': source_digest}
    return selected, dict(counts)


def prepare(source, folder, *, limit=1000, concurrency=5, model='gpt-6-sol', remaining_after=None):
    if not 1 <= concurrency <= 5:
        raise ValueError('并发必须为1–5')
    options = quality.model_options(model)
    excluded, exclusion = frozenset(), None
    if remaining_after is not None:
        # 用户明确执行全部剩余时，旧批次的成功、失败与未知提交都必须排除，不能暗中重试。
        previous_path = remaining_after / 'manifest.json'
        previous = json.loads(previous_path.read_bytes())
        summary = json.loads((remaining_after / 'summary.json').read_bytes())
        if summary['status'] != 'completed' or summary['finished'] != previous['selected_count']:
            raise ValueError('被排除批次尚未完成')
        if (previous['source_sha256'] != sha256(source.read_bytes()).hexdigest()
                or previous['model'] != model or previous['parameters'] != options
                or previous['prompt_sha256'] != sha256(quality.compact.PROMPT_PATH.read_bytes()).hexdigest()):
            raise ValueError('来源清单／模型／参数／提示与旧批次不同，不能声称同方式续跑')
        if not all((remaining_after / 'calls' / (item['entry_id'] + '.json')).is_file()
                   for item in previous['entries']):
            raise ValueError('旧批次有缺失的提交账本')
        excluded = frozenset(item['image_sha256'] for item in previous['entries'])
        exclusion = {'batch': str(remaining_after),
                     'manifest_sha256': sha256(previous_path.read_bytes()).hexdigest(),
                     'excluded_image_hashes': sorted(excluded)}
        limit = None
    selected, population = select_images(source, limit, excluded_hashes=excluded)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'inputs').mkdir()
    (folder / 'calls').mkdir()
    (folder / 'source.snapshot.json').write_bytes(source.read_bytes())
    (folder / 'prompt.txt').write_bytes(quality.compact.PROMPT_PATH.read_bytes())
    for index, item in enumerate(selected, 1):
        try:
            data, metadata = quality.prepare_image(Path(item['source_path']))
            if metadata['image_sha256'] != item['image_sha256']:
                raise ValueError('原图哈希与来源库存不一致')
            suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(metadata['mime_type'], '.image')
            item.update(snapshot='inputs/' + item['entry_id'] + suffix, preprocessing=metadata)
            (folder / item['snapshot']).write_bytes(data)
        except Exception as exc:
            item['prepare_error'] = _safe_exception(exc)
        if index % 100 == 0:
            print(json.dumps({'stage': 'prepare', 'images': index, 'target': len(selected)}), flush=True)
    hashes = {}
    for name in [Path(__file__), Path(quality.__file__), Path(quality.compact.__file__),
                 ROOT / 'backend/app/agents/dna_deep_agent.py']:
        (folder / (name.name + '.snapshot')).write_bytes(name.read_bytes())
        hashes[str(name)] = sha256(name.read_bytes()).hexdigest()
    manifest = {'schema_version': 'prism.quality_handshake_batch.v1', 'created_at': now(),
                'source': str(source), 'source_sha256': sha256(source.read_bytes()).hexdigest(),
                'population': population,
                'selection': 'all_remaining_unique_hashes_in_source_order' if exclusion else 'first_unique_hashes_in_source_order',
                'exclusion': exclusion,
                'requested_limit': limit, 'selected_count': len(selected), 'model': model,
                'concurrency': concurrency, 'max_requests': len(selected), 'automatic_retries': 0,
                'parameters': options, 'version': quality.compact.VERSION,
                'prompt_sha256': sha256(quality.compact.PROMPT_PATH.read_bytes()).hexdigest(),
                'code_sha256': hashes, 'production_admission': False, 'entries': selected}
    save(folder / 'manifest.json', manifest)
    export(folder, manifest, {}, status='prepared', started_at=None, max_active=0)
    print(json.dumps({'stage': 'prepared', 'out': str(folder), 'population': population,
                      'selected': len(selected), 'concurrency': concurrency, 'model': model}), flush=True)


def export(folder, manifest, records, *, status, started_at, max_active, full=True):
    """仅导出候选清单；失败／未知不计为审美淘汰，失败用量缺失也不当零成本。"""
    entries = []
    for item in manifest['entries']:
        if item['entry_id'] in records:
            entries.append(dict(item, result=records[item['entry_id']]))
    counts = Counter(record.get('decision') or record['status'] for record in records.values())
    usages = [record.get('usage', {}) for record in records.values()]
    submitted = sum(value.get('llm_request_count', 0) for value in usages)
    summary = {'status': status, 'updated_at': now(), 'started_at': started_at,
               'model': manifest['model'], 'selected': len(manifest['entries']),
               'finished': len(records), 'remaining': len(manifest['entries']) - len(records),
               'counts': dict(counts), 'concurrency': manifest['concurrency'], 'max_active': max_active,
               'recorded_llm_requests': submitted, 'max_requests': manifest['max_requests'],
               'requests_with_usage': sum(value.get('requests_with_usage', 0) for value in usages),
               'known_input_tokens': sum(value.get('input_tokens', 0) for value in usages),
               'known_output_tokens': sum(value.get('output_tokens', 0) for value in usages),
               'known_total_tokens': sum(value.get('total_tokens', 0) for value in usages),
               'unknown_submission_states': counts['execution_unknown'],
               'production_admission': False}
    save(folder / 'summary.json', summary)
    if not full:
        return summary
    save(folder / 'results.json', {'summary': summary, 'entries': entries})
    for filename, predicate in [
        ('passed.json', lambda x: x.get('decision') == 'PASS'),
        ('rejected.json', lambda x: x.get('decision') == 'FAIL'),
        ('review.json', lambda x: x['status'] == 'needs_review'),
        ('failed.json', lambda x: x['status'] in {'execution_error', 'execution_unknown', 'invalid_output', 'input_error'}),
    ]:
        save(folder / filename, [item for item in entries if predicate(item['result'])])
    cards = []
    for item in entries:
        result = item['result']
        kind = result.get('decision') or result['status']
        label = {'PASS': '通过', 'FAIL': '不通过', 'needs_review': '待复核'}.get(kind, '失败／跳过')
        image = f'<img loading="lazy" src="{escape(item["snapshot"])}">' if item.get('snapshot') else ''
        cards.append(f'<section data-kind="{escape(kind)}"><h3>{escape(item["image_id"])}</h3>'
                     + image + f'<p>{label} · {result.get("duration_seconds", 0)} 秒</p>'
                     + f'<small>{escape(item["references"][0]["article_title"])}</small></section>')
    (folder / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>握手趋势图筛选</title>'
        '<style>body{font:16px system-ui;margin:30px;background:#f6f6f6}main{display:flex;flex-wrap:wrap;gap:16px}'
        'section{background:white;padding:16px;width:280px}img{width:100%;height:230px;object-fit:contain}select{padding:8px}</style>'
        f'<h1>握手趋势图筛选</h1><p>{escape(manifest["model"])} · 完成 {len(records)}/{len(manifest["entries"])} · {escape(status)}</p>'
        + f'<p>{escape(json.dumps(dict(counts),ensure_ascii=False))}</p>'
        + '<p><a href="passed.json">通过清单</a> · <a href="rejected.json">不通过清单</a> · <a href="failed.json">失败记录</a> · <a href="summary.json">进度及用量</a></p>'
        + '<select onchange="document.querySelectorAll(\'section\').forEach(e=>e.hidden=this.value!==\'all\'&&e.dataset.kind!==this.value)">'
        + '<option value="all">全部</option><option value="PASS">通过</option><option value="FAIL">不通过</option><option value="needs_review">待复核</option><option value="execution_error">调用失败</option></select>'
        + '<main>' + ''.join(cards) + '</main>')
    return summary


async def execute(folder):
    # 非阻塞进程锁阻止第二个运行器同时消费同一冻结批次。
    with (folder / 'run.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest['parameters'] != quality.model_options(manifest['model']):
            raise ValueError('模型配置与冻结参数不同')
        if sha256(quality.compact.PROMPT_PATH.read_bytes()).hexdigest() != manifest['prompt_sha256']:
            raise ValueError('提示词版本已变更')
        for filename, digest in manifest['code_sha256'].items():
            if sha256(Path(filename).read_bytes()).hexdigest() != digest:
                raise ValueError('冻结代码已变更：' + filename)
        records, pending = {}, []
        for item in manifest['entries']:
            call_path = folder / 'calls' / (item['entry_id'] + '.json')
            if call_path.exists():
                record = json.loads(call_path.read_text())
                if record.get('state') == 'submitted':
                    record.update(status='execution_unknown', decision=None,
                                  error='前次提交状态未知，跳过且不重发')
                records[item['entry_id']] = record
            else:
                pending.append(item)
        previous_summary = json.loads((folder / 'summary.json').read_text()) if (folder / 'summary.json').exists() else {}
        started_at, timer = previous_summary.get('started_at') or now(), monotonic()
        active, max_active = 0, previous_summary.get('max_active', 0)
        iterator = iter(pending)
        export(folder, manifest, records, status='running', started_at=started_at, max_active=0)

        async def worker():
            nonlocal active, max_active
            for item in iterator:
                destination = folder / 'calls' / (item['entry_id'] + '.json')
                request = {'state': 'submitted', 'image_id': item['image_id'], 'entry_id': item['entry_id'],
                           'model': manifest['model'], 'started_at': now(), 'decision': None,
                           'image_sha256': item['image_sha256'], 'prompt_sha256': manifest['prompt_sha256'],
                           'parameters': manifest['parameters'], 'version': manifest['version']}
                with destination.open('x') as handle:
                    json.dump(request, handle)
                try:
                    if item.get('prepare_error'):
                        raise ValueError(item['prepare_error'])
                    data = (folder / item['snapshot']).read_bytes()
                    if sha256(data).hexdigest() != item['preprocessing']['input_image_sha256']:
                        raise ValueError('冻结发送图哈希不一致')
                except Exception as exc:
                    record = dict(request, status='input_error', error=_safe_exception(exc),
                                  finished_at=now(), duration_seconds=0)
                else:
                    active += 1
                    max_active = max(max_active, active)
                    try:
                        record = await quality.classify(data, item['preprocessing'],
                                                        image_id=item['image_id'], model_id=manifest['model'])
                    except Exception as exc:
                        # 调用外层异常也永久留账，不在下一轮当作未处理图重发。
                        record = dict(request, status='execution_unknown', error=_safe_exception(exc),
                                      finished_at=now(), duration_seconds=0)
                    finally:
                        active -= 1
                record.update(state='finished', entry_id=item['entry_id'], source_kind='trend',
                              source_path=item['source_path'], provenance=item['provenance'], production_admission=False)
                save(destination, record)
                records[item['entry_id']] = record
                # 大批次每图刷新轻量进度，每100张导出完整清单与浏览页，避免逐图重写整库。
                summary = export(folder, manifest, records, status='running', started_at=started_at,
                                 max_active=max_active, full=len(records) <= 5 or len(records) % 100 == 0)
                print(json.dumps({'at': now(), 'entry_id': item['entry_id'], 'decision': record.get('decision'),
                                  'status': record['status'], 'duration_seconds': record.get('duration_seconds'),
                                  'finished': summary['finished'], 'selected': summary['selected'],
                                  'active': active, 'known_tokens': summary['known_total_tokens']},ensure_ascii=False), flush=True)

        await asyncio.gather(*(worker() for _ in range(manifest['concurrency'])))
        summary = export(folder, manifest, records, status='completed', started_at=started_at, max_active=max_active)
        summary['run_seconds'] = round(monotonic() - timer, 3)
        save(folder / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'status'])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--remaining-after', type=Path,
                        help='显式处理此已完成批次之外的全部剩余图，保留其失败且不重试')
    parser.add_argument('--concurrency', type=int, default=5)
    parser.add_argument('--model', choices=['gpt-6-sol', 'gemini-3.8-flash'], default='gpt-6-sol')
    args = parser.parse_args()
    folder = args.out.resolve()
    if args.command == 'prepare':
        if not args.source:
            parser.error('prepare 必须提供 --source')
        if args.remaining_after and args.limit is not None:
            parser.error('--remaining-after 与 --limit 不能同时使用')
        prepare(args.source.resolve(), folder, limit=args.limit or 1000,
                concurrency=args.concurrency, model=args.model,
                remaining_after=args.remaining_after.resolve() if args.remaining_after else None)
    elif args.command == 'run':
        asyncio.run(execute(folder))
    else:
        print((folder / 'summary.json').read_text())


if __name__ == '__main__':
    main()
