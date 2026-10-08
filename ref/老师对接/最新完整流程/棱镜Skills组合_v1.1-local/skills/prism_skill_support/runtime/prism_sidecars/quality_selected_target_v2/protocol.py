"""CMF-REFERENCE-V4. Fresh targets do not require a legacy quality result.

Stdlib only; no imports from frozen producers, no network or inference runner.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
VERSION='selected-target-quality-v2.0.0'
ROOT_THREAD='prism-local-executor'
MODEL={'model':'gpt-6-sol','reasoning_effort':'low','service_tier_requested':'default','fast_mode':False}
FEATURES={'CMF':['color','material_appearance','surface_pattern','optics','material_boundary'],
          'ID':['silhouette','proportion','surface_transition','structure_interface','rhythm','part_relationship']}

def need(c,e):
    if not c:raise ValueError(e)
def text(v):return isinstance(v,str) and bool(v.strip())
def digest(v):
    if not isinstance(v,bytes):v=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return sha256(v).hexdigest()
def strict_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out,'duplicate_json_key');out[k]=v
        return out
    def bad(value):raise ValueError('nonfinite_json')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)
def read_ref(ref,parse=True):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and text(ref.get('path')),'FileRef_required')
    name=ref['path'];need('://' not in name and not name.startswith(('\\\\','//')),'local_FileRef_required')
    path=Path(name);need(path.is_absolute() and path.is_file(),'absolute_existing_file_required')
    raw=path.read_bytes();need(digest(raw)==ref['sha256'],'file_hash_mismatch')
    return strict_json(raw.decode('utf-8-sig')) if parse else raw
def pointer(v,p):
    need(isinstance(p,str) and p.startswith('/'),'json_pointer_required')
    for k in p[1:].split('/'):
        k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
    return v
def pick(evidence):return pointer(read_ref(evidence['ref']),evidence['pointer'])
def seal(v,key):v[key]=digest(v);return v

def model_schema(target):
    s=lambda:{'type':'string','minLength':1}
    enum=lambda values:{'type':'string','enum':values}
    arr=lambda items,n:{'type':'array','items':items,'maxItems':n}
    def obj(props):return {'type':'object','additionalProperties':False,'required':list(props),'properties':props}
    return obj({'schema_version':enum(['prism.selected_target_quality.wire.v2']),
        'target_digest':enum([target['target_digest']]),'branch':enum([target['branch']]),
        'coverage':obj({'status':enum(['exact_target','partial_target','other_target','not_visible','uncertain']),
            'observed_scope':s(),'reason':s(),'limits':arr(s(),5)}),
        'observations':arr(obj({'evidence_id':s(),'carrier':enum(['selected_target','other_target','background','uncertain']),
            'region':s(),'feature':enum(FEATURES[target['branch']]),'observation':s()}),5),
        'quality':obj({'design_reference':{'type':'boolean'},'signal_level':enum(['clear','basic','none']),
            'image_quality':enum(['sufficient','limited','unusable']),
            'veto':enum(['none','unreadable','no_design_content','unsupported_use','clear_uncontrolled_defect']),
            'evidence_ids':arr(s(),5),'reason':s(),'limits':arr(s(),5)})})

def shape(v,s,path='$'):
    kinds={'object':dict,'array':list,'string':str,'boolean':bool};typ=s['type']
    if not isinstance(v,kinds[typ]):return [path+':type']
    errors=[]
    if 'enum' in s and v not in s['enum']:errors.append(path+':enum')
    if typ=='object':
        if set(v)!=set(s['required']):errors.append(path+':keys')
        for k,child in s['properties'].items():
            if k in v:errors+=shape(v[k],child,path+'/'+k)
    elif typ=='array':
        if len(v)>s['maxItems']:errors.append(path+':count')
        for i,child in enumerate(v):errors+=shape(child,s['items'],path+'/'+str(i))
    elif typ=='string' and not v.strip():errors.append(path+':empty')
    return errors

def prepare(*,run_id,manifest_ref,image_pointer,asset_evidence,selection_ref,
            view_request_ref,view_receipt_ref,original_result_ref=None):
    """Extract target verbatim from original-view selection, without DNA inference."""
    need(text(run_id),'new_run_id_required')
    manifest=read_ref(manifest_ref);row=pointer(manifest,image_pointer);asset=pick(asset_evidence)
    branch=manifest.get('branch');did=manifest.get('direction_id')
    need(branch in FEATURES and text(did),'selected_branch_required')
    need(isinstance(asset,dict) and text(asset.get('image_id')),'indexed_asset_required')
    base={'schema_version':'prism.selected_target_quality.prepared.v2','version':VERSION,'run_id':run_id,
        'image_id':asset['image_id'],'source_kind':asset.get('source_kind','unknown'),'branch':branch,'direction_id':did,
        'execution_authorized':False,'new_model_calls':0,'selected_target_decision':None,
        'prior_assessment_present':original_result_ref is not None,'prerequisite_global_quality_calls':0}
    if asset.get('source_kind') not in ['trend','public_design_reference']:
        return seal({**base,'status':'not_applicable','reason':'source_not_quality_eligible'},'prepared_digest')
    image=asset['image_ref'];need(row.get('image_ref')==image,'selected_image_identity_mismatch');read_ref(image,False)
    need(asset.get('source_status')=='established' and text(asset.get('source_group_id')),'source_identity_required')
    for ref in asset.get('provenance_refs',[]):read_ref(ref,False)
    selection=read_ref(selection_ref)
    need(selection.get('status')=='confirmed','confirmed_selection_required')
    need(selection.get('selection_digest')==digest({k:v for k,v in selection.items() if k!='selection_digest'}),'stale_selection_digest')
    directions=[d for d in selection['directions'] if d['direction_id']==did]
    need(len(directions)==1 and branch in directions[0]['branches'] and asset['image_id'] in directions[0]['candidate_image_ids'],'target_not_in_selected_branch')
    direction=directions[0]
    h01=read_ref(manifest['H01_selection_ref']);scope=read_ref(manifest['visual_scope_ref'])
    need(h01.get('digest')==digest({k:v for k,v in h01.items() if k!='digest'}),'stale_H01')
    need(any(d['direction_id']==did and branch in d['branches'] for d in h01['selection']),'H01_branch_mismatch')
    need(h01.get('confirmation',{}).get('status')=='confirmed','H01_not_confirmed')
    need(scope.get('direction_id')==did and scope.get('branch')==branch,'visual_scope_mismatch')
    original=None;old_scope=None
    if original_result_ref is not None:
        original=read_ref(original_result_ref)
        need(isinstance(original,dict),'original_quality_not_object')
        original_target=original.get('selected_target') or {}
        original_sha=(original.get('image_sha256') or (original.get('image_ref') or {}).get('sha256')
                      or original_target.get('image_sha256'))
        need(original.get('image_id')==asset['image_id'] and original_sha==image['sha256']
             and original.get('source_kind')==asset['source_kind'],'original_quality_image_mismatch')
        branch_key='cmf_reference' if branch=='CMF' else 'id_reference'
        if isinstance(original.get('uses'),dict):
            old_scope=deepcopy(original['uses'].get(branch_key))
        elif original.get('branch')==branch:
            old_scope=deepcopy(original)
    choice=row.get('original_view_choice',{})
    provenance={'manifest_ref':manifest_ref,'image_pointer':image_pointer,'asset_evidence':asset_evidence,
        'selection_ref':selection_ref,'view_review_ref':row.get('view_review_ref'),
        'view_request_ref':view_request_ref,'view_receipt_ref':view_receipt_ref,
        'original_result_ref':original_result_ref,'H01_ref':manifest['H01_selection_ref'],'visual_scope_ref':manifest['visual_scope_ref']}
    base.update(image_ref=deepcopy(image),source_group_id=asset['source_group_id'],source_provenance_refs=deepcopy(asset.get('provenance_refs',[])),
        input_refs=deepcopy(provenance),original_receipt=deepcopy(original),original_assessed_scope=old_scope,
        selected_view_record=deepcopy(choice),negative_audit=deepcopy(direction.get('negative_audit',[])),
        deferred_obligations=deepcopy(direction.get('deferred_obligations',[])),visual_scope_context=deepcopy(scope))
    description=choice.get('visible_surface_scope')
    if (choice.get('choice')!='candidate_for_DNA_and_quality' or choice.get('original_seen') is not True
            or not text(description) or not isinstance(choice.get('limits'),list)):
        return seal({**base,'status':'not_assessed','reason':'incomplete_selected_target'},'prepared_digest')
    if not row.get('view_review_ref') or not view_request_ref or not view_receipt_ref:
        return seal({**base,'status':'not_assessed','reason':'missing_selected_view_provenance'},'prepared_digest')
    review=read_ref(row['view_review_ref']);request=read_ref(view_request_ref);receipt=read_ref(view_receipt_ref)
    need(review.get('direction_id')==did,'view_direction_mismatch')
    matches=[(i,v) for i,v in enumerate(review.get('articles',[])) if v==choice]
    need(len(matches)==1,'choice_not_exact_original_view_output')
    n=choice.get('attached_image_index')
    need(type(n) is int and 1<=n<=len(request.get('images',[])) and request['images'][n-1]==image,'view_image_attachment_mismatch')
    need(type(receipt.get('exit_code')) is int and receipt['exit_code']==0 and receipt.get('timed_out') is False
         and receipt.get('schema_valid') is True and type(receipt.get('tool_event_count')) is int and receipt['tool_event_count']==0,'invalid_original_view_receipt')
    need(text(receipt.get('call_id')) and receipt['call_id']==request.get('call_id'),'view_call_id_mismatch')
    target={'image_id':asset['image_id'],'image_sha256':image['sha256'],'source_kind':asset['source_kind'],
        'branch':branch,'scope_kind':'local_cmf' if branch=='CMF' else 'overall_id','direction_id':did,
        'selected_scope':description,'selection_reason':choice.get('reason'),
        'selected_scope_limits':deepcopy(choice['limits']),
        # History is audit context, not part of the selected target's identity.
        'provenance':{**{k:v for k,v in provenance.items() if k!='original_result_ref'},'review_pointer':'/articles/'+str(matches[0][0]),
                      'choice_pointer':image_pointer+'/original_view_choice'},
        'target_identity_basis':'verbatim_original_view_selection_not_new_DNA'}
    target['target_digest']=digest(target)
    payload={k:target[k] for k in ['target_digest','branch','scope_kind','selected_scope','selected_scope_limits']}
    prompt=(ROOT/'prompt.txt').read_text(encoding='utf-8')+json.dumps(payload,ensure_ascii=False,indent=2)
    schema=model_schema(target)
    base.update(status='ready_not_assessed',target=target,prompt=prompt,prompt_sha256=digest(prompt.encode()),
        schema=schema,schema_sha256=digest(schema),model_policy=deepcopy(MODEL),
        maximum_primary_calls=1,maximum_confirmation_calls=1,old_result_upgraded=False,
        confirmation_prompt=prompt+'\n独立确认本次目标是否真的被评估，不接收旧PASS或首次答案，不要求通过。')
    base['confirmation_prompt_sha256']=digest(base['confirmation_prompt'].encode())
    return seal(base,'prepared_digest')

def current(p):
    need(p.get('prepared_digest')==digest({k:v for k,v in p.items() if k!='prepared_digest'}),'prepared_hash_mismatch')
    if p.get('status')!='ready_not_assessed':return
    replay=prepare(run_id=p['run_id'],manifest_ref=p['input_refs']['manifest_ref'],image_pointer=p['input_refs']['image_pointer'],
        asset_evidence=p['input_refs']['asset_evidence'],selection_ref=p['input_refs']['selection_ref'],
        view_request_ref=p['input_refs']['view_request_ref'],view_receipt_ref=p['input_refs']['view_receipt_ref'],
        original_result_ref=p['input_refs']['original_result_ref'])
    need(replay==p,'stale_target_provenance')

def build_request(p,stage='primary',previous=None):
    current(p);need(p['status']=='ready_not_assessed','target_not_prepared')
    need(stage in ['primary','confirmation'],'invalid_stage')
    if stage=='confirmation':
        need(isinstance(previous,dict) and previous.get('prepared_digest')==p['prepared_digest']
             and previous.get('confirmation_eligible') is True and previous.get('stage')=='primary','confirmation_not_eligible')
    prompt=p['prompt'] if stage=='primary' else p['confirmation_prompt']
    r={'schema_version':'prism.selected_target_quality.request.v2','version':VERSION,'run_id':p['run_id'],
       'prepared_digest':p['prepared_digest'],'target_digest':p['target']['target_digest'],'branch':p['branch'],
       'image_ref':deepcopy(p['image_ref']),'stage':stage,'target':deepcopy(p['target']),
       'prompt':prompt,'prompt_sha256':digest(prompt.encode()),'schema':deepcopy(p['schema']),'schema_sha256':p['schema_sha256'],
       **MODEL,'execution_authorized':False,'prior_result_sent_to_model':False,'expected_pass_supplied':False,
       'no_network_or_cli_execution_in_adapter':True}
    return seal(r,'request_digest')

def validate_grant(p,request,grant):
    current(p);need(isinstance(grant,dict),'new_explicit_target_grant_required')
    need(grant.get('authorized_by_thread_id')==ROOT_THREAD and grant.get('exclusive') is True,'root_exclusive_grant_required')
    for k in ['prepared_digest','target_digest','branch','request_digest']:
        need(grant.get(k)==request[k],'target_grant_mismatch:'+k)
    need(grant.get('image_sha256')==p['image_ref']['sha256'],'grant_image_mismatch')
    need(text(grant.get('executor_thread_id')) and text(grant.get('lease_id')),'executor_lease_required')
    need(type(grant.get('max_primary_calls')) is int and grant['max_primary_calls']==1,'primary_bound_required')
    need(type(grant.get('max_confirmation_calls')) is int and 0<=grant['max_confirmation_calls']<=1,'confirmation_bound_required')
    need(type(grant.get('max_total_calls')) is int and grant['max_total_calls']==1+grant['max_confirmation_calls'],'total_bound_required')
    return {'valid':True,'actual_os_lease_checked':False,'execution_performed':False}

def count_attempts(p,attempts):
    current(p);need(isinstance(attempts,list),'attempts_required');stages=set();calls=set();tokens=[]
    for a in attempts:
        need(isinstance(a,dict) and a.get('target_digest')==p['target']['target_digest'],'attempt_target_mismatch')
        stage=a.get('stage');cid=a.get('call_id')
        need(stage in ['primary','confirmation'] and stage not in stages and text(cid) and cid not in calls,'repeated_attempt')
        need(a.get('state') in ['reserved','started','completed','failed','interrupted'],'attempt_state_invalid')
        stages.add(stage);calls.add(cid);t=a.get('total_tokens')
        need(t is None or type(t) is int and t>=0,'invalid_token_usage');tokens.append(t)
    need('confirmation' not in stages or 'primary' in stages,'confirmation_without_primary')
    original=p.get('original_receipt')
    prior_calls=deepcopy(original.get('call_ids',[])) if isinstance(original,dict) else []
    if isinstance(original,dict) and not prior_calls and text(original.get('call_id')):prior_calls=[original['call_id']]
    return {'new_target_reserved_attempts':len(attempts),'prior_call_ids':prior_calls,
        'prior_assessment_present':original is not None,
        'total_tokens':sum(tokens) if all(x is not None for x in tokens) else None,
        'provider_calls':None if attempts else 0,'automatic_retries':0,'model_calls_started_by_adapter':0}

def accept(p,execution_ref=None,*,target_review_ref=None,previous=None):
    """Only a distinct target request + actual receipt + exact-scope review can admit."""
    current(p)
    out={'schema_version':'prism.selected_target_quality.result.v2','version':VERSION,'prepared_digest':p['prepared_digest'],
        'image_id':p['image_id'],'branch':p['branch'],'source_kind':p['source_kind'],'status':'not_assessed','decision':None,
        'admissible':False,'old_result_upgraded':False,'model_calls_started_by_adapter':0,
        'selected_target':deepcopy(p.get('target')),'original_receipt_ref':deepcopy(p.get('input_refs',{}).get('original_result_ref')),
        'original_assessed_scope':deepcopy(p.get('original_assessed_scope')),
        'negative_audit':deepcopy(p.get('negative_audit',[])),'deferred_obligations':deepcopy(p.get('deferred_obligations',[])),
        'other_branch_decisions':{},'confirmation_eligible':False,'validated_target':None,
        'prior_assessment_present':p.get('prior_assessment_present',False),'prerequisite_global_quality_calls':0}
    if p['status']!='ready_not_assessed':out['reason']=p.get('reason',p['status']);return out
    if execution_ref is None:out['reason']='no_new_selected_target_evidence';return out
    e=read_ref(execution_ref);out['execution_ref']=deepcopy(execution_ref)
    if e.get('schema_version')!='prism.selected_target_quality.execution.v2':
        out['reason']='legacy_or_unbound_receipt_cannot_upgrade_selected_target';return out
    r=read_ref(e['request_ref']);receipt=read_ref(e['receipt_ref']);raw=read_ref(e['raw_output_ref'],False)
    stage=r.get('stage');expected=build_request(p,stage,previous)
    if r!=expected:out.update(status='invalid_output',reason='request_not_exact_target_bound');return out
    grant=read_ref(e['grant_ref']);validate_grant(p,r,grant)
    attempts=e.get('attempts');counts=count_attempts(p,attempts);out['call_accounting']=counts
    need(counts['new_target_reserved_attempts']<=grant['max_total_calls'],'grant_exhausted')
    need(any(a.get('call_id')==e.get('call_id') and a.get('stage')==stage and a.get('state') in ['completed','failed','interrupted'] for a in attempts),'execution_missing_from_ledger')
    if stage=='confirmation':need(grant['max_confirmation_calls']==1,'confirmation_not_granted')
    out.update(stage=stage,call_id=e.get('call_id'),raw_output_ref=deepcopy(e['raw_output_ref']),new_request_ref=deepcopy(e['request_ref']))
    if (receipt.get('call_id')!=e.get('call_id') or type(receipt.get('exit_code')) is not int or receipt['exit_code']!=0
        or receipt.get('timed_out') is not False or receipt.get('tool_event_count')!=0):
        out.update(status='execution_error',reason='target_inference_execution_failed');return out
    need(e.get('receipt_request_digest')==r['request_digest'] and e.get('receipt_raw_output_sha256')==e['raw_output_ref']['sha256'],'execution_receipt_binding_mismatch')
    try:wire=strict_json(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError):
        out.update(status='invalid_output',reason='invalid_new_target_json',confirmation_eligible=stage=='primary');return out
    errors=shape(wire,p['schema'])
    if errors:out.update(status='invalid_output',reason='new_target_wire_invalid',errors=errors,confirmation_eligible=stage=='primary');return out
    obs={};errors=[]
    for o in wire['observations']:
        if o['evidence_id'] in obs:errors.append('duplicate_evidence_id')
        obs[o['evidence_id']]=o
    q=wire['quality'];ids=q['evidence_ids']
    if len(set(ids))!=len(ids):errors.append('duplicate_evidence_reference')
    for eid in ids:
        if eid not in obs or obs[eid]['carrier']!='selected_target':errors.append('evidence_not_selected_target')
    if q['signal_level']=='clear' and (not ids or not q['design_reference']):errors.append('clear_without_selected_target_evidence')
    if q['image_quality']=='unusable' and q['veto']=='none':errors.append('unusable_without_veto')
    if errors:out.update(status='invalid_output',errors=errors,confirmation_eligible=stage=='primary');return out
    out['new_observations']=deepcopy(wire)
    if wire['coverage']['status']!='exact_target':
        out.update(status='scope_pending',reason='model_did_not_confirm_exact_selected_target',confirmation_eligible=stage=='primary');return out
    if target_review_ref is None:out.update(status='pending_target_confirmation',reason='actual_original_target_binding_review_required');return out
    review=read_ref(target_review_ref);out['target_review_ref']=deepcopy(target_review_ref)
    for key,value in [('target_digest',p['target']['target_digest']),('branch',p['branch']),('image_ref',p['image_ref']),
                      ('raw_output_ref',e['raw_output_ref']),('request_digest',r['request_digest'])]:
        need(review.get(key)==value,'target_review_binding_mismatch:'+key)
    need(review.get('acknowledged_selection_limits')==p['target']['selected_scope_limits']
         and review.get('acknowledged_quality_limits')==q['limits']
         and review.get('acknowledged_coverage_limits')==wire['coverage']['limits'],'target_limits_changed')
    need(review.get('negative_audit_digest')==digest(p['negative_audit']) and review.get('deferred_obligations_digest')==digest(p['deferred_obligations']),'negative_or_pending_context_changed')
    checked=review.get('covered_evidence_ids')
    need(isinstance(checked,list) and all(text(x) for x in checked) and len(set(checked))==len(checked) and set(ids)<=set(checked) and all(x in obs and obs[x]['carrier']=='selected_target' for x in checked),'review_evidence_scope_mismatch')
    if review.get('original_image_seen') is not True or review.get('target_verdict')!='exact_target':
        out.update(status='scope_pending',reason='original_review_does_not_cover_selected_target');return out
    need(text(review.get('reason')),'target_review_reason_required')
    passed=q['design_reference'] and q['signal_level']=='clear' and q['image_quality']!='unusable' and q['veto']=='none' and bool(ids)
    out.update(status='complete',decision='PASS' if passed else 'FAIL',admissible=bool(passed),reason=q['reason'],
        limits=deepcopy(q['limits']),scope_kind=p['target']['scope_kind'])
    out['validated_target']={
        'target_digest':p['target']['target_digest'],'image_id':p['image_id'],'image_ref':deepcopy(p['image_ref']),
        'source_kind':p['source_kind'],'source_group_id':p['source_group_id'],'branch':p['branch'],
        'scope_kind':p['target']['scope_kind'],'selected_scope':p['target']['selected_scope'],
        'target_provenance':deepcopy(p['target']['provenance']),
        'source_provenance_refs':deepcopy(p['source_provenance_refs']),
        'selection_limits':deepcopy(p['target']['selected_scope_limits']),
        'quality_limits':deepcopy(q['limits']),'coverage_limits':deepcopy(wire['coverage']['limits']),
        'evidence_ids':deepcopy(ids),'evidence':[deepcopy(obs[eid]) for eid in ids],
        'request_ref':deepcopy(e['request_ref']),'raw_output_ref':deepcopy(e['raw_output_ref']),
        'target_review_ref':deepcopy(target_review_ref),'target_verdict':review['target_verdict'],
        'quality_decision':out['decision'],'target_scope_verified':True,
        'r5_positions':None,'r5_alignment_verified':False,'display_region_verified':False,
        'region_semantics':'original descriptive regions; not R5 at, bbox or merged endpoint facts',
        'negative_audit_digest':digest(p['negative_audit']),'deferred_obligations_digest':digest(p['deferred_obligations'])}
    if stage=='primary' and not passed and q['design_reference'] and q['signal_level']=='basic' and q['veto']=='none' and ids:
        out['confirmation_eligible']=True
    return out

def clustering_view(p,execution_ref=None,*,target_review_ref=None,previous=None):
    """Replay acceptance and expose scope/evidence, never invent R5 alignment."""
    result=accept(p,execution_ref,target_review_ref=target_review_ref,previous=previous)
    return {'schema_version':'prism.selected_target_quality.clustering_view.v2',
        'quality_result_digest':digest(result),'status':result['status'],'decision':result['decision'],
        'admissible':result['admissible'],'image_id':result['image_id'],'branch':result['branch'],
        'source_kind':result['source_kind'],'validated_target':deepcopy(result['validated_target']),
        'selected_target':deepcopy(result['selected_target']),
        'unvalidated_observations':deepcopy(result.get('new_observations')) if result['validated_target'] is None else None,
        'negative_audit':deepcopy(result['negative_audit']),'deferred_obligations':deepcopy(result['deferred_obligations']),
        'original_receipt_ref':deepcopy(result['original_receipt_ref']),
        'requires_original_target_to_R5_confirmation':True,
        'board_coherence_decision':None,'physical_properties_verified':False}
