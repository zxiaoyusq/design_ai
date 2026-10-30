"""Behavioral counterexamples for the v2 handoff contracts. No inference or network."""
from pathlib import Path
from copy import deepcopy
import json,os,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
SUP=ROOT/'skills/prism_skill_support'
sys.path[:0]=[str(SUP/'scripts'),str(SUP/'runtime')]
from io_utils import write,ref,read,sha,store_content
import material_plan,review_gate,native_api,workflow

class Contracts(unittest.TestCase):
 def setUp(self):
  root=Path(os.environ.get('PRISM_TEST_ROOT',str(ROOT.parent/'v2-test-work')));root.mkdir(parents=True,exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=root,prefix='v2-');self.p=Path(self.tmp.name)
  self.img=ROOT/'cases/linear-relief/originals/N001.jpg'
  self.trace=self.put('trace.txt','Synthetic test trace; not a human or model review.')
  self.b={'direction_id':'SYN-CMF','branch':'CMF','comparison_unit':'surface','primary_relation':'synthetic repeated relief','required_evidence':['surface'],'allowed_variation':['carrier'],'confounders':['flat pattern'],'scope_limits':['no physical claim'],'frozen_before_final_selection':True,'count_policy':{'minimum':1,'target':1,'maximum':2},'candidate_pool_policy':{'target':3}}
  self.row={'image_id':'I1','article_id':'A1','source_group_id':'A1','source_project_id':'P1','identity_basis':'synthetic identity','image_ref':ref(self.img),'current_target':'synthetic target','comparison_scope':'synthetic surface','primary_relation_evidence':'synthetic observation','secondary_signal':'none asserted','rectangle':{'x':0,'y':0,'width':1,'height':1},'treatment':'crop','reason':'synthetic test','read_trace_ref':ref(self.trace)}
 def tearDown(self):self.tmp.cleanup()
 def put(self,name,value):p=self.p/name;write(p,value);return p
 def material(self,b=None,row=None):return material_plan.prepare(self.put('brief.json',b or self.b),self.put('materials.json',{'items':[row or self.row]}),self.p/'prepared')
 def board(self,rows=None):
  br=self.put('brief.json',self.b);items=rows or [{'image_id':'I1','original_ref':ref(self.img),'view_ref':ref(self.img),'article_id':'A1','source_group_id':'A1','source_project_id':'P1'}]
  b={'dataset_mode':'synthetic_fixture','brief_ref':ref(br),'rendered_board_ref':ref(self.img),'tiles':items};bp=self.put('board.json',b)
  r={'board_manifest_sha256':sha(bp),'rendered_board_sha256':sha(self.img),'brief_sha256':sha(br),'review_kind':'synthetic_fixture','reviewer_actor':'synthetic test','review_trace_ref':ref(self.trace),'visual_judgment':'pass','slots':[{'image_id':q['image_id'],'can_remain':True} for q in items]}
  return bp,r
 def test_prepare_does_not_award_visual_pass_or_shrink_pool(self):
  r=self.material();self.assertFalse(r['visual_PASS_awarded']);self.assertEqual(r['candidate_pool_target'],3);self.assertEqual(r['final_board_target'],1);self.assertEqual(r['new_model_calls'],0)
 def test_frozen_config_retains_original_relative_input_identity(self):
  image=self.put('inputs/source.txt','source evidence');cfg={'project_id':'SYN','model_policy':{'fast_mode':False},'input_paths':{'one':'./inputs/source.txt','missing':'./not-yet-present','folder':'./inputs'}}
  config=self.put('project.json',cfg);workflow.init(config,self.p/'nested'/'run')
  frozen=read(self.p/'nested/run/project.frozen.json');self.assertEqual(Path(frozen['input_paths']['one']),image.resolve());self.assertTrue(Path(frozen['input_paths']['folder']).is_dir());self.assertFalse(Path(frozen['input_paths']['missing']).exists())
  self.assertEqual(read(self.p/'nested/run/project.source.json'),cfg)
 def test_wrong_image_hash_rejected(self):
  row=deepcopy(self.row);row['image_ref']['sha256']='0'*64
  with self.assertRaises(ValueError):self.material(row=row)
 def test_short_archive_name_preserves_full_hash_and_rejects_changed_content(self):
  body=b'synthetic original';p=store_content(body,self.p/'archive','.txt');self.assertEqual(len(p.stem),20);self.assertEqual(p.read_bytes(),body)
  self.assertEqual(store_content(body,self.p/'archive','.txt'),p);p.write_bytes(b'tampered')
  with self.assertRaises(ValueError):store_content(body,self.p/'archive','.txt')
 def test_outside_crop_rejected(self):
  row=deepcopy(self.row);row['rectangle']['width']=1.1
  with self.assertRaises(ValueError):self.material(row=row)
 def test_ID_cannot_use_surface_contract(self):
  b=deepcopy(self.b);b['branch']='ID'
  with self.assertRaises(ValueError):self.material(b=b)
 def test_unresolved_source_not_invented(self):
  row=deepcopy(self.row);row['source_project_id']=None;r=self.material(row=row)
  self.assertIn('project_identity_unresolved',[q['issue'] for q in r['findings']])
 def test_enhancement_is_display_only(self):
  row=deepcopy(self.row);row['treatment']='display_enhance';r=self.material(row=row)
  self.assertIn('display_only_enhancement_cannot_resolve_evidence_gap',[q['issue'] for q in r['findings']])
 def test_current_board_review_binds_exact_bytes(self):
  bp,r=self.board();r['rendered_board_sha256']='0'*64
  with self.assertRaises(ValueError):review_gate.verify(bp,self.put('review.json',r))
 def test_pass_cannot_hide_rejected_member(self):
  bp,r=self.board();r['slots'][0]['can_remain']=False
  with self.assertRaises(ValueError):review_gate.verify(bp,self.put('review.json',r))
 def test_synthetic_pass_stays_synthetic(self):
  bp,r=self.board();v=review_gate.verify(bp,self.put('review.json',r));self.assertFalse(v['eligible_to_report_scoped_AI_or_human_visual_result']);self.assertFalse(v['new_visual_review_performed'])
 def test_duplicate_projects_are_reported(self):
  row={'image_id':'I1','original_ref':ref(self.img),'view_ref':ref(self.img),'article_id':'A1','source_group_id':'A1','source_project_id':'P1'};b=deepcopy(row);b.update(image_id='I2',article_id='A2',source_group_id='A2')
  bp,r=self.board([row,b]);v=review_gate.verify(bp,self.put('review.json',r));self.assertIn('duplicate_source_project_id',v['provenance_and_quantity_issues'])
 def test_review_cannot_omit_a_tile(self):
  bp,r=self.board();r['slots']=[]
  with self.assertRaises(ValueError):review_gate.verify(bp,self.put('review.json',r))
 def test_optional_future_api_is_exposed(self):
  self.assertIn('derive_future_references',native_api.describe('future-references'));self.assertIn('accept_grouping',native_api.describe('future-id'))
 def test_future_reference_immutable_synthetic_source(self):
  from prism_runtime.clustering.id_reference_board_v5.common import seal
  from prism_runtime.clustering.h2_original_negative_future_ref_v1.references import derive_future_references,validate_future_references
  negative={'negative_id':'SYN-N1','statement':'synthetic target must not glare','original_person_id':'synthetic-person','original_scope':'future back panel'}
  prepared=seal({'schema_version':'prism.cmf.prepared.v4','brief':{'negative_audit':[negative],'deferred_obligations':[]},'negative_aliases':{'N01':negative}})
  proposal={'prepared_digest':prepared['digest'],'negative_dispositions':[{'negative_alias':'N01','status':'future_product_obligation','deferred_obligation_indices':[],'reason':'future target, not current reference claim','scope_basis':'synthetic future back panel'}]}
  pr=ref(self.put('proposal.json',proposal));doc=derive_future_references(prepared,pr);valid=ref(self.put('future.json',doc));self.assertEqual(validate_future_references(prepared,pr,valid),doc)
  for name,change in [('resolved',lambda d:d['references'][0].update(resolved=True)),('person',lambda d:d['references'][0]['original_negative'].update(original_person_id='someone-else')),('erased',lambda d:d['references'].clear())]:
   bad=deepcopy(doc);change(bad)
   with self.assertRaises(ValueError):validate_future_references(prepared,pr,ref(self.put(name+'.json',bad)))

if __name__=='__main__':unittest.main()
