"""CMF reference-signal gate. No total score, no filename/brand/label whitelist."""
TYPES={'object_detail','material_texture','color_optical','whole_object','fashion','space_composition','non_design'}
REGIONS={'whole','upper','center','lower','left','right'}
FEATURES={'form','color','material_appearance','surface_pattern','optics','detail','composition'}
VETOS={'none','unreadable','no_design_content','clear_uncontrolled_defect'}
def evaluate(v):
 errors=[];warnings=[]
 if not isinstance(v,dict):return {'valid':False,'errors':['not_object'],'decision':None}
 required={'image_type','design_reference','signal_level','image_quality','veto','evidence','limits'}
 if not required.issubset(v) or not set(v).issubset(required|{'reason'}):errors.append('wrong_keys')
 if v.get('image_type') not in TYPES:errors.append('invalid_image_type')
 if type(v.get('design_reference')) is not bool:errors.append('invalid_design_reference')
 if v.get('signal_level') not in {'distinct','basic','none'}:errors.append('invalid_signal_level')
 if v.get('image_quality') not in {'sufficient','limited','unusable'}:errors.append('invalid_image_quality')
 if v.get('veto') not in VETOS:errors.append('invalid_veto')
 evidence=v.get('evidence')
 if not isinstance(evidence,list) or len(evidence)>3:errors.append('invalid_evidence')
 else:
  for e in evidence:
   if not isinstance(e,dict) or set(e)!={'region','feature','observation'}:errors.append('invalid_evidence_shape');continue
   if not isinstance(e.get('region'),str) or not 1<=len(e['region'].strip())<=80:errors.append('invalid_region')
   if e.get('feature') not in FEATURES:errors.append('invalid_feature')
   if not isinstance(e.get('observation'),str) or not e['observation'].strip():errors.append('empty_observation')
 limits=v.get('limits')
 if not isinstance(limits,list) or len(limits)>2 or any(not isinstance(x,str) for x in limits):errors.append('invalid_limits')
 if not isinstance(v.get('reason'),str) or not v['reason'].strip():warnings.append('summary_missing_use_evidence')
 if v.get('signal_level')=='distinct' and not evidence:errors.append('distinct_without_evidence')
 if v.get('image_quality')=='unusable' and v.get('veto')=='none':errors.append('unusable_without_veto')
 if errors:return {'valid':False,'errors':errors,'decision':None}
 passed=v['design_reference'] and v['signal_level']=='distinct' and v['image_quality']!='unusable' and v['veto']=='none' and bool(evidence)
 return {'valid':True,'errors':[],'warnings':warnings,'decision':'PASS' if passed else 'FAIL'}

def display_reason(v):
 if isinstance(v.get('reason'),str) and v['reason'].strip():return v['reason'],'model_summary'
 evidence=v.get('evidence') or []
 if evidence and isinstance(evidence[0],dict):return evidence[0].get('observation',''),'first_model_evidence'
 return '','unavailable'
