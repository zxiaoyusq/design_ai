"""按原图 SHA 差集创建独立人工审核集合；只读原图，不调用模型。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import os

from PIL import Image


COLLECTION_ID = 'dna-cluster-remaining2224-20261011'
SAMPLE = 'data/result/dna_cluster_moodboard/sample1600_balanced_llm_20261010/sample.json'


def file_hash(path):
    """分块核验原字节，避免同时载入整个图片集合。"""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare(root):
    """只创建不存在的目录；已有审核状态必须原样保留。"""
    root = root.resolve()
    target = root / 'data/result/trend_quality/manual_review' / COLLECTION_ID
    if target.exists():
        raise FileExistsError(f'集合已存在，拒绝覆盖或重置人工状态：{target}')
    sample_path = root / SAMPLE
    sample = json.loads(sample_path.read_text())
    pool_path = Path(sample['pool_ref']['path'])
    if not pool_path.is_absolute():
        pool_path = root / pool_path
    pool_hash = file_hash(pool_path)
    if pool_hash != sample['pool_ref']['sha256']:
        raise ValueError('sample.pool_ref 的原始文件 SHA 不匹配')
    pool = json.loads(pool_path.read_text())
    pool_ids = [item['sha256'] for item in pool['images']]
    selected_ids = [item['sha256'] for item in sample['images']]
    assert len(pool_ids) == len(set(pool_ids)) == 3824
    assert len(selected_ids) == len(set(selected_ids)) == 1600
    selected = set(selected_ids)
    assert selected <= set(pool_ids)
    remaining = [item for item in pool['images'] if item['sha256'] not in selected]
    remaining_ids = {item['sha256'] for item in remaining}
    assert len(remaining_ids) == 2224
    assert not remaining_ids & selected
    assert remaining_ids | selected == set(pool_ids)
    created = datetime.now(timezone.utc).isoformat()
    sample_ref = {'path': str(sample_path.relative_to(root)), 'sha256': file_hash(sample_path)}
    pool_ref = {'path': str(pool_path.relative_to(root)), 'sha256': pool_hash}
    images, verified = [], []
    alias_count = total_bytes = 0
    for item in remaining:
        path = Path(item['local_path'])
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_relative_to(root / 'data/trend_data/images') or not path.is_file():
            raise FileNotFoundError(f'原图缺失或路径越界：{path}')
        digest = file_hash(path)
        if digest != item['sha256']:
            raise ValueError(f'原图 SHA 不匹配：{path}')
        relative = str(path.relative_to(root))
        size = path.stat().st_size
        total_bytes += size
        verified.append({'sha256': digest, 'source_path': relative, 'size_bytes': size})
        aliases, sources = deepcopy(item['aliases']), deepcopy(item['sources'])
        alias_count += len(aliases)
        metadata = next((a.get('image_metadata', {}) for a in aliases
                         if a.get('image_metadata', {}).get('width') and a.get('image_metadata', {}).get('height')), {})
        width, height = metadata.get('width'), metadata.get('height')
        if not width or not height:
            with Image.open(path) as original:
                width, height = original.size
        directions = {}
        for source in sources:
            for membership in source.get('all_direction_membership', []):
                key = membership['direction_id']
                directions[key] = {'id': key, 'title': membership.get('title') or key}
        for key in [*item.get('direction_ids', []), *(d for a in aliases for d in a.get('direction_ids', [])),
                    *(d for s in sources for d in s.get('direction_ids', []))]:
            directions.setdefault(key, {'id': key, 'title': key})
        articles = {s['article_id']: {'id': s['article_id'], 'title': s.get('title') or s['article_id'],
                                    'url': s.get('article_url')} for s in sources}
        references = []
        for alias in aliases:
            article = articles.setdefault(alias['article_id'], {'id': alias['article_id'],
                'title': alias['article_id'], 'url': alias.get('article_url')})
            references.append(dict(alias, article_title=article['title'],
                directions=[{'direction_id': key, 'direction_title': directions[key]['title']}
                            for key in alias.get('direction_ids', [])]))
        images.append({'id': digest, 'image_id': item['image_id'],
            'image_ids': list(dict.fromkeys([item['image_id'], *(a['image_id'] for a in aliases)])),
            'source_path': relative, 'snapshot_path': relative, 'input_image_sha256': digest,
            'width': width, 'height': height, 'batch': 'remaining_after_sample1600_20261010',
            'article_title': next(iter(articles.values()))['title'], 'articles': list(articles.values()),
            'directions': list(directions.values()), 'references': references,
            'aliases': aliases, 'sources': sources, 'original_image_url': item.get('image_url'),
            'model': '', 'model_decision': None, 'model_category': 'REVIEW',
            'model_status': 'not_evaluated_for_this_manual_collection', 'model_error': None,
            'prompt_version': '', 'prompt_sha256': '', 'model_finished_at': None,
            'model_record_path': '', 'model_record_sha256': ''})
    scope = {'pool_ref': pool_ref, 'sample_ref': sample_ref, 'pool_unique_images': 3824,
        'selected_unique_images': 1600, 'remaining_unique_images': 2224,
        'difference_rule': 'pool SHA256 minus every sample SHA256, irrespective of DNA status',
        'selected_overlap': 0, 'union_equals_pool': True,
        'byte_verification': {'verified_unique_images': len(verified), 'missing': [], 'sha_mismatch': [],
                              'total_original_bytes': total_bytes}}
    # 在完整核验成功后一次发布目录，异常不留下半成品，也不会覆盖既有目录。
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.remaining-review-', dir=target.parent) as temporary:
        staging = Path(temporary) / COLLECTION_ID
        staging.mkdir()
        catalog = {'schema_version': 'prism.quality_manual_catalog.v1', 'collection_id': COLLECTION_ID,
            'title': '剩余 2,224 张原图 · 人工审核', 'created_at': created,
            'source_batches': [], 'source_scope': scope, 'images': images}
        write_json(staging / 'catalog.json', catalog)
        catalog_hash = file_hash(staging / 'catalog.json')
        write_json(staging / 'selections.json', {'schema_version': 'prism.quality_manual_selection.v1',
            'collection_id': COLLECTION_ID, 'catalog_sha256': catalog_hash, 'revision': 1,
            'updated_at': created, 'labels': {}, 'history': []})
        write_json(staging / 'remaining-scope.json', dict(scope,
            schema_version='prism.remaining_review_scope.v1', collection_id=COLLECTION_ID,
            selected_hashes=selected_ids, excluded_hashes=selected_ids,
            remaining_hashes=[item['sha256'] for item in remaining], pool_hashes=pool_ids))
        write_json(staging / 'prepare-audit.json', {'schema_version': 'prism.remaining_review_prepare_audit.v1',
            'collection_id': COLLECTION_ID, 'created_at': created, 'source_scope': scope,
            'catalog_sha256': catalog_hash, 'remaining_alias_count': alias_count,
            'pool_alias_count': sum(len(i['aliases']) for i in pool['images']),
            'selected_alias_count': sum(len(i['aliases']) for i in pool['images'] if i['sha256'] in selected),
            'total_original_bytes': total_bytes, 'verified_original_files': verified,
            'model_calls': 0, 'original_files_modified': False, 'initial_manual_labels': 0})
        if target.exists():
            raise FileExistsError(f'发布时集合已存在，拒绝覆盖：{target}')
        os.rename(staging, target)
    return {'directory': str(target), 'catalog_sha256': catalog_hash,
            'count': len(images), 'aliases': alias_count, 'total_original_bytes': total_bytes,
            'selected_overlap': 0, 'missing': [], 'sha_mismatch': []}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    print(json.dumps(prepare(parser.parse_args().root), ensure_ascii=False))
