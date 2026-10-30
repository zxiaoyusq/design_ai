"""Validate material identities and planned treatments. No model or visual verdict."""
from pathlib import Path
import argparse,json
from io_utils import read,write,fresh,checked,ref,rectangle

ACTIONS={'keep_whole','crop','display_enhance','request_clearer_source','evidence_pending','exclude_for_family'}
def prepare(brief_path,candidates_path,out):
 b=read(brief_path);c=read(candidates_path)
 if b.get('branch') not in ('ID','CMF'):raise ValueError('ID/CMF branch required')
 if b.get('comparison_unit') not in ('whole_object','surface','same_object_interface'):raise ValueError('Explicit comparison unit required')
 if b['branch']=='ID' and b['comparison_unit']!='whole_object':raise ValueError('ID comparison cannot silently become a local surface')
 for k in ('direction_id','primary_relation'):
  if not isinstance(b.get(k),str) or not b[k].strip():raise ValueError(k+' required')
 for k in ('required_evidence','allowed_variation','confounders','scope_limits'):
  if not isinstance(b.get(k),list) or not b[k]:raise ValueError(k+' must be explicit')
 if b.get('frozen_before_final_selection') is not True:raise ValueError('Freeze family before final selection')
 count=b.get('count_policy',{});nums=[count.get(k) for k in ('minimum','target','maximum')]
 if any(type(x)!=int or x<1 for x in nums) or not nums[0]<=nums[1]<=nums[2]:raise ValueError('Invalid final board quantity policy')
 target=b.get('candidate_pool_policy',{}).get('target')
 if type(target)!=int or target<1:raise ValueError('Candidate pool policy separate from final count is required')
 rows=c.get('items',[])
 if not rows:raise ValueError('No materials')
 seen=set();findings=[];groups=set();projects=set()
 for row in rows:
  if row.get('image_id') in seen:raise ValueError('Duplicate image_id')
  seen.add(row.get('image_id'))
  for k in ('image_id','article_id','source_group_id','current_target','comparison_scope','primary_relation_evidence','secondary_signal','reason'):
   if not isinstance(row.get(k),str) or not row[k].strip():raise ValueError(k+' must describe this material')
  checked(row['image_ref'],False);rectangle(row['rectangle'])
  if row.get('treatment') not in ACTIONS:raise ValueError('Unknown treatment')
  trace=row.get('read_trace_ref')
  if trace is not None:checked(trace,False)
  else:findings.append({'image_id':row['image_id'],'issue':'actual_image_read_trace_missing'})
  groups.add(row['source_group_id'])
  if row.get('source_project_id'):
   if not row.get('identity_basis'):raise ValueError('Project identity needs basis')
   projects.add(row['source_project_id'])
  else:findings.append({'image_id':row['image_id'],'issue':'project_identity_unresolved'})
  if row.get('treatment')=='display_enhance':findings.append({'image_id':row['image_id'],'issue':'display_only_enhancement_cannot_resolve_evidence_gap'})
 if len(rows)<target:findings.append({'issue':'candidate_pool_below_declared_target','actual':len(rows),'target':target})
 if target<=count['target']:findings.append({'issue':'candidate_capacity_not_broader_than_final_board','not_automatically_expanded':True})
 folder=fresh(out);write(folder/'brief.frozen.json',b);write(folder/'materials.frozen.json',c)
 summary={'status':'prepared_with_findings' if findings else 'prepared','direction_id':b['direction_id'],'candidate_rows':len(rows),'unique_image_bytes':len({q['image_ref']['sha256'] for q in rows}),'registered_source_groups':len(groups),'known_project_ids':len(projects),'candidate_pool_target':target,'final_board_target':count['target'],'findings':findings,'brief_ref':ref(folder/'brief.frozen.json'),'candidates_ref':ref(folder/'materials.frozen.json'),'visual_PASS_awarded':False,'new_model_calls':0}
 write(folder/'summary.json',summary);return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--brief',required=True);p.add_argument('--candidates',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(prepare(a.brief,a.candidates,a.out),ensure_ascii=False))
