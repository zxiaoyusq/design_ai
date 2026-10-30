"""Meaningful offline boundary checks for current v4 handoffs; no models/network."""
from pathlib import Path
from copy import deepcopy
import importlib.util, json, os, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'skills/prism_skill_support/scripts'))
from demo_style_contract import make_fixture, dump
from style_board_check import verify, sha
from render_style_board import render
import workflow

class StyleBoundaryTests(unittest.TestCase):
    def setUp(self):
        root=Path(os.environ.get('PRISM_TEST_ROOT',str(ROOT.parent/'style-v4-tests')));root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root,prefix='style-');self.path=make_fixture(Path(self.tmp.name)/'fixture')
        self.board=json.loads(self.path.read_text('utf-8'))
    def tearDown(self):self.tmp.cleanup()
    def check(self):dump(self.path,self.board);return verify(self.path)
    def test_valid_structure_never_awards_aesthetic_or_human_approval(self):
        r=self.check();self.assertTrue(r['machine_contract_valid']);self.assertTrue(r['mechanical_requirements_met'])
        self.assertFalse(r['aesthetic_pass_awarded']);self.assertFalse(r['human_approval_verified']);self.assertFalse(r['new_visual_review_performed'])
    def test_short_board_preserves_candidate_but_not_requirements(self):
        self.board['tiles'].pop();r=self.check();self.assertTrue(r['machine_contract_valid']);self.assertFalse(r['mechanical_requirements_met']);self.assertIn('count_outside_frozen_policy',r['findings'])
    def test_lowering_minimum_without_current_instruction_rejected(self):
        self.board['count_policy']['minimum']=7;self.assertFalse(self.check()['machine_contract_valid'])
    def test_tampered_original_rejected(self):
        self.board['tiles'][0]['original_ref']['sha256']='0'*64;self.assertFalse(self.check()['machine_contract_valid'])
    def test_duplicate_project_rejected(self):
        self.board['tiles'][1]['project_id']=self.board['tiles'][0]['project_id'];self.assertFalse(self.check()['machine_contract_valid'])
    def test_duplicate_crop_of_same_original_not_new_image(self):
        self.board['tiles'][1]['original_ref']=self.board['tiles'][0]['original_ref'];self.assertFalse(self.check()['machine_contract_valid'])
    def test_outside_roi_rejected(self):
        self.board['tiles'][0]['rectangle']['width']=1.1;self.assertFalse(self.check()['machine_contract_valid'])
    def test_missing_research_ref_is_not_silently_discarded(self):
        self.board['research_binding_ref']=None;self.assertFalse(self.check()['machine_contract_valid'])
    def test_upstream_negative_file_changed_is_rejected(self):
        (self.path.parent/'synthetic-upstream.json').write_text('{}','utf-8');self.assertFalse(self.check()['machine_contract_valid'])
    def test_partial_binding_stays_partial(self):
        bp=self.path.parent/'research-binding.json';b=json.loads(bp.read_text('utf-8'));b['status']='partial';dump(bp,b)
        self.board['research_binding_ref']['sha256']=sha(bp);r=self.check();self.assertTrue(r['machine_contract_valid']);self.assertIn('research_binding_partial',r['findings'])
    def test_paraphrase_cannot_be_marked_complete_binding(self):
        bp=self.path.parent/'research-binding.json';b=json.loads(bp.read_text('utf-8'));b['trend_evidence'][0]['text_kind']='source_paraphrase';dump(bp,b)
        self.board['research_binding_ref']['sha256']=sha(bp);self.assertFalse(self.check()['machine_contract_valid'])
        b['status']='partial';dump(bp,b);self.board['research_binding_ref']['sha256']=sha(bp)
        r=self.check();self.assertTrue(r['machine_contract_valid']);self.assertFalse(r['mechanical_requirements_met'])
    def test_brand_impression_not_promoted_to_direct_preference(self):
        bp=self.path.parent/'research-binding.json';b=json.loads(bp.read_text('utf-8'));b['research_evidence'][0]['kind']='brand_preference_or_impression';dump(bp,b)
        self.board['research_binding_ref']['sha256']=sha(bp);self.assertFalse(self.check()['machine_contract_valid'])
    def test_missing_evidence_identity_rejected(self):
        bp=self.path.parent/'research-binding.json';b=json.loads(bp.read_text('utf-8'));del b['research_evidence'][0]['evidence_kind'];dump(bp,b)
        self.board['research_binding_ref']['sha256']=sha(bp);self.assertFalse(self.check()['machine_contract_valid'])
    def test_source_identity_unknown_stays_pending(self):
        self.board['tiles'][0]['project_id']=None;r=self.check();self.assertFalse(r['mechanical_requirements_met']);self.assertTrue(r['machine_contract_valid'])
    def test_optional_quota_not_hardcoded_from_old_trial(self):
        for t in self.board['tiles']:t['runway_status']='runway'
        self.assertTrue(self.check()['mechanical_requirements_met'])
        self.board['source_policy'].update(runway_max_fraction=.3,runway_policy_basis='synthetic user policy')
        self.assertIn('runway_limit_exceeded',self.check()['findings'])
    def test_model_ledger_keeps_current_model_policy(self):
        cfg=self.path.parent/'project.json';dump(cfg,{'project_id':'synthetic','model_policy':{'model':'synthetic-user-choice','fast_mode':True}})
        workflow.init(cfg,self.path.parent/'run');f=json.loads((self.path.parent/'run/project.frozen.json').read_text('utf-8'))
        self.assertEqual(f['model_policy']['model'],'synthetic-user-choice');self.assertTrue(f['model_policy']['fast_mode'])
    def test_renderer_preserves_sources_and_produces_distinct_text_modes(self):
        sources={t['original_ref']['path']:sha(self.path.parent/t['original_ref']['path']) for t in self.board['tiles']}
        render(self.path,self.path.parent/'rendered');a=(self.path.parent/'rendered/communication.html').read_text('utf-8');b=(self.path.parent/'rendered/pure-images.html').read_text('utf-8')
        self.assertEqual(a.count('<img '),8);self.assertEqual(b.count('<img '),8);self.assertIn('class="copy"',a);self.assertNotIn('class="copy"',b)
        for p,h in sources.items():self.assertEqual(sha(self.path.parent/p),h)
    def test_renderer_rejects_distortion(self):
        self.board['tiles'][0]['layout']['width']=160;dump(self.path,self.board)
        with self.assertRaises(ValueError):render(self.path,self.path.parent/'bad-render')
    def test_exif_orientation_uses_display_dimensions_without_rewriting(self):
        from PIL import Image
        p=self.path.parent/'rotated.jpg';im=Image.new('RGB',(200,100),'#123456');exif=Image.Exif();exif[274]=6;im.save(p,exif=exif)
        h=sha(p);self.board['tiles'][0]['original_ref']={'path':p.name,'sha256':h}
        self.board['tiles'][0]['layout']['width']=100;dump(self.path,self.board)
        render(self.path,self.path.parent/'orientation-render');self.assertEqual(sha(p),h)
    def test_ambiguous_crop_coordinate_space_rejected(self):
        del self.board['coordinate_space'];dump(self.path,self.board)
        self.assertFalse(self.check()['machine_contract_valid'])
        with self.assertRaises(ValueError):render(self.path,self.path.parent/'no-coordinate-render')
    def test_dna_membership_ignores_titles_and_preserves_unknowns(self):
        path=ROOT/'skills/prism-dna-clustering/scripts/cluster.py';spec=importlib.util.spec_from_file_location('trial_cluster',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        a={'image_id':'SYN','known_facts':[{'p':'COL-006','v':'灰色','at':'主体'},{'p':'OPT-001','v':'合成材料外观','at':'主体'},{'p':'OPT-002','v':'哑光','at':'主体'},{'p':'OPT-003','v':'不透明','at':'主体'}],'effective_texture_states':{'主体':'unknown'}}
        b=deepcopy(a);b.update(title='a different arbitrary style',research_preference='not clustering input')
        self.assertEqual(m.make_units(a),m.make_units(b));units,_=m.make_units(a)
        for u in units:self.assertNotIn('TEXTURE_STATE',u['attributes'])

if __name__=='__main__':unittest.main()
