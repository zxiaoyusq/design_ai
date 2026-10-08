"""确定性的本地DNA关系预分组；只决定看图优先级，不授予视觉/品质通过。

输入仅使用本方向语义命中的原索引。字段覆盖是后续看图的证据线索，
不是条件已经成立；跨位置事实不得拼成同一表面关系，未知事实不参与排序。
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Any

VERSION = 'matched-dna-relations-priority-v3'
UNKNOWN = {'unknown', '未知', '不确定', '无法判断', '不适用', ''}
# 每项对应冻结primary的证据种类代理；真实物件/范围/程度仍由独立看图确认。
PRIMARY_FIELDS = {
    'H001': [('COL',), ('COL', 'REL'), ('COL', 'OPT')],
    'H002': [('TEX',), ('TEX', 'REL'), ('TEX',)],
    'H003': [('GEO',), ('REL',), ('GEO', 'REL')],
    'H004': [('TEX',), ('TEX', 'REL'), ('COL', 'TEX')],
    'H006': [('TXT',), ('TXT', 'REL'), ('TXT',)],
    'H007': [('COL',), ('COL', 'REL'), ('COL', 'REL')],
    'H008': [('GEO',), ('REL',), ('REL',)],
    'H012': [('OPT',), ('OPT', 'REL', 'COL'), ('OPT', 'TEX')],
    'H013': [('COL',), ('COL', 'OPT'), ('COL', 'REL')],
    'H015': [('GEO', 'REL'), ('GEO',), ('GEO', 'REL')],
    'H016': [('GEO', 'REL'), ('REL',), ('REL', 'GEO')],
    'H017': [('GEO',), ('GEO', 'REL'), ('GEO', 'REL')],
    'H019': [('GEO',), ('GEO', 'REL'), ('GEO', 'REL')],
}
CORE_FIELDS = {
    'H001': ('COL', 'REL'), 'H002': ('TEX', 'REL'), 'H003': ('GEO', 'REL'),
    'H004': ('TEX', 'REL'), 'H006': ('TXT', 'REL'), 'H007': ('COL', 'REL'),
    'H008': ('GEO', 'REL'), 'H012': ('OPT', 'TEX'), 'H013': ('COL', 'REL'),
    'H015': ('GEO', 'REL'), 'H016': ('GEO', 'REL'), 'H017': ('GEO', 'REL'), 'H019': ('GEO', 'REL'),
}
# 仅归并已出现的值变体，不凭物件名称或主题标签添DNA。
VALUE_VARIANTS = (
    ('irregular', ('不规则', '非规则')),
    ('nonuniform', ('不均匀', '非均匀')),
    ('nonparallel', ('不平行', '非平行')),
    ('low_reflection', ('哑光', '亚光', '低光泽', '低反光', '低反射', '磨砂')),
    ('wide_diffuse_highlight', ('宽散', '漫反射', '柔散', '柔和高光', '宽阔高光')),
    ('linear_unit', ('线性', '条纹', '线条', '线状', '平行线', '细条')),
    ('ordered_repeat', ('平移重复', '规则', '统一', '均匀', '等距', '有序')),
    ('single_direction', ('单向', '平行')),
    ('bounded_region', ('分区', '局部', '边缘', '窄带')),
    ('tapered_middle', ('中部收束', '收腰', '腰部收束')),
    ('straight_boundary', ('直线', '方正', '矩形')),
    ('sparse', ('稀疏', '疏排', '疏散', '留白')),
)

# 原R5枚举按完整字段/完整值归并；不从物件标题猜关系，不合并有相反含义的值。
EXACT_RELATIONS = {
    'REL-014': {'连接':'connected', '邻接':'adjacent', '嵌套':'nested', '穿插':'interwoven', '分离':'separated'},
    'REL-015': {'主体':'dominant', '辅助':'subordinate', '点缀':'accent'},
    'REL-020': {'近似':'similar', '明暗差异':'lightness_contrast', '色相差异':'hue_contrast'},
    'REL-022': {'相似':'similar', '大小对比':'size_contrast', '粗细对比':'thickness_contrast'},
    'REL-021': {'硬分界':'hard_boundary', '层叠':'layered', '覆盖':'covered'},
    'REL-008': {'近似对称':'near_symmetry', '对称':'symmetry'},
    'REL-009': {'阵列':'array', '镜像':'mirrored', '路径分布':'path_distribution'},
    'REL-011': {'沿外轮廓':'along_outline'},
    'GEO-002': {'闭合':'closed_outline', '开放':'open_outline'},
    'GEO-020': {'弯折':'bent', '褶皱':'folded_surface', '垂坠':'draped'},
    'GEO-011': {'分段变化':'segmented_profile'},
    'GEO-001': {'自由曲线':'free_curve', '复合路径':'compound_path'},
    'TXT-001': {'文字':'text_mark'}, 'TXT-004': {'无衬线':'sans_serif', '衬线':'serif', '手写':'handwritten'},
    'COL-013': {'渐变':'gradient', '斑驳':'mottled'},
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _field_value(fact: dict) -> tuple[str, Any]:
    pv = fact.get('pv')
    if isinstance(pv, dict):
        return str(pv.get('p', pv.get('field', ''))), pv.get('v', pv.get('value'))
    if isinstance(pv, (list, tuple)) and len(pv) == 2:
        return str(pv[0]), pv[1]
    return str(fact.get('p', fact.get('field', ''))), fact.get('v', fact.get('value'))


def _blocked(value: Any):
    if isinstance(value, dict):
        p, _ = _field_value(value)
        if p:
            yield p, value.get('at')
        for child in value.values():
            yield from _blocked(child)
    elif isinstance(value, list):
        for child in value:
            yield from _blocked(child)


def matched_facts(candidate: dict) -> tuple[list[dict], list[dict]]:
    """保留原索引和位置；越界、冲突、pending/invalid不能提高候选优先级。"""
    indices = set(candidate.get('semantic_match', {}).get('observation_indices', []))
    blocked = set(_blocked(candidate.get('pending', []))) | set(_blocked(candidate.get('invalid', [])))
    variants = defaultdict(set)
    pending = []
    for location in candidate.get('matched_locations', []):
        for fact in location.get('features', []):
            index = fact.get('original_local_feature_index', fact.get('index'))
            if type(index) is not int or index not in indices:
                continue
            p, value = _field_value(fact)
            at = fact.get('at', location.get('at'))
            row = {'index': index, 'p': p, 'v': value, 'at': at, 'path': fact.get('path'), 'source': fact.get('source')}
            variants[(p, at)].add(_canonical(value))
            pending.append(row)
    usable, excluded, seen = [], [], set()
    for row in pending:
        p, at, value = row['p'], row['at'], row['v']
        values = value if isinstance(value, list) else [value]
        reason = None
        if not p or not isinstance(at, str) or not at:
            reason = 'missing_field_or_original_location'
        elif value is None or any(isinstance(v, str) and v.strip().lower() in UNKNOWN for v in values):
            reason = 'unknown_value'
        elif (p, at) in blocked or (p, None) in blocked:
            reason = 'pending_or_invalid'
        elif len(variants[(p, at)]) > 1:
            reason = 'conflicting_values_at_same_location'
        if reason:
            excluded.append({**row, 'reason': reason})
        elif row['index'] not in seen:
            usable.append(row);seen.add(row['index'])
    return sorted(usable, key=lambda row: row['index']), excluded


def relation_value(fact: dict) -> str:
    """复合、否定及相反关系保留原值，禁止首个子串命中把负证归成正关系。"""
    if not isinstance(fact['v'], str):
        return _canonical(fact['v'])
    value = re.sub(r'\s+', '', fact['v']).lower()
    if value in EXACT_RELATIONS.get(fact['p'], {}):
        return EXACT_RELATIONS[fact['p']][value]
    if fact['p'].startswith('TEX') and value == '线':
        return 'linear_unit'
    if re.search(r'不|非|无|未|混|同时|与|和|、|/|，|,|;|；|及|\+', value):
        return value
    matched = {normalized for normalized, aliases in VALUE_VARIANTS if any(alias in value for alias in aliases)}
    return next(iter(matched)) if len(matched) == 1 else value


def candidate_profile(family: dict, candidate: dict, quality: dict | None = None) -> dict:
    """字段覆盖只作解释性代理，明确不等于primary已满足。"""
    did = family['direction_id'];facts, excluded = matched_facts(candidate)
    match = candidate['semantic_match']
    locations = defaultdict(list)
    for fact in facts:
        locations[fact['at']].append(fact)
    core = CORE_FIELDS.get(did, ('GEO', 'REL', 'COL', 'TEX', 'OPT', 'TXT'))
    relations = []
    for at, at_facts in sorted(locations.items()):
        chosen = [f for f in at_facts if f['p'].split('-')[0] in core]
        terms = sorted({(f['p'], relation_value(f)) for f in chosen})
        if terms:
            relations.append({'at': at, 'terms': [list(t) for t in terms], 'original_terms': sorted([[f['p'], f['v']] for f in chosen], key=_canonical), 'observation_indices': [f['index'] for f in chosen]})
    # 最完整的同位置关系作本地簇锚点；其他表面单独列出，绝不拼接为同一表面。
    anchor = max(relations, key=lambda row: (len(row['terms']), _canonical(row['terms'])), default={'terms': [], 'original_terms': [], 'at': None, 'observation_indices': []})
    # 粗簇只表示同位置已知关系线索，原值组合保留为子组，避免exact签名使全部变单例。
    # 没有可安全归一的关系值时仅按字段种类分桶，不声称成员视觉风格相同。
    normalized_names = {row[0] for row in VALUE_VARIANTS} | {name for table in EXACT_RELATIONS.values() for name in table.values()}
    relation_hints = sorted({value for _,value in anchor['terms'] if value in normalized_names})
    field_hints = sorted({p.split('-')[0] for p,_ in anchor['terms']})
    signature = {'direction_id': did, 'same_location_field_families': field_hints,
        'safe_relation_hints': relation_hints, 'basis': 'relation_hints' if relation_hints else 'field_structure_only'}
    cluster_id = did + '-' + hashlib.sha256(_canonical(signature).encode()).hexdigest()[:12]
    variant_id = hashlib.sha256(_canonical(anchor['original_terms']).encode()).hexdigest()[:12]
    coverage_facts = [fact for fact in facts if fact['at'] == anchor['at']] if family.get('branch') == 'CMF' and did != 'H007' else facts
    primary = []
    hints = PRIMARY_FIELDS.get(did, [])
    for index, question in enumerate(family.get('primary_questions', [])):
        prefixes = hints[index] if index < len(hints) else CORE_FIELDS.get(did, ('GEO', 'REL', 'COL', 'TEX', 'OPT', 'TXT'))
        support = [f for f in coverage_facts if f['p'].split('-')[0] in prefixes]
        present = {f['p'].split('-')[0] for f in support}
        primary.append({'question_index': index, 'question': question, 'expected_field_families': list(prefixes),
            'present_field_families': sorted(present), 'observation_indices': [f['index'] for f in support],
            'field_family_coverage': len(present) / len(prefixes), 'visual_condition_verified': False, 'coverage_at': anchor['at'] if family.get('branch') == 'CMF' and did != 'H007' else None, 'coverage_alignment': 'same_anchor_location' if family.get('branch') == 'CMF' and did != 'H007' else 'cross_location_proxy_requires_object_or_pair_review'})
    known = set(f['index'] for f in facts)
    reliable = bool(quality and quality.get('provenance_verified') is True and quality.get('image_sha256') == candidate['image_sha256']
                    and known and known <= set(quality.get('target_observation_indices', [])))
    q = quality.get('quality', {}) if reliable else {}
    quality_rank = (2 if q.get('design_reference') is True and q.get('veto') == 'none' and q.get('signal_level') == 'clear'
                    else 1 if q.get('design_reference') is True and q.get('veto') == 'none' else -1 if reliable else 0)
    coverage = sum(row['field_family_coverage'] for row in primary)
    score = [1 if match.get('state') == 'candidate' else 0, round(coverage, 6),
             sum(len(r['terms']) >= 2 for r in relations), {'strong': 2, 'plausible': 1}.get(match.get('relation_strength'), 0),
             len({(f['p'], _canonical(f['v'])) for f in facts}), quality_rank]
    return {'candidate_id': candidate['candidate_id'], 'image_sha256': candidate['image_sha256'],
        'source_group_ids': candidate.get('source_group_ids', []), 'cluster_id': cluster_id,
        'cluster_relation': signature, 'variant_id': variant_id, 'same_location_original_terms': anchor['original_terms'], 'anchor_at': anchor['at'], 'relation_variants': relations,
        'semantic_state': match.get('state'), 'relation_strength': match.get('relation_strength'),
        'family_relation': match.get('family_relation'), 'score_components': score,
        'primary_evidence_hints': primary, 'usable_observation_indices': sorted(known), 'excluded_observations': excluded,
        'quality_provenance_used': reliable, 'quality_rank': quality_rank,
        'explanation': ['先candidate后uncertain', '逐primary仅统计原字段族覆盖，不代表条件通过',
            '同at字段/值关系优先，变体保留', '已绑定同图同目标的品质只影响排序' if reliable else '无可复用同目标品质，不猜测品质'],
        'visual_pass_claimed': False}


def prioritize_candidates(family: dict, candidates: list[dict], quality_by_candidate: dict | None = None) -> dict:
    """完整返回队列；相同原图去重留别名，来源变体延后而不冒称不匹配。"""
    quality_by_candidate = quality_by_candidate or {}
    profiles = [candidate_profile(family, row, quality_by_candidate.get(row['candidate_id'])) for row in candidates]
    profiles.sort(key=lambda row: (tuple(-x for x in row['score_components']), row['candidate_id']))
    unique, duplicate_images, seen_images = [], [], {}
    for row in profiles:
        if row['image_sha256'] in seen_images:
            duplicate_images.append({'candidate_id': row['candidate_id'], 'same_image_representative': seen_images[row['image_sha256']]})
        else:
            unique.append(row);seen_images[row['image_sha256']] = row['candidate_id']
    ordered = []
    for state in ('candidate', 'uncertain'):
        groups = defaultdict(list)
        for row in unique:
            if row['semantic_state'] == state:
                groups[row['cluster_id']].append(row)
        for key, rows in groups.items():
            subgroups = defaultdict(list)
            for row in rows: subgroups[row['variant_id']].append(row)
            variant_order = sorted(subgroups, key=lambda value: (tuple(-x for x in subgroups[value][0]['score_components']), value))
            groups[key] = [subgroups[value][depth] for depth in range(max(len(v) for v in subgroups.values()))
                           for value in variant_order if depth < len(subgroups[value])]
        cluster_order = sorted(groups, key=lambda key: (tuple(-v for v in groups[key][0]['score_components']), key))
        interleaved = [groups[key][depth] for depth in range(max((len(v) for v in groups.values()), default=0))
                       for key in cluster_order if depth < len(groups[key])]
        sources, representatives, alternatives = set(), [], []
        for row in interleaved:
            keys = set(row['source_group_ids']) or {'image:' + row['image_sha256']}
            if keys & sources:
                row['selection_role'] = 'same_source_alternative';alternatives.append(row)
            else:
                row['selection_role'] = 'independent_source_representative';representatives.append(row);sources.update(keys)
        ordered.extend(representatives + alternatives)
    for rank, row in enumerate(ordered, 1): row['priority_rank'] = rank
    clusters = defaultdict(list);variants = defaultdict(lambda: defaultdict(list))
    for row in ordered:
        clusters[row['cluster_id']].append(row['candidate_id'])
        variants[row['cluster_id']][row['variant_id']].append(row['candidate_id'])
    return {'version': VERSION, 'direction_id': family['direction_id'], 'input_count': len(candidates),
        'ordered_candidate_ids': [r['candidate_id'] for r in ordered], 'candidates': ordered,
        'clusters': [{'cluster_id': key, 'candidate_ids': ids, 'representative_candidate_id': ids[0], 'variant_subgroups': [{'variant_id': variant, 'candidate_ids': cids} for variant,cids in sorted(variants[key].items())]} for key, ids in sorted(clusters.items())],
        'duplicate_images': duplicate_images, 'total_candidate_cap': None, 'visual_pass_claimed': False, 'local_preselection_only': True,
        'cluster_statistics': {'count': len(clusters), 'maximum_size': max((len(v) for v in clusters.values()), default=0), 'singleton_count': sum(len(v) == 1 for v in clusters.values()), 'singleton_ratio': sum(len(v) == 1 for v in clusters.values()) / max(1, len(clusters))},
        'limitations': ['本地字段关系是看图排序依据，不是视觉家族判定。', 'primary证据覆盖是字段族代理，物件/位置/程度须实际看图。',
                       '其他对象、未知和pending/invalid不能补全本方向正证。', '同源变体仍保留，只有原图SHA完全相同才去重。']}
