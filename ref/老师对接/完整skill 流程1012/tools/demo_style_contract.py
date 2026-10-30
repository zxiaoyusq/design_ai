"""Create an explicitly synthetic, entirely local v4 contract demo. Not a real moodboard."""
from pathlib import Path
import argparse, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/prism_skill_support/scripts'))
from style_board_check import verify, sha
from render_style_board import render

def dump(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')

def make_fixture(folder):
    from PIL import Image, ImageDraw
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    def ref(p):return {'path':p.relative_to(folder).as_posix(),'sha256':sha(p)}
    source=folder/'synthetic-research.txt'
    source.write_text('SYNTHETIC FIXTURE ONLY. Fictional P1: I prefer an orderly front, but not a reflective back. No real participant or product.','utf-8')
    trend=folder/'synthetic-trend.txt';trend.write_text('SYNTHETIC: arranged front with low-reflection back. No real source.','utf-8')
    upstream=folder/'synthetic-upstream.json'
    dump(upstream,{'dataset_mode':'synthetic_fixture','negative_audit':[{'id':'SYN-N1','original':'not a reflective back','object':'back','status':'unresolved'}]})
    trace=folder/'synthetic-read-record.txt';trace.write_text('SYNTHETIC DATA for testing refs only; no actual visual review occurred.','utf-8')
    binding={'dataset_mode':'synthetic_fixture','status':'bound','research_evidence':[{'unit_id':'SYN-U1','person_id':'SYN-P1','object_scope':'fictional front/back','full_text':'I prefer an orderly front, but not a reflective back.','quote':'I prefer an orderly front, but not a reflective back.','attitude':'conditional','evidence_kind':'synthetic_fixture','kind':'phone_preference_reason','text_kind':'original_text','claimed_direct_preference':True,'source_ref':ref(source)}],'trend_evidence':[{'parent_cluster_id':'SYN-T1','article_ids':['SYN-A1'],'text_kind':'original_text','source_ref':ref(trend)}],'upstream_refs':[ref(upstream)],'negative_audit':[{'id':'SYN-N1','original':'not a reflective back','object_scope':'back','status':'unresolved'}],'deferred_obligations':[]}
    bp=folder/'research-binding.json';dump(bp,binding)
    tiles=[]
    for i in range(8):
        p=folder/f'synthetic-{i+1}.png'
        im=Image.new('RGB',(200,200),(230-i*6,228-i*5,220-i*4));d=ImageDraw.Draw(im)
        d.rectangle((35,35,165,165),outline=(80+i*3,80,80),width=2)
        d.text((42,90),f'SYNTHETIC {i+1}',fill='black');im.save(p)
        tiles.append({'image_id':f'SYN-I{i+1}','article_id':f'SYN-A{i+1}','source_group_id':f'SYN-S{i+1}','project_id':f'SYN-PROJECT{i+1}','project_identity_basis':'synthetic distinct IDs, not real provenance','original_ref':ref(p),'rectangle':{'x':0,'y':0,'width':1,'height':1},'comparison_scope':'synthetic square only','semantic_relation':'synthetic data-link example, not an inferred human preference','visual_evidence':'synthetic outlined square','product_design_use':'schema demonstration only','source_role':'semantic_member','semantic_parent_ids':['SYN-T1'],'image_kind':'unknown','observations':[{'dimension':'synthetic geometry','location':'center','visible_evidence':'drawn rectangle'}],'actual_image_read_ref':ref(trace),'analysis_status':'synthetic_fixture_not_actual_analysis','runway_status':'not_runway','layout':{'x':30+(i%4)*230,'y':170+(i//4)*220,'width':200,'height':200}})
    board={'schema_version':'prism.style-board.v4','dataset_mode':'synthetic_fixture','title':'Synthetic contract demo','research_level':'overall_style','run_mode':'visual_trial','branch':'ID_CMF','originals_only':True,'coordinate_space':'display_oriented','design_language':{'core_relationships':['synthetic square relationship for file tests only'],'allowed_variation':['synthetic colour differences'],'core_conflicts':['fixture contains no real moodboard judgment'],'emotion_hypothesis':'not evaluated; synthetic demo'},'count_policy':{'minimum':8,'target':8,'maximum':10},'source_policy':{'one_per_article':True,'one_per_known_project':True,'runway_max_fraction':None},'research_binding_ref':ref(bp),'native_status':{'H01':'not_executed','H2':'not_executed'},'canvas':{'width':950,'height':620,'background':'#EEECE6'},'texts':[{'text':'SYNTHETIC FIXTURE — NOT A MOODBOARD\nContract and portable-layout demonstration only.','x':30,'y':25,'width':890,'height':120,'font_size':22,'bold':True,'color':'#292B2A'}],'tiles':tiles}
    path=folder/'board.v4.json';dump(path,board)
    return path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args()
    path=make_fixture(a.out);check=verify(path);dump(path.parent/'mechanical-check.json',check)
    result=render(path,path.parent/'rendered')
    print(json.dumps({'fixture':str(path),'mechanical_contract_valid':check['machine_contract_valid'],'aesthetic_pass_awarded':False,'new_model_calls':0,**result},ensure_ascii=False))

if __name__=='__main__':main()
