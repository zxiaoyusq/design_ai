"""H007多物件逐表面复核的显式本地合同；无模型执行、无旧回执升级。

仅替代CMF两条“整体必须同一表面/物件”断言，其余原链必须先通过。
R5没有独立object_id时，模型对象标签只能绑定原at/indices，不能伪造原DNA对象ID。
"""
from __future__ import annotations

from typing import Callable

POLICY = 'h007-independently-bound-paired-surfaces-v2'
REPLACED_ERRORS = {'branch_target_not_readable', 'CMF_same_surface_or_object_not_confirmed'}

PAIRED_VIEW_PROMPT = '''你是H007的独立原图与实际DOM视窗审阅者。本请求采用h007-independently-bound-paired-surfaces-v2。
只检查本次原图original与实际视窗actual_view及已选目标上的原R5可用观察；不调用工具，不改DNA，不复用旧肯定结论。
本合同只适用于已经选定的同图多个物件之各自表面。每表面独立绑定，不要求整个物件轮廓齐全；不得把两件物体改登记为同表面或同物件interface。same_surface_or_object应如实为false，whole_object_readable如实报告；这些false不由宿主改写。
每个surface_binding只对应一个原dna_at和dna_source，indices仅用已选原索引中的单表面事实，禁止把跨物件REL伪装为单表面。原selected中的REL-*索引必须单列pair_context.observation_indices；该表只允许原可用REL且本次真实同图跨物件上下文清楚。逐REL另给relation_bindings，逐字保留dna_at/dna_source，并列已绑定的至少两个involved_object_labels与original/actual_view的实际关系可见性。表面索引与pair_context索引互斥，二者合并恰好覆盖全部selected且每索引一次；无REL时两个关系数组明确为空。object_label是你实际看图识别的物件标签，不是原DNA object_id。每物件至少一组可用COL正证。original_rectangle是该表面在原图中的归一化框，须完全位于本次当前ROI，表面在actual_view中必须真实可辨。不得为凑框把不同表面合并，不能借背景或未知/pending/invalid。
逐quality_output.evidence_ids解释其可见载体surface_ids；跨物件色彩关系可同时绑定多个surface_ids，但不能声称两物件构成真实接口。partial_target/basic仍需实际必要关系清楚，其他目标/not_visible/unreadable/unsupported不得通过。局部遮挡与细节未知必须保留。
本次只确认各表面与同图配对上下文可读；不授予用户配色接受或组板通过。U56设备同色、U52正式场合分开；U47鞋机无关，U75未纳入本方向支持统计，均不得冒充支持者。逐family.scope_limits保留限制，后续独立group还必须确认具体用户/场合/基色来源及crosspair，随后独立board看整板。仅同为深色不足。
返回一个JSON对象{"reviews":[{"candidate_id":"输入ID","comparison_contract":"h007-independently-bound-paired-surfaces-v2","quality_policy":"selected-target-visible-relations-v2","original_image_seen":true或false,"actual_view_seen":true或false,"exact_target":true或false,"view_matches_original":true或false,"observations_valid":true或false,"quality_evidence_valid":true或false,"limits_acknowledged":true或false,"whole_object_readable":true或false,"same_surface_or_object":false,"necessary_relations_visible":true或false,"necessary_relations_reason":"当前必要关系及局限","covered_evidence_ids":["真实ID"],"surface_bindings":[{"surface_id":"s1","object_label":"实际可见物件","object_identity_kind":"visible_label_bound_to_original_location","dna_at":"原at逐字","dna_source":"原source逐字","observation_indices":[原零基索引],"original_rectangle":{"x":0,"y":0,"width":1,"height":1},"original_surface_visible":true或false,"actual_view_surface_visible":true或false,"single_surface_binding":true或false,"original_facts_confirmed":true或false,"reason":"逐表面可见依据"}],"evidence_bindings":[{"evidence_id":"原品质ID","surface_ids":["s1"],"visible_on_bound_surfaces":true或false,"reason":"品质正证归属"}],"pair_context":{"observation_indices":[已选原REL索引或空],"relation_bindings":[{"observation_index":原REL零基索引,"dna_at":"原at逐字","dna_source":"原source逐字","involved_object_labels":["两个或更多已绑定物件标签"],"original_relation_visible":true或false,"actual_view_relation_visible":true或false,"reason":"同图实际关系及局限"}],"co_present_in_original":true或false,"co_visible_in_actual_view":true或false,"no_cross_object_interface_claimed":true或false,"relation_description":"同图可见关系，勿声称精确同色","group_scope_status":"requires_independent_user_context_review","user_acceptance_confirmed":false,"scope_limit_handling":[{"index":原family.scope_limits零基,"disposition":"retained_for_group_review或current_visual_limitation","reason":"如何保留限制"}]},"decision":"pass或pending或reject","reason":"具体结论","issues":["缺口"]}]}。
所有true必须来自本次实际观察；表面绑定或必要色彩/对象关系不清即pending/reject。pass仅表示逐表面与上下文可读，绝不表示group/board通过。'''

