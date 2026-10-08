"""离线修复保留证据、未知和冲突；无模型请求。"""
from copy import deepcopy
import json
from unittest import TestCase

from app.services.dna.prism_r5 import _portable
from app.services.dna.r5_primary_repair import recover_primary, original_paths, parse_primary


class R5PrimaryRepairTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portable, cls.engine = _portable()

    def sample(self):
        return {'areas': [{'name': '椅子座面', 'base': {'COL-006': '米白色', 'OPT-001': '织物外观',
                'OPT-002': '哑光', 'OPT-007': '不透明'}, 'texture': {'state': 'none'}, 'more': []}],
                'overall': [{'at': '椅子边缘', 'dna': {'p': 'REL-014', 'v': '接触'}}], 'uncertain': []}

    def repair(self, answer):
        return recover_primary(json.dumps(answer, ensure_ascii=False), self.portable, self.engine)

    def test_missing_nullable_fields_do_not_lose_valid_texture(self):
        answer = self.sample()
        answer['areas'][0]['texture'] = {'state': 'visible', 'dna': {'TEX-001': '真实起伏', 'TEX-002': '线'}}
        result = self.repair(answer)
        dna = result['answer']['areas'][0]['texture']['dna']
        self.assertEqual(dna['TEX-001'], '真实起伏')
        self.assertIsNone(dna['TEX-018'])
        self.assertEqual(set(dna), set(self.engine.TEX))

    def test_bad_enum_never_guessed_or_wrapped_as_custom(self):
        answer = self.sample(); answer['areas'][0]['base']['OPT-001'] = '其他'
        answer['overall'][0]['dna']['v'] = '层叠'
        result = self.repair(answer)
        self.assertIsNone(result['answer']['areas'][0]['base']['OPT-001'])
        self.assertEqual(result['answer']['overall'], [])
        self.assertEqual(len(result['quarantined']), 2)
        self.assertEqual(result['answer']['areas'][0]['base']['COL-006'], '米白色')

    def test_misrouted_core_does_not_enter_overall_and_paths_point_to_original(self):
        answer = self.sample()
        answer['overall'].insert(0, {'at': '椅子座面', 'dna': {'p': 'COL-006', 'v': '米白色'}})
        result = self.repair(answer)
        unpacked = self.portable.primary(self.engine, result['answer'], 'example')
        mapped = original_paths(unpacked, result['source_paths'])
        fact = next(f for f in mapped['direct'] if f['p'] == 'REL-014')
        self.assertEqual(fact['path'], '/overall/1')
        self.assertEqual(fact['projection_path'], '/overall/0')

    def test_duplicate_conflict_never_uses_last_value(self):
        answer = json.dumps(self.sample(), ensure_ascii=False).replace('"OPT-002": "哑光"', '"OPT-002": "哑光", "OPT-002": "高光"')
        result = recover_primary(answer, self.portable, self.engine)
        self.assertIsNone(result['answer']['areas'][0]['base']['OPT-002'])
        self.assertTrue(any(r['kind'] == 'duplicate_key_conflict' for r in result['quarantined']))

    def test_only_structural_texture_move_is_allowed_and_conflicts_are_unknown(self):
        answer = self.sample()
        answer['areas'][0]['texture'] = {'state': 'visible', 'dna': {}, 'TEX-018': '全域'}
        result = self.repair(answer)
        self.assertEqual(result['answer']['areas'][0]['texture']['dna']['TEX-018'], '全域')
        answer['areas'][0]['texture']['dna']['TEX-018'] = '局部'
        self.assertIsNone(self.repair(answer)['answer']['areas'][0]['texture']['dna']['TEX-018'])

    def test_hard_features_stay_pending_without_new_review(self):
        answer = self.sample()
        answer['overall'] = [{'at': '椅子连接部', 'dna': {'p': 'STR-004', 'v': '卡接'}}]
        result = self.repair(answer)
        unpacked = self.portable.primary(self.engine, result['answer'], 'example')
        final = self.portable.finish(self.engine, unpacked, None, 'example')
        self.assertFalse(any(f['p'] == 'STR-004' for f in final['local_features']))
        self.assertTrue(any(row['issue']['fact']['p'] == 'STR-004' for row in final['pending'] if 'issue' in row))

    def test_missing_location_is_not_invented(self):
        answer = self.sample(); answer['areas'][0].pop('name')
        with self.assertRaisesRegex(ValueError, '没有可保留的合法位置'):
            self.repair(answer)

    def test_removed_conflicting_candidate_blocks_same_location_valid_candidate(self):
        answer = self.sample()
        answer['areas'][0]['texture'] = {'state': 'visible', 'dna': {'TEX-011': '平移重复'}}
        answer['areas'][0]['more'] = [{'p': 'TEX-011', 'v': '旋转重复'}]
        result = self.repair(answer)
        self.assertIn({'at': '椅子座面', 'p': 'TEX-011'}, result['blocked_fields'])

    def test_numeric_overflow_is_not_accepted_as_finite_json(self):
        with self.assertRaisesRegex(ValueError, '非有限JSON数值'):
            parse_primary('{"value":1e999}')
