"""新版判标的微型离线回归；不进行图像推理或网络请求。"""

from copy import deepcopy
from hashlib import sha256
import json
import unittest

from . import curation
from .adapter import export_existing_result, route_quality
from .policy import aggregate_children, resolve as resolve_legacy
from .test_quality import saved


def features(readiness='ready'):
    """合成结构夹具，不冒充真实图片的视觉判断。"""
    return {
        'image_type': 'whole_object', 'design_reference': True,
        'signal_level': 'distinct', 'reference_readiness': readiness,
        'image_quality': 'sufficient', 'veto': 'none',
        'evidence': [{'region': 'center', 'feature': 'form',
                      'observation': '合成夹具：宽面向细颈过渡，弯折与反射边线清楚。'}],
        'limits': ['局部遮挡，无法确定关系是否充分。'] if readiness == 'uncertain' else [],
        'reason': '用于离线检查参考就绪度门槛的合成描述。',
    }


def record(value=None, *, confirmation=False):
    return {
        'image_id': 'fixture',
        'version': curation.CONFIRMATION_VERSION if confirmation else curation.PRIMARY_VERSION,
        'image_sha256': 'a' * 64, 'input_image_sha256': 'b' * 64,
        'prompt_sha256': sha256(curation.PROMPT_PATH.read_bytes()).hexdigest(),
        'model': 'offline-fixture', 'parameters': {},
        'started_at': '2026-10-02T00:00:00Z', 'finished_at': '2026-10-02T00:00:01Z',
        'http_status': 200, 'model_features': features() if value is None else value,
        'raw_response': 'synthetic fixture', 'provenance': {'mode': 'synthetic'},
    }


class CurationTests(unittest.TestCase):
    def test_clear_signal_alone_does_not_override_weak_reference(self):
        result = curation.resolve(record(features('weak')))
        self.assertEqual(result['decision'], 'FAIL')
        self.assertIsNone(result['confirmation_reason'])
        self.assertEqual(result['status'], 'complete')

    def test_ready_limited_image_passes_without_extra_review(self):
        value = features(); value['image_quality'] = 'limited'
        result = curation.resolve(record(value))
        self.assertEqual(result['decision'], 'PASS')
        self.assertFalse(result['production_admission'])
        self.assertIsNone(result['confirmation_reason'])

    def test_uncertainty_is_pending_and_prevents_board_pass(self):
        result = curation.resolve(record(features('uncertain')))
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['decision'])
        self.assertIsNone(curation.confirmation_reason(record(features('uncertain'))))
        self.assertEqual(aggregate_children([result])['status'], 'incomplete')

    def test_malformed_enum_values_never_crash(self):
        for field in ('image_type', 'signal_level', 'reference_readiness', 'image_quality', 'veto'):
            for malformed in ([], {}, None, 1, True):
                with self.subTest(field=field, value=malformed):
                    value = features(); value[field] = malformed
                    self.assertFalse(curation.evaluate(value)['valid'])
        for field in ('feature', 'region'):
            for malformed in ([], {}, None, 'invented'):
                with self.subTest(field=field, value=malformed):
                    value = features(); value['evidence'][0][field] = malformed
                    self.assertFalse(curation.evaluate(value)['valid'])

    def test_missing_or_contradictory_support_stays_invalid(self):
        cases = [('evidence', []), ('design_reference', False), ('signal_level', 'basic'),
                 ('veto', 'unreadable'), ('reason', '')]
        for field, changed in cases:
            with self.subTest(field=field):
                value = features(); value[field] = changed
                result = curation.evaluate(value)
                self.assertFalse(result['valid'])
                self.assertIsNone(result['decision'])
        value = features('uncertain'); value['limits'] = []
        self.assertFalse(curation.evaluate(value)['valid'])

    def test_format_repair_is_bounded_and_keeps_raw_history(self):
        primary = record([])
        self.assertEqual(curation.resolve(primary)['status'], 'needs_confirmation')
        confirmation = record(confirmation=True)
        before = deepcopy((primary, confirmation))
        result = curation.resolve(primary, confirmation)
        self.assertEqual(result['decision'], 'PASS')
        self.assertEqual(result['source_results']['primary'], primary)
        self.assertEqual(result['source_results']['confirmation'], confirmation)
        self.assertEqual((primary, confirmation), before)
        invalid = curation.resolve(primary, record([], confirmation=True))
        self.assertEqual(invalid['status'], 'invalid_output')
        self.assertIsNone(invalid['decision'])
        self.assertIsNone(curation.confirmation_reason(record([], confirmation=True)))

    def test_transport_and_metadata_errors_do_not_request_repair(self):
        for status in (None, 401, 429, 500):
            primary = record([]); primary['http_status'] = status
            self.assertEqual(curation.resolve(primary)['status'], 'execution_error')
            self.assertIsNone(curation.confirmation_reason(primary))
        for field, changed in [('image_id', ''), ('image_sha256', ''),
                               ('input_image_sha256', None), ('prompt_sha256', 'c' * 64),
                               ('model', ''), ('parameters', [])]:
            with self.subTest(field=field):
                primary = record([]); primary[field] = changed
                self.assertEqual(curation.resolve(primary)['status'], 'invalid_output')
                self.assertIsNone(curation.confirmation_reason(primary))
        for bad in ([], None, 'record'):
            self.assertEqual(curation.resolve(bad)['status'], 'invalid_output')

    def test_confirmation_must_match_actual_image(self):
        for field, changed in [('image_id', 'other'), ('image_sha256', 'c' * 64),
                               ('input_image_sha256', 'c' * 64)]:
            with self.subTest(field=field):
                confirmation = record(confirmation=True); confirmation[field] = changed
                result = curation.resolve(record([]), confirmation)
                self.assertEqual(result['error'], 'confirmation_' + field + '_mismatch')
                self.assertIsNone(result['decision'])

    def test_no_unsolicited_confirmation_for_valid_fail_or_pass(self):
        for readiness in ('ready', 'weak', 'uncertain'):
            result = curation.resolve(record(features(readiness)), record(confirmation=True))
            self.assertEqual(result['error'], 'unsolicited_confirmation')

    def test_mismatched_saved_decision_is_rejected(self):
        primary = record(); primary['decision'] = 'FAIL'
        self.assertEqual(curation.resolve(primary)['error'], 'stored_decision_mismatch')

    def test_versions_do_not_reinterpret_each_other(self):
        old = saved()
        self.assertEqual(resolve_legacy(old)['decision'], 'PASS')
        self.assertEqual(curation.resolve(old)['error'], 'unsupported_stage_version')
        self.assertEqual(resolve_legacy(record())['error'], 'unsupported_primary_version')

    def test_saved_host_probe_is_replayed_without_vision_calls(self):
        root = curation.PROMPT_PATH.parent.parent
        probe = json.loads((root / 'calibration-probe-20261002.json').read_text())
        calibration = json.loads((root / 'calibration-20261002.json').read_text())
        expected = {item['image_sha256']: item['user_label'] for item in calibration['images']}
        self.assertEqual(probe['prompt_sha256'], sha256(curation.PROMPT_PATH.read_bytes()).hexdigest())
        self.assertEqual(len(probe['results']), 4)
        for item in probe['results']:
            result = curation.evaluate(item['model_features'])
            self.assertTrue(result['valid'], result)
            self.assertEqual(result['decision'], expected[item['image_sha256']])


