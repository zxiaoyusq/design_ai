"""v0.7 当前画面的参考就绪度判标；纯离线，不调用模型或改写旧判定。"""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .signal_gate import FEATURES, REGIONS, TYPES, VETOS

VERSION = 'cmf-reference-curation-v0.7.0'
PRIMARY_VERSION = 'cmf-reference-curation-primary-v0.7.0'
CONFIRMATION_VERSION = 'cmf-reference-curation-confirm-v0.7.0'
PROMPT_PATH = Path(__file__).resolve().parents[3] / 'references/prompts/curation-v0.7.0.txt'


def _enum(value, choices):
    # 先校验类型，模型返回数组或对象时仍能返回结构化错误。
    return isinstance(value, str) and value in choices


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _digest(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def evaluate(features):
    """校验新字段并计算结论；uncertain 是有效未决，不能计为 FAIL。"""
    if not isinstance(features, dict):
        return {'valid': False, 'errors': ['not_object'], 'decision': None}
    enums = {
        'image_type': TYPES,
        'signal_level': {'distinct', 'basic', 'none'},
        'reference_readiness': {'ready', 'weak', 'uncertain'},
        'image_quality': {'sufficient', 'limited', 'unusable'},
        'veto': VETOS,
    }
    errors = []
    required = set(enums) | {'design_reference', 'evidence', 'limits', 'reason'}
    if set(features) != required:
        errors.append('wrong_keys')
    for field, choices in enums.items():
        if not _enum(features.get(field), choices):
            errors.append('invalid_' + field)
    if type(features.get('design_reference')) is not bool:
        errors.append('invalid_design_reference')
    evidence = features.get('evidence')
    if not isinstance(evidence, list) or len(evidence) > 2:
        errors.append('invalid_evidence')
    else:
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {'region', 'feature', 'observation'}:
                errors.append('invalid_evidence_shape')
                continue
            if not _enum(item.get('region'), REGIONS):
                errors.append('invalid_region')
            if not _enum(item.get('feature'), FEATURES):
                errors.append('invalid_feature')
            if not _text(item.get('observation')):
                errors.append('empty_observation')
    limits = features.get('limits')
    if not isinstance(limits, list) or len(limits) > 1 or any(not _text(x) for x in limits):
        errors.append('invalid_limits')
    if not _text(features.get('reason')):
        errors.append('missing_reason')
    if features.get('signal_level') == 'distinct' and not evidence:
        errors.append('distinct_without_evidence')
    if features.get('image_quality') == 'unusable' and features.get('veto') == 'none':
        errors.append('unusable_without_veto')
    ready = features.get('reference_readiness') == 'ready'
    sufficient = (features.get('design_reference') is True
                  and features.get('signal_level') == 'distinct'
                  and features.get('image_quality') != 'unusable'
                  and features.get('veto') == 'none' and bool(evidence))
    if ready and not sufficient:
        errors.append('ready_without_support')
    if features.get('reference_readiness') == 'uncertain' and not limits:
        errors.append('uncertainty_without_limit')
    if errors:
        return {'valid': False, 'errors': errors, 'decision': None}
    if features['reference_readiness'] == 'uncertain':
        return {'valid': True, 'errors': [], 'decision': None, 'status': 'needs_review'}
    return {'valid': True, 'errors': [], 'decision': 'PASS' if ready else 'FAIL',
            'status': 'complete'}


def _record_error(record, version):
    """新记录必须能绑定原图、发送图和提示词；元数据错误不消耗补查额度。"""
    if not isinstance(record, dict):
        return 'record_not_object'
    if record.get('version') != version:
        return 'unsupported_stage_version'
    if not _text(record.get('image_id')):
        return 'missing_image_identity'
    for field in ('image_sha256', 'input_image_sha256', 'prompt_sha256'):
        if not _digest(record.get(field)):
            return 'invalid_' + field
    if record['prompt_sha256'] != sha256(PROMPT_PATH.read_bytes()).hexdigest():
        return 'prompt_hash_mismatch'
    for field in ('model', 'started_at', 'finished_at'):
        if not _text(record.get(field)):
            return 'missing_' + field
    if not isinstance(record.get('parameters'), dict):
        return 'missing_parameters'
    return None


def confirmation_reason(primary):
    """仅完整请求得到无效模型结构时可补查一次，明确 FAIL 不再自动翻案。"""
    if _record_error(primary, PRIMARY_VERSION) or primary.get('http_status') != 200:
        return None
    return None if evaluate(primary.get('model_features'))['valid'] else 'invalid_model_output'


def resolve(primary, confirmation=None):
    """组合最多一次独立补查；保存全部原记录，复核后仍异常就停止。"""
    result = {
        'image_id': primary.get('image_id') if isinstance(primary, dict) else None,
        'version': VERSION, 'status': 'invalid_output', 'decision': None,
        'validation': {'valid': False}, 'network_calls_by_policy': 0,
        'maximum_confirmation_attempts': 1, 'production_admission': False,
        'source_results': {'primary': deepcopy(primary)},
    }
    if confirmation is not None:
        result['source_results']['confirmation'] = deepcopy(confirmation)
    error = _record_error(primary, PRIMARY_VERSION)
    if error:
        result['error'] = error
        return result
    if primary.get('http_status') != 200:
        result.update(status='execution_error', error='primary_transport_error')
        return result
    needs = confirmation_reason(primary)
    result['confirmation_reason'] = needs
    chosen = primary
    if needs:
        if confirmation is None:
            result.update(status='needs_confirmation', error='confirmation_not_supplied')
            return result
        error = _record_error(confirmation, CONFIRMATION_VERSION)
        if error:
            result['error'] = error
            return result
        # 同 ID 也可能指向不同内容，首次与补查必须保持实际图像一致。
        for field in ('image_id', 'image_sha256', 'input_image_sha256'):
            if primary[field] != confirmation[field]:
                result['error'] = 'confirmation_' + field + '_mismatch'
                return result
        if confirmation.get('http_status') != 200:
            result.update(status='execution_error', error='confirmation_transport_error')
            return result
        chosen = confirmation
    elif confirmation is not None:
        result['error'] = 'unsolicited_confirmation'
        return result
    validation = evaluate(chosen.get('model_features'))
    result.update(validation=validation, model_features=deepcopy(chosen.get('model_features')),
                  selected_stage='confirmation' if needs else 'primary',
                  primary_version=primary['version'], primary_decision=evaluate(primary.get('model_features'))['decision'])
    if not validation['valid']:
        result['error'] = 'invalid_model_output'
        return result
    if 'decision' in chosen and chosen['decision'] != validation['decision']:
        result.update(error='stored_decision_mismatch', validation={'valid': False})
        return result
    result.update(status=validation['status'], decision=validation['decision'],
                  reference_readiness=chosen['model_features']['reference_readiness'])
    return result
