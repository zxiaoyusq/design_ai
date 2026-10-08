"""逐表面合同的极小离线fixture；不写生产结果、不调用模型。"""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from app.services.visual_workflow.paired_surfaces import POLICY,validate_surface_report,validate_paired_surface_chain,validate_pair_group_scope


def fixture():
    rect={'x':0,'y':0,'width':1,'height':1}
    family={'direction_id':'H007','branch':'CMF','comparison_unit':'surface','scope_limits':['52/56分别','47不支持']}
    target={'candidate_id':'H007-fixture','source_kind':'trend','observation_indices':[0,2], 'quality_output':{'quality':{'evidence_ids':['e1']}}}
    observations=[{'index':i,'usable':True,'original':{'p':'COL-006','v':'蓝','at':at,'source':'P-fixture'}} for i,at in [(0,'包正面'),(2,'上衣正面')]]
    report={'candidate_id':'H007-fixture','comparison_contract':POLICY,'decision':'pass','reason':'fixture actual review', 'same_surface_or_object':False,
      'necessary_relations_visible':True,'necessary_relations_reason':'fixture visible surfaces',
      'surface_bindings':[{'surface_id':sid,'object_label':obj,'object_identity_kind':'visible_label_bound_to_original_location','dna_at':at,'dna_source':'P-fixture','observation_indices':[index],
        'original_rectangle':dict(rect),'original_surface_visible':True,'actual_view_surface_visible':True,'single_surface_binding':True,'original_facts_confirmed':True,'reason':'fixture visible'} for sid,obj,at,index in [('s1','包','包正面',0),('s2','上衣','上衣正面',2)]],
      'evidence_bindings':[{'evidence_id':'e1','surface_ids':['s1','s2'],'visible_on_bound_surfaces':True,'reason':'fixture carriers'}],
      'pair_context':{'observation_indices':[],'relation_bindings':[],'co_present_in_original':True,'co_visible_in_actual_view':True,'no_cross_object_interface_claimed':True,'relation_description':'fixture pair',
        'group_scope_status':'requires_independent_user_context_review','user_acceptance_confirmed':False,
        'scope_limit_handling':[{'index':i,'disposition':'retained_for_group_review','reason':'fixture scope retained'} for i in range(2)]}}
    return report,target,family,observations,rect