PAIR_GROUP_APPENDIX = '''H007 paired-surfaces-v2补充：逐surface独立通过仅是入围，不是配色接受。pair_review仍由你本次看所有原图+实际视窗独立裁决。
每个subgroup追加user_scope_id:"52_formal"或"56_devices"、member_surface_bindings:[{candidate_id:"...",surface_ids:["真实surface_id"]}]、accepted_base_color_evidence:[{user_id:"52或56",source_ref:{path:"原H01文件",sha256:"原SHA"},pointer:"原研究引文/约束的具体JSON指针",quote:"来源逐字短引文",acceptance_kind:"specific_base_color或relationship_only",reason:"该用户/场合接受何种基色关系及迁移边界"}]。引用只能来自family原H01对应方向的research_citations具体条目，不得用趋势图片或他人负向约束证明用户接受；只有希望同色/搭配的引用标relationship_only，不能当specific_base_color。每个成员恰属一个用户场合子组；52正式与56设备不得合并为全员配色。若无法证明对应基色已被该用户/场合接受，pair_review.decision=pending及group.decision=pending，保留gap。''' 


def _rectangle(value: dict) -> bool:
    return (isinstance(value, dict) and set(value) == {'x','y','width','height'}
            and all(type(v) in (int,float) for v in value.values())
            and 0 <= value['x'] < 1 and 0 <= value['y'] < 1
            and 0 < value['width'] <= 1 and 0 < value['height'] <= 1
            and value['x'] + value['width'] <= 1.000001 and value['y'] + value['height'] <= 1.000001)


