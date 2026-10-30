"""Semantic H01 contracts and attributable direction selection.

No model transport is present. Semantic proposals and designer choices are
external, attributable inputs. Validation here is structural/provenance-level,
not an independent judgment of semantic truth or designer identity.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re

VERSION = 'prism.semantic-first-dual-h02.v2'
BRANCHES = {'ID', 'CMF'}


class ContractError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ContractError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def seal(value):
    value = deepcopy(value)
    value['digest'] = digest(value)
    return value


def verify(value):
    payload = {k: v for k, v in value.items() if k != 'digest'}
    need(value.get('digest') == digest(payload), 'Artifact changed after binding')
    return payload


def unique(rows, field):
    need(isinstance(rows, list), field + ' collection must be an array')
    out = {}
    for row in rows:
        key = row.get(field)
        need(isinstance(key, str) and key and key not in out, 'Invalid/duplicate ' + field)
        out[key] = row
    return out


def prepare_h01(brief, trend_semantics, research_semantics, asset_catalog, *, dataset_mode='real_or_public'):
    """Prepare text-only clustering inputs. Asset metadata never reaches the model."""
    need(dataset_mode in {'real_or_public', 'synthetic_fixture'}, 'Unknown dataset mode')
    need(brief.get('brief_id') and brief.get('design_question'), 'Brief identity and question required')
    need(trend_semantics and research_semantics, 'Both semantic lanes are required')
    assets = unique(asset_catalog, 'image_id')
    for item in assets.values():
        need(bool(re.fullmatch('[0-9a-f]{64}', item.get('sha256', ''))), 'Invalid image hash')
        need(item.get('source_kind') in {'trend', 'research', 'calibration', 'generated', 'synthetic', 'unknown'}, 'Invalid source kind')
        need(item.get('source_id') and item.get('source_group'), 'Source identity/group required')
    lanes = {}
    all_ids = set()
    for side, rows in [('trend', trend_semantics), ('research', research_semantics)]:
        unique(rows, 'evidence_id')
        lanes[side] = []
        for row in rows:
            need(not (set(row) - {'evidence_id', 'text', 'source_id', 'source_group', 'evidence_kind', 'image_refs', 'user_ids'}),
                 'H01 accepts semantic text and provenance, not image features/DNA')
            need(row['evidence_id'] not in all_ids, 'Evidence IDs must be unique across lanes')
            all_ids.add(row['evidence_id'])
            need(isinstance(row.get('text'), str) and row['text'].strip(), 'Semantic text required')
            need(row.get('source_id') and row.get('source_group') and row.get('evidence_kind'), 'Semantic provenance required')
            for image_id in row.get('image_refs', []):
                need(image_id in assets, 'Unknown image reference')
                need(assets[image_id]['source_id'] == row['source_id'], 'Image/source relation mismatch')
                if side == 'trend':
                    need(assets[image_id]['source_kind'] == 'trend', 'Trend case images must retain trend provenance')
            lanes[side].append(deepcopy(row))
    # Explicit text-only transport projection; no local paths, pixels or visual fields.
    model_input = {'brief': {'brief_id': brief['brief_id'], 'design_question': brief['design_question'],
                            'scope': brief.get('scope', '')}, 'trend_semantics': [], 'research_semantics': []}
    for side in lanes:
        model_input[side + '_semantics'] = [{k: v for k, v in row.items() if k != 'image_refs'} for row in lanes[side]]
    return seal({'schema_version': VERSION, 'stage': 'H01_semantic', 'dataset_mode': dataset_mode,
                 'brief': deepcopy(brief), 'lanes': lanes, 'asset_catalog': deepcopy(asset_catalog),
                 'model_input': model_input, 'model_modalities': ['text'],
                 'instructions': '分别聚类趋势语义与用研报告语义，再提出带双侧依据的候选方向；不得调用图片DNA或高级感作为本阶段前提。',
                 'DNA_jobs_before_selection': 0, 'quality_jobs_before_selection': 0})


def accept_candidates(prepared, proposal):
    verify(prepared)
    need(proposal.get('prepared_digest') == prepared['digest'], 'Proposal uses a stale semantic snapshot')
    evidence = {side: unique(rows, 'evidence_id') for side, rows in prepared['lanes'].items()}
    clusters = {}
    for side in ['trend', 'research']:
        clusters[side] = unique(proposal.get(side + '_clusters', []), 'cluster_id')
        for row in clusters[side].values():
            need(row.get('label') and row.get('evidence_refs'), 'Cluster label/evidence required')
            need(set(row['evidence_refs']) <= evidence[side].keys(), 'Cross-lane/unknown cluster evidence')
    directions = unique(proposal.get('directions', []), 'direction_id')
    compiled = []
    for direction in directions.values():
        need(direction.get('title') and direction.get('design_question'), 'Specific design direction required')
        need(direction.get('alignment_state') in {'overlap_candidate', 'extension_hypothesis', 'conflict', 'insufficient'},
             'Semantic similarity does not confer confirmed support')
        image_ids, refs = set(), {'trend': set(), 'research': set()}
        for side in ['trend', 'research']:
            ids = direction.get(side + '_cluster_ids', [])
            need(ids and set(ids) <= clusters[side].keys(), 'Direction needs valid clusters on both sides')
            for cluster_id in ids:
                refs[side].update(clusters[side][cluster_id]['evidence_refs'])
        for evidence_id in refs['trend']:
            image_ids.update(evidence['trend'][evidence_id].get('image_refs', []))
        # Article-linked images are an unparsed pool, never a visual clustering result.
        compiled.append({**deepcopy(direction), 'trend_evidence_refs': sorted(refs['trend']),
                         'research_evidence_refs': sorted(refs['research']),
                         'candidate_image_ids': sorted(image_ids),
                         'image_association_basis': 'source_relation_only_visual_relevance_unchecked',
                         'semantic_truth_verified': False, 'status': 'candidate_for_designer_selection'})
    return seal({'schema_version': VERSION, 'stage': 'H01_candidates', 'prepared_digest': prepared['digest'],
                 'dataset_mode': prepared['dataset_mode'], 'proposal': deepcopy(proposal), 'directions': compiled})


def select_directions(prepared, candidates, selection, confirmation):
    verify(prepared)
    verify(candidates)
    need(candidates['prepared_digest'] == prepared['digest'], 'Candidates use a stale input')
    need(confirmation.get('candidate_digest') == candidates['digest'], 'Confirmation uses a stale candidate list')
    need(confirmation.get('status') == 'confirmed' and confirmation.get('actor_id') and confirmation.get('source_ref'),
         'An actual attributable selection is required')
    actor = confirmation.get('actor_kind')
    need(actor in {'human_designer', 'user_delegated_ai', 'synthetic_fixture'}, 'Unknown confirmation actor')
    if actor == 'synthetic_fixture':
        need(prepared['dataset_mode'] == 'synthetic_fixture', 'Synthetic choices cannot authorize real data')
    if actor == 'user_delegated_ai':
        need(confirmation.get('current_scope_delegation_ref'), 'Historical AI delegation is not transferable')
    chosen = unique(selection, 'direction_id')
    available = unique(candidates['directions'], 'direction_id')
    need(chosen and chosen.keys() <= available.keys(), 'Select explicit existing directions')
    for row in chosen.values():
        branches = row.get('branches', [])
        need(branches and len(set(branches)) == len(branches) and set(branches) <= BRANCHES, 'Choose ID and/or CMF explicitly')
    need(confirmation.get('selection_digest') == digest(selection), 'Confirmation is not bound to the selected routes')
    return seal({'schema_version': VERSION, 'stage': 'designer_selection', 'prepared_digest': prepared['digest'],
                 'candidate_digest': candidates['digest'], 'selection': deepcopy(selection),
                 'confirmation': deepcopy(confirmation), 'identity_authentication': 'trusted_caller_responsibility'})

