"""Bounded, score-free review policy. No provider or network dependency."""
from copy import deepcopy

from .signal_gate import evaluate

VERSION = 'cmf-reference-signal-cascade-v0.6.1'
PRIMARY_VERSION = 'cmf-reference-signal-gate-v0.5.2'
CONFIRMATION_VERSION = 'cmf-reference-signal-confirm-v0.6.0'


def confirmation_reason(primary):
    """Return a generic routing reason, never an image/brand/label whitelist."""
    if primary.get('version') != PRIMARY_VERSION:
        return None
    if primary.get('http_status') != 200:
        return None  # Transport/auth/rate-limit failures need explicit resolution.
    features = primary.get('model_features')
    checked = evaluate(features)
    if not checked['valid']:
        return 'invalid_model_output'
    if (checked['decision'] == 'FAIL' and features['design_reference']
            and features['signal_level'] == 'basic'
            and features['image_quality'] != 'unusable'
            and features['veto'] == 'none' and features['evidence']):
        return 'basic_with_visible_evidence'
    return None


def resolve(primary, confirmation=None):
    """Accept at most one independent image-only confirmation; retain history."""
    iid = primary.get('image_id')
    result = {
        'image_id': iid, 'version': VERSION,
        'primary_version': primary.get('version'),
        'primary_decision': primary.get('decision'),
        'primary_validation': deepcopy(primary.get('validation')),
        'confirmation_reason': confirmation_reason(primary),
        'decision': None, 'status': 'invalid_output',
        'model_features': None, 'validation': {'valid': False},
        'network_calls_by_policy': 0, 'maximum_confirmation_attempts': 1,
    }
    if primary.get('version') != PRIMARY_VERSION:
        result['error'] = 'unsupported_primary_version'
        return result
    if primary.get('http_status') != 200:
        result.update(status='execution_error', error='primary_transport_error')
        return result
    needs = result['confirmation_reason']
    chosen = primary
    if needs:
        if confirmation is None:
            result.update(status='needs_confirmation', error='confirmation_not_supplied')
            return result
        if confirmation.get('image_id') != iid:
            result['error'] = 'confirmation_identity_mismatch'
            return result
        if confirmation.get('version') != CONFIRMATION_VERSION:
            result['error'] = 'confirmation_version_mismatch'
            return result
        result['confirmation_version'] = confirmation['version']
        if confirmation.get('http_status') != 200:
            result.update(status='execution_error', error='confirmation_transport_error')
            return result
        chosen = confirmation
    elif confirmation is not None:
        result['error'] = 'unsolicited_confirmation'
        return result
    validation = evaluate(chosen.get('model_features'))
    result.update(validation=validation,
                  model_features=deepcopy(chosen.get('model_features')),
                  selected_stage='confirmation' if needs else 'primary')
    if not validation['valid']:
        result['error'] = 'invalid_model_output'
        return result
    if chosen.get('decision') != validation['decision']:
        result.update(error='stored_decision_mismatch', validation={'valid': False})
        return result
    result.update(status='complete', decision=validation['decision'])
    return result


def aggregate_children(children):
    """Board PASS never overrides a child; technical gaps are not FAIL."""
    if not isinstance(children, list):
        return {'status': 'invalid_output', 'decision': None, 'error': 'children_not_list'}
    if not children:
        return {'status': 'invalid_output', 'decision': None, 'error': 'no_children'}

    # Check identity before gathering verdicts; malformed/duplicate records
    # cannot represent an unambiguous set of independently reviewed children.
    identity_errors = []
    seen_ids = set()
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            identity_errors.append({'index': index, 'error': 'child_not_object'})
            continue
        iid = child.get('image_id')
        if not isinstance(iid, str) or not iid.strip():
            identity_errors.append({'index': index, 'error': 'invalid_image_id'})
        elif iid in seen_ids:
            identity_errors.append({'index': index, 'image_id': iid, 'error': 'duplicate_image_id'})
        else:
            seen_ids.add(iid)
    if identity_errors:
        return {'status': 'invalid_output', 'decision': None,
                'error': 'invalid_child_identity', 'errors': identity_errors}

    unresolved = []
    failures = []
    for child in children:
        decision = child.get('decision')
        # A completion label alone is not evidence of a valid decision. Use
        # a type check so arrays/objects cannot raise during membership tests.
        valid = (child.get('status') == 'complete'
                 and isinstance(decision, str) and decision in {'PASS', 'FAIL'})
        if not valid:
            unresolved.append(child['image_id'])
        elif decision == 'FAIL':
            failures.append(child['image_id'])
    if unresolved:
        return {'status': 'incomplete', 'decision': None,
                'unresolved': unresolved, 'known_failures': failures}
    return {'status': 'complete', 'decision': 'FAIL' if failures else 'PASS',
            'unresolved': [], 'known_failures': failures}
