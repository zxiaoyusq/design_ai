"""One-image Sol R5 CLI. Default prepares locally; --execute makes model calls."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import re
import shutil
import subprocess
import sys
import time

from engine import ROOT, canonical, file_hash, read, write_new, load_original, primary, finish, refinement_job, apply_refinement, replay_examples, validate

MODEL = 'gpt-6-sol'
DISABLED = ['apps', 'plugins', 'memories', 'multi_agent', 'multi_agent_v2', 'shell_tool', 'unified_exec',
            'browser_use', 'computer_use', 'image_generation', 'view_image', 'sleep_tool', 'goals',
            'unbounded_connection_retries', 'shell_snapshot', 'fast_mode', 'hooks']


def command(cli, run, call_dir, image):
    configs = [
        'model_reasoning_effort="low"', 'service_tier="default"',
        'model_provider="prism_sol_r5_openai"',
        'model_providers.prism_sol_r5_openai.name="Prism Sol R5 standard"',
        'model_providers.prism_sol_r5_openai.requires_openai_auth=true',
        'model_providers.prism_sol_r5_openai.wire_api="responses"',
        'model_providers.prism_sol_r5_openai.supports_websockets=false',
        'model_providers.prism_sol_r5_openai.request_max_retries=0',
        'model_providers.prism_sol_r5_openai.stream_max_retries=0',
        'skills.max_context_tokens=1', 'project_doc_max_bytes=0',
        'model_instructions_file=' + json.dumps((ROOT / 'assets/vision-only.txt').as_posix(), ensure_ascii=False),
        'log_dir=' + json.dumps((call_dir / 'logs').as_posix(), ensure_ascii=False),
        'sqlite_home=' + json.dumps((run / 'private-runtime-state').as_posix(), ensure_ascii=False),
    ]
    args = [cli, 'exec', '--ignore-user-config', '--ephemeral', '--json', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--model', MODEL, '--color', 'never', '--strict-config',
            '--output-schema', str(call_dir / 'schema.json'), '--output-last-message', str(call_dir / 'answer.json')]
    for config in configs:
        args.extend(['-c', config])
    for flag in DISABLED:
        args.extend(['--disable', flag])
    args.extend(['--image', str(image), '-'])
    return args


def doctor(cli):
    resolved = shutil.which(cli) or (cli if Path(cli).is_file() else None)
    if not resolved:
        return {'ready': False, 'reason': 'Codex CLI not found; provide --codex PATH', 'model_request_sent': False}
    r = subprocess.run([resolved, 'exec', '--help'], capture_output=True, text=True, encoding='utf-8', timeout=20)
    required = ['--ignore-user-config', '--ephemeral', '--json', '--output-schema', '--image', '--strict-config', '--disable']
    missing = [x for x in required if x not in r.stdout]
    return {'ready': r.returncode == 0 and not missing, 'cli': resolved, 'missing_flags': missing,
            'account_or_model_access_verified': False, 'model_request_sent': False}


def call(engine, run, call_id, prompt, schema, image, cli, timeout, ledger, max_calls):
    if len(ledger['calls']) >= max_calls:
        raise RuntimeError('Request budget exhausted; no automatic retry')
    call_dir = run / 'calls' / call_id
    call_dir.mkdir(parents=True, exist_ok=False)
    write_new(call_dir / 'prompt.txt', prompt, text=True)
    write_new(call_dir / 'schema.json', schema)
    args = command(cli, run, call_dir, image)
    request = {'call_id': call_id, 'model': MODEL, 'reasoning_effort': 'low', 'service_tier_requested': 'default',
               'fast_mode': False, 'actual_served_tier': 'not_exposed', 'command': args,
               'image_sha256': file_hash(image), 'prompt_sha256': file_hash(call_dir / 'prompt.txt'),
               'schema_sha256': file_hash(call_dir / 'schema.json'), 'max_attempts': 1, 'timeout_seconds': timeout}
    write_new(call_dir / 'request.json', request)
    entry = {'call_id': call_id, 'state': 'attempt_started', 'started_at': datetime.now(timezone.utc).isoformat()}
    ledger['calls'].append(entry)
    (run / 'call-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
    start = time.monotonic()
    answer, stderr, stdout, error = None, '', '', None
    timed_out, returncode = False, None
    try:
        result = subprocess.run(args, input=prompt, cwd=str(run / 'empty-workspace'), capture_output=True,
                                text=True, encoding='utf-8', timeout=timeout)
        returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = e.stdout.decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else e.stdout or ''
        stderr = e.stderr.decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else e.stderr or ''
        error = 'timeout_no_retry'
    except OSError as e:
        error = type(e).__name__ + ': ' + str(e)
    write_new(call_dir / 'events.jsonl', stdout, text=True)
    write_new(call_dir / 'stderr.log', stderr, text=True)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    tool_events = [x for x in events if x.get('item', {}).get('type') in
                   {'command_execution', 'mcp_tool_call', 'web_search', 'file_change', 'image_generation', 'collab_tool_call'}]
    usage = next((e.get('usage') for e in reversed(events) if e.get('type') == 'turn.completed'), None)
    if returncode == 0 and not timed_out and not tool_events:
        try:
            answer = read(call_dir / 'answer.json')
            validate(engine, schema, answer)
        except (OSError, ValueError) as e:
            error, answer = str(e), None
    else:
        error = error or ('tool_events_not_allowed' if tool_events else 'nonzero_cli_exit')
    receipt = {'call_id': call_id, 'exit_code': returncode, 'timed_out': timed_out, 'schema_valid': answer is not None,
               'wall_seconds': round(time.monotonic() - start, 4), 'usage': usage,
               'tool_events': tool_events, 'error': error, 'state': 'response_received' if answer is not None else 'failed_no_retry'}
    write_new(call_dir / 'receipt.json', receipt)
    entry.update(receipt)
    (run / 'call-ledger.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
    return answer, receipt


def parse(args):
    engine = load_original()
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.image_id):
        raise ValueError('image-id must be a stable ASCII identifier, without path separators')
    if args.timeout < 60 or args.timeout > 1800:
        raise ValueError('Use a bounded per-call timeout from 60 to 1800 seconds')
    image = args.image.resolve(strict=True)
    run = args.out.resolve()
    run.mkdir(parents=True, exist_ok=False)
    (run / 'empty-workspace').mkdir()
    max_calls = 3 if args.refine else 2
    write_new(run / 'primary.prompt.txt', engine.prompt(), text=True)
    write_new(run / 'primary.schema.json', engine.schema())
    prepared = {'algorithm_version': engine.VERSION, 'model': MODEL, 'reasoning_effort': 'low',
                'service_tier_requested': 'default', 'fast_mode': False, 'image_id': args.image_id,
                'image_path': str(image), 'image_sha256': file_hash(image), 'max_calls': max_calls,
                'automatic_retries': False, 'optional_refinement': args.refine,
                'few_shot_examples_in_runtime_input': False, 'status': 'prepared_only',
                'execution_requested': args.execute, 'timeout_seconds': args.timeout}
    write_new(run / 'prepared.json', prepared)
    if not args.execute:
        print(json.dumps(prepared, ensure_ascii=False))
        return 0
    environment = doctor(args.codex)
    write_new(run / 'cli-environment.json', environment)
    if not environment['ready']:
        raise RuntimeError('CLI preflight failed; no model request sent. See cli-environment.json')
    ledger = {'limit': max_calls, 'automatic_retries': False, 'calls': []}
    cid = args.image_id
    answer, receipt = call(engine, run, 'P-' + cid, engine.prompt(), engine.schema(), image,
                           environment['cli'], args.timeout, ledger, max_calls)
    if answer is None:
        print(json.dumps({'status': 'primary_failed_no_retry', 'run': str(run)}, ensure_ascii=False))
        return 2
    unpacked = primary(engine, answer, cid)
    write_new(run / 'unpacked.json', unpacked)
    focus, focus_receipt = None, None
    if unpacked['issues']:
        focus, focus_receipt = call(engine, run, 'F-' + cid, engine.focus_prompt(unpacked['issues']),
            engine.focus_schema(unpacked['issues']), image, environment['cli'], args.timeout, ledger, max_calls)
    final = finish(engine, unpacked, focus, cid)
    write_new(run / 'before-refinement.json', final)
    if args.refine and not (focus_receipt and focus is None):
        job = refinement_job(engine, args.refine, answer, final)
        write_new(run / 'refinement-plan.json', job)
        if job['target_count']:
            extra, extra_receipt = call(engine, run, 'H-' + cid, job['prompt'], job['schema'], image,
                                        environment['cli'], args.timeout, ledger, max_calls)
            if extra is not None:
                final = apply_refinement(engine, final, answer, job, extra, cid)
    final.update(image_sha256=prepared['image_sha256'], model=MODEL, reasoning_effort='low',
                 service_tier_requested='default', fast_mode=False, model_calls=len(ledger['calls']),
                 actual_served_tier='not_exposed', status='partial' if final['pending'] or final['invalid'] or any(x['state'] != 'response_received' for x in ledger['calls']) else 'accepted_for_pilot')
    write_new(run / 'result.json', final)
    print(json.dumps({k: final[k] for k in ['image_id', 'status', 'ID_unique', 'CMF_unique', 'pending_count', 'model_calls']}, ensure_ascii=False))
    return 0 if all(x['state'] == 'response_received' for x in ledger['calls']) else 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    q = sub.add_parser('parse')
    q.add_argument('--image', type=Path, required=True)
    q.add_argument('--image-id', required=True)
    q.add_argument('--out', type=Path, required=True)
    q.add_argument('--execute', action='store_true')
    q.add_argument('--refine', choices=['mixed-areas', 'optics'])
    q.add_argument('--codex', default='codex')
    q.add_argument('--timeout', type=int, default=600)
    sub.add_parser('self-test')
    q = sub.add_parser('doctor')
    q.add_argument('--codex', default='codex')
    args = p.parse_args()
    if args.action == 'self-test':
        result = replay_examples()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['passed'] else 2
    if args.action == 'doctor':
        result = doctor(args.codex)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['ready'] else 2
    return parse(args)


if __name__ == '__main__':
    sys.exit(main())
