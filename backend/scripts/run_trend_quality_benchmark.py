"""D03 随机十图双模型实测：冻结样本，串行交替调用，留存原回复与计时。"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
import json
import mimetypes
from pathlib import Path
import random
import secrets
import statistics
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.agents/skills/prism-trend-quality'
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(SKILL / 'runtime'))

from app.agents.dna_deep_agent import _model_options, create_dna_agent
from app.services.dna.prism_r5 import _reply, _safe_exception
from app.services.llm.catalog import get_model
from app.services.llm.telemetry import ModelCallTelemetry
from langchain_core.messages import HumanMessage
from PIL import Image
from prism_runtime.quality import curation

MODELS = ('gemini-3.8-flash', 'gpt-6-sol')
INVENTORY = ROOT / 'data/trend_data/trend_info_0930/trends.json'


def now():
    return datetime.now(UTC).isoformat()


def write(path, value):
    """逐请求原子落盘，恢复时不重发已提交或状态未知的请求。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def prepare(folder):
    if folder.exists():
        raise ValueError('输出目录已存在；不能静默覆盖或重新抽样')
    calibration = json.loads((SKILL / 'references/calibration-20261002.json').read_text())
    excluded = {item['image_sha256'] for item in calibration['images']}
    inventory_raw = INVENTORY.read_bytes()
    inventory = json.loads(inventory_raw)
    candidates = {}
    for article in inventory['trends']:
        for item in article.get('images', []):
            if item.get('status') != 'downloaded' or not item.get('sha256'):
                continue
            path = (INVENTORY.parent / item['local_path']).resolve()
            content_hash = item['sha256']
            if (content_hash in excluded or not path.is_file()
                    or not path.is_relative_to(ROOT / 'data/trend_data/images')):
                continue
            candidates.setdefault(content_hash, {
                'image_id': item['image_id'], 'article_id': article['id'],
                'source_path': str(path.relative_to(ROOT)), 'image_sha256': content_hash,
                'provenance': {'verified': True, 'source_kind': 'trend',
                               'source_ref': str(INVENTORY.relative_to(ROOT)),
                               'url': item['url']},
            })
    population = [candidates[key] for key in sorted(candidates)]
    seed = secrets.randbits(64)
    sample = random.Random(seed).sample(population, 10)
    # 只检查抽中的原图；验证失败就停止，不暗中重抽成容易通过的图片。
    for item in sample:
        path = ROOT / item['source_path']
        if digest(path) != item['image_sha256']:
            raise ValueError('抽中图片与库存哈希不同：' + item['source_path'])
        with Image.open(path) as image:
            item['pixels'] = list(image.size)
            image.verify()
    folder.mkdir(parents=True)
    for index, item in enumerate(sample, 1):
        source = ROOT / item['source_path']
        item['sample_id'] = f'S{index:02d}'
        item['snapshot'] = f'images/{item["sample_id"]}{source.suffix.lower()}'
        destination = folder / item['snapshot']
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(source.read_bytes())
    snapshots = ['SKILL.md', 'references/prompts/curation-v0.7.0.txt',
                 'runtime/prism_runtime/quality/curation.py',
                 'runtime/prism_runtime/quality/signal_gate.py']
    skill_files = {}
    for name in snapshots:
        destination = folder / 'skill_snapshot' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((SKILL / name).read_bytes())
        skill_files[name] = digest(destination)
    (folder / 'runner.snapshot.py').write_bytes(Path(__file__).read_bytes())
    manifest = {
        'schema_version': 'prism.quality_model_benchmark.v1', 'created_at': now(),
        'seed': seed, 'sampling': 'uniform_without_replacement_over_unique_inventory_sha256',
        'candidate_count': len(population), 'excluded_calibration_hashes': sorted(excluded),
        'population_sha256': sha256(json.dumps(population, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'inventory': str(INVENTORY.relative_to(ROOT)),
        'inventory_sha256': sha256(inventory_raw).hexdigest(),
        'sample': sample, 'models': list(MODELS), 'policy_version': curation.VERSION,
        'skill_files': skill_files, 'preprocessing': 'none: original image bytes sent to both models',
        'model_options': {model: _model_options(model) for model in MODELS},
        'execution': 'serial; Gemini first on odd rows, GPT first on even rows',
        'max_primary_requests': 20, 'max_format_confirmations': 20,
        'automatic_transport_retries': 0, 'production_admission': False,
        'runner_sha256': digest(folder / 'runner.snapshot.py'),
        'engine_adapter_sha256': digest(ROOT / 'backend/app/agents/dna_deep_agent.py'),
    }
    write(folder / 'manifest.json', manifest)
    write(folder / 'results.json', {'started_at': None, 'finished_at': None, 'rows': []})
    print(json.dumps({'prepared': str(folder), 'seed': seed, 'candidate_count': len(population),
                      'sample': [{k: item[k] for k in ('sample_id', 'image_id', 'source_path')} for item in sample]},
                     ensure_ascii=False), flush=True)


class OneRequestTelemetry(ModelCallTelemetry):
    """每阶段最多一次内部模型调用，避免 DeepAgents 工具循环引起隐式收费。"""

    raise_error = True

    def on_chat_model_start(self, *args, **kwargs):
        if self.request_count:
            raise RuntimeError('当前阶段已提交一次模型请求，禁止工具循环追加请求')
        super().on_chat_model_start(*args, **kwargs)


def call(folder, item, model, stage):
    telemetry = OneRequestTelemetry()
    version = curation.PRIMARY_VERSION if stage == 'primary' else curation.CONFIRMATION_VERSION
    request = {
        'image_id': item['image_id'], 'version': version, 'image_sha256': item['image_sha256'],
        'input_image_sha256': digest(folder / item['snapshot']),
        'prompt_sha256': digest(folder / 'skill_snapshot/references/prompts/curation-v0.7.0.txt'),
        'model': get_model(model).id, 'parameters': _model_options(model), 'started_at': now(),
        'finished_at': None, 'http_status': None, 'model_features': None,
    }
    destination = folder / 'calls' / item['sample_id'] / model / (stage + '.json')
    if destination.exists():
        raise ValueError('阶段记录已存在，禁止再次提交：' + str(destination))
    write(destination, dict(request, state='submitted'))
    timer = monotonic()
    try:
        prompt = (folder / 'skill_snapshot/references/prompts/curation-v0.7.0.txt').read_text()
        agent = create_dna_agent(model, prompt, 'prism-trend-quality-benchmark')
        payload = base64.b64encode((folder / item['snapshot']).read_bytes()).decode('ascii')
        result = agent.invoke({'messages': [HumanMessage(content=[{
            'type': 'image', 'base64': payload,
            'mime_type': mimetypes.guess_type(item['snapshot'])[0] or 'image/jpeg',
        }])]}, config={'callbacks': [telemetry], 'recursion_limit': 40})
        request['http_status'] = 200
        request['http_status_source'] = 'successful_sdk_completion'
        raw = _reply(result)
        request['raw_response'] = raw
        text = raw.strip()
        if text.startswith('```') and text.endswith('```'):
            text = '\n'.join(text.splitlines()[1:-1]).strip()
        try:
            request['model_features'] = json.loads(text)
        except ValueError as exc:
            request['parse_error'] = str(exc)
        last = result['messages'][-1]
        metadata = getattr(last, 'response_metadata', {})
        request['response_metadata'] = {key: metadata[key] for key in
                                        ('model_name', 'model_provider', 'finish_reason', 'id') if key in metadata}
        request['message_usage_metadata'] = getattr(last, 'usage_metadata', None)
    except Exception as exc:
        request['error'] = _safe_exception(exc)
        request['http_status'] = getattr(exc, 'status_code', None) or 0
    finally:
        request.update(finished_at=now(), duration_seconds=round(monotonic() - timer, 3),
                       usage=telemetry.snapshot(), state='finished')
        write(destination, request)
    return request


def summarize(folder, manifest, results):
    """区分完整判定、未决及执行错误；计时与用量均取真实回执。"""
    summary = {'models': {}, 'rows': [], 'sample_count': len(manifest['sample']),
               'started_at': results['started_at'], 'finished_at': results['finished_at']}
    for model in MODELS:
        rows = [row for row in results['rows'] if row['model'] == model]
        durations = [row['duration_seconds'] for row in rows]
        first = [row['attempts'][0]['duration_seconds'] for row in rows]
        completed = [row['duration_seconds'] for row in rows if row['resolved']['status'] == 'complete']
        failed = [row['duration_seconds'] for row in rows if row['resolved']['status'] == 'execution_error']
        decisions = Counter(row['resolved']['decision'] or row['resolved']['status'] for row in rows)
        usages = [attempt['usage'] for row in rows for attempt in row['attempts']]
        reasoning = []
        for row in rows:
            for attempt in row['attempts']:
                message_usage = attempt.get('message_usage_metadata') or {}
                value = message_usage.get('output_token_details', {}).get('reasoning')
                if type(value) is int:
                    reasoning.append(value)
        summary['models'][model] = {
            'images_attempted': len(rows), 'results': dict(decisions),
            'primary_mean_seconds': round(statistics.mean(first), 3) if first else None,
            'image_mean_seconds': round(statistics.mean(durations), 3) if durations else None,
            'image_median_seconds': round(statistics.median(durations), 3) if durations else None,
            'complete_mean_seconds': round(statistics.mean(completed), 3) if completed else None,
            'execution_error_mean_seconds': round(statistics.mean(failed), 3) if failed else None,
            'total_request_seconds': round(sum(durations), 3),
            'format_confirmation_count': sum(len(row['attempts']) - 1 for row in rows),
            'llm_requests': sum(value['llm_request_count'] for value in usages),
            'input_tokens': sum(value['input_tokens'] for value in usages),
            'output_tokens': sum(value['output_tokens'] for value in usages),
            'total_tokens': sum(value['total_tokens'] for value in usages),
            'requests_with_usage': sum(value['requests_with_usage'] for value in usages),
            'usage_covers_all_submissions': all(value['requests_with_usage'] == value['llm_request_count'] for value in usages),
            # 供应方推理 Token 是输出 Token 的组成部分，不能再加到总量中。
            'reasoning_tokens_in_reported_output': sum(reasoning) if reasoning else None,
            'requests_with_reasoning_breakdown': len(reasoning),
        }
    agreements = 0
    comparable = 0
    paired_durations = {model: [] for model in MODELS}
    for item in manifest['sample']:
        row = {'sample_id': item['sample_id'], 'image_id': item['image_id'], 'models': {}}
        for model in MODELS:
            found = next((r for r in results['rows'] if r['sample_id'] == item['sample_id'] and r['model'] == model), None)
            if found:
                features = found['resolved'].get('model_features')
                row['models'][model] = {
                    'decision': found['resolved']['decision'], 'status': found['resolved']['status'],
                    'duration_seconds': found['duration_seconds'],
                    'reason': features.get('reason') if isinstance(features, dict) else found['resolved'].get('error'),
                    'reference_readiness': features.get('reference_readiness') if isinstance(features, dict) else None,
                    'evidence': features.get('evidence') if isinstance(features, dict) else None,
                }
        both = list(row['models'].values())
        if len(both) == 2 and all(r['decision'] in ('PASS', 'FAIL') for r in both):
            comparable += 1
            agreements += both[0]['decision'] == both[1]['decision']
            for model in MODELS:
                paired_durations[model].append(row['models'][model]['duration_seconds'])
        summary['rows'].append(row)
    summary.update(comparable_pairs=comparable, decision_agreements=agreements,
                   decision_disagreements=comparable - agreements)
    # 速度结论使用双方均有有效判定的同图子集，避免不同成功样本造成偏差。
    for model in MODELS:
        paired = paired_durations[model]
        summary['models'][model]['paired_complete_mean_seconds'] = round(statistics.mean(paired), 3) if paired else None
        summary['models'][model]['paired_complete_count'] = len(paired)
    write(folder / 'summary.json', summary)
    report = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>D03 双模型十图对比</title>',
              '<style>body{font:16px/1.6 system-ui;margin:32px;color:#223}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:10px;text-align:left}img{max-width:100%;max-height:440px}section{margin:30px 0;padding:20px;border:1px solid #ccd;border-radius:12px}.models{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap}a{color:#246}</style>',
              '<h1>D03 · Gemini 3.8 Flash / GPT-6 Sol 十图对比</h1>',
              '<p>同一随机十图；排除参与规则校准的十图；原图原字节、同一 v0.7 提示词。串行执行且交替模型顺序。GPT 使用工程默认 low 推理，Gemini temperature=0。耗时包括客户端创建、网络、生成与解析。没有人工正反标签，结果一致性不等于准确率。</p>',
              '<p><a href="summary.json">统计 JSON</a> · <a href="manifest.json">随机清单</a> · <a href="results.json">原回复与调用记录</a></p>',
              '<table><tr><th>模型</th><th>结果分布</th><th>成功判标均值</th><th>双方成功同图均值</th><th>错误返回均值</th><th>请求累计耗时</th><th>模型提交数</th><th>已返回用量的 Token</th></tr>']
    for model, value in summary['models'].items():
        report.append('<tr>' + ''.join('<td>' + escape(str(x)) + '</td>' for x in
                                      (model, value['results'], value['complete_mean_seconds'],
                                       value['paired_complete_mean_seconds'],
                                       value['execution_error_mean_seconds'], value['total_request_seconds'],
                                       value['llm_requests'], value['total_tokens'] if value['requests_with_usage'] else '未知')) + '</tr>')
    report.append(f'</table><p>可比较的明确判定 {comparable} 对，一致 {agreements} 对，分歧 {comparable-agreements} 对。</p>')
    report.append('<p>Token 统计只含已返回的回执，失败请求的用量未知；不同模型的图片 Token 计量口径不同，不能据此直接比较费用。推理 Token 已包含在输出量内。</p>')
    for item, row in zip(manifest['sample'], summary['rows']):
        report.append(f'<section><h2>{item["sample_id"]} · {escape(item["image_id"])}</h2><p>{escape(item["source_path"])}</p><a href="{escape(item["snapshot"])}"><img src="{escape(item["snapshot"])}"></a><div class="models">')
        for model in MODELS:
            value = row['models'].get(model)
            report.append('<div><h3>' + escape(model) + '</h3><pre>' + escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></div>')
        report.append('</div></section>')
    (folder / 'report.html').write_text('\n'.join(report) + '</html>')
    return summary


def execute(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    for name, expected in manifest['skill_files'].items():
        if digest(SKILL / name) != expected:
            raise ValueError('Skill 在抽样后已改变，停止：' + name)
    results = json.loads((folder / 'results.json').read_text())
    if results['rows'] or any((folder / 'calls').rglob('*.json')):
        raise ValueError('已有提交记录，禁止再次执行；不要用重跑掩盖失败或重复收费')
    results['started_at'] = now()
    write(folder / 'results.json', results)
    stopped_models = set()
    try:
        for index, item in enumerate(manifest['sample']):
            for model in MODELS if index % 2 == 0 else tuple(reversed(MODELS)):
                if model in stopped_models:
                    continue
                attempts = [call(folder, item, model, 'primary')]
                if curation.confirmation_reason(attempts[0]):
                    attempts.append(call(folder, item, model, 'confirmation'))
                resolved = curation.resolve(attempts[0], attempts[1] if len(attempts) == 2 else None)
                duration = round(sum(attempt['duration_seconds'] for attempt in attempts), 3)
                results['rows'].append({'sample_id': item['sample_id'], 'model': model,
                                        'duration_seconds': duration, 'attempts': attempts, 'resolved': resolved})
                write(folder / 'results.json', results)
                print(json.dumps({'sample': item['sample_id'], 'model': model, 'duration_seconds': duration,
                                  'decision': resolved['decision'], 'status': resolved['status'],
                                  'calls': sum(a['usage']['llm_request_count'] for a in attempts)}, ensure_ascii=False), flush=True)
                # 真实 HTTP 状态触发停发；不搜索随机追踪 ID 中的数字。
                if any(attempt['http_status'] in (401, 403, 429) for attempt in attempts):
                    stopped_models.add(model)
    finally:
        results['finished_at'] = now()
        results['stopped_models'] = sorted(stopped_models)
        write(folder / 'results.json', results)
        summary = summarize(folder, manifest, results)
        print(json.dumps(summary['models'], ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='使用工程当前网关发起真实模型请求')
    args = parser.parse_args()
    folder = args.out.resolve()
    if args.execute:
        execute(folder)
    else:
        prepare(folder)


if __name__ == '__main__':
    main()
