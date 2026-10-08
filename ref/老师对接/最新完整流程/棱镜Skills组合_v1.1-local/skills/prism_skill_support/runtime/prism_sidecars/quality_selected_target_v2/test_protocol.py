"""Target-identity regressions. All constructed executions are synthetic tests."""
from copy import deepcopy
from pathlib import Path
import base64,json,tempfile,unittest
from .protocol import *

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRZkAAAAASUVORK5CYII=')
def ref(path):return {'path':str(path.resolve()),'sha256':digest(path.read_bytes())}
def save(path,v):path.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8');return ref(path)

def fixture(folder):
    image=folder/'image.png';image.write_bytes(PNG);image_ref=ref(image)
    h01={'selection':[{'direction_id':'CMF01','branches':['CMF']}],'confirmation':{'status':'confirmed'}}
    h01['digest']=digest(h01);h01_ref=save(folder/'h01.json',h01)
    scope_ref=save(folder/'scope.json',{'direction_id':'CMF01','branch':'CMF','hint_only':True})
    choice={'article_id':'a','choice':'candidate_for_DNA_and_quality','original_seen':True,'attached_image_index':1,
            'visible_surface_scope':'left child shirt including collar and sleeve trim',
            'visible_relation_evidence':'synthetic original-view relation','reason':'Exclude papers and other clothing',
            'limits':['shirt partly occluded; no back view']}
    answer_ref=save(folder/'view-answer.json',{'direction_id':'CMF01','articles':[choice]})
    request_ref=save(folder/'view-request.json',{'call_id':'original-view','images':[image_ref]})
    receipt_ref=save(folder/'view-receipt.json',{'call_id':'original-view','exit_code':0,'timed_out':False,'schema_valid':True,'tool_event_count':0})
    manifest={'direction_id':'CMF01','branch':'CMF','H01_selection_ref':h01_ref,'visual_scope_ref':scope_ref,
              'images':[{'image_ref':image_ref,'original_view_choice':choice,'view_review_ref':answer_ref}]}
    manifest_ref=save(folder/'manifest.json',manifest)
    asset={'image_id':'same-image','image_ref':image_ref,'source_kind':'trend','source_status':'established',
           'source_group_id':'original-source','provenance_refs':[scope_ref]}
    asset_ref=save(folder/'asset.json',{'asset':asset})
    direction={'direction_id':'CMF01','branches':['CMF'],'candidate_image_ids':['same-image'],
               'negative_audit':[{'id':'negative','statement':'too flashy','scope':'unresolved'}],
               'deferred_obligations':[{'id':'pending-material','status':'pending'}]}
    selection={'status':'confirmed','directions':[direction]};selection['selection_digest']=digest(selection)
    selection_ref=save(folder/'selection.json',selection)
    old={'schema_version':'prism.quality_selected.decision.v2','image_id':'same-image','image_sha256':image_ref['sha256'],
         'source_kind':'trend','uses':{'cmf_reference':{'decision':'PASS','evidence':[{'region':'paper airplanes','observation':'paper facets'}],
                                                     'limits':['paper composition unknown']}},'call_ids':['old-paper-call']}
    old_ref=save(folder/'old-result.json',old)
    args=dict(run_id='separate-target-run',manifest_ref=manifest_ref,image_pointer='/images/0',
              asset_evidence={'ref':asset_ref,'pointer':'/asset'},selection_ref=selection_ref,
              view_request_ref=request_ref,view_receipt_ref=receipt_ref,original_result_ref=old_ref)
    return args,old_ref

def wire(p,carrier='selected_target',coverage='exact_target',branch=None):
    return {'schema_version':'prism.selected_target_quality.wire.v2','target_digest':p['target']['target_digest'],
        'branch':branch or p['branch'],'coverage':{'status':coverage,'observed_scope':'shirt collar and cuff',
            'reason':'synthetic test observation','limits':['limited view']},
        'observations':[{'evidence_id':'e1','carrier':carrier,'region':'shirt collar','feature':'color','observation':'synthetic relation'}],
        'quality':{'design_reference':True,'signal_level':'clear','image_quality':'sufficient','veto':'none',
                   'evidence_ids':['e1'],'reason':'synthetic quality basis','limits':['not physical proof']}}

