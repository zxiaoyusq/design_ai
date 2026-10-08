"""极小本地fixture验证排序证据边界；不创建模型或访问供应商。"""
from copy import deepcopy
import unittest
from app.services.visual_workflow.candidate_prioritization import candidate_profile, matched_facts, prioritize_candidates, relation_value

FAMILY = {'direction_id': 'H012', 'branch': 'CMF', 'primary_questions': ['反射', '连续表面', '纹理从属']}


def candidate(cid, state='candidate', source=None):
    return {'candidate_id': cid, 'image_sha256': cid, 'source_group_ids': [source or cid],
        'semantic_match': {'state': state, 'relation_strength': 'strong', 'family_relation': 'frozen_family', 'observation_indices': [2, 3, 5]},
        'matched_locations': [{'at': 'surface', 'features': [
            {'p': 'OPT-001', 'v': '哑光', 'original_local_feature_index': 2, 'at': 'surface'},
            {'p': 'OPT-002', 'v': '漫反射', 'original_local_feature_index': 3, 'at': 'surface'},
            {'p': 'TEX-001', 'v': '均匀', 'original_local_feature_index': 5, 'at': 'surface'},
            {'p': 'COL-001', 'v': '红色', 'original_local_feature_index': 9, 'at': 'surface'}]}]}


class CandidatePriorityTests(unittest.TestCase):
    def test_only_matched_known_indices_can_rank(self):
        c = candidate('a');c['pending'] = [{'fact': {'p': 'OPT-001', 'at': 'surface'}}]
        c['matched_locations'][0]['features'][1]['v'] = 'unknown'
        usable, excluded = matched_facts(c)
        self.assertEqual([f['index'] for f in usable], [5])
        self.assertEqual({f['index'] for f in excluded}, {2,3})

    def test_different_locations_never_form_one_relation(self):
        c = candidate('a');c['matched_locations'][0]['features'][1]['at'] = 'other'
        p = candidate_profile(FAMILY,c)
        self.assertEqual(len(p['relation_variants']), 2)
        for relation in p['relation_variants']:
            self.assertFalse({2,3} <= set(relation['observation_indices']))
        self.assertFalse(any(q['visual_condition_verified'] for q in p['primary_evidence_hints']))

    def test_cmf_cross_location_facts_do_not_complete_anchor_coverage(self):
        c=candidate('a');c['matched_locations'][0]['features']=[
            {'p':'TEX-001','v':'线','at':'surfaceA','original_local_feature_index':2},
            {'p':'TEX-002','v':'有序','at':'surfaceA','original_local_feature_index':3},
            {'p':'REL-015','v':'辅助','at':'surfaceB','original_local_feature_index':5}]
        family={'direction_id':'H002','branch':'CMF','primary_questions':['线','窄带关系','有序']}
        p=candidate_profile(family,c)
        self.assertEqual(p['anchor_at'],'surfaceA')
        self.assertLess(p['score_components'][1],3)
        self.assertNotIn(5,[index for row in p['primary_evidence_hints'] for index in row['observation_indices']])
        self.assertIn(5,p['usable_observation_indices'])

    def test_compound_and_negative_values_stay_original(self):
        for value in ['不规则', '哑光与高光', '有序、无序混合', '线性平行', '规则但局部不均匀']:
            self.assertEqual(relation_value({'p':'OPT-001','v':value}),value)
        self.assertEqual(relation_value({'p':'OPT-001','v':'低光泽哑光'}),'low_reflection')

    def test_candidate_before_uncertain_and_sha_dedup_preserves_variants(self):
        a,b,c,d = candidate('a'),candidate('b',source='a'),candidate('c','uncertain'),candidate('d')
        d['image_sha256'] = 'a'
        plan = prioritize_candidates(FAMILY,[d,c,b,a])
        self.assertEqual(plan['ordered_candidate_ids'][-1],'c')
        self.assertEqual(len(plan['ordered_candidate_ids']),3)
        self.assertEqual(len(plan['duplicate_images']),1)
        self.assertEqual(plan,prioritize_candidates(FAMILY,[b,a,c,d]))
        self.assertFalse(plan['visual_pass_claimed'])

    def test_quality_requires_actual_same_image_scope_and_never_passes(self):
        c=candidate('a');q={'provenance_verified': True,'image_sha256':'a','target_observation_indices':[2,3,5], 'quality':{'design_reference':True,'veto':'none','signal_level':'clear'}}
        p=candidate_profile(FAMILY,c,q)
        self.assertTrue(p['quality_provenance_used']);self.assertFalse(p['visual_pass_claimed'])
        for change in [{'image_sha256':'else'},{'target_observation_indices':[2]}, {'provenance_verified':False}]:
            self.assertFalse(candidate_profile(FAMILY,c,{**q,**change})['quality_provenance_used'])

    def test_relation_level_clusters_keep_original_value_subgroups(self):
        a,b=candidate('a'),candidate('b')
        b['matched_locations'][0]['features'][0]['v']='低光泽'
        b['matched_locations'][0]['features'][2]['v']='致密细颗粒'
        # 同低反射关系可进入粗簇；原纹理变体不能消失。
        a['matched_locations'][0]['features'][2]['v']='浅细颗粒'
        plan=prioritize_candidates(FAMILY,[a,b])
        self.assertEqual(len(plan['clusters']),1)
        self.assertEqual(len(plan['clusters'][0]['variant_subgroups']),2)
        self.assertEqual(plan['cluster_statistics']['maximum_size'],2)


if __name__ == '__main__': unittest.main()
