"""Check review provenance and declarative consistency; never performs visual review."""
from pathlib import Path
import argparse,json
from io_utils import read,checked,ref,sha

def verify(board_path,review_path):
 b=read(board_path);r=read(review_path);issues=[]
 if r.get('board_manifest_sha256')!=sha(board_path):raise ValueError('Review belongs to another board manifest')
 rendered=b['rendered_board_ref'];brief=b['brief_ref'];checked(rendered,False);spec=checked(brief)
 if r.get('rendered_board_sha256')!=rendered['sha256'] or r.get('brief_sha256')!=brief['sha256']:raise ValueError('Review board/brief identity changed')
 if r.get('review_kind') not in ('ai_independent_context','human','synthetic_fixture'):raise ValueError('Explicit reviewer kind required')
 if not r.get('reviewer_actor'):raise ValueError('Actual reviewer identity required')
 checked(r['review_trace_ref'],False)
 tiles=b.get('tiles',[]);ids=[t['image_id'] for t in tiles]
 if len(ids)!=len(set(ids)):raise ValueError('Duplicate selected image_id')
 slots=r.get('slots',[]);review_ids=[t['image_id'] for t in slots]
 if len(review_ids)!=len(set(review_ids)) or set(review_ids)!=set(ids):raise ValueError('Review must cover exactly the current tiles')
 if r.get('visual_judgment') not in ('pass','revise','insufficient'):raise ValueError('Explicit visual judgment required')
 if r['visual_judgment']=='pass' and not all(t.get('can_remain') is True for t in slots):raise ValueError('PASS contradicts member findings')
 for t in tiles:checked(t['original_ref'],False);checked(t['view_ref'],False)
 for key in ['article_id','source_group_id','source_project_id']:
  vals=[t.get(key) for t in tiles if t.get(key)]
  if len(vals)!=len(set(vals)):issues.append('duplicate_'+key)
 hashes=[t['original_ref']['sha256'] for t in tiles]
 if len(hashes)!=len(set(hashes)):issues.append('duplicate_image_bytes')
 if any(not t.get('source_project_id') for t in tiles):issues.append('project_identity_uncertain')
 policy=spec['count_policy'];quantity=policy['minimum']<=len(tiles)<=policy['maximum']
 if not quantity:issues.append('quantity_outside_frozen_policy')
 synthetic=b.get('dataset_mode')=='synthetic_fixture' or r['review_kind']=='synthetic_fixture'
 return {'machine_contract_check':'valid','quantity_pass':quantity,'provenance_and_quantity_issues':issues,'visual_judgment_origin':r['review_kind'],'reported_visual_judgment':r['visual_judgment'],'eligible_to_report_scoped_AI_or_human_visual_result':not synthetic and not issues and r['visual_judgment']=='pass','native_H01_H2_gate_not_executed_by_this_tool':True,'new_visual_review_performed':False,'synthetic_fixture':synthetic,'new_model_calls':0}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--board',required=True);p.add_argument('--review',required=True);a=p.parse_args();print(json.dumps(verify(a.board,a.review),ensure_ascii=False))
