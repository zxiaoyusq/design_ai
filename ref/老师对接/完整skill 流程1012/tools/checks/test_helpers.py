"""Behavioral tests on new portable glue using synthetic data. Zero model calls."""
from pathlib import Path
from copy import deepcopy
from tempfile import TemporaryDirectory
import base64,importlib.util,json,os,struct,subprocess,sys,time,unittest,zipfile,zlib

PKG=Path(__file__).resolve().parents[2];BASE=Path(os.environ.get('PRISM_TEST_ROOT',str(Path.cwd()/'prism-offline-tests'))).resolve();S=PKG/'skills';SUP=S/'prism_skill_support/scripts'
sys.path.insert(0,str(SUP));sys.path.insert(0,str(S/'prism-dna-sol-r5/scripts'))
from io_utils import read,write,ref,digest
import intake_pptx,trend_text,recall,assets,render_board,workflow,run_model,bounded_process
def png_chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
PNG=b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+png_chunk(b'IDAT',zlib.compress(b'\x00\xff\xff\xff\xff'))+png_chunk(b'IEND',b'')

class Helpers(unittest.TestCase):
    def setUp(self):
        root=BASE/'helper-test-work';root.mkdir(parents=True,exist_ok=True);self.tmp=TemporaryDirectory(dir=root,prefix='case-');self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def put(self,name,x):p=self.p/name;write(p,x);return p
    def make_trends(self):
        source=self.put('articles.json',{'dataset_mode':'synthetic_fixture','records':[{'article_id':'A1','title':'合成低反射盒体','summary':'表面低反射，按钮沿侧边排列。','detail_url':'https://example.invalid/a1','image_urls':['https://example.invalid/i1.png']},{'article_id':'A2','title':'合成低反射灯','summary':'低反射主体具有细窄亮边。','image_urls':[]},{'article_id':'A3','title':'信息不足','summary':'未描述具体设计关系。','image_urls':[]}]})
        trend_text.prepare(source,self.p/'prepared',2);corpus=self.p/'prepared/corpus.json';d=read(corpus)
        proposal={'corpus_digest':digest(d),'analyst':{'actor_id':'synthetic-author'},'themes':[{'theme_id':'G1','title':'低反射外观','definition':'明确的低反射表面描述','boundary':'不证明材料和反射率','design_question':'可见光感怎样组织'}],'assignments':[{'article_id':'A1','theme_id':'G1','anchor':'表面低反射','reason':'合成原句支持'},{'article_id':'A2','theme_id':'G1','anchor':'低反射主体','reason':'合成原句支持'},{'article_id':'A3','theme_id':None,'reason':'原句无具体关系'}]}
        pp=self.put('proposal.json',proposal);review={'proposal_sha256':ref(pp)['sha256'],'reviewer':{'actor_id':'synthetic-reviewer','review_kind':'synthetic_fixture'},'reviews':[{'article_id':'A1','theme_id':'G1','status':'supported','anchor':'表面低反射','reason':'合成检查'},{'article_id':'A2','theme_id':'G1','status':'uncertain','anchor':'低反射主体','reason':'刻意保留合成未知'}]};rp=self.put('review.json',review)
        return corpus,pp,rp
    def test_supported_only_rank_and_h01_export(self):
        c,p,r=self.make_trends();trend_text.compile_run(c,p,r,self.p/'out');o=read(self.p/'out/trend-clusters.json');self.assertEqual(o['clusters'][0]['evidence_refs'],['TEXT:A1']);self.assertEqual(o['dataset_mode'],'synthetic_fixture');self.assertEqual(len(read(self.p/'out/coverage.json')),3)
        core=S/'prism-h01-semantic-handshake/scripts';sys.path.insert(0,str(core));from h01_core.trends import load_trends
        view=load_trends(self.p/'out/trend-clusters.json',self.p/'out/text-catalogue.json');self.assertEqual(len(view['clusters']),1);self.assertEqual(len(view['unclustered_evidence_ids']),2)
    def test_trend_foreign_anchor_rejected(self):
        c,p,r=self.make_trends();v=read(r);v['reviews'][0]['anchor']='不存在的原句';rp=self.put('bad-review.json',v)
        with self.assertRaises(ValueError):trend_text.compile_run(c,p,rp,self.p/'bad')
    def test_trend_missing_review_rejected(self):
        c,p,r=self.make_trends();v=read(r);v['reviews']=v['reviews'][:1];rp=self.put('bad-review.json',v)
        with self.assertRaises(ValueError):trend_text.compile_run(c,p,rp,self.p/'bad')
    def test_trend_duplicate_assignment_rejected(self):
        c,p,r=self.make_trends();v=read(p);v['assignments'].append(v['assignments'][0]);pp=self.put('bad-proposal.json',v);w=read(r);w['proposal_sha256']=ref(pp)['sha256'];rp=self.put('bad-review.json',w)
        with self.assertRaises(ValueError):trend_text.compile_run(c,pp,rp,self.p/'bad')
    def test_pptx_extract_does_not_infer_preference(self):
        pp=self.p/'source.pptx'
        with zipfile.ZipFile(pp,'w') as z:
            z.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="r1"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="slides/slide1.xml"/></Relationships>')
            z.writestr('ppt/slides/slide1.xml','<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>Not glossy, but the edge can be bright.</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
        cfg=self.put('intake.json',{'dataset_id':'synthetic-intake','dataset_mode':'synthetic_fixture','sources':[{'source_id':'S1','person_id':'P1','path':'source.pptx'}]});intake_pptx.extract(cfg,self.p/'out');d=read(self.p/'out/research-input.draft.json');self.assertEqual(d['units'][0]['attitude'],'unknown');self.assertEqual(d['units'][0]['kind'],'reference');self.assertIn('but',d['units'][0]['text']);self.assertEqual(d['schema_version'],'prism.research_semantic_input.v1')
    def test_recall_requires_all_groups_and_keeps_membership(self):
        rows=[{'article_id':'A1','title':'折面灯主体','summary':'','image_urls':['x'],'primary_theme_id':'G9'},{'article_id':'A2','title':'折面','summary':'','image_urls':['x'],'primary_theme_id':'G1'}];o=recall.recall(rows,{'term_groups':[['折面'],['灯']],'maximum_text_candidates':10});self.assertEqual(len(o['selected']),1);self.assertEqual(o['selected'][0]['primary_theme_id'],'G9');self.assertFalse(o['selected'][0]['visual_qualification'])
    def image(self,name='one.png',tail=b''):p=self.p/name;p.write_bytes(PNG+tail);return p
    def board(self):
        p=self.image();return {'title':'合成显示测试','branch':'CMF','stage_status':'synthetic_fixture','tiles':[{'image_ref':ref(p),'article_id':'A1','source_group_id':'article:A1','rectangle':{'x':0,'y':0,'width':1,'height':1},'scope':'合成fixture','limits':[]}]}
    def test_display_embeds_original_no_pass(self):
        data=self.board();page,a=render_board.build(data);self.assertIn('data:image/png;base64,',page);self.assertFalse(a['visual_PASS_awarded']);self.assertEqual(a['external_image_resources'],0)
    def test_display_duplicate_article_rejected_even_different_project(self):
        data=self.board();t=deepcopy(data['tiles'][0]);t['image_ref']=ref(self.image('two.png',b'synthetic second bytes'));t['source_group_id']='different';t['source_project_id']='different';data['tiles'].append(t)
        with self.assertRaises(ValueError):render_board.build(data)
    def test_display_duplicate_project_rejected(self):
        data=self.board();data['tiles'][0]['source_project_id']='same';t=deepcopy(data['tiles'][0]);t['article_id']='A2';t['image_ref']=ref(self.image('two.png',b'2'));data['tiles'].append(t)
        with self.assertRaises(ValueError):render_board.build(data)
    def test_display_outside_roi_rejected(self):
        data=self.board();data['tiles'][0]['rectangle']['x']=.8
        with self.assertRaises(ValueError):render_board.build(data)
    def test_display_changed_bytes_rejected(self):
        data=self.board();Path(data['tiles'][0]['image_ref']['path']).write_bytes(PNG+b'changed')
        with self.assertRaises(ValueError):render_board.build(data)
    def test_display_corrupt_image_rejected(self):
        data=self.board();p=Path(data['tiles'][0]['image_ref']['path']);p.write_bytes(PNG[:40]);data['tiles'][0]['image_ref']=ref(p)
        with self.assertRaises(Exception):render_board.build(data)
    def test_acquire_no_implicit_network(self):
        plan=self.put('plan.json',{'images':[{'image_id':'I1','article_id':'A1','source_group_id':'A1','image_url':'https://example.invalid/not-requested'}]});r=assets.acquire(plan,self.p/'out');self.assertEqual(r['decoded'],0);self.assertEqual(read(self.p/'out/manifest.json')['images'][0]['status'],'not_downloaded')
    def test_acquire_original_byte_preservation(self):
        im=self.image();plan=self.put('plan.json',{'images':[{'image_id':'I1','article_id':'A1','source_group_id':'A1','local_path':'one.png'}]});assets.acquire(plan,self.p/'out');r=read(self.p/'out/manifest.json')['images'][0];self.assertEqual(r['original_ref']['sha256'],ref(im)['sha256'])
    def test_metadata_only_cache_and_three_round_issue_not_global_stop(self):
        cfg=self.put('project.json',{'project_id':'test','model_policy':{'fast_mode':False}});workflow.init(cfg,self.p/'run');base={'stage':'quality','algorithm_version':'v1','semantic_inputs':{'image':'sha'},'processing_config':{},'model_policy':{},'notes':'one'};another={**base,'notes':'more explanation'};self.assertEqual(workflow.cache_key(base),workflow.cache_key(another))
        for i in range(3):
            j=self.put(f'job{i}.json',base);o=self.put(f'outcome{i}.json',{'status':'failed','artifact_refs':[],'issue_id':'Q1'});workflow.record(self.p/'run',j,o)
        s=read(self.p/'run/state.json');self.assertEqual(s['issues']['Q1']['status'],'needs_method_or_user_decision');self.assertEqual(s['status'],'in_progress')
    def test_complete_stage_reuses_without_overwrite(self):
        cfg=self.put('project.json',{'project_id':'test','model_policy':{'fast_mode':False}});workflow.init(cfg,self.p/'run');j=self.put('job.json',{'stage':'DNA','algorithm_version':'v1','semantic_inputs':{'hash':'a'}});artifact=self.put('artifact.json',{'fixture_only':True});o=self.put('outcome.json',{'status':'complete','artifact_refs':[ref(artifact)]});workflow.record(self.p/'run',j,o);r=workflow.record(self.p/'run',j,o);self.assertEqual(r['action'],'reuse_same_version_and_semantic_input')
    def test_complete_without_artifact_rejected(self):
        cfg=self.put('project.json',{'project_id':'test','model_policy':{'fast_mode':False}});workflow.init(cfg,self.p/'run');j=self.put('job.json',{'stage':'DNA','algorithm_version':'v1','semantic_inputs':{'hash':'a'}});o=self.put('outcome.json',{'status':'complete','artifact_refs':[]})
        with self.assertRaises(ValueError):workflow.record(self.p/'run',j,o)
    def test_generic_model_prepare_does_not_execute(self):
        self.put('prompt.txt','Synthetic preparation only');self.put('schema.json',{'type':'object'});job=self.put('job.json',{'stage':'test','call_id':'TEST','prompt_path':'prompt.txt','schema_path':'schema.json','images':[],'execution_authorization':{'allowed':False}});r=run_model.run(job,self.p/'prepared',codex='missing-codex-for-offline-test');self.assertEqual(r['model_calls'],0);self.assertFalse((self.p/'prepared/receipt.json').exists())
        with self.assertRaises(ValueError):run_model.run(job,self.p/'not-started',execute=True,codex='missing-codex')
    def test_large_file_stdin_transport(self):
        d=self.p/'call';d.mkdir();code,out,err,timed,error=bounded_process.execute([sys.executable,'-c','import sys; print(len(sys.stdin.buffer.read()))'],'x'*2000000,str(self.p),5,d);self.assertEqual(code,0);self.assertEqual(out.strip(),'2000000');self.assertFalse(timed)
    def test_transport_timeout_is_bounded(self):
        d=self.p/'call';d.mkdir();start=time.monotonic();code,out,err,timed,error=bounded_process.execute([sys.executable,'-c','import time; time.sleep(10)'],'',str(self.p),.1,d);self.assertTrue(timed);self.assertLess(time.monotonic()-start,5)

if __name__=='__main__':unittest.main()