def validate_surface_report(report: dict, target: dict, family: dict, observations: list[dict], rectangle: dict) -> dict:
    """只校验真实模型结构与原事实绑定；未调用模型的旧报告永不自动升级。"""
    errors = []
    def need(ok, error):
        if not ok: errors.append(error)
    try:
        need(family['direction_id']=='H007' and family['branch']=='CMF' and family['comparison_unit']=='surface', 'paired_policy_only_H007_CMF_surfaces')
        need(target.get('source_kind')=='trend', 'paired_trend_contract_not_research_admission')
        need(report.get('comparison_contract')==POLICY, 'new_actual_paired_contract_required')
        need(report.get('candidate_id')==target['candidate_id'], 'paired_candidate_identity_mismatch')
        need(report.get('decision')=='pass' and bool(report.get('reason')), 'paired_review_not_passed')
        need(report.get('same_surface_or_object') is False, 'multiple_objects_must_not_be_claimed_one_surface')
        need(report.get('necessary_relations_visible') is True and bool(report.get('necessary_relations_reason')), 'paired_necessary_relations_not_visible')
        selected = set(target['observation_indices']);original = {o['index']:o for o in observations}
        bindings = report.get('surface_bindings', [])
        need(isinstance(bindings,list) and len(bindings)>=2, 'at_least_two_independent_surfaces_required')
        surfaces = {};assigned = [];objects = {}
        need(_rectangle(rectangle), 'current_ROI_invalid')
        for row in bindings:
            sid=row['surface_id'];label=row['object_label'];indices=row['observation_indices'];box=row['original_rectangle']
            need(bool(sid) and sid not in surfaces, 'unique_surface_id_required');surfaces[sid]=row
            need(isinstance(label,str) and bool(label.strip()) and row.get('object_identity_kind')=='visible_label_bound_to_original_location', 'object_label_must_not_forge_DNA_object_id')
            need(isinstance(indices,list) and bool(indices) and all(type(i) is int for i in indices), 'surface_original_indices_required')
            need(all(i in selected and i in original and original[i]['usable'] for i in indices), 'surface_evidence_outside_selected_or_unusable')
            known=[original[i]['original'] for i in indices if i in original]
            need(bool(known) and all(f['at']==row.get('dna_at') and f['source']==row.get('dna_source') for f in known), 'surface_must_bind_one_original_location_and_source')
            need(all(not fact['p'].startswith('REL-') for fact in known), 'REL_context_must_not_be_disguised_as_single_surface')
            objects.setdefault(label,[]).extend(known);assigned.extend(indices)
            need(_rectangle(box), 'surface_rectangle_invalid')
            if _rectangle(box) and _rectangle(rectangle):
                need(box['x']>=rectangle['x']-1e-6 and box['y']>=rectangle['y']-1e-6
                     and box['x']+box['width']<=rectangle['x']+rectangle['width']+1e-6
                     and box['y']+box['height']<=rectangle['y']+rectangle['height']+1e-6, 'surface_outside_actual_view_ROI')
            need(all(row.get(k) is True for k in ('original_surface_visible','actual_view_surface_visible','single_surface_binding','original_facts_confirmed')) and bool(row.get('reason')), 'surface_not_independently_visible_or_confirmed')
        pair=report.get('pair_context',{})
        context_indices=pair.get('observation_indices')
        need(isinstance(context_indices,list) and all(type(i) is int for i in context_indices), 'explicit_pair_context_original_indices_required')
        context_indices=context_indices if isinstance(context_indices,list) else []
        need(all(i in selected and i in original and original[i]['usable'] and original[i]['original']['p'].startswith('REL-') for i in context_indices), 'pair_context_only_selected_usable_REL_facts')
        combined=assigned+context_indices
        need(set(combined)==selected and len(combined)==len(selected), 'surface_and_pair_indices_must_cover_selected_once_disjointly')
        relations=pair.get('relation_bindings')
        need(isinstance(relations,list), 'explicit_relation_bindings_required')
        relations=relations if isinstance(relations,list) else []
        need({row.get('observation_index') for row in relations}==set(context_indices) and len(relations)==len(context_indices), 'every_pair_REL_requires_one_actual_binding')
        for row in relations:
            index=row.get('observation_index');fact=original[index]['original'] if index in original else {}
            need(fact.get('at')==row.get('dna_at') and fact.get('source')==row.get('dna_source'), 'pair_REL_original_location_or_source_mismatch')
            labels=row.get('involved_object_labels',[])
            need(isinstance(labels,list) and len(set(labels))>=2 and set(labels)<=set(objects), 'pair_REL_requires_two_independently_bound_objects')
            need(row.get('original_relation_visible') is True and row.get('actual_view_relation_visible') is True and bool(row.get('reason')), 'pair_REL_not_actually_visible')
        need(len(objects)>=2 and all(any(f['p'].startswith('COL-') for f in facts) for facts in objects.values()), 'two_objects_each_need_selected_known_color_evidence')
        wanted=set(target['quality_output']['quality']['evidence_ids']);evidence=report.get('evidence_bindings',[])
        need({r.get('evidence_id') for r in evidence}==wanted and len(evidence)==len(wanted), 'each_quality_positive_requires_actual_surface_binding')
        covered=set()
        for row in evidence:
            ids=row.get('surface_ids',[]);covered.update(ids)
            need(bool(ids) and len(set(ids))==len(ids) and set(ids)<=set(surfaces), 'quality_bound_surface_missing')
            need(row.get('visible_on_bound_surfaces') is True and bool(row.get('reason')), 'quality_evidence_not_visible_on_bound_surfaces')
        need(covered==set(surfaces), 'every_selected_surface_requires_quality_carrier_review')
        pair=report.get('pair_context',{})
        need(all(pair.get(k) is True for k in ('co_present_in_original','co_visible_in_actual_view','no_cross_object_interface_claimed')) and bool(pair.get('relation_description')), 'actual_separate_object_pair_context_required')
        need(pair.get('group_scope_status')=='requires_independent_user_context_review' and pair.get('user_acceptance_confirmed') is False, 'surface_pass_cannot_grant_user_or_group_acceptance')
        handling=pair.get('scope_limit_handling',[])
        need({r.get('index') for r in handling}==set(range(len(family['scope_limits']))) and len(handling)==len(family['scope_limits']), 'all_original_user_scope_limits_required')
        need(all(r.get('disposition') in ('retained_for_group_review','current_visual_limitation') and bool(r.get('reason')) for r in handling), 'scope_limits_not_actually_acknowledged')
    except (KeyError,TypeError,ValueError) as exc:
        errors.append('paired_surface_structure:'+str(exc))
    return {'comparison_contract':POLICY,'valid':not errors,'errors':errors,'group_pass_claimed':False,'native_status':'not_claimed'}