class PairedSurfaceTests(unittest.TestCase):
    def test_independently_bound_surfaces_keep_false_without_group_pass(self):
        report,target,family,observations,rect=fixture();before=deepcopy(report)
        result=validate_surface_report(report,target,family,observations,rect)
        self.assertTrue(result['valid'],result);self.assertFalse(result['group_pass_claimed']);self.assertEqual(report,before)

    def test_old_view_without_new_binding_remains_stopped(self):
        report,target,family,observations,rect=fixture();report.pop('comparison_contract');report.pop('surface_bindings')
        result=validate_surface_report(report,target,family,observations,rect)
        self.assertFalse(result['valid']);self.assertIn('new_actual_paired_contract_required',result['errors'])

    def test_unknown_wrong_at_and_cross_object_merge_rejected(self):
        for modification in ('unknown','wrong_at','merged_object','invented_index','same_surface_true'):
            report,target,family,observations,rect=fixture()
            if modification=='unknown':observations[0]['usable']=False
            if modification=='wrong_at':report['surface_bindings'][0]['dna_at']='different surface'
            if modification=='merged_object':report['surface_bindings'][1]['object_label']='包'
            if modification=='invented_index':report['surface_bindings'][0]['observation_indices']=[1]
            if modification=='same_surface_true':report['same_surface_or_object']=True
            with self.subTest(modification=modification):self.assertFalse(validate_surface_report(report,target,family,observations,rect)['valid'])

    def test_surface_not_shown_or_quality_carrier_missing_rejected(self):
        for modification in ('invisible','outside_roi','missing_quality','missing_limit','user_acceptance_granted'):
            report,target,family,observations,rect=fixture()
            if modification=='invisible':report['surface_bindings'][1]['actual_view_surface_visible']=False
            if modification=='outside_roi':rect={'x':0,'y':0,'width':0.5,'height':1}
            if modification=='missing_quality':report['evidence_bindings'][0]['surface_ids']=['s1']
            if modification=='missing_limit':report['pair_context']['scope_limit_handling'].pop()
            if modification=='user_acceptance_granted':report['pair_context']['user_acceptance_confirmed']=True
            with self.subTest(modification=modification):self.assertFalse(validate_surface_report(report,target,family,observations,rect)['valid'])

    def test_chain_never_discards_other_native_gate_errors(self):
        report,target,family,observations,rect=fixture();target.update(image_ref={'id':'image'},actual_view_ref={'id':'view'},dna_ref={'id':'dna'})
        old={'call':{'call_id':'old'},'model_report':{'candidate_id':target['candidate_id'],'same_surface_or_object':False}}
        files={'old':old,'request':{'user_prompt_ref':'payload'},'payload':{'family':family}}
        bridge=SimpleNamespace(checked=lambda ref:files[ref],_call=lambda *a:None,read_dna=lambda *a:{'observations':observations},current_view_rectangle=lambda *a:rect)
        review={'previous_review_ref':'old','call':{'call_id':'new','request_ref':'request'},'model_report':report}
        base=lambda *a:{'errors':['branch_target_not_readable','CMF_same_surface_or_object_not_confirmed','quality_veto_blocks_review']}
        result=validate_paired_surface_chain(target,review,family,bridge=bridge,standard_validator=base)
        self.assertFalse(result['valid']);self.assertIn('quality_veto_blocks_review',result['errors'])
        self.assertEqual(old['model_report']['same_surface_or_object'],False)
        review['call']['call_id']='old'
        self.assertIn('new_independent_paired_review_required',validate_paired_surface_chain(target,review,family,bridge=bridge,standard_validator=base)['errors'])

    def relation_fixture(self, field='REL-014', at='左侧椅子与右侧脚凳', index=71):
        report,target,family,observations,rect=fixture()
        target['observation_indices'].append(index)
        observations.append({'index':index,'usable':True,'original':{'p':field,'v':'分离' if field=='REL-014' else '点缀','at':at,'source':'P-fixture'}})
        report['pair_context']['observation_indices']=[index]
        report['pair_context']['relation_bindings']=[{'observation_index':index,'dna_at':at,'dna_source':'P-fixture','involved_object_labels':['包','上衣'],
            'original_relation_visible':True,'actual_view_relation_visible':True,'reason':'fixture actual cross-object context'}]
        return report,target,family,observations,rect

    def test_real_REL014_and_REL015_locations_bind_separately_from_surfaces(self):
        for field,at,index in [('REL-014','左侧椅子与右侧脚凳',71),('REL-015','左侧人物酒红包和鞋相对于条纹服装',158)]:
            data=self.relation_fixture(field,at,index)
            result=validate_surface_report(*data)
            self.assertTrue(result['valid'],result)
            self.assertFalse(data[0]['same_surface_or_object'])

    def test_duplicate_unknown_wrong_kind_or_single_surface_REL_are_rejected(self):
        for change in ('duplicate','unknown','wrong_kind','single_surface','missing','wrong_object','invisible'):
            report,target,family,observations,rect=self.relation_fixture()
            if change=='duplicate':report['surface_bindings'][0]['observation_indices'].append(71)
            if change=='unknown':observations[-1]['usable']=False
            if change=='wrong_kind':observations[-1]['original']['p']='COL-006'
            if change=='single_surface':
                report['pair_context']['observation_indices']=[];report['pair_context']['relation_bindings']=[]
                report['surface_bindings'].append({**report['surface_bindings'][0],'surface_id':'fake-single-surface','dna_at':observations[-1]['original']['at'],'observation_indices':[71]})
            if change=='missing':report['pair_context']['observation_indices']=[];report['pair_context']['relation_bindings']=[]
            if change=='wrong_object':report['pair_context']['relation_bindings'][0]['involved_object_labels']=['包','invented']
            if change=='invisible':report['pair_context']['relation_bindings'][0]['actual_view_relation_visible']=False
            with self.subTest(change=change):self.assertFalse(validate_surface_report(report,target,family,observations,rect)['valid'])

    def test_group_user_scope_is_not_granted_by_other_user_or_relation_only(self):
        report,target,family,_,_=fixture();family.update(h01_ref={'path':'fixture','sha256':'fixture'},h01_pointer='/directions/6')
        target['independent_review']={'model_report':report}
        actual={'observation':{'user_id':'56','stance':'prefer'},'quote':'希望设备颜色一致'}
        bridge=SimpleNamespace(checked=lambda ref:actual,pointer=lambda actual,path:actual)
        evidence={'user_id':'52','source_ref':family['h01_ref'],'pointer':'/directions/6/research_citations/0','quote':'希望设备颜色一致','acceptance_kind':'relationship_only','reason':'fixture'}
        group={'members':[target['candidate_id']],'pair_review':{'decision':'pass','subgroups':[{'candidate_ids':[target['candidate_id']],'user_scope_id':'52_formal',
          'member_surface_bindings':[{'candidate_id':target['candidate_id'],'surface_ids':['s1','s2']}],'accepted_base_color_evidence':[evidence]}]}}
        result=validate_pair_group_scope(group,{target['candidate_id']:target},family,bridge=bridge)
        self.assertIn('actual_citation_does_not_support_this_user_preference',result['errors'])
        self.assertIn('relation_only_preference_cannot_prove_specific_base_color_acceptance',result['errors'])


if __name__=='__main__':unittest.main()
