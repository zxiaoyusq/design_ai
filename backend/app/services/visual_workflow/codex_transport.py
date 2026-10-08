"""当前ChatGPT登录下的单轮Codex CLI视觉执行；隔离工程供应商，无回退/重试。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
from typing import Any

TRANSPORT = 'codex_cli_chatgpt'
MODEL = 'gpt-6.1-sol'
ENV_ALLOWLIST = {'PATH', 'HOME', 'CODEX_HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
                 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
                 'NODE_EXTRA_CA_CERTS', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}
SAFE_ITEM_TYPES = {'agent_message', 'reasoning'}


class CodexTransportError(RuntimeError):
    """错误元数据随异常返回，原始输出仍保留在调用目录，不重发付费请求。"""
    def __init__(self, message: str, *, metadata: dict | None = None, usage: dict | None = None):
        super().__init__(message)
        self.metadata = metadata or {}
        self.usage = usage or {}


def isolated_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """白名单继承运行/证书/网络设置；不继承APIkey、供应商URL或工程LLM变量。"""
    source = os.environ if source is None else source
    return {key: value for key, value in source.items() if key in ENV_ALLOWLIST}


def verify_chatgpt_auth(environment: dict[str, str]) -> dict:
    home = Path(environment.get('CODEX_HOME', str(Path(environment.get('HOME', '~')).expanduser() / '.codex')))
    try:
        auth = json.loads((home / 'auth.json').read_bytes())
    except (OSError, ValueError) as exc:
        raise CodexTransportError('Codex ChatGPT auth.json unavailable or invalid; no supplier fallback') from exc
    if auth.get('auth_mode') != 'chatgpt' or not isinstance(auth.get('tokens'), dict) or not auth['tokens'].get('access_token'):
        raise CodexTransportError('Codex must use existing ChatGPT token authentication; no supplier fallback')
    if auth.get('OPENAI_API_KEY'):
        raise CodexTransportError('API-key auth material is not permitted for this Codex transport')
    return {'auth_mode': 'chatgpt', 'chatgpt_tokens_present': True, 'api_key_used': False}


def build_stdin(system: str, payload: dict, images: list[dict]) -> str:
    mapping = [{'attachment_index': index + 1, 'role': image['role'],
                'candidate_id': image.get('candidate_id'), 'sha256': image['sha256']} for index, image in enumerate(images)]
    return ('这是一个独立、单轮、无工具的图片审阅请求。只使用本次直接附图与下方事实。'
            '不得调用任何工具、读取其他文件、浏览网页或加载技能；不得产生中间工具调用。'
            '严格依照阶段任务返回一个JSON对象，不输出Markdown围栏或其他文字。\n\n'
            '=== STAGE SYSTEM (verbatim) ===\n' + system + '\n\n'
            '=== ORDERED ATTACHMENT IDENTITY ===\n' + json.dumps(mapping, ensure_ascii=False) + '\n\n'
            '=== ACTUAL PAYLOAD ===\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')


def build_argv(folder: Path, images: list[dict], *, model: str = MODEL, effort: str = 'low') -> list[str]:
    if model != MODEL or effort != 'low':
        raise CodexTransportError('This transport is authorized only for gpt-6.1-sol with low reasoning')
    args = ['codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
            '--sandbox', 'read-only', '-m', model, '--json', '--color', 'never']
    for value in ('model_reasoning_effort="low"', 'features.shell_tool=false', 'features.multi_agent=false',
                  'features.view_image=false', 'features.image_generation=false', 'web_search="disabled"',
                  'project_doc_max_bytes=0'):
        args += ['--config', value]
    for image in images:
        args += ['-i', str(Path(image['path']).resolve())]
    return args + ['-o', str((folder / 'answer.raw.txt').resolve()), '-']


def _connection_diagnostic(event: dict) -> dict | None:
    """只识别CLI明确的重连/同provider传输恢复提示；普通error不得忽略。"""
    kind=event.get('type');item=event.get('item') or {}
    message=event.get('message') if kind=='error' else item.get('message') if isinstance(item,dict) and item.get('type')=='error' else None
    if not isinstance(message,str):return None
    reconnect=re.fullmatch(r'Reconnecting\.\.\.\s+(\d+)/(\d+)\s+\(stream disconnected before completion: .+\)',message)
    if reconnect and 0<int(reconnect[1])<=int(reconnect[2]):
        return {'kind':'stream_reconnecting','attempt_label':int(reconnect[1]),'attempt_limit_label':int(reconnect[2]),'message':message}
    if message.startswith('Falling back from WebSockets to HTTPS transport. stream disconnected before completion: '):
        return {'kind':'websocket_to_https','message':message}
    return None


def parse_events(text: str) -> dict[str, Any]:
    """只有后续单个完整无工具turn才可恢复连接诊断；已知turn用量不冒充全部重连用量。"""
    events, invalid_lines, tools, completed, failures, messages = [], [], [], [], [], []
    diagnostics, completed_lines = [], []
    actual_models, providers = set(), set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip(): continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict): raise ValueError('event is not an object')
        except ValueError:
            invalid_lines.append(number);continue
        events.append(event);kind = str(event.get('type', ''))
        item = event.get('item') or {}
        if not isinstance(item, dict): item = {}
        diagnostic=_connection_diagnostic(event)
        # item:error是诊断/错误，不是工具；未知错误仍阻断，不能被宽泛白名单放过。
        item_error=kind.startswith('item.') and item.get('type')=='error'
        if kind.startswith('item.') and item.get('type') not in SAFE_ITEM_TYPES and not item_error:
            tools.append({'event_type': kind, 'item_type': item.get('type'), 'item_id': item.get('id')})
        elif any(word in kind for word in ('tool', 'command', 'web_search', 'file_change', 'mcp', 'collab')):
            tools.append({'event_type': kind, 'item_type': item.get('type'), 'item_id': item.get('id')})
        if item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
            messages.append(item['text'])
        if kind == 'turn.completed':
            completed.append(event);completed_lines.append(number)
        if diagnostic is not None:
            diagnostics.append({**diagnostic,'line_number':number,'event':event})
        elif kind in ('turn.failed', 'error') or item_error:
            failures.append(event)
        for obj in (event, event.get('response', {})):
            if not isinstance(obj, dict): continue
            model = obj.get('model_name') or obj.get('model')
            provider = obj.get('model_provider') or obj.get('provider')
            if isinstance(model, str): actual_models.add(model)
            if isinstance(provider, str): providers.add(provider)
    starts=sum(e.get('type')=='turn.started' for e in events)
    recovered=(bool(diagnostics) and len(completed)==1 and starts==1 and not tools and not failures and not invalid_lines
               and all(d['line_number']<completed_lines[0] for d in diagnostics))
    if diagnostics and not recovered:
        failures.extend(d['event'] for d in diagnostics)
    for d in diagnostics:d['recovered_by_completed_turn']=recovered
    usages = [item.get('usage', {}) for item in completed]
    turn_usage_complete = len(usages) == 1 and all(type(usages[0].get(key)) is int and usages[0][key] >= 0 for key in ('input_tokens', 'cached_input_tokens', 'output_tokens'))
    usage = {'input_tokens': sum(u.get('input_tokens', 0) or 0 for u in usages),
             'cached_input_tokens': sum(u.get('cached_input_tokens', 0) or 0 for u in usages),
             'output_tokens': sum(u.get('output_tokens', 0) or 0 for u in usages),
             'usage_complete': turn_usage_complete and not diagnostics, 'turn_usage_complete':turn_usage_complete,
             'llm_request_count': len(completed), 'request_count_is_completed_turn_count':True,
             'requests_with_usage': int(turn_usage_complete), 'source': 'codex_cli_turn.completed',
             'cached_tokens_included_in_input': True, 'usage_is_billing_statement': False,
             'additional_network_attempt_usage_known':False if diagnostics else None,
             'usage_gap_reason':'additional_network_attempt_usage_not_exposed' if diagnostics else None}
    usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
    return {'usage': usage, 'tool_event_count': len(tools), 'tool_events': tools,
            'completed_turn_count': len(completed), 'started_turn_count': starts,
            'invalid_jsonl_line_numbers': invalid_lines, 'failure_events': failures,
            'transport_diagnostics':diagnostics,'transport_diagnostics_recovered':recovered,
            'observed_reconnect_diagnostic_count':sum(d['kind']=='stream_reconnecting' for d in diagnostics),
            'websocket_to_https_observed':any(d['kind']=='websocket_to_https' for d in diagnostics),
            'actual_http_request_count':None,'cli_internal_http_retry_count':None,
            'actual_model': next(iter(actual_models)) if len(actual_models) == 1 else None,
            'actual_provider': next(iter(providers)) if len(providers) == 1 else None,
            'reported_models': sorted(actual_models), 'last_agent_message': messages[-1] if messages else None}


def run_codex_cli(folder: Path, system: str, payload: dict, images: list[dict], *,
                  model: str = MODEL, effort: str = 'low', timeout: float = 600) -> dict:
    """只启动一次无工具CLI推理；失败输出原样保留，不调用工程模型工厂。"""
    folder = Path(folder).resolve();folder.mkdir(parents=True, exist_ok=True)
    environment = isolated_environment()
    auth = verify_chatgpt_auth(environment)
    for image in images:
        if hashlib.sha256(Path(image['path']).read_bytes()).hexdigest() != image['sha256']:
            raise CodexTransportError('Actual image bytes changed before CLI attachment')
    prompt = build_stdin(system, payload, images)
    (folder / 'codex.stdin.txt').write_text(prompt, encoding='utf-8')
    argv = build_argv(folder, images, model=model, effort=effort)
    metadata = {'transport': TRANSPORT, 'framework': 'Codex CLI', **auth, 'argv': argv,
                'requested_model': model, 'requested_reasoning_effort': effort,
                'actual_model': None, 'actual_provider': None, 'automatic_retries': False,
                'maximum_inference_turns': 1, 'tool_event_count': 0,
                'automatic_retries_scope': 'host does not restart or retry CLI task',
                'actual_http_request_count': None, 'cli_internal_http_retry_count': None}
    with tempfile.TemporaryDirectory(prefix='prism-codex-visual-', dir='/tmp') as cwd:
        metadata['working_directory'] = cwd
        version = subprocess.run(['codex', '--version'], cwd=cwd, env=environment, capture_output=True, text=True, timeout=15, check=False)
        metadata['cli_version'] = version.stdout.strip()
        if version.returncode:
            raise CodexTransportError('Unable to inspect Codex CLI version', metadata=metadata)
        (folder / 'codex-invocation.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        failure = None
        with (folder / 'events.jsonl').open('w', encoding='utf-8') as output, (folder / 'stderr.txt').open('w', encoding='utf-8') as error:
            try:
                result = subprocess.run(argv, input=prompt, text=True, cwd=cwd, env=environment,
                                        stdout=output, stderr=error, timeout=timeout, check=False)
                metadata['exit_code'] = result.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                metadata['exit_code'] = None
                failure = 'Codex CLI timed out without retry' if isinstance(exc, subprocess.TimeoutExpired) else 'Codex CLI could not launch; no fallback'
    parsed = parse_events((folder / 'events.jsonl').read_text(encoding='utf-8'))
    metadata.update({key: value for key, value in parsed.items() if key not in ('usage', 'last_agent_message')})
    (folder / 'codex-events-summary.json').write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw_path = folder / 'answer.raw.txt'
    if not raw_path.exists() and parsed['last_agent_message'] is not None:
        raw_path.write_text(parsed['last_agent_message'], encoding='utf-8')
        metadata['raw_answer_source'] = 'actual_last_agent_message_event'
    else:
        metadata['raw_answer_source'] = 'codex_output_last_message_file'
    if failure or metadata['exit_code'] != 0:
        raise CodexTransportError(failure or 'Codex CLI returned nonzero exit status; see stderr/events', metadata=metadata, usage=parsed['usage'])
    if parsed['tool_event_count'] or parsed['invalid_jsonl_line_numbers'] or parsed['failure_events'] or parsed['completed_turn_count'] != 1 or parsed['started_turn_count'] != 1:
        raise CodexTransportError('Codex event contract rejected: exactly one completed tool-free turn required', metadata=metadata, usage=parsed['usage'])
    if not raw_path.exists():
        raise CodexTransportError('Codex CLI did not return an actual final message', metadata=metadata, usage=parsed['usage'])
    return {'raw': raw_path.read_text(encoding='utf-8'), 'metadata': metadata, 'usage': parsed['usage']}
