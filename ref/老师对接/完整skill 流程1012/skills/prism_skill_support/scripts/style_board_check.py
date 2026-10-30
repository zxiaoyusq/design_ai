"""Offline file/identity/coverage checks for style boards. Never judges aesthetics."""
from pathlib import Path
import argparse, hashlib, json, math

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked_ref(value, base):
    if not isinstance(value, dict) or not isinstance(value.get('path'), str):
        raise ValueError('FileRef needs path and sha256')
    path = Path(value['path']).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file() or value.get('sha256') != sha(path):
        raise ValueError('missing file or changed SHA: '+str(path))
    return path

def rectangle(r):
    if not isinstance(r, dict):
        raise ValueError('rectangle required')
    vals = [r.get(k) for k in ['x','y','width','height']]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in vals):
        raise ValueError('rectangle must use finite numeric coordinates')
    x,y,w,h = vals
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > 1+1e-9 or y+h > 1+1e-9:
        raise ValueError('rectangle is outside original image')

def verify(board_path):
    board_path = Path(board_path).resolve()
    base = board_path.parent
    b = read(board_path)
    errors, findings = [], []
    def need(condition, message):
        if not condition: errors.append(message)
    def ref(value, label):
        try: return checked_ref(value, base)
        except (ValueError, OSError, TypeError) as e:
            errors.append(label+': '+str(e)); return None
    need(b.get('schema_version') == 'prism.style-board.v4', 'wrong schema_version')
    need(b.get('research_level') in ('overall_style','element'), 'research_level required')
    need(b.get('run_mode') in ('visual_trial','end_to_end','historical_replay'), 'run_mode required')
    need(b.get('branch') in ('ID','CMF','ID_CMF'), 'branch required')
    spec = b.get('design_language', {})
    for k in ('core_relationships','allowed_variation','core_conflicts'):
        need(isinstance(spec.get(k),list) and bool(spec[k]) and all(isinstance(v,str) and v.strip() for v in spec[k]), 'design_language.'+k+' required')
    need(isinstance(spec.get('emotion_hypothesis'),str) and bool(spec['emotion_hypothesis'].strip()), 'emotion_hypothesis required')
    need(b.get('originals_only') is True, 'originals_only must be true in this workflow')
    need(b.get('coordinate_space') == 'display_oriented', 'declare display_oriented ROI coordinate space')
    policy = b.get('count_policy', {})
    numbers = [policy.get(k) for k in ('minimum','target','maximum')]
    numeric = all(type(n) is int and n > 0 for n in numbers)
    need(numeric and numbers[0] <= numbers[1] <= numbers[2] if numeric else False, 'invalid frozen count_policy')
    if numeric and numbers[0] < 8:
        need(isinstance(policy.get('user_override_basis'),str) and bool(policy['user_override_basis'].strip()), 'minimum below 8 requires actual current user override basis')
    need(b.get('source_policy',{}).get('one_per_article') is True, 'one_per_article required')
    need(b.get('source_policy',{}).get('one_per_known_project') is True, 'one_per_known_project required')
    binding_path = ref(b.get('research_binding_ref'), 'research_binding_ref')
    binding = {}
    if binding_path:
        try:
            binding = read(binding_path)
            need(binding.get('status') in ('bound','partial','missing'), 'binding status required')
            for k in ('research_evidence','trend_evidence','upstream_refs','negative_audit','deferred_obligations'):
                need(isinstance(binding.get(k),list), 'binding.'+k+' required (empty must be explicit)')
            if binding.get('status') == 'bound':
                need(bool(binding.get('research_evidence')) and bool(binding.get('trend_evidence')), 'bound requires both research and trend evidence')
            else:
                findings.append('research_binding_'+str(binding.get('status')))
            # Every upstream record is byte-bound; downstream commentary cannot silently replace it.
            for i, source in enumerate(binding.get('upstream_refs', [])):
                try: checked_ref(source, binding_path.parent)
                except (ValueError, OSError, TypeError) as e: errors.append('upstream_ref_'+str(i)+': '+str(e))
            for i, item in enumerate(binding.get('research_evidence', [])):
                for k in ('unit_id','person_id','object_scope','full_text','quote','attitude','source_ref','evidence_kind','text_kind','kind'):
                    need(bool(item.get(k)), 'research_evidence_'+str(i)+'.'+k+' required')
                if item.get('text_kind') in ('source_paraphrase','analysis_note','unknown') or item.get('evidence_kind') in ('analyst_notes','unknown') or item.get('kind') == 'unknown':
                    findings.append('research_evidence_'+str(i)+'_partial_or_unknown')
                    need(binding.get('status') != 'bound', 'partial research evidence cannot be marked bound')
                direct_kinds={'selected_board_reason','selected_style_word','phone_preference_reason','explicit_cmf_caption'}
                if item.get('claimed_direct_preference') is True:
                    need(item.get('kind') in direct_kinds, 'brand/aspiration/example/reference cannot be promoted to direct preference')
                if item.get('quote') and item.get('full_text'):
                    need(item['quote'] in item['full_text'], 'research quote not present in full_text')
                if item.get('source_ref'):
                    try: checked_ref(item['source_ref'], binding_path.parent)
                    except (ValueError, OSError, TypeError) as e: errors.append('research_source_'+str(i)+': '+str(e))
            for i, item in enumerate(binding.get('trend_evidence', [])):
                need(bool(item.get('parent_cluster_id')) and bool(item.get('article_ids')), 'trend parent identity required')
                need(item.get('text_kind') in ('original_text','source_paraphrase','analysis_note'), 'trend text_kind required')
                if item.get('text_kind') in ('source_paraphrase','analysis_note'):
                    findings.append('trend_evidence_'+str(i)+'_is_not_original_text')
                    need(binding.get('status') != 'bound', 'trend paraphrase/analysis requires partial binding')
                if item.get('source_ref'):
                    try: checked_ref(item['source_ref'], binding_path.parent)
                    except (ValueError, OSError, TypeError) as e: errors.append('trend_source_'+str(i)+': '+str(e))
                else: findings.append('trend_source_ref_missing_'+str(i))
            if not binding.get('upstream_refs'):
                findings.append('upstream_original_bindings_missing')
            if not binding.get('negative_audit'):
                need(bool(binding.get('negative_audit_basis')), 'explain empty negative_audit; do not silently drop negatives')
        except (ValueError, TypeError, KeyError) as e:
            errors.append('binding content: '+str(e))
    tiles = b.get('tiles', [])
    need(isinstance(tiles,list) and bool(tiles), 'tiles required')
    if not isinstance(tiles,list): tiles=[]
    if numeric and not numbers[0] <= len(tiles) <= numbers[2]:
        findings.append('count_outside_frozen_policy')
    seen = {key:set() for key in ('image_id','article_id','source_group_id','project_id','sha256')}
    runway_known = runway_unknown = 0
    for i,t in enumerate(tiles):
        label = t.get('image_id', 'tile_'+str(i))
        for key in ('image_id','article_id','source_group_id','comparison_scope','semantic_relation','visual_evidence','product_design_use'):
            need(isinstance(t.get(key),str) and bool(t[key].strip()), label+': '+key+' required')
        for key in ('image_id','article_id','source_group_id','project_id'):
            value=t.get(key)
            if value:
                need(value not in seen[key], label+': duplicate '+key)
                seen[key].add(value)
        if not t.get('project_id'):
            findings.append(label+': project_identity_pending')
        else:
            need(bool(t.get('project_identity_basis')), label+': project identity basis required')
        need(t.get('source_role') in ('semantic_member','visual_extension'), label+': source_role required')
        need(t.get('image_kind') in ('photo','concept_render','unknown'), label+': image_kind required')
        if t.get('source_role') == 'semantic_member':
            need(bool(t.get('semantic_parent_ids')), label+': semantic parent ids required')
        path=ref(t.get('original_ref'), label+' original_ref')
        if path:
            digest=sha(path)
            need(digest not in seen['sha256'], label+': duplicate original image bytes')
            seen['sha256'].add(digest)
            try:
                from PIL import Image
                with Image.open(path) as im: im.verify()
            except Exception as e: errors.append(label+': unreadable image '+str(e))
        try: rectangle(t.get('rectangle'))
        except ValueError as e: errors.append(label+': '+str(e))
        observations = t.get('observations', [])
        need(isinstance(observations,list) and bool(observations), label+': visible observations required')
        for obs in observations:
            need(all(isinstance(obs.get(k),str) and obs[k].strip() for k in ('dimension','location','visible_evidence')), label+': incomplete observation')
        # No arbitrary dimension-count threshold: meaning and independence require real review.
        if t.get('actual_image_read_ref'):
            ref(t['actual_image_read_ref'], label+' actual_image_read_ref')
        else: findings.append(label+': actual_image_read_record_missing')
        if t.get('DNA_ref'): ref(t['DNA_ref'], label+' DNA_ref')
        else: need(bool(t.get('analysis_status')), label+': analysis_status required when no DNA ref')
        state=t.get('runway_status','unknown')
        need(state in ('runway','not_runway','unknown'), label+': invalid runway status')
        runway_known += state == 'runway'
        runway_unknown += state == 'unknown'
    cap=b.get('source_policy',{}).get('runway_max_fraction')
    if cap is not None:
        cap_valid=type(cap) in (int,float) and math.isfinite(cap) and 0 <= cap <= 1
        need(cap_valid and bool(b['source_policy'].get('runway_policy_basis')), 'runway cap needs valid fraction and current basis')
        if cap_valid and runway_known > cap*len(tiles): findings.append('runway_limit_exceeded')
        elif cap_valid and runway_known+runway_unknown > cap*len(tiles): findings.append('runway_unknown_upper_bound_exceeds_limit')
    native=b.get('native_status',{})
    for key in ('H01','H2'):
        need(key in native, 'native_status.'+key+' must be explicit')
        if native.get(key) == 'executed': ref(b.get('native_'+key+'_ref'), 'native_'+key+'_ref')
        else: need(native.get(key) in ('not_executed','pending','failed'), 'invalid native status')
    return {'schema_version':'prism.style-board-check.v4','board_sha256':sha(board_path),
            'machine_contract_valid':not errors,'mechanical_requirements_met':not errors and not findings,
            'errors':errors,'findings':findings,'tile_count':len(tiles),'known_project_count':len(seen['project_id']),
            'unique_original_bytes':len(seen['sha256']),'runway_known':runway_known,'runway_unknown':runway_unknown,
            'new_model_calls':0,'new_visual_review_performed':False,'semantic_review_performed':False,
            'aesthetic_pass_awarded':False,'human_approval_verified':False,
            'warning':'File checks cannot prove semantic correctness, independent projects, visual coherence or actual reading.'}

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();out=Path(a.out)
    if out.exists(): raise SystemExit('Output exists; keep the earlier check and choose a new path.')
    result=verify(a.board);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['machine_contract_valid'] else 2)