class ExportBoundaryTests(unittest.TestCase):
    def test_pending_review_remains_pending_on_export(self):
        record_value = curation.resolve(record(features('uncertain')))
        result = export_existing_result({'image_id': 'fixture', 'source_kind': 'trend'},
                                        record_value, source_ref='fixture')
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['decision'])
        self.assertFalse(result['production_admission'])
        self.assertEqual(result['reference_readiness'], 'uncertain')
        self.assertEqual(result['rubric_version'], curation.VERSION)

    def test_new_pass_is_candidate_even_with_verified_source(self):
        result = export_existing_result(
            {'image_id': 'fixture', 'source_kind': 'trend',
             'provenance': {'verified': True, 'source_ref': 'fixture-source'}},
            curation.resolve(record()), source_ref='fixture')
        self.assertEqual(result['decision'], 'PASS')
        self.assertFalse(result['production_admission'])
        self.assertEqual(result['reference_readiness'], 'ready')

    def test_missing_provenance_preserves_verdict_without_admission(self):
        existing = saved(); existing.pop('provenance')
        result = export_existing_result({'image_id': 'x', 'source_kind': 'trend'},
                                        existing, source_ref='fixture')
        self.assertEqual(result['decision'], 'PASS')
        self.assertFalse(result['production_admission'])

    def test_malformed_provenance_is_an_error_before_loader(self):
        def forbidden():
            raise AssertionError('invalid metadata must not invoke loader')
        for provenance in (None, [], 'trend'):
            result = route_quality({'image_id': 'x', 'source_kind': 'trend', 'provenance': provenance},
                                   forbidden, source_ref='fixture')
            self.assertEqual(result['status'], 'invalid_input')
            existing = saved(); existing['provenance'] = provenance
            self.assertEqual(export_existing_result({'image_id': 'x', 'source_kind': 'trend'},
                                                    existing, source_ref='fixture')['status'], 'invalid_output')

    def test_verified_source_cannot_promote_synthetic_calibration(self):
        for kind in ('trend', 'calibration'):
            result = export_existing_result(
                {'image_id': 'x', 'source_kind': kind,
                 'provenance': {'verified': True, 'source_ref': 'fixture-source'}},
                saved(), source_ref='fixture', calibration_only=True)
            self.assertFalse(result['production_admission'])


if __name__ == '__main__':
    unittest.main()