def validate_paired_surface_chain(target: dict, review: dict, family: dict, *, bridge, standard_validator: Callable | None = None) -> dict:
    """复用原门，只在新真实逐表面合同完整成立时替代两条单表面断言。

    接入时standard_validator必须是重命名后的原校验函数，避免dispatch递归。
    previous_review_ref应指旧envelope的不可变快照，不可指向会被覆盖的当前target。
    """
    base=(standard_validator or bridge.validate_target_review)(target,review,family)
    errors=[e for e in base['errors'] if e not in REPLACED_ERRORS]
    try:
        prior=bridge.checked(review['previous_review_ref'])
        bridge._call(prior['call'],[target['image_ref'],target['actual_view_ref']],errors,prior)
        if prior['call']['call_id']==review['call']['call_id']:errors.append('new_independent_paired_review_required')
        if prior.get('model_report',{}).get('candidate_id')!=target['candidate_id']:errors.append('previous_review_candidate_mismatch')
        request=bridge.checked(review['call']['request_ref'])
        payload=bridge.checked(request['user_prompt_ref'])
        if payload.get('family')!=family:errors.append('paired_request_must_use_unchanged_frozen_family')
        dna=bridge.read_dna(target['dna_ref'],target['image_ref'],target.get('dna_identity_binding'))
        rectangle=bridge.current_view_rectangle(target,errors)
        surface=validate_surface_report(review.get('model_report',{}),target,family,dna['observations'],rectangle)
        errors.extend(surface['errors'])
    except (KeyError,ValueError,OSError,TypeError,IndexError) as exc:
        errors.append('paired_chain:'+str(exc))
    return {'comparison_contract':POLICY,'valid':not errors,'errors':errors,
            'standard_validation_errors_preserved':base['errors'],
            'replaced_single_surface_assertions':sorted(REPLACED_ERRORS),
            'group_pass_claimed':False,'native_status':'not_claimed'}


def validate_pair_group_scope(group_report: dict, targets: dict, family: dict, *, bridge) -> dict:
    """独立group补充门：原引文确切绑定用户/场合，不接受趋势图替代用户接受证据。"""
    errors=[]
    try:
        if family['direction_id']!='H007':raise ValueError('H007_only')
        pair=group_report['pair_review'];members=set(group_report['members']);assigned=[]
        if pair.get('decision')!='pass' or not pair.get('subgroups'):errors.append('independent_pair_group_not_passed')
        for sub in pair.get('subgroups',[]):
            scope=sub.get('user_scope_id');user={'52_formal':'52','56_devices':'56'}.get(scope)
            if not user:errors.append('unknown_or_merged_user_context')
            ids=sub['candidate_ids'];assigned.extend(ids)
            if not ids or not set(ids)<=members:errors.append('pair_subgroup_member_not_on_board')
            bindings=sub.get('member_surface_bindings',[])
            if {b.get('candidate_id') for b in bindings}!=set(ids) or len(bindings)!=len(ids):errors.append('pair_group_missing_member_surfaces')
            for binding in bindings:
                target=targets[binding['candidate_id']];report=target['independent_review']['model_report']
                known={r['surface_id'] for r in report.get('surface_bindings',[])}
                if not binding.get('surface_ids') or not set(binding['surface_ids'])<=known:errors.append('pair_group_surface_not_independently_reviewed')
            references=sub.get('accepted_base_color_evidence',[])
            if not references:errors.append('accepted_base_color_user_evidence_missing')
            for evidence in references:
                if evidence.get('user_id')!=user or evidence.get('source_ref')!=family['h01_ref']:errors.append('user_acceptance_source_identity_mismatch')
                ptr=evidence['pointer'];prefix=family['h01_pointer']
                expected_prefix=prefix+'/research_citations/'
                if not ptr.startswith(expected_prefix) or not ptr[len(expected_prefix):].isdigit():errors.append('user_evidence_pointer_requires_exact_research_citation_item')
                actual=bridge.pointer(bridge.checked(evidence['source_ref']),ptr)
                import json
                source=actual if isinstance(actual,str) else json.dumps(actual,ensure_ascii=False)
                observation=actual.get('observation',{}) if isinstance(actual,dict) else {}
                if observation.get('user_id')!=user or observation.get('stance')!='prefer':errors.append('actual_citation_does_not_support_this_user_preference')
                if evidence.get('acceptance_kind')!='specific_base_color':errors.append('relation_only_preference_cannot_prove_specific_base_color_acceptance')
                quote=evidence.get('quote')
                if not isinstance(quote,str) or not quote.strip() or quote not in source or not evidence.get('reason'):errors.append('user_acceptance_quote_not_in_actual_source')
        if set(assigned)!=members or len(assigned)!=len(members):errors.append('members_must_belong_to_one_user_context_each')
    except (KeyError,ValueError,OSError,TypeError,IndexError) as exc:
        errors.append('pair_group_scope:'+str(exc))
    return {'comparison_contract':POLICY,'valid':not errors,'errors':errors,'board_pass_claimed':False}
