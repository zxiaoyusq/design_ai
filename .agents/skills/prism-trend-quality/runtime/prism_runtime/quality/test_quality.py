"""Safety/semantic boundary tests; no network and no paid calls."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import Mock

from .adapter import adapt_file, export_existing_result, route_quality
from .policy import (CONFIRMATION_VERSION, PRIMARY_VERSION, aggregate_children,
                     confirmation_reason, resolve)


def saved(decision='PASS'):
    return {'image_id': 'x', 'version': PRIMARY_VERSION, 'http_status': 200,
            'decision': decision, 'validation': {'valid': True, 'errors': [], 'decision': decision},
            'model_features': {'image_type': 'object_detail', 'design_reference': True,
                'signal_level': 'distinct' if decision == 'PASS' else 'basic',
                'image_quality': 'sufficient', 'veto': 'none',
                'evidence': [{'region': 'center', 'feature': 'form',
                              'observation': 'Original synthetic evidence text'}],
                'limits': [], 'reason': 'Original synthetic reason'},
            'provenance': {'mode': 'synthetic'}}


class AdapterTests(unittest.TestCase):
    def test_ineligible_sources_never_call_loader(self):
        for kind in ['research', 'generated', 'unknown', 'synthetic', 'calibration', None]:
            loader = Mock(side_effect=AssertionError('must not read or call'))
            result = route_quality({'image_id': 'x', 'source_kind': kind}, loader, source_ref='fixture')
            loader.assert_not_called()
            self.assertIsNone(result['decision'])
            self.assertFalse(result['applicable'])

    def test_ineligible_sources_do_not_read_missing_file(self):
        result = adapt_file({'image_id': 'x', 'source_kind': 'research'}, 'does-not-exist.json', calibration_only=True)
        self.assertEqual(result['status'], 'not_applicable')

    def test_calibration_opt_in_stays_calibration(self):
        result = export_existing_result({'image_id': 'x', 'source_kind': 'calibration'}, saved(),
                                        source_ref='fixture', calibration_only=True)
        self.assertEqual(result['decision'], 'PASS')
        self.assertEqual(result['source_kind'], 'calibration')
        self.assertFalse(result['applicable'])
        self.assertFalse(result['production_admission'])
        self.assertNotEqual(result['schema_version'], 'prism.trend_quality.v0.1')

    def test_original_pass_and_fail_preserved(self):
        for d in ['PASS', 'FAIL']:
            original = saved(d)
            before = deepcopy(original)
            r = export_existing_result({'image_id': 'x', 'source_kind': 'trend'}, original, source_ref='fixture')
            self.assertEqual(r['decision'], d)
            self.assertEqual(r['reason'], before['model_features']['reason'])
            self.assertEqual(r['raw_evidence'], before['model_features']['evidence'])
            self.assertEqual(original, before)
            self.assertFalse(r['production_admission'])  # Synthetic never publishes.

    def test_http_error_is_never_aesthetic_fail(self):
        bad = saved('FAIL'); bad['http_status'] = 429
        r = export_existing_result({'image_id': 'x', 'source_kind': 'trend'}, bad, source_ref='fixture')
        self.assertEqual(r['status'], 'execution_error')
        self.assertIsNone(r['decision'])
        self.assertEqual(r['original_decision'], 'FAIL')

    def test_invalid_output_is_not_fail(self):
        bad = saved('FAIL'); bad['validation'] = {'valid': False, 'errors': ['not_object']}
        r = export_existing_result({'image_id': 'x', 'source_kind': 'trend'}, bad, source_ref='fixture')
        self.assertEqual(r['status'], 'invalid_output')
        self.assertIsNone(r['decision'])

    def test_legacy_requires_original_version(self):
        old = {'image_id': 'x', 'valid': True, 'validation_errors': [], 'http_status': 200,
               'output': {'decision': 'FAIL', 'reason': 'Exact old wording', 'negative_evidence': ['original']}}
        image = {'image_id': 'x', 'source_kind': 'trend'}
        r = export_existing_result(image, old, source_ref='fixture')
        self.assertEqual(r['error'], 'missing_original_rubric_version')
        r = export_existing_result(image, old, source_ref='fixture', rubric_version='v0.4')
        self.assertEqual(r['decision'], 'FAIL')
        self.assertEqual(r['rubric_version'], 'v0.4')
        self.assertEqual(r['reason'], 'Exact old wording')

    def test_identity_and_provenance_conflicts_are_explicit(self):
        image = {'image_id': 'x', 'source_kind': 'trend'}
        bad = saved(); bad['image_id'] = 'y'
        self.assertEqual(export_existing_result(image, bad, source_ref='fixture')['error'], 'image_identity_mismatch')
        bad = saved(); bad['source_kind'] = 'calibration'
        self.assertEqual(export_existing_result(image, bad, source_ref='fixture')['error'], 'source_kind_mismatch')
        self.assertEqual(export_existing_result(image, saved(), source_ref='fixture', rubric_version='new')['error'], 'rubric_version_conflict')

    def test_conflicting_stored_decision_is_invalid(self):
        bad = saved(); bad['decision'] = 'FAIL'
        r = export_existing_result({'image_id': 'x', 'source_kind': 'trend'}, bad, source_ref='fixture')
        self.assertIsNone(r['decision'])
        self.assertEqual(r['status'], 'invalid_output')

    def test_loader_error_is_not_fail(self):
        r = route_quality({'image_id': 'x', 'source_kind': 'trend'}, Mock(side_effect=OSError), source_ref='fixture')
        self.assertEqual(r['status'], 'execution_error')
        self.assertIsNone(r['decision'])


class PolicyTests(unittest.TestCase):
    def test_pass_keeps_original_without_confirmation(self):
        self.assertIsNone(confirmation_reason(saved()))
        self.assertEqual(resolve(saved())['decision'], 'PASS')

    def test_basic_evidence_gets_one_independent_confirmation(self):
        primary = saved('FAIL')
        self.assertEqual(confirmation_reason(primary), 'basic_with_visible_evidence')
        self.assertEqual(resolve(primary)['status'], 'needs_confirmation')
        confirmation = saved(); confirmation['version'] = CONFIRMATION_VERSION
        r = resolve(primary, confirmation)
        self.assertEqual(r['decision'], 'PASS')
        self.assertEqual(r['primary_decision'], 'FAIL')
        self.assertEqual(r['maximum_confirmation_attempts'], 1)

    def test_empty_array_is_recoverable_once_then_invalid(self):
        primary = saved(); primary.update(model_features=[], decision=None)
        self.assertEqual(confirmation_reason(primary), 'invalid_model_output')
        confirmation = deepcopy(primary); confirmation['version'] = CONFIRMATION_VERSION
        r = resolve(primary, confirmation)
        self.assertEqual(r['status'], 'invalid_output')
        self.assertIsNone(r['decision'])

    def test_transport_error_never_auto_retries(self):
        primary = saved('FAIL'); primary['http_status'] = 429
        self.assertIsNone(confirmation_reason(primary))
        self.assertEqual(resolve(primary)['status'], 'execution_error')

    def test_board_cannot_cover_child_gap_or_failure(self):
        items = [{'image_id': 'a', 'status': 'complete', 'decision': 'PASS'},
                 {'image_id': 'b', 'status': 'invalid_output', 'decision': None}]
        self.assertIsNone(aggregate_children(items)['decision'])
        items[1].update(status='complete', decision='FAIL')
        self.assertEqual(aggregate_children(items)['decision'], 'FAIL')

    def test_original_138_and_new_119_replay(self):
        root = Path(__file__).resolve().parents[2]/'outputs/prism-quality-pilot-20260926'
        old = root/'ee1-cmf-calibration-v052'
        if not old.exists():
            self.skipTest('Existing-output regression data not present in this checkout')
        load = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
        gold = [x for x in load(old/'manifest.json') if x['cohort'] == 'designer_positive']
        self.assertEqual(len(gold), 138)
        for item in gold:
            r = resolve(load(old/'runs'/item['id']/'result.json'))
            self.assertEqual(r['decision'], 'PASS')
        boardroot = root/'designer-boards-round2'
        confirmations = root/'designer-boards-round2-v06/runs'
        records = load(boardroot/'manifest.json')
        self.assertEqual(len(records), 119)
        triggered = []
        for item in records:
            primary = load(boardroot/'runs'/item['id']/'result.json')
            follow = None
            if confirmation_reason(primary):
                triggered.append(item['id'])
                follow = load(confirmations/item['id']/'result.json')
            self.assertEqual(resolve(primary, follow)['decision'], 'PASS')
        self.assertEqual(set(triggered), {'B07-T04','B08-T03','B08-T04','B11-T01'})


class AggregationTests(unittest.TestCase):
    def test_complete_label_requires_legal_decision(self):
        for decision in [None, '', 'pass', 'UNKNOWN', True, 1, [], {}]:
            with self.subTest(decision=decision):
                children = [{'image_id': 'child:1', 'status': 'complete', 'decision': 'PASS'},
                            {'image_id': 'child:2', 'status': 'complete', 'decision': decision}]
                before = deepcopy(children)
                result = aggregate_children(children)
                self.assertEqual(result['status'], 'incomplete')
                self.assertIsNone(result['decision'])
                self.assertEqual(result['unresolved'], ['child:2'])
                self.assertEqual(result['known_failures'], [])
                self.assertEqual(children, before)

    def test_complete_label_with_missing_decision_is_unresolved(self):
        result = aggregate_children([{'image_id': 'child:1', 'status': 'complete'}])
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['decision'])

    def test_known_failure_preserved_alongside_unresolved(self):
        result = aggregate_children([
            {'image_id': 'child:1', 'status': 'complete', 'decision': 'FAIL'},
            {'image_id': 'child:2', 'status': 'complete', 'decision': None},
            {'image_id': 'child:3', 'status': 'execution_error', 'decision': 'FAIL'},
        ])
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['decision'])
        self.assertEqual(result['known_failures'], ['child:1'])
        self.assertEqual(result['unresolved'], ['child:2', 'child:3'])

    def test_valid_pass_and_fail_aggregation(self):
        children = [{'image_id': 'a', 'status': 'complete', 'decision': 'PASS'},
                    {'image_id': 'b', 'status': 'complete', 'decision': 'PASS'}]
        self.assertEqual(aggregate_children(children)['decision'], 'PASS')
        children[1]['decision'] = 'FAIL'
        result = aggregate_children(children)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['decision'], 'FAIL')

    def test_bad_child_shapes_and_ids_never_pass(self):
        for child in [None, [], 'child', {}, {'image_id': None}, {'image_id': ''},
                      {'image_id': ' '}, {'image_id': 1}, {'image_id': []}]:
            with self.subTest(child=child):
                result = aggregate_children([child])
                self.assertEqual(result['status'], 'invalid_output')
                self.assertIsNone(result['decision'])

    def test_duplicate_identity_is_invalid_even_when_both_pass(self):
        children = [{'image_id': 'same', 'status': 'complete', 'decision': 'PASS'},
                    {'image_id': 'same', 'status': 'complete', 'decision': 'PASS'}]
        result = aggregate_children(children)
        self.assertEqual(result['status'], 'invalid_output')
        self.assertIsNone(result['decision'])
        self.assertEqual(result['errors'][0]['error'], 'duplicate_image_id')

    def test_empty_and_non_list_batches_are_invalid(self):
        for children in [[], None, {}, 'children', 1]:
            with self.subTest(children=children):
                result = aggregate_children(children)
                self.assertEqual(result['status'], 'invalid_output')
                self.assertIsNone(result['decision'])


if __name__ == '__main__': unittest.main()
