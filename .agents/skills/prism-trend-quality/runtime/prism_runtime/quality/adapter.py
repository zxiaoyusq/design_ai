"""Preserve saved verdicts; reject ineligible sources before reading results.

This adapter never imports provider code, credentials, image processing, or DNA.
It does not rerun old model features through a newer rubric.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROUTE_SCHEMA = 'prism.quality_route.v0.1'
DECISION_SCHEMA = 'prism.trend_quality.v0.1'


def _base(image):
    image = image if isinstance(image, dict) else {}
    return {
        'schema_version': ROUTE_SCHEMA, 'image_id': image.get('image_id'),
        'source_kind': image.get('source_kind', 'unknown'),
        'applicable': image.get('source_kind') == 'trend',
        'decision': None, 'status': 'not_applicable',
        'new_paid_calls': 0, 'production_admission': False,
    }


def _eligible(image, calibration_only):
    kind = image.get('source_kind', 'unknown')
    return kind == 'trend' or (kind == 'calibration' and calibration_only)


def _route_stop(image, calibration_only):
    if not isinstance(image, dict):
        result = _base({})
        result.update(status='invalid_input', error='image_metadata_not_object')
        return result
    if not _eligible(image, calibration_only):
        result = _base(image)
        result['reason'] = 'Only provenance-declared trend images enter the production quality route.'
        return result
    if not isinstance(image.get('image_id'), str) or not image['image_id'].strip():
        result = _base(image)
        result.update(status='invalid_input', error='missing_image_identity')
        return result
    if 'provenance' in image and not isinstance(image['provenance'], dict):
        return _error(image, 'invalid_image_provenance', status='invalid_input')
    return None


def _error(image, error, *, status='invalid_output', source_ref=None, original_decision=None):
    result = _base(image)
    result.update(status=status, error=error, original_decision=original_decision,
                  evidence_refs=[source_ref] if source_ref else [])
    return result


def _stored_parts(record):
    if isinstance(record.get('validation'), dict):
        valid = record['validation'].get('valid') is True
        errors = record['validation'].get('errors', [])
    else:
        valid = record.get('valid') is True
        errors = record.get('validation_errors', [])
    output = record.get('output') if isinstance(record.get('output'), dict) else {}
    features = record.get('model_features') if isinstance(record.get('model_features'), dict) else {}
    decision = record.get('decision', output.get('decision'))
    if isinstance(record.get('validation'), dict):
        checked_decision = record['validation'].get('decision', decision)
        if checked_decision != decision:
            valid = False
            errors = list(errors) + ['stored_decision_inconsistent']
    reason, reason_source = '', 'unavailable'
    for value, name in [(record.get('display_reason'), 'stored_display_reason'),
                        (record.get('reason'), 'stored_reason'),
                        (features.get('reason'), 'model_summary'),
                        (output.get('reason'), 'model_summary')]:
        if isinstance(value, str) and value.strip():
            reason, reason_source = value, name
            break
    if not reason:
        evidence = features.get('evidence') or []
        if evidence and isinstance(evidence[0], dict):
            text = evidence[0].get('observation')
            if isinstance(text, str):
                reason, reason_source = text, 'first_model_evidence'
    raw_evidence = deepcopy(features.get('evidence', {
        'positive_evidence': output.get('positive_evidence', []),
        'negative_evidence': output.get('negative_evidence', []),
    }))
    return valid, errors, decision, reason, reason_source, raw_evidence


def export_existing_result(image, record, *, source_ref, rubric_version=None,
                           calibration_only=False, provenance_mode='existing_model_output'):
    """Export an existing verdict without recomputing it under newer rules.

    `image` may be an ImageDNA record or its image_id/source_kind/provenance subset.
    Source kind must come from upstream provenance, never from image appearance.
    Calibration opt-in exports a non-production route record, not a Trend decision.
    """
    stopped = _route_stop(image, calibration_only)
    if stopped is not None:
        return stopped
    if not isinstance(record, dict):
        return _error(image, 'result_not_object', source_ref=source_ref)
    if 'provenance' in record and not isinstance(record['provenance'], dict):
        return _error(image, 'invalid_result_provenance', source_ref=source_ref)
    if not isinstance(source_ref, str) or not source_ref.strip():
        return _error(image, 'missing_source_reference')
    if record.get('image_id') != image['image_id']:
        return _error(image, 'image_identity_mismatch', source_ref=source_ref)
    if record.get('source_kind') not in (None, image['source_kind']):
        return _error(image, 'source_kind_mismatch', source_ref=source_ref)
    if provenance_mode not in {'existing_model_output', 'synthetic'}:
        return _error(image, 'invalid_provenance_mode', source_ref=source_ref)
    valid, errors, decision, reason, reason_source, raw_evidence = _stored_parts(record)
    common = {'source_ref': source_ref, 'original_decision': decision}
    if record.get('http_status', 200) != 200 or record.get('status') == 'execution_error' or record.get('ok') is False:
        return _error(image, 'saved_execution_failure', status='execution_error', **common)
    if record.get('status') in {'needs_confirmation', 'incomplete'}:
        return _error(image, 'saved_confirmation_pending', status='needs_confirmation', **common)
    if record.get('status') == 'needs_review':
        result = _error(image, 'saved_human_review_pending', status='needs_review', **common)
        result['model_features'] = deepcopy(record.get('model_features'))
        result['source_results'] = deepcopy(record.get('source_results'))
        result['rubric_version'] = record.get('version') or record.get('rubric_version')
        result['reference_readiness'] = record.get('reference_readiness')
        return result
    if (not valid or errors or not isinstance(decision, str) or decision not in {'PASS', 'FAIL'}
            or record.get('status') in {'invalid_output', 'invalid_input'}):
        result = _error(image, 'saved_result_invalid', **common)
        result['validation_errors'] = deepcopy(errors)
        return result
    stored_version = record.get('version') or record.get('rubric_version')
    if rubric_version and stored_version and rubric_version != stored_version:
        return _error(image, 'rubric_version_conflict', **common)
    version = stored_version or rubric_version
    if not isinstance(version, str) or not version.strip():
        return _error(image, 'missing_original_rubric_version', **common)
    if not reason:
        # v0.8 只请求判定单词，缺少解释是契约本意；旧回执仍必须保留原理由。
        from . import compact
        checked = compact.evaluate(record.get('raw_response'))
        if (version != compact.VERSION or checked['status'] != 'complete'
                or checked['decision'] != decision):
            return _error(image, 'missing_original_reason', **common)
        reason_source = 'not_requested'
    synthetic = (provenance_mode == 'synthetic'
                 or image.get('provenance', {}).get('mode') == 'synthetic'
                 or record.get('provenance', {}).get('mode') == 'synthetic')
    # 历史结论可导出，正式准入还需上游明确核实来源，缺省不表示已核实。
    provenance = image.get('provenance', {})
    provenance_verified = (provenance.get('verified') is True
                           and isinstance(provenance.get('source_ref'), str)
                           and bool(provenance['source_ref'].strip())
                           and provenance.get('source_kind', image['source_kind']) == image['source_kind'])
    result = _base(image)
    result.update({
        'schema_version': DECISION_SCHEMA if image['source_kind'] == 'trend' else ROUTE_SCHEMA,
        'status': 'complete', 'decision': decision, 'reason': reason,
        'reason_source': reason_source, 'evidence_refs': [source_ref],
        'source_ref': source_ref, 'rubric_version': version,
        'raw_evidence': raw_evidence,
        'provenance': {'mode': 'synthetic' if synthetic else provenance_mode,
                       'decision_preserved': True, 'recomputed': False,
                       'source_verified': provenance_verified,
                       'input_provenance': deepcopy(provenance)},
        'calibration_only': image['source_kind'] == 'calibration',
        'production_admission': (image['source_kind'] == 'trend' and decision == 'PASS'
                                 and not synthetic and provenance_verified
                                 and record.get('production_admission', True) is True),
    })
    for field in ['selected_stage', 'primary_version', 'primary_decision',
                  'primary_validation', 'confirmation_version', 'confirmation_reason',
                  'source_results', 'reference_readiness']:
        if field in record:
            result[field] = deepcopy(record[field])
    return result


def adapt_file(image, result_path, *, rubric_version=None, calibration_only=False,
               provenance_mode='existing_model_output'):
    """Ineligible sources do not even open result_path."""
    stopped = _route_stop(image, calibration_only)
    if stopped is not None:
        return stopped
    path = Path(result_path).resolve()
    try:
        raw = path.read_bytes()
        record = json.loads(raw.decode('utf-8-sig'))
    except OSError:
        return _error(image, 'result_file_unavailable', status='execution_error', source_ref=str(path))
    except (ValueError, UnicodeError):
        return _error(image, 'result_json_invalid', source_ref=str(path))
    result = export_existing_result(image, record, source_ref=str(path), rubric_version=rubric_version,
                                    calibration_only=calibration_only, provenance_mode=provenance_mode)
    result['source_sha256'] = hashlib.sha256(raw).hexdigest()
    return result


def route_quality(image, result_loader, *, source_ref, **kwargs):
    """Lazy offline loader for integrations; forbidden sources never invoke it."""
    stopped = _route_stop(image, kwargs.get('calibration_only', False))
    if stopped is not None:
        return stopped
    try:
        record = result_loader()
    except Exception:
        return _error(image, 'result_loader_failed', status='execution_error', source_ref=source_ref)
    return export_existing_result(image, record, source_ref=source_ref, **kwargs)