def execution(folder,p,value=None,review_verdict='exact_target',scope_override=None):
    request=build_request(p);request_ref=save(folder/'new-target-request.json',request)
    value=value if value is not None else wire(p);raw_ref=save(folder/'new-target-wire.json',value)
    grant={'authorized_by_thread_id':ROOT_THREAD,'exclusive':True,'executor_thread_id':'TEST-executor','lease_id':'TEST-lease',
        **{k:request[k] for k in ['prepared_digest','target_digest','branch','request_digest']},
        'image_sha256':p['image_ref']['sha256'],'max_primary_calls':1,'max_confirmation_calls':1,'max_total_calls':2}
    grant_ref=save(folder/'TEST-grant.json',grant)
    receipt_ref=save(folder/'TEST-receipt.json',{'call_id':'TEST-new-target','exit_code':0,'timed_out':False,'tool_event_count':0})
    e={'schema_version':'prism.selected_target_quality.execution.v2','fixture_only':True,'request_ref':request_ref,
       'raw_output_ref':raw_ref,'receipt_ref':receipt_ref,'grant_ref':grant_ref,'call_id':'TEST-new-target',
       'receipt_request_digest':request['request_digest'],'receipt_raw_output_sha256':raw_ref['sha256'],
       'attempts':[{'call_id':'TEST-new-target','stage':'primary','state':'completed','target_digest':p['target']['target_digest']}]}
    e_ref=save(folder/'TEST-execution.json',e)
    review={'target_digest':scope_override or p['target']['target_digest'],'branch':p['branch'],'image_ref':p['image_ref'],
        'raw_output_ref':raw_ref,'request_digest':request['request_digest'],'covered_evidence_ids':['e1'],
        'acknowledged_selection_limits':p['target']['selected_scope_limits'],
        'acknowledged_quality_limits':value['quality']['limits'],'acknowledged_coverage_limits':value['coverage']['limits'],
        'negative_audit_digest':digest(p['negative_audit']),'deferred_obligations_digest':digest(p['deferred_obligations']),
        'original_image_seen':True,'target_verdict':review_verdict,'reason':'SYNTHETIC TEST, NOT REAL REVIEW'}
    return e_ref,save(folder/'TEST-target-review.json',review)

class TargetBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.args,self.old=fixture(self.folder);self.p=prepare(**self.args)
    def test_exact_selected_scope_extracted_without_DNA(self):
        self.assertEqual(self.p['target']['selected_scope'],'left child shirt including collar and sleeve trim')
        self.assertEqual(self.p['target']['provenance']['review_pointer'],'/articles/0')
        self.assertEqual(self.p['negative_audit'][0]['statement'],'too flashy')
        self.assertEqual(self.p['deferred_obligations'][0]['status'],'pending')
    def test_same_image_old_paper_PASS_cannot_upgrade_shirt(self):
        before=Path(self.old['path']).read_bytes();r=accept(self.p,self.old)
        self.assertEqual(r['status'],'not_assessed');self.assertIsNone(r['decision']);self.assertFalse(r['admissible'])
        self.assertEqual(r['original_assessed_scope']['decision'],'PASS')
        self.assertEqual(Path(self.old['path']).read_bytes(),before)
    def test_no_new_evidence_stays_not_assessed(self):
        r=accept(self.p);self.assertEqual(r['reason'],'no_new_selected_target_evidence')
        self.assertFalse(r['old_result_upgraded']);self.assertEqual(r['other_branch_decisions'],{})
    def test_incomplete_target_never_invents_pass_or_fail(self):
        data=read_ref(self.args['manifest_ref']);data['images'][0]['original_view_choice']['visible_surface_scope']=''
        self.args['manifest_ref']=save(self.folder/'manifest-missing.json',data)
        p=prepare(**self.args);self.assertEqual(p['status'],'not_assessed');self.assertIsNone(accept(p)['decision'])
        with self.assertRaises(ValueError):build_request(p)
    def test_changed_hash_or_view_provenance_rejected(self):
        Path(self.args['view_request_ref']['path']).write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):accept(self.p)
    def test_same_image_wrong_selected_scope_claim_rejected(self):
        e,r=execution(self.folder,self.p,review_verdict='other_target')
        out=accept(self.p,e,target_review_ref=r)
        self.assertEqual(out['status'],'scope_pending');self.assertFalse(out['admissible']);self.assertIsNone(out['decision'])
    def test_other_object_evidence_never_supports_target(self):
        e,r=execution(self.folder,self.p,wire(self.p,carrier='other_target'))
        out=accept(self.p,e,target_review_ref=r)
        self.assertEqual(out['status'],'invalid_output');self.assertIn('evidence_not_selected_target',out['errors'])
    def test_only_CMF_cannot_become_ID(self):
        e,r=execution(self.folder,self.p,wire(self.p,branch='ID'))
        out=accept(self.p,e,target_review_ref=r)
        self.assertEqual(out['status'],'invalid_output');self.assertIsNone(out['decision']);self.assertEqual(out['other_branch_decisions'],{})
    def test_exact_target_positive_requires_new_record_and_review(self):
        e,r=execution(self.folder,self.p)
        pending=accept(self.p,e);self.assertEqual(pending['status'],'pending_target_confirmation')
        out=accept(self.p,e,target_review_ref=r)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['branch'],'CMF');self.assertEqual(out['scope_kind'],'local_cmf')
        self.assertEqual(out['original_assessed_scope']['evidence'][0]['region'],'paper airplanes')
    def test_scope_digest_must_match_even_same_image(self):
        e,r=execution(self.folder,self.p,scope_override='wrong-target-digest')
        with self.assertRaises(ValueError):accept(self.p,e,target_review_ref=r)
    def test_network_failure_is_not_aesthetic_FAIL(self):
        e,r=execution(self.folder,self.p);data=read_ref(e);receipt=read_ref(data['receipt_ref']);receipt['exit_code']=1
        data['receipt_ref']=save(self.folder/'TEST-failed.json',receipt);e=save(self.folder/'TEST-failed-execution.json',data)
        out=accept(self.p,e,target_review_ref=r);self.assertEqual(out['status'],'execution_error');self.assertIsNone(out['decision'])
    def test_prior_call_accounting_preserved_and_retry_bounded(self):
        a={'call_id':'new','stage':'primary','state':'interrupted','target_digest':self.p['target']['target_digest']}
        out=count_attempts(self.p,[a]);self.assertEqual(out['prior_call_ids'],['old-paper-call']);self.assertIsNone(out['provider_calls'])
        with self.assertRaises(ValueError):count_attempts(self.p,[a,a])
    def test_old_image_grant_cannot_authorize_new_target(self):
        request=build_request(self.p)
        with self.assertRaises(ValueError):validate_grant(self.p,request,{'image_sha256':self.p['image_ref']['sha256']})
    def test_negative_and_limit_context_cannot_be_erased(self):
        e,r=execution(self.folder,self.p);review=read_ref(r);review['negative_audit_digest']=digest([])
        r=save(self.folder/'TEST-erased-negative.json',review)
        with self.assertRaises(ValueError):accept(self.p,e,target_review_ref=r)
    def test_provider_wire_contract_has_explicit_types(self):
        def walk(v):
            if isinstance(v,dict):
                if 'enum' in v or 'const' in v:self.assertIn('type',v)
                self.assertNotIn('uniqueItems',v)
                for c in v.values():walk(c)
            elif isinstance(v,list):
                for c in v:walk(c)
        walk(self.p['schema'])

class FreshTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.args,self.old=fixture(self.folder)
        self.args['original_result_ref']=None
        Path(self.old['path']).unlink()  # Prove there is no legacy file to read.
        self.p=prepare(**self.args)
    def test_fresh_prepare_has_no_legacy_receipt_and_no_global_call(self):
        self.assertEqual(self.p['status'],'ready_not_assessed')
        self.assertIsNone(self.p['original_receipt']);self.assertIsNone(self.p['original_assessed_scope'])
        self.assertIsNone(self.p['input_refs']['original_result_ref']);self.assertFalse(self.p['prior_assessment_present'])
        self.assertEqual(self.p['prerequisite_global_quality_calls'],0)
        self.assertEqual(count_attempts(self.p,[])['prior_call_ids'],[])
        self.assertEqual(accept(self.p)['status'],'not_assessed')
        self.assertIsNone(accept(self.p)['validated_target'])
    def test_original_argument_can_be_omitted(self):
        args={k:v for k,v in self.args.items() if k!='original_result_ref'}
        self.assertEqual(prepare(**args),self.p)
    def test_fresh_exact_target_requires_real_target_confirmation_contract(self):
        e,r=execution(self.folder,self.p)
        self.assertEqual(accept(self.p,e)['status'],'pending_target_confirmation')
        result=accept(self.p,e,target_review_ref=r)
        self.assertEqual(result['decision'],'PASS');self.assertIsNone(result['original_receipt_ref'])
        bound=result['validated_target']
        self.assertTrue(bound['target_scope_verified']);self.assertEqual(bound['branch'],'CMF')
        self.assertEqual(bound['evidence_ids'],['e1']);self.assertIsNone(bound['r5_positions'])
        self.assertFalse(bound['r5_alignment_verified']);self.assertFalse(bound['display_region_verified'])
        view=clustering_view(self.p,e,target_review_ref=r)
        self.assertEqual(view['validated_target'],bound);self.assertEqual(view['negative_audit'],self.p['negative_audit'])
        self.assertIsNone(view['board_coherence_decision'])
    def test_fresh_wrong_carrier_stays_unassessed_even_same_image(self):
        e,r=execution(self.folder,self.p,wire(self.p,carrier='other_target'))
        result=accept(self.p,e,target_review_ref=r)
        self.assertEqual(result['status'],'invalid_output');self.assertIsNone(result['decision']);self.assertIsNone(result['validated_target'])
    def test_fresh_model_echo_cannot_override_wrong_target_review(self):
        e,r=execution(self.folder,self.p,review_verdict='other_target')
        result=accept(self.p,e,target_review_ref=r)
        self.assertEqual(result['status'],'scope_pending');self.assertFalse(result['admissible']);self.assertIsNone(result['validated_target'])
    def test_fresh_missing_scope_or_execution_failure_not_FAIL(self):
        data=read_ref(self.args['manifest_ref']);data['images'][0]['original_view_choice']['visible_surface_scope']=''
        args=deepcopy(self.args);args['manifest_ref']=save(self.folder/'incomplete-manifest.json',data)
        pending=prepare(**args);self.assertIsNone(accept(pending)['decision'])
        e,r=execution(self.folder,self.p);d=read_ref(e);rc=read_ref(d['receipt_ref']);rc['exit_code']=1
        d['receipt_ref']=save(self.folder/'failed-receipt.json',rc);er=save(self.folder/'failed-execution.json',d)
        self.assertEqual(accept(self.p,er,target_review_ref=r)['status'],'execution_error')
    def test_target_identity_is_not_changed_by_optional_history(self):
        old={'image_id':'same-image','image_sha256':self.p['image_ref']['sha256'],'source_kind':'trend',
             'uses':{'cmf_reference':{'decision':'PASS','evidence':[{'region':'paper'}]}},'call_ids':['prior']}
        args=deepcopy(self.args);args['original_result_ref']=save(self.folder/'actual-prior.json',old)
        with_prior=prepare(**args)
        self.assertEqual(with_prior['target']['target_digest'],self.p['target']['target_digest'])
        self.assertNotEqual(with_prior['prepared_digest'],self.p['prepared_digest'])
        self.assertEqual(accept(with_prior,args['original_result_ref'])['status'],'not_assessed')
    def test_prior_selected_target_result_preserved_without_upgrade(self):
        old={'schema_version':'prism.selected_target_quality.result.v1','image_id':'same-image','source_kind':'trend',
             'selected_target':deepcopy(self.p['target']),'branch':'CMF','decision':'PASS','call_id':'older-target-call'}
        args=deepcopy(self.args);args['original_result_ref']=save(self.folder/'prior-target-result.json',old)
        p=prepare(**args)
        self.assertEqual(p['original_receipt'],old);self.assertEqual(p['original_assessed_scope'],old)
        self.assertEqual(count_attempts(p,[])['prior_call_ids'],['older-target-call'])
        self.assertIsNone(accept(p,args['original_result_ref'])['decision'])
if __name__=='__main__':unittest.main()
