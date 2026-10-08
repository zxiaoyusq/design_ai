"""趋势模型筛选结果的人工图库：冻结模型结论，独立持久化人工选择。"""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from PIL import Image, ImageOps

from app.services.high_trends.image_review import read, write_atomic, file_hash, timestamp, IMAGE_SUFFIXES

COLLECTION_ID = 'handshake-astra-20261001'
BATCHES = ('handshake_gpt6sol_first1000_20261002', 'handshake_gpt6sol_remaining7670_20261002')
MODEL_CATEGORIES = ('PASS', 'FAIL', 'REVIEW', 'ERROR')


class TrendQualityReview:
    """按原图哈希同步人工状态；分页接口不向浏览器发送整库和模型原回执。"""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = self.root / 'data/result/trend_quality/manual_review' / COLLECTION_ID
        self._lock = RLock()
        self._catalog = None
        self._by_id = {}
        self._verified_files = {}

    @contextmanager
    def _writing(self):
        """线程锁与文件锁覆盖读取版本到原子写入，防止多页面／多进程丢失选择。"""
        self.folder.mkdir(parents=True, exist_ok=True)
        with self._lock, (self.folder / 'review.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _safe_path(self, value, allowed_root):
        path = (self.root / value).resolve()
        if not path.is_relative_to(allowed_root.resolve()) or not path.is_file():
            raise FileNotFoundError('图片不在当前图库或文件已不存在')
        return path

    def prepare(self):
        """只在首次创建时导入两批已完成结果，重复打开不会重置人工选择。"""
        with self._writing():
            catalog_path = self.folder / 'catalog.json'
            if catalog_path.is_file():
                self._load()
                return self._counts(self._state())
            images, source_batches, seen = [], [], set()
            model_options = prompt_hash = source_hash = None
            batch_root = self.root / 'data/result/trend_quality/batches'
            for batch_name in BATCHES:
                folder = batch_root / batch_name
                manifest = read(folder / 'manifest.json')
                summary = read(folder / 'summary.json')
                if summary['status'] != 'completed' or summary['finished'] != len(manifest['entries']):
                    raise ValueError('模型批次尚未完成，不能冻结人工图库')
                if source_batches and (manifest['parameters'] != model_options
                        or manifest['prompt_sha256'] != prompt_hash or manifest['source_sha256'] != source_hash):
                    raise ValueError('两批来源、模型参数或提示版本不一致')
                model_options, prompt_hash, source_hash = manifest['parameters'], manifest['prompt_sha256'], manifest['source_sha256']
                source_batches.append({'id': batch_name, 'manifest_sha256': file_hash(folder / 'manifest.json'),
                                       'summary_sha256': file_hash(folder / 'summary.json'),
                                       'model': manifest['model'], 'prompt_sha256': prompt_hash,
                                       'policy_version': manifest['version'], 'parameters': model_options,
                                       'source': manifest['source'], 'source_sha256': source_hash})
                for entry in manifest['entries']:
                    digest = entry['image_sha256']
                    if digest in seen or entry.get('source_kind') != 'trend':
                        raise ValueError('批次原图重复或不属于趋势来源')
                    seen.add(digest)
                    record_path = folder / 'calls' / (entry['entry_id'] + '.json')
                    record = read(record_path)
                    if (record.get('image_sha256') != digest or record.get('prompt_sha256') != prompt_hash
                            or record.get('model') != manifest['model'] or record.get('state') != 'finished'
                            or record.get('version') != manifest['version']
                            or record.get('input_image_sha256') != entry['preprocessing']['input_image_sha256']):
                        raise ValueError('原回执身份与冻结清单不一致：' + entry['image_id'])
                    decision = record.get('decision')
                    status = record['status']
                    category = (decision if status == 'complete' and record.get('valid') is True
                                and decision in {'PASS', 'FAIL'} else 'REVIEW' if status == 'needs_review' else 'ERROR')
                    original = self._safe_path(entry['source_path'], self.root / 'data/trend_data/images')
                    snapshot = self._safe_path(str(folder / entry['snapshot']), folder / 'inputs')
                    if original.suffix.lower() not in IMAGE_SUFFIXES:
                        raise ValueError('不支持的图片格式')
                    # 旧批次将未转码GIF保存为.image；按真实格式识别，不改写冻结输入。
                    if snapshot.suffix.lower() not in IMAGE_SUFFIXES:
                        if snapshot.suffix != '.image' or entry['preprocessing']['mime_type'] != 'image/gif':
                            raise ValueError('不支持的冻结图片格式')
                        with Image.open(snapshot) as source:
                            if source.format != 'GIF':
                                raise ValueError('冻结GIF格式不一致')
                    references = deepcopy(entry['references'])
                    directions, articles, image_ids = {}, {}, []
                    for reference in references:
                        if reference['image_id'] not in image_ids:
                            image_ids.append(reference['image_id'])
                        articles[reference['article_id']] = {'id': reference['article_id'],
                            'title': reference['article_title'], 'url': reference.get('article_url')}
                        for direction in reference.get('directions', []):
                            directions[direction['direction_id']] = {'id': direction['direction_id'], 'title': direction['direction_title']}
                    pixels = entry.get('preprocessing', {}).get('original_pixels', [None, None])
                    images.append({'id': digest, 'image_id': entry['image_id'], 'image_ids': image_ids,
                                   'source_path': str(original.relative_to(self.root)),
                                   'snapshot_path': str(snapshot.relative_to(self.root)),
                                   'input_image_sha256': entry['preprocessing']['input_image_sha256'],
                                   'width': pixels[0], 'height': pixels[1], 'batch': batch_name,
                                   'article_title': references[0]['article_title'], 'articles': list(articles.values()),
                                   'directions': list(directions.values()), 'references': references,
                                   'model': record['model'], 'model_decision': decision,
                                   'model_category': category, 'model_status': status,
                                   'model_error': record.get('error') or record.get('parse_error'),
                                   'prompt_version': record['version'], 'prompt_sha256': prompt_hash,
                                   'model_finished_at': record.get('finished_at'),
                                   'model_record_path': str(record_path.relative_to(self.root)),
                                   'model_record_sha256': file_hash(record_path)})
            if len(images) != 8670:
                raise ValueError('本次握手图库应覆盖8670张去重图，当前数据范围不匹配')
            created = timestamp()
            write_atomic(catalog_path, {'schema_version': 'prism.quality_manual_catalog.v1',
                'collection_id': COLLECTION_ID, 'title': '握手趋势图片 · 人工筛选',
                'created_at': created, 'source_batches': source_batches, 'images': images})
            # 人工标签为空即未审核，模型PASS绝不能自动冒充人工通过。
            if not (self.folder / 'selections.json').is_file():
                write_atomic(self.folder / 'selections.json', {'schema_version': 'prism.quality_manual_selection.v1',
                    'collection_id': COLLECTION_ID, 'catalog_sha256': file_hash(catalog_path),
                    'revision': 1, 'updated_at': created, 'labels': {}, 'history': []})
            self._load()
            return self._counts(self._state())

    def _load(self):
        with self._lock:
            if self._catalog is None:
                self._catalog = read(self.folder / 'catalog.json')
                self._by_id = {item['id']: item for item in self._catalog['images']}
                self._catalog_hash = file_hash(self.folder / 'catalog.json')
                directions = Counter(d['id'] for image in self._catalog['images'] for d in image['directions'])
                self._directions = {d['id']: dict(d, count=directions[d['id']])
                                    for image in self._catalog['images'] for d in image['directions']}
                self._search = {image['id']: ' '.join([*image['image_ids'],
                    *(a['title'] + ' ' + a['id'] for a in image['articles']),
                    *(d['title'] + ' ' + d['id'] for d in image['directions'])]).casefold()
                    for image in self._catalog['images']}

    def _state(self):
        self._load()
        state = read(self.folder / 'selections.json')
        if state['catalog_sha256'] != self._catalog_hash:
            raise RuntimeError('图库索引已变化，不能写回旧选择')
        return state

    def _counts(self, state):
        model = Counter(image['model_category'] for image in self._catalog['images'])
        manual = Counter(value['decision'] for value in state['labels'].values())
        return {'total': len(self._by_id), 'model': {key: model[key] for key in MODEL_CATEGORIES},
                'manual': {'PASS': manual['PASS'], 'FAIL': manual['FAIL'],
                           'unreviewed': len(self._by_id) - len(state['labels'])}}

    def _public_image(self, image, state):
        result = {key: value for key, value in image.items()
                  if key not in {'references', 'snapshot_path', 'model_record_path', 'model_record_sha256', 'input_image_sha256'}}
        label = state['labels'].get(image['id'], {})
        result.update(manual_decision=label.get('decision'), manual_updated_at=label.get('updated_at'),
                      image_url=f'/api/v1/trend-quality/review/images/{image["id"]}',
                      thumbnail_url=f'/api/v1/trend-quality/review/images/{image["id"]}?thumbnail=true')
        return result

    def page(self, *, model_category='all', manual='all', direction_id='', q='', page=1, page_size=60):
        state = self._state()
        words = q.casefold().split()
        filtered = [image for image in self._catalog['images']
                    if (model_category == 'all' or image['model_category'] == model_category)
                    and (manual == 'all' or (state['labels'].get(image['id'], {}).get('decision') or 'unreviewed') == manual)
                    and (not direction_id or any(d['id'] == direction_id for d in image['directions']))
                    and all(word in self._search[image['id']] for word in words)]
        page = min(page, max(1, (len(filtered) + page_size - 1) // page_size))
        return {'collection_id': COLLECTION_ID, 'title': self._catalog['title'],
                'revision': state['revision'], 'updated_at': state['updated_at'],
                'counts': self._counts(state), 'directions': sorted(self._directions.values(), key=lambda x: x['id']),
                'filtered_count': len(filtered), 'page': page, 'page_size': page_size,
                'images': [self._public_image(image, state) for image in filtered[(page - 1) * page_size:page * page_size]]}

    def update(self, revision, image_ids, decision):
        """校验整批身份再写入；null恢复未审核，审计记录保留每图修改前后的标签。"""
        if decision not in ('PASS', 'FAIL', None):
            raise ValueError('未知人工判定')
        with self._writing():
            state = self._state()
            if state['revision'] != revision:
                raise RuntimeError('其他页面已更新选择，本次未覆盖，请刷新后重新选择')
            wanted = set(image_ids)
            if not wanted or not wanted.issubset(self._by_id):
                raise ValueError('所选图片不在当前图库')
            before = {key: state['labels'].get(key, {}).get('decision') for key in wanted
                      if state['labels'].get(key, {}).get('decision') != decision}
            updated = timestamp()
            if before:
                for key in before:
                    if decision is None:
                        state['labels'].pop(key, None)
                    else:
                        state['labels'][key] = {'decision': decision, 'updated_at': updated}
                state.update(revision=revision + 1, updated_at=updated)
                state['history'].append({'revision': state['revision'], 'updated_at': updated,
                    'decision': decision, 'previous': before, 'image_ids': sorted(before)})
                write_atomic(self.folder / 'selections.json', state)
            return {'revision': state['revision'], 'updated_at': state['updated_at'],
                    'counts': self._counts(state), 'changed': [dict(id=key,
                    manual_decision=state['labels'].get(key, {}).get('decision'),
                    manual_updated_at=state['labels'].get(key, {}).get('updated_at')) for key in sorted(wanted)]}

    def _verify_file(self, path, digest):
        """原图按文件状态缓存核验，避免图片请求重复哈希，也不展示已被换掉的原图。"""
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        with self._lock:
            if self._verified_files.get((path, digest)) != stamp:
                if file_hash(path) != digest:
                    raise RuntimeError('原图内容已变化，请核对来源后继续')
                self._verified_files[(path, digest)] = stamp

    def image(self, image_id, thumbnail=False):
        self._load()
        if not re.fullmatch('[0-9a-f]{64}', image_id) or image_id not in self._by_id:
            raise FileNotFoundError('图片不在本次人工图库')
        item = self._by_id[image_id]
        if not thumbnail:
            path = self._safe_path(item['source_path'], self.root / 'data/trend_data/images')
            self._verify_file(path, image_id)
            return path
        target = self.folder / 'thumbnails' / (image_id + '.webp')
        if not target.is_file():
            snapshot = self._safe_path(item['snapshot_path'], self.root / 'data/result/trend_quality/batches')
            self._verify_file(snapshot, item['input_image_sha256'])
            target.parent.mkdir(exist_ok=True)
            temporary = target.with_name('.' + uuid4().hex + '.tmp')
            try:
                with Image.open(snapshot) as source:
                    image = ImageOps.exif_transpose(source)
                    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
                    if image.mode not in {'RGB', 'RGBA'}:
                        image = image.convert('RGBA')
                    image.save(temporary, format='WEBP', quality=85)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def download(self, selection='PASS'):
        state = self._state()
        images = [dict(image, manual_decision=state['labels'].get(image['id'], {}).get('decision'),
                       manual_updated_at=state['labels'].get(image['id'], {}).get('updated_at'))
                  for image in self._catalog['images']
                  if selection == 'all' or state['labels'].get(image['id'], {}).get('decision') == selection]
        return {'schema_version': 'prism.quality_manual_export.v1', 'collection_id': COLLECTION_ID,
                'revision': state['revision'], 'exported_at': timestamp(), 'selection': selection,
                'counts': self._counts(state), 'source_batches': self._catalog['source_batches'],
                'production_admission': False, 'images': images}
