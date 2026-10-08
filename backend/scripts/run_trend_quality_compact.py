"""先离线冻结少量输入，再显式执行 D03 极简判标；已有账本不重发。"""

import argparse
import asyncio
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agents import trend_quality as quality


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare(folder, images, models):
    if not images:
        raise ValueError('准备批次须指定 --images')
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'inputs').mkdir()
    (folder / 'calls').mkdir()
    samples = []
    for index, source in enumerate(images, 1):
        source = source.resolve()
        data, metadata = quality.prepare_image(source)
        name = f'S{index:02d}'
        suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(metadata['mime_type'], source.suffix)
        snapshot = f'inputs/{name}{suffix}'
        (folder / snapshot).write_bytes(data)
        samples.append({'image_id': name, 'source_path': str(source),
                        'snapshot': snapshot, 'preprocessing': metadata})
    prompt = quality.compact.PROMPT_PATH.read_bytes()
    (folder / 'prompt.txt').write_bytes(prompt)
    code_files = [Path(__file__), Path(quality.__file__), Path(quality.compact.__file__)]
    hashes = {}
    for path in code_files:
        (folder / (path.name + '.snapshot')).write_bytes(path.read_bytes())
        hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
    write(folder / 'manifest.json', {
        'version': quality.compact.VERSION, 'samples': samples, 'models': models,
        'prompt_sha256': sha256(prompt).hexdigest(), 'code_sha256': hashes,
        'parameters': {model: quality.model_options(model) for model in models},
        'production_admission': False, 'max_requests': len(samples) * len(models),
        'automatic_retries': 0, 'execution': 'serial, alternating model order',
    })
    print(json.dumps({'prepared': str(folder), 'images': len(samples),
                      'original_bytes': sum(s['preprocessing']['original_bytes'] for s in samples),
                      'input_bytes': sum(s['preprocessing']['input_bytes'] for s in samples)}), flush=True)


async def execute(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    if list((folder / 'calls').glob('*.json')):
        raise ValueError('已有提交账本（含失败或未知状态），禁止整批重发')
    if sha256(quality.compact.PROMPT_PATH.read_bytes()).hexdigest() != manifest['prompt_sha256']:
        raise ValueError('当前提示词与冻结版本不一致')
    for filename, digest in manifest['code_sha256'].items():
        if sha256(Path(filename).read_bytes()).hexdigest() != digest:
            raise ValueError('执行代码已变更，须另建批次')
    for model in manifest['models']:
        if quality.model_options(model) != manifest['parameters'][model]:
            raise ValueError('模型配置与冻结参数不一致')
    # 先核验全部输入，避免执行到一半才发现部分冻结图片损坏。
    for item in manifest['samples']:
        if sha256((folder / item['snapshot']).read_bytes()).hexdigest() != item['preprocessing']['input_image_sha256']:
            raise ValueError('冻结图片哈希不一致')
    rows, stopped = [], set()
    timer = monotonic()
    for index, item in enumerate(manifest['samples']):
        order = manifest['models'] if index % 2 == 0 else manifest['models'][::-1]
        for model in order:
            if model in stopped:
                continue
            destination = folder / 'calls' / f'{item["image_id"]}_{model}.json'
            # 原子独占创建：崩溃或并发执行留下的未知提交也不能自动重发。
            with destination.open('x') as handle:
                json.dump({'state': 'submitted', 'image_id': item['image_id'], 'model': model}, handle)
            record = await quality.classify((folder / item['snapshot']).read_bytes(), item['preprocessing'],
                                            image_id=item['image_id'], model_id=model)
            write(destination, dict(record, state='finished'))
            rows.append(record)
            write(folder / 'results.json', {'rows': rows, 'batch_seconds': round(monotonic() - timer, 3)})
            print(json.dumps({k: record.get(k) for k in ('image_id', 'model', 'decision', 'status', 'duration_seconds', 'error')}), flush=True)
            if record.get('http_status') in {400, 401, 403, 404, 429}:
                stopped.add(model)
    render(folder, manifest, rows)


def render(folder, manifest, rows):
    """面向查看者只列判定和时间，完整追溯记录留在 JSON。"""
    cards = []
    for item in manifest['samples']:
        values = []
        for row in rows:
            if row['image_id'] == item['image_id']:
                verdict = {'PASS': '通过', 'FAIL': '不通过'}.get(row['decision'], row['status'])
                values.append(f'<p>{escape(row["model"])}：{escape(verdict)} · {row["duration_seconds"]} 秒</p>')
        cards.append(f'<section><h2>{item["image_id"]}</h2><img src="{escape(item["snapshot"])}">'
                     + ''.join(values) + f'<small>{escape(item["source_path"])}</small></section>')
    (folder / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>D03 极简判标</title>'
        '<style>body{font:16px system-ui;margin:32px;background:#f5f5f5}main{display:flex;flex-wrap:wrap;gap:24px}'
        'section{background:white;padding:20px;width:360px}img{width:100%;height:280px;object-fit:contain}small{overflow-wrap:anywhere}</style>'
        '<h1>D03 极简判标</h1><p>待复核及调用错误不计为不通过。本批次不写入生产图库。</p><main>' + ''.join(cards) + '</main>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--images', nargs='+', type=Path)
    # 极简回归中 Gemini 保住了用户反例；日常不默认双模型，避免额外消耗。
    parser.add_argument('--models', nargs='+', choices=['gemini-3.8-flash', 'gpt-6-sol'],
                        default=['gemini-3.8-flash'])
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        asyncio.run(execute(args.out.resolve()))
    else:
        prepare(args.out.resolve(), args.images, list(dict.fromkeys(args.models)))


if __name__ == '__main__':
    main()
