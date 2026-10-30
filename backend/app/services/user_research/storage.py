"""PPT 提取工作台的本地存储；旧分析和图片库不作为 PPT 回答混入。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

PROJECT = Path(__file__).resolve().parents[4]
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
SUMMARY_FIELDS = ('id', 'name', 'profile', 'sourceFile', 'sourceSha256', 'recordCount',
                  'enjoyCount', 'dislikeCount', 'referenceCount', 'missingImageCount', 'status', 'createdAt')


def _id(value: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError('非法标识符')
    return value


def _filename(value: Any) -> str:
    return str(value or '').replace('\\', '/').rsplit('/', 1)[-1]


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _atomic(path: Path, value: Any) -> None:
    """同目录临时文件原子替换，避免读取半写入 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _counts(detail: dict) -> None:
    images = detail['images']
    detail.update(recordCount=len(detail['records']),
                  enjoyCount=sum(x['emotion'] == 'ENJOY' for x in images),
                  dislikeCount=sum(x['emotion'] == 'DISLIKE' for x in images),
                  referenceCount=sum(x['emotion'] == 'REFERENCE' for x in images),
                  missingImageCount=sum(x.get('url') is None for x in images))


class ResearchStore:
    """同步存储接口；API 在工作线程中调用，返回独立的 camelCase DTO。"""

    def __init__(self, root: Path | str | None = None, seed_file: Path | str | None = None,
                 image_root: Path | str | None = None):
        self.root = Path(root or PROJECT / 'data/result/user_research_intake').resolve()
        self.seed_file = Path(seed_file or PROJECT / 'data/userreseach_data/users_selected_5.json').resolve()
        self.image_root = Path(image_root or self.seed_file.parent).resolve()
        self._lock = threading.RLock()
        self._seed_stamp = None
        self._seed_users: dict[str, dict] = {}
        self._seed_assets: dict[str, dict[str, Path]] = {}
        self._seed_copies: dict[str, dict[str, dict]] = {}

    def _run(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError('非法任务标识符')
        path = (self.root / run_id).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('任务路径越界')
        return path

    def _asset(self, raw: Path | str, *, seed: bool = False) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = (self.image_root if seed else self.root) / path
        path = path.resolve()
        roots = (self.image_root,) if seed else (self.root, self.image_root)
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError('图片路径越界')
        return path

    def _load_seed(self) -> None:
        if not self.seed_file.exists():
            self._seed_users, self._seed_assets = {}, {}
            return
        stat = self.seed_file.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._seed_stamp:
            return
        users, assets, copies = {}, {}, {}
        for user in _read(self.seed_file).get('users', []):
            uid = _id(str(user['id']))
            detail, paths = self._adapt_seed(user)
            users[uid], assets[uid] = detail, paths
            copies[uid] = self._linked_copies(user)
        self._seed_users, self._seed_assets, self._seed_stamp = users, assets, stamp
        self._seed_copies = copies

    def _linked_copies(self, user: dict) -> dict[str, dict]:
        """只接受原记录显式 ppt_evidence 关联；同编号本身不能证明是同图。"""
        catalog_file = self.image_root / 'images.json'
        if not catalog_file.is_file():
            return {}
        catalog = {x['id']: x for x in _read(catalog_file).get('images', [])}
        originals = {x['image_id']: x for x in user.get('ppt_images', [])}
        candidates: dict[str, dict[str, dict]] = {}
        for preference in user.get('image_preferences', []):
            source = catalog.get(preference.get('image_id'), {})
            if not preference.get('local_path') or source.get('local_path') != preference['local_path']:
                continue
            for evidence in preference.get('ppt_evidence', []):
                original = originals.get(evidence.get('image_id'))
                if not original or evidence.get('evidence_scope') != 'exact':
                    continue
                if preference.get('ref_pic_code') != original.get('ref_pic_code') or preference.get('emotion_tag') != original.get('emotion_tag'):
                    continue
                fields = ('local_path', 'source_file', 'source_slide', 'source_question_id')
                if any(evidence.get(key) is None or evidence[key] != original.get(key) for key in fields):
                    continue
                try:
                    path = self._asset(preference['local_path'], seed=True)
                except ValueError:
                    continue
                if not path.is_file():
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != source.get('sha256'):
                    continue
                candidates.setdefault(original['image_id'], {})[str(path)] = dict(
                    localPath=preference['local_path'], sha256=digest,
                    originalSha256=original.get('sha256'), sourceImageId=preference.get('image_id'),
                    sourceRecordId=preference.get('source_id'), evidence=copy.deepcopy(evidence),
                    label='原调研关联副本（非 PPT 提取原件）')
        # 多个不同文件的关联存在歧义时保留缺图，不任意选第一个。
        return {iid: next(iter(paths.values())) for iid, paths in candidates.items() if len(paths) == 1}

    def _copy_path(self, user_id: str, image_id: str) -> Path | None:
        """副本与冻结的本次关联字节一致才供图，仍限制在研究素材目录内。"""
        entry = self._seed_copies.get(user_id, {}).get(image_id)
        if not entry:
            return None
        try:
            path = self._asset(entry['localPath'], seed=True)
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']:
                return path
        except (ValueError, OSError):
            pass
        return None

    def _adapt_seed(self, user: dict) -> tuple[dict, dict[str, Path]]:
        uid = str(user['id'])
        meta = user.get('ppt_supplement', {})
        filename = _filename(meta.get('source_file'))
        warnings = []
        records, original_records = [], []
        for section in ('aesthetic_research', 'demand_research'):
            for row in user.get(section, []):
                if row.get('source_type') != 'ppt_supplement':
                    continue
                rid = str(row['id'])
                topic = next((str(row[key]).strip() for key in ('scenario_type', 'question_type')
                              if row.get(key) and str(row[key]).strip()), section)
                records.append(dict(id=rid, section=topic, question=row.get('question', ''),
                    answer=row.get('ai_analysis', row.get('ai_index', row.get('answer', ''))),
                    sourceSlide=row.get('source_slide'), sourceFile=_filename(row.get('source_file')),
                    imageIds=[], sourceKind='ppt'))
                original_records.append(row)
        images, paths, by_original = [], {}, {}

        def add_image(raw: dict, *, question: str | None = None, missing: bool = False) -> str:
            original = str(raw.get('image_id') or '')
            base = original or 'missing_' + hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:20]
            base = _id(base)
            iid = base
            # 同一字节的多个态度/题目出现关系必须独立保存，不能用 code 覆盖。
            while any(x['id'] == iid for x in images):
                iid = f'{base}_{len(images)}'
            emotion = raw.get('emotion_tag', 'REFERENCE')
            if emotion not in ('ENJOY', 'DISLIKE', 'REFERENCE'):
                warnings.append('部分图片情绪未明确，已保留为 REFERENCE。')
                emotion = 'REFERENCE'
            path = None
            if raw.get('local_path') and not missing:
                try:
                    candidate = self._asset(raw['local_path'], seed=True)
                    paths[iid] = candidate
                    if candidate.is_file():
                        path = candidate
                except ValueError:
                    warnings.append('部分图片路径超出资料目录，未提供访问。')
            image = dict(id=iid, code=raw.get('ref_pic_code', raw.get('code', '')), emotion=emotion,
                url=f'/api/v1/user-research/assets/{uid}/{iid}' if path else None,
                sourceSlide=raw.get('source_slide'), questionId=question or raw.get('source_question_id'),
                description=raw.get('description_zh', ''), evidenceScope=raw.get('evidence_scope', 'unknown'),
                status=raw.get('status', 'extracted') if path else 'missing_source_image')
            images.append(image)
            if path:
                paths[iid] = path
            if original:
                by_original.setdefault(original, []).append(image)
            return iid

        for raw in user.get('ppt_images', []):
            add_image(raw)
        for record, raw_record in zip(records, original_records):
            linked = [x['id'] for x in images if x['questionId'] == record['id']]
            for link in raw_record.get('ref_pic_links', []):
                if link.get('status') == 'missing_source_image':
                    declared = [x['id'] for x in images if x['questionId'] == record['id']
                                and x['code'] == link.get('code') and x['emotion'] == link.get('emotion_tag', 'REFERENCE')
                                and x['status'] == 'missing_source_image']
                    linked.extend(declared or [add_image({**link, 'source_slide': link.get('source_slide', record['sourceSlide'])}, question=record['id'], missing=True)])
                for original in link.get('image_ids', []):
                    matches = by_original.get(original, [])
                    emotion = link.get('emotion_tag')
                    matching = [x for x in matches if (not emotion or x['emotion'] == emotion) and x['questionId'] in (None, record['id'])]
                    if matching:
                        linked.extend(x['id'] for x in matching)
                    elif matches:
                        # 明确不同态度的链接复制关系，而非覆盖另一道题或原图片态度。
                        source = next(x for x in user['ppt_images'] if str(x['image_id']) == original)
                        linked.append(add_image({**source, 'emotion_tag': emotion or source.get('emotion_tag', 'REFERENCE')}, question=record['id']))
                    else:
                        linked.append(add_image({**link, 'image_id': original}, question=record['id'], missing=True))
            record['imageIds'] = list(dict.fromkeys(linked))
        if any(x['url'] is None for x in images):
            warnings.append('有已声明选择未提供原图或本地图片缺失；缺图态度已保留。')
        provenance = dict(sourceKind='ppt', textKind='PPT填写内容的既有翻译补录，并非逐字访谈',
            sourceFile=filename, sourceSha256=meta.get('source_sha256'), sourceLanguage=meta.get('source_language'),
            translatedTo=meta.get('translated_to'), addedAt=meta.get('added_at'), updatedAt=meta.get('updated_at'))
        # 迁移后仅在项目 ref 内按文件名寻找，必须校验原哈希才标记已核实。
        expected = meta.get('source_sha256')
        ref = PROJECT / 'ref'
        candidates = list(ref.rglob(filename)) if filename and ref.exists() else []
        verified = any(p.is_file() and p.resolve().is_relative_to(ref.resolve()) and hashlib.sha256(p.read_bytes()).hexdigest() == expected for p in candidates)
        provenance['sourceVerified'] = verified
        if not verified:
            warnings.append('原 PPT 当前未通过来源哈希核实；展示已保存的翻译文本和提取图片。')
        detail = dict(id=uid, name=user.get('name', uid), profile=copy.deepcopy(user.get('profile', {})),
            sourceFile=filename, sourceSha256=expected, records=records, images=images, provenance=provenance,
            warnings=list(dict.fromkeys(warnings)), status='ready', createdAt=meta.get('added_at'))
        _counts(detail)
        return detail, paths

    def list_users(self) -> list[dict]:
        """实时合并五用户种子及上传结果，不写回原始 JSON。"""
        with self._lock:
            self._load_seed()
            users = [self.get_user(uid) for uid in self._seed_users]
            if self.root.exists():
                for path in sorted(self.root.glob('*/user.json')):
                    if RUN_ID.fullmatch(path.parent.name):
                        users.append(self.get_user('import_' + path.parent.name))
            return copy.deepcopy([{key: u.get(key) for key in SUMMARY_FIELDS} for u in users])

    def get_user(self, user_id: str) -> dict:
        """取完整文本和图片出现关系；未知用户抛 FileNotFoundError。"""
        _id(user_id)
        with self._lock:
            self._load_seed()
            is_seed = user_id in self._seed_users
            if is_seed:
                value = copy.deepcopy(self._seed_users[user_id])
                paths = self._seed_assets[user_id]
            else:
                if not user_id.startswith('import_'):
                    raise FileNotFoundError('用户不存在')
                run = self._run(user_id[7:])
                value = _read(run / 'user.json')
                paths = _read(run / 'assets.json') if (run / 'assets.json').exists() else {}
            # 种子和上传结果均实时核实文件，删除或符号链接替换不得继续供图。
            # 只调整返回 DTO，不覆盖历史确认状态与持久化来源记录。
            for image in value['images']:
                raw = paths.get(image['id'])
                try:
                    available = bool(raw and self._asset(raw, seed=is_seed).is_file())
                except ValueError:
                    available = False
                if not available and is_seed and self._copy_path(user_id, image['id']):
                    available = True
                    image['status'] = 'linked_source_copy'
                    image['recovery'] = copy.deepcopy(self._seed_copies[user_id][image['id']])
                if available:
                    image['url'] = f'/api/v1/user-research/assets/{user_id}/{image["id"]}'
                    if image['status'] == 'missing_source_image':
                        image['status'] = 'extracted'
                else:
                    image['url'] = None
                    image['status'] = 'missing_source_image'
            if any(x.get('recovery') for x in value['images']):
                value['warnings'].append('部分缺图已用原记录明确关联的调研图库副本补充展示，PPT 原件仍缺失；图片卡片已注明。')
            _counts(value)
            warning = '有已声明选择未提供原图或本地图片缺失；缺图态度已保留。'
            value.setdefault('warnings', [])
            if value['missingImageCount']:
                if warning not in value['warnings']:
                    value['warnings'].append(warning)
            elif warning in value['warnings']:
                value['warnings'].remove(warning)
            return value

    def asset_path(self, user_id: str, image_id: str) -> Path:
        """仅按已登记的图片 ID 取文件；不接受任意文件名或外部路径。"""
        _id(user_id); _id(image_id)
        with self._lock:
            detail = self.get_user(user_id)
            if not any(x['id'] == image_id and x.get('url') for x in detail['images']):
                raise FileNotFoundError('图片不存在')
            if user_id in self._seed_users:
                selected = next(x for x in detail['images'] if x['id'] == image_id)
                if selected.get('recovery'):
                    path = self._copy_path(user_id, image_id)
                    if path is None:
                        raise FileNotFoundError('关联副本缺失或内容变更')
                    return path
                raw = self._seed_assets[user_id].get(image_id)
            else:
                raw = _read(self._run(user_id[7:]) / 'assets.json').get(image_id)
            if not raw:
                raise FileNotFoundError('图片源文件缺失')
            path = self._asset(raw, seed=user_id in self._seed_users)
            if not path.is_file():
                raise FileNotFoundError('图片源文件缺失')
            return path

    def save_user(self, detail: dict, asset_paths: dict[str, Path]) -> None:
        """首次导入强制人工待确认；后续 ready 由 API 明确确认后保存。"""
        value = copy.deepcopy(detail)
        uid = _id(value['id'])
        if not uid.startswith('import_'):
            raise ValueError('已有种子用户不可覆盖')
        run = self._run(uid[7:])
        with self._lock:
            registered = {}
            image_ids = [_id(x['id']) for x in value['images']]
            if len(set(image_ids)) != len(image_ids):
                raise ValueError('图片出现关系 ID 重复')
            if set(asset_paths) - set(image_ids):
                raise ValueError('图片路径未关联图片记录')
            for iid, path in asset_paths.items():
                resolved = self._asset(path)
                if not resolved.is_file():
                    raise FileNotFoundError('图片源文件缺失')
                registered[iid] = str(resolved)
            for image in value['images']:
                if image['emotion'] not in ('ENJOY', 'DISLIKE', 'REFERENCE'):
                    raise ValueError('图片情绪不明确')
                image['url'] = f'/api/v1/user-research/assets/{uid}/{image["id"]}' if image['id'] in registered else None
                if image['url'] is None:
                    image['status'] = 'missing_source_image'
            for record in value['records']:
                if set(record['imageIds']) - set(image_ids):
                    raise ValueError('问题引用未知图片')
                record['sourceFile'] = _filename(record.get('sourceFile'))
            value['sourceFile'] = _filename(value.get('sourceFile'))
            value['status'] = value.get('status', 'needs_review') if (run / 'user.json').exists() else 'needs_review'
            if value['status'] not in ('ready', 'needs_review'):
                raise ValueError('非法用户状态')
            _counts(value)
            _atomic(run / 'assets.json', registered)
            _atomic(run / 'user.json', value)

    def list_tasks(self) -> list[dict]:
        """读取持久化任务，不在列表操作时启动或重跑模型。"""
        with self._lock:
            return [self.get_task(p.parent.name) for p in sorted(self.root.glob('*/task.json')) if RUN_ID.fullmatch(p.parent.name)]

    def get_task(self, task_id: str) -> dict:
        """未知任务抛 FileNotFoundError。"""
        with self._lock:
            return _read(self._run(task_id) / 'task.json')

    def save_task(self, task: dict) -> None:
        """以任务 UUID 原子保存状态。"""
        with self._lock:
            _atomic(self._run(task['id']) / 'task.json', task)
